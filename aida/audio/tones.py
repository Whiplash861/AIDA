from __future__ import annotations
import os
import simpleaudio  # type: ignore

from aida.config import AidaConfig
from aida.logging_utils import get_logger

log = get_logger(__name__)


def _play_tone(filename: str, config: AidaConfig, blocking: bool = False) -> None:
    path = os.path.join(config.sounds_dir, filename)
    if not os.path.exists(path):
        log.warning("Tone file not found: %s", path)
        return

    try:
        wave_obj = simpleaudio.WaveObject.from_wave_file(path)
        play_obj = wave_obj.play()
        if blocking:
            play_obj.wait_done()
    except Exception as exc:
        log.exception("Error playing tone %s: %s", filename, exc)


def play_start_tone(config: AidaConfig, blocking: bool = False) -> None:
    _play_tone("aida_start.wav", config, blocking=blocking)


def play_end_tone(config: AidaConfig, blocking: bool = False) -> None:
    _play_tone("aida_end.wav", config, blocking=blocking)
