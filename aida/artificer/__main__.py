from __future__ import annotations

import argparse
import json
from pathlib import Path

from aida.artificer.bootstrap import build_artificer_engine


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated AIDA Artificer backend without frontend wiring."
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Profile the platform without running a source and telemetry review.",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export the resulting local Artificer report.",
    )
    args = parser.parse_args()

    engine = build_artificer_engine()
    engine.start(run_startup_review=False)
    try:
        snapshot = engine.snapshot() if args.no_review else engine.run_review()
        payload = {
            "status": snapshot.status,
            "last_review_utc": snapshot.last_review_utc,
            "platform": snapshot.platform_summary,
            "compatibility": dict(snapshot.compatibility_summary),
            "open_findings": len(snapshot.open_findings),
            "pending_proposals": len(snapshot.pending_proposals),
            "dispatch_queue_depth": snapshot.dispatch_queue_depth,
            "telemetry_level": snapshot.telemetry_level,
            "ledger_integrity": engine.ledger.verify_integrity(),
        }
        if args.export:
            exported: Path = engine.export_report()
            payload["exported_report"] = str(exported)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    finally:
        engine.stop()


if __name__ == "__main__":
    raise SystemExit(main())
