from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import requests

from aida.config import AidaConfig
from aida.logging_utils import get_logger

log = get_logger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"

# ElevenLabs may interpret the all-caps project name as an acronym and produce
# a hard "I" sound. Keep the visible product name as AIDA, but send a stable
# speech-only pronunciation spelling to the voice provider.
_AIDA_SPOKEN_NAME = "Ada"

# Serialize voice generation/playback so AIDA utterances never overlap and so
# every runtime uses one canonical ElevenLabs implementation.
_voice_lock = threading.RLock()

# Small in-memory LRU cache for repeated lines.
_CACHE_MAX_ITEMS = 32
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_cache_lock = threading.Lock()
_cache_times: dict[str, float] = {}
_CACHE_MAX_BYTES = 32 * 1024 * 1024
_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class VoiceSettings:
    model_id: str = "eleven_multilingual_v2"
    stability: float = 0.25
    similarity_boost: float = 0.85


_DEFAULT_SETTINGS = VoiceSettings()


def synthesize_text(
    text: str,
    config: AidaConfig,
    settings: VoiceSettings = _DEFAULT_SETTINGS,
) -> Optional[bytes]:
    """Generate AIDA's canonical ElevenLabs audio without playing it locally.

    This is the shared synthesis boundary used by desktop playback and remote
    AIDA runtimes. Provider keys and the configured AIDA voice ID remain on the
    trusted host running this function.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return None

    if not getattr(config, "voice_enabled", False):
        log.info("Voice disabled. Skipping TTS synthesis.")
        return None

    api_key = getattr(config, "elevenlabs_api_key", None)
    voice_id = getattr(config, "elevenlabs_voice_id", None)
    if not api_key or not voice_id:
        log.warning("ElevenLabs API key or voice ID missing. Skipping TTS synthesis.")
        return None

    # Playback is serialized by speak_text; independent gateway devices must
    # not block behind another device's network request.
    return _get_tts_bytes_cached(normalized, api_key, voice_id, settings)


def speak_text(
    text: str,
    config: AidaConfig,
    settings: VoiceSettings = _DEFAULT_SETTINGS,
) -> None:
    """Speak a single line using AIDA's canonical ElevenLabs voice.

    Guarantees:
    - Blocking playback (prevents overlapping lines)
    - Thread-safe serialization
    - Retries on transient failures (429/5xx/network)
    - Small LRU cache to avoid repeated provider calls
    """
    normalized = _normalize_text(text)
    if not normalized:
        return

    # Keep generation and local playback inside one serialized operation. The
    # RLock lets synthesize_text reuse the same canonical boundary safely.
    with _voice_lock:
        audio_bytes = synthesize_text(normalized, config, settings)
        if not audio_bytes:
            return
        _play_mp3_bytes_blocking(audio_bytes)


def _normalize_text(text: str) -> str:
    t = (text or "").strip()
    t = " ".join(t.split())
    # Speech-only pronunciation override. Displayed/transcript text remains
    # "AIDA"; only provider-bound text is respelled so the name is spoken as
    # "AY-duh" / "Ayee-duh" rather than with a sharp "I" sound.
    return re.sub(r"\bAIDA\b", _AIDA_SPOKEN_NAME, t, flags=re.IGNORECASE)


def _get_tts_bytes_cached(
    text: str,
    api_key: str,
    voice_id: str,
    settings: VoiceSettings,
) -> Optional[bytes]:
    key = _cache_key(text, voice_id, settings)

    with _cache_lock:
        for expired in [item for item, seen in _cache_times.items() if time.monotonic() - seen > _CACHE_TTL_SECONDS]:
            _cache.pop(expired, None)
            _cache_times.pop(expired, None)
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    audio = _request_tts_with_retries(text, api_key, voice_id, settings)
    if not audio:
        return None

    with _cache_lock:
        _cache[key] = audio
        _cache_times[key] = time.monotonic()
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX_ITEMS or sum(len(value) for value in _cache.values()) > _CACHE_MAX_BYTES:
            removed, _ = _cache.popitem(last=False)
            _cache_times.pop(removed, None)

    return audio


def _cache_key(text: str, voice_id: str, settings: VoiceSettings) -> str:
    payload = (
        f"{voice_id}|{settings.model_id}|{settings.stability:.3f}|"
        f"{settings.similarity_boost:.3f}|{text}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _request_tts_with_retries(
    text: str,
    api_key: str,
    voice_id: str,
    settings: VoiceSettings,
) -> Optional[bytes]:
    max_attempts = 2
    base_sleep = 0.6
    last_err: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        try:
            audio = _request_tts(text, api_key, voice_id, settings)
            if audio:
                return audio
            last_err = "No audio returned (non-200, 429, 5xx, or empty body)."
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_err = "Provider network error."
        except Exception as exc:
            last_err = "Provider request failed."

        if attempt < max_attempts:
            sleep_s = base_sleep * (1.7 ** (attempt - 1))
            log.warning(
                "TTS attempt %d/%d failed. Retrying in %.2fs. (%s)",
                attempt,
                max_attempts,
                sleep_s,
                last_err,
            )
            time.sleep(sleep_s)

    log.error("TTS failed after %d attempts. (%s)", max_attempts, last_err)
    return None


def _request_tts(
    text: str,
    api_key: str,
    voice_id: str,
    settings: VoiceSettings,
) -> Optional[bytes]:
    url = f"{ELEVENLABS_TTS_URL}/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": settings.model_id,
        "voice_settings": {
            "stability": settings.stability,
            "similarity_boost": settings.similarity_boost,
        },
    }

    log.info("Sending TTS request to ElevenLabs. Text length: %d", len(text))
    deadline = time.monotonic() + 15
    with requests.post(url, headers=headers, json=payload, timeout=(3, 12), stream=True) as resp:
        if resp.status_code == 429 or 500 <= resp.status_code <= 599:
            log.warning("ElevenLabs temporarily unavailable (HTTP %d).", resp.status_code)
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs returned HTTP {resp.status_code}.")
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=16384):
            if time.monotonic() > deadline:
                raise requests.Timeout("Voice download exceeded its time budget.")
            total += len(chunk)
            if total > 12 * 1024 * 1024:
                raise RuntimeError("AIDA voice audio exceeds the supported size.")
            chunks.append(chunk)
        data = b"".join(chunks)
    if not data:
        log.warning("ElevenLabs returned empty audio.")
        return None
    return data


def _play_mp3_bytes_blocking(audio_bytes: bytes) -> None:
    """Play a uniquely owned temporary file and discard it after playback."""
    # Desktop playback is the only operation that needs playsound. Keeping the
    # import here allows the shared synthesis module to run in a headless
    # Services Gateway container without installing desktop audio dependencies.
    from playsound import playsound  # type: ignore

    descriptor, mp3_path = tempfile.mkstemp(prefix="aida_tts_", suffix=".mp3")
    try:
        with os.fdopen(descriptor, "wb") as audio_file:
            audio_file.write(audio_bytes)
        playsound(mp3_path, block=True)
    except Exception:
        log.warning("AIDA audio playback failed.")
    finally:
        try:
            os.unlink(mp3_path)
        except OSError:
            log.warning("Temporary AIDA speech audio could not be removed.")


def set_quiet_logs() -> None:
    logging.getLogger("aida.audio.voice").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
