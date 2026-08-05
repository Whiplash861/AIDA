from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from aida import APP_FULL_NAME, APP_NAME, __version__

load_dotenv()


@dataclass(frozen=True, slots=True)
class AidaConfig:
    app_name: str
    app_full_name: str
    version: str
    base_dir: str
    assets_dir: str
    sounds_dir: str
    log_dir: str
    memory_db_path: str
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    voice_enabled: bool
    artificer_enabled: bool
    artificer_mode: str
    artificer_source_root: str
    artificer_data_dir: str
    artificer_ledger_path: str
    artificer_consent_path: str
    artificer_developer_registry_path: str
    artificer_export_dir: str
    artificer_dispatch_endpoint: str | None
    artificer_local_export_enabled: bool
    artificer_review_interval_seconds: int
    artificer_telemetry_level: str
    artificer_auto_maintenance_enabled: bool
    installation_id_path: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def get_config() -> AidaConfig:
    base_dir = Path(__file__).resolve().parent.parent
    assets_dir = base_dir / "assets"
    sounds_dir = assets_dir / "sounds"
    log_dir = base_dir / "logs"
    memory_dir = base_dir / "memory"
    artificer_data_dir = memory_dir / "artificer"

    for directory in (log_dir, memory_dir, artificer_data_dir):
        directory.mkdir(parents=True, exist_ok=True)

    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
    elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID")

    return AidaConfig(
        app_name=APP_NAME,
        app_full_name=APP_FULL_NAME,
        version=__version__,
        base_dir=str(base_dir),
        assets_dir=str(assets_dir),
        sounds_dir=str(sounds_dir),
        log_dir=str(log_dir),
        memory_db_path=str(memory_dir / "aida_cases.db"),
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=elevenlabs_voice_id,
        voice_enabled=bool(elevenlabs_api_key and elevenlabs_voice_id),
        artificer_enabled=_env_bool("AIDA_ARTIFICER_ENABLED", True),
        artificer_mode=os.getenv("AIDA_ARTIFICER_MODE", "early_alpha"),
        artificer_source_root=str(base_dir),
        artificer_data_dir=str(artificer_data_dir),
        artificer_ledger_path=str(artificer_data_dir / "artificer.db"),
        artificer_consent_path=str(artificer_data_dir / "consent.json"),
        artificer_developer_registry_path=str(artificer_data_dir / "developers.json"),
        artificer_export_dir=str(artificer_data_dir / "exports"),
        artificer_dispatch_endpoint=os.getenv("AIDA_ARTIFICER_DISPATCH_ENDPOINT"),
        artificer_local_export_enabled=_env_bool("AIDA_ARTIFICER_LOCAL_EXPORT", True),
        artificer_review_interval_seconds=_env_int(
            "AIDA_ARTIFICER_REVIEW_INTERVAL_SECONDS", 21600, minimum=60
        ),
        artificer_telemetry_level=os.getenv(
            "AIDA_ARTIFICER_TELEMETRY_LEVEL", "local_only"
        ),
        artificer_auto_maintenance_enabled=_env_bool(
            "AIDA_ARTIFICER_AUTO_MAINTENANCE", False
        ),
        installation_id_path=str(artificer_data_dir / "installation_id"),
    )
