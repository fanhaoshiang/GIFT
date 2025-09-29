# Project: UniTTS-OneVoice-Tunable
import threading, time
from collections import deque
from typing import List, Optional
from PySide6.QtCore import QObject

try:
    import pyttsx3
    _HAS_TTS = True
except ImportError:
    pyttsx3 = None  # type: ignore
    _HAS_TTS = False
    print("[WARN] pip install pyttsx3")

try:
    import pythoncom
    _HAS_PYCOM = True
except Exception:
    pythoncom = None  # type: ignore
    _HAS_PYCOM = False


def _pick_universal_voice(engine: "pyttsx3.Engine") -> Optional[str]:
    try:
        voices = engine.getProperty("voices")  # type: ignore
        for v in voices:
            langs = getattr(v, "languages", []) or []
            if any(
                (isinstance(l, bytes) and b"zh" in l) or (isinstance(l, str) and "zh" in l.lower())
                for l in langs
            ):
                return v.id
        prefer = ("Chinese", "Huihui", "Hanhan", "Yating", "Xiaoyi", "Hsiao", "Lili", "Tracy", "Kangkang")
        for v in voices:
            name = (getattr(v, "name", "") or "")
            if any(k.lower() in name.lower() for k in prefer):
                return v.id
        return engine.getProperty("voice")  # type: ignore
    except Exception:
        return None


class SpeechEngine(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine: Optional["pyttsx3.Engine"] = None  # type: ignore
        self.queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self.running = False
        self.thread: Optional[threading.Thread] = None

        # 可調參數（預設先別太快）
        self._base_rate = 180
        self._rate_offset = -10     # 語速微調，正數更快，負數更慢
        self._volume = 1.0          # 0.0–1.0
        self._gap_ms = 0            # 每字之間的微停頓，0=關閉；建議 15–40 可提高清晰
        self._fixed_voice_id: Optional[str] = None

        if not _HAS_TTS:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # === 參數介面 ===
    def set_rate(self, words_per_minute: int):
        """絕對語速。例：150、180、200。"""
        with self._cond:
            self._base_rate = int(words_per_minute)

    def set_rate_offset(self, delta: int):
        """相對語速偏移。正=更快，負=更慢。"""
        with self._cond:
            self._rate_offset = int(delta)

    def set_volume(self, vol: float):
        """音量 0.0–1.0。"""
        with self._cond:
            self._volume = max(0.0, min(1.0, float(vol)))

    def set_gap_ms(self, ms: int):
        """每字之間的微停頓毫秒數。15–40 會提高清晰度；0 關閉。"""
        with self._cond:
            self._gap_ms = max(0, int(ms))

    # === 使用 ===
    def say(self, text: str):
        if not _HAS_TTS or not text or not text.strip():
            return
        with self._cond:
            self.queue.append(text.strip())
            self._cond.notify()

    def snapshot(self) -> List[str]:
        with self._lock:
            return list(self.queue)

    def stop(self, graceful: bool = True):
        with self._cond:
            self.running = False
            if not graceful:
                self.queue.clear()
            self._cond.notify_all()
        th = self.thread
        if th and th.is_alive():
            th.join(timeout=5.0)

    # === 內部 ===
    def _pump_once(self):
        try:
            if self.engine:
                self.engine.iterate()  # type: ignore
        except Exception:
            pass
        if _HAS_PYCOM:
            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass

    def _sleep_pump(self, ms: int):
        end = time.time() + ms / 1000.0
        while time.time() < end:
            self._pump_once()
            time.sleep(0.01)

    def _run(self):
        if _HAS_PYCOM:
            try:
                pythoncom.CoInitialize()
            except Exception as e:
                print(f"[WARN] CoInitialize 失敗: {e}")

        try:
            self.engine = pyttsx3.init(driverName="sapi5")  # type: ignore
            self._fixed_voice_id = _pick_universal_voice(self.engine)
            if self._fixed_voice_id:
                try:
                    self.engine.setProperty("voice", self._fixed_voice_id)  # type: ignore
                except Exception:
                    pass

            try:
                self._base_rate = int(self.engine.getProperty("rate"))  # type: ignore
            except Exception:
                self._base_rate = 180
            try:
                self.engine.setProperty("volume", self._volume)  # type: ignore
            except Exception:
                pass

            self.engine.startLoop(False)  # type: ignore

            while True:
                with self._cond:
                    while self.running and not self.queue:
                        self._cond.wait(timeout=0.2)
                        self._pump_once()
                    if not self.running and not self.queue:
                        break
                    text = self.queue.popleft()

                # 套用目前速率與音量
                try:
                    self.engine.setProperty("rate", int(self._base_rate + self._rate_offset))  # type: ignore
                    self.engine.setProperty("volume", float(self._volume))                     # type: ignore
                except Exception:
                    pass

                if text and self.engine:
                    if self._gap_ms <= 0:
                        # 直接念整句
                        try:
                            self.engine.say(text)  # type: ignore
                        except Exception as e:
                            print(f"TTS 錯誤(say): {e}")
                        for _ in range(12):
                            self._pump_once()
                        while True:
                            busy = True
                            try:
                                busy = self.engine.isBusy()  # type: ignore
                            except Exception:
                                busy = True
                            self._pump_once()
                            if not busy:
                                break
                    else:
                        # 逐字帶微停，提升清晰度（中英皆適用）
                        for ch in text:
                            try:
                                self.engine.say(ch)  # type: ignore
                            except Exception:
                                pass
                            # 推進直到該字送入播放
                            for _ in range(6):
                                self._pump_once()
                            # 播放期間推進
                            while True:
                                busy = True
                                try:
                                    busy = self.engine.isBusy()  # type: ignore
                                except Exception:
                                    busy = True
                                self._pump_once()
                                if not busy:
                                    break
                            # 微停頓
                            if ch.strip():
                                self._sleep_pump(self._gap_ms)

        finally:
            try:
                if self.engine is not None:
                    try:
                        self.engine.endLoop()  # type: ignore
                    except Exception:
                        pass
                    try:
                        self.engine.stop()     # type: ignore
                    except Exception:
                        pass
            except Exception:
                pass
            self.engine = None

            if _HAS_PYCOM:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass


# 測試與參數示例
if __name__ == "__main__":
    se = SpeechEngine()
    se.set_rate_offset(-15)  # 更慢更清楚；正數=更快
    se.set_volume(0.95)
    se.set_gap_ms(25)        # 15–40 提高清晰；0 關閉
    se.say("今天天氣不錯，we test English and 中文 together.")
    time.sleep(1.0)
    se.stop(graceful=True)
    print("done")