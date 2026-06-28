from pydantic import BaseModel
from typing import Dict


class I18nStringsResponse(BaseModel):
    lang: str                         # "en" | "hi" | "pa" | "hw"
    strings: Dict[str, str]           # all key-value pairs for this language
    fallback_used: bool = False       # True if some keys fell back to English
    total_keys: int = 0               # count of keys returned
