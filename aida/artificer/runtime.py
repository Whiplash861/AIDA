from __future__ import annotations

import threading

from aida.artificer.engine import ArtificerEngine

_LOCK = threading.RLock()
_ACTIVE_ENGINE: ArtificerEngine | None = None


def set_active_artificer(engine: ArtificerEngine | None) -> None:
    global _ACTIVE_ENGINE
    with _LOCK:
        _ACTIVE_ENGINE = engine


def get_active_artificer() -> ArtificerEngine | None:
    with _LOCK:
        return _ACTIVE_ENGINE
