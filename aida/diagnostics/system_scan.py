from __future__ import annotations

import platform
import time

import psutil

from aida.artificer.runtime import get_active_artificer
from aida.diagnostics.base import Finding
from aida.diagnostics.performance_scan import run_performance_diagnostics
from aida.logging_utils import get_logger
from aida.platform.registry import get_platform_adapter

log = get_logger(__name__)


def run_quickscan(config) -> list[Finding]:
    del config
    started = time.monotonic()
    status = "completed"
    error: str | None = None
    findings: list[Finding] = []
    try:
        adapter = get_platform_adapter()
        memory = psutil.virtual_memory()
        findings.extend(
            [
                Finding(
                    id="sys.os",
                    title="Operating system",
                    detail=(
                        f"{platform.system()} {platform.release()} "
                        f"({platform.version()})"
                    ),
                    evidence=f"Architecture: {platform.machine() or 'unknown'}",
                ),
                Finding(
                    id="sys.cpu",
                    title="CPU logical cores",
                    detail=str(psutil.cpu_count(logical=True) or 0),
                ),
                Finding(
                    id="sys.ram",
                    title="Memory",
                    severity=(
                        "high" if memory.percent >= 85
                        else "medium" if memory.percent >= 70
                        else "info"
                    ),
                    detail=f"{memory.percent:.1f}% utilization",
                    evidence=(
                        f"{memory.total / (1024 ** 3):.2f} GB installed; "
                        f"{memory.available / (1024 ** 3):.2f} GB available"
                    ),
                    recommended_next=(
                        "Review high-memory processes."
                        if memory.percent >= 70
                        else ""
                    ),
                ),
            ]
        )
        provider = adapter.security_provider_status()
        findings.append(
            Finding(
                id="sec.provider",
                title=f"Security provider: {provider.provider}",
                severity=(
                    "high" if provider.available and provider.enabled is False
                    else "medium" if not provider.available
                    else "info"
                ),
                detail=provider.detail,
                evidence=f"Adapter: {adapter.name}",
                recommended_next=(
                    "Verify the installed security provider and platform adapter."
                    if not provider.available
                    else "Enable real-time protection through the security provider."
                    if provider.enabled is False
                    else ""
                ),
            )
        )
        log.info("Quickscan complete on %s.", adapter.name)
    except Exception as exc:
        status = "failed"
        error = str(exc)
        log.exception("Quickscan failed: %s", exc)
        findings.append(
            Finding(
                id="sys.quickscan_error",
                title="Quickscan error",
                severity="high",
                detail="Quickscan encountered an unexpected error.",
                evidence=str(exc),
                recommended_next="Review AIDA logs and rerun the quickscan.",
            )
        )
    engine = get_active_artificer()
    if engine is not None:
        engine.record_diagnostic_run(
            scan_type="quickscan",
            status=status,
            findings_count=len(findings),
            duration_ms=(time.monotonic() - started) * 1000.0,
            error=error,
        )
    return findings


def run_full_diagnostics(config) -> list[Finding]:
    started = time.monotonic()
    status = "completed"
    error: str | None = None
    findings = run_quickscan(config)
    try:
        findings.extend(run_performance_diagnostics())
        findings.extend(_scan_suspicious_process_locations())
        log.info("Full diagnostics complete.")
    except Exception as exc:
        status = "failed"
        error = str(exc)
        log.exception("Full diagnostics failed: %s", exc)
        findings.append(
            Finding(
                id="sys.full_scan_error",
                title="Full diagnostics error",
                severity="high",
                detail="Full diagnostics encountered an unexpected error.",
                evidence=str(exc),
                recommended_next="Review AIDA logs and rerun full diagnostics.",
            )
        )
    engine = get_active_artificer()
    if engine is not None:
        engine.record_diagnostic_run(
            scan_type="full_diagnostics",
            status=status,
            findings_count=len(findings),
            duration_ms=(time.monotonic() - started) * 1000.0,
            error=error,
        )
    return findings


def run_file_scan(config) -> list[Finding]:
    del config
    started = time.monotonic()
    adapter = get_platform_adapter()
    result = adapter.request_security_scan("quick")
    severity = {
        "completed": "high" if result.threats else "info",
        "unsupported": "medium",
        "unknown": "medium",
        "failed": "high",
    }.get(result.state, "medium")
    findings = [
        Finding(
            id="sec.scan_state",
            title=f"{result.provider} scan",
            severity=severity,
            detail=f"State: {result.state}. {result.detail}",
            evidence=(
                "\n".join(result.threats)
                if result.threats
                else f"Platform adapter: {adapter.name}"
            ),
            recommended_next=(
                "Review detections in the active security provider."
                if result.threats
                else "Verify provider compatibility or run the scan manually."
                if result.state != "completed"
                else ""
            ),
        )
    ]
    for index, threat in enumerate(result.threats, start=1):
        findings.append(
            Finding(
                id=f"sec.threat.{index}",
                title="Threat detection returned",
                severity="high",
                detail=threat,
                recommended_next="Review and remediate through the active security provider.",
            )
        )
    engine = get_active_artificer()
    if engine is not None:
        engine.record_diagnostic_run(
            scan_type="security_scan",
            status=result.state,
            findings_count=len(findings),
            duration_ms=(time.monotonic() - started) * 1000.0,
            provider=result.provider,
            error=result.detail if result.state == "failed" else None,
        )
    return findings


def _scan_suspicious_process_locations(limit: int = 5) -> list[Finding]:
    findings: list[Finding] = []
    suspicious_markers = (
        "/tmp/",
        "\\temp\\",
        "\\appdata\\local\\temp\\",
    )
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            executable = str(process.info.get("exe") or "")
            normalized = executable.lower()
            if not executable or not any(marker in normalized for marker in suspicious_markers):
                continue
            findings.append(
                Finding(
                    id=f"proc.suspicious_location.{process.info.get('pid', 0)}",
                    title="Process running from a temporary location",
                    severity="medium",
                    detail=str(process.info.get("name") or "unknown"),
                    evidence=executable,
                    recommended_next="Verify the process publisher, signature, and expected installation path.",
                )
            )
            if len(findings) >= limit:
                break
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return findings
