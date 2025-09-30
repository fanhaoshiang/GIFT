# -*- coding: utf-8 -*-
"""
Data managers for Overlay UltraLite
- LayoutsManager: layouts.json 的讀取/寫入與資料升級
- SettingsManager: gift_map.json（含 url/api_key/gift_map/fallback/interrupt/volume）
- LibraryManager: library.json 影片清單的讀寫
- ThemeManager: theme.json 主題設定的讀寫
"""

from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional


class _JsonFile:
    def __init__(self, path: str):
        self.path = path

    def _load(self, default: Any) -> Any:
        if not os.path.exists(self.path):
            return default
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return default

    def _save(self, data: Any):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


class LayoutsManager(_JsonFile):
    """
    資料格式：
    {
      "<path>": {
        "16:9": {"x":0.1,"y":0.1,"w":0.8,"h":0.8},
        "9:16": {...}
      },
      ...
    }
    """
    def __init__(self, path: str):
        super().__init__(path)
        self.data: Dict[str, Dict[str, Dict[str, float]]] = {}

    def load(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        raw = self._load(default={})
        upgraded: Dict[str, Dict[str, Dict[str, float]]] = {}
        # 升級舊格式（平面 x/y/w/h）到分長寬比格式
        try:
            for video_path, layout_info in raw.items():
                if isinstance(layout_info, dict) and "x" in layout_info:
                    layout = layout_info
                    if all(k in layout for k in ("x", "y", "w", "h")):
                        upgraded[video_path] = {"16:9": layout}
                else:
                    # 已是分長寬比格式
                    valid_aspects = {}
                    if isinstance(layout_info, dict):
                        for aspect, layout in layout_info.items():
                            if isinstance(layout, dict) and all(k in layout for k in ("x", "y", "w", "h")):
                                valid_aspects[aspect] = layout
                    if valid_aspects:
                        upgraded[video_path] = valid_aspects
        except Exception:
            upgraded = {}
        self.data = upgraded
        # 若有升級，回寫
        if len(upgraded) != len(raw):
            self.save()
        return self.data

    def save(self, data: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None):
        if data is not None:
            self.data = data
        self._save(self.data)

    def get_layout(self, video_path: str, aspect: str) -> Optional[Dict[str, float]]:
        return self.data.get(video_path, {}).get(aspect)

    def set_layout(self, video_path: str, aspect: str, layout: Dict[str, float]):
        self.data.setdefault(video_path, {})[aspect] = layout
        self.save()

    def delete_path(self, video_path: str):
        if video_path in self.data:
            del self.data[video_path]
            self.save()


class SettingsManager(_JsonFile):
    """
    gift_map.json：
    {
      "tiktok_url": "",
      "api_key": "",
      "gift_map": [],
      "fallback_video": "",
      "interrupt_on_gift": false,
      "playback_volume": 100
    }
    """
    DEFAULT = {
        "tiktok_url": "",
        "api_key": "",
        "gift_map": [],
        "fallback_video": "",
        "interrupt_on_gift": False,
        "playback_volume": 100
    }

    def __init__(self, path: str):
        super().__init__(path)
        self.data: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        d = self._load(default=self.DEFAULT)
        if not isinstance(d, dict):
            d = dict(self.DEFAULT)
        # 補上缺欄
        out = dict(self.DEFAULT)
        out.update(d)
        self.data = out
        return self.data

    def save(self, data: Optional[Dict[str, Any]] = None):
        if data is not None:
            self.data = data
        self._save(self.data)


class LibraryManager(_JsonFile):
    """
    library.json：
    ["C:/video/a.mp4", "C:/video/b.mp4", ...]
    """
    def load_list(self) -> List[str]:
        data = self._load(default=[])
        return data if isinstance(data, list) else []

    def save_list(self, items: List[str]):
        self._save(list(items))


class ThemeManager(_JsonFile):
    DEFAULT = {
        "background_color": "rgba(0, 0, 0, 180)",
        "text_color": "white",
        "font_size": 16,
        "border_radius": 10,
        "item_spacing": 10,
        "counter_font_size": 20,
        "queue_counter_font_size": 16
    }

    def load_theme(self) -> Dict[str, Any]:
        data = self._load(default=self.DEFAULT)
        base = dict(self.DEFAULT)
        if isinstance(data, dict):
            base.update(data)
        return base

    def save_theme(self, theme: Dict[str, Any]):
        out = dict(self.DEFAULT)
        if isinstance(theme, dict):
            out.update(theme)
        self._save(out)
