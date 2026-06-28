from fastapi import APIRouter, Query
from typing import Annotated
from schemas.i18n import I18nStringsResponse
from services.cache_manager import load_i18n_strings, SUPPORTED_LANGS
from utils.logger import get_logger

router = APIRouter(tags=["i18n"])
logger = get_logger(__name__)


# ── Endpoint: GET /i18n/strings ───────────────────────────────

@router.get("/i18n/strings", response_model=I18nStringsResponse)
async def get_i18n_strings(
    lang: Annotated[str, Query(
        ...,
        description="Language code: en | hi | pa | hw"
    )]
):
    """
    Return all UI strings for the requested language.
    Used by the Lovable PWA frontend to localize the entire UI.

    Logic:
    1. Call load_i18n_strings(lang) → (strings_dict, fallback_used)
    2. Count keys in strings_dict → total_keys
    3. Return I18nStringsResponse

    Never returns 404 or 500 — always returns strings.
    If lang is unsupported, returns English with fallback_used=True.
    """
    strings, fallback_used = load_i18n_strings(lang)

    if fallback_used:
        logger.info(
            f"i18n fallback used for lang='{lang}' → returning English"
        )

    return I18nStringsResponse(
        lang=lang,
        strings=strings,
        fallback_used=fallback_used,
        total_keys=len(strings)
    )
