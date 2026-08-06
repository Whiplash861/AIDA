from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

APP_NAME = "AIDA"
APP_FULL_NAME = "Analytical Intelligent Diagnostic Agent"
VERSION = "1.0.0"
DEFAULT_BUG_REPORT_RECIPIENT = "AIDAdeveloper@outlook.com"


@dataclass
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
    bug_report_recipient: str = DEFAULT_BUG_REPORT_RECIPIENT
    bug_report_outbox_dir: str = ""
    artificer_enabled: bool = True
    artificer_mode: str = "early_alpha"
    artificer_data_dir: str = ""
    artificer_ledger_path: str = ""
    artificer_consent_path: str = ""
    artificer_developer_registry_path: str = ""
    artificer_export_dir: str = ""
    artificer_dispatch_endpoint: str = ""
    artificer_local_export_enabled: bool = True
    artificer_review_interval_seconds: int = 21_600
    artificer_telemetry_level: str = "local_only"
    artificer_source_root: str = ""
    artificer_auto_maintenance_enabled: bool = False


def get_config() -> AidaConfig:
    """Build and return AIDA's configuration."""

    base_dir = os.path.abspath(
        os.path.dirname(os.path.dirname(__file__))
    )
    assets_dir = os.path.join(base_dir, "assets")
    sounds_dir = os.path.join(assets_dir, "sounds")
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    user_data_root = _user_data_root()
    memory_dir = user_data_root / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    support_dir = user_data_root / "support"
    support_dir.mkdir(parents=True, exist_ok=True)
    artificer_dir = user_data_root / "artificer"
    artificer_dir.mkdir(parents=True, exist_ok=True)

    elevenlabs_api_key = os.getenv(
        "ELEVENLABS_API_KEY"
    )
    elevenlabs_voice_id = os.getenv(
        "ELEVENLABS_VOICE_ID"
    )
    voice_enabled = bool(
        elevenlabs_api_key
        and elevenlabs_voice_id
    )

    return AidaConfig(
        app_name=APP_NAME,
        app_full_name=APP_FULL_NAME,
        version=VERSION,
        base_dir=base_dir,
        assets_dir=assets_dir,
        sounds_dir=sounds_dir,
        log_dir=log_dir,
        memory_db_path=str(
            memory_dir / "aida_memory.db"
        ),
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=elevenlabs_voice_id,
        voice_enabled=voice_enabled,
        bug_report_recipient=(
            os.getenv("AIDA_BUG_REPORT_RECIPIENT")
            or DEFAULT_BUG_REPORT_RECIPIENT
        ).strip(),
        bug_report_outbox_dir=str(support_dir / "bug_reports"),
        artificer_enabled=_env_bool("AIDA_ARTIFICER_ENABLED", True),
        artificer_mode=(
            os.getenv("AIDA_ARTIFICER_MODE")
            or "early_alpha"
        ).strip(),
        artificer_data_dir=str(artificer_dir),
        artificer_ledger_path=str(artificer_dir / "artificer.db"),
        artificer_consent_path=str(artificer_dir / "consent.json"),
        artificer_developer_registry_path=str(
            artificer_dir / "developers.json"
        ),
        artificer_export_dir=str(artificer_dir / "exports"),
        artificer_dispatch_endpoint=(
            os.getenv("AIDA_ARTIFICER_DISPATCH_ENDPOINT")
            or ""
        ).strip(),
        artificer_local_export_enabled=_env_bool(
            "AIDA_ARTIFICER_LOCAL_EXPORT_ENABLED",
            True,
        ),
        artificer_review_interval_seconds=_env_int(
            "AIDA_ARTIFICER_REVIEW_INTERVAL_SECONDS",
            21_600,
            minimum=300,
        ),
        artificer_telemetry_level=(
            os.getenv("AIDA_ARTIFICER_TELEMETRY_LEVEL")
            or "local_only"
        ).strip().lower(),
        artificer_source_root=base_dir,
        artificer_auto_maintenance_enabled=_env_bool(
            "AIDA_ARTIFICER_AUTO_MAINTENANCE_ENABLED",
            False,
        ),
    )


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


def _user_data_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AIDA"
    return Path.home() / ".aida"
