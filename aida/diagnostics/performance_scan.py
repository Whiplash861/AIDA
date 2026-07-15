from __future__ import annotations

import csv
import os
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

    try:
        findings.extend(_scan_cpu())
        findings.extend(_scan_memory())
        findings.extend(_scan_top_memory_processes())
        findings.extend(_scan_nvidia_gpu())

        log.info("Performance diagnostics complete.")

    except Exception as exc:
        log.exception(
            "Performance diagnostics failed: %s",
            exc,
        )

        findings.append(
            Finding(
                id="perf.error",
                title="Performance diagnostics error",
                severity="high",
                detail=(
                    "Performance diagnostics encountered "
                    "an unexpected error."
                ),
                evidence=str(exc),
                recommended_next=(
                    "Review the application logs and rerun "
                    "the performance scan."
                ),
            )
        )

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
            f"{memory_used_mb:.0f} MB used of "
            f"{memory_total_mb:.0f} MB"
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
        return "Critical load condition"

    if value >= warning_threshold:
        return "Elevated resource pressure"

    return "Operating within normal parameters"


def _gpu_severity(
    utilization: float,
    temperature_c: float,
) -> str:
    if (
        utilization >= 95.0
        or temperature_c >= 85.0
    ):
        return "high"

    if (
        utilization >= 80.0
        or temperature_c >= 75.0
    ):
        return "medium"

    return "info"


def _bytes_to_gb(
    value: int,
) -> float:
    return value / (1024 ** 3)


def _safe_float(
    value: str,
) -> float:
    try:
        return float(
            value.strip()
        )

    except ValueError:
        return 0.0