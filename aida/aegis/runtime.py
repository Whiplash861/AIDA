from __future__ import annotations

import atexit
import threading

from aida.aegis.bootstrap import build_aegis_engine
from aida.aegis.engine import AegisEngine
from aida.config import AidaConfig
from aida.memory.service import MemoryService
from aida.security.threat_analysis import ThreatAnalysisService


_LOCK = threading.RLock()
_ACTIVE: AegisEngine | None = None
_ACTIVE_KEY: str | None = None
_ATEXIT_REGISTERED = False


def ensure_aegis_engine(
    config: AidaConfig,
    *,
    memory: MemoryService,
    threat_analysis: ThreatAnalysisService,
    detection_reader=None,
) -> AegisEngine:
    global _ACTIVE, _ACTIVE_KEY, _ATEXIT_REGISTERED
    configured_memory = getattr(config, "memory_db_path", None)
    database_path = getattr(memory.database, "path", "")
    key = str(configured_memory or database_path)
    if not key:
        raise ValueError("Aegis requires a durable local database scope")
    with _LOCK:
        if _ACTIVE is not None and _ACTIVE_KEY == key:
            if not _ACTIVE.running:
                _ACTIVE.start()
            return _ACTIVE
        if _ACTIVE is not None:
            _ACTIVE.stop()
        _ACTIVE = build_aegis_engine(
            config,
            memory=memory,
            threat_analysis=threat_analysis,
            detection_reader=detection_reader,
        )
        _ACTIVE_KEY = key
        _ACTIVE.start()
        if not _ATEXIT_REGISTERED:
            atexit.register(stop_active_aegis)
            _ATEXIT_REGISTERED = True
        return _ACTIVE


def get_active_aegis() -> AegisEngine | None:
    with _LOCK:
        return _ACTIVE


def stop_active_aegis() -> None:
    global _ACTIVE, _ACTIVE_KEY
    with _LOCK:
        engine = _ACTIVE
        _ACTIVE = None
        _ACTIVE_KEY = None
    if engine is not None:
        engine.stop()
