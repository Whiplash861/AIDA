from __future__ import annotations

from dotenv import load_dotenv

from aida.artificer.engine import ArtificerEngine
from aida.artificer.event_bus import EventBus
from aida.artificer.runtime import set_active_artificer
from aida.brain.llm_client import AIDABrain
from aida.config import get_config
from aida.logging_utils import get_logger, setup_logging
from aida.ui.cli import start_cli_loop
from aida.audio.voice import set_quiet_logs

log = get_logger(__name__)


def main() -> int:
    load_dotenv(override=True)
    config = get_config()
    setup_logging(config)
    try:
        set_quiet_logs()
    except Exception:
        pass

    event_bus = EventBus()
    artificer = ArtificerEngine(config=config, event_bus=event_bus)
    set_active_artificer(artificer)
    artificer.start(run_startup_review=True)
    brain = AIDABrain(event_bus=event_bus, config=config)

    log.info("AIDA starting up. Version: %s", config.version)
    try:
        start_cli_loop(config, initial_findings=[], brain=brain)
    finally:
        artificer.stop()
        set_active_artificer(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
