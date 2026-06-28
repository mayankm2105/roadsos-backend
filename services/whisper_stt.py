import asyncio
import time
from typing import Optional
from utils.logger import get_logger
from config import settings

logger = get_logger(__name__)

# Whisper model singleton — loaded once, reused for every request
_whisper_model = None
_model_loading = False

# Map our lang codes to Whisper language codes
WHISPER_LANG_MAP = {
    "en": "en",
    "hi": "hi",    # Hindi
    "pa": "pa",    # Punjabi
    "hw": "hi",    # Haryanvi — closest to Hindi for Whisper
}

# Max audio duration in seconds Whisper should handle
MAX_AUDIO_DURATION_SECONDS = 300  # 5 minutes


def load_whisper_model():
    """
    Load Whisper model synchronously. Called once at startup.
    Uses settings.WHISPER_MODEL (default: "base").

    Available models (tradeoff speed vs accuracy):
      tiny   (~75MB)  — fastest, less accurate
      base   (~145MB) — RECOMMENDED for this project
      small  (~244MB) — more accurate but slower
      medium (~769MB) — too slow for real-time use

    On first run this downloads the model weights to ~/.cache/whisper/
    Subsequent runs use the cached weights instantly.
    """
    global _whisper_model, _model_loading

    if _whisper_model is not None:
        return _whisper_model

    if _model_loading:
        logger.warning("Whisper model is already loading, waiting...")
        return None

    try:
        _model_loading = True
        import whisper
        import ssl
        
        # macOS python SSL workaround
        try:
            _create_unverified_https_context = ssl._create_unverified_context
        except AttributeError:
            pass
        else:
            ssl._create_default_https_context = _create_unverified_https_context

        model_name = settings.WHISPER_MODEL  # "base"
        logger.info(
            f"Loading Whisper '{model_name}' model... "
            f"(first run may take 1-2 minutes to download)"
        )
        start = time.time()
        _whisper_model = whisper.load_model(model_name)
        elapsed = time.time() - start
        logger.info(
            f"Whisper '{model_name}' model loaded in {elapsed:.1f}s ✓"
        )
        return _whisper_model

    except ImportError:
        logger.error(
            "openai-whisper not installed. "
            "Run: pip install openai-whisper"
        )
        return None
    except Exception as e:
        logger.error(f"Failed to load Whisper model: {e}")
        return None
    finally:
        _model_loading = False


def get_whisper_model():
    """Return the loaded model singleton. Loads if not yet loaded."""
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = load_whisper_model()
    return _whisper_model


def transcribe_audio_sync(
    audio_path: str,
    lang: str = "en"
) -> dict:
    """
    Synchronous Whisper transcription. Must be called via asyncio.to_thread()
    from async contexts — Whisper inference is CPU-bound and blocks.

    Args:
        audio_path: Absolute path to the audio file
        lang: Language hint code ("en", "hi", "pa", "hw")

    Returns dict with:
        {
          "text": "transcribed text here",
          "language": "hi",       # detected language (from Whisper)
          "duration_seconds": 12  # audio duration
        }

    Raises:
        RuntimeError: If Whisper model not loaded
        TimeoutError: If audio is too long (> MAX_AUDIO_DURATION_SECONDS)
        Exception: If transcription fails
    """
    model = get_whisper_model()
    if model is None:
        raise RuntimeError(
            "Whisper model is not available. "
            "Check server logs for loading errors."
        )

    # Map lang code to Whisper format
    whisper_lang = WHISPER_LANG_MAP.get(lang, None)
    # None means auto-detect — let Whisper figure it out

    try:
        import whisper

        # Load audio and check duration BEFORE transcribing
        logger.debug(f"Loading audio file: {audio_path}")
        audio = whisper.load_audio(audio_path)
        duration_seconds = len(audio) / 16000  # Whisper uses 16kHz

        logger.debug(f"Audio duration: {duration_seconds:.1f}s")

        if duration_seconds > MAX_AUDIO_DURATION_SECONDS:
            raise TimeoutError(
                f"Audio too long ({duration_seconds:.0f}s). "
                f"Maximum is {MAX_AUDIO_DURATION_SECONDS}s (5 minutes)."
            )

        # Run transcription
        logger.info(
            f"Transcribing {duration_seconds:.1f}s audio "
            f"(lang hint: {whisper_lang or 'auto'})"
        )
        start = time.time()

        transcribe_options = {
            "fp16": False,  # fp16 only works on GPU; CPU must use fp32
        }
        if whisper_lang:
            transcribe_options["language"] = whisper_lang

        result = model.transcribe(audio, **transcribe_options)

        elapsed = time.time() - start
        text = result["text"].strip()
        detected_lang = result.get("language", lang)

        logger.info(
            f"Transcription complete in {elapsed:.1f}s: "
            f"'{text[:80]}...' (lang: {detected_lang})"
        )

        return {
            "text": text,
            "language": detected_lang,
            "duration_seconds": round(duration_seconds, 1)
        }

    except (TimeoutError, RuntimeError):
        raise
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        raise Exception(f"Transcription failed: {str(e)}")


async def transcribe_audio(
    audio_path: str,
    lang: str = "en"
) -> dict:
    """
    Async wrapper around transcribe_audio_sync().
    Runs Whisper in a thread pool so the FastAPI event loop stays free.

    This is the function called by the endpoint — always use this,
    never call transcribe_audio_sync() directly from async code.
    """
    return await asyncio.to_thread(
        transcribe_audio_sync,
        audio_path,
        lang
    )
