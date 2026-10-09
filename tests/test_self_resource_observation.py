from types import SimpleNamespace

import psutil
import pytest

from aida.technomancer.self_resources import SelfResourceObserver, render_self_resources


class Process:
    def __init__(self, pid, *, created=1, cpu=1, rss=100, io=(10, 20), children=()):
        self.pid, self.created, self.cpu, self.rss, self.io, self.descendants = pid, created, cpu, rss, io, children

    def create_time(self):
        return self.created

    def cpu_times(self):
        return SimpleNamespace(user=self.cpu, system=0)

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)

    def io_counters(self):
        if self.io is None:
            raise psutil.AccessDenied(self.pid)
        return SimpleNamespace(read_bytes=self.io[0], write_bytes=self.io[1])

    def children(self, recursive=False):
        assert recursive is False
        return self.descendants


def observer(before, after, **kwargs):
    state = {"phase": 0}
    def advance(_seconds):
        state["phase"] = 1
    return SelfResourceObserver(
        process_factory=lambda _pid: (before, after)[state["phase"]],
        host_counters=lambda: {"cpu_total": 100 + state["phase"] * 4,
                               "cpu_busy": 40 + state["phase"] * 2,
                               "memory_percent": 60, "logical_cpu_count": 4},
        clock=lambda: float(state["phase"]), sleeper=advance, **kwargs)


def test_same_window_cpu_memory_io_are_measured_with_explicit_limits():
    before = Process(1, children=(Process(2),))
    after = Process(1, cpu=1.25, io=(110, 220), children=(Process(2, cpu=1.75, io=(30, 50)),))
    record = observer(before, after).measure(operation_id="case-1")
    assert record["aida_cpu_core_percent"] == 100
    assert record["aida_cpu_machine_percent"] == 25
    assert record["host_cpu_percent_same_window"] == 50
    assert record["aida_rss_sum_bytes"] == 200
    assert record["aida_io_read_bytes_delta"] == 120
    assert record["aida_io_write_bytes_delta"] == 230
    assert record["status"] == "observed"
    assert record["operation_id"] == "case-1"
    assert record["causal_claim_verified"] is False
    assert "does not establish" in render_self_resources(record)
    assert "pid" not in record  # Only aggregate data leaves the observer.


def test_reused_pid_is_excluded_from_cpu_and_io_deltas():
    before = Process(1, children=(Process(2, cpu=100),))
    after = Process(1, cpu=1.2, children=(Process(2, created=99, cpu=500),))
    record = observer(before, after).measure()
    assert record["aida_cpu_core_percent"] == pytest.approx(20)
    assert record["processes_compared"] == 1
    assert record["process_set_changed"] is True
    assert record["status"] == "partial"


def test_missing_io_is_unknown_and_process_count_is_bounded():
    process = Process(1, io=None, children=tuple(Process(pid) for pid in range(2, 20)))
    record = observer(process, process, max_processes=1).measure()
    assert record["processes_observed"] == 1
    assert record["truncated"] is True
    assert record["aida_io_read_bytes_delta"] is None
    assert record["io_process_coverage"] == 0
    assert record["status"] == "partial"


def test_process_unavailable_is_partial_not_zero_activity():
    sampler = observer(Process(1), Process(1))
    def denied(_pid):
        raise psutil.AccessDenied(1)
    sampler.process_factory = denied
    record = sampler.measure()
    assert record["processes_unavailable"] == 2
    assert record["aida_cpu_core_percent"] is None
    assert record["aida_rss_sum_bytes"] is None
    assert record["status"] == "partial"


@pytest.mark.parametrize("window", [True, "1", float("nan"), float("inf"), .1, 6])
def test_invalid_measurement_window_is_rejected_before_sampling(window):
    with pytest.raises(ValueError):
        observer(Process(1), Process(1)).measure(window_seconds=window)


def test_same_observer_rejects_overlapping_sample():
    sampler = observer(Process(1), Process(1))
    sampler._lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            sampler.measure()
    finally:
        sampler._lock.release()
    assert sampler.measure()["status"] == "observed"
