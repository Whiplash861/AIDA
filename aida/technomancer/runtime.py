from __future__ import annotations

import argparse
import os
import time

from aida.config import get_config
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.technomancer.engine import TechnomancerEngine
from aida.technomancer.launcher import _pid_path
from aida.technomancer.permissions import TECHNOMANCER_BACKGROUND_SCOPE


def _canonical_autonomy_enabled(memory: MemoryService) -> bool:
    payload = memory.get_preference("autonomy.settings", {})
    if not isinstance(payload, dict):
        return False
    return bool(
        payload.get("enabled", False)
        and not payload.get("kill_switch_engaged", False)
    )


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
    args = parser.parse_args()

    config = get_config()
    engine = TechnomancerEngine.from_config(config)
    memory = MemoryService(MemoryDatabase(config.memory_db_path))
    pid_path = _pid_path(config.base_dir)

    if args.once:
        engine.monitor_cycle()
        return 0

    engine.permissions.set_autonomy(_canonical_autonomy_enabled(memory))
    if not engine.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE):
        return 2

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
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
            except Exception:
                # Background observation must not take AIDA down. Fail closed
                # for this cycle and try again only while authorization remains.
                pass

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
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
