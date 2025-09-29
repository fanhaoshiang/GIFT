# -*- coding: utf-8 -*-
import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QGroupBox, QHBoxLayout, QHeaderView,
                             QInputDialog, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QSpinBox, QSlider, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget, QFileDialog)

from gift_manager import GiftManager, GiftInfo
from tiktok_listener import TikTokListener
from ui_components import GiftListDialog
from gift_map_dialog import GiftMapDialog


class GiftsTab(QWidget):
    """
    一個獨立的 QWidget，封裝了所有「TikTok 禮物設定」分頁的功能。
    """

    def __init__(self,
                 tiktok_listener: TikTokListener,
                 gift_manager: GiftManager,
                 get_library_paths: Callable[[], List[str]],
                 log_func: Callable[[str], None],
                 parent: Optional[QWidget] = None):
        super().__init__(parent)

        # 接收從 MainWindow 傳入的核心物件
        self.listener = tiktok_listener
        self.gift_manager = gift_manager
        self.get_library_paths = get_library_paths
        self._log = log_func
        self.playback_volume = 100

        # 初始化 UI
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """建立此分頁的所有 UI 元件"""
        layout = QVBoxLayout(self)

        # --- 連線設定群組 ---
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
        self.tiktok_api_key_entry.setPlaceholderText("从 eulerstream.com 取得")
        self.tiktok_api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.tiktok_api_key_entry.setToolTip(
            "API Key 需要從 eulerstream.com 網站付費取得。\n這是 TikTokLive 函式庫連線的必要憑證。"
        )
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

        # --- 禮物映射群組 ---
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

        # --- 後備影片群組 ---
        fallback_group = QGroupBox("后备影片 (无匹配时播放)")
        fallback_layout = QHBoxLayout(fallback_group)
        self.fallback_video_entry = QLineEdit()
        self.fallback_video_entry.setReadOnly(True)
        btn_pick_fallback = QPushButton("选择档案...")
        fallback_layout.addWidget(self.fallback_video_entry, 1)
        fallback_layout.addWidget(btn_pick_fallback)
        layout.addWidget(fallback_group)

        # --- 播放選項群組 ---
        option_group = QGroupBox("播放选项")
        option_layout = QVBoxLayout(option_group)
        top_options_layout = QHBoxLayout()
        self.interrupt_checkbox = QCheckBox("新礼物插队播放")
        self.read_comment_checkbox = QCheckBox("朗读观众留言")
        # 假設 _HAS_TTS 在主程式中處理
        # if not _HAS_TTS:
        #     self.read_comment_checkbox.setDisabled(True)
        #     self.read_comment_checkbox.setToolTip("错误: 'pyttsx3' 函式库未安装")
        top_options_layout.addWidget(self.interrupt_checkbox)
        top_options_layout.addWidget(self.read_comment_checkbox)
        top_options_layout.addStretch()
        option_layout.addLayout(top_options_layout)

        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("触发媒体音量:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.playback_volume)
        self.volume_spinbox = QSpinBox()
        self.volume_spinbox.setRange(0, 100)
        self.volume_spinbox.setValue(self.playback_volume)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_spinbox)
        option_layout.addLayout(volume_layout)
        layout.addWidget(option_group)

        # --- 將剛剛建立的按鈕連接到方法 ---
        self.tiktok_start_btn.clicked.connect(self._start_tiktok_listener)
        self.tiktok_stop_btn.clicked.connect(self._stop_tiktok_listener)
        self.gift_tree.itemDoubleClicked.connect(self._on_gift_tree_double_clicked)
        btn_add_gift.clicked.connect(self._add_gift_map)
        btn_edit_gift.clicked.connect(self._edit_gift_map)
        btn_del_gift.clicked.connect(self._remove_gift_map)
        btn_manage_gifts.clicked.connect(self._manage_gift_list)
        btn_pick_fallback.clicked.connect(self._pick_fallback_video)
        self.volume_slider.valueChanged.connect(self.volume_spinbox.setValue)
        self.volume_spinbox.valueChanged.connect(self.volume_slider.setValue)
        self.volume_spinbox.valueChanged.connect(self._on_volume_changed)

    def _setup_connections(self):
        """設定與外部 (MainWindow) 的信號連接"""
        # 當音量改變時，通知 MainWindow
        self.volume_spinbox.valueChanged.connect(
            lambda vol: self.parent()._on_volume_changed(vol)
        )
        # 當朗讀選項改變時，通知 MainWindow
        self.read_comment_checkbox.toggled.connect(
            lambda checked: setattr(self.parent(), 'read_comments', checked)
        )

    # ==================================================================
    # 以下是從 MainWindow 搬移過來的所有相關方法
    # ==================================================================

    def _start_tiktok_listener(self):
        url = self.tiktok_url_entry.text().strip()
        api_key = self.tiktok_api_key_entry.text().strip()
        if not url or not api_key:
            QMessageBox.warning(self, "提示", "请同时输入直播网址和 API Key。")
            return
        self.listener.interrupt_on_gift = self.interrupt_checkbox.isChecked()
        self.listener.start(url, api_key)
        self.tiktok_start_btn.setEnabled(False)
        self.tiktok_stop_btn.setEnabled(True)

    def _stop_tiktok_listener(self):
        self.listener.stop()
        self.tiktok_start_btn.setEnabled(True)
        self.tiktok_stop_btn.setEnabled(False)

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
                tree_item.setToolTip(1, f"档案不存在或未设定！\n路径: {path}")
            self.gift_tree.addTopLevelItem(tree_item)
        self.gift_tree.resizeColumnToContents(0)

    def _add_gift_map(self):
        library_paths = self.get_library_paths()
        if not library_paths:
            QMessageBox.warning(self, "提示", "媒体库是空的，请先加入一些影片。")
            return
        dialog = GiftMapDialog(self,
                               library_paths=library_paths,
                               gift_list=self.gift_manager.get_all_gifts())
        if dialog.exec():
            new_data = dialog.get_data()
            if not new_data.get("path"):
                QMessageBox.warning(self, "提示", "必须选择一个影片档案。")
                return
            if not new_data.get("kw") and not new_data.get("gid"):
                QMessageBox.warning(self, "提示", "礼物未选择或无效。")
                return
            self.listener.gift_map.append(new_data)
            self._refresh_gift_tree()
            self.parent()._save_gift_map() # 通知 MainWindow 儲存

    def _edit_gift_map(self):
        selected = self.gift_tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个要编辑的项目。")
            return
        index = self.gift_tree.indexOfTopLevelItem(selected)
        if index < 0: return
        
        library_paths = self.get_library_paths()
        item_data = self.listener.gift_map[index]
        dialog = GiftMapDialog(self,
                               item=item_data,
                               library_paths=library_paths,
                               gift_list=self.gift_manager.get_all_gifts())
        if dialog.exec():
            updated_data = dialog.get_data()
            if not updated_data.get("path"):
                QMessageBox.warning(self, "提示", "必须选择一个影片档案。")
                return
            if not updated_data.get("kw") and not updated_data.get("gid"):
                QMessageBox.warning(self, "提示", "礼物未选择或无效。")
                return
            self.listener.gift_map[index] = updated_data
            self._refresh_gift_tree()
            self.parent()._save_gift_map() # 通知 MainWindow 儲存

    def _remove_gift_map(self):
        selected = self.gift_tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个要删除的项目。")
            return
        index = self.gift_tree.indexOfTopLevelItem(selected)
        if index >= 0:
            reply = QMessageBox.question(
                self, "确认删除", f"确定要删除「{selected.text(0)}」这个映射吗？")
            if reply == QMessageBox.StandardButton.Yes:
                del self.listener.gift_map[index]
                self._refresh_gift_tree()
                self.parent()._save_gift_map() # 通知 MainWindow 儲存

    def _pick_fallback_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择后备影片", "", "影片档案 (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.fallback_video_entry.setText(path)
            self.listener.fallback_video_path = path
            self.parent()._save_gift_map() # 通知 MainWindow 儲存

    def _on_gift_tree_double_clicked(self, item: QTreeWidgetItem, column: int):
        index = self.gift_tree.indexOfTopLevelItem(item)
        if index < 0: return
        
        map_item = self.listener.gift_map[index]
        path = map_item.get("path")
        if path and os.path.exists(path):
            count, ok = QInputDialog.getInt(
                self, "输入播放次数", f"请输入 '{os.path.basename(path)}' 的播放次数：", 1, 1, 999, 1)
            if ok:
                # 直接呼叫 MainWindow 的方法來處理影片排隊
                self.parent()._enqueue_video_from_gift(path, False, count)
                self._log(f"已手动将「{os.path.basename(path)}」加入待播清单 {count} 次，并更新计数。")
        else:
            QMessageBox.warning(self, "提示", "该映射的影片档案不存在或未设定。")

    def _manage_gift_list(self):
        # GiftListDialog 也是一個 UI 元件，理論上應該由 MainWindow 管理
        # 這裡我們暫時透過 parent() 呼叫 MainWindow 的方法
        self.parent()._manage_gift_list()

    def _on_volume_changed(self, value: int):
        self.playback_volume = value
        # 通知 MainWindow 更新音量
        self.parent()._on_volume_changed(value)

    # --- 以下方法供 MainWindow 呼叫，用來同步狀態 ---
    def load_settings(self, data: dict):
        """從 MainWindow 接收設定並更新 UI"""
        self.tiktok_url_entry.setText(data.get("tiktok_url", ""))
        self.listener.gift_map = data.get("gift_map", [])
        self.listener.fallback_video_path = data.get("fallback_video", "")
        self.listener.interrupt_on_gift = data.get("interrupt_on_gift", False)
        self.tiktok_api_key_entry.setText(data.get("api_key", ""))
        self.fallback_video_entry.setText(self.listener.fallback_video_path)
        self.interrupt_checkbox.setChecked(self.listener.interrupt_on_gift)
        
        self.playback_volume = data.get("playback_volume", 100)
        self.volume_slider.setValue(self.playback_volume)
        
        self._refresh_gift_tree()

    def get_settings(self) -> dict:
        """讓 MainWindow 可以從此 Tab 獲取需要儲存的資料"""
        return {
            "tiktok_url": self.tiktok_url_entry.text().strip(),
            "api_key": self.tiktok_api_key_entry.text().strip(),
            "gift_map": self.listener.gift_map,
            "fallback_video": self.fallback_video_entry.text(),
            "interrupt_on_gift": self.interrupt_checkbox.isChecked(),
            "playback_volume": self.playback_volume
        }
```

### 第 2 步：修改主程式 `9.51-DedupeFix.py`

現在，我們來修改您的主檔案。您會看到 `_setup_gifts_tab` 和一大堆相關的方法都不見了，取而代之的是 `GiftsTab` 的實例化。

（**注意**：為了簡化，我假設 `ui_tabs.py` 和其他您自己建立的元件檔案如 `gift_manager.py` 等都放在與主程式相同的目錄下。）

````python name=9.51-DedupeFix.py
# -*- coding: utf-8 -*-
"""
Overlay UltraLite - V9.51-DedupeFix (Fixes event deduplication attribute error)
"""
# ... (前面的 import 維持不變) ...

# 舊的 import
# from ui_components import GiftListDialog, GameMenuContainer, MenuItemWidget, TriggerEditDialog
# from trigger_manager import TriggerManager

# 新增/修改的 import
from speech_engine import SpeechEngine
from gift_manager import GiftManager
from tiktok_listener import TikTokListener
from trigger_manager import TriggerManager
from ui_components import GiftListDialog, GameMenuContainer, MenuItemWidget, TriggerEditDialog
from gift_map_dialog import GiftMapDialog
# ！！！我們在這裡導入新的 GiftsTab 類別！！！
from ui_tabs import GiftsTab

# ... (其他依賴和核心程式碼維持不變) ...

# ==================== 主 GUI 應用 ===================
class MainWindow(QMainWindow):
    LAYOUT_FILE = os.path.join(application_path, "layouts.json")
    LIBRARY_FILE = os.path.join(application_path, "library.json")
    GIFT_MAP_FILE = os.path.join(application_path, "gift_map.json")
    GIFT_LIST_FILE = os.path.join(application_path, "gifts.json")
    EVENTS_LOG_FILE = os.path.join(application_path, "events_log.txt")
    THEME_FILE = os.path.join(application_path, "theme.json")
    TRIGGER_FILE = os.path.join(application_path, "triggers.json")

    # ... (DEV_LOG_CONTENT 維持不變) ...

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Overlay UltraLite - V9.51 (Dedupe Fix)")
        self.setGeometry(100, 100, 1200, 800)

        # --- 1. 初始化所有屬性 ---
        self.layouts = self._load_layouts()
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
        self.read_comments = False # 新增屬性，給 GiftsTab 控制
        self.speech_engine = SpeechEngine(self)
        self.recent_events = deque(maxlen=20)

        # ... (計時器初始化維持不變) ...

        # --- 2. 設定 UI ---
        self._setup_ui()

        # --- 3. 連接所有信號和槽 ---
        self._setup_connections()

        # --- 4. 載入初始資料 ---
        self._load_theme()
        self._auto_load_library()
        self._load_gift_map() # 這個方法現在會變得更簡單
        self._build_path_to_gift_id_map()
        self._refresh_queue_view()

        # ... (啟動計時器和 first_run 維持不變) ...

    def _setup_connections(self):
        """將所有信號連接集中在此"""
        # ... (其他信號連接維持不變) ...

        # TikTok 信號
        self.tiktok_listener.on_video_triggered.connect(self._enqueue_video_from_gift)
        self.tiktok_listener.on_event_received.connect(self._on_tiktok_event)
        self.tiktok_listener.on_status_change.connect(self._on_tiktok_status)

        # ... (其他信號連接維持不變) ...


    def _setup_ui(self):
        # ... (Menu Bar 和 Main Layout 設定維持不變) ...

        # Center Tabs
        self.tab_library = QWidget()
        # ！！！不再自己建立，而是實例化 GiftsTab ！！！
        self.tab_gifts = GiftsTab(
            tiktok_listener=self.tiktok_listener,
            gift_manager=self.gift_manager,
            get_library_paths=lambda: [self.lib_list.item(i).text() for i in range(self.lib_list.count())],
            log_func=self._log,
            parent=self
        )
        self.tab_triggers = QWidget()
        self.tab_log = QWidget()
        self.tab_theme = QWidget()
        self.tabs.addTab(self.tab_library, "媒体库")
        self.tabs.addTab(self.tab_gifts, "TikTok 礼物设定") # 加入實例
        self.tabs.addTab(self.tab_triggers, "關鍵字觸發")
        self.tabs.addTab(self.tab_theme, "外觀設定")
        self.tabs.addTab(self.tab_log, "日誌")
        self._setup_library_tab(self.tab_library)
        # ！！！不再需要呼叫 _setup_gifts_tab ！！！
        # self._setup_gifts_tab(self.tab_gifts) 
        self._setup_triggers_tab(self.tab_triggers)
        self.read_comments = self.tab_gifts.read_comment_checkbox.isChecked() # 同步初始狀態
        self._setup_theme_tab(self.tab_theme)
        self._setup_log_tab(self.tab_log)

        # ... (其他 UI 設定維持不變) ...

    # ... (其他 _setup_..._tab 方法維持不變) ...
    # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    # X   從這裡開始，刪除整個 _setup_gifts_tab 方法 (約 100 行)      X
    # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

    # ... (繼續保留 _setup_triggers_tab, _setup_log_tab 等其他方法) ...

    def _load_gift_map(self):
        """
        現在這個方法變得非常簡單，它只負責讀取檔案，
        然後將資料傳遞給 GiftsTab 去更新自己的 UI。
        """
        if not os.path.exists(self.GIFT_MAP_FILE):
            return
        try:
            with open(self.GIFT_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 呼叫 GiftsTab 的方法來載入設定
            self.tab_gifts.load_settings(data)
            # 同步音量狀態到 MainWindow
            self.playback_volume = self.tab_gifts.playback_volume
        except (IOError, json.JSONDecodeError) as e:
            self._log(f"錯誤: 無法載入禮物設定: {e}")

    def _save_gift_map(self):
        """
        儲存時，反過來向 GiftsTab 索取最新的設定資料。
        """
        try:
            # 從 GiftsTab 獲取需要儲存的資料
            data = self.tab_gifts.get_settings()
            with open(self.GIFT_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._build_path_to_gift_id_map()
        except IOError as e:
            self._log(f"錯誤: 無法儲存禮物設定: {e}")
            
    def _manage_gift_list(self):
        """這個方法被 GiftsTab 呼叫"""
        dialog = GiftListDialog(self, gift_manager=self.gift_manager)
        dialog.exec()
        self._refresh_menu_content()

    def _on_volume_changed(self, value: int):
        """這個方法被 GiftsTab 呼叫"""
        self.playback_volume = value
        if self.player_state == PlayerState.PLAYING:
            self.player.set_volume(self.playback_volume)

    # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    # X   從 MainWindow 刪除以下所有方法，因為它們已經搬到 GiftsTab 裡了:
    # X   - _on_tiktok_status
    # X   - _start_tiktok_listener
    # X   - _stop_tiktok_listener
    # X   - _refresh_gift_tree
    # X   - _add_gift_map
    # X   - _edit_gift_map
    # X   - _remove_gift_map
    # X   - _pick_fallback_video
    # X   - _on_gift_tree_double_clicked
    # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

    # 保留 _on_tiktok_status 因為它會更新主視窗的標籤
    def _on_tiktok_status(self, status: str):
        self.tab_gifts.tiktok_status_label.setText(f"状态: {status}")
        if "已连线" in status:
            self.tab_gifts.tiktok_status_label.setStyleSheet("color: green; font-weight: bold;")
        elif "错误" in status or "已断线" in status:
            self.tab_gifts.tiktok_status_label.setStyleSheet("color: red;")
        elif "正在连线" in status:
            self.tab_gifts.tiktok_status_label.setStyleSheet("color: orange;")
        else:
            self.tab_gifts.tiktok_status_label.setStyleSheet("")
            
    # ... (其他所有 MainWindow 的方法維持不變) ...

    def closeEvent(self, event):
        self._flush_log_buffer_to_file()
        self._auto_save_library()
        self._save_gift_map() # 這裡的邏輯不變，但內部實現已經變了
        self.tiktok_listener.stop()
        # ... (其餘部分不變) ...
        event.accept()


if __name__ == "__main__":
    # ... (主程式進入點維持不變) ...
```

### 如何應用這些修改

1.  **建立 `ui_tabs.py`**：在您的專案資料夾中，建立一個名為 `ui_tabs.py` 的新檔案，並將第一塊程式碼完整複製進去。
2.  **更新 `9.51-DedupeFix.py`**：用第二塊程式碼的內容，**替換**您現有的 `9.51-DedupeFix.py` 檔案。
    *   **重點**：這個重構移除了 `MainWindow` 中大量的方法和 UI 設定程式碼，並用更簡潔的呼叫取代。

完成後，您的程式功能應該完全一樣，但 `MainWindow` 的程式碼會變得更短、更專注於協調工作，而所有「禮物設定」相關的細節都被封裝在 `GiftsTab` 類別中了。

這是邁向一個更健康、更易於維護的專案結構的第一步，也是最重要的一步！您可以仿照這個模式，繼續將 `LibraryTab`、`TriggersTab` 等也拆分出去。