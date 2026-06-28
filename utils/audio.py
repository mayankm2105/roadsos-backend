import os
import uuid
import tempfile
import aiofiles
from pathlib import Path
from fastapi import UploadFile, HTTPException
from utils.logger import get_logger

logger = get_logger(__name__)

# Allowed audio MIME types and extensions
ALLOWED_MIME_TYPES = {
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mpeg",       # MP3
    "audio/mp3",
    "audio/ogg",
    "audio/webm",       # Browser MediaRecorder default
    "audio/mp4",        # iOS Safari
    "video/webm",       # Some browsers send this for audio
    "application/octet-stream"  # Generic fallback
}

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".ogg", ".webm", ".m4a", ".mp4"}

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


def validate_audio_file(file: UploadFile) -> None:
    """
    Validate uploaded audio file. Raises HTTPException on failure.
    Checks:
    1. File is not empty (filename exists)
    2. Content-type is in ALLOWED_MIME_TYPES
       (be lenient — browsers send different MIME types)
    3. File extension is in ALLOWED_EXTENSIONS
       (extract from file.filename)
    
    NOTE: Do NOT check file size here — UploadFile doesn't expose
    size without reading. Size is checked after reading to temp file.
    """
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No audio file provided",
            headers={"X-Error-Code": "MISSING_PARAMS"}
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{ext}'. "
                   f"Supported: WAV, MP3, OGG, WebM, M4A",
            headers={"X-Error-Code": "MISSING_PARAMS"}
        )

    # Content-type check is lenient (warn only, don't reject)
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        logger.warning(
            f"Unusual audio content-type received: {content_type}. "
            f"Proceeding anyway."
        )


async def save_temp_audio(file: UploadFile) -> str:
    """
    Save uploaded audio to a temporary file. Returns the temp file path.
    Uses a system temp directory with a unique UUID filename.
    Preserves the original file extension for Whisper format detection.
    
    IMPORTANT: The caller is responsible for deleting the temp file
    after transcription using cleanup_temp_file().
    
    Raises HTTPException if file exceeds MAX_FILE_SIZE_BYTES.
    """
    ext = Path(file.filename).suffix.lower() or ".wav"
    temp_filename = f"roadsos_audio_{uuid.uuid4().hex}{ext}"
    temp_path = os.path.join(tempfile.gettempdir(), temp_filename)

    try:
        async with aiofiles.open(temp_path, "wb") as temp_file:
            total_bytes = 0
            chunk_size = 1024 * 64  # 64KB chunks

            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)

                if total_bytes > MAX_FILE_SIZE_BYTES:
                    # Clean up partial file
                    await temp_file.close()
                    cleanup_temp_file(temp_path)
                    raise HTTPException(
                        status_code=413,
                        detail="Audio file too large. Maximum size is 25 MB.",
                        headers={"X-Error-Code": "MISSING_PARAMS"}
                    )

                await temp_file.write(chunk)

        logger.debug(
            f"Saved temp audio: {temp_path} ({total_bytes / 1024:.1f} KB)"
        )
        return temp_path

    except HTTPException:
        raise
    except Exception as e:
        cleanup_temp_file(temp_path)
        logger.error(f"Failed to save temp audio file: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process audio file",
            headers={"X-Error-Code": "INTERNAL_ERROR"}
        )


def cleanup_temp_file(file_path: str) -> None:
    """
    Delete a temporary file. Silently ignores errors (file may not exist).
    Always call this in a finally block after transcription.
    """
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f"Cleaned up temp file: {file_path}")
    except Exception as e:
        logger.warning(f"Could not delete temp file {file_path}: {e}")
