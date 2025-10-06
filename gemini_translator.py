# -*- coding: utf-8 -*-
"""
Gemini Translator - simple wrapper with model listing
依賴: pip install google-generativeai
"""
from __future__ import annotations

from typing import Optional, Tuple, List

# 常見模型（補充候選，實際可用性取決於金鑰/區域/帳務）
KNOWN_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",         # 8B（有時俗稱 lite）
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
    "gemini-1.5-pro-latest",
]

def _normalize(name: str) -> str:
    # 把 "models/xxx" -> "xxx"
    return (name or "").split("/")[-1].strip()

class Translator:
    """封裝 Google Gemini 翻譯功能的翻譯器。"""
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        try:
            import google.generativeai as genai
        except Exception as e:
            raise RuntimeError("缺少相依性: 請先安裝 google-generativeai") from e

        if not api_key:
            raise ValueError("API 金鑰不能為空。")
        genai.configure(api_key=api_key)

        self.model_name = _normalize(model) or "gemini-1.5-flash"
        self._model = genai.GenerativeModel(self.model_name)
        # 可重用對話（非必要，但可微幅加速）
        self._chat = self._model.start_chat(history=[])

    def translate(self, text_to_translate: str) -> Optional[str]:
        """
        辨識語言並將文字翻譯成繁體中文。
        預期回傳格式: "[來源語言]: [翻譯後的繁體中文內容]"
        發生錯誤則回傳 None。
        """
        if not text_to_translate:
            return None
        prompt = f"""
請遵循以下兩步驟：
1. 辨識以下文字是哪一國的語言。
2. 嚴格將該文字翻譯成流暢、自然的繁體中文。
3. 嚴格按照「[來源語言]: [翻譯後的繁體中文內容]」的格式輸出最終結果，不要包含任何額外的說明或引號。
要處理的文字是：'{text_to_translate}'
""".strip()
        try:
            resp = self._chat.send_message(prompt)
            text = (getattr(resp, "text", None) or "").strip()
            return text or None
        except Exception:
            return None

    @staticmethod
    def parse_result(result: str) -> Tuple[str, str]:
        """
        將 "[來源語言]: [翻譯]" 解析成 (source_lang, translated_text)。
        若格式無法解析，回傳 ("", 原字串)。
        """
        if not result:
            return "", ""
        parts = result.split(":", 1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
        return "", result.strip()


def list_generation_models(api_key: str, include_known: bool = True) -> List[str]:
    """
    回傳具備 generateContent 能力的模型清單（名稱字串），並去掉 models/ 前綴。
    - 若 include_known=True，會把常見模型也併入清單，方便使用者選擇或手動測試。
    - 實際可用性以你的金鑰/區域/帳務為準（選了不可用會在初始化時報錯）。
    """
    models: List[str] = []
    if not api_key:
        return KNOWN_MODELS[:] if include_known else []

    # 延後匯入，減少啟動時噪音
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        raw = list(genai.list_models())
        for m in raw:
            try:
                methods = getattr(m, "supported_generation_methods", []) or []
                if "generateContent" in methods:
                    models.append(_normalize(getattr(m, "name", "")))
            except Exception:
                pass
    except Exception:
        # 忽略列舉失敗，走 fallback
        pass

    # 併入常見模型並去重
    merged = set(models)
    if include_known:
        merged.update(KNOWN_MODELS)

    # 排序：flash > flash-8b > pro > 其他
    def rank(n: str):
        nl = n.lower()
        if "flash" in nl:
            # 把 8b 稍後於 flash
            return (1, 1 if ("8b" in nl or "lite" in nl) else 0, nl)
        if "pro" in nl:
            return (2, 0, nl)
        return (3, 0, nl)

    result = sorted({x for x in merged if x}, key=rank)
    return result
