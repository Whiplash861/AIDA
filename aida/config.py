from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env file (for ElevenLabs keys, etc.)
load_dotenv()

# App metadata (kept here so we don't depend on __init__ imports)
APP_NAME = "AIDA"
APP_FULL_NAME = "Analytical Intelligence & Diagnostic Agent"
VERSION = "1.0.0"


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

    # ElevenLabs / voice settings
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    voice_enabled: bool


def get_config() -> AidaConfig:
    """
    Build and return the global AIDA configuration object.
    """
    # Assume project layout: <root>/aida, <root>/assets, etc.
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    assets_dir = os.path.join(base_dir, "assets")
    sounds_dir = os.path.join(assets_dir, "sounds")
    log_dir = os.path.join(base_dir, "logs")
    memory_dir = os.path.join(base_dir, "memory")

    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(memory_dir, exist_ok=True)

    # Load ElevenLabs settings from environment (.env)
    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
    elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    voice_enabled = bool(elevenlabs_api_key and elevenlabs_voice_id)

    return AidaConfig(
        app_name=APP_NAME,
        app_full_name=APP_FULL_NAME,
        version=VERSION,
        base_dir=base_dir,
        assets_dir=assets_dir,
        sounds_dir=sounds_dir,
        log_dir=log_dir,
        memory_db_path=os.path.join(memory_dir, "aida_cases.db"),
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=elevenlabs_voice_id,
        voice_enabled=voice_enabled,
    )
