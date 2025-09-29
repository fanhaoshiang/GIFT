import json
import os
from typing import List, Dict, Any

TriggerItem = Dict[str, Any]

class TriggerManager:
    def __init__(self, filename="triggers.json"):
        self.filename = filename
        self.triggers: List[TriggerItem] = []
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.triggers = json.load(f)
                if not isinstance(self.triggers, list):
                    self.triggers = []
                    self.save()
            except (IOError, json.JSONDecodeError):
                self.triggers = []
                self.save()
        else:
            self.triggers = []
            self.save()

    def save(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.triggers, f, indent=2, ensure_ascii=False)
        except IOError:
            print(f"錯誤: 無法儲存觸發器清單到 {self.filename}")

    def get_all_triggers(self) -> List[TriggerItem]:
        return sorted(self.triggers, key=lambda x: x.get("keyword", ""))

    def add_trigger(self, trigger_info: TriggerItem):
        self.triggers.append(trigger_info)
        self.save()

    def update_trigger(self, index: int, trigger_info: TriggerItem):
        if 0 <= index < len(self.triggers):
            self.triggers[index] = trigger_info
            self.save()

    def delete_trigger(self, index: int):
        if 0 <= index < len(self.triggers):
            del self.triggers[index]
            self.save()