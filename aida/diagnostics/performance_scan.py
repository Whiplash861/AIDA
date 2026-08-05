from __future__ import annotations

import csv
import shutil
import subprocess

import psutil

from aida.diagnostics.base import Finding
from aida.logging_utils import get_logger

log = get_logger(__name__)


def run_performance_diagnostics() -> list[Finding]:
    """Collect focused CPU, memory, process, and optional GPU telemetry."""
    findings: list[Finding] = []
    checks = (_scan_cpu, _scan_memory, _scan_top_memory_processes, _scan_nvidia_gpu)
    for check in checks:
        try:
            findings.extend(check())
        except Exception as exc:
            log.exception("Performance check %s failed: %s", check.__name__, exc)
            findings.append(
                Finding(
                    id=f"perf.error.{check.__name__}",
                    title=f"Performance check failed: {check.__name__}",
                    severity="high",
                    detail="The check encountered an unexpected error.",
                    evidence=str(exc),
                    recommended_next="Review AIDA logs and rerun the performance scan.",
                )
            )
    log.info("Performance diagnostics complete.")
    return findings


def _scan_cpu() -> list[Finding]:
    utilization = psutil.cpu_percent(interval=1.0)
    physical = psutil.cpu_count(logical=False) or 0
    logical = psutil.cpu_count(logical=True) or 0
    severity = _usage_severity(utilization, 75.0, 90.0)
    return [
        Finding(
            id="perf.cpu_usage",
            title="CPU utilization",
            severity=severity,
            detail=f"{utilization:.1f}% utilization | {_usage_interpretation(utilization, 75.0, 90.0)}",
            evidence=f"{physical} physical cores, {logical} logical cores",
            recommended_next=(
                "Review active processes for sustained CPU demand."
                if severity == "high"
                else "Monitor CPU utilization for sustained load."
                if severity == "medium"
                else ""
            ),
        )
    ]


def _scan_memory() -> list[Finding]:
    memory = psutil.virtual_memory()
    severity = _usage_severity(memory.percent, 70.0, 85.0)
    return [
        Finding(
            id="perf.memory_usage",
            title="Memory utilization",
            severity=severity,
            detail=f"{memory.percent:.1f}% utilization | {_usage_interpretation(memory.percent, 70.0, 85.0)}",
            evidence=(
                f"{memory.used / (1024 ** 3):.2f} GB used, "
                f"{memory.available / (1024 ** 3):.2f} GB available, "
                f"{memory.total / (1024 ** 3):.2f} GB installed"
            ),
            recommended_next=(
                "Review high-memory processes and close unnecessary applications."
                if severity == "high"
                else "Monitor memory pressure and the largest active processes."
                if severity == "medium"
                else ""
            ),
        )
    ]


def _scan_top_memory_processes() -> list[Finding]:
    processes: list[tuple[str, int, int]] = []
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            memory_info = process.info.get("memory_info")
            if memory_info is None:
                continue
            processes.append(
                (
                    str(process.info.get("name") or "unknown"),
                    int(process.info.get("pid") or 0),
                    int(memory_info.rss),
                )
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    processes.sort(key=lambda item: item[2], reverse=True)
    top = processes[:5]
    if not top:
        return [
            Finding(
                id="perf.top_memory_processes",
                title="Top memory processes",
                detail="No process memory data was available.",
            )
        ]
    evidence = "\n".join(
        f"{name} (PID {pid}): {memory_bytes / (1024 ** 2):.1f} MB"
        for name, pid, memory_bytes in top
    )
    return [
        Finding(
            id="perf.top_memory_processes",
            title="Top memory processes",
            detail="Five processes currently using the most physical memory.",
            evidence=evidence,
        )
    ]


def _scan_nvidia_gpu() -> list[Finding]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return [
            Finding(
                id="perf.gpu_unavailable",
                title="GPU telemetry",
                detail="NVIDIA GPU telemetry is unavailable on this system.",
            )
        ]
    command = [
        executable,
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [
            Finding(
                id="perf.gpu_timeout",
                title="GPU telemetry",
                severity="medium",
                detail="NVIDIA telemetry did not respond within five seconds.",
            )
        ]
    if result.returncode != 0 or not result.stdout.strip():
        return [
            Finding(
                id="perf.gpu_unavailable",
                title="GPU telemetry",
                detail="NVIDIA GPU telemetry could not be retrieved.",
                evidence=(result.stderr or "No telemetry returned").strip(),
            )
        ]
    findings: list[Finding] = []
    for index, row in enumerate(csv.reader(result.stdout.splitlines()), start=1):
        if len(row) != 5:
            continue
        name = row[0].strip()
        utilization = _safe_float(row[1])
        memory_used = _safe_float(row[2])
        memory_total = _safe_float(row[3])
        temperature = _safe_float(row[4])
        severity = _gpu_severity(utilization, temperature)
        findings.append(
            Finding(
                id=f"perf.gpu.{index}",
                title=f"GPU {index}",
                severity=severity,
                detail=f"{utilization:.1f}% utilization | {temperature:.1f}°C",
                evidence=f"{name}; {memory_used:.0f} MB used of {memory_total:.0f} MB",
                recommended_next=(
                    "Review GPU-intensive applications and verify cooling performance."
                    if severity == "high"
                    else "Monitor GPU utilization and temperature."
                    if severity == "medium"
                    else ""
                ),
            )
        )
    return findings or [
        Finding(
            id="perf.gpu_unparsed",
            title="GPU telemetry",
            severity="medium",
            detail="NVIDIA telemetry was returned but could not be parsed.",
        )
    ]


def _usage_severity(value: float, warning: float, critical: float) -> str:
    if value >= critical:
        return "high"
    if value >= warning:
        return "medium"
    return "info"


def _usage_interpretation(value: float, warning: float, critical: float) -> str:
    if value >= critical:
        return "Critical load condition"
    if value >= warning:
        return "Elevated resource pressure"
    return "Operating within normal parameters"


def _gpu_severity(utilization: float, temperature: float) -> str:
    if utilization >= 95.0 or temperature >= 85.0:
        return "high"
    if utilization >= 80.0 or temperature >= 75.0:
        return "medium"
    return "info"


def _safe_float(value: str) -> float:
    try:
        return float(value.strip())
    except ValueError:
        return 0.0
