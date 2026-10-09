"""Bounded resource evidence for the AIDA process family, not a host diagnosis."""
from __future__ import annotations

import math
import os
import time
import threading
import uuid
from datetime import datetime, timezone

import psutil


def _number(value):
    return float(value) if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None


def _host_counters():
    counters = psutil.cpu_times()
    fields = counters._asdict()
    total = sum(value for key, value in fields.items() if key not in {"guest", "guest_nice"})
    idle = fields.get("idle", 0) + fields.get("iowait", 0)
    return {"cpu_total": total, "cpu_busy": total - idle,
            "memory_percent": psutil.virtual_memory().percent, "logical_cpu_count": psutil.cpu_count()}


class SelfResourceObserver:
    """Measure only this process and its descendants across one bounded window."""

    def __init__(self, *, process_factory=None, host_counters=None, clock=None, sleeper=None, max_processes=64):
        self.process_factory = process_factory or psutil.Process
        self.host_counters = host_counters or _host_counters
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.max_processes = max(1, min(64, int(max_processes)))
        self._lock = threading.Lock()

    def _capture(self, pid):
        try:
            queue = [self.process_factory(pid)]
        except (psutil.Error, OSError):
            queue = []
        result = {}
        unavailable = 0 if queue else 1
        truncated = False
        seen = set()
        while queue and len(seen) < self.max_processes:
            process = queue.pop(0)
            if process.pid in seen:
                continue
            seen.add(process.pid)
            try:
                created = process.create_time()
                cpu = process.cpu_times()
                cpu_seconds = _number(cpu.user + cpu.system)
                try:
                    rss = _number(process.memory_info().rss)
                except (psutil.Error, OSError, AttributeError):
                    rss = None
                try:
                    io = process.io_counters()
                    read_bytes, write_bytes = _number(io.read_bytes), _number(io.write_bytes)
                except (psutil.Error, OSError, AttributeError):
                    read_bytes = write_bytes = None
                result[(process.pid, created)] = {"cpu": cpu_seconds, "rss": rss, "read": read_bytes, "write": write_bytes}
                children = process.children(recursive=False)
                available = max(0, self.max_processes - len(seen) - len(queue))
                truncated = truncated or len(children) > available
                queue.extend(children[:available])
            except (psutil.Error, OSError):
                unavailable += 1
        try:
            host = self.host_counters()
        except (psutil.Error, OSError):
            host = {}
        return result, host, unavailable, truncated or bool(queue)

    def measure(self, *, window_seconds=1.0, operation_id=None) -> dict:
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, (int, float)) or not math.isfinite(window_seconds) or not .2 <= window_seconds <= 5:
            raise ValueError("Resource measurement window must be between 0.2 and 5 seconds")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("An AIDA resource measurement is already running")
        try:
            pid = os.getpid()
            before, host_before, missing_before, truncated_before = self._capture(pid)
            started = self.clock()
            self.sleeper(window_seconds)
            after, host_after, missing_after, truncated_after = self._capture(pid)
            elapsed = self.clock() - started
            if not math.isfinite(elapsed) or elapsed <= 0:
                raise ValueError("Resource measurement clock did not advance")
            common = before.keys() & after.keys()
            def delta(field):
                values = [after[key][field] - before[key][field] for key in common
                          if before[key][field] is not None and after[key][field] is not None
                          and after[key][field] >= before[key][field]]
                return (sum(values), len(values)) if values else (None, 0)
            cpu_seconds, cpu_covered = delta("cpu")
            read_delta, read_covered = delta("read")
            write_delta, write_covered = delta("write")
            cores = _number(host_after.get("logical_cpu_count"))
            core_cpu = cpu_seconds / elapsed * 100 if cpu_seconds is not None else None
            machine_cpu = core_cpu / cores if core_cpu is not None and cores else None
            host_cpu = None
            if all(_number(host.get(key)) is not None for host in (host_before, host_after) for key in ("cpu_total", "cpu_busy")):
                total = host_after["cpu_total"] - host_before["cpu_total"]
                busy = host_after["cpu_busy"] - host_before["cpu_busy"]
                if total > 0 and 0 <= busy <= total:
                    host_cpu = busy / total * 100
            rss = [item["rss"] for item in after.values() if item["rss"] is not None]
            partial = (not common or not cores or _number(host_after.get("memory_percent")) is None
                       or missing_before or missing_after or truncated_before or truncated_after
                       or set(before) != set(after) or cpu_covered != len(common)
                       or len(rss) != len(after) or read_covered != len(common) or write_covered != len(common)
                       or host_cpu is None)
            return {
                "measurement_id": "AE-RESOURCE-" + uuid.uuid4().hex[:16].upper(),
                "observed_at_utc": datetime.now(timezone.utc).isoformat(), "operation_id": operation_id,
                "observer_engine": "technomancer", "subject": "aida_process_family",
                "elapsed_seconds": elapsed, "processes_observed": len(after), "processes_compared": len(common),
                "processes_unavailable": missing_before + missing_after,
                "process_set_changed": set(before) != set(after), "truncated": truncated_before or truncated_after,
                "aida_cpu_core_percent": core_cpu, "aida_cpu_machine_percent": machine_cpu,
                "aida_rss_sum_bytes": sum(rss) if rss else None,
                "aida_io_read_bytes_delta": read_delta, "aida_io_write_bytes_delta": write_delta,
                "host_cpu_percent_same_window": host_cpu, "host_memory_percent": _number(host_after.get("memory_percent")),
                "cpu_process_coverage": cpu_covered, "io_process_coverage": min(read_covered, write_covered),
                "status": "partial" if partial else "observed", "causal_claim_verified": False,
                "limitations": [
                    "One window describes concurrent activity; it does not establish the cause of a slowdown.",
                    "CPU deltas cover only matching PID and creation-time identities present at both endpoints.",
                    "Summed RSS may count shared pages more than once; it is not unique physical memory ownership.",
                    "I/O counters are operating-system reported process I/O, not proof of physical disk traffic.",
                    "Sampling overhead is included; short-lived subprocesses may not be represented.",
                ],
            }
        finally:
            self._lock.release()


def render_self_resources(record: dict) -> str:
    def number(key, unit="%", divisor=1):
        value = record.get(key)
        return "unavailable" if value is None else f"{value / divisor:.2f}{unit}"
    return "\n".join((
        "AIDA RESOURCE OBSERVATION", f"Measurement: {record['measurement_id']}",
        f"Observed: {record['observed_at_utc']} | Window: {record['elapsed_seconds']:.2f} seconds | Status: {record['status']}",
        f"AIDA CPU, one-core basis: {number('aida_cpu_core_percent')} (can exceed 100% across cores)",
        f"AIDA CPU, machine-capacity basis: {number('aida_cpu_machine_percent')}",
        f"Host CPU during the same window: {number('host_cpu_percent_same_window')}",
        f"AIDA summed resident memory: {number('aida_rss_sum_bytes', ' MiB', 1024 ** 2)}",
        f"Host memory utilization: {number('host_memory_percent')}",
        f"AIDA observed read/write I/O: {number('aida_io_read_bytes_delta', ' KiB', 1024)} / {number('aida_io_write_bytes_delta', ' KiB', 1024)}",
        f"Processes compared: {record['processes_compared']} | Unavailable reads: {record['processes_unavailable']}",
        "", "INTERPRETATION LIMITS", *["- " + line for line in record["limitations"]],
    ))
