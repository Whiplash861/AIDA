from __future__ import annotations

import os
from pathlib import Path

from aida.aegis.artificer_bridge import AegisArtificerBridge
from aida.aegis.engine import AegisEngine
from aida.aegis.models import ProviderHealth
from aida.aegis.sensors import AegisSystemSensor
from aida.aegis.store import AegisStore
from aida.config import AidaConfig
from aida.memory.service import MemoryService
from aida.security.models import ProviderDetection
from aida.security.threat_analysis import ThreatAnalysisService
from aida.security.windows.discovery import WindowsAntivirusDiscovery


def build_aegis_engine(
    config: AidaConfig,
    *,
    memory: MemoryService,
    threat_analysis: ThreatAnalysisService,
    detection_reader=None,
) -> AegisEngine:
    data_root = _aegis_data_root(config, memory)
    data_root.mkdir(parents=True, exist_ok=True)
    raw_reader = detection_reader or _read_defender_detections

    def unresolved_reader() -> tuple[ProviderDetection, ...]:
        try:
            rows = tuple(raw_reader() or ())
        except (OSError, RuntimeError):
            return ()
        return tuple(item for item in rows if _is_unresolved(item))

    sensor = AegisSystemSensor(provider_health_reader=_read_provider_health)
    return AegisEngine(
        store=AegisStore(data_root / "aegis.db"),
        memory=memory,
        threat_analysis=threat_analysis,
        detection_reader=unresolved_reader,
        sensor=sensor,
        bridge=AegisArtificerBridge(),
        observation_interval_seconds=_env_int(
            "AIDA_AEGIS_OBSERVATION_INTERVAL_SECONDS",
            900,
            minimum=60,
        ),
        initial_observation_delay_seconds=_env_float(
            "AIDA_AEGIS_INITIAL_DELAY_SECONDS",
            5.0,
            minimum=0.0,
        ),
        enabled=_env_bool("AIDA_AEGIS_ENABLED", True),
    )


def _aegis_data_root(config: AidaConfig, memory: MemoryService) -> Path:
    configured = os.getenv("AIDA_AEGIS_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    configured_memory = getattr(config, "memory_db_path", None)
    database_path = configured_memory or getattr(memory.database, "path", "")
    if not database_path:
        raise ValueError("Aegis requires a durable local data path")
    memory_path = Path(database_path).expanduser()
    aida_root = memory_path.parent.parent
    return aida_root / "aegis"


def _read_defender_detections() -> tuple[ProviderDetection, ...]:
    try:
        discovery = WindowsAntivirusDiscovery().discover()
        getter = getattr(discovery.provider, "get_detection_snapshot", None)
        if not callable(getter):
            return ()
        return tuple(getter() or ())
    except (OSError, RuntimeError):
        return ()


def _is_unresolved(detection: ProviderDetection) -> bool:
    active = _optional_bool(detection.metadata.get("is_active"))
    action_success = _optional_bool(detection.metadata.get("action_success"))
    return active is True or (active is None and action_success is not True)


def _read_provider_health() -> ProviderHealth:
    try:
        discovery = WindowsAntivirusDiscovery().discover()
        status = discovery.provider.get_status()
    except (OSError, RuntimeError):
        return ProviderHealth(
            available=False,
            active=None,
            healthy=None,
            real_time_protection=None,
            signatures_current=None,
            provider_name="unavailable",
        )
    return ProviderHealth(
        available=True,
        active=status.active,
        healthy=status.healthy,
        real_time_protection=status.real_time_protection,
        signatures_current=status.signatures_current,
        provider_name=discovery.provider.display_name,
    )


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, value)
