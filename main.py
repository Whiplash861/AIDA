# main.py (DROP-IN) — silent quickscan; user must request scan explicitly
from __future__ import annotations

from dotenv import load_dotenv

from aida.config import get_config
from aida.logging_utils import get_logger
from aida.brain.llm_client import AIDABrain
from aida.diagnostics.system_scan import run_full_diagnostics  # kept available
from aida.ui.cli import start_cli_loop
from aida.audio.voice import set_quiet_logs  # we'll add this helper in voice.py (see section C)

log = get_logger(__name__)


def main() -> int:
    load_dotenv(override=True)
    config = get_config()

    # Optional: silence chatty TTS logs (only affects INFO spam)
    try:
        set_quiet_logs()
    except Exception:
        pass

    log.info("AIDA starting up. Version: %s", getattr(config, "version", "1.0.0"))

    # No quickscan here. CLI will run it only on user request ("scan"/"quickscan").
    brain = AIDABrain()
    start_cli_loop(config, initial_findings=[], brain=brain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
