from __future__ import annotations

import argparse
import os
import time

from aida.config import get_config
from aida.technomancer.engine import TechnomancerEngine
from aida.technomancer.launcher import _pid_path
from aida.technomancer.permissions import TECHNOMANCER_BACKGROUND_SCOPE


def main() -> int:
    parser = argparse.ArgumentParser(description="AIDA Technomancer background runtime")
    parser.add_argument("--once", action="store_true", help="Run one explicitly invoked observation cycle")
    parser.add_argument("--interval", type=int, default=300, help="Background sampling interval in seconds")
    args = parser.parse_args()

    config = get_config()
    engine = TechnomancerEngine.from_config(config)
    pid_path = _pid_path(config.base_dir)

    if args.once:
        engine.monitor_cycle()
        return 0

    if not engine.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE):
        return 2

    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        while engine.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE):
            try:
                engine.monitor_cycle()
            except Exception:
                pass
            remaining = max(60, args.interval)
            while remaining > 0 and engine.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE):
                step = min(15, remaining)
                time.sleep(step)
                remaining -= step
    finally:
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
