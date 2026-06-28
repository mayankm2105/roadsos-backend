import uuid
from datetime import datetime
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
from models.cache import CacheEntry
from utils.logger import get_logger

logger = get_logger(__name__)

# Categories that the offline cache serves
SERVICE_CATEGORIES = ["police", "hospital", "ambulance", "towing", "mechanic"]

# State code to total pincode count (approximate — used for metadata)
PINCODE_COUNTS = {
    "HR": 78,
    "DL": 11,
}


def get_cache_for_state(
    db: Session,
    state_code: str,
    pincode: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Query the CacheEntry table and return all service entries for a given
    state, grouped by category.

    Filter logic:
    1. category IN SERVICE_CATEGORIES
    2. state_code == state_code (e.g. "HR" or "DL")
    3. If pincode is provided: filter by entries whose cache_key contains
       the pincode string (use: CacheEntry.cache_key.contains(pincode))
    4. expires_at > datetime.utcnow() — only return non-expired entries

    Grouping:
    - Initialize result dict: {cat: [] for cat in SERVICE_CATEGORIES}
    - For each row: result[row.category].append(row.data)
      - row.data is already a dict (SQLAlchemy JSON column)
      - If row.data is a string (some implementations store JSON as text),
        parse it with json.loads() first

    Return the grouped dict. Counts and metadata are computed by the router.
    """
    query = db.query(CacheEntry).filter(
        CacheEntry.category.in_(SERVICE_CATEGORIES),
        CacheEntry.state_code == state_code,
        CacheEntry.expires_at > datetime.utcnow()
    )

    if pincode:
        query = query.filter(CacheEntry.cache_key.contains(pincode))

    rows = query.all()

    result: Dict[str, List[Dict[str, Any]]] = {
        cat: [] for cat in SERVICE_CATEGORIES
    }

    for row in rows:
        data = row.data
        if isinstance(data, str):
            import json
            try:
                data = json.loads(data)
            except Exception:
                continue
        if isinstance(data, dict) and row.category in result:
            result[row.category].append(data)

    return result


def get_cache_version_info(
    db: Session
) -> Dict[str, Dict]:
    """
    Return version and last_updated metadata for each state (HR and DL).

    For each state in ["HR", "DL"]:
    1. Query CacheEntry where state_code == state AND
       category IN SERVICE_CATEGORIES
    2. Find the maximum created_at timestamp across all rows
       → this is the last_updated datetime for this state
    3. Find the maximum version string (format: "YYYYMMDD")
       → use max() over version column
    4. Count total rows → entries_count

    If no rows exist for a state, use:
    - last_updated: datetime.utcnow()
    - version: datetime.utcnow().strftime("%Y%m%d")
    - entries_count: 0

    Return:
    {
      "HR": {
        "last_updated": datetime object,
        "version": "20260614",
        "entries_count": 1247
      },
      "DL": {
        "last_updated": datetime object,
        "version": "20260614",
        "entries_count": 312
      }
    }
    """
    from sqlalchemy import func
    result = {}

    for state in ["HR", "DL"]:
        rows = db.query(CacheEntry).filter(
            CacheEntry.state_code == state,
            CacheEntry.category.in_(SERVICE_CATEGORIES)
        ).all()

        if rows:
            last_updated = max(
                (r.created_at for r in rows if r.created_at),
                default=datetime.utcnow()
            )
            version = max(
                (r.version for r in rows if r.version),
                default=datetime.utcnow().strftime("%Y%m%d")
            )
            count = len(rows)
        else:
            last_updated = datetime.utcnow()
            version = datetime.utcnow().strftime("%Y%m%d")
            count = 0

        result[state] = {
            "last_updated": last_updated,
            "version": version,
            "entries_count": count
        }

    return result


def bump_cache_version(db: Session, states: List[str]) -> None:
    """
    Update the version field on all CacheEntry rows for the given states
    to today's date string. Used by the admin sync endpoint to mark that
    a sync has been triggered.

    This is a stub — real re-scraping would happen in a background task.
    For the hackathon, this just updates the version timestamp so
    GET /offline/cache/last-updated reflects a fresh version.

    Steps:
    1. new_version = datetime.utcnow().strftime("%Y%m%d%H%M")
       (include HHMM so version changes even if called twice same day)
    2. For each state: UPDATE CacheEntry SET version = new_version
       WHERE state_code == state AND category IN SERVICE_CATEGORIES
    3. db.commit()
    4. Log: "Cache version bumped for states {states} → {new_version}"
    """
    new_version = datetime.utcnow().strftime("%Y%m%d%H%M")
    for state in states:
        db.query(CacheEntry).filter(
            CacheEntry.state_code == state,
            CacheEntry.category.in_(SERVICE_CATEGORIES)
        ).update({"version": new_version}, synchronize_session=False)
    db.commit()
    logger.info(f"Cache version bumped for states {states} → {new_version}")

import json
import os
from pathlib import Path

# Path to translation files (relative to project root)
I18N_DIR = Path(__file__).parent.parent / "data" / "i18n"

SUPPORTED_LANGS = ["en", "hi", "pa", "hw"]
FALLBACK_LANG = "en"

# In-memory cache of loaded translations (avoid re-reading files every request)
_translation_cache: Dict[str, Dict[str, str]] = {}


def load_i18n_strings(lang: str) -> tuple[Dict[str, str], bool]:
    original_lang = lang.lower().strip()
    lang_to_load = original_lang
    fallback_used = False

    if lang_to_load not in SUPPORTED_LANGS:
        lang_to_load = FALLBACK_LANG
        fallback_used = True

    # Return from memory cache
    if lang_to_load in _translation_cache:
        return _translation_cache[lang_to_load], fallback_used

    # Load English baseline first (always needed for merge fallback)
    en_strings = _load_json_file("en") or {}

    if lang_to_load == "en":
        _translation_cache["en"] = en_strings
        return en_strings, fallback_used

    lang_strings = _load_json_file(lang_to_load)

    if lang_strings is None:
        logger.warning(f"i18n file missing for lang='{lang_to_load}', falling back to English")
        fallback_used = True
        result = en_strings
    else:
        # Merge: English fills any missing keys in partial locales
        result = {**en_strings, **lang_strings}

    _translation_cache[lang_to_load] = result
    return result, fallback_used


def _load_json_file(lang: str) -> Optional[Dict[str, str]]:
    """
    Load and parse a single i18n JSON file.
    Returns the "strings" dict from the file, or None on any error.
    """
    filepath = I18N_DIR / f"{lang}.json"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("strings", {})
    except FileNotFoundError:
        logger.warning(f"i18n file not found: {filepath}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"i18n JSON parse error for {lang}: {e}")
        return None
