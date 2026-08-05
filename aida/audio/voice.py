from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import requests
from playsound import playsound  # type: ignore

from aida.artificer.events import make_event
from aida.artificer.runtime import get_active_artificer
from aida.config import AidaConfig
from aida.logging_utils import get_logger

log = get_logger(__name__)
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
_speak_lock = threading.Lock()
_session = requests.Session()
_CACHE_MAX_ITEMS = 32
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_cache_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    model_id: str = "eleven_multilingual_v2"
    stability: float = 0.25
    similarity_boost: float = 0.85


_DEFAULT_SETTINGS = VoiceSettings()


def speak_text(
    text: str,
    config: AidaConfig,
    settings: VoiceSettings = _DEFAULT_SETTINGS,
) -> None:
    normalized = _normalize_text(text)
    if not normalized:
        return
    operation_id = str(uuid.uuid4())
    started = time.monotonic()
    _publish(
        config,
        "speech_request",
        "started",
        operation_id=operation_id,
        metadata={"characters": len(normalized), "model_id": settings.model_id},
    )
    if not config.voice_enabled:
        log.info("Voice disabled. Skipping TTS.")
        _publish(
            config,
            "speech_request",
            "disabled",
            operation_id=operation_id,
            duration_ms=(time.monotonic() - started) * 1000.0,
        )
        return
    api_key = config.elevenlabs_api_key
    voice_id = config.elevenlabs_voice_id
    if not api_key or not voice_id:
        log.warning("ElevenLabs API key or voice ID missing. Skipping TTS.")
        _publish(
            config,
            "speech_request",
            "failed",
            operation_id=operation_id,
            duration_ms=(time.monotonic() - started) * 1000.0,
            error_category="ConfigurationError",
            metadata={"error": "Voice credentials are incomplete"},
        )
        return

    with _speak_lock:
        try:
            audio, cache_hit, attempts = _get_tts_bytes_cached(
                normalized, api_key, voice_id, settings
            )
            if not audio:
                raise RuntimeError("No audio returned by the configured speech provider")
            _play_mp3_bytes_blocking(audio)
            _publish(
                config,
                "speech_request",
                "completed",
                operation_id=operation_id,
                duration_ms=(time.monotonic() - started) * 1000.0,
                metadata={
                    "cache_hit": cache_hit,
                    "provider_attempts": attempts,
                    "audio_bytes": len(audio),
                    "model_id": settings.model_id,
                },
            )
        except Exception as exc:
            log.exception("Speech operation failed: %s", exc)
            _publish(
                config,
                "speech_request",
                "failed",
                operation_id=operation_id,
                duration_ms=(time.monotonic() - started) * 1000.0,
                error_category=type(exc).__name__,
                metadata={"error": str(exc), "model_id": settings.model_id},
            )


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _get_tts_bytes_cached(
    text: str,
    api_key: str,
    voice_id: str,
    settings: VoiceSettings,
) -> tuple[Optional[bytes], bool, int]:
    key = _cache_key(text, voice_id, settings)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key], True, 0
    audio, attempts = _request_tts_with_retries(text, api_key, voice_id, settings)
    if not audio:
        return None, False, attempts
    with _cache_lock:
        _cache[key] = audio
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX_ITEMS:
            _cache.popitem(last=False)
    return audio, False, attempts


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
) -> tuple[Optional[bytes], int]:
    max_attempts = 4
    base_sleep = 0.6
    last_error: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        try:
            audio = _request_tts(text, api_key, voice_id, settings)
            if audio:
                return audio, attempt
            last_error = "No audio returned by the provider"
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = f"Network error: {exc}"
        except Exception as exc:
            last_error = f"Unexpected error: {exc}"
        if attempt < max_attempts:
            delay = base_sleep * (1.7 ** (attempt - 1))
            log.warning(
                "TTS attempt %d/%d failed. Retrying in %.2fs. (%s)",
                attempt,
                max_attempts,
                delay,
                last_error,
            )
            time.sleep(delay)
    log.error("TTS failed after %d attempts. (%s)", max_attempts, last_error)
    return None, max_attempts


def _request_tts(
    text: str,
    api_key: str,
    voice_id: str,
    settings: VoiceSettings,
) -> Optional[bytes]:
    response = _session.post(
        f"{ELEVENLABS_TTS_URL}/{voice_id}",
        headers={
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": settings.model_id,
            "voice_settings": {
                "stability": settings.stability,
                "similarity_boost": settings.similarity_boost,
            },
        },
        timeout=(5, 45),
    )
    if response.status_code == 429 or 500 <= response.status_code <= 599:
        return None
    if response.status_code != 200:
        raise RuntimeError(f"ElevenLabs returned HTTP {response.status_code}")
    return response.content or None


def _play_mp3_bytes_blocking(audio_bytes: bytes) -> None:
    directory = os.path.join(tempfile.gettempdir(), "AIDA_TTS_CACHE")
    os.makedirs(directory, exist_ok=True)
    digest = hashlib.sha256(audio_bytes).hexdigest()
    path = os.path.join(directory, f"aida_{digest}.mp3")
    if not os.path.exists(path):
        with open(path, "wb") as file:
            file.write(audio_bytes)
    playsound(path, block=True)


def _publish(
    config: AidaConfig,
    event_type: str,
    status: str,
    *,
    operation_id: str,
    duration_ms: float | None = None,
    error_category: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    engine = get_active_artificer()
    if engine is None:
        return
    engine.event_bus.publish(
        make_event(
            source="speech.elevenlabs",
            event_type=event_type,
            status=status,
            aida_version=config.version,
            platform_profile_id=(
                engine.platform_profile.profile_id if engine.platform_profile else "unknown"
            ),
            operation_id=operation_id,
            duration_ms=duration_ms,
            error_category=error_category,
            metadata=metadata or {},
        )
    )


def set_quiet_logs() -> None:
    logging.getLogger("aida.audio.voice").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
