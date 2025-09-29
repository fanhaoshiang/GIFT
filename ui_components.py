import os
import json
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QSize, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QImage, QPaintEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHBoxLayout,
    QPushButton, QAbstractItemView, QHeaderView, QMessageBox, QLineEdit,
    QDialogButtonBox, QLabel, QComboBox, QFrame, QFileDialog, QListWidget,
    QListWidgetItem, QWidget, QGridLayout, QGroupBox
)

# 依賴 Pillow
try:
    from PIL import Image

    _HAS_PILLOW = True
except ImportError:
    Image = None
    _HAS_PILLOW = False


# 為了避免循環導入，我們使用字串形式的類型提示
# from main import GiftManager, GiftInfo

class PredefinedGiftManager:
    """讀取預定義的禮物清單，用於下拉選單"""

    def __init__(self, filename="predefined_gifts.json"):
        self.filename = filename
        self.predefined_gifts: List[Dict[str, str]] = []
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.predefined_gifts = json.load(f)
            except (IOError, json.JSONDecodeError) as e:
                print(f"警告: 無法載入預定義禮物清單 {self.filename}: {e}")
                self.predefined_gifts = []

    def get_all(self) -> List[Dict[str, str]]:
        return sorted(self.predefined_gifts, key=lambda x: x.get("name_cn", ""))


class GiftEditor(QDialog):
    def __init__(self, parent=None, item: Optional[dict] = None, predefined_gifts: List[Dict[str, str]] = []):
        super().__init__(parent)
        self.setWindowTitle("編輯禮物")
        self.item = item or {}
        self.predefined_gifts = predefined_gifts

        layout = QVBoxLayout(self)

        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("選擇預設禮物:"))
        self.gift_selector_combo = QComboBox()
        self.gift_selector_combo.addItem("--- 手動輸入新禮物 ---", userData=None)
        for gift in self.predefined_gifts:
            display_text = f"{gift.get('name_cn', '')} ({gift.get('name_en', '')})"
            self.gift_selector_combo.addItem(display_text, userData=gift)
        self.gift_selector_combo.currentIndexChanged.connect(self._on_predefined_gift_selected)
        selector_layout.addWidget(self.gift_selector_combo)
        layout.addLayout(selector_layout)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        cn_layout = QHBoxLayout()
        cn_layout.addWidget(QLabel("中文名:"))
        self.cn_edit = QLineEdit(self.item.get("name_cn", ""))
        cn_layout.addWidget(self.cn_edit)
        layout.addLayout(cn_layout)

        en_layout = QHBoxLayout()
        en_layout.addWidget(QLabel("英文關鍵字:"))
        self.en_edit = QLineEdit(self.item.get("name_en", ""))
        en_layout.addWidget(self.en_edit)
        layout.addLayout(en_layout)

        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("禮物 ID:"))
        self.id_edit = QLineEdit(self.item.get("id", ""))
        id_layout.addWidget(self.id_edit)
        layout.addLayout(id_layout)

        img_layout = QHBoxLayout()
        img_layout.addWidget(QLabel("禮物圖片:"))
        self.img_path_edit = QLineEdit(self.item.get("image_path", ""))
        self.img_path_edit.setReadOnly(True)
        btn_pick_img = QPushButton("選擇...")
        btn_pick_img.clicked.connect(self._pick_image)
        img_layout.addWidget(self.img_path_edit, 1)
        img_layout.addWidget(btn_pick_img)
        layout.addLayout(img_layout)

        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("效果說明:"))
        self.desc_edit = QLineEdit(self.item.get("description", ""))
        desc_layout.addWidget(self.desc_edit)
        layout.addLayout(desc_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self.item.get("id"):
            for i in range(1, self.gift_selector_combo.count()):
                gift_data = self.gift_selector_combo.itemData(i)
                if gift_data and gift_data.get("id") == self.item.get("id"):
                    self.gift_selector_combo.setCurrentIndex(i)
                    return
            self.gift_selector_combo.setCurrentIndex(0)
        else:
            self.gift_selector_combo.setCurrentIndex(0)
            self._on_predefined_gift_selected(0)

    def _on_predefined_gift_selected(self, index):
        selected_data = self.gift_selector_combo.itemData(index)
        if selected_data:
            self.cn_edit.setText(selected_data.get("name_cn", ""))
            self.en_edit.setText(selected_data.get("name_en", ""))
            self.id_edit.setText(selected_data.get("id", ""))
            self.cn_edit.setReadOnly(True)
            self.en_edit.setReadOnly(True)
            self.id_edit.setReadOnly(True)
        else:
            if not self.item.get("id"):
                self.cn_edit.clear()
                self.en_edit.clear()
                self.id_edit.clear()
            self.cn_edit.setReadOnly(False)
            self.en_edit.setReadOnly(False)
            self.id_edit.setReadOnly(False)

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇禮物圖片", "",
                                              "圖片檔案 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self.img_path_edit.setText(path)

            if self.gift_selector_combo.currentIndex() == 0:
                filename = os.path.basename(path)
                name_without_ext, _ = os.path.splitext(filename)

                if not self.cn_edit.text().strip():
                    self.cn_edit.setText(name_without_ext)
                if not self.en_edit.text().strip():
                    self.en_edit.setText(name_without_ext)
                if not self.id_edit.text().strip():
                    self.id_edit.setText(name_without_ext)

    def get_data(self) -> dict:
        return {
            "name_cn": self.cn_edit.text().strip(),
            "name_en": self.en_edit.text().strip(),
            "id": self.id_edit.text().strip(),
            "image_path": self.img_path_edit.text().strip(),
            "description": self.desc_edit.text().strip()
        }


class GiftListDialog(QDialog):
    def __init__(self, parent=None, gift_manager=None):
        super().__init__(parent)
        self.gift_manager = gift_manager

        try:
            from main import application_path
            predefined_gifts_path = os.path.join(application_path, "predefined_gifts.json")
        except (ImportError, NameError):
            predefined_gifts_path = "predefined_gifts.json"

        self.predefined_gift_manager = PredefinedGiftManager(predefined_gifts_path)
        self.setWindowTitle("礼物清单管理")
        self.setMinimumSize(600, 400)
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["中文名", "英文關鍵字", "禮物 ID", "圖片", "效果說明"])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_add = QPushButton("新增")
        btn_edit = QPushButton("编辑")
        btn_del = QPushButton("删除")
        btn_add.clicked.connect(self._add_item)
        btn_edit.clicked.connect(self._edit_item)
        btn_del.clicked.connect(self._del_item)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_del)
        layout.addLayout(btn_layout)

        self._refresh_table()

    def _refresh_table(self):
        self.table.setRowCount(0)
        if not self.gift_manager:
            return
        gifts = self.gift_manager.get_all_gifts()
        self.table.setRowCount(len(gifts))
        for row, gift in enumerate(gifts):
            self.table.setItem(row, 0, QTableWidgetItem(gift.get("name_cn", "")))
            self.table.setItem(row, 1, QTableWidgetItem(gift.get("name_en", "")))
            self.table.setItem(row, 2, QTableWidgetItem(gift.get("id", "")))
            img_path = gift.get("image_path", "")
            self.table.setItem(
                row, 3,
                QTableWidgetItem(os.path.basename(img_path)
                                 if img_path else "未設定"))
            self.table.setItem(row, 4,
                               QTableWidgetItem(gift.get("description", "")))

    def _add_item(self):
        dialog = GiftEditor(self, predefined_gifts=self.predefined_gift_manager.get_all())
        if dialog.exec():
            new_data = dialog.get_data()
            if not new_data["name_cn"] or not new_data["name_en"]:
                QMessageBox.warning(self, "提示", "中文名和英文关键字不能为空。")
                return
            self.gift_manager.add_gift(new_data)
            self._refresh_table()

    def _edit_item(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择一个要编辑的礼物。")
            return

        original_name_en_item = self.table.item(current_row, 1)
        if not original_name_en_item or not original_name_en_item.text():
            QMessageBox.warning(self, "錯誤", "無法獲取選定禮物的唯一標識(英文名)。")
            return
        original_name_en = original_name_en_item.text()

        item_data_to_edit = None
        for gift in self.gift_manager.gifts:
            if gift.get("name_en") == original_name_en:
                item_data_to_edit = gift
                break

        if not item_data_to_edit:
            QMessageBox.critical(self, "嚴重錯誤", "在資料源中找不到選定的禮物，無法編輯。")
            return

        dialog = GiftEditor(self, item=item_data_to_edit, predefined_gifts=self.predefined_gift_manager.get_all())
        if dialog.exec():
            updated_data = dialog.get_data()
            if not updated_data["name_cn"] or not updated_data["name_en"]:
                QMessageBox.warning(self, "提示", "中文名和英文关键字不能为空。")
                return

            self.gift_manager.update_gift_by_name(original_name_en, updated_data)
            self._refresh_table()

    def _del_item(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "请先选择一个要删除的礼物。")
            return

        name_en_item = self.table.item(current_row, 1)
        if not name_en_item or not name_en_item.text():
            QMessageBox.warning(self, "錯誤", "無法獲取選定禮物的唯一標識(英文名)。")
            return

        name_en_to_delete = name_en_item.text()

        name_cn_item = self.table.item(current_row, 0)
        display_name = name_cn_item.text() if name_cn_item else name_en_to_delete

        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除礼物「{display_name}」吗？")

        if reply == QMessageBox.StandardButton.Yes:
            self.gift_manager.delete_gift_by_name(name_en_to_delete)
            self._refresh_table()


class MenuItemWidget(QWidget):
    """單個菜單項的 Widget (使用 QGridLayout 的最終佈局修正版)"""

    def __init__(self, gift_info: dict, theme_settings: dict, parent=None):
        super().__init__(parent)
        self.gift_info = gift_info
        self.theme_settings = theme_settings

        grid_layout = QGridLayout(self)
        grid_layout.setContentsMargins(5, 5, 5, 5)
        grid_layout.setSpacing(self.theme_settings.get("item_spacing", 10))

        self.image_label = QLabel()
        self.image_label.setFixedSize(64, 64)
        self.image_label.setScaledContents(True)
        grid_layout.addWidget(self.image_label, 0, 0)

        self.counter_label = QLabel("0", parent=self.image_label)

        image_path = self.gift_info.get("image_path", "")
        if image_path and os.path.exists(image_path):
            pixmap = self._load_pixmap(image_path)
            if pixmap:
                self.image_label.setPixmap(pixmap)

        self.desc_label = QLabel(self.gift_info.get("description", ""))
        self.desc_label.setWordWrap(True)
        grid_layout.addWidget(self.desc_label, 0, 1)

        self.queue_count_label = QLabel("")
        grid_layout.addWidget(self.queue_count_label, 0, 2)

        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(0, 0)
        grid_layout.setColumnStretch(2, 0)

        self.apply_styles()

    def apply_styles(self):
        """集中應用所有樣式"""
        font_size = self.theme_settings.get("font_size", 16)
        text_color = self.theme_settings.get("text_color", "white")
        counter_font_size = self.theme_settings.get("counter_font_size", font_size + 4)
        queue_counter_font_size = self.theme_settings.get("queue_counter_font_size", font_size)

        self.desc_label.setStyleSheet(
            f"font-size: {font_size}px; color: {text_color}; background-color: transparent; font-weight: bold;"
        )
        self.queue_count_label.setStyleSheet(
            f"font-size: {queue_counter_font_size}px; color: #FFD700; font-weight: bold; background-color: transparent;"
        )
        self.counter_label.setStyleSheet(
            f"font-size: {counter_font_size}px; color: white; background-color: rgba(0,0,0,0.6); "
            "border-radius: 5px; padding: 2px 5px; font-weight: bold;"
        )

    def set_queue_count(self, count: int, show: bool):
        if count > 0 and show:
            self.queue_count_label.setText(f"x{count}")
        else:
            self.queue_count_label.setText("")

    def resizeEvent(self, event: QPaintEvent):
        super().resizeEvent(event)
        self.update_counter_position()

    def update_counter_position(self):
        if not self.counter_label.parent():
            return

        parent_rect = self.counter_label.parent().rect()
        x = (parent_rect.width() - self.counter_label.width()) / 2
        y = parent_rect.height() - self.counter_label.height() - 5
        self.counter_label.move(int(x), int(y))

    def set_count(self, count: int):
        self.counter_label.setText(str(count))
        self.counter_label.adjustSize()
        self.update_counter_position()

    def show_counter(self, show: bool):
        self.counter_label.setVisible(show)

    def _load_pixmap(self, path: str) -> Optional[QPixmap]:
        if not _HAS_PILLOW:
            return QPixmap(path)
        try:
            with Image.open(path) as img:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                qimage = QImage(img.tobytes(), img.width, img.height,
                                QImage.Format.Format_RGBA8888)
                return QPixmap.fromImage(qimage)
        except Exception as e:
            print(f"錯誤: 使用 Pillow 載入圖片失敗 {path}: {e}")
            return QPixmap(path)

    def trigger_highlight(self):
        original_style = self.styleSheet()
        self.setStyleSheet(original_style + "background-color: rgba(255, 215, 0, 0.3); border-radius: 5px;")
        QTimer.singleShot(2000, lambda: self.setStyleSheet(original_style))


class GameMenuContainer(QFrame):
    """
    一個菜單容器，現在會被放置在專用的綠幕視窗中。
    """

    def __init__(self, parent=None, theme_settings=None):
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._is_editing = False
        self._is_dragging = False
        self._is_resizing = False
        self._start_pos = QPoint()
        self._start_geom = QRect()
        self.resize_margin = 15
        self.setMouseTracking(True)

        self.setObjectName("background")
        self.theme_settings = theme_settings if theme_settings else {}
        self.apply_theme()

        self.list_widget = QListWidget(self)
        self.list_widget.setStyleSheet("background-color: transparent; border: none;")
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content_layout = QVBoxLayout(self)
        self.content_layout.addWidget(self.list_widget)

    def update_menu_data(self, gifts: List[dict], counts: Dict[str, int], show_counter: bool):
        """填充 QListWidget，並設置計數器"""
        self.list_widget.clear()
        for gift in gifts:
            item_widget = MenuItemWidget(gift, self.theme_settings)

            gift_id = gift.get("id")
            count = counts.get(gift_id, 0)
            item_widget.set_count(count)
            item_widget.show_counter(show_counter)

            list_item = QListWidgetItem(self.list_widget)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.ItemDataRole.UserRole, gift.get("name_en"))
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)

    def highlight_item_by_key(self, key: str):
        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            if list_item.data(Qt.ItemDataRole.UserRole) == key:
                widget = self.list_widget.itemWidget(list_item)
                if isinstance(widget, MenuItemWidget):
                    widget.trigger_highlight()
                break

    def setEditing(self, is_editing: bool):
        self._is_editing = is_editing
        self.apply_theme()
        if is_editing:
            self.raise_()
        else:
            self.unsetCursor()

    def apply_theme(self):
        bg_color = self.theme_settings.get("background_color", "rgba(0, 0, 0, 180)")
        radius = self.theme_settings.get("border_radius", 10)
        border_style = "border: 2px dashed rgba(255, 255, 0, 0.7);" if self._is_editing else "border: none;"
        self.setStyleSheet(
            f"""
            #background {{
                background-color: {bg_color};
                border-radius: {radius}px;
                {border_style}
            }}
            """
        )

    def mousePressEvent(self, event: QMouseEvent):
        if not self._is_editing or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        if (pos.x() >= self.width() - self.resize_margin and
                pos.y() >= self.height() - self.resize_margin):
            self._is_resizing = True
        else:
            self._is_dragging = True
        self._start_pos = event.globalPosition().toPoint()
        self._start_geom = self.geometry()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._is_editing:
            return
        global_pos = event.globalPosition().toPoint()
        if self._is_resizing or self._is_dragging:
            parent_widget = self.parentWidget()
            parent_rect = parent_widget.rect() if parent_widget else self.rect()
            delta = global_pos - self._start_pos
            if self._is_resizing:
                new_width = self._start_geom.width() + delta.x()
                new_height = self._start_geom.height() + delta.y()
                new_geom = QRect(self._start_geom.topLeft(), QSize(new_width, new_height))
                if new_geom.right() > parent_rect.right(): new_geom.setRight(parent_rect.right())
                if new_geom.bottom() > parent_rect.bottom(): new_geom.setBottom(parent_rect.bottom())
                self.setGeometry(new_geom)
            elif self._is_dragging:
                new_top_left = self._start_geom.topLeft() + delta
                new_top_left.setX(max(0, min(new_top_left.x(), parent_rect.width() - self.width())))
                new_top_left.setY(max(0, min(new_top_left.y(), parent_rect.height() - self.height())))
                self.move(new_top_left)
            if parent_widget:
                parent_widget.update()
        else:
            pos = event.position().toPoint()
            if (pos.x() >= self.width() - self.resize_margin and
                    pos.y() >= self.height() - self.resize_margin):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self._is_editing:
            return
        self._is_dragging = False
        self._is_resizing = False
        self.unsetCursor()
        event.accept()


class TriggerEditDialog(QDialog):
    def __init__(self, parent=None, item: Optional[dict] = None, library_paths: List[str] = []):
        super().__init__(parent)
        self.setWindowTitle("編輯關鍵字觸發")
        self.item = item or {}
        layout = QVBoxLayout(self)

        # 關鍵字輸入
        kw_layout = QHBoxLayout()
        kw_layout.addWidget(QLabel("觀眾留言關鍵字:"))
        self.keyword_edit = QLineEdit(self.item.get("keyword", ""))
        kw_layout.addWidget(self.keyword_edit)
        layout.addLayout(kw_layout)

        # 觸發影片 (可選)
        self.video_group = QGroupBox("觸發影片 (可選)")
        self.video_group.setCheckable(True)
        self.video_group.setChecked(bool(self.item.get("path")))
        video_layout = QHBoxLayout(self.video_group)

        video_layout.addWidget(QLabel("影片路徑:"))
        self.path_combo = QComboBox()
        self.path_combo.addItem("--- 不選擇影片 ---", userData="")
        for path in library_paths:
            self.path_combo.addItem(os.path.basename(path), userData=path)

        current_path = self.item.get("path", "")
        if current_path:
            index = self.path_combo.findData(current_path)
            if index >= 0:
                self.path_combo.setCurrentIndex(index)
        video_layout.addWidget(self.path_combo)
        layout.addWidget(self.video_group)

        # 朗讀指定回覆 (可選)
        self.tts_group = QGroupBox("朗讀指定回覆 (可選)")
        self.tts_group.setCheckable(True)
        self.tts_group.setChecked(bool(self.item.get("tts_response")))
        tts_layout = QHBoxLayout(self.tts_group)

        tts_layout.addWidget(QLabel("朗讀內容:"))
        self.tts_response_edit = QLineEdit(self.item.get("tts_response", ""))
        tts_layout.addWidget(self.tts_response_edit)
        layout.addWidget(self.tts_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 將 groupbox 的勾選狀態與內部元件的啟用狀態連動
        self.video_group.toggled.connect(self.path_combo.setEnabled)
        self.tts_group.toggled.connect(self.tts_response_edit.setEnabled)
        self.path_combo.setEnabled(self.video_group.isChecked())
        self.tts_response_edit.setEnabled(self.tts_group.isChecked())

    def get_data(self) -> dict:
        data = {"keyword": self.keyword_edit.text().strip()}

        if self.video_group.isChecked():
            selected_path_index = self.path_combo.currentIndex()
            path = self.path_combo.itemData(selected_path_index) if selected_path_index >= 0 else ""
            if path:
                data["path"] = path

        if self.tts_group.isChecked():
            tts_response = self.tts_response_edit.text().strip()
            if tts_response:
                data["tts_response"] = tts_response

        return data


class MarqueeLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._px = 0
        self.py = 0
        self._text = ""
        self.text_width = 0
        self.animation = QPropertyAnimation(self, b"px", self)
        self.animation.setLoopCount(-1)

    def setText(self, text):
        self._text = text
        self.update_text()

    def text(self):
        return self._text

    def update_text(self):
        self._px = 0
        self.text_width = self.fontMetrics().horizontalAdvance(self._text)
        self.update()
        self.start_animation()

    def start_animation(self):
        self.animation.stop()
        if self.text_width > self.width():
            self.animation.setDuration((self.text_width + self.width()) * 10)
            self.animation.setStartValue(self.width())
            self.animation.setEndValue(-self.text_width)
            self.animation.start()
        else:
            self._px = 0
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.text_width > self.width():
            x = self._px
        else:
            x = (self.width() - self.text_width) / 2

        painter.drawText(x, self.py + self.fontMetrics().ascent(), self._text)

    def resizeEvent(self, event):
        self.py = (self.height() - self.fontMetrics().height()) / 2
        self.update_text()

    def get_px(self):
        return self._px

    def set_px(self, val):
        self._px = val
        self.update()

    px = Property(int, get_px, set_px)


class NowPlayingWidget(QWidget):
    """用於顯示正在播放歌曲的 Widget"""

    def __init__(self, theme_settings: dict, parent=None):
        super().__init__(parent)
        self.theme_settings = theme_settings
        self.setObjectName("background")  # 為了讓樣式表能選中它

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 5, 10, 5)
        main_layout.setSpacing(15)

        # 固定的音樂圖示
        self.icon_label = QLabel("🎵")
        main_layout.addWidget(self.icon_label)

        # 跑馬燈標籤
        self.marquee_label = MarqueeLabel(self)
        main_layout.addWidget(self.marquee_label, 1)

        self.apply_styles()

    def apply_styles(self):
        """應用主題設定"""
        # 從主題設定中獲取專門為 NowPlaying Overlay 設計的樣式
        bg_color = self.theme_settings.get("now_playing_bg_color", "rgba(0, 0, 0, 180)")
        text_color = self.theme_settings.get("now_playing_text_color", "white")
        font_size = self.theme_settings.get("now_playing_font_size", 24)
        radius = self.theme_settings.get("now_playing_border_radius", 10)

        self.setStyleSheet(f"""
            #background {{
                background-color: {bg_color};
                border-radius: {radius}px;
            }}
        """)

        self.icon_label.setStyleSheet(f"font-size: {font_size}px; background-color: transparent;")
        self.marquee_label.setStyleSheet(f"color: {text_color}; font-size: {font_size}px; font-weight: bold;")

    def setText(self, text: str):
        self.marquee_label.setText(text)


class NowPlayingOverlay(QWidget):
    def __init__(self, theme_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在播放 Overlay")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(600, 60)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 現在它包含的是 NowPlayingWidget
        self.content_widget = NowPlayingWidget(theme_settings, self)
        layout.addWidget(self.content_widget)

        self._is_dragging = False
        self._start_pos = QPoint()

    def set_stay_on_top(self, stay_on_top: bool):
        if stay_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        else:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        # 重新顯示以應用 flag 變更
        if self.isVisible():
            self.show()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._start_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._is_dragging = False
        event.accept()

    def setText(self, text: str):
        self.content_widget.setText(text)

    def apply_theme(self, theme_settings: dict):
        """接收新的主題設定並應用"""
        self.content_widget.theme_settings = theme_settings
        self.content_widget.apply_styles()