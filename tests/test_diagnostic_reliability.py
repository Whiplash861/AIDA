from types import SimpleNamespace

from aida.diagnostics import performance_scan, system_scan
from aida.platform.windows import WindowsAdapter
from aida.platform.models import SecurityProviderStatus


def test_legacy_scan_requires_authority_before_creating_state(tmp_path):
    path = tmp_path / "memory.db"
    findings = system_scan.run_file_scan(SimpleNamespace(memory_db_path=path))
    assert findings[0].id == "sec.authorization_required"
    assert not path.exists()


def test_legacy_scan_preserves_canonical_unknown_and_continuity(tmp_path):
    calls = []
    class Executor:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def execute(self):
            return SimpleNamespace(transcript_text="Provider scan remains running; findings are unavailable.")
    findings = system_scan.run_file_scan(SimpleNamespace(memory_db_path=tmp_path / "memory.db"),
                                        user_authorized=True, executor_factory=Executor)
    assert "remain" in findings[0].detail
    assert "no active threats" not in findings[0].detail.lower()
    assert calls[0]["max_monitor_seconds"] == 300
    assert calls[0]["task_ledger"] is not None


def test_unknown_defender_status_is_not_disabled(monkeypatch):
    monkeypatch.setattr(WindowsAdapter, "security_provider_status",
                        lambda self: SecurityProviderStatus("Defender", False, None, "Unavailable"))
    finding = system_scan._defender_status_finding()
    assert "Unknown" in finding.detail
    assert finding.severity != "high"


def test_gpu_utilization_is_not_a_fault_and_missing_values_stay_unknown():
    assert performance_scan._gpu_severity(100, 55) == "info"
    assert performance_scan._safe_float("N/A") is None
    assert performance_scan._safe_float("nan") is None


def test_one_sensor_failure_does_not_cancel_other_diagnostics(monkeypatch):
    monkeypatch.setattr(performance_scan, "_scan_cpu", lambda: (_ for _ in ()).throw(OSError("unavailable")))
    monkeypatch.setattr(performance_scan, "_scan_memory", lambda: [SimpleNamespace(id="memory")])
    monkeypatch.setattr(performance_scan, "_scan_top_memory_processes", lambda: [])
    monkeypatch.setattr(performance_scan, "_scan_nvidia_gpu", lambda: [])
    findings = performance_scan.run_performance_diagnostics()
    assert {item.id for item in findings} == {"perf.cpu_unavailable", "memory"}
