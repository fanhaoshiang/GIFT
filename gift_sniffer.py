# -*- coding: utf-8 -*-
"""
TikTok Gift Sniffer GUI（專用設定檔，不共用 gift_map.json）
- 在 GUI 輸入 EulerStream API Key（保存到當前資料夾的 gift_sniffer.json）
- 一次輸入一個 @username 或完整 TikTok 直播網址加入清單；可開始/停止/刪除
- 可同時監聽多個目標，每個目標寫入 gifts_seen_<username>.json
- 支援匯出 gift_map_template.json（包含 gid/kw/path）

安裝：
  pip install PySide6 TikTokLive

啟動：
  python gift_sniffer.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from concurrent.futures import TimeoutError
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple

# PySide6
from PySide6.QtCore import Qt, QThread, Signal, Slot, QByteArray
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QHeaderView,
    QGroupBox,
    QAbstractItemView,
)

# TikTokLive（以防環境缺模組，做防呆）
try:
    from TikTokLive import TikTokLiveClient  # type: ignore
    from TikTokLive.events import GiftEvent, ConnectEvent, DisconnectEvent  # type: ignore
except Exception:
    TikTokLiveClient = None  # type: ignore
    GiftEvent = None  # type: ignore
    ConnectEvent = None  # type: ignore
    DisconnectEvent = None  # type: ignore


# 依照你環境（6.6.1）的檔案清單，簽名器位於 TikTokLive.client.web.web_signer
# 為了相容其他安裝，動態解析簽名器（找不到就提示）
def resolve_euler_signer() -> Tuple[Optional[type], Optional[str]]:
    try:
        from importlib import import_module
    except Exception:
        return None, None

    candidates = (
        "TikTokLive.client.web.web_signer",  # 你的環境有這個
        "TikTokLive.client.sign",
        "TikTokLive.client.web.sign",
        "TikTokLive.client.signer",
    )
    for mod in candidates:
        try:
            m = import_module(mod)
            if hasattr(m, "TikTokSigner"):
                return getattr(m, "TikTokSigner"), mod
        except Exception:
            continue
    return None, None


# ------------ 工具/存檔 ------------
CFG_FILE = os.path.join(os.getcwd(), "gift_sniffer.json")


def load_config() -> Dict[str, Any]:
    try:
        if os.path.exists(CFG_FILE):
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def parse_username(url_or_username: str) -> Optional[str]:
    """
    接受完整網址/@username/username，回傳 username
    支援：
      - https://www.tiktok.com/@name/live
      - @name
      - name
    """
    s = (url_or_username or "").strip()
    if not s:
        return None
    m = re.search(r"tiktok\.com/@([^/?]+)", s, re.IGNORECASE)
    if m:
        return m.group(1)
    if s.startswith("@"):
        return s[1:]
    # 去除可能的尾部路徑
    s = s.split("/")[0]
    return s or None


@dataclass
class Target:
    username: str
    out_path: str
    status: str = "就緒"
    total_seen: int = 0


class GiftSnifferWorker(QThread):
    # 帶 username 的訊號，方便對應行
    status = Signal(str, str)     # username, message
    error = Signal(str, str)      # username, message
    gift_seen = Signal(str, dict) # username, payload
    finished_ok = Signal(str)     # username

    def __init__(self, username: str, out_path: str, api_key: str):
        super().__init__()
        self.username = username
        self.out_path = out_path
        self.api_key = api_key
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[TikTokLiveClient] = None
        self._seen: Dict[str, Dict[str, Any]] = {}
        self._stop_requested = False

        # 載入既有 gifts_seen 檔（若存在）
        if os.path.exists(self.out_path):
            try:
                with open(self.out_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._seen = data
            except Exception:
                self._seen = {}

    def _save_seen(self):
        try:
            os.makedirs(os.path.dirname(self.out_path) or ".", exist_ok=True)
            with open(self.out_path, "w", encoding="utf-8") as f:
                json.dump(self._seen, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.error.emit(self.username, f"無法寫入 {self.out_path}: {e}")

    def stop(self):
        self._stop_requested = True
        if self._client and self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._client.stop(), self._loop)
                future.result(timeout=5)  # 等待停止完成，最多5秒
            except TimeoutError:
                self.error.emit(self.username, "停止操作超時")
            except Exception as e:
                self.error.emit(self.username, f"停止時發生錯誤: {e}")

    def _update_seen(self, gift_id: str, gift_name: str, count: int):
        key = gift_id or gift_name.lower()
        if not key:
            return
        it = self._seen.get(key) or {
            "gift_id": gift_id,
            "gift_name": gift_name,
            "count_total": 0,
            "first_seen_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        it["gift_id"] = it.get("gift_id") or gift_id
        it["gift_name"] = it.get("gift_name") or gift_name
        it["count_total"] = int(it.get("count_total", 0)) + max(1, int(count))
        it["last_seen_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._seen[key] = it
        self._save_seen()
        self.gift_seen.emit(self.username, it)

    def run(self):
        # 基本檢查
        if TikTokLiveClient is None:
            self.error.emit(self.username, "未安裝 TikTokLive：請先 pip install TikTokLive")
            return

        SignerClass, mod = resolve_euler_signer()
        if SignerClass is None:
            self.error.emit(self.username, "找不到 TikTokSigner，請更新 TikTokLive（或回報簽名器模組路徑）")
            return

        if not self.api_key:
            self.error.emit(self.username, "未提供 API Key，無法連線簽名服務")
            return

        try:
            # 在這個 Thread 內建立自己的 asyncio 事件圈
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop

            signer_kwargs = {"sign_api_key": self.api_key}
            web_kwargs = {"signer_kwargs": signer_kwargs}
            client = TikTokLiveClient(unique_id=self.username, web_kwargs=web_kwargs)
            self._client = client

            @client.on(ConnectEvent)
            async def on_connect(_: ConnectEvent):
                # 可在此印出實際使用的簽名器模組，便於除錯
                self.status.emit(self.username, f"已連線 @{self.username}（signer: {mod}）")

            @client.on(DisconnectEvent)
            async def on_disconnect(_: DisconnectEvent):
                self.status.emit(self.username, "已斷線")

            @client.on(GiftEvent)
            async def on_gift(event: GiftEvent):
                try:
                    gid = str(getattr(event.gift, "id", "") or getattr(event.gift, "gift_id", "") or "")
                    gname = str(getattr(event.gift, "name", "") or getattr(event.gift, "gift_name", "") or "")
                    cnt = int(getattr(event.gift, "repeat_count", 1) or 1)
                    self._update_seen(gid, gname, cnt)
                except Exception as ee:
                    self.error.emit(self.username, f"解析禮物事件失敗: {ee}")

            self.status.emit(self.username, f"連線 @{self.username} 中…")
            client.run()  # 阻塞直到 stop()
            self.finished_ok.emit(self.username)
        except Exception as e:
            self.error.emit(self.username, f"執行錯誤：{e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok Gift Sniffer GUI")
        self.resize(980, 620)

        self.targets: List[Target] = []
        self.row_by_username: Dict[str, int] = {}
        self.workers: Dict[str, GiftSnifferWorker] = {}
        self.seen_cache_by_user: Dict[str, Dict[str, Dict[str, Any]]] = {}

        w = QWidget()
        root = QVBoxLayout(w)

        # API Key 區塊（只存到 gift_sniffer.json）
        box_api = QGroupBox("EulerStream API")
        api_layout = QHBoxLayout(box_api)
        api_layout.addWidget(QLabel("API Key："))
        self.api_edit = QLineEdit()
        self.api_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_edit.setPlaceholderText("輸入在 eulerstream.com 申請的 API Key（儲存於 gift_sniffer.json）")
        btn_toggle = QPushButton("顯示")
        def toggle_echo():
            if self.api_edit.echoMode() == QLineEdit.EchoMode.Password:
                self.api_edit.setEchoMode(QLineEdit.EchoMode.Normal)
                btn_toggle.setText("隱藏")
            else:
                self.api_edit.setEchoMode(QLineEdit.EchoMode.Password)
                btn_toggle.setText("顯示")
        btn_toggle.clicked.connect(toggle_echo)
        api_layout.addWidget(self.api_edit, 1)
        api_layout.addWidget(btn_toggle)
        root.addWidget(box_api)

        # 單筆加入區塊
        box_add = QGroupBox("新增目標（一次輸入一個）")
        add_layout = QHBoxLayout(box_add)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("輸入 @username 或完整網址，按『加入』")
        self.btn_add_one = QPushButton("加入")
        add_layout.addWidget(QLabel("目標："))
        add_layout.addWidget(self.target_input, 1)
        add_layout.addWidget(self.btn_add_one)
        root.addWidget(box_add)

        # 清單 + 控制
        box_targets = QGroupBox("監聽清單")
        v_targets = QVBoxLayout(box_targets)

        ctl = QHBoxLayout()
        self.btn_start_sel = QPushButton("開始（選取）")
        self.btn_stop_sel = QPushButton("停止（選取）")
        self.btn_start_all = QPushButton("全部開始")
        self.btn_stop_all = QPushButton("全部停止")
        self.btn_remove_sel = QPushButton("刪除選取")
        self.btn_export = QPushButton("匯出映射模板")
        ctl.addWidget(self.btn_start_sel)
        ctl.addWidget(self.btn_stop_sel)
        ctl.addWidget(self.btn_start_all)
        ctl.addWidget(self.btn_stop_all)
        ctl.addStretch(1)
        ctl.addWidget(self.btn_remove_sel)
        ctl.addWidget(self.btn_export)
        v_targets.addLayout(ctl)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["username", "out_file", "status", "total_seen", "last_update"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        v_targets.addWidget(self.table)

        self.status_label = QLabel("就緒")
        v_targets.addWidget(self.status_label)
        root.addWidget(box_targets)

        self.setCentralWidget(w)

        # 事件綁定
        self.btn_add_one.clicked.connect(self.on_add_one)
        self.btn_remove_sel.clicked.connect(self.on_remove_selected)
        self.btn_start_sel.clicked.connect(lambda: self.start_selected(start_all=False))
        self.btn_stop_sel.clicked.connect(lambda: self.stop_selected(stop_all=False))
        self.btn_start_all.clicked.connect(lambda: self.start_selected(start_all=True))
        self.btn_stop_all.clicked.connect(lambda: self.stop_selected(stop_all=True))
        self.btn_export.clicked.connect(self.export_template_all)

        # 載入設定
        self.load_ui_state()

        if TikTokLiveClient is None:
            QMessageBox.critical(self, "缺少模組", "未找到 TikTokLive 模組。\n請先執行 `pip install TikTokLive` 安裝。")
            self.btn_add_one.setEnabled(False)
            self.btn_start_sel.setEnabled(False)
            self.btn_start_all.setEnabled(False)
            self.target_input.setEnabled(False)
            self.status_label.setText("錯誤：缺少 TikTokLive 模組")

    # ---------- 設定保存/恢復 ----------
    def load_ui_state(self):
        cfg = load_config()
        self.api_edit.setText(cfg.get("api_key", ""))

        geom_b64 = cfg.get("geometry_b64")
        if geom_b64:
            try:
                ba = QByteArray.fromBase64(geom_b64.encode("ascii"))
                self.restoreGeometry(ba)
            except Exception:
                pass

        for t in cfg.get("targets", []):
            username = t.get("username", "")
            out_path = t.get("out_path", "") or os.path.join(os.getcwd(), f"gifts_seen_{username}.json")
            if username:
                self._append_target(username, out_path)

    def save_ui_state(self):
        cfg = {
            "api_key": self.api_edit.text().strip(),
            "geometry_b64": bytes(self.saveGeometry().toBase64()).decode("ascii"),
            "targets": [{"username": t.username, "out_path": t.out_path} for t in self.targets],
        }
        save_config(cfg)

    def closeEvent(self, ev):
        # 停止所有 worker
        for w in list(self.workers.values()):
            try:
                w.stop()
                w.wait(3000)
            except Exception:
                pass
        self.save_ui_state()
        return super().closeEvent(ev)

    # ---------- 清單維護 ----------
    @Slot()
    def on_add_one(self):
        token = self.target_input.text().strip()
        if not token:
            QMessageBox.information(self, "提示", "請輸入 @username 或完整網址")
            return
        username = parse_username(token)
        if not username:
            QMessageBox.warning(self, "格式錯誤", "無法解析使用者名稱，請確認輸入")
            return
        if username in self.row_by_username:
            QMessageBox.information(self, "已存在", f"{username} 已在清單中")
            return
        out_file = os.path.join(os.getcwd(), f"gifts_seen_{username}.json")
        self._append_target(username, out_file)
        self.target_input.clear()
        self.status_label.setText(f"已加入：{username}")
        self.save_ui_state()

    def _append_target(self, username: str, out_path: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(username))
        self.table.setItem(row, 1, QTableWidgetItem(out_path))
        self.table.setItem(row, 2, QTableWidgetItem("就緒"))
        self.table.setItem(row, 3, QTableWidgetItem("0"))
        self.table.setItem(row, 4, QTableWidgetItem("-"))
        self.targets.append(Target(username=username, out_path=out_path))
        self.row_by_username[username] = row

        # 預載既有檔，填 total
        try:
            if os.path.exists(out_path):
                data = json.load(open(out_path, "r", encoding="utf-8"))
                if isinstance(data, dict):
                    self.seen_cache_by_user[username] = data
                    total = sum(int(v.get("count_total", 0)) for v in data.values())
                    self.table.item(row, 3).setText(str(total))
        except Exception:
            pass

    @Slot()
    def on_remove_selected(self):
        sel_rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not sel_rows:
            QMessageBox.information(self, "提示", "請先選取要刪除的列")
            return
        removed = 0
        for row in sel_rows:
            username = self.table.item(row, 0).text()
            # 若在運行中，先停止
            if username in self.workers:
                self._stop_worker_for(username)
            # 移除列/資料
            self.table.removeRow(row)
            self.row_by_username.pop(username, None)
            self.targets = [t for t in self.targets if t.username != username]
            self.seen_cache_by_user.pop(username, None)
            removed += 1
        if removed:
            # 重建索引
            self.row_by_username = {self.table.item(r, 0).text(): r for r in range(self.table.rowCount())}
        self.status_label.setText(f"已刪除 {removed} 個目標")
        self.save_ui_state()
    # ---------- 啟停 ----------
    def _start_worker_for(self, username: str, out_path: str):
        if username in self.workers:
            return
        api_key = self.api_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "缺少 API Key", "請先在上方輸入 EulerStream API Key（儲存於 gift_sniffer.json）")
            return
        worker = GiftSnifferWorker(username=username, out_path=out_path, api_key=api_key)
        worker.status.connect(self.on_worker_status)
        worker.error.connect(self.on_worker_error)
        worker.gift_seen.connect(self.on_worker_gift_seen)
        worker.finished_ok.connect(self.on_worker_finished)
        self.workers[username] = worker
        self._set_row_status(username, "啟動中…")
        worker.start()

    def _stop_worker_for(self, username: str):
        w = self.workers.get(username)
        if not w:
            return
        try:
            self._set_row_status(username, "停止中…")
            w.stop()
            w.wait(3000)
        except Exception:
            pass
        finally:
            self.workers.pop(username, None)
            self._set_row_status(username, "已停止")

    def selected_usernames(self) -> List[str]:
        return [self.table.item(r, 0).text() for r in sorted({i.row() for i in self.table.selectedIndexes()})]

    def start_selected(self, start_all: bool = False):
        rows = range(self.table.rowCount()) if start_all else sorted({i.row() for i in self.table.selectedIndexes()})
        started = 0
        for r in rows:
            if r < 0:
                continue
            username = self.table.item(r, 0).text()
            out_path = self.table.item(r, 1).text()
            if username and username not in self.workers:
                self._start_worker_for(username, out_path)
                started += 1
        self.status_label.setText(f"已啟動 {started} 個目標")

    def stop_selected(self, stop_all: bool = False):
        usernames = [self.table.item(r, 0).text() for r in (range(self.table.rowCount()) if stop_all else sorted({i.row() for i in self.table.selectedIndexes()}))]
        stopped = 0
        for u in usernames:
            if u in self.workers:
                self._stop_worker_for(u)
                stopped += 1
        self.status_label.setText(f"已停止 {stopped} 個目標")

    # ---------- Worker 回報 ----------
    @Slot(str, str)
    def on_worker_status(self, username: str, msg: str):
        self._set_row_status(username, msg)

    @Slot(str, str)
    def on_worker_error(self, username: str, msg: str):
        self._set_row_status(username, f"錯誤：{msg}")
        if "403" in msg or "API key" in msg:
            self.status_label.setText("簽名服務拒絕：請確認 EulerStream API Key 是否正確/有效")

    @Slot(str)
    def on_worker_finished(self, username: str):
        self._set_row_status(username, "已停止")
        self.workers.pop(username, None)

    @Slot(str, dict)
    def on_worker_gift_seen(self, username: str, it: Dict[str, Any]):
        row = self.row_by_username.get(username, -1)
        if row < 0:
            return
        cache = self.seen_cache_by_user.setdefault(username, {})
        key = (it.get("gift_id") or it.get("gift_name", "").lower() or "")
        if key:
            cache[key] = it
        total = sum(int(v.get("count_total", 0)) for v in cache.values())
        self.table.item(row, 3).setText(str(total))
        self.table.item(row, 4).setText(it.get("last_seen_at", ""))

    def _set_row_status(self, username: str, text: str):
        row = self.row_by_username.get(username, -1)
        if row >= 0:
            self.table.item(row, 2).setText(text)

    # ---------- 匯出模板 ----------
    @Slot()
    def export_template_all(self):
        rows: List[Dict[str, str]] = []
        for cache in self.seen_cache_by_user.values():
            for v in cache.values():
                rows.append({
                    "gid": v.get("gift_id", "") or "",
                    "kw": v.get("gift_name", "") or "",
                    "path": ""
                })
        if not rows:
            QMessageBox.information(self, "提示", "目前尚無禮物資料可匯出。請先開始監聽，或確認 gifts_seen_xxx.json 已產生。")
            return
        out, _ = QFileDialog.getSaveFileName(self, "匯出映射模板", os.path.join(os.getcwd(), "gift_map_template.json"), "JSON (*.json)")
        if not out:
            return
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "完成", f"已匯出 {len(rows)} 筆到：\n{out}")
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"寫入失敗：{e}")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()

    # 從 gift_sniffer.json 還原視窗位置
    cfg = load_config()
    geom_b64 = cfg.get("geometry_b64")
    if geom_b64:
        try:
            ba = QByteArray.fromBase64(geom_b64.encode("ascii"))
            win.restoreGeometry(ba)
        except Exception:
            pass

    win.show()
    rc = app.exec()

    # 關閉時保存視窗位置
    try:
        cfg = load_config()
        cfg["geometry_b64"] = bytes(win.saveGeometry().toBase64()).decode("ascii")
        save_config(cfg)
    except Exception:
        pass

    sys.exit(rc)


if __name__ == "__main__":
    main()
