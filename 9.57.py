# -*- coding: utf-8 -*-
"""
Overlay UltraLite - V9.57 (Comment Translation)
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
from typing import Union

from PySide6.QtGui import (QColor,  QMouseEvent, QPaintEvent,
                            QDragEnterEvent, QDropEvent)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QRadioButton, QSplitter, QTabWidget,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget, QSlider, QSpinBox)
from PySide6.QtCore import Signal, QObject, QRect, Qt, QPointF,  QTimer, QPoint

from speech_engine import SpeechEngine
from ui_components import GiftListDialog, GameMenuContainer, MenuItemWidget, TriggerEditDialog
from trigger_manager import TriggerManager
from data_managers import LayoutsManager,  LibraryManager, ThemeManager
# 新增：Gemini 翻譯模組匯入（可缺省）
try:
    # 新增了 list_generation_models 的匯入
    from gemini_translator import Translator as GeminiTranslator, list_generation_models
    _HAS_GEMINI = True
except Exception:
    GeminiTranslator = None
    list_generation_models = None # 確保在 import 失敗時此變數存在
    _HAS_GEMINI = False
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
# --- Aho-Corasick 依賴（多關鍵字高效比對）---
try:
    import ahocorasick  # pip install pyahocorasick
    _HAS_AHOCORASICK = True
except ImportError:
    ahocorasick = None
    _HAS_AHOCORASICK = False
# --- 處理打包路徑的核心程式碼 ---
if getattr(sys, 'frozen', False):
    # 如果是在打包後的環境中運行
    application_path = os.path.dirname(sys.executable)
else:
    # 如果是在正常的 Python 環境中運行
    application_path = os.path.dirname(__file__)

# --- 處理結束 ---

def _fetch_models_in_process(api_key_str: str, result_queue):
    """
    此函式被設計在一個完全獨立的子進程中執行，以避免函式庫衝突。
    它使用 requests 函式庫來抓取模型清單。
    """
    try:
        import requests

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key_str}"

        # 設定較長的超時時間，以應對網路不穩定的情況
        response = requests.get(url, timeout=20)
        response.raise_for_status()  # 如果狀態碼不是 2xx，則拋出例外

        data = response.json()
        models_data = data.get("models", [])

        available_models = [
            m.get("name") for m in models_data
            if m.get("supportedGenerationMethods") and 'generateContent' in m.get("supportedGenerationMethods")
        ]

        short_names = sorted(list(set(n.split("/")[-1] for n in available_models if n)))

        # 將成功結果放入佇列
        result_queue.put(("SUCCESS", short_names))

    except Exception as e:
        # 將失敗的詳細錯誤訊息放入佇列
        error_message = f"{type(e).__name__}: {e}"
        result_queue.put(("FAILURE", error_message))


def _translate_in_process(api_key_str: str, model_name_str: str, text_to_translate: str, result_queue):
    """
    此函式在一個完全獨立的子進程中執行翻譯，以避免函式庫衝突。
    (新版：包含更嚴格的 Prompt 以獲得簡潔的翻譯結果)
    """
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key_str)
        model = genai.GenerativeModel(model_name_str)

        # --- 關鍵修改：使用一個非常嚴格和明確的 Prompt ---
        prompt = (
            "You are a translation engine. Your task is to translate the user's text into "
            "natural, colloquial, and fluent Traditional Chinese (Taiwanese Mandarin - 台灣正體中文). "
            "Follow these rules strictly:\n"
            "1. ONLY return the translated text.\n"
            "2. DO NOT include the original text.\n"
            "3. DO NOT include any explanations, annotations, or pinyin.\n"
            "4. DO NOT add any prefixes like '翻譯:' or '譯文:'.\n\n"
            f"Translate the following text: \"{text_to_translate}\""
        )

        response = model.generate_content(prompt)

        # 將成功結果放入佇列
        result_queue.put(("SUCCESS", response.text))

    except Exception as e:
        # 將失敗的詳細錯誤訊息放入佇列
        error_message = f"{type(e).__name__}: {e}"
        result_queue.put(("FAILURE", error_message))

# ==================== 型別宣告 & 資料類別 ====================
Layout = dict[str, float]
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

    def add_gifts_batch(self, gifts_to_add: List[GiftInfo]) -> int:
        """
        批次新增多個禮物，並只儲存一次。
        返回成功新增的禮物數量。
        """
        if not gifts_to_add:
            return 0

        # 為了避免重複，先建立一個現有英文名的集合
        existing_names = {g.get("name_en", "").lower() for g in self.gifts if g.get("name_en")}

        added_count = 0
        for new_gift in gifts_to_add:
            new_name_en = new_gift.get("name_en", "").lower()
            # 如果提供了英文名，且該名稱尚未存在，才進行新增
            if new_name_en and new_name_en not in existing_names:
                self.gifts.append(new_gift)
                existing_names.add(new_name_en)  # 更新集合，以防批次內部有重複
                added_count += 1

        # 如果有任何禮物被成功新增，才執行存檔
        if added_count > 0:
            self.save()

        return added_count

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

        # 新增：並發防護與工作階段 id
        self._lock = threading.RLock()
        self._session_id = 0  # 每次 start 都會 +1，用於讓舊 handler 失效

    @staticmethod
    def _extract_username(url: str) -> Optional[str]:
        m = re.search(r"tiktok\.com/@([^/?]+)", url)
        return m.group(1) if m else None

    def start(self, url: str, api_key: str):
        if not _HAS_TIKTOK_LIVE:
            self.on_event_received.emit({
                "type": "LOG", "tag": "ERROR", "message": "錯誤: 'TikTokLive' 函式庫未安裝"
            })
            return

        username = self._extract_username(url)
        if not username:
            self.on_event_received.emit({
                "type": "LOG", "tag": "ERROR", "message": "錯誤: 無效的 TikTok 直播網址"
            })
            return
        if not api_key:
            self.on_event_received.emit({
                "type": "LOG", "tag": "ERROR", "message": "錯誤: 必須提供 API Key"
            })
            return

        with self._lock:
            # 若先前仍在跑，直接阻擋（或改為先 stop 再啟動）
            if self.thread and self.thread.is_alive():
                self.on_event_received.emit({
                    "type": "LOG", "tag": "WARN", "message": "監聽已在執行，已忽略重複啟動。"
                })
                return

            # 保險：啟動前先嘗試清掉舊的 client/thread
            self._unsafe_cleanup()

            self.running = True
            self._session_id += 1
            session = self._session_id

            # 立即通知 UI 正在連線，並避免使用者連點
            self.on_status_change.emit(f"正在連線至 @{username}...")

            self.thread = threading.Thread(
                target=self._run_client, args=(username, api_key, session), daemon=True
            )
            self.thread.start()

    def stop(self):
        with self._lock:
            # 作廢所有舊 handler
            self._session_id += 1
            self.running = False

            if self.client:
                try:
                    self.client.stop()
                except OSError as e:
                    if "[WinError 6]" in str(e):
                        print("[INFO] 捕捉到良性的網路控制代碼關閉錯誤，已忽略。")
                    else:
                        self.on_event_received.emit({
                            "type": "LOG", "tag": "WARN", "message": f"停止 client 時發生 OSError: {e}"
                        })
                except Exception as e:
                    self.on_event_received.emit({
                        "type": "LOG", "tag": "WARN", "message": f"停止 client 時發生錯誤: {e}"
                    })

            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=2.0)

            self._unsafe_cleanup()
            self.on_status_change.emit("已停止")

    def _unsafe_cleanup(self):
        # 僅供內部呼叫：清理欄位，不發 signal
        self.client = None
        self.thread = None

    def _find_gift_map_match(self, gift_name: str, gift_id: int) -> Optional[GiftMapItem]:
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

    def _run_client(self, username: str, api_key: str, session: int):
        # 簡單自動重連（指數退避），避免「冷清就斷」後需要手動點開始
        backoff = 1.0
        MAX_BACKOFF = 30.0

        def still_valid() -> bool:
            # 僅當前 session 且 running 才處理事件
            return self.running and (session == self._session_id)

        while still_valid():
            try:
                if WebDefaults:
                    WebDefaults.tiktok_sign_api_key = api_key

                self.client = TikTokLiveClient(unique_id=f"@{username}")

                @self.client.on(ConnectEvent)
                async def on_connect(_: ConnectEvent):
                    if not still_valid():
                        return
                    self.on_event_received.emit({
                        "type": "LOG", "tag": "INFO", "message": f"已連線至 @{username} 的直播間。"
                    })
                    self.on_status_change.emit(f"已連線: @{username}")

                @self.client.on(DisconnectEvent)
                async def on_disconnect(_: DisconnectEvent):
                    if not still_valid():
                        return
                    self.on_event_received.emit({
                        "type": "LOG", "tag": "INFO", "message": "已從直播間斷線。"
                    })
                    self.on_status_change.emit("已斷線")

                @self.client.on(CommentEvent)
                async def on_comment(evt: CommentEvent):
                    if not still_valid():
                        return
                    self.on_event_received.emit({
                        "type": "COMMENT", "user": evt.user.nickname, "message": evt.comment
                    })

                @self.client.on(GiftEvent)
                async def on_gift(evt: GiftEvent):
                    if not still_valid():
                        return
                    gift = evt.gift
                    # combo 未結束時不重複觸發
                    if gift.combo and not evt.repeat_end:
                        return
                    self.on_event_received.emit({
                        "type": "GIFT",
                        "user": evt.user.nickname,
                        "gift_name": gift.name,
                        "count": evt.repeat_count
                    })
                    self.on_status_change.emit(f"收到禮物: {gift.name} x{evt.repeat_count}")

                    match = self._find_gift_map_match(gift.name, gift.id)
                    if match:
                        path = match.get("path")
                        if path and os.path.exists(path):
                            self.on_event_received.emit({
                                "type": "LOG",
                                "tag": "DEBUG",
                                "message": f"匹配成功: {gift.name} -> {os.path.basename(path)}"
                            })
                            # 核心：僅在有效 session 下發射觸發
                            if still_valid():
                                self.on_video_triggered.emit(path, self.interrupt_on_gift, evt.repeat_count)
                        else:
                            self.on_event_received.emit({
                                "type": "LOG", "tag": "WARN", "message": f"匹配成功但檔案不存在: {path}"
                            })
                    elif self.fallback_video_path and os.path.exists(self.fallback_video_path):
                        self.on_event_received.emit({
                            "type": "LOG", "tag": "DEBUG", "message": "無匹配，播放後備影片。"
                        })
                        if still_valid():
                            self.on_video_triggered.emit(self.fallback_video_path, self.interrupt_on_gift, evt.repeat_count)

                @self.client.on(LikeEvent)
                async def on_like(event: LikeEvent):
                    if not still_valid():
                        return
                    self.on_event_received.emit({
                        "type": "LIKE", "user": event.user.nickname, "count": event.count
                    })

                @self.client.on(JoinEvent)
                async def on_join(event: JoinEvent):
                    if not still_valid():
                        return
                    self.on_event_received.emit({
                        "type": "JOIN", "user": event.user.nickname
                    })

                @self.client.on(FollowEvent)
                async def on_follow(event: FollowEvent):
                    if not still_valid():
                        return
                    self.on_event_received.emit({
                        "type": "FOLLOW", "user": event.user.nickname
                    })

                # 執行，直到正常結束或丟例外
                self.client.run()

                # 若是正常返回（例如遠端關閉），嘗試依退避策略重連
                if not still_valid():
                    break
                self.on_event_received.emit({
                    "type": "LOG", "tag": "INFO", "message": f"連線結束，{int(backoff)} 秒後自動重試..."
                })
                time.sleep(backoff)
                backoff = min(MAX_BACKOFF, max(1.0, backoff * 2))
            except Exception as e:
                if not still_valid():
                    break
                self.on_event_received.emit({
                    "type": "LOG", "tag": "ERROR", "message": f"TikTok 連線失敗: {e}，{int(backoff)} 秒後重試。"
                })
                self.on_status_change.emit("連線錯誤")
                time.sleep(backoff)
                backoff = min(MAX_BACKOFF, max(1.0, backoff * 2))
            finally:
                # 保險：嘗試停止並清理 client 實例
                try:
                    if self.client:
                        self.client.stop()
                except Exception:
                    pass
                self.client = None

        # 跳出重連迴圈
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
        self._desired_volume = 100

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
                    # 開啟 >100 音量的支援，與 UI 0..150 一致
                    volume_max=150,
                )

                @self._p.event_callback('end-file')
                def _(event):
                    self._on_end_file(event)

                @self._p.event_callback('file-loaded')
                def _(_event):
                    # 統一用 command，避免某些 build 下 set_property 不穩
                    try:
                        self._p.command("set", "volume", str(self._desired_volume))
                    except MPV_CALL_ERRORS as e:
                        self._on_log(f"[MPV] set volume on file-loaded failed: {e}")

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
        try:
            self.command("set", "mute", "yes" if muted else "no")
        except MPV_CALL_ERRORS as e:
            self._on_log(f"[MPV] set mute failed: {e}")

    # PlayerWrapper 內
    def set_volume(self, volume: int):
        vol = max(0, min(150, int(volume)))
        self._desired_volume = vol
        try:
            self.command("set", "volume", str(vol))
        except MPV_CALL_ERRORS as e:
            self._on_log(f"[MPV] set volume failed: {e}")

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
            # 以滑鼠移動量計算新矩形
            delta = event.globalPosition() - self._start_pos
            dx = int(delta.x())
            dy = int(delta.y())

            x, y, w, h = (self._start_geom.x(), self._start_geom.y(),
                          self._start_geom.width(), self._start_geom.height())
            ar = self._aspect_ratio
            MIN_W, MIN_H = 20, 20

            corner = self._current_corner or ""

            if corner == "tl":
                # 固定右下角，改變左上角
                new_w = max(MIN_W, w - dx)
                new_h = max(MIN_H, int(new_w / ar))
                nx = x + (w - new_w)
                ny = y + (h - new_h)
                new_rect = QRect(nx, ny, new_w, new_h)
            elif corner == "tr":
                # 固定左下角，改變右上角
                new_w = max(MIN_W, w + dx)
                new_h = max(MIN_H, int(new_w / ar))
                nx = x
                ny = y + (h - new_h)
                new_rect = QRect(nx, ny, new_w, new_h)
            elif corner == "bl":
                # 固定右上角，改變左下角
                new_w = max(MIN_W, w - dx)
                new_h = max(MIN_H, int(new_w / ar))
                nx = x + (w - new_w)
                ny = y
                new_rect = QRect(nx, ny, new_w, new_h)
            elif corner == "br":
                # 固定左上角，改變右下角
                new_w = max(MIN_W, w + dx)
                new_h = max(MIN_H, int(new_w / ar))
                nx = x
                ny = y
                new_rect = QRect(nx, ny, new_w, new_h)
            else:
                # 非角落：拖曳移動整個矩形
                nx = x + dx
                ny = y + dy
                new_rect = QRect(nx, ny, w, h)

            # 限制在父視窗內容區域內
            new_rect = self._bounded_rect(new_rect)
            self.setGeometry(new_rect)
            self.layout_changed_by_user.emit(new_rect)
        else:
            self.set_cursor_for_pos(event.position())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self._is_editing:
            return
        self._is_dragging = False
        self.set_cursor_for_pos(event.position())
        event.accept()

    def _get_corner(self, pos: QPoint, margin: int = 15) -> str:
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

    def set_cursor_for_pos(self, pos: Union[QPoint, QPointF, tuple[int, int]]) -> None:
        if not self._is_editing:
            self.unsetCursor()
            return
        if isinstance(pos, QPointF):
            pos = pos.toPoint()
        elif isinstance(pos, tuple):
            pos = QPoint(pos[0], pos[1])
        corner = self._get_corner(pos)
        if corner in ('tl', 'br'):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif corner in ('tr', 'bl'):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    # noinspection PyPep8Naming
    def setCursorForPos(self, pos):  # noqa: N802
        self.set_cursor_for_pos(pos)

    def _bounded_rect(self, rect: QRect) -> QRect:
        """將矩形限制在父視窗內容區域內，並避免超出邊界。"""
        parent = self.parent()
        if not isinstance(parent, QWidget):
            return rect
        bounds = parent.contentsRect()
        # 修正到父視窗座標系
        bounds.moveTo(0, 0)

        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        # 限制寬高不超過父視窗
        w = min(w, max(1, bounds.width()))
        h = min(h, max(1, bounds.height()))

        # 限制位置
        x = max(bounds.left(), min(x, bounds.right() - w + 1))
        y = max(bounds.top(), min(y, bounds.bottom() - h + 1))

        return QRect(x, y, w, h)

# ==================== Overlay 視窗 ===================
class OverlayWindow(QWidget):
    def __init__(self, owner: 'MainWindow', parent=None):
        super().__init__(parent)
        self.main_window = owner
        self.setWindowTitle("影片 Overlay 播放視窗")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        # 明確不置頂（修正這一行）
        #self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        # 顯示時不搶焦點
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet("background-color: rgba(0, 255, 0, 80);")


class MenuOverlayWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("菜單 Overlay 視窗 (綠幕)")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        # 明確不置頂（修正這一行）
        #self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        # 顯示時不搶焦點
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

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
                 library_paths: Optional[List[str]] = None,
                 gift_list: Optional[List[GiftInfo]] = None):
        super().__init__(parent)
        self.setWindowTitle("編輯禮物映射")
        self.item = item or {}
        library_paths = library_paths or []
        gift_list = gift_list or []
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

        buttons = QDialogButtonBox(self)

        # 逐一加入標準按鈕，QDialogButtonBox 會自動賦予正確角色
        ok_btn = buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)

        # 體驗最佳化：Enter 預設觸發 OK；Esc 預設觸發 reject（Qt 也會處理 Esc）
        ok_btn.setDefault(True)
        ok_btn.setAutoDefault(True)
        cancel_btn.setAutoDefault(False)

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
    (新版：統一管理連線、翻譯、朗讀的所有相關設定)
    """

    def __init__(self,
                 owner: 'MainWindow',
                 tiktok_listener: TikTokListener,
                 gift_manager: GiftManager,
                 get_library_paths: Callable[[], List[str]],
                 log_func: Callable[[str], None],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.main = owner
        self.listener = tiktok_listener
        self.gift_manager = gift_manager
        self.get_library_paths = get_library_paths
        self._log = log_func
        self.playback_volume = 100
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- 第一部分：連線與核心設定 ---
        connect_group = QGroupBox("TikTok 連線設定")
        connect_layout = QGridLayout(connect_group)

        connect_layout.addWidget(QLabel("直播網址:"), 0, 0)
        self.tiktok_url_entry = QLineEdit()
        self.tiktok_url_entry.setPlaceholderText("https://www.tiktok.com/@username/live")
        connect_layout.addWidget(self.tiktok_url_entry, 0, 1, 1, 2)

        connect_layout.addWidget(QLabel("TikTok API Key:"), 1, 0) # <--- 修改標籤文字
        self.tiktok_api_key_entry = QLineEdit()
        self.tiktok_api_key_entry.setPlaceholderText("從 eulerstream.com 取得") # <--- 修改提示文字
        self.tiktok_api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        connect_layout.addWidget(self.tiktok_api_key_entry, 1, 1, 1, 2)

        self.tiktok_start_btn = QPushButton("开始监听")
        self.tiktok_stop_btn = QPushButton("停止监听")
        self.tiktok_status_label = QLabel("状态: 未连线")
        self.tiktok_stop_btn.setEnabled(False)
        connect_layout.addWidget(self.tiktok_start_btn, 2, 0)
        connect_layout.addWidget(self.tiktok_stop_btn, 2, 1)
        connect_layout.addWidget(self.tiktok_status_label, 2, 2, 1, -1)

        layout.addWidget(connect_group)

        # --- 第二部分：禮物映射與影片 ---
        main_splitter = QSplitter(Qt.Orientation.Vertical)

        gift_map_group = QGroupBox("礼物 -> 影片 映射")
        map_layout = QVBoxLayout(gift_map_group)
        self.gift_tree = QTreeWidget()
        self.gift_tree.setColumnCount(2)
        self.gift_tree.setHeaderLabels(["礼物", "影片路径"])
        self.gift_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        map_layout.addWidget(self.gift_tree)
        map_btn_layout = QHBoxLayout()
        btn_add_gift = QPushButton("新增")
        btn_edit_gift = QPushButton("编辑")
        btn_del_gift = QPushButton("删除")
        btn_manage_gifts = QPushButton("礼物清单...")
        map_btn_layout.addWidget(btn_add_gift)
        map_btn_layout.addWidget(btn_edit_gift)
        map_btn_layout.addWidget(btn_del_gift)
        map_btn_layout.addStretch()
        map_btn_layout.addWidget(btn_manage_gifts)
        map_layout.addLayout(map_btn_layout)
        main_splitter.addWidget(gift_map_group)

        # --- 第三部分：功能選項 (使用 QTabWidget) ---
        options_tabs = QTabWidget()

        # Tab 1: 播放選項
        playback_tab = QWidget()
        playback_layout = QVBoxLayout(playback_tab)

        fallback_group = QGroupBox("后备影片 (无匹配时播放)")
        fallback_layout = QHBoxLayout(fallback_group)
        self.fallback_video_entry = QLineEdit()
        self.fallback_video_entry.setReadOnly(True)
        btn_pick_fallback = QPushButton("选择档案...")
        fallback_layout.addWidget(self.fallback_video_entry, 1)
        fallback_layout.addWidget(btn_pick_fallback)
        playback_layout.addWidget(fallback_group)

        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("觸發媒體音量:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 150)
        self.volume_slider.setValue(100)
        self.volume_spinbox = QSpinBox()
        self.volume_spinbox.setRange(0, 150)
        self.volume_spinbox.setValue(100)
        self.volume_slider.valueChanged.connect(self.volume_spinbox.setValue)
        self.volume_spinbox.valueChanged.connect(self.volume_slider.setValue)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_spinbox)
        playback_layout.addLayout(volume_layout)

        self.interrupt_checkbox = QCheckBox("新礼物插队播放")
        playback_layout.addWidget(self.interrupt_checkbox)
        playback_layout.addStretch()
        options_tabs.addTab(playback_tab, "🎬 播放")

        # Tab 2: 朗讀選項
        tts_tab = QWidget()
        tts_layout = QVBoxLayout(tts_tab)
        self.read_comment_checkbox = QCheckBox("朗讀觀眾留言")
        if not _HAS_TTS:
            self.read_comment_checkbox.setDisabled(True)
            self.read_comment_checkbox.setToolTip("錯誤: 'pyttsx3' 函式庫未安裝")
        tts_layout.addWidget(self.read_comment_checkbox)

        tts_filter_group = QGroupBox("朗讀過濾選項")
        tts_filter_layout = QVBoxLayout(tts_filter_group)
        filter_hbox = QHBoxLayout()
        self.tts_filter_checkbox = QCheckBox("啟用暱稱過濾")
        self.tts_filter_edit = QLineEdit()
        self.tts_filter_edit.setPlaceholderText("輸入關鍵字，用逗號分隔 (例: bot,機器人)")
        filter_hbox.addWidget(self.tts_filter_checkbox)
        filter_hbox.addWidget(self.tts_filter_edit)
        tts_filter_layout.addLayout(filter_hbox)
        self.tts_truncate_checkbox = QCheckBox("只朗讀觀眾暱稱的前 6 個字")
        tts_filter_layout.addWidget(self.tts_truncate_checkbox)
        tts_layout.addWidget(tts_filter_group)
        tts_layout.addStretch()
        options_tabs.addTab(tts_tab, "💬 朗讀")

        # Tab 3: 翻譯選項
        trans_tab = QWidget()
        trans_layout = QGridLayout(trans_tab)
        self.translate_checkbox = QCheckBox("自動翻譯外語留言 (非中文→繁中)")
        self.show_original_comment_checkbox = QCheckBox("同時顯示原文於動態")
        # --- 新增 Gemini API Key 輸入框 ---
        self.gemini_api_key_edit = QLineEdit()
        self.gemini_api_key_edit.setPlaceholderText("在此輸入你的 Gemini API Key")
        self.gemini_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.setEditable(False)
        self.gemini_model_combo.setPlaceholderText("請先輸入 API Key 後按『重新載入』")
        self.btn_reload_models = QPushButton("重新載入模型清單")

        # 重新安排版面
        trans_layout.addWidget(self.translate_checkbox, 0, 0, 1, 2)
        trans_layout.addWidget(self.show_original_comment_checkbox, 1, 0, 1, 2)
        trans_layout.addWidget(QLabel("Gemini API Key:"), 2, 0)
        trans_layout.addWidget(self.gemini_api_key_edit, 2, 1)
        trans_layout.addWidget(QLabel("翻譯模型:"), 3, 0)
        trans_layout.addWidget(self.gemini_model_combo, 3, 1)
        trans_layout.addWidget(self.btn_reload_models, 4, 1)

        trans_tab.setLayout(trans_layout)
        options_tabs.addTab(trans_tab, "🌐 翻譯")

        main_splitter.addWidget(options_tabs)
        main_splitter.setSizes([400, 200])
        layout.addWidget(main_splitter, 1)

        # 事件連接
        self.tiktok_start_btn.clicked.connect(self._start_tiktok_listener)
        self.tiktok_stop_btn.clicked.connect(self._stop_tiktok_listener)
        self.gift_tree.itemDoubleClicked.connect(self._on_gift_tree_double_clicked)
        btn_add_gift.clicked.connect(self._add_gift_map)
        btn_edit_gift.clicked.connect(self._edit_gift_map)
        btn_del_gift.clicked.connect(self._remove_gift_map)
        btn_manage_gifts.clicked.connect(lambda: self.main._manage_gift_list())
        btn_pick_fallback.clicked.connect(self._pick_fallback_video)

        # 所有設定變更都觸發儲存
        self.tiktok_url_entry.editingFinished.connect(self.main._save_gift_map)
        self.tiktok_api_key_entry.editingFinished.connect(self.main._save_gift_map)
        self.gemini_api_key_edit.editingFinished.connect(self.main._save_gift_map)
        self.fallback_video_entry.textChanged.connect(self.main._save_gift_map)
        self.interrupt_checkbox.toggled.connect(self.main._save_gift_map)
        self.volume_spinbox.valueChanged.connect(self._on_volume_changed)
        self.read_comment_checkbox.toggled.connect(self.main._save_gift_map)
        self.tts_filter_checkbox.toggled.connect(self.main._save_gift_map)
        self.tts_filter_edit.editingFinished.connect(self.main._save_gift_map)
        self.tts_truncate_checkbox.toggled.connect(self.main._save_gift_map)
        self.translate_checkbox.toggled.connect(self.main._save_gift_map)
        self.show_original_comment_checkbox.toggled.connect(self.main._save_gift_map)
        self.gemini_model_combo.currentIndexChanged.connect(self.main._save_gift_map)
        self.btn_reload_models.clicked.connect(lambda: self.main._refresh_gemini_models_async())

    def _start_tiktok_listener(self):
        url = self.tiktok_url_entry.text().strip()
        api_key = self.tiktok_api_key_entry.text().strip()
        if not url or not api_key:
            QMessageBox.warning(self, "提示", "請同時輸入直播網址和 API Key。")
            return
        self.tiktok_start_btn.setEnabled(False)
        self.tiktok_stop_btn.setEnabled(True)
        self.tiktok_status_label.setText("状态: 正在连线...")
        self.listener.interrupt_on_gift = self.interrupt_checkbox.isChecked()
        self.listener.start(url, api_key)

    def _stop_tiktok_listener(self):
        self.listener.stop()
        self.tiktok_start_btn.setEnabled(True)
        self.tiktok_stop_btn.setEnabled(False)
        self.tiktok_status_label.setText("状态: 已停止")

    def _refresh_gift_tree(self):
        self.gift_tree.clear()
        gift_name_map = {g.get("name_en"): g.get("name_cn", g.get("name_en")) for g in
                         self.gift_manager.get_all_gifts()}
        for item in self.listener.gift_map:
            kw, gid, path = item.get("kw", ""), item.get("gid", ""), item.get("path", "")
            display_name = gift_name_map.get(kw, kw)
            id_str = f"(ID: {gid})" if gid else ""
            tree_item = QTreeWidgetItem([f"{display_name} {id_str}".strip(), os.path.basename(path) if path else "N/A"])
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
        dialog = GiftMapDialog(self, library_paths=library_paths, gift_list=self.gift_manager.get_all_gifts())
        if dialog.exec():
            new_data = dialog.get_data()
            if not new_data.get("path") or not (new_data.get("kw") or new_data.get("gid")):
                QMessageBox.warning(self, "提示", "必須選擇一個禮物和一個影片檔案。")
                return
            self.listener.gift_map.append(new_data)
            self._refresh_gift_tree()
            self.main._save_gift_map()

    def _edit_gift_map(self):
        selected = self.gift_tree.currentItem()
        if not selected: return
        index = self.gift_tree.indexOfTopLevelItem(selected)
        if index < 0: return
        dialog = GiftMapDialog(self, item=self.listener.gift_map[index], library_paths=self.get_library_paths(),
                               gift_list=self.gift_manager.get_all_gifts())
        if dialog.exec():
            updated_data = dialog.get_data()
            if not updated_data.get("path") or not (updated_data.get("kw") or updated_data.get("gid")):
                QMessageBox.warning(self, "提示", "必須選擇一個禮物和一個影片檔案。")
                return
            self.listener.gift_map[index] = updated_data
            self._refresh_gift_tree()
            self.main._save_gift_map()

    def _remove_gift_map(self):
        selected = self.gift_tree.currentItem()
        if not selected: return
        index = self.gift_tree.indexOfTopLevelItem(selected)
        if index >= 0 and QMessageBox.question(self, "確認刪除",
                                               f"確定要刪除「{selected.text(0)}」這個映射嗎？") == QMessageBox.StandardButton.Yes:
            del self.listener.gift_map[index]
            self._refresh_gift_tree()
            self.main._save_gift_map()

    def _pick_fallback_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇後備影片", "", "影片檔案 (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.fallback_video_entry.setText(path)

    def _on_gift_tree_double_clicked(self, item: QTreeWidgetItem, _):
        index = self.gift_tree.indexOfTopLevelItem(item)
        if index < 0: return
        path = self.listener.gift_map[index].get("path")
        if not (path and os.path.exists(path)):
            QMessageBox.warning(self, "提示", "該映射的影片檔案不存在或未設定。")
            return
        count, ok = QInputDialog.getInt(self, "輸入播放次數", f"請輸入「{os.path.basename(path)}」的播放次數：", 1, 1, 999,
                                        1)
        if ok:
            self.main._enqueue_video_from_gift(path, False, count)
            self._log(f"已手動將「{os.path.basename(path)}」加入待播清單 {count} 次。")

    def _on_volume_changed(self, value: int):
        self.playback_volume = value
        self.main._on_volume_changed(value)
        self.main._save_gift_map()

    def load_settings(self, data: dict):
        # 分別讀取兩個 Key
        self.tiktok_url_entry.setText(data.get("tiktok_url", ""))
        self.tiktok_api_key_entry.setText(data.get("tiktok_api_key", ""))  # 使用 tiktok_api_key
        self.gemini_api_key_edit.setText(data.get("gemini_api_key", ""))  # 使用 gemini_api_key

        self.listener.gift_map = data.get("gift_map", [])
        self.listener.fallback_video_path = data.get("fallback_video", "")
        self.fallback_video_entry.setText(self.listener.fallback_video_path)
        self.interrupt_checkbox.setChecked(data.get("interrupt_on_gift", False))
        self.playback_volume = data.get("playback_volume", 100)
        self.volume_slider.setValue(self.playback_volume)
        self.read_comment_checkbox.setChecked(data.get("read_comment", False))
        self.tts_filter_checkbox.setChecked(data.get("tts_filter_enabled", False))
        self.tts_filter_edit.setText(data.get("tts_filter_keywords", ""))
        self.tts_truncate_checkbox.setChecked(data.get("tts_truncate_enabled", False))
        self.translate_checkbox.setChecked(data.get("translate_enabled", False))
        self.show_original_comment_checkbox.setChecked(data.get("show_original", True))

        model = data.get("gemini_model", "gemini-1.5-flash")
        if self.gemini_model_combo.findData(model) == -1:
            self.gemini_model_combo.addItem(model, userData=model)
        self.gemini_model_combo.setCurrentIndex(self.gemini_model_combo.findData(model))

        self._refresh_gift_tree()
        self.main._on_translation_settings_changed()

    def get_settings(self) -> dict:
        model = ""
        if self.gemini_model_combo.count() > 0:
            model = self.gemini_model_combo.currentData() or self.gemini_model_combo.currentText()

        return {
            "tiktok_url": self.tiktok_url_entry.text().strip(),
            "tiktok_api_key": self.tiktok_api_key_entry.text().strip(),  # 分開儲存
            "gemini_api_key": self.gemini_api_key_edit.text().strip(),  # 分開儲存
            "gift_map": self.listener.gift_map,
            "fallback_video": self.fallback_video_entry.text(),
            "interrupt_on_gift": self.interrupt_checkbox.isChecked(),
            "playback_volume": self.playback_volume,
            "read_comment": self.read_comment_checkbox.isChecked(),
            "tts_filter_enabled": self.tts_filter_checkbox.isChecked(),
            "tts_filter_keywords": self.tts_filter_edit.text().strip(),
            "tts_truncate_enabled": self.tts_truncate_checkbox.isChecked(),
            "translate_enabled": self.translate_checkbox.isChecked(),
            "show_original": self.show_original_comment_checkbox.isChecked(),
            "gemini_model": self.main._normalize_model_name(model),
        }

class LibraryListWidget(QListWidget):
    # 拖入的檔案清單會透過這個訊號丟給外部（MainWindow）
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            exts = ('.mp4', '.mkv', '.mov', '.avi')
            files = [
                url.toLocalFile() for url in urls
                if url.isLocalFile() and url.toLocalFile().lower().endswith(exts)
            ]
            if files:
                self.filesDropped.emit(files)
                event.acceptProposedAction()
                return
        event.ignore()
# ==================== 主 GUI 應用 ===================
class MainWindow(QMainWindow):
    LAYOUT_FILE = os.path.join(application_path, "layouts.json")
    LIBRARY_FILE = os.path.join(application_path, "library.json")
    GIFT_MAP_FILE = os.path.join(application_path, "gift_map.json")
    GIFT_LIST_FILE = os.path.join(application_path, "gifts.json")
    EVENTS_LOG_FILE = os.path.join(application_path, "events_log.txt")
    THEME_FILE = os.path.join(application_path, "theme.json")
    TRIGGER_FILE = os.path.join(application_path, "triggers.json")
    AUDIO_LEVELS_FILE = os.path.join(application_path, "audio_levels.json")


    DEV_LOG_CONTENT = """<h3>版本更新歷史</h3>
        <p><b>V9.57 (Comment Translation)</b></p>
        <ul>
          <li>新增：自動翻譯外語留言（Gemini）。只翻非中文→繁中，結果以橘色顯示，且可選擇先翻譯再朗讀。</li>
          <li>設定：即時動態分頁底部提供開關與 API Key，設定儲存於 translation.json。</li>
        </ul>
        <p><b>V9.56 (Per-Item Volume)</b></p>
        <ul>
          <li>每個媒體檔案的個別相對音量（0~200%），播時套用「主音量 × 個別音量」。</li>
          <li>載入/刪除/清空媒體清單時，修剪殘留的個別音量與版面設定；去除失效禮物映射。</li>
          <li>UI：標題/待播計數標題統一顯示版本字樣。</li>
        </ul>
        ...（其餘版本保留）
        """
    VERSION = "V9.57 (Comment Translation)"
    def __init__(self):
        super().__init__()
        #self._is_loading_settings = False  # <--- 新增這一行
        self._ac = None  # Aho-Corasick automaton (若可用)
        self._trigger_by_keyword = {}  # keyword(lower) -> trigger dict
        self._trigger_regex = None  # 回退方案：單一正則（alternation）
        self.setWindowTitle(f"Overlay UltraLite - {self.VERSION}")
        self.setGeometry(100, 100, 1200, 800)

        # --- 1. 初始化所有屬性 ---
        self.layouts_mgr = LayoutsManager(self.LAYOUT_FILE)
        self.layouts = self.layouts_mgr.load()

        #self.settings_mgr = SettingsManager(self.GIFT_MAP_FILE)
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

        self.per_item_volume: Dict[str, int] = {}
        # 翻譯設定
        self.auto_translate_enabled: bool = False
        self.gemini_api_key: str = ""
        self._translator: Optional[GeminiTranslator] = None
        # 新增這兩行（就在翻譯設定這段之後）
        self.gemini_model: str = ""
        self._translator_model: str = ""
        # 折疊狀態（新增）
        self._overlay_collapsed = False
        self._overlay_saved_geometry: Optional[QRect] = None
        #self._menu_collapsed = False
        #self._menu_saved_geometry: Optional[QRect] = None

        self._overlay_pending_size: Optional[tuple[int, int]] = None
        # 初始化所有計時器
        self.log_write_timer = QTimer(self)
        self.viewer_list_updater = QTimer(self)
        self.tts_queue_refresh_timer = QTimer(self)
        #self.queue_count_update_timer = QTimer(self)

        self._overlay_prev_opacity: float = 1.0
        #self._menu_prev_opacity: float = 1.0  # 新增：菜單視窗前一個不透明度

        # --- 2. 設定 UI ---
        self._setup_ui()

        # --- 3. 連接所有信號和槽 ---
        self._setup_connections()

        # --- 4. 載入初始資料 ---
        QTimer.singleShot(0, self._perform_initial_load)
        # --- 5. 啟動所有計時器 ---
        self.viewer_list_updater.start(5000)
        self.log_write_timer.start(5000)
        self.tts_queue_refresh_timer.start(1000)
        #self.queue_count_update_timer.start(1000)

        #self._check_for_first_run()
        #self._rebuild_trigger_matcher()

    def _on_translation_settings_changed(self):
        """當 GiftsTab 中的翻譯設定改變時，由此方法更新主視窗的狀態。"""
        if not hasattr(self, "tab_gifts"):
            return

        # 從 GiftsTab 同步設定到 MainWindow
        self.auto_translate_enabled = self.tab_gifts.translate_checkbox.isChecked()
        self.gemini_api_key = self.tab_gifts.gemini_api_key_edit.text().strip()
        self.gemini_model = self.tab_gifts.gemini_model_combo.currentData() or self.tab_gifts.gemini_model_combo.currentText()
        self.gemini_model = self._normalize_model_name(self.gemini_model)

        # 根據新設定更新翻譯器實例
        if self.auto_translate_enabled:
            self._ensure_translator()
        else:
            self._translator = None  # 如果關閉了，就清空翻譯器

        self._log(f"翻譯設定已更新。啟用: {self.auto_translate_enabled}, 模型: {self.gemini_model}")

    def _perform_initial_load(self):
        """
        执行所有需要在 UI 完全初始化后才进行的载入操作。
        """
        self._log("程式啟動，開始執行初始資料載入...")
        self._load_theme()
        self._auto_load_library()
        self._load_gift_map() # <--- 這個方法會處理所有禮物和翻譯的設定載入
        self._build_path_to_gift_id_map()
        self._prune_invalid_gift_mappings()
        self._refresh_queue_view()
        self._load_audio_levels()
        # self._load_translation_settings() # <--- 刪除這一行
        if self.per_item_volume:
            valid = {self.lib_list.item(i).text() for i in range(self.lib_list.count())}
            pruned = {k: v for k, v in self.per_item_volume.items() if k in valid}
            if pruned != self.per_item_volume:
                self.per_item_volume = pruned
                self._save_audio_levels()
        self._check_for_first_run()
        self._rebuild_trigger_matcher()
        self._log("初始資料載入完成。")

    def _load_audio_levels(self):
        try:
            if os.path.exists(self.AUDIO_LEVELS_FILE):
                with open(self.AUDIO_LEVELS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.per_item_volume = {
                    k: int(v) for k, v in (data or {}).items()
                    if isinstance(v, (int, float)) and 0 <= int(v) <= 200
                }
            else:
                self.per_item_volume = {}
        except Exception as e:
            self._log(f"警告: 載入個別音量檔失敗: {e}")
            self.per_item_volume = {}





    @staticmethod
    def _normalize_model_name(name: str) -> str:
        return (name or "").split("/")[-1].strip()

    def _ensure_translator(self) -> bool:
        if not self.auto_translate_enabled:
            return False
        if not _HAS_GEMINI:
            self._log("警告: 未安裝 google-generativeai，無法啟用翻譯。")
            return False
        if not self.gemini_api_key:
            self._log("警告: 尚未設定 Gemini API Key，無法啟用翻譯。")
            return False
        model = self.gemini_model or "gemini-1.5-flash"
        try:
            # 若尚未建立，或模型不同則重建
            if self._translator is None or getattr(self._translator, "model_name", "") != model:
                self._translator = GeminiTranslator(self.gemini_api_key, model=model)
                self._translator_model = model
                self._log(f"翻譯器已初始化，使用模型：{model}")
            return True
        except Exception as e:
            self._translator = None
            self._translator_model = ""
            self._log(f"錯誤: 初始化 Gemini 翻譯器失敗: {e}")
            return False



    # 將 MainWindow 內的 _refresh_gemini_models_async 整段替換為以下版本
    def _refresh_gemini_models_async(self, checked: bool = False):
        # 步驟 1: 取得 API Key
        api_key = self.tab_gifts.gemini_api_key_edit.text().strip()
        if not api_key:
            QMessageBox.information(self, "提示", "請先在「翻譯」選項卡中輸入 Gemini API Key。")
            return

        # 步驟 2: 禁用 UI (GiftsTab 中的按鈕)
        self.tab_gifts.btn_reload_models.setEnabled(False)
        self.tab_gifts.btn_reload_models.setText("載入中...")
        self._log(f"🚀 [多進程] 準備啟動子進程抓取模型清單...")

        # 步驟 3: 透過獨立進程執行網路請求
        try:
            from multiprocessing import Process, Queue

            # 建立用於進程間通訊的佇列
            self.result_q = Queue()

            # 呼叫我們剛剛定義的「全域」函式
            self.fetch_process = Process(target=_fetch_models_in_process, args=(api_key, self.result_q), daemon=True)
            self.fetch_process.start()

            self._log("⏳ [多進程] 子進程已啟動，等待網路請求結果...")

            # 設定計時器來檢查佇列
            self.check_timer = QTimer(self)
            self.check_timer.start(100)  # 每 100 毫秒檢查一次

            # 設定 25 秒的總超時
            QTimer.singleShot(25000, self._check_process_timeout)

            def check_queue():
                if not self.result_q.empty():
                    self.check_timer.stop()
                    status, data = self.result_q.get()
                    self.fetch_process.join(timeout=1)

                    if status == "SUCCESS":
                        self._on_fetch_success(data)
                    else:
                        self._on_fetch_failure(f"❌ 子進程錯誤: {data}")

            self.check_timer.timeout.connect(check_queue)

        except Exception as e:
            self._on_fetch_failure(f"❌ 無法啟動子進程: {e}")

    def _check_process_timeout(self):
        """檢查子進程是否超時的輔助函式"""
        if hasattr(self, 'fetch_process') and self.fetch_process.is_alive():
            if hasattr(self, 'check_timer') and self.check_timer.isActive():
                self.check_timer.stop()

            self._log("❌ [多進程] 錯誤：子進程執行超過 25 秒，強制終止。")
            try:
                self.fetch_process.terminate()
                self.fetch_process.join()
            except Exception as e:
                self._log(f"警告：終止子進程時發生錯誤: {e}")

            self._on_fetch_failure("❌ 網路請求超時，可能被防火牆或網路問題阻擋。")

    # _on_fetch_success 和 _on_fetch_failure 函式保持不變，但為了完整性，這裡一併提供
    def _on_fetch_success(self, model_list: list[str]):
        """在主執行緒中處理抓取成功的 UI 更新。"""
        self._log("✅ [多進程] 請求成功！")

        # 操作 GiftsTab 的下拉選單
        combo = self.tab_gifts.gemini_model_combo
        combo.blockSignals(True)
        combo.clear()

        if model_list:
            self._log(f"🎉 找到 {len(model_list)} 個可用的模型。")
            for model_name in model_list:
                combo.addItem(model_name, userData=model_name)

            current = self._normalize_model_name(self.gemini_model)
            idx = combo.findData(current) if current else -1
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self._log("⚠️ 警告：API 回應成功，但您的金鑰目前沒有任何可用的生成模型。")
            combo.setPlaceholderText("API 未返回可用模型")

        combo.blockSignals(False)

        # 恢復 GiftsTab 的按鈕
        self.tab_gifts.btn_reload_models.setEnabled(True)
        self.tab_gifts.btn_reload_models.setText("重新載入清單")

        # 順便儲存一次設定
        self._save_gift_map()

    def _on_fetch_failure(self, error_message: str):
        """在主執行緒中處理抓取失敗的 UI 更新。"""
        self._log(error_message)
        QMessageBox.warning(self, "抓取失敗", error_message)

        # 操作 GiftsTab 的 UI
        self.tab_gifts.gemini_model_combo.clear()
        self.tab_gifts.gemini_model_combo.setPlaceholderText("讀取失敗，請檢查日誌")
        self.tab_gifts.btn_reload_models.setEnabled(True)
        self.tab_gifts.btn_reload_models.setText("重新載入清單")

    def _background_fetch_models(self, api_key: str):
        """
        (此函式在背景執行緒中執行)
        呼叫 API 獲取模型清單，然後將結果傳回主執行緒更新 UI。
        """
        # 由於此函式在背景執行緒中，所有UI操作（包括日誌）都必須透過 QTimer.singleShot 傳回主執行緒
        QTimer.singleShot(0, lambda: self._log("[翻譯] (背景) 開始執行 API 請求以獲取模型..."))

        if not list_generation_models:
            QTimer.singleShot(0, lambda: self._log("[翻譯] (背景) 錯誤: list_generation_models 函式不存在。"))
            return

        try:
            # 真正執行 API 請求的函式
            fetched_models = list_generation_models(api_key)
            QTimer.singleShot(0, lambda: self._log(f"[翻譯] (背景) API 請求成功，獲取到 {len(fetched_models)} 個模型。"))
        except Exception as e:
            # 如果 API 請求失敗，在日誌中記錄錯誤
            QTimer.singleShot(0, lambda: self._log(f"[翻譯] (背景) 獲取模型清單失敗: {e}"))
            QTimer.singleShot(0, lambda: self._log("================================================="))
            return

        # 當背景任務完成後，使用 QTimer.singleShot 將 UI 更新操作推送到主執行緒
        QTimer.singleShot(0, lambda: self._log("[翻譯] (背景) 準備將結果傳回主執行緒更新 UI。"))
        QTimer.singleShot(0, lambda: self._update_model_combo(fetched_models))

    def _update_model_combo(self, models: list[str]):
        """
        (此函式在主執行緒中執行)
        安全地更新下拉選單的內容。
        """
        self._log("[翻譯] (主緒) 已收到背景作業結果，開始更新 UI 下拉選單。")
        if not models:
            self._log("[翻譯] (主緒) API 未返回任何可用模型，保留預設清單。")
            self._log("=================================================")
            return

        self._log(f"[翻譯] (主緒) 正在清空並重新填入 {len(models)} 個模型到下拉選單...")
        current_selection = self.gemini_model_combo.currentText()
        self.gemini_model_combo.clear()
        for m in models:
            self.gemini_model_combo.addItem(m, userData=m)

        # 嘗試還原使用者之前的選擇
        index = self.gemini_model_combo.findText(current_selection)
        if index != -1:
            self.gemini_model_combo.setCurrentIndex(index)
            self._log(f"[翻譯] (主緒) 已還原先前的選擇: {current_selection}")
        elif self.gemini_model:
            # 如果之前的選擇不在新列表裡，嘗試還原設定檔中的模型
            index = self.gemini_model_combo.findText(self.gemini_model)
            if index != -1:
                self.gemini_model_combo.setCurrentIndex(index)
                self._log(f"[翻譯] (主緒) 已還原設定檔中的模型: {self.gemini_model}")

        self._log("[翻譯] (主緒) UI 下拉選單更新完畢。操作結束。")
        self._log("=================================================")


    # 用下面整段取代現有的 _contains_cjk 定義
    @staticmethod
    def _contains_cjk(text: str) -> bool:
        if not text:
            return False
        for ch in text:
            code = ord(ch)
            if 0x4E00 <= code <= 0x9FFF:
                return True
            if 0x3400 <= code <= 0x4DBF:
                return True
        return False

    def _save_audio_levels(self):
        try:
            with open(self.AUDIO_LEVELS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.per_item_volume, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._log(f"錯誤: 無法儲存個別音量檔: {e}")



    def _effective_volume_for_path(self, path: str) -> int:
        rel = int(self.per_item_volume.get(path, 100))  # 0..200%
        eff = int(round(self.playback_volume * rel / 100.0))
        return max(0, min(150, eff))  # 與 volume_max/GUI 一致

    def _set_item_volume(self):
        if not self.lib_list.currentItem():
            QMessageBox.information(self, "提示", "請先在媒體庫選擇一個檔案。")
            return
        path = self.lib_list.currentItem().text()
        current = int(self.per_item_volume.get(path, 100))
        val, ok = QInputDialog.getInt(
            self, "個別音量",
            f"為此檔案設定相對音量（0~200%）：\n{os.path.basename(path)}",
            current, 0, 200, 5
        )
        if not ok:
            return
        self.per_item_volume[path] = int(val)
        self._save_audio_levels()
        self._log(f"已設定個別音量: {os.path.basename(path)} -> {val}%")

        if self.current_job_path:
            try:
                same = os.path.samefile(self.current_job_path, path)
            except Exception:
                same = (os.path.abspath(self.current_job_path) == os.path.abspath(path))
            if same:
                self.player.set_volume(self._effective_volume_for_path(path))

    def _compute_overlay_size(self) -> tuple[int, int]:
        """依解析度下拉與長寬比，回傳 Overlay 視窗應用的 (w, h)。"""
        base_h = 720
        if hasattr(self, "resolution_combo") and self.resolution_combo is not None:
            data = self.resolution_combo.currentData()
            if isinstance(data, int) and data > 0:
                base_h = data

        if self.aspect_16_9.isChecked():
            # 16:9 → 540p: 960x540, 720p: 1280x720, 1080p: 1920x1080
            return (16 * base_h) // 9, base_h
        else:
            # 9:16 → 540p: 540x960, 720p: 720x1280, 1080p: 1080x1920
            return base_h, (16 * base_h) // 9

    # 將 MainWindow._toggle_collapsible_window 改為如下版本
    def _toggle_collapsible_window(self, win: QWidget, prefix: str, refresh_cb: Optional[Callable[[], None]] = None):
        """
        將視窗在「一般狀態」與「折疊成 1x1 + 透明（且不可點）」之間切換。
        支援 prefix == "overlay" 與 "menu"：
          - overlay：會處理 setFixedSize（依解析度/長寬比）
          - menu：不調整 fixed size，只還原/保存幾何
        """
        state_attr = f"_{prefix}_collapsed"
        geom_attr = f"_{prefix}_saved_geometry"
        prev_opacity_attr = f"_{prefix}_prev_opacity"

        collapsed = getattr(self, state_attr, False)
        saved_geom: Optional[QRect] = getattr(self, geom_attr, None)
        prev_opacity: float = getattr(self, prev_opacity_attr, 1.0)

        # 初次顯示或目前不可見 → 顯示（不進入折疊流程）
        if not win.isVisible():
            if refresh_cb:
                refresh_cb()

            if prefix == "overlay":
                # 影片：顯示前套用尺寸
                if getattr(self, "_overlay_pending_size", None):
                    w, h = self._overlay_pending_size  # type: ignore
                    self._overlay_pending_size = None
                    win.setFixedSize(w, h)
                elif saved_geom and saved_geom.isValid():
                    win.setFixedSize(saved_geom.width(), saved_geom.height())

            setattr(self, prev_opacity_attr, win.windowOpacity())
            win.setWindowOpacity(1.0)
            win.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

            win.show()
            if saved_geom and saved_geom.isValid():
                win.setGeometry(saved_geom)

            setattr(self, state_attr, False)
            return

        # 從折疊 → 還原
        if collapsed:
            setattr(self, state_attr, False)
            if refresh_cb:
                refresh_cb()

            if saved_geom and saved_geom.isValid():
                if prefix == "overlay":
                    # overlay：如有 pending size 先用 pending size，否則用保存的寬高
                    if getattr(self, "_overlay_pending_size", None):
                        w, h = self._overlay_pending_size  # type: ignore
                        self._overlay_pending_size = None
                        win.setFixedSize(w, h)
                        win.setGeometry(saved_geom.x(), saved_geom.y(), w, h)
                    else:
                        win.setFixedSize(saved_geom.width(), saved_geom.height())
                        win.setGeometry(saved_geom)
                else:
                    # menu：只還原幾何
                    win.setGeometry(saved_geom)

            # 恢復不透明與可點擊
            win.setWindowOpacity(prev_opacity or 1.0)
            win.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            return

        # 從一般 → 折疊
        setattr(self, geom_attr, win.geometry())
        setattr(self, state_attr, True)
        g = win.geometry()

        if prefix == "overlay":
            # 影片 Overlay 在正常狀態有 fixed size，需先改為 1x1 才能縮小
            win.setFixedSize(1, 1)

        # 統一：完全透明 + 點不到，避免桌面殘影與誤點
        setattr(self, prev_opacity_attr, win.windowOpacity())
        win.setWindowOpacity(0.0)
        win.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # 縮到 1x1（維持原左上角）
        win.setGeometry(g.x(), g.y(), 1, 1)

    def _rebuild_trigger_matcher(self):
        # 蒐集所有關鍵字（小寫），同時建立 keyword -> trigger 的映射
        self._trigger_by_keyword = {}
        keywords = []
        for trig in self.trigger_manager.get_all_triggers():
            kw = (trig.get("keyword") or "").strip()
            if kw:
                k = kw.lower()
                # 若有多條相同關鍵字，保留第一條或最後一條皆可；這裡以「第一條」為準
                if k not in self._trigger_by_keyword:
                    self._trigger_by_keyword[k] = trig
                    keywords.append(k)

        # 預設清空舊的結構
        self._ac = None
        self._trigger_regex = None

        # 優先使用 Aho-Corasick
        if _HAS_AHOCORASICK and keywords:
            try:
                A = ahocorasick.Automaton()
                # 使用 set 避免重複插入
                for k in set(keywords):
                    A.add_word(k, k)  # 存 payload 為關鍵字本身
                A.make_automaton()
                self._ac = A
                return
            except Exception:
                # 若建構失敗，回退到正則方案
                self._ac = None

        # 回退方案：將所有關鍵字用 alternation 編成一條正則
        if keywords:
            # 為避免 catastrophic backtracking，先依長度由長到短排序
            parts = [re.escape(k) for k in sorted(set(keywords), key=len, reverse=True)]
            pattern = "|".join(parts)
            try:
                self._trigger_regex = re.compile(pattern, re.IGNORECASE)
            except re.error:
                # 正則建置失敗則放棄（極少見），最終會回到逐一掃描（不建議）
                self._trigger_regex = None

    def _on_library_files_dropped(self, files: List[str]) -> None:
        if files:
            self._add_library_items(files)

    def _setup_connections(self):
        """將所有信號連接集中在此"""
        self.queue.queue_changed.connect(self._update_queue_counts_in_menu)
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
        #self.queue_count_update_timer.timeout.connect(self._update_queue_counts_in_menu)

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
            owner=self,  # 這行是關鍵：把 MainWindow 傳給 GiftsTab
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

        self.menu_overlay_window = MenuOverlayWindow(None)
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

        # 新增：解析度選單（540p / 720p / 1080p）
        res_widget = QWidget()
        res_layout = QHBoxLayout(res_widget)
        res_layout.addWidget(QLabel("解析度:"))
        self.resolution_combo = QComboBox()
        # userData 存放基準高度（以 p 表示）
        self.resolution_combo.addItem("540p", 540)
        self.resolution_combo.addItem("720p", 720)
        self.resolution_combo.addItem("1080p", 1080)
        # 預設選 720p（可改成 0 → 540p 或 2 → 1080p）
        self.resolution_combo.setCurrentIndex(1)
        self.resolution_combo.currentIndexChanged.connect(self._update_overlay_geometry)
        res_layout.addWidget(self.resolution_combo)
        overlay_box_layout.addWidget(res_widget)

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
            self.tts_q_list.setUpdatesEnabled(False)
            self.tts_q_list.clear()
            self.tts_q_list.addItems(snapshot)
            self.tts_q_list.setUpdatesEnabled(True)

    def _setup_library_tab(self, parent):
        layout = QVBoxLayout(parent)
        lib_box = QGroupBox("媒体清单 (可拖放檔案至此)")
        lib_box_layout = QHBoxLayout(lib_box)

        # 使用自訂的 LibraryListWidget（取代原本的 QListWidget）
        self.lib_list = LibraryListWidget()
        self.lib_list.itemDoubleClicked.connect(self._enqueue_selected_from_library)
        # 接收拖放完成的檔案清單
        self.lib_list.filesDropped.connect(self._on_library_files_dropped)

        # 保留右鍵選單與其它設定
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
        btn_item_volume = QPushButton("個別音量")
        btn_item_volume.clicked.connect(self._set_item_volume)

        # 一次性加入（避免重複）
        for btn in [btn_add, btn_enqueue, btn_edit, btn_reset, btn_remove,
                    btn_clear, btn_save_list_as, btn_load_list_from, btn_item_volume]:
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

    # 在新增/更新/刪除觸發器後，呼叫重建（_add_trigger/_edit_trigger/_del_trigger 內）
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
            self._rebuild_trigger_matcher()  # 新增：重建比對器

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
            if not updated_data.get("keyword") or (
                    not updated_data.get("path") and not updated_data.get("tts_response")):
                QMessageBox.warning(self, "提示", "關鍵字不能為空，且必須至少設定一個觸發動作（影片或朗讀）。")
                return
            self.trigger_manager.update_trigger(index, updated_data)
            self._refresh_trigger_tree()
            self._rebuild_trigger_matcher()  # 新增：重建比對器

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
            self._rebuild_trigger_matcher()  # 新增：重建比對器

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
        # 新增：翻譯區塊（置於底部）


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
        if not self.game_menu_container or not self.menu_overlay_window.isVisible():
            return

        # 1) 將佇列中的 path 直接彙總為 gift_id 計數
        queue_snapshot = self.queue.snapshot()
        counts_by_gift: Dict[str, int] = {}
        for path, _ in queue_snapshot:
            gid = self.path_to_gift_id_map.get(path)
            if gid:
                counts_by_gift[gid] = counts_by_gift.get(gid, 0) + 1

        # 2) 如需避免不必要的 UI 重繪，可比對上次結果
        if getattr(self, "_last_counts_by_gift", None) == counts_by_gift:
            return
        self._last_counts_by_gift = counts_by_gift

        # 3) 更新 UI（僅當菜單視窗可見）
        list_widget = self.game_menu_container.list_widget
        show = self.show_queue_counter_checkbox.isChecked()
        for i in range(list_widget.count()):
            widget = list_widget.itemWidget(list_widget.item(i))
            if isinstance(widget, MenuItemWidget):
                gift_id = widget.gift_info.get("id")
                new_count = counts_by_gift.get(gift_id, 0)
                widget.set_queue_count(new_count, show)

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
            f"<h2>Overlay UltraLite - {self.VERSION}</h2>"
            "<p>一個為 TikTok 直播設計的影片播放疊加工具。</p>"
            "<p>基於 PySide6 和 TikTokLive 函式庫開發。</p>")



    # 在 _show_library_context_menu 增加右鍵選單項
    def _show_library_context_menu(self, pos):
        item = self.lib_list.itemAt(pos)
        menu = QMenu()
        enqueue_action = menu.addAction("→ 加入待播")
        edit_layout_action = menu.addAction("調整版面")
        item_volume_action = menu.addAction("調整個別音量…")  # 新增
        remove_action = menu.addAction("删除所選")
        if not item:
            enqueue_action.setEnabled(False)
            edit_layout_action.setEnabled(False)
            item_volume_action.setEnabled(False)  # 新增
            remove_action.setEnabled(False)
        action = menu.exec(self.lib_list.mapToGlobal(pos))
        if action == enqueue_action:
            self._enqueue_selected_from_library()
        elif action == edit_layout_action:
            self._enter_edit_mode()
        elif action == item_volume_action:  # 新增
            self._set_item_volume()
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
        # 折疊/還原菜單 Overlay；還原時會先 refresh 內容
        self._toggle_collapsible_window(self.menu_overlay_window, "menu", refresh_cb=self._refresh_menu_content)

    def _load_layouts(self) -> LayoutsData:
        # 與舊介面相容：回傳 dict，但實際由 LayoutsManager 管
        return self.layouts_mgr.load()

    def _save_layouts(self, data: Optional[LayoutsData] = None):
        # 寫入指定資料或目前 self.layouts
        self.layouts_mgr.save(data if data is not None else self.layouts)

    def _toggle_overlay_window(self):
        # 折疊/還原影片 Overlay 視窗
        self._toggle_collapsible_window(self.overlay_window, "overlay")

    def _update_overlay_geometry(self):
        # 折疊時：只記錄待套用尺寸，避免把 1x1 撐開
        if getattr(self, "_overlay_collapsed", False):
            self._overlay_pending_size = self._compute_overlay_size()
            return

        w, h = self._compute_overlay_size()
        self.overlay_window.setFixedSize(w, h)
        self._update_child_geometries()

    def _get_video_dimensions(self, path: str) -> Optional[tuple[int, int]]:
        if path in self.video_dimensions_cache:
            return self.video_dimensions_cache[path]
        if not cv2:
            self._log("警告: cv2 模組不可用，無法獲取影片尺寸。使用預設值。")
            return (1920, 1080) if self.aspect_16_9.isChecked() else (1080, 1920)

        cap = None  # 先宣告，避免靜態分析警告
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
            if cap is not None and cap.isOpened():
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

    def _add_library_items(self, paths: List[str]):
        if not paths:
            return
        existing = {self.lib_list.item(i).text() for i in range(self.lib_list.count())}
        new_items = [p for p in paths if p not in existing]
        if new_items:
            self.lib_list.addItems(new_items)
            self._auto_save_library()

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇影片檔案", "", "影片檔案 (*.mp4 *.mkv *.mov *.avi)")
        if paths:
            self._add_library_items(paths)


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

    # 同步清掉個別音量：移除單一項目
    def _remove_selected_from_library(self):
        if self.lib_list.currentItem():
            path = self.lib_list.currentItem().text()
            self.lib_list.takeItem(self.lib_list.currentRow())
            # 刪除 per-item volume
            if path in self.per_item_volume:
                del self.per_item_volume[path]
                self._save_audio_levels()
            # 刪除對應版面
            if path in self.layouts:
                del self.layouts[path]
                self._save_layouts()
            # 立即保存媒體清單
            self._auto_save_library()
            self._prune_invalid_gift_mappings()

    # 同步清掉個別音量：清空清單
    def _clear_library(self):
        if QMessageBox.question(
                self, "確認", "確定要清空媒體清單和所有版面嗎？"
        ) == QMessageBox.StandardButton.Yes:
            self.lib_list.clear()
            self.layouts.clear()
            self._save_layouts()
            # 新增：清空所有 per-item volume 設定
            if self.per_item_volume:
                self.per_item_volume.clear()
                self._save_audio_levels()
            self._auto_save_library()
            self._prune_invalid_gift_mappings()

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
                # 修剪個別音量與版面資料
                valid = set(items)
                if self.per_item_volume:
                    self.per_item_volume = {k: v for k, v in self.per_item_volume.items() if k in valid}
                    self._save_audio_levels()
                if self.layouts:
                    self.layouts = {k: v for k, v in self.layouts.items() if k in valid}
                    self._save_layouts()
                # 新增：載入清單後也修剪禮物映射
                self._prune_invalid_gift_mappings()
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

    # 從檔案載入清單時，修剪 per_item_volume 僅保留仍存在的路徑
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
                    valid = set(items)
                    # 修剪 per-item volume
                    if self.per_item_volume:
                        self.per_item_volume = {k: v for k, v in self.per_item_volume.items() if k in valid}
                        self._save_audio_levels()
                    # 新增：修剪 layouts
                    if self.layouts:
                        self.layouts = {k: v for k, v in self.layouts.items() if k in valid}
                        self._save_layouts()
                    # 新增：保存 library 並修剪禮物映射
                    self._auto_save_library()
                    self._prune_invalid_gift_mappings()
                else:
                    self._log(f"錯誤: 檔案 {path} 格式不正確。")
            except (IOError, json.JSONDecodeError) as e:
                self._log(f"錯誤: 無法從檔案載入清單 {path}: {e}")

    def _refresh_queue_view(self):
        self.q_list.clear()
        snapshot = self.queue.snapshot()
        if not snapshot:
            self.setWindowTitle(f"Overlay UltraLite - {self.VERSION} [待播: 0]")
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
        self.setWindowTitle(f"Overlay UltraLite - {self.VERSION} [待播: {len(self.queue)}]")

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

        # 在 MainWindow._start_job 裡，loadfile 後再補一次 set_volume（讓使用者感知更直覺）

    # 替換 MainWindow._start_job 內套用音量的兩行
    def _start_job(self, path: str):
        if not os.path.exists(path):
            self._log(f"錯誤: 檔案不存在 - {path}")
            self._play_next_if_idle()
            return

        self._set_player_state(PlayerState.PLAYING, job_path=path)
        self.player.set_loop(1)

        video_rect = self._apply_video_layout(path=path)
        self._last_video_geometry = video_rect

        # 先計算合成音量，先寫進 PlayerWrapper 當成期望音量
        eff = self._effective_volume_for_path(path)
        self.player.set_volume(eff)

        # 再載入媒體
        self.player.command("loadfile", path, "replace")

        # 補一次（確保即時生效）
        self.player.set_volume(eff)

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

    def _add_event_item(self, text: str, color: Optional[QColor] = None):
        """一個輔助函式，用來將項目新增到即時動態列表，並處理自動滾動。"""
        scroll_bar = self.events_list.verticalScrollBar()
        is_at_bottom = (scroll_bar.value() >= scroll_bar.maximum() - 5)

        item = QListWidgetItem(text)
        if color:
            item.setForeground(color)

        self.events_list.addItem(item)
        if self.events_list.count() > 200:
            self.events_list.takeItem(0)

        if is_at_bottom:
            self.events_list.scrollToBottom()

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
            original_message_line = f"[{timestamp}] 💬 {user}: {msg}"
            self._check_comment_for_triggers(msg)
            self._log_realtime_event(original_message_line)

            # 判斷是否需要翻譯
            read_enabled = getattr(self.tab_gifts, "read_comment_checkbox", None) and self.tab_gifts.read_comment_checkbox.isChecked()
            needs_translate = self.auto_translate_enabled and (not self._contains_cjk(msg)) and self._ensure_translator()

            if needs_translate:
                # --- 處理需要翻譯的留言 ---
                show_original = hasattr(self, "tab_gifts") and self.tab_gifts.show_original_comment_checkbox.isChecked()
                if show_original:
                    self._add_event_item(original_message_line, QColor("gray")) # 顯示灰色原文
                self._translate_comment_async(user, msg, also_tts=read_enabled) # 進行翻譯(完成後會顯示橘色譯文)
            else:
                # --- 處理不需要翻譯的留言 ---
                self._add_event_item(original_message_line) # 直接顯示黑色原文
                self._process_and_say_comment(user, msg) # 朗讀原文

            return # 留言事件處理完畢

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

        if message:
            self._add_event_item(message, color)
            self._log_realtime_event(message)


    def _translate_comment_async(self, user: str, original: str, also_tts: bool):
        # 1. 檢查 API Key 和模型是否就緒
        if not (self.gemini_api_key and self.gemini_model):
            return  # 如果沒有設定，直接放棄翻譯

        # 2. 為每一條留言啟動一個獨立的翻譯子進程
        try:
            from multiprocessing import Process, Queue

            result_q = Queue()

            # 呼叫全域的翻譯 worker 函式
            process = Process(
                target=_translate_in_process,
                args=(self.gemini_api_key, self.gemini_model, original, result_q),
                daemon=True
            )
            process.start()

            # 3. 使用 QTimer 非同步等待結果
            timer = QTimer(self)

            def check_result():
                if not result_q.empty():
                    status, data = result_q.get()
                    process.join(timeout=1)
                    timer.stop()

                    if status == "SUCCESS" and data:
                        translated_text = data.strip()
                        ts = time.strftime("%H:%M:%S")

                        # --- 關鍵修改：在翻譯結果中加入使用者名稱 ---
                        # 格式模仿原始留言，但用橘色來區分
                        trans_line = f"[{ts}] 💬 {user}: {translated_text}"

                        # --- 關鍵修改：呼叫新的輔助函式來顯示 ---
                        self._add_event_item(trans_line, QColor("orange"))

                        self._log_realtime_event(f"↳ 翻譯 ({user}): {translated_text}")

                        if also_tts:
                            self._process_and_say_comment(user, translated_text)

                elif not process.is_alive():
                    timer.stop()

            timer.timeout.connect(check_result)
            timer.start(100)

            QTimer.singleShot(30000, timer.stop)

        except Exception as e:
            self._log(f"❌ 無法啟動即時翻譯子進程: {e}")

    def _test_translation(self):
        # 1. 檢查並獲取必要的資訊
        if not self._ensure_translator():
            QMessageBox.warning(self, "翻譯測試",
                                "翻譯器尚未準備就緒。\n請檢查：\n1. 是否已勾選啟用\n2. API Key 是否已填寫\n3. 模型是否已選擇")
            return

        text_to_test = "Hello, how are you today?"
        api_key = self.gemini_api_key
        model_name = self.gemini_model

        self._log("==================================================")
        self._log(f"🚀 [多進程翻譯測試] 使用模型 '{model_name}' 翻譯 '{text_to_test}'...")

        # --- 為了讓取消功能可以存取這些物件，將它們宣告在 try 區塊外 ---
        self.translation_process = None
        self.translation_timer = None

        def cleanup_translation_task():
            """一個集中的清理函式，用來停止計時器和終止進程。"""
            if hasattr(self, 'translation_timer') and self.translation_timer:
                self.translation_timer.stop()
                self.translation_timer = None

            if hasattr(self,
                       'translation_process') and self.translation_process and self.translation_process.is_alive():
                try:
                    self.translation_process.terminate()
                    self.translation_process.join(timeout=1)
                    self.translation_process = None
                except Exception as e:
                    self._log(f"警告：終止翻譯子進程時發生錯誤: {e}")

        try:
            from multiprocessing import Process, Queue

            result_q = Queue()

            # 2. 建立並啟動子進程
            self.translation_process = Process(target=_translate_in_process,
                                               args=(api_key, model_name, text_to_test, result_q), daemon=True)
            self.translation_process.start()

            # 3. 建立一個帶有「取消」按鈕的等待視窗
            wait_dialog = QMessageBox(self)
            wait_dialog.setWindowTitle("翻譯中")
            wait_dialog.setText("正在向 Gemini API 發送請求，請稍候...")
            wait_dialog.setIcon(QMessageBox.Icon.Information)
            # --- 關鍵修改：新增取消按鈕 ---
            wait_dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
            wait_dialog.setWindowModality(Qt.WindowModality.WindowModal)

            # 4. 連接取消按鈕的點擊事件
            def handle_cancel():
                self._log("🟡 使用者手動取消了翻譯請求。")
                cleanup_translation_task()
                wait_dialog.close()

            # 取得取消按鈕並連接事件
            cancel_button = wait_dialog.button(QMessageBox.StandardButton.Cancel)
            cancel_button.clicked.connect(handle_cancel)

            # 5. 使用 QTimer 非同步等待結果
            self.translation_timer = QTimer(self)

            def check_result():
                if not result_q.empty():
                    status, data = result_q.get()
                    cleanup_translation_task()  # 收到結果，清理任務
                    wait_dialog.close()

                    if status == "SUCCESS":
                        QMessageBox.information(self, "翻譯測試結果", f"原文：{text_to_test}\n\n結果：{data.strip()}")
                        self._log(f"✅ 翻譯成功: {data.strip()}")
                    else:
                        error_msg = f"翻譯失敗：\n{data}"
                        QMessageBox.warning(self, "翻譯測試失敗", error_msg)
                        self._log(f"❌ {error_msg}")
                # 如果計時器還在，但進程已經掛了，也算結束
                elif self.translation_process and not self.translation_process.is_alive():
                    cleanup_translation_task()
                    wait_dialog.close()
                    self._log("❌ 翻譯子進程意外終止。")
                    QMessageBox.warning(self, "錯誤", "翻譯子進程意外終止。")

            self.translation_timer.timeout.connect(check_result)
            self.translation_timer.start(100)

            # 6. 執行對話框，它會阻塞直到被關閉
            wait_dialog.exec()

            # 當 wait_dialog.exec() 結束後 (無論是成功、失敗或取消)，都確保清理
            cleanup_translation_task()

        except Exception as e:
            QMessageBox.critical(self, "啟動失敗", f"無法啟動翻譯子進程: {e}")
            self._log(f"❌ 無法啟動翻譯子進程: {e}")
    # 抽出執行觸發細節（影片/朗讀）的共用方法
    def _perform_trigger(self, trigger: dict) -> bool:
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

        return triggered
    def _check_comment_for_triggers(self, comment: str):
        if not comment:
            return

        text = comment.lower()

        # 1) Aho-Corasick（最佳效能）
        if self._ac is not None:
            for _, matched_kw in self._ac.iter(text):
                trig = self._trigger_by_keyword.get(matched_kw)
                if trig and self._perform_trigger(trig):
                    break  # 觸發成功即停止
            return

        # 2) 回退：單一正則（效能佳於逐一 substring）
        if self._trigger_regex is not None:
            m = self._trigger_regex.search(text)
            if m:
                kw = m.group(0).lower()
                trig = self._trigger_by_keyword.get(kw)
                if trig:
                    self._perform_trigger(trig)
            return

        # 3) 最終回退：逐一 substring（避免完全失效）
        for trig in self.trigger_manager.get_all_triggers():
            kw = (trig.get("keyword") or "").lower()
            if kw and kw in text:
                if self._perform_trigger(trig):
                    break

    def _process_and_say_comment(self, user: str, comment_text: str):
        """
        一個集中的函式，在朗讀留言前進行過濾和截斷。
        (新版：截斷功能改為作用於使用者暱稱)
        """
        # 檢查朗讀功能是否開啟
        read_enabled = getattr(self.tab_gifts, "read_comment_checkbox",
                               None) and self.tab_gifts.read_comment_checkbox.isChecked()
        if not read_enabled:
            return

        # 1. 執行暱稱過濾 (這部分邏輯不變)
        filter_enabled = getattr(self.tab_gifts, "tts_filter_checkbox",
                                 None) and self.tab_gifts.tts_filter_checkbox.isChecked()
        if filter_enabled:
            keywords_text = getattr(self.tab_gifts, "tts_filter_edit",
                                    None) and self.tab_gifts.tts_filter_edit.text().strip()
            if keywords_text:
                filter_keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
                for keyword in filter_keywords:
                    if keyword in user:
                        self._log(f"🚫 朗讀過濾：因暱稱 '{user}' 包含關鍵字 '{keyword}'，已略過留言。")
                        return  # 找到符合的關鍵字，直接返回，不朗讀

        # --- 關鍵修改：將截斷邏輯從留言改為暱稱 ---

        # 2. 準備最終要朗讀的暱稱和留言
        final_user = user
        truncate_enabled = getattr(self.tab_gifts, "tts_truncate_checkbox",
                                   None) and self.tab_gifts.tts_truncate_checkbox.isChecked()

        # 如果啟用截斷，且暱稱長度超過 6，則只取前 6 個字
        if truncate_enabled and len(user) > 6:
            final_user = user[:6]

        # 留言內容保持不變
        final_comment = comment_text

        # 3. 呼叫朗讀引擎
        self.speech_engine.say(f"{final_user} 說 {final_comment}")

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

    # 替換 MainWindow._on_volume_changed
    def _on_volume_changed(self, value: int):
        self.playback_volume = value
        # 正在播放 → 使用主音量 × 個別相對音量
        if self.current_job_path:
            self.player.set_volume(self._effective_volume_for_path(self.current_job_path))
        else:
            # 尚未播放 → 先把主音量送進 PlayerWrapper（下一個檔案載入時仍會被覆蓋成合成音量）
            self.player.set_volume(self.playback_volume)

    def closeEvent(self, event):
        self._flush_log_buffer_to_file()
        self._auto_save_library()
        self._save_gift_map()
        self._save_audio_levels()  # 新增：保存個別音量


        self.tiktok_listener.stop()
        self.player.terminate()
        if self.speech_engine:
            self.speech_engine.stop()
        if self.menu_overlay_window:
            self.menu_overlay_window.close()
        if self.overlay_window:
            self.overlay_window.close()
        event.accept()

    def _prune_invalid_gift_mappings(self):
        before = len(self.tiktok_listener.gift_map)
        self.tiktok_listener.gift_map = [
            m for m in self.tiktok_listener.gift_map
            if m.get("path") and os.path.exists(m["path"])
        ]
        if len(self.tiktok_listener.gift_map) != before:
            self._save_gift_map()
            self._build_path_to_gift_id_map()
            if hasattr(self, "tab_gifts"):
                self.tab_gifts._refresh_gift_tree()



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
    if not _HAS_GEMINI:
        QMessageBox.warning(
            None, "缺少相依性",
            "警告: 'google-generativeai' 未安裝。\n翻譯功能將無法使用。\n請執行: pip install google-generativeai"
        )

    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())
