import random
import string
from urllib.parse import quote
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# SOS ID format: 3 uppercase letters + 3 digits + 2 uppercase letters
# Example: "ABX291KZ"
# This is short enough to share verbally and unique enough for 24h use
SOS_ID_LENGTH = 8
SOS_ID_CHARS = string.ascii_uppercase + string.digits


def generate_sos_id() -> str:
    """
    Generate a short alphanumeric SOS ID.
    Format: 8 characters, uppercase letters + digits only.
    Example outputs: "ABX291KZ", "R7TK92MN", "ALPHA123"

    Collision probability is negligible for hackathon scale
    (36^8 = 2.8 trillion combinations, 24h TTL).
    """
    return "".join(random.choices(SOS_ID_CHARS, k=SOS_ID_LENGTH))


def build_shareable_link(sos_id: str) -> str:
    """
    Build the public shareable URL for this SOS.
    Uses SOS_BASE_URL from settings (default: https://roadsos.vercel.app/sos/)
    Strips trailing slash from base URL to avoid double slashes.
    """
    base = settings.SOS_BASE_URL.rstrip("/")
    return f"{base}/{sos_id}"


def build_whatsapp_link(sos_id: str, severity: str,
                        additional_info: str = "") -> str:
    """
    Build a WhatsApp share link that pre-fills a message.
    Format: https://wa.me/?text=<encoded_message>

    The message should be short, urgent, and include the shareable link.
    Include severity emoji for visual urgency.

    Severity emoji map:
      low      → ℹ️
      medium   → ⚠️
      high     → 🚨
      critical → 🆘

    Example message (English):
      🚨 EMERGENCY: I had an accident and need help!
      📍 View my location & nearest services:
      https://roadsos.vercel.app/sos/ABX291KZ
      ⏰ This link expires in 24 hours.
      Additional info: Two-wheeler accident, possible chest injury

    URL encode the full message using urllib.parse.quote().
    """
    SEVERITY_EMOJI = {
        "low": "ℹ️",
        "medium": "⚠️",
        "high": "🚨",
        "critical": "🆘"
    }
    emoji = SEVERITY_EMOJI.get(severity, "🚨")
    link = build_shareable_link(sos_id)

    message_parts = [
        f"{emoji} EMERGENCY: I had an accident and need help!",
        f"📍 View my location & nearest emergency services:",
        link,
        "⏰ This link expires in 24 hours."
    ]
    if additional_info and additional_info.strip():
        message_parts.append(f"ℹ️ {additional_info.strip()}")

    full_message = "\n".join(message_parts)
    encoded = quote(full_message)
    return f"https://wa.me/?text={encoded}"


def build_whatsapp_link_for_contact(
    sos_id: str,
    phone: str,
    severity: str,
    additional_info: str = ""
) -> str:
    """
    Build a WhatsApp link for a SPECIFIC contact phone number.
    Format: https://wa.me/<phone>?text=<encoded_message>

    Phone number formatting:
    - Remove all non-digit characters except leading +
    - If starts with 0: replace with +91 (Indian number)
    - If 10 digits with no prefix: prepend +91
    - If already has +: use as-is

    Example: "09876543210" → "+919876543210"
             "9876543210"  → "+919876543210"
             "+919876543210" → "+919876543210"
    """
    # Clean phone number
    clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")

    if clean_phone.startswith("0"):
        clean_phone = "+91" + clean_phone[1:]
    elif clean_phone.startswith("+"):
        pass  # already formatted
    elif len(clean_phone) == 10:
        clean_phone = "+91" + clean_phone
    elif len(clean_phone) == 12 and clean_phone.startswith("91"):
        clean_phone = "+" + clean_phone

    link = build_shareable_link(sos_id)
    emoji = {"low": "ℹ️", "medium": "⚠️",
             "high": "🚨", "critical": "🆘"}.get(severity, "🚨")

    message_parts = [
        f"{emoji} EMERGENCY ALERT",
        f"Someone you know had an accident and needs help!",
        f"📍 Location & emergency services:",
        link,
        "⏰ Link expires in 24 hours."
    ]
    if additional_info:
        message_parts.append(f"ℹ️ {additional_info.strip()}")

    encoded = quote("\n".join(message_parts))
    return f"https://wa.me/{clean_phone.lstrip('+')}?text={encoded}"
