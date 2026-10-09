from __future__ import annotations
import os

from aida.config import AidaConfig
from aida.logging_utils import get_logger

log = get_logger(__name__)


def _play_tone(filename: str, config: AidaConfig, blocking: bool = False) -> None:
    path = os.path.join(config.sounds_dir, filename)
    if not os.path.exists(path):
        log.warning("Tone file not found: %s", path)
        return

    try:
        if os.name == "nt":
            import winsound
            flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
            if not blocking:
                flags |= winsound.SND_ASYNC
            winsound.PlaySound(path, flags)
            return
        try:
            import simpleaudio  # type: ignore
        except ImportError:
            log.warning("Local tone playback is unavailable; optional simpleaudio is not installed.")
            return
        wave_obj = simpleaudio.WaveObject.from_wave_file(path)
        play_obj = wave_obj.play()
        if blocking:
            play_obj.wait_done()
    except Exception:
        log.warning("Local tone playback is temporarily unavailable.")


def play_start_tone(config: AidaConfig, blocking: bool = False) -> None:
    _play_tone("aida_start.wav", config, blocking=blocking)


def play_end_tone(config: AidaConfig, blocking: bool = False) -> None:
    _play_tone("aida_end.wav", config, blocking=blocking)
