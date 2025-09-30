# -*- coding: utf-8 -*-
"""
Overlay UltraLite - V9.51-DedupeFix (Fixes event deduplication attribute error)
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from collections import deque
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QRect, QRectF,
                            QSize, QTimer, Qt, Signal)
from PySide6.QtGui import (QColor, QCursor, QImage, QMouseEvent, QPaintEvent,
                           QPainter, QPixmap)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QRadioButton, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget, QSlider, QSpinBox
)

from speech_engine import SpeechEngine
from ui_components import GiftListDialog, GameMenuContainer, MenuItemWidget, TriggerEditDialog
from trigger_manager import TriggerManager
from data_managers import LayoutsManager, SettingsManager, LibraryManager, ThemeManager

# --- Pillow 依賴 (用於 WebP 支援) ---
try:
    from PIL import Image
    _HAS_PILLOW = True
except ImportError:
    Image = None
    _HAS_PILLOW = False

# --- TikTokLiveClient 依賴 ---
try:
    from TikTokLive import TikTokLiveClient
    from TikTokLive.client.web.web_settings import WebDefaults
    from TikTokLive.events import (CommentEvent, ConnectEvent, DisconnectEvent,
                                   FollowEvent, GiftEvent, JoinEvent,
                                   LikeEvent)
    _HAS_TIKTOK_LIVE = True
except ImportError:
    TikTokLiveClient = None
    WebDefaults = None
    CommentEvent, ConnectEvent, DisconnectEvent, GiftEvent, LikeEvent, JoinEvent, FollowEvent = (None,) * 7
    _HAS_TIKTOK_LIVE = False

# --- OpenCV 依賴 ---
try:
    import cv2
except ImportError:
    cv2 = None

# --- MPV 依賴 ---
try:
    import mpv
    _HAS_MPV = True
except ImportError:
    mpv = None
    _HAS_MPV = False

# --- pyttsx3 依賴 ---
try:
    import pyttsx3
    _HAS_TTS = True
except ImportError:
    pyttsx3 = None
    _HAS_TTS = False

# --- 處理打包路徑的核心程式碼 ---
if getattr(sys, 'frozen', False):
    # 如果是在打包後的環境中運行
    application_path = os.path.dirname(sys.executable)
else:
    # 如果是在正常的 Python 環境中運行
    application_path = os.path.dirname(__file__)
# --- 處理結束 ---


# ==================== 型別宣告 & 資料類別 ====================
Layout = dict[str, int]
LayoutsData = dict[str, dict[str, Layout]]
GiftMapItem = Dict[str, Any]
GiftInfo = Dict[str, str]

# ==================== mpv 可用性偵測 & 精準例外 =========================
MPV_ERRORS: tuple[type, ...] = ()
MPV_CALL_ERRORS: tuple[type, ...] = ()
if _HAS_MPV:
    MPV_ERRORS = tuple([
        exc for name in ("Error", "MPVError")
        if (exc := getattr(mpv, name, None)) and isinstance(exc, type)
    ])
    MPV_CALL_ERRORS = MPV_ERRORS + (AttributeError, RuntimeError, TypeError,
                                    ValueError)


class PlayerState(Enum):
    IDLE = auto()
    PLAYING = auto()
    STOPPED = auto()


# ==================== 礼物清单管理器 ===================
class GiftManager:
    DEFAULT_GIFTS: List[GiftInfo] = [{
        "name_cn": "玫瑰",
        "name_en": "Rose",
        "id": "5655",
        "image_path": "",
        "description": ""
    }, {
        "name_cn": "TikTok",
        "name_en": "TikTok",
        "id": "1",
        "image_path": "",
        "description": ""
    }, {
        "name_cn": "小爱心",
        "name_en": "Hearts",
        "id": "5586",
        "image_path": "",
        "description": ""
    }, {
        "name_cn": "手指爱心",
        "name_en": "Finger Heart",
        "id": "5822",
        "image_path": "",
        "description": ""
    }]

    def __init__(self, filename="gifts.json"):
        self.filename = filename
        self.gifts: List[GiftInfo] = []
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.gifts = json.load(f)
                if not isinstance(self.gifts, list):
                    self._reset_to_default()
            except (IOError, json.JSONDecodeError):
                self._reset_to_default()
        else:
            self._reset_to_default()

    def save(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.gifts,
                          f,
                          indent=2,
                          ensure_ascii=False)
        except IOError:
            print(f"错误: 无法储存礼物清单到 {self.filename}")

    def _reset_to_default(self):
        self.gifts = self.DEFAULT_GIFTS
        self.save()

    def get_all_gifts(self) -> List[GiftInfo]:
        return sorted(self.gifts, key=lambda x: x.get("name_cn", ""))

    def add_gift(self, gift_info: GiftInfo):
        self.gifts.append(gift_info)
        self.save()

    def update_gift_by_name(self, original_name_en: str, new_gift_info: GiftInfo):
        """根據禮物的原始英文名來更新禮物資訊"""
        for i, gift in enumerate(self.gifts):
            if gift.get("name_en") == original_name_en:
                self.gifts[i] = new_gift_info
                self.save()
                return True
        return False

    def delete_gift_by_name(self, name_en: str):
        """根據禮物的英文名 (唯一鍵) 來刪除禮物"""
        initial_len = len(self.gifts)
        self.gifts = [gift for gift in self.gifts if gift.get("name_en") != name_en]
        if len(self.gifts) < initial_len:
            self.save()


# ==================== TikTok 監聽核心 ===================
class TikTokListener(QObject):
    on_video_triggered = Signal(str, bool, int)
    on_event_received = Signal(dict)
    on_status_change = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client: Optional[TikTokLiveClient] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.gift_map: List[GiftMapItem] = []
        self.fallback_video_path: str = ""
        self.interrupt_on_gift = False

    def _extract_username(self, url: str) -> Optional[str]:
        m = re.search(r"tiktok\.com/@([^/?]+)", url)
        return m.group(1) if m else None

    def start(self, url: str, api_key: str):
        if not _HAS_TIKTOK_LIVE:
            self.on_event_received.emit({
                "type": "LOG",
                "tag": "ERROR",
                "message": "錯誤: 'TikTokLive' 函式庫未安裝"
            })
            return
        username = self._extract_username(url)
        if not username:
            self.on_event_received.emit({
                "type": "LOG",
                "tag": "ERROR",
                "message": f"錯誤: 無效的 TikTok 直播網址"
            })
            return
        if not api_key:
            self.on_event_received.emit({
                "type": "LOG",
                "tag": "ERROR",
                "message": f"錯誤: 必須提供 API Key"
            })
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_client,
                                       args=(username, api_key),
                                       daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.client:
            try:
                self.client.stop()
            except OSError as e:
                if "[WinError 6]" in str(e):
                    print("[INFO] 捕捉到良性的網路控制代碼關閉錯誤，已忽略。")
                else:
                    self.on_event_received.emit({
                        "type": "LOG",
                        "tag": "WARN",
                        "message": f"停止 client 時發生 OSError: {e}"
                    })
            except Exception as e:
                self.on_event_received.emit({
                    "type": "LOG",
                    "tag": "WARN",
                    "message": f"停止 client 時發生錯誤: {e}"
                })
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def _find_gift_map_match(self, gift_name: str,
                             gift_id: int) -> Optional[GiftMapItem]:
        if not gift_name:
            return None
        text = gift_name.lower()
        if gift_id:
            for item in self.gift_map:
                if str(item.get("gid", "")) == str(gift_id):
                    return item
        for item in self.gift_map:
            kw = item.get("kw", "").lower()
            if kw and kw in text:
                return item
        return None

    def _run_client(self, username: str, api_key: str):
        try:
            WebDefaults.tiktok_sign_api_key = api_key
            self.client = TikTokLiveClient(unique_id=f"@{username}")

            @self.client.on(ConnectEvent)
            async def on_connect(_: ConnectEvent):
                self.on_event_received.emit({
                    "type": "LOG",
                    "tag": "INFO",
                    "message": f"已連線至 @{username} 的直播間。"
                })
                self.on_status_change.emit(f"已連線: @{username}")

            @self.client.on(DisconnectEvent)
            async def on_disconnect(_: DisconnectEvent):
                self.on_event_received.emit({
                    "type": "LOG",
                    "tag": "INFO",
                    "message": "已從直播間斷線。"
                })
                self.on_status_change.emit("已斷線")

            @self.client.on(CommentEvent)
            async def on_comment(evt: CommentEvent):
                if not self.running:
                    return
                self.on_event_received.emit({
                    "type": "COMMENT",
                    "user": evt.user.nickname,
                    "message": evt.comment
                })

            @self.client.on(GiftEvent)
            async def on_gift(evt: GiftEvent):
                if not self.running:
                    return
                gift = evt.gift
                if gift.combo and not evt.repeat_end:
                    return
                self.on_event_received.emit({
                    "type": "GIFT",
                    "user": evt.user.nickname,
                    "gift_name": gift.name,
                    "count": evt.repeat_count
                })
                self.on_status_change.emit(
                    f"收到禮物: {gift.name} x{evt.repeat_count}")
                match = self._find_gift_map_match(gift.name, gift.id)
                if match:
                    path = match.get("path")
                    if path and os.path.exists(path):
                        self.on_event_received.emit({
                            "type": "LOG",
                            "tag": "DEBUG",
                            "message":
                                f"匹配成功: {gift.name} -> {os.path.basename(path)}"
                        })
                        self.on_video_triggered.emit(path,
                                                     self.interrupt_on_gift,
                                                     evt.repeat_count)
                    else:
                        self.on_event_received.emit({
                            "type": "LOG",
                            "tag": "WARN",
                            "message": f"匹配成功但檔案不存在: {path}"
                        })
                elif self.fallback_video_path and os.path.exists(
                        self.fallback_video_path):
                    self.on_event_received.emit({
                        "type": "LOG",
                        "tag": "DEBUG",
                        "message": "無匹配，播放後備影片。"
                    })
                    self.on_video_triggered.emit(self.fallback_video_path,
                                                 self.interrupt_on_gift,
                                                 evt.repeat_count)

            @self.client.on(LikeEvent)
            async def on_like(event: LikeEvent):
                if not self.running:
                    return
                self.on_event_received.emit({
                    "type": "LIKE",
                    "user": event.user.nickname,
                    "count": event.count
                })

            @self.client.on(JoinEvent)
            async def on_join(event: JoinEvent):
                if not self.running:
                    return
                self.on_event_received.emit({
                    "type": "JOIN",
                    "user": event.user.nickname
                })

            @self.client.on(FollowEvent)
            async def on_follow(event: FollowEvent):
                if not self.running:
                    return
                self.on_event_received.emit({
                    "type": "FOLLOW",
                    "user": event.user.nickname
                })

            self.on_status_change.emit(f"正在連線至 @{username}...")
            self.client.run()
        except Exception as e:
            self.on_event_received.emit({
                "type": "LOG",
                "tag": "ERROR",
                "message": f"TikTok 連線失敗: {e}"
            })
            self.on_status_change.emit("連線錯誤")
        finally:
            self.running = False
            self.on_status_change.emit("已停止")


# ==================== FIFO 佇列 ==========================
class PlayQueueFIFO(QObject):
    monitor_signal = Signal(str, str, int, str)
    queue_changed = Signal()

    def __init__(self, maxlen: Optional[int] = None):
        super().__init__()
        self._q = deque()
        self._lock = threading.RLock()
        self._maxlen = int(maxlen) if maxlen and maxlen > 0 else None

    def _mon(self, op, caller, size, note):
        self.monitor_signal.emit(op, caller, size, note)
        self.queue_changed.emit()

    def enqueue(self, job_path: str, repeat: int = 1, note: str = ""):
        item = (job_path, str(note or ""))
        with self._lock:
            for _ in range(max(1, repeat or 1)):
                if self._maxlen and len(self._q) >= self._maxlen:
                    self._q.popleft()
                self._q.append(item)
            self._mon("push", "enqueue", len(self._q), f"{note} x{max(1, repeat or 1)}")

    def pop_next(self) -> Optional[tuple[str, str]]:
        with self._lock:
            if not self._q:
                return None
            job = self._q.popleft()
            self._mon("pop", "pop_next", len(self._q), job[1])
            return job

    def snapshot(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._q)

    def clear(self):
        with self._lock:
            self._q.clear()
            self._mon("clear", "clear", 0, "")

    def __len__(self):
        with self._lock:
            return len(self._q)


# ==================== 播放器包裝 ===================
class PlayerWrapper(QObject):
    playback_ended = Signal()

    def __init__(self, video_container: QWidget,
                 on_log: Callable[[str], None]):
        super().__init__()
        self._on_log = on_log
        if _HAS_MPV:
            try:
                self._p = mpv.MPV(
                    wid=int(video_container.winId()),
                    vo="gpu",
                    hwdec="auto-safe",
                    osc="no",
                    border="no",
                    input_default_bindings=False,
                    input_vo_keyboard=False,
                )

                @self._p.event_callback('end-file')
                def _(event):
                    self._on_end_file(event)

                self._backend = "mpv"
            except MPV_CALL_ERRORS as e:
                self._on_log(f"[MPV INIT FAILED] {e}")
                self._p, self._backend = None, "mock"
        else:
            self._p, self._backend = None, "mock"

    def _on_end_file(self, event):
        reason_str = ""
        try:
            reason = getattr(getattr(event, 'data', None), 'reason', None)
            if reason is not None:
                if isinstance(reason, (str, bytes)):
                    reason_str = reason.decode(
                        'utf-8') if isinstance(reason, bytes) else reason
                elif isinstance(reason, int):
                    reason_str = str(reason)
                elif hasattr(reason, 'value'):
                    reason_str = str(reason.value)
                else:
                    reason_str = str(reason)
        except Exception:
            pass
        reason_str = reason_str.lower().strip()
        if reason_str == 'eof' or reason_str == '0':
            self.playback_ended.emit()

    def _safe_call(self, method_name: str, *args):
        if not self._p:
            return
        try:
            method = getattr(self._p, method_name)
            if callable(method):
                return method(*args)
        except MPV_CALL_ERRORS as e:
            self._on_log(
                f"[{self._backend.upper()}] call failed: {method_name} with {args} ({e})"
            )

    def command(self, *args):
        self._safe_call("command", *args)

    def set_property(self, name, value):
        self._safe_call("set_property", name, value)

    def get_property(self, name):
        if not self._p:
            return None
        try:
            return self._p.get_property(name)
        except MPV_CALL_ERRORS:
            self._on_log(
                f"[{self._backend.upper()}] get_property failed: {name}")
            return None

    def terminate(self):
        self._safe_call("terminate")

    def set_loop(self, times: int):
        if times == 1:
            loop_value = "no"
        elif times <= 0:
            loop_value = "inf"
        else:
            loop_value = str(times)
        self.command("set", "loop", loop_value)

    def set_mute(self, muted: bool = True):
        current_mute_state = self.get_property("mute")
        if current_mute_state is None:
            self._on_log("警告: 無法獲取 'mute' 屬性，無法可靠設定靜音。")
            return
        if muted and not current_mute_state:
            self.command("cycle", "mute")
        elif not muted and current_mute_state:
            self.command("cycle", "mute")

    def set_volume(self, volume: int):
        """設定播放器音量 (0-100)"""
        vol = max(0, min(100, volume))
        self.set_property("volume", vol)

    def stop_playback(self):
        self.command("loadfile", "", "replace")

    def cycle_property(self, prop: str):
        self.command("cycle", prop)


# ==================== 可縮放的影片框架 ===================
class ResizableVideoFrame(QFrame):
    layout_changed_by_user = Signal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setMouseTracking(True)
        self._aspect_ratio = 16.0 / 9.0
        self._is_dragging = False
        self._current_corner = None
        self._start_pos = QPointF()
        self._start_geom = self.geometry()
        self._is_editing = False

    def set_editing(self, is_editing: bool):
        self._is_editing = is_editing
        self.update()
        if is_editing:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()

    def set_aspect_ratio(self, ratio: float):
        if ratio > 0:
            self._aspect_ratio = ratio

    def paintEvent(self, event: QPaintEvent):
        pass

    def mousePressEvent(self, event: QMouseEvent):
        if not self._is_editing:
            return
        self._is_dragging = True
        self._start_pos = event.globalPosition()
        self._start_geom = self.geometry()
        self._current_corner = self._get_corner(event.position().toPoint())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._is_editing:
            return
        if self._is_dragging:
            delta = event.globalPosition() - self._start_pos
            new_geom = QRectF(self._start_geom)
            if self._current_corner:
                if 'l' in self._current_corner:
                    new_geom.setLeft(self._start_geom.left() + delta.x())
                if 'r' in self._current_corner:
                    new_geom.setRight(self._start_geom.right() + delta.x())
                if 't' in self._current_corner:
                    new_geom.setTop(self._start_geom.top() + delta.y())
                if 'b' in self._current_corner:
                    new_geom.setBottom(self._start_geom.bottom() + delta.y())
                w, h = new_geom.width(), new_geom.height()
                if w > 0 and h > 0:
                    if w / h > self._aspect_ratio:
                        h = w / self._aspect_ratio
                    else:
                        w = h * self._aspect_ratio
                    if 'l' in self._current_corner:
                        new_geom.setLeft(new_geom.right() - w)
                    if 't' in self._current_corner:
                        new_geom.setTop(new_geom.bottom() - h)
                    new_geom.setWidth(w)
                    new_geom.setHeight(h)
            else:
                new_geom.translate(delta)
            new_rect = new_geom.toRect()
            self.setGeometry(new_rect)
            self.layout_changed_by_user.emit(new_rect)
        else:
            self.setCursorForPos(event.position().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self._is_editing:
            return
        self._is_dragging = False
        self.setCursorForPos(event.position().toPoint())
        event.accept()

    def setCursorForPos(self, pos: QPointF):
        if not self._is_editing:
            self.unsetCursor()
            return
        corner = self._get_corner(pos)
        if corner in ['tl', 'br']:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif corner in ['tr', 'bl']:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def _get_corner(self, pos: QPointF, margin=15):
        on_left = 0 <= pos.x() < margin
        on_right = self.width() - margin < pos.x() <= self.width()
        on_top = 0 <= pos.y() < margin
        on_bottom = self.height() - margin < pos.y() <= self.height()
        if on_top and on_left:
            return 'tl'
        if on_top and on_right:
            return 'tr'
        if on_bottom and on_left:
            return 'bl'
        if on_bottom and on_right:
            return 'br'
        return ""


# ==================== Overlay 視窗 ===================
class OverlayWindow(QWidget):
    def __init__(self, main_window: 'MainWindow', parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("影片 Overlay 播放視窗")
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.CustomizeWindowHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet("background-color: rgba(0, 255, 0, 80);")


class MenuOverlayWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("菜單 Overlay 視窗 (綠幕)")
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.CustomizeWindowHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet("background-color: #00FF00;")
        self.resize(400, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)


# ==================== 禮物編輯對話方塊 ===================
class GiftMapDialog(QDialog):
    def __init__(self,
                 parent=None,
                 item: Optional[GiftMapItem] = None,
                 library_paths: List[str] = [],
                 gift_list: List[GiftInfo] = []):
        super().__init__(parent)
        self.setWindowTitle("編輯禮物映射")
        self.item = item or {}
        layout = QVBoxLayout(self)

        gift_layout = QHBoxLayout()
        gift_layout.addWidget(QLabel("禮物:"))
        self.gift_combo = QComboBox()
        for gift in gift_list:
            display_text = f"{gift.get('name_cn', '')} ({gift.get('name_en', '')})"
            self.gift_combo.addItem(display_text, userData=gift)

        current_kw = self.item.get("kw", "")
        current_gid = self.item.get("gid", "")
        if current_kw or current_gid:
            for i in range(self.gift_combo.count()):
                gift_data = self.gift_combo.itemData(i)
                if (gift_data.get("name_en") == current_kw
                        or gift_data.get("id") == current_gid):
                    self.gift_combo.setCurrentIndex(i)
                    break
        gift_layout.addWidget(self.gift_combo)
        layout.addLayout(gift_layout)

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("影片路徑:"))
        self.path_combo = QComboBox()
        for path in library_paths:
            self.path_combo.addItem(os.path.basename(path), userData=path)

        current_path = self.item.get("path", "")
        if current_path:
            index = self.path_combo.findData(current_path)
            if index >= 0:
                self.path_combo.setCurrentIndex(index)
        path_layout.addWidget(self.path_combo)
        layout.addLayout(path_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self) -> GiftMapItem:
        selected_gift_index = self.gift_combo.currentIndex()
        gift_data = self.gift_combo.itemData(
            selected_gift_index) if selected_gift_index >= 0 else {}
        selected_path_index = self.path_combo.currentIndex()
        path = self.path_combo.itemData(
            selected_path_index) if selected_path_index >= 0 else ""
        return {
            "kw": gift_data.get("name_en", ""),
            "gid": gift_data.get("id", ""),
            "path": path
        }


# ==================== GiftsTab（新：抽離 TikTok 禮物設定頁） ===================
class GiftsTab(QWidget):
    """
    封裝「TikTok 禮物設定」分頁的 UI 與互動邏輯。
    改為持有 main_window 的參考，避免使用 parent() 造成 QStackedWidget 問題。
    """
    def __init__(self,
                 main_window: 'MainWindow',
                 tiktok_listener: TikTokListener,
                 gift_manager: GiftManager,
                 get_library_paths: Callable[[], List[str]],
                 log_func: Callable[[str], None],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.main = main_window               # 新增：保存 MainWindow 參考
        self.listener = tiktok_listener
        self.gift_manager = gift_manager
        self.get_library_paths = get_library_paths
        self._log = log_func
        self.playback_volume = 100
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 連線設定
        connect_group = QGroupBox("TikTok 连线设定")
        connect_layout = QVBoxLayout(connect_group)
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("直播网址:"))
        self.tiktok_url_entry = QLineEdit()
        self.tiktok_url_entry.setPlaceholderText("https://www.tiktok.com/@username/live")
        url_layout.addWidget(self.tiktok_url_entry)
        connect_layout.addLayout(url_layout)

        api_layout = QHBoxLayout()
        api_layout.addWidget(QLabel("API Key:"))
        self.tiktok_api_key_entry = QLineEdit()
        self.tiktok_api_key_entry.setPlaceholderText("從 eulerstream.com 取得")
        self.tiktok_api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.tiktok_api_key_entry.setToolTip("API Key 需要從 eulerstream.com 取得，供 TikTokLive 函式庫使用。")
        api_layout.addWidget(self.tiktok_api_key_entry)
        connect_layout.addLayout(api_layout)

        btn_layout = QHBoxLayout()
        self.tiktok_start_btn = QPushButton("开始监听")
        self.tiktok_stop_btn = QPushButton("停止监听")
        self.tiktok_status_label = QLabel("状态: 未连线")
        self.tiktok_stop_btn.setEnabled(False)
        btn_layout.addWidget(self.tiktok_start_btn)
        btn_layout.addWidget(self.tiktok_stop_btn)
        btn_layout.addWidget(self.tiktok_status_label, 1)
        connect_layout.addLayout(btn_layout)
        layout.addWidget(connect_group)

        # 禮物映射
        map_group = QGroupBox("礼物 -> 影片 映射")
        map_layout = QVBoxLayout(map_group)
        self.gift_tree = QTreeWidget()
        self.gift_tree.setColumnCount(2)
        self.gift_tree.setHeaderLabels(["礼物", "影片路径"])
        self.gift_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        map_layout.addWidget(self.gift_tree)
        map_btn_layout = QHBoxLayout()
        btn_add_gift = QPushButton("新增映射")
        btn_edit_gift = QPushButton("编辑所选")
        btn_del_gift = QPushButton("删除所选")
        btn_manage_gifts = QPushButton("礼物清单管理...")
        map_btn_layout.addWidget(btn_add_gift)
        map_btn_layout.addWidget(btn_edit_gift)
        map_btn_layout.addWidget(btn_del_gift)
        map_btn_layout.addStretch()
        map_btn_layout.addWidget(btn_manage_gifts)
        map_layout.addLayout(map_btn_layout)
        layout.addWidget(map_group, 1)

        # 後備影片 + 播放選項
        fallback_group = QGroupBox("后备影片 (无匹配时播放)")
        fallback_layout = QHBoxLayout(fallback_group)
        self.fallback_video_entry = QLineEdit()
        self.fallback_video_entry.setReadOnly(True)
        btn_pick_fallback = QPushButton("选择档案...")
        fallback_layout.addWidget(self.fallback_video_entry, 1)
        fallback_layout.addWidget(btn_pick_fallback)
        layout.addWidget(fallback_group)

        option_group = QGroupBox("播放選項")
        option_layout = QVBoxLayout(option_group)
        top_options_layout = QHBoxLayout()
        self.interrupt_checkbox = QCheckBox("新礼物插队播放")
        self.read_comment_checkbox = QCheckBox("朗讀觀眾留言")
        if not _HAS_TTS:
            self.read_comment_checkbox.setDisabled(True)
            self.read_comment_checkbox.setToolTip("錯誤: 'pyttsx3' 函式庫未安裝")
        top_options_layout.addWidget(self.interrupt_checkbox)
        top_options_layout.addWidget(self.read_comment_checkbox)
        top_options_layout.addStretch()
        option_layout.addLayout(top_options_layout)

        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("觸發媒體音量:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.playback_volume)
        self.volume_spinbox = QSpinBox()
        self.volume_spinbox.setRange(0, 100)
        self.volume_spinbox.setValue(self.playback_volume)
        self.volume_slider.valueChanged.connect(self.volume_spinbox.setValue)
        self.volume_spinbox.valueChanged.connect(self.volume_slider.setValue)
        self.volume_spinbox.valueChanged.connect(self._on_volume_changed)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_spinbox)
        option_layout.addLayout(volume_layout)

        layout.addWidget(option_group)

        # 事件連接
        self.tiktok_start_btn.clicked.connect(self._start_tiktok_listener)
        self.tiktok_stop_btn.clicked.connect(self._stop_tiktok_listener)
        self.gift_tree.itemDoubleClicked.connect(self._on_gift_tree_double_clicked)
        btn_add_gift.clicked.connect(self._add_gift_map)
        btn_edit_gift.clicked.connect(self._edit_gift_map)
        btn_del_gift.clicked.connect(self._remove_gift_map)
        btn_manage_gifts.clicked.connect(lambda: self.main._manage_gift_list())   # 改用 self.main
        btn_pick_fallback.clicked.connect(self._pick_fallback_video)

    # ----- GiftsTab 內部邏輯 -----
    def _start_tiktok_listener(self):
        url = self.tiktok_url_entry.text().strip()
        api_key = self.tiktok_api_key_entry.text().strip()
        if not url or not api_key:
            QMessageBox.warning(self, "提示", "請同時輸入直播網址和 API Key。")
            return
        self.listener.interrupt_on_gift = self.interrupt_checkbox.isChecked()
        self.listener.start(url, api_key)

    def _stop_tiktok_listener(self):
        self.listener.stop()

    def _refresh_gift_tree(self):
        self.gift_tree.clear()
        gift_name_map = {
            g.get("name_en"): g.get("name_cn", g.get("name_en"))
            for g in self.gift_manager.get_all_gifts()
        }
        for item in self.listener.gift_map:
            kw = item.get("kw", "")
            gid = item.get("gid", "")
            path = item.get("path", "")
            display_name = gift_name_map.get(kw, kw)
            id_str = f"(ID: {gid})" if gid else ""
            full_display_name = f"{display_name} {id_str}".strip()
            display_path = os.path.basename(path) if path else "N/A"
            tree_item = QTreeWidgetItem([full_display_name, display_path])
            if not path or not os.path.exists(path):
                tree_item.setForeground(1, QColor("red"))
                tree_item.setToolTip(1, f"檔案不存在或未設定！\n路徑: {path}")
            self.gift_tree.addTopLevelItem(tree_item)
        self.gift_tree.resizeColumnToContents(0)

    def _add_gift_map(self):
        library_paths = self.get_library_paths()
        if not library_paths:
            QMessageBox.warning(self, "提示", "媒體庫是空的，請先加入一些影片。")
            return
        dialog = GiftMapDialog(self,
                               library_paths=library_paths,
                               gift_list=self.gift_manager.get_all_gifts())
        if dialog.exec():
            new_data = dialog.get_data()
            if not new_data.get("path"):
                QMessageBox.warning(self, "提示", "必須選擇一個影片檔案。")
                return
            if not new_data.get("kw") and not new_data.get("gid"):
                QMessageBox.warning(self, "提示", "禮物未選擇或無效。")
                return
            self.listener.gift_map.append(new_data)
            self._refresh_gift_tree()
            self.main._save_gift_map()          # 改用 self.main

    def _edit_gift_map(self):
        selected = self.gift_tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "提示", "請先選擇一個要編輯的項目。")
            return
        index = self.gift_tree.indexOfTopLevelItem(selected)
        if index < 0:
            return
        library_paths = self.get_library_paths()
        item_data = self.listener.gift_map[index]
        dialog = GiftMapDialog(self,
                               item=item_data,
                               library_paths=library_paths,
                               gift_list=self.gift_manager.get_all_gifts())
        if dialog.exec():
            updated_data = dialog.get_data()
            if not updated_data.get("path"):
                QMessageBox.warning(self, "提示", "必須選擇一個影片檔案。")
                return
            if not updated_data.get("kw") and not updated_data.get("gid"):
                QMessageBox.warning(self, "提示", "禮物未選擇或無效。")
                return
            self.listener.gift_map[index] = updated_data
            self._refresh_gift_tree()
            self.main._save_gift_map()          # 改用 self.main

    def _remove_gift_map(self):
        selected = self.gift_tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "提示", "請先選擇一個要刪除的項目。")
            return
        index = self.gift_tree.indexOfTopLevelItem(selected)
        if index >= 0:
            reply = QMessageBox.question(self, "確認刪除", f"確定要刪除「{selected.text(0)}」這個映射嗎？")
            if reply == QMessageBox.StandardButton.Yes:
                del self.listener.gift_map[index]
                self._refresh_gift_tree()
                self.main._save_gift_map()      # 改用 self.main

    def _pick_fallback_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇後備影片", "", "影片檔案 (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.fallback_video_entry.setText(path)
            self.listener.fallback_video_path = path
            self.main._save_gift_map()          # 改用 self.main

    def _on_gift_tree_double_clicked(self, item: QTreeWidgetItem, _):
        index = self.gift_tree.indexOfTopLevelItem(item)
        if index < 0:
            return
        path = self.listener.gift_map[index].get("path")
        if not (path and os.path.exists(path)):
            QMessageBox.warning(self, "提示", "該映射的影片檔案不存在或未設定。")
            return
        count, ok = QInputDialog.getInt(
            self, "輸入播放次數",
            f"請輸入「{os.path.basename(path)}」的播放次數：",
            1, 1, 999, 1
        )
        if ok:
            self.main._enqueue_video_from_gift(path, False, count)   # 改用 self.main
            self._log(f"已手動將「{os.path.basename(path)}」加入待播清單 {count} 次，並更新計數。")

    def _on_volume_changed(self, value: int):
        self.playback_volume = value
        self.main._on_volume_changed(value)     # 改用 self.main

    # 讓 MainWindow 呼叫以同步/持久化
    def load_settings(self, data: dict):
        self.tiktok_url_entry.setText(data.get("tiktok_url", ""))
        self.tiktok_api_key_entry.setText(data.get("api_key", ""))
        self.listener.gift_map = data.get("gift_map", [])
        self.listener.fallback_video_path = data.get("fallback_video", "")
        self.fallback_video_entry.setText(self.listener.fallback_video_path)
        self.listener.interrupt_on_gift = data.get("interrupt_on_gift", False)
        self.interrupt_checkbox.setChecked(self.listener.interrupt_on_gift)
        self.playback_volume = data.get("playback_volume", 100)
        self.volume_slider.setValue(self.playback_volume)
        self._refresh_gift_tree()

    def get_settings(self) -> dict:
        return {
            "tiktok_url": self.tiktok_url_entry.text().strip(),
            "api_key": self.tiktok_api_key_entry.text().strip(),
            "gift_map": self.listener.gift_map,
            "fallback_video": self.fallback_video_entry.text(),
            "interrupt_on_gift": self.interrupt_checkbox.isChecked(),
            "playback_volume": self.playback_volume
        }


# ==================== 主 GUI 應用 ===================
class MainWindow(QMainWindow):
    LAYOUT_FILE = os.path.join(application_path, "layouts.json")
    LIBRARY_FILE = os.path.join(application_path, "library.json")
    GIFT_MAP_FILE = os.path.join(application_path, "gift_map.json")
    GIFT_LIST_FILE = os.path.join(application_path, "gifts.json")
    EVENTS_LOG_FILE = os.path.join(application_path, "events_log.txt")
    THEME_FILE = os.path.join(application_path, "theme.json")
    TRIGGER_FILE = os.path.join(application_path, "triggers.json")

    DEV_LOG_CONTENT = """<h3>版本更新歷史</h3>
    <p><b>V9.52-DataManagers</b></p>
    <ul>
      <li>重構：新增資料管理器（SettingsManager / LayoutsManager / LibraryManager / ThemeManager），
      將所有檔案 I/O 從 MainWindow 中抽離，統一管理。</li>
    </ul>
    <p><b>V9.51-DedupeFix</b></p>
    <ul><li>修復 Bug：修正了事件去重功能因缺少屬性初始化而導致的 AttributeError。</li></ul>
    <p><b>V9.50-VolumeControl</b></p>
    <ul><li>新增功能：在「播放選項」中新增了觸發媒體的音量控制滑塊和數字框。</li></ul>
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Overlay UltraLite - V9.52 (Data Managers)")
        self.setGeometry(100, 100, 1200, 800)

        # --- 1. 初始化所有屬性 ---
        self.layouts_mgr = LayoutsManager(self.LAYOUT_FILE)
        self.layouts = self.layouts_mgr.load()

        self.settings_mgr = SettingsManager(self.GIFT_MAP_FILE)
        self.library_mgr = LibraryManager(self.LIBRARY_FILE)
        self.theme_mgr = ThemeManager(self.THEME_FILE)

        self.queue = PlayQueueFIFO(maxlen=500)
        self.player_state = PlayerState.IDLE
        self.current_job_path: Optional[str] = None
        self.is_editing = False
        self._last_video_geometry: Optional[QRect] = None
        self.gift_manager = GiftManager(self.GIFT_LIST_FILE)
        self.trigger_manager = TriggerManager(self.TRIGGER_FILE)
        self.tiktok_listener = TikTokListener(self)
        self.event_log_buffer = []
        self.video_dimensions_cache = {}
        self.theme_settings = {}
        self.gift_trigger_counts = {}
        self.path_to_gift_id_map = {}
        self.playback_volume = 100
        self.speech_engine = SpeechEngine(self)
        self.recent_events = deque(maxlen=20)

        # 初始化所有計時器
        self.log_write_timer = QTimer(self)
        self.viewer_list_updater = QTimer(self)
        self.tts_queue_refresh_timer = QTimer(self)
        self.queue_count_update_timer = QTimer(self)

        # --- 2. 設定 UI ---
        self._setup_ui()

        # --- 3. 連接所有信號和槽 ---
        self._setup_connections()

        # --- 4. 載入初始資料 ---
        self._load_theme()
        self._auto_load_library()
        self._load_gift_map()
        self._build_path_to_gift_id_map()
        self._refresh_queue_view()

        # --- 5. 啟動所有計時器 ---
        self.viewer_list_updater.start(5000)
        self.log_write_timer.start(5000)
        self.tts_queue_refresh_timer.start(1000)
        self.queue_count_update_timer.start(1000)

        self._check_for_first_run()

    def _setup_connections(self):
        """將所有信號連接集中在此"""
        # 佇列信號
        self.queue.monitor_signal.connect(self._write_to_monitor)
        self.queue.queue_changed.connect(self._refresh_queue_view)

        # TikTok 信號
        self.tiktok_listener.on_video_triggered.connect(self._enqueue_video_from_gift)
        self.tiktok_listener.on_event_received.connect(self._on_tiktok_event)
        self.tiktok_listener.on_status_change.connect(self._on_tiktok_status)

        # 計時器信號
        self.log_write_timer.timeout.connect(self._flush_log_buffer_to_file)
        self.viewer_list_updater.timeout.connect(self._update_viewer_list)
        self.tts_queue_refresh_timer.timeout.connect(self._refresh_tts_queue_view)
        self.queue_count_update_timer.timeout.connect(self._update_queue_counts_in_menu)

    def _setup_ui(self):
        # --- Menu Bar ---
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("幫助")
        about_action = help_menu.addAction("關於 Overlay UltraLite")
        about_action.triggered.connect(self._show_about_dialog)
        dev_log_action = help_menu.addAction("開發日誌")
        dev_log_action.triggered.connect(self._show_dev_log_dialog)

        # --- Main Layout ---
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # --- Panels ---
        left_panel = QWidget()
        self.left_layout = QVBoxLayout(left_panel)

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        self.tabs = QTabWidget()
        center_layout.addWidget(self.tabs)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.right_tabs = QTabWidget()
        right_layout.addWidget(self.right_tabs)

        # 先將所有面板加入 splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(right_panel)

        # Right Tabs
        self.tab_events = QWidget()
        self.tab_viewers = QWidget()
        self.tab_tts_queue = QWidget()
        self.right_tabs.addTab(self.tab_events, "即时动态")
        self.right_tabs.addTab(self.tab_viewers, "观众")
        self.right_tabs.addTab(self.tab_tts_queue, "語音佇列")
        self._setup_events_tab(self.tab_events)
        self._setup_viewers_tab(self.tab_viewers)
        self._setup_tts_queue_tab(self.tab_tts_queue)

        # Center Tabs
        self.tab_library = QWidget()
        self.tab_gifts = GiftsTab(
            main_window=self,  # 這行是關鍵：把 MainWindow 傳給 GiftsTab
            tiktok_listener=self.tiktok_listener,
            gift_manager=self.gift_manager,
            get_library_paths=lambda: [self.lib_list.item(i).text() for i in range(self.lib_list.count())],
            log_func=self._log,
            parent=self.tabs  # 可設為 self.tabs 或不設，均可
        )
        self.tab_triggers = QWidget()
        self.tab_log = QWidget()
        self.tab_theme = QWidget()
        self.tabs.addTab(self.tab_library, "媒体库")
        self.tabs.addTab(self.tab_gifts, "TikTok 礼物设定")
        self.tabs.addTab(self.tab_triggers, "關鍵字觸發")
        self.tabs.addTab(self.tab_theme, "外觀設定")
        self.tabs.addTab(self.tab_log, "日誌")
        self._setup_library_tab(self.tab_library)
        # 不再呼叫 self._setup_gifts_tab(self.tab_gifts)
        self._setup_triggers_tab(self.tab_triggers)
        self._setup_theme_tab(self.tab_theme)
        self._setup_log_tab(self.tab_log)

        # 最後才設定左側面板
        self._setup_left_panel()

        splitter.setSizes([300, 500, 400])

    def _setup_left_panel(self):
        # --- Overlay Window and Player ---
        self.overlay_window = OverlayWindow(self)
        self.video_container = ResizableVideoFrame(self.overlay_window)

        self.menu_overlay_window = MenuOverlayWindow(self)
        self.game_menu_container = GameMenuContainer(parent=self.menu_overlay_window,
                                                     theme_settings=self.theme_settings)
        self.menu_overlay_window.layout().addWidget(self.game_menu_container)
        self.menu_overlay_window.hide()

        self.video_container.layout_changed_by_user.connect(
            self._on_layout_var_change_by_user)
        self.player = PlayerWrapper(self.video_container, self._log)
        self.player.playback_ended.connect(self._on_playback_end)

        # --- Overlay Control Box ---
        overlay_box = QGroupBox("影片 Overlay 視窗控制")
        overlay_box_layout = QVBoxLayout(overlay_box)
        btn_show_overlay = QPushButton("顯示 / 建立 影片 Overlay 視窗")
        btn_show_overlay.clicked.connect(self._toggle_overlay_window)
        overlay_box_layout.addWidget(btn_show_overlay)

        ratio_widget = QWidget()
        ratio_layout = QHBoxLayout(ratio_widget)
        ratio_layout.addWidget(QLabel("長寬比:"))
        self.aspect_16_9 = QRadioButton("16:9")
        self.aspect_16_9.setChecked(True)
        self.aspect_16_9.toggled.connect(self._update_overlay_geometry)
        ratio_layout.addWidget(self.aspect_16_9)
        self.aspect_9_16 = QRadioButton("9:16")
        self.aspect_9_16.toggled.connect(self._update_overlay_geometry)
        ratio_layout.addWidget(self.aspect_9_16)
        overlay_box_layout.addWidget(ratio_widget)
        self.left_layout.addWidget(overlay_box)

        # --- Game Menu Control Box ---
        menu_box = QGroupBox("菜單 Overlay 控制 (綠幕)")
        menu_box_layout = QVBoxLayout(menu_box)
        btn_toggle_menu = QPushButton("顯示 / 隱藏 菜單 Overlay")
        btn_toggle_menu.clicked.connect(self._toggle_menu_overlay_window)
        menu_box_layout.addWidget(btn_toggle_menu)

        self.show_counter_checkbox = QCheckBox("顯示禮物觸發計數")
        self.show_counter_checkbox.toggled.connect(self._on_show_counter_toggled)
        menu_box_layout.addWidget(self.show_counter_checkbox)

        self.show_queue_counter_checkbox = QCheckBox("顯示待播影片計數")
        self.show_queue_counter_checkbox.setChecked(True)
        self.show_queue_counter_checkbox.toggled.connect(self._update_queue_counts_in_menu)
        menu_box_layout.addWidget(self.show_queue_counter_checkbox)

        btn_reset_counter = QPushButton("重設計數")
        btn_reset_counter.clicked.connect(self._reset_gift_counts)
        menu_box_layout.addWidget(btn_reset_counter)

        self.btn_edit_menu_layout = QPushButton("🔒 編輯菜單佈局")
        self.btn_edit_menu_layout.setCheckable(True)
        self.btn_edit_menu_layout.toggled.connect(self._on_menu_edit_mode_toggled)
        menu_box_layout.addWidget(self.btn_edit_menu_layout)

        self.left_layout.addWidget(menu_box)

        # --- Playback Control Box ---
        play_box = QGroupBox("播放控制")
        play_box_layout = QHBoxLayout(play_box)
        btn_play = QPushButton("▶ 播下一个")
        btn_play.clicked.connect(self._force_play_next)
        play_box_layout.addWidget(btn_play)
        btn_stop = QPushButton("⏹ 停止")
        btn_stop.clicked.connect(self._stop_current)
        play_box_layout.addWidget(btn_stop)
        btn_clear_q = QPushButton("清空待播")
        btn_clear_q.clicked.connect(self.queue.clear)
        play_box_layout.addWidget(btn_clear_q)
        self.left_layout.addWidget(play_box)

        self.now_playing_label = QLabel("▶ 尚未播放")
        self.left_layout.addWidget(self.now_playing_label)

        self._setup_layout_editor()

        # --- Queue Box ---
        q_box = QGroupBox("待播清单")
        q_box_layout = QVBoxLayout(q_box)
        self.q_list = QListWidget()
        q_box_layout.addWidget(self.q_list)
        self.left_layout.addWidget(q_box, 1)

        self.left_layout.addStretch(0)

    def _setup_tts_queue_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tts_q_list = QListWidget()
        layout.addWidget(self.tts_q_list)

    def _refresh_tts_queue_view(self):
        if not self.speech_engine:
            return
        snapshot = self.speech_engine.snapshot()
        current_items = [self.tts_q_list.item(i).text() for i in range(self.tts_q_list.count())]
        if current_items != snapshot:
            self.tts_q_list.clear()
            self.tts_q_list.addItems(snapshot)

    def _setup_library_tab(self, parent):
        layout = QVBoxLayout(parent)
        lib_box = QGroupBox("媒体清单 (可拖放檔案至此)")
        lib_box_layout = QHBoxLayout(lib_box)

        self.lib_list = QListWidget()
        self.lib_list.itemDoubleClicked.connect(self._enqueue_selected_from_library)
        self.lib_list.setAcceptDrops(True)
        self.lib_list.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        self.lib_list.dragEnterEvent = self._on_library_drag_enter
        self.lib_list.dropEvent = self._on_library_drop
        self.lib_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lib_list.customContextMenuRequested.connect(self._show_library_context_menu)
        lib_box_layout.addWidget(self.lib_list)

        lib_btn_widget = QWidget()
        lib_btn_layout = QVBoxLayout(lib_btn_widget)
        btn_add = QPushButton("＋ 加入档案")
        btn_add.clicked.connect(self._pick_files)
        btn_enqueue = QPushButton("→ 加入待播")
        btn_enqueue.clicked.connect(self._enqueue_selected_from_library)
        btn_edit = QPushButton("调整版面")
        btn_edit.clicked.connect(self._enter_edit_mode)
        btn_reset = QPushButton("重设版面")
        btn_reset.clicked.connect(self._reset_selected_layout)
        btn_remove = QPushButton("删除所选")
        btn_remove.clicked.connect(self._remove_selected_from_library)
        btn_clear = QPushButton("清空清单")
        btn_clear.clicked.connect(self._clear_library)
        btn_save_list_as = QPushButton("另存清单...")
        btn_save_list_as.clicked.connect(self._save_library_as)
        btn_load_list_from = QPushButton("从档案载入...")
        btn_load_list_from.clicked.connect(self._load_library_from)

        for btn in [btn_add, btn_enqueue, btn_edit, btn_reset, btn_remove, btn_clear, btn_save_list_as, btn_load_list_from]:
            lib_btn_layout.addWidget(btn)
        lib_btn_layout.addStretch()
        lib_box_layout.addWidget(lib_btn_widget)
        layout.addWidget(lib_box, 1)

    # 保留舊的 _setup_gifts_tab 定義，但不再呼叫它（避免大規模刪除造成影響）
    def _setup_gifts_tab(self, parent):
        # 已由 GiftsTab 取代，保留空殼以相容舊呼叫（不做事）
        placeholder = QWidget(parent)
        layout = QVBoxLayout(placeholder)
        layout.addWidget(QLabel("此分頁已由 GiftsTab 取代。"))
        parent.setLayout(layout)

    def _setup_triggers_tab(self, parent):
        layout = QVBoxLayout(parent)
        group = QGroupBox("留言關鍵字 -> 影片 映射")
        group_layout = QVBoxLayout(group)

        self.trigger_tree = QTreeWidget()
        self.trigger_tree.setColumnCount(3)
        self.trigger_tree.setHeaderLabels(["關鍵字", "影片路徑", "朗讀回覆"])
        self.trigger_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.trigger_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        group_layout.addWidget(self.trigger_tree)

        btn_layout = QHBoxLayout()
        btn_add = QPushButton("新增")
        btn_edit = QPushButton("编辑")
        btn_del = QPushButton("删除")
        btn_add.clicked.connect(self._add_trigger)
        btn_edit.clicked.connect(self._edit_trigger)
        btn_del.clicked.connect(self._del_trigger)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_del)
        group_layout.addLayout(btn_layout)

        layout.addWidget(group)
        self._refresh_trigger_tree()

    def _refresh_trigger_tree(self):
        self.trigger_tree.clear()
        for item in self.trigger_manager.get_all_triggers():
            keyword = item.get("keyword", "N/A")
            path = item.get("path", "")
            tts_response = item.get("tts_response", "")

            display_path = os.path.basename(path) if path else "---"
            display_tts = tts_response if tts_response else "---"

            tree_item = QTreeWidgetItem([keyword, display_path, display_tts])

            if path and not os.path.exists(path):
                tree_item.setForeground(1, QColor("red"))
                tree_item.setToolTip(1, f"檔案不存在！\n路徑: {path}")

            self.trigger_tree.addTopLevelItem(tree_item)
        self.trigger_tree.resizeColumnToContents(0)

    def _add_trigger(self):
        library_paths = [self.lib_list.item(i).text() for i in range(self.lib_list.count())]
        if not library_paths:
            QMessageBox.warning(self, "提示", "媒體庫是空的，請先加入一些影片。")
            return
        dialog = TriggerEditDialog(self, library_paths=library_paths)
        if dialog.exec():
            new_data = dialog.get_data()
            if not new_data.get("keyword") or (not new_data.get("path") and not new_data.get("tts_response")):
                QMessageBox.warning(self, "提示", "關鍵字不能為空，且必須至少設定一個觸發動作（影片或朗讀）。")
                return
            self.trigger_manager.add_trigger(new_data)
            self._refresh_trigger_tree()

    def _edit_trigger(self):
        selected = self.trigger_tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "提示", "請先選擇一個要編輯的項目。")
            return
        index = self.trigger_tree.indexOfTopLevelItem(selected)
        item_data = self.trigger_manager.get_all_triggers()[index]

        library_paths = [self.lib_list.item(i).text() for i in range(self.lib_list.count())]
        dialog = TriggerEditDialog(self, item=item_data, library_paths=library_paths)
        if dialog.exec():
            updated_data = dialog.get_data()
            if not updated_data.get("keyword") or (not updated_data.get("path") and not updated_data.get("tts_response")):
                QMessageBox.warning(self, "提示", "關鍵字不能為空，且必須至少設定一個觸發動作（影片或朗讀）。")
                return
            self.trigger_manager.update_trigger(index, updated_data)
            self._refresh_trigger_tree()

    def _del_trigger(self):
        selected = self.trigger_tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "提示", "請先選擇一個要刪除的項目。")
            return
        index = self.trigger_tree.indexOfTopLevelItem(selected)
        reply = QMessageBox.question(self, "確認刪除", f"確定要刪除關鍵字「{selected.text(0)}」嗎？")
        if reply == QMessageBox.StandardButton.Yes:
            self.trigger_manager.delete_trigger(index)
            self._refresh_trigger_tree()

    def _setup_log_tab(self, parent):
        layout = QVBoxLayout(parent)
        mon_box = QGroupBox("监控台")
        mon_box_layout = QVBoxLayout(mon_box)
        self.monitor_list = QListWidget()
        mon_box_layout.addWidget(self.monitor_list)
        layout.addWidget(mon_box)

    def _setup_events_tab(self, parent):
        layout = QVBoxLayout(parent)
        self.events_list = QListWidget()
        layout.addWidget(self.events_list)

    def _setup_viewers_tab(self, parent):
        layout = QVBoxLayout(parent)
        self.viewer_count_label = QLabel("在线人数: N/A")
        self.viewer_list = QListWidget()
        layout.addWidget(self.viewer_count_label)
        layout.addWidget(self.viewer_list)

    def _setup_layout_editor(self):
        self.editor_box = QGroupBox("版面編輯器")
        editor_layout = QVBoxLayout(self.editor_box)
        self.layout_vars_widgets = {}
        for name in ["x", "y", "w", "h"]:
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.addWidget(QLabel(f"{name.upper()}:"))
            label = QLabel("0")
            layout.addWidget(label)
            self.layout_vars_widgets[name] = label
            editor_layout.addWidget(widget)
        preview_control_widget = QWidget()
        preview_control_layout = QHBoxLayout(preview_control_widget)
        self.btn_preview_play_pause = QPushButton("⏸ 暫停")
        self.btn_preview_play_pause.clicked.connect(self._toggle_preview_pause)
        preview_control_layout.addWidget(self.btn_preview_play_pause)
        self.btn_preview_stop = QPushButton("⏹ 停止")
        self.btn_preview_stop.clicked.connect(self._stop_preview_and_seek_to_start)
        preview_control_layout.addWidget(self.btn_preview_stop)
        editor_layout.addWidget(preview_control_widget)
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_save = QPushButton("儲存版面")
        btn_save.clicked.connect(lambda: self._exit_edit_mode(save=True))
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(lambda: self._exit_edit_mode(save=False))
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        editor_layout.addWidget(btn_widget)
        self.left_layout.addWidget(self.editor_box)
        self.editor_box.hide()

    # ==================== 主題設定相關方法 ====================
    def _load_theme(self):
        self.theme_settings = self.theme_mgr.load_theme()

    def _save_theme(self):
        try:
            # 收集 UI 值並存檔
            self.theme_settings["background_color"] = self.bg_color_btn.text()
            self.theme_settings["text_color"] = self.text_color_btn.text()
            self.theme_settings["font_size"] = self.font_size_spinbox.value()
            self.theme_settings["border_radius"] = self.radius_spinbox.value()
            self.theme_settings["item_spacing"] = self.spacing_spinbox.value()
            self.theme_settings["counter_font_size"] = self.counter_font_size_spinbox.value()
            self.theme_settings["queue_counter_font_size"] = self.queue_counter_font_size_spinbox.value()
            self.theme_mgr.save_theme(self.theme_settings)
            QMessageBox.information(self, "成功", "外觀設定已儲存！")
            self._apply_theme_to_menu()
        except IOError:
            QMessageBox.warning(self, "錯誤", f"無法儲存主題檔案至 {self.THEME_FILE}")

    def _reset_theme(self):
        self.theme_settings = dict(ThemeManager.DEFAULT)
        if hasattr(self, 'bg_color_btn'):
            self._update_theme_tab_ui()

    def _apply_theme_to_menu(self):
        if self.game_menu_container and self.menu_overlay_window.isVisible():
            self.game_menu_container.theme_settings = self.theme_settings
            self.game_menu_container.apply_theme()
            self._refresh_menu_content()

    def _setup_theme_tab(self, parent):
        layout = QVBoxLayout(parent)
        form_layout = QGridLayout()
        form_layout.addWidget(QLabel("背景顏色 (RGBA):"), 0, 0)
        self.bg_color_btn = QPushButton()
        self.bg_color_btn.clicked.connect(lambda: self._pick_color(self.bg_color_btn))
        form_layout.addWidget(self.bg_color_btn, 0, 1)
        form_layout.addWidget(QLabel("文字顏色:"), 1, 0)
        self.text_color_btn = QPushButton()
        self.text_color_btn.clicked.connect(lambda: self._pick_color(self.text_color_btn, use_rgba=False))
        form_layout.addWidget(self.text_color_btn, 1, 1)
        form_layout.addWidget(QLabel("字體大小 (px):"), 2, 0)
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 72)
        form_layout.addWidget(self.font_size_spinbox, 2, 1)
        form_layout.addWidget(QLabel("邊框圓角 (px):"), 3, 0)
        self.radius_spinbox = QSpinBox()
        self.radius_spinbox.setRange(0, 50)
        form_layout.addWidget(self.radius_spinbox, 3, 1)
        form_layout.addWidget(QLabel("項目間距 (px):"), 4, 0)
        self.spacing_spinbox = QSpinBox()
        self.spacing_spinbox.setRange(0, 50)
        form_layout.addWidget(self.spacing_spinbox, 4, 1)

        form_layout.addWidget(QLabel("計數器字體大小 (px):"), 5, 0)
        self.counter_font_size_spinbox = QSpinBox()
        self.counter_font_size_spinbox.setRange(8, 96)
        form_layout.addWidget(self.counter_font_size_spinbox, 5, 1)

        form_layout.addWidget(QLabel("待播計數字體大小 (px):"), 6, 0)
        self.queue_counter_font_size_spinbox = QSpinBox()
        self.queue_counter_font_size_spinbox.setRange(8, 72)
        form_layout.addWidget(self.queue_counter_font_size_spinbox, 6, 1)

        layout.addLayout(form_layout)
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("儲存設定")
        save_btn.clicked.connect(self._save_theme)
        apply_btn = QPushButton("即時預覽")
        apply_btn.clicked.connect(self._apply_theme_to_menu)
        reset_btn = QPushButton("重設為預設值")
        reset_btn.clicked.connect(self._reset_theme)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        btn_layout.addWidget(apply_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        layout.addStretch()
        self._update_theme_tab_ui()

    def _update_theme_tab_ui(self):
        bg_color_str = self.theme_settings.get("background_color", "rgba(0,0,0,180)")
        self.bg_color_btn.setText(bg_color_str)
        self.bg_color_btn.setStyleSheet(
            f"background-color: {bg_color_str}; color: white; text-shadow: 1px 1px 2px black;")
        text_color_str = self.theme_settings.get("text_color", "white")
        self.text_color_btn.setText(text_color_str)
        self.text_color_btn.setStyleSheet(
            f"background-color: {text_color_str}; color: black; text-shadow: 1px 1px 2px white;")
        self.font_size_spinbox.setValue(self.theme_settings.get("font_size", 16))
        self.radius_spinbox.setValue(self.theme_settings.get("border_radius", 10))
        self.spacing_spinbox.setValue(self.theme_settings.get("item_spacing", 10))
        self.counter_font_size_spinbox.setValue(self.theme_settings.get("counter_font_size", 20))
        self.queue_counter_font_size_spinbox.setValue(self.theme_settings.get("queue_counter_font_size", 16))

    def _pick_color(self, button, use_rgba=True):
        try:
            initial_color = QColor(button.text())
        except ValueError:
            initial_color = QColor("white")
        dialog = QColorDialog(initial_color, self)
        if use_rgba:
            dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if dialog.exec():
            color = dialog.selectedColor()
            if use_rgba:
                color_str = f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
                button.setText(color_str)
                button.setStyleSheet(f"background-color: {color_str}; color: white; text-shadow: 1px 1px 2px black;")
            else:
                color_str = color.name()
                button.setText(color_str)
                button.setStyleSheet(f"background-color: {color_str}; color: black; text-shadow: 1px 1px 2px white;")

    # ==================== 其他 MainWindow 方法 ====================
    def _build_path_to_gift_id_map(self):
        self.path_to_gift_id_map.clear()
        gift_en_to_id = {g.get("name_en"): g.get("id") for g in self.gift_manager.get_all_gifts()}

        for item in self.tiktok_listener.gift_map:
            path = item.get("path")
            kw = item.get("kw")
            if path and kw:
                gift_id = gift_en_to_id.get(kw)
                if gift_id:
                    self.path_to_gift_id_map[path] = gift_id

    def _update_queue_counts_in_menu(self):
        if not self.game_menu_container:
            return

        queue_snapshot = self.queue.snapshot()
        path_counts = {}
        for path, note in queue_snapshot:
            path_counts[path] = path_counts.get(path, 0) + 1

        if not self.menu_overlay_window.isVisible():
            return

        list_widget = self.game_menu_container.list_widget
        for i in range(list_widget.count()):
            widget = list_widget.itemWidget(list_widget.item(i))
            if isinstance(widget, MenuItemWidget):
                gift_id = widget.gift_info.get("id")

                paths_for_this_gift = [
                    path for path, gid in self.path_to_gift_id_map.items() if gid == gift_id
                ]

                total_count = sum(path_counts.get(p, 0) for p in paths_for_this_gift)

                widget.set_queue_count(total_count, self.show_queue_counter_checkbox.isChecked())

    def _on_show_counter_toggled(self, checked: bool):
        if not self.game_menu_container or not self.menu_overlay_window.isVisible():
            return
        list_widget = self.game_menu_container.list_widget
        for i in range(list_widget.count()):
            list_item = list_widget.item(i)
            widget = list_widget.itemWidget(list_item)
            if isinstance(widget, MenuItemWidget):
                widget.show_counter(checked)

    def _reset_gift_counts(self):
        reply = QMessageBox.question(self, "確認", "確定要將所有禮物計數歸零嗎？")
        if reply == QMessageBox.StandardButton.Yes:
            self.gift_trigger_counts.clear()
            self._refresh_menu_content()
            self._log("所有禮物觸發計數已重設。")

    def _on_menu_edit_mode_toggled(self, checked):
        if checked:
            QMessageBox.information(self, "編輯模式提示",
                                    "菜單佈局現在應直接在直播軟體 (如 OBS) 中，\n"
                                    "透過調整『菜單 Overlay 視窗 (綠幕)』的來源大小和位置來完成。\n\n"
                                    "此按鈕僅用於視覺提示，無實際拖動功能。")
            self.btn_edit_menu_layout.setText("✅ 完成編輯")
        else:
            self.btn_edit_menu_layout.setText("🔒 編輯菜單佈局")

        if self.game_menu_container:
            self.game_menu_container.setEditing(checked)

    def _show_dev_log_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("開發日誌")
        dialog.setMinimumSize(500, 400)
        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(self.DEV_LOG_CONTENT)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(text_edit)
        layout.addWidget(button_box)
        dialog.exec()

    def _check_for_first_run(self):
        if not os.path.exists(self.GIFT_MAP_FILE) and not os.path.exists(self.LIBRARY_FILE):
            QMessageBox.information(
                self, "歡迎使用 Overlay UltraLite！",
                "這似乎是您第一次使用，請依照以下步驟開始：\n\n"
                "1. 在「媒體庫」分頁，點擊「+ 加入檔案」或直接將影片檔案拖曳進來。\n\n"
                "2. 在「TikTok 禮物設定」分頁，填寫您的直播網址和 API Key。\n\n"
                "3. 接著設定禮物與影片的對應關係，然後就可以開始監聽了！\n\n"
                "祝您使用愉快！")

    def _show_about_dialog(self):
        QMessageBox.about(
            self, "關於 Overlay UltraLite",
            f"<h2>Overlay UltraLite - {self.windowTitle().split(' ')[3]}</h2>"
            "<p>一個為 TikTok 直播設計的影片播放疊加工具。</p>"
            "<p>基於 PySide6 和 TikTokLive 函式庫開發。</p>")

    def _on_library_drag_enter(self, event: QEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_library_drop(self, event: QEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            video_files = [
                url.toLocalFile() for url in urls
                if url.isLocalFile() and url.toLocalFile().lower().endswith(
                    ('.mp4', '.mkv', '.mov', '.avi'))
            ]
            if video_files:
                self.lib_list.addItems(video_files)
                event.acceptProposedAction()

    def _show_library_context_menu(self, pos):
        item = self.lib_list.itemAt(pos)
        menu = QMenu()
        enqueue_action = menu.addAction("→ 加入待播")
        edit_layout_action = menu.addAction("調整版面")
        remove_action = menu.addAction("删除所選")
        if not item:
            enqueue_action.setEnabled(False)
            edit_layout_action.setEnabled(False)
            remove_action.setEnabled(False)
        action = menu.exec(self.lib_list.mapToGlobal(pos))
        if action == enqueue_action:
            self._enqueue_selected_from_library()
        elif action == edit_layout_action:
            self._enter_edit_mode()
        elif action == remove_action:
            self._remove_selected_from_library()

    def _refresh_menu_content(self):
        """刷新並設定遊戲菜單的內容，並更新計數"""
        if not self.game_menu_container:
            return

        self.game_menu_container.theme_settings = self.theme_settings
        self.game_menu_container.apply_theme()

        gifts = [
            g for g in self.gift_manager.get_all_gifts()
            if g.get("image_path") and g.get("description")
        ]

        self.game_menu_container.update_menu_data(
            gifts,
            self.gift_trigger_counts,
            self.show_counter_checkbox.isChecked()
        )

    def _toggle_menu_overlay_window(self):
        """切換新的菜單專用 Overlay 視窗的可見性"""
        if self.menu_overlay_window.isVisible():
            self.menu_overlay_window.hide()
        else:
            self._refresh_menu_content()
            self.menu_overlay_window.show()

    def _load_layouts(self) -> LayoutsData:
        # 與舊介面相容：回傳 dict，但實際由 LayoutsManager 管
        return self.layouts_mgr.load()

    def _save_layouts(self, data: Optional[LayoutsData] = None):
        # 寫入指定資料或目前 self.layouts
        self.layouts_mgr.save(data if data is not None else self.layouts)

    def _toggle_overlay_window(self):
        if self.overlay_window.isVisible():
            self.overlay_window.hide()
        else:
            self._update_overlay_geometry()
            self.overlay_window.show()

    def _update_overlay_geometry(self):
        if self.aspect_16_9.isChecked():
            self.overlay_window.setFixedSize(1280, 720)
        else:
            self.overlay_window.setFixedSize(720, 1280)
        self._update_child_geometries()

    def _get_video_dimensions(self, path: str) -> Optional[tuple[int, int]]:
        if path in self.video_dimensions_cache:
            return self.video_dimensions_cache[path]
        if not cv2:
            self._log("警告: cv2 模組不可用，無法獲取影片尺寸。使用預設值。")
            return (1920, 1080) if self.aspect_16_9.isChecked() else (1080, 1920)
        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                self._log(f"錯誤: 無法開啟影片 - {path}")
                return None
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.video_dimensions_cache[path] = (width, height)
            return width, height
        finally:
            if 'cap' in locals() and cap.isOpened():
                cap.release()

    def _enter_edit_mode(self):
        if self.is_editing or not self.lib_list.currentItem():
            return
        path = self.lib_list.currentItem().text()
        dims = self._get_video_dimensions(path)
        if not dims:
            QMessageBox.critical(self, "錯誤", "無法讀取影片尺寸")
            return

        self.is_editing = True
        self.video_container.set_editing(True)
        video_w, video_h = dims
        self.video_container.set_aspect_ratio(video_w / video_h if video_h > 0 else 1)
        print("\n" + "=" * 20 + " [進入版面編輯模式] " + "=" * 20)
        self.player.stop_playback()
        self._set_player_state(PlayerState.IDLE)

        aspect_ratio_str = "16:9" if self.aspect_16_9.isChecked() else "9:16"
        layout_ratio = self.layouts.get(path, {}).get(aspect_ratio_str)
        initial_rect = QRect()
        overlay_rect = self.overlay_window.contentsRect()

        if layout_ratio:
            x = layout_ratio['x'] * overlay_rect.width()
            y = layout_ratio['y'] * overlay_rect.height()
            w = layout_ratio['w'] * overlay_rect.width()
            h = layout_ratio['h'] * overlay_rect.height()
            initial_rect.setRect(int(x), int(y), int(w), int(h))
        else:
            overlay_w, overlay_h = overlay_rect.width(), overlay_rect.height()
            vid_ratio = video_w / video_h if video_h > 0 else 1
            w, h = 0.0, 0.0
            if (overlay_w / (overlay_h or 1)) > vid_ratio:
                h = float(overlay_h)
                w = h * vid_ratio
            else:
                w = float(overlay_w)
                h = w / vid_ratio
            x, y = (overlay_w - w) / 2.0, (overlay_h - h) / 2.0
            initial_rect.setRect(int(x), int(y), int(w), int(h))

        self.video_container.setGeometry(initial_rect)
        self._on_layout_var_change_by_user(initial_rect)
        self.player.set_mute(True)
        self.player.set_loop(0)
        self.player.command("loadfile", path, "replace")
        self._set_player_state(PlayerState.PLAYING, job_path=path)
        self.btn_preview_play_pause.setText("⏸ 暫停")
        self.editor_box.show()

    def _exit_edit_mode(self, save: bool):
        if not self.is_editing:
            return
        path = self.lib_list.currentItem().text()
        self.player.stop_playback()
        if save:
            rect = self.video_container.geometry()
            overlay_rect = self.overlay_window.contentsRect()
            if overlay_rect.width() > 0 and overlay_rect.height() > 0:
                layout = {
                    "x": rect.x() / overlay_rect.width(),
                    "y": rect.y() / overlay_rect.height(),
                    "w": rect.width() / overlay_rect.width(),
                    "h": rect.height() / overlay_rect.height()
                }
                aspect_ratio_str = "16:9" if self.aspect_16_9.isChecked() else "9:16"
                self.layouts.setdefault(path, {})[aspect_ratio_str] = layout
                self._save_layouts()

        self.is_editing = False
        self.video_container.set_editing(False)
        self._set_player_state(PlayerState.IDLE)
        self.editor_box.hide()
        self.player.set_loop(1)
        self.player.set_mute(False)
        self._play_next_if_idle()

    def _toggle_preview_pause(self):
        if not self.is_editing:
            return
        self.player.cycle_property("pause")
        QTimer.singleShot(50, self._update_pause_button_text)

    def _update_pause_button_text(self):
        current_pause_state = self.player.get_property("pause")
        if current_pause_state:
            self.btn_preview_play_pause.setText("▶ 播放")
        else:
            self.btn_preview_play_pause.setText("⏸ 暫停")

    def _stop_preview_and_seek_to_start(self):
        if not self.is_editing:
            return
        self.player.set_property("pause", True)
        self.player.command("seek", "0", "absolute")
        self._update_pause_button_text()

    def _on_layout_var_change_by_user(self, rect: QRect):
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        self.layout_vars_widgets['x'].setText(str(x))
        self.layout_vars_widgets['y'].setText(str(y))
        self.layout_vars_widgets['w'].setText(str(w))
        self.layout_vars_widgets['h'].setText(str(h))

    def _write_to_monitor(self, op, caller, size, note):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] op={op:<6} caller={caller:<22} size={size:<3} note={note}"
        self.monitor_list.addItem(line)
        self.monitor_list.scrollToBottom()

    def _log(self, s: str):
        self.monitor_list.addItem(s)
        self.monitor_list.scrollToBottom()

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇影片檔案", "", "影片檔案 (*.mp4 *.mkv *.mov *.avi)")
        if paths:
            self.lib_list.addItems(paths)

    def _enqueue_selected_from_library(self):
        if self.lib_list.currentItem():
            path = self.lib_list.currentItem().text()
            self.queue.enqueue(path, note=os.path.basename(path))
            self._play_next_if_idle()

    def _reset_selected_layout(self):
        if not self.lib_list.currentItem():
            return
        path = self.lib_list.currentItem().text()
        if path in self.layouts and QMessageBox.question(
                self, "確認",
                f"確定要重設 '{os.path.basename(path)}' 的版面嗎？"
        ) == QMessageBox.StandardButton.Yes:
            del self.layouts[path]
            self._save_layouts()
            self._log(f"已重設版面: {os.path.basename(path)}")

    def _remove_selected_from_library(self):
        if self.lib_list.currentItem():
            self.lib_list.takeItem(self.lib_list.currentRow())

    def _clear_library(self):
        if QMessageBox.question(
                self, "確認", "確定要清空媒體清單和所有版面嗎？"
        ) == QMessageBox.StandardButton.Yes:
            self.lib_list.clear()
            self.layouts.clear()
            self._save_layouts()
            self._auto_save_library()

    def _auto_save_library(self):
        try:
            items = [self.lib_list.item(i).text() for i in range(self.lib_list.count())]
            self.library_mgr.save_list(items)
        except IOError as e:
            self._log(f"錯誤: 無法自動儲存媒體清單到 {self.LIBRARY_FILE}: {e}")

    def _auto_load_library(self):
        if not os.path.exists(self.LIBRARY_FILE):
            return
        try:
            items = self.library_mgr.load_list()
            if isinstance(items, list):
                self.lib_list.addItems(items)
        except (IOError, json.JSONDecodeError) as e:
            self._log(f"錯誤: 無法自動載入媒體清單從 {self.LIBRARY_FILE}: {e}")

    def _save_library_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "另存媒體清單", "", "JSON 檔案 (*.json);;文字檔案 (*.txt)")
        if path:
            items = [self.lib_list.item(i).text() for i in range(self.lib_list.count())]
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    if path.endswith('.json'):
                        json.dump(items, f, indent=2)
                    else:
                        f.write('\n'.join(items))
            except IOError as e:
                self._log(f"錯誤: 無法儲存清單到 {path}: {e}")

    def _load_library_from(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "從檔案載入媒體清單", "", "JSON 檔案 (*.json);;文字檔案 (*.txt)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    if path.endswith('.json'):
                        items = json.load(f)
                    else:
                        items = [line.strip() for line in f if line.strip()]
                    if isinstance(items, list):
                        self.lib_list.clear()
                        self.lib_list.addItems(items)
                    else:
                        self._log(f"錯誤: 檔案 {path} 格式不正確。")
            except (IOError, json.JSONDecodeError) as e:
                self._log(f"錯誤: 無法從檔案載入清單 {path}: {e}")

    def _refresh_queue_view(self):
        self.q_list.clear()
        snapshot = self.queue.snapshot()
        if not snapshot:
            self.setWindowTitle(f"tiktok - V9.50 [待播: 0]")
            return

        display_items = []
        current_note = snapshot[0][1]
        count = 1
        for i in range(1, len(snapshot)):
            note = snapshot[i][1]
            if note == current_note:
                count += 1
            else:
                if count > 1:
                    display_items.append(f"{current_note} (x{count})")
                else:
                    display_items.append(current_note)
                current_note = note
                count = 1
        if count > 1:
            display_items.append(f"{current_note} (x{count})")
        else:
            display_items.append(current_note)

        self.q_list.addItems(display_items)
        self.setWindowTitle(f"tiktok - V9.50 [待播: {len(self.queue)}]")

    def _play_next_if_idle(self):
        if self.player_state != PlayerState.IDLE or self.is_editing:
            return
        job = self.queue.pop_next()
        if job:
            self._start_job(job[0])

    def _force_play_next(self):
        if self.is_editing:
            return
        if self.player_state in [PlayerState.PLAYING, PlayerState.STOPPED]:
            self.player.stop_playback()
        self._set_player_state(PlayerState.IDLE)
        self._play_next_if_idle()

    def _start_job(self, path: str):
        if not os.path.exists(path):
            self._log(f"錯誤: 檔案不存在 - {path}")
            self._play_next_if_idle()
            return

        self._set_player_state(PlayerState.PLAYING, job_path=path)
        self.player.set_loop(1)

        video_rect = self._apply_video_layout(path=path)
        self._last_video_geometry = video_rect

        self.player.set_volume(self.playback_volume)
        self.player.command("loadfile", path, "replace")

    def _on_playback_end(self):
        if self.is_editing:
            return

        self.player.stop_playback()
        self._set_player_state(PlayerState.IDLE)

        overlay_height = self.overlay_window.height()
        self.video_container.setGeometry(0, overlay_height - 1, 1, 1)

        QTimer.singleShot(10, self._play_next_if_idle)

    def _stop_current(self):
        if self.player_state == PlayerState.PLAYING:
            self.player.stop_playback()
            self._set_player_state(PlayerState.STOPPED)

            overlay_height = self.overlay_window.height()
            self.video_container.setGeometry(0, overlay_height - 1, 1, 1)

    def _update_child_geometries(self):
        if not self.overlay_window or not self.overlay_window.isVisible():
            return
        if not self.is_editing:
            self._apply_video_layout()

    def _apply_video_layout(self, path: Optional[str] = None) -> QRect:
        if not self.overlay_window.isVisible():
            return QRect()

        if path:
            target_path = path
            rect = self.overlay_window.contentsRect()
            aspect_ratio_str = "16:9" if self.aspect_16_9.isChecked() else "9:16"
            layout_ratio = self.layouts.get(target_path, {}).get(aspect_ratio_str)

            final_rect = QRect()
            if layout_ratio:
                x = int(layout_ratio['x'] * rect.width())
                y = int(layout_ratio['y'] * rect.height())
                w = int(layout_ratio['w'] * rect.width())
                h = int(layout_ratio['h'] * rect.height())
                final_rect.setRect(x, y, w, h)
            else:
                final_rect = rect

            self.video_container.setGeometry(final_rect)
            return final_rect
        elif self._last_video_geometry:
            self.video_container.setGeometry(self._last_video_geometry)
            return self._last_video_geometry
        return QRect()

    def _set_player_state(self,
                          new_state: PlayerState,
                          job_path: Optional[str] = None):
        self.player_state = new_state
        if new_state == PlayerState.PLAYING and job_path:
            self.current_job_path = job_path
            self.now_playing_label.setText(
                f"▶ 正在播放: {os.path.basename(job_path)}")
        elif new_state == PlayerState.IDLE:
            self.current_job_path = None
            self.now_playing_label.setText("▶ 播放結束，閒置中")
        elif new_state == PlayerState.STOPPED:
            self.current_job_path = None
            self.now_playing_label.setText("▶ 播放已手動停止")

    def _enqueue_video_from_gift(self, path: str, interrupt: bool, count: int):
        note = os.path.basename(path)
        if interrupt:
            self.queue.clear()
            self.queue.enqueue(path, repeat=count, note=note)
            self._force_play_next()
        else:
            self.queue.enqueue(path, repeat=count, note=note)
            self._play_next_if_idle()

        triggered_gift_key = None
        triggered_gift_id = None
        for item in self.tiktok_listener.gift_map:
            if item.get("path") == path:
                triggered_gift_key = item.get("kw")
                for gift in self.gift_manager.get_all_gifts():
                    if gift.get("name_en") == triggered_gift_key:
                        triggered_gift_id = gift.get("id")
                        break
                break

        if triggered_gift_id:
            current_count = self.gift_trigger_counts.get(triggered_gift_id, 0)
            self.gift_trigger_counts[triggered_gift_id] = current_count + count
            self._update_single_counter_in_menu(triggered_gift_id, self.gift_trigger_counts[triggered_gift_id])

        if triggered_gift_key and self.game_menu_container and self.menu_overlay_window.isVisible():
            self.game_menu_container.highlight_item_by_key(triggered_gift_key)

    def _update_single_counter_in_menu(self, gift_id: str, new_count: int):
        if not self.game_menu_container or not self.menu_overlay_window.isVisible():
            return

        list_widget = self.game_menu_container.list_widget
        for i in range(list_widget.count()):
            list_item = list_widget.item(i)
            widget = list_widget.itemWidget(list_item)
            if isinstance(widget, MenuItemWidget) and widget.gift_info.get("id") == gift_id:
                widget.set_count(new_count)
                break

    def _on_tiktok_event(self, event: dict):
        event_type = event.get("type")

        user = event.get('user', '匿名')
        message_content = event.get('message', '') or event.get('gift_name', '') or str(event.get('count', ''))
        event_key = (event_type, user, message_content)

        if event_key in self.recent_events:
            return

        self.recent_events.append(event_key)

        timestamp = time.strftime("%H:%M:%S")

        message = ""
        color = None
        if event_type == "LOG":
            self._log(f"[TikTok] [{event.get('tag', 'INFO')}] {event.get('message', '')}")
            return
        elif event_type == "COMMENT":
            msg = event.get('message', '')
            message = f"[{timestamp}] 💬 {user}: {msg}"
            self._check_comment_for_triggers(msg)
            # 從 GiftsTab 讀取朗讀設定
            if self.tab_gifts.read_comment_checkbox.isChecked():
                self.speech_engine.say(f"{user} 說 {msg}")
        elif event_type == "GIFT":
            gift_name = event.get('gift_name', '禮物')
            count = event.get('count', 1)
            message = f"[{timestamp}] 🎁 {user} 送出 {gift_name} x{count}"
            color = QColor("darkGreen")
        elif event_type == "LIKE":
            count = event.get('count', 1)
            message = f"[{timestamp}] ❤️ {user} 按了 {count} 個讚"
            color = QColor("red")
        elif event_type == "JOIN":
            message = f"[{timestamp}] 👋 {user} 進入了直播間"
            color = QColor("gray")
        elif event_type == "FOLLOW":
            message = f"[{timestamp}] 💖 {user} 關注了主播！"
            color = QColor("blue")
        else:
            message = f"[{timestamp}] {str(event)}"

        item = QListWidgetItem(message)
        if color:
            item.setForeground(color)
        self.events_list.addItem(item)
        if self.events_list.count() > 200:
            self.events_list.takeItem(0)
        self.events_list.scrollToBottom()
        self._log_realtime_event(message)

    def _check_comment_for_triggers(self, comment: str):
        comment_lower = comment.lower()
        for trigger in self.trigger_manager.get_all_triggers():
            keyword = trigger.get("keyword", "").lower()
            if keyword and keyword in comment_lower:
                triggered = False

                path = trigger.get("path")
                if path and os.path.exists(path):
                    self._log(f"關鍵字觸發: '{trigger.get('keyword')}' -> 播放 {os.path.basename(path)}")
                    self.tiktok_listener.on_video_triggered.emit(path, False, 1)
                    triggered = True

                tts_response = trigger.get("tts_response")
                if tts_response:
                    self._log(f"關鍵字觸發: '{trigger.get('keyword')}' -> 朗讀 '{tts_response}'")
                    self.speech_engine.say(tts_response)
                    triggered = True

                if triggered:
                    break

    def _log_realtime_event(self, message: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.event_log_buffer.append(f"[{timestamp}] {message}\n")
        if len(self.event_log_buffer) >= 100:
            self._flush_log_buffer_to_file()

    def _flush_log_buffer_to_file(self):
        if not self.event_log_buffer:
            return
        try:
            with open(self.EVENTS_LOG_FILE, "a", encoding="utf-8") as f:
                f.writelines(self.event_log_buffer)
            self.event_log_buffer.clear()
        except IOError as e:
            print(f"錯誤: 無法寫入即時動態日誌: {e}")

    def _on_tiktok_status(self, status: str):
        # 更新 GiftsTab 的狀態顯示與按鈕
        if hasattr(self, "tab_gifts"):
            self.tab_gifts.tiktok_status_label.setText(f"状态: {status}")
            if "已連線" in status or "已连线" in status:
                self.tab_gifts.tiktok_status_label.setStyleSheet("color: green; font-weight: bold;")
                self.tab_gifts.tiktok_start_btn.setEnabled(False)
                self.tab_gifts.tiktok_stop_btn.setEnabled(True)
            elif "錯誤" in status or "错误" in status or "已斷線" in status or "已断线" in status:
                self.tab_gifts.tiktok_status_label.setStyleSheet("color: red;")
                self.tab_gifts.tiktok_start_btn.setEnabled(True)
                self.tab_gifts.tiktok_stop_btn.setEnabled(False)
            elif "正在連線" in status or "正在连线" in status:
                self.tab_gifts.tiktok_status_label.setStyleSheet("color: orange;")
            else:
                self.tab_gifts.tiktok_status_label.setStyleSheet("")
                self.tab_gifts.tiktok_start_btn.setEnabled(True)
                self.tab_gifts.tiktok_stop_btn.setEnabled(False)

    # 舊版 gifts-tab 相關儲存/載入 → 改為呼叫 GiftsTab
    def _load_gift_map(self):
        if not os.path.exists(self.GIFT_MAP_FILE):
            return
        try:
            with open(self.GIFT_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.tab_gifts.load_settings(data)
            self.playback_volume = self.tab_gifts.playback_volume
        except (IOError, json.JSONDecodeError) as e:
            self._log(f"錯誤: 無法載入禮物設定: {e}")

    def _save_gift_map(self):
        try:
            data = self.tab_gifts.get_settings()
            with open(self.GIFT_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._build_path_to_gift_id_map()
        except IOError as e:
            self._log(f"錯誤: 無法儲存禮物設定: {e}")

    def _update_viewer_list(self):
        if not (self.tiktok_listener and self.tiktok_listener.running and self.tiktok_listener.client):
            self.viewer_count_label.setText("在线人数: N/A")
            return
        try:
            client = self.tiktok_listener.client
            self.viewer_count_label.setText(f"在线人数: {client.viewer_count}")
            current_viewers = {self.viewer_list.item(i).text() for i in range(self.viewer_list.count())}
            new_viewers = {viewer.nickname for viewer in client.viewers}
            if current_viewers != new_viewers:
                self.viewer_list.clear()
                self.viewer_list.addItems(sorted(list(new_viewers)))
        except Exception:
            pass

    def _manage_gift_list(self):
        dialog = GiftListDialog(self, gift_manager=self.gift_manager)
        dialog.exec()
        self._refresh_menu_content()

    def _on_volume_changed(self, value: int):
        self.playback_volume = value
        if self.player_state == PlayerState.PLAYING:
            self.player.set_volume(self.playback_volume)

    def closeEvent(self, event):
        self._flush_log_buffer_to_file()
        self._auto_save_library()
        self._save_gift_map()
        self.tiktok_listener.stop()
        self.player.terminate()
        if self.speech_engine:
            self.speech_engine.stop()
        if self.menu_overlay_window:
            self.menu_overlay_window.close()
        if self.overlay_window:
            self.overlay_window.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not _HAS_TIKTOK_LIVE:
        QMessageBox.critical(None, "缺少相依性",
                             "錯誤: 'TikTokLive' 函式庫未安裝。\n請執行: pip install TikTokLive")
        sys.exit(1)
    if not _HAS_MPV:
        QMessageBox.critical(
            None, "缺少相依性",
            "錯誤: 'python-mpv' 函式庫未安裝。\n請執行: pip install python-mpv")
        sys.exit(1)
    if not cv2:
        QMessageBox.warning(
            None, "缺少相依性",
            "警告: 'opencv-python' (cv2) 未安裝。\n將無法獲取影片的正確長寬比。")
    if not _HAS_PILLOW:
        QMessageBox.warning(
            None, "缺少相依性",
            "警告: 'Pillow' 函式庫未安裝。\n將無法支援 WebP 等圖片格式。\n請執行: pip install Pillow"
        )
    if not _HAS_TTS:
        QMessageBox.warning(
            None, "缺少相依性",
            "警告: 'pyttsx3' 函式庫未安裝。\n朗讀留言功能將無法使用。\n請執行: pip install pyttsx3 pypiwin32"
        )

    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())
