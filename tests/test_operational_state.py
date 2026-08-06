from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from aida.operational_state import OperationalStateStore


def test_operational_state_store_publishes_status_and_activity(tmp_path) -> None:
    store = OperationalStateStore(tmp_path / "state.json")
    store.mark_online("STANDBY")
    store.set_status("tasks", "2 ACTIVE")
    store.add_activity("TASKS background review started")

    snapshot = store.read_snapshot()
    activity = store.read_activity()

    assert snapshot["desktop_online"] is True
    tasks = next(item for item in snapshot["statuses"] if item["id"] == "tasks")
    assert tasks["value"] == "2 ACTIVE"
    assert tasks["tone"] == "active"
    assert activity[0]["category"] == "TASKS"


def test_operational_state_store_marks_stale_heartbeat_offline(tmp_path) -> None:
    path = tmp_path / "state.json"
    store = OperationalStateStore(path)
    store.mark_online("STANDBY")

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["heartbeat_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")

    snapshot = store.read_snapshot()
    agent = next(item for item in snapshot["statuses"] if item["id"] == "agent")

    assert snapshot["desktop_online"] is False
    assert agent["value"] == "OFFLINE"
    assert agent["tone"] == "offline"
