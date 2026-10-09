import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aida.technomancer.analyzer import analyze, _advisory
from aida.technomancer.models import HardwareInventory, TelemetrySample
from aida.technomancer.storage import TechnomancerStore
from aida.technomancer.permissions import PermissionStore, TECHNOMANCER_BACKGROUND_SCOPE
from aida.technomancer import launcher


def sample(timestamp, **updates):
    data = dict(timestamp=timestamp, machine_id="machine", cpu_percent=20, memory_percent=95,
                swap_percent=40, disk_percent=40, disk_free_gb=100, process_count=50,
                context_level="process", workload_context="editor")
    return TelemetrySample(**(data | updates))


def test_sparse_age_is_not_coverage_and_hardware_starts_new_epoch(tmp_path):
    store = TechnomancerStore(tmp_path / "t.db")
    inventory = HardwareInventory(machine_id="machine", total_ram_gb=16)
    store.record_inventory(inventory)
    now = time.time()
    store.record_sample(sample(now - 40 * 86400))
    store.record_sample(sample(now))
    assert store.observation_days("machine", now) == 0
    assert not any(item.kind == "upgrade" for item in analyze(store, inventory, now))
    changed = HardwareInventory(machine_id="machine", total_ram_gb=32)
    store.record_inventory(changed)
    assert store.samples_since("machine", 0) == []
    assert store.observation_days("machine", now) == 0


def test_late_daily_compaction_merges_counts_and_averages(tmp_path):
    store = TechnomancerStore(tmp_path / "t.db")
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=40)).replace(hour=1).timestamp()
    store.record_sample(sample(old, cpu_percent=20))
    store.compact("machine", now=now)
    store.record_sample(sample(old + 3600, cpu_percent=80))
    store.compact("machine", now=now)
    store.compact("machine", now=now)
    with store._connection() as conn:
        row = conn.execute("SELECT sample_count,data_json FROM daily_summaries").fetchone()
    assert row["sample_count"] == 2
    assert json.loads(row["data_json"])["avg_cpu_percent"] == 50


def test_advisory_lifecycle_severity_and_feedback_are_evidence_bound(tmp_path):
    store = TechnomancerStore(tmp_path / "t.db")
    high = _advisory("health.high", "storage", "Warning", "Evidence", "health", "high", "urgent", "observed", .8, 3)
    first_seen = high.first_seen
    store.upsert_advisory(high)
    store.mark_surfaced(high.advisory_id, "2026-01-01T00:00:00+00:00")
    newer = _advisory("health.high", "storage", "Warning", "Evidence", "health", "high", "urgent", "observed", .9, 4)
    store.upsert_advisory(newer)
    medium = _advisory("health.medium", "memory", "Pressure", "Evidence", "health", "medium", "persistent", "observed", .95, 4)
    store.upsert_advisory(medium)
    assert store.active_advisories()[0].advisory_id == high.advisory_id
    assert newer.first_seen == first_seen
    assert newer.last_surfaced_at is not None
    with pytest.raises(KeyError):
        store.record_outcome("invented", "success")
    with pytest.raises(ValueError):
        store.record_outcome(high.advisory_id, "anything")
    store.record_outcome(high.advisory_id, "helped")
    assert store.outcome_score("health") is None
    store.resolve_absent_advisories([medium.advisory_id])
    assert [item.advisory_id for item in store.active_advisories()] == [medium.advisory_id]


def test_pid_reuse_and_corrupt_permissions_never_authorize_effects(tmp_path, monkeypatch):
    marker = tmp_path / "runtime.json"
    marker.write_text(json.dumps({"pid": 42, "create_time": 10, "executable": "python.exe"}))
    calls = []
    process = SimpleNamespace(pid=42, create_time=lambda: 11,
        cmdline=lambda: ["python", "-m", "aida.technomancer.runtime", "--data-dir", str(tmp_path)],
        terminate=lambda: calls.append("terminated"))
    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: process)
    assert launcher.stop_background(tmp_path, data_dir=tmp_path)[0] is False
    assert calls == []
    permissions = PermissionStore(tmp_path / "permissions.json")
    permissions.path.write_text('[]')
    assert permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE) is False


def test_summary_retention_removes_old_coverage_without_dropping_recent_days(tmp_path):
    store = TechnomancerStore(tmp_path / "t.db")
    now = datetime.now(timezone.utc)
    store.record_sample(sample((now - timedelta(days=800)).timestamp()))
    store.record_sample(sample((now - timedelta(days=40)).timestamp()))
    store.compact("machine", now=now)
    with store._connection() as conn:
        rows = conn.execute("SELECT day FROM daily_summaries").fetchall()
    assert len(rows) == 1
    assert rows[0]["day"] == (now - timedelta(days=40)).date().isoformat()



@pytest.mark.parametrize("payload,expected", [
    ({"enabled": "false", "level": 1}, False),
    ({"enabled": "true", "level": 1}, False),
    ({"enabled": True, "kill_switch_engaged": "false", "level": 1}, False),
    ({"enabled": True, "kill_switch_engaged": True, "level": 1}, False),
    ({"enabled": True, "level": 0}, False),
    ({"enabled": True, "level": 1}, True),
    ({"enabled": True, "level": 3}, True),
    ({"enabled": True, "level": 99}, False),
    ({"enabled": True, "level": True}, False),
    ({"enabled": True, "level": None}, False),
    ({"enabled": True, "allow_autonomous_deep_scan": "false"}, False),
    ({"enabled": True}, True),
    ({}, False),
])
def test_runtime_uses_strict_persisted_autonomy_flags(payload, expected):
    from aida.technomancer.runtime import _canonical_autonomy_enabled
    memory = SimpleNamespace(get_preference=lambda *args: payload)
    assert _canonical_autonomy_enabled(memory) is expected
