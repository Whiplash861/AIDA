from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import requests
from playsound import playsound  # type: ignore

from aida.config import AidaConfig
from aida.logging_utils import get_logger

log = get_logger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"

# Serialize voice generation/playback so AIDA utterances never overlap and so
# every runtime uses one canonical ElevenLabs implementation.
_voice_lock = threading.RLock()

# Reuse HTTP connections for speed.
_session = requests.Session()

# Small in-memory LRU cache for repeated lines.
_CACHE_MAX_ITEMS = 32
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_cache_lock = threading.Lock()


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

    with _voice_lock:
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
    - Connection pooling via requests.Session
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
    return " ".join(t.split())


def _get_tts_bytes_cached(
    text: str,
    api_key: str,
    voice_id: str,
    settings: VoiceSettings,
) -> Optional[bytes]:
    key = _cache_key(text, voice_id, settings)

    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    audio = _request_tts_with_retries(text, api_key, voice_id, settings)
    if not audio:
        return None

    with _cache_lock:
        _cache[key] = audio
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX_ITEMS:
            _cache.popitem(last=False)

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
    max_attempts = 4
    base_sleep = 0.6
    last_err: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        try:
            audio = _request_tts(text, api_key, voice_id, settings)
            if audio:
                return audio
            last_err = "No audio returned (non-200, 429, 5xx, or empty body)."
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_err = f"Network error: {exc}"
        except Exception as exc:
            last_err = f"Unexpected error: {exc}"

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
    resp = _session.post(url, headers=headers, json=payload, timeout=(5, 45))

    if resp.status_code == 429:
        log.warning("ElevenLabs rate-limited (429).")
        return None
    if 500 <= resp.status_code <= 599:
        log.warning("ElevenLabs server error (%d).", resp.status_code)
        return None

    if resp.status_code != 200:
        body = resp.text
        log.error(
            "ElevenLabs TTS failed.\nStatus: %d\nResponse:\n%s",
            resp.status_code,
            body,
        )
        raise RuntimeError(f"ElevenLabs returned {resp.status_code}:\n{body}")

    data = resp.content
    if not data:
        log.error("ElevenLabs returned empty audio.")
        return None

    log.info("TTS response OK. Content length: %d bytes", len(data))
    return data


def _play_mp3_bytes_blocking(audio_bytes: bytes) -> None:
    """Write generated audio to the deterministic temp cache and play it."""
    tmp_dir = os.path.join(tempfile.gettempdir(), "AIDA_TTS_CACHE")
    os.makedirs(tmp_dir, exist_ok=True)

    h = hashlib.sha256(audio_bytes).hexdigest()
    mp3_path = os.path.join(tmp_dir, f"aida_{h}.mp3")

    try:
        if not os.path.exists(mp3_path):
            with open(mp3_path, "wb") as file_obj:
                file_obj.write(audio_bytes)
        playsound(mp3_path, block=True)
    except Exception as exc:
        log.exception("Error playing TTS audio: %s", exc)


def set_quiet_logs() -> None:
    logging.getLogger("aida.audio.voice").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
