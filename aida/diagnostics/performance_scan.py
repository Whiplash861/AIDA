from __future__ import annotations

import csv
import os
import math
import subprocess

import psutil

from aida.diagnostics.base import Finding
from aida.logging_utils import get_logger


log = get_logger(__name__)


def run_performance_diagnostics() -> list[Finding]:
    """
    Collects focused CPU, memory, process, and optional GPU telemetry.

    This function performs no corrective or destructive actions.
    """

    findings: list[Finding] = []

    for name, scan in (("cpu", _scan_cpu), ("memory", _scan_memory), ("processes", _scan_top_memory_processes), ("gpu", _scan_nvidia_gpu)):
        try:
            findings.extend(scan())
        except Exception as exc:
            log.warning("%s telemetry unavailable: %s", name, type(exc).__name__)
            findings.append(Finding(id=f"perf.{name}_unavailable", title=f"{name.title()} telemetry",
                severity="info", detail="Telemetry unavailable; no health conclusion was made.", evidence=type(exc).__name__))
    return findings


def _scan_cpu() -> list[Finding]:
    cpu_percent = psutil.cpu_percent(
        interval=1.0
    )

    physical_cores = (
        psutil.cpu_count(logical=False)
        or 0
    )

    logical_cores = (
        psutil.cpu_count(logical=True)
        or 0
    )

    severity = _usage_severity(
        cpu_percent,
        warning_threshold=75.0,
        critical_threshold=90.0,
    )

    interpretation = _usage_interpretation(
        cpu_percent,
        warning_threshold=75.0,
        critical_threshold=90.0,
    )

    detail = (
        f"{cpu_percent:.1f}% utilization"
        f" | {interpretation}"
    )

    evidence = (
        f"{physical_cores} physical cores, "
        f"{logical_cores} logical cores"
    )

    recommended_next = ""

    if severity == "high":
        recommended_next = (
            "Review active processes for sustained CPU demand."
        )

    elif severity == "medium":
        recommended_next = (
            "Monitor CPU utilization and identify processes "
            "causing sustained load."
        )

    return [
        Finding(
            id="perf.cpu_usage",
            title="CPU utilization",
            severity=severity,
            detail=detail,
            evidence=evidence,
            recommended_next=recommended_next,
        )
    ]


def _scan_memory() -> list[Finding]:
    memory = psutil.virtual_memory()

    total_gb = _bytes_to_gb(
        memory.total
    )

    used_gb = _bytes_to_gb(
        memory.used
    )

    available_gb = _bytes_to_gb(
        memory.available
    )

    severity = _usage_severity(
        memory.percent,
        warning_threshold=70.0,
        critical_threshold=85.0,
    )

    interpretation = _usage_interpretation(
        memory.percent,
        warning_threshold=70.0,
        critical_threshold=85.0,
    )

    detail = (
        f"{memory.percent:.1f}% utilization"
        f" | {interpretation}"
    )

    evidence = (
        f"{used_gb:.2f} GB used, "
        f"{available_gb:.2f} GB available, "
        f"{total_gb:.2f} GB installed"
    )

    recommended_next = ""

    if severity == "high":
        recommended_next = (
            "Review high-memory processes and close "
            "unnecessary applications."
        )

    elif severity == "medium":
        recommended_next = (
            "Monitor memory pressure and review the "
            "largest active processes."
        )

    return [
        Finding(
            id="perf.memory_usage",
            title="Memory utilization",
            severity=severity,
            detail=detail,
            evidence=evidence,
            recommended_next=recommended_next,
        )
    ]


def _scan_top_memory_processes() -> list[Finding]:
    processes: list[
        tuple[str, int, int]
    ] = []

    for process in psutil.process_iter(
        ["pid", "name", "memory_info"]
    ):
        try:
            memory_info = process.info.get(
                "memory_info"
            )

            if memory_info is None:
                continue

            process_name = (
                process.info.get("name")
                or "unknown"
            )

            process_id = int(
                process.info.get("pid")
                or 0
            )

            processes.append(
                (
                    process_name,
                    process_id,
                    memory_info.rss,
                )
            )

        except (
            psutil.AccessDenied,
            psutil.NoSuchProcess,
            psutil.ZombieProcess,
        ):
            continue

    processes.sort(
        key=lambda item: item[2],
        reverse=True,
    )

    top_processes = processes[:5]

    if not top_processes:
        return [
            Finding(
                id="perf.top_memory_processes",
                title="Top memory processes",
                severity="info",
                detail=(
                    "No process memory data was available."
                ),
            )
        ]

    evidence_lines = []

    for name, process_id, memory_bytes in top_processes:
        memory_mb = (
            memory_bytes / (1024 ** 2)
        )

        evidence_lines.append(
            f"{name} "
            f"(PID {process_id}): "
            f"{memory_mb:.1f} MB"
        )

    return [
        Finding(
            id="perf.top_memory_processes",
            title="Top memory processes",
            severity="info",
            detail=(
                "Five processes currently using "
                "the most physical memory."
            ),
            evidence="\n".join(
                evidence_lines
            ),
        )
    ]


def _scan_nvidia_gpu() -> list[Finding]:
    """
    Reads NVIDIA telemetry when nvidia-smi is available.

    A missing NVIDIA utility is treated as unavailable telemetry,
    not as a diagnostic failure.
    """

    command = [
        "nvidia-smi",
        (
            "--query-gpu="
            "name,"
            "utilization.gpu,"
            "memory.used,"
            "memory.total,"
            "temperature.gpu"
        ),
        "--format=csv,noheader,nounits",
    ]

    creation_flags = 0

    if os.name == "nt":
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
        )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=creation_flags,
        )

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return [
            Finding(
                id="perf.gpu_unavailable",
                title="GPU telemetry",
                severity="info",
                detail=(
                    "NVIDIA GPU telemetry is unavailable "
                    "on this system."
                ),
            )
        ]

    if (
        result.returncode != 0
        or not result.stdout.strip()
    ):
        return [
            Finding(
                id="perf.gpu_unavailable",
                title="GPU telemetry",
                severity="info",
                detail=(
                    "NVIDIA GPU telemetry is unavailable "
                    "on this system."
                ),
            )
        ]

    findings: list[Finding] = []

    rows = csv.reader(
        result.stdout.splitlines()
    )

    for index, row in enumerate(
        rows,
        start=1,
    ):
        if len(row) != 5:
            continue

        name = row[0].strip()
        utilization = _safe_float(
            row[1]
        )
        memory_used_mb = _safe_float(
            row[2]
        )
        memory_total_mb = _safe_float(
            row[3]
        )
        temperature_c = _safe_float(
            row[4]
        )

        severity = _gpu_severity(
            utilization=utilization,
            temperature_c=temperature_c,
        )

        detail = (
            f"{utilization:.1f}% utilization"
            f" | {temperature_c:.1f}°C"
        )

        evidence = (
            f"{name}; "
            f"{_display(memory_used_mb)} MB used of "
            f"{_display(memory_total_mb)} MB"
        )

        recommended_next = ""

        if severity == "high":
            recommended_next = (
                "Review GPU-intensive applications and "
                "verify cooling performance."
            )

        elif severity == "medium":
            recommended_next = (
                "Monitor GPU utilization and temperature."
            )

        findings.append(
            Finding(
                id=f"perf.gpu_{index}",
                title=f"GPU {index}",
                severity=severity,
                detail=detail,
                evidence=evidence,
                recommended_next=recommended_next,
            )
        )

    if findings:
        return findings

    return [
        Finding(
            id="perf.gpu_unavailable",
            title="GPU telemetry",
            severity="info",
            detail=(
                "NVIDIA GPU telemetry could not be parsed."
            ),
        )
    ]


def _usage_severity(
    value: float,
    warning_threshold: float,
    critical_threshold: float,
) -> str:
    if value >= critical_threshold:
        return "high"

    if value >= warning_threshold:
        return "medium"

    return "info"


def _usage_interpretation(
    value: float,
    warning_threshold: float,
    critical_threshold: float,
) -> str:
    if value >= critical_threshold:
        return "High utilization in this snapshot; workload context is needed"

    if value >= warning_threshold:
        return "Elevated resource pressure"

    return "Below the configured utilization threshold"


def _gpu_severity(utilization: float | None, temperature_c: float | None) -> str:
    # A busy GPU is expected for many workloads. Temperature is a prompt to
    # verify device-specific limits, not proof of hardware failure.
    if temperature_c is not None and temperature_c >= 85:
        return "medium"
    return "info"


def _bytes_to_gb(
    value: int,
) -> float:
    return value / (1024 ** 3)


def _safe_float(value: str) -> float | None:
    try:
        number = float(value.strip())
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _display(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1f}"
