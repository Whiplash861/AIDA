from __future__ import annotations

import argparse
import os
import time
import logging
import json

from aida.config import get_config
from aida.autonomy.models import AutonomyLevel
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.technomancer.engine import TechnomancerEngine
from aida.technomancer.launcher import _pid_path, write_runtime_marker
from aida.artificer.state_file import locked_state
from aida.technomancer.permissions import TECHNOMANCER_BACKGROUND_SCOPE


def _canonical_autonomy_enabled(memory: MemoryService) -> bool:
    payload = memory.get_preference("autonomy.settings", {})
    if not isinstance(payload, dict):
        return False
    if any(key in payload and not isinstance(payload[key], bool) for key in (
        "enabled", "kill_switch_engaged", "allow_autonomous_surface_scan", "allow_autonomous_deep_scan",
    )):
        return False
    if payload.get("enabled", False) is not True or payload.get("kill_switch_engaged", False) is not False:
        return False
    if "level" in payload:
        try:
            if isinstance(payload["level"], bool) or AutonomyLevel(int(payload["level"])) < AutonomyLevel.OBSERVE:
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AIDA Technomancer background runtime"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one explicitly invoked observation cycle",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Background sampling interval in seconds",
    )
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    config = get_config()
    engine = TechnomancerEngine(base_dir=config.base_dir, data_dir=args.data_dir) if args.data_dir else TechnomancerEngine.from_config(config)
    memory = MemoryService(MemoryDatabase(config.memory_db_path))
    pid_path = _pid_path(config.base_dir, data_dir=engine.data_dir)

    if args.once:
        engine.monitor_cycle()
        return 0

    engine.permissions.set_autonomy(_canonical_autonomy_enabled(memory))
    if not engine.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE):
        return 2

    with locked_state(engine.data_dir / "monitoring-session"):
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        write_runtime_marker(pid_path, os.getpid())
        try:
            while True:
                engine.permissions.set_autonomy(
                    _canonical_autonomy_enabled(memory)
                )
                if not engine.permissions.permitted(
                    TECHNOMANCER_BACKGROUND_SCOPE
                ):
                    break

                try:
                    engine.monitor_cycle()
                except Exception as exc:
                    # Background observation must not take AIDA down. Fail closed
                    # for this cycle and try again only while authorization remains.
                    engine.store.record_runtime_health(success=False, error_category=type(exc).__name__)
                    logging.getLogger(__name__).exception("Technomancer observation failed")

                remaining = max(60, args.interval)
                while remaining > 0:
                    time.sleep(min(15, remaining))
                    remaining -= min(15, remaining)
                    engine.permissions.set_autonomy(
                        _canonical_autonomy_enabled(memory)
                    )
                    if not engine.permissions.permitted(
                        TECHNOMANCER_BACKGROUND_SCOPE
                    ):
                        remaining = 0
                        break
        finally:
            try:
                marker = json.loads(pid_path.read_text(encoding="utf-8"))
                if marker.get("pid") == os.getpid():
                    pid_path.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
