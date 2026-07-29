from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

APP_NAME = "AIDA"
APP_FULL_NAME = "Analytical Intelligence & Diagnostic Agent"
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
    microsoft_graph_client_id: str | None = None
    bug_report_outbox_dir: str = ""
    microsoft_token_cache_path: str = ""


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
    auth_dir = user_data_root / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)

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
        microsoft_graph_client_id=(
            os.getenv("AIDA_MICROSOFT_GRAPH_CLIENT_ID") or None
        ),
        bug_report_outbox_dir=str(support_dir / "bug_reports"),
        microsoft_token_cache_path=str(
            auth_dir / "microsoft_graph_token_cache.bin"
        ),
    )


def _user_data_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AIDA"
    return Path.home() / ".aida"
