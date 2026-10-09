from __future__ import annotations
import os
import platform
from pathlib import Path
import psutil
from aida.logging_utils import get_logger
from aida.diagnostics.base import Finding as Finding

log = get_logger(__name__)

def run_full_diagnostics(config) -> list[Finding]:
    findings: list[Finding] = []

    try:
        # ----------------------------
        # SYSTEM INFO (existing)
        # ----------------------------
        os_name = platform.system()
        os_version = platform.version()
        cpu_count = psutil.cpu_count(logical=True) or 0
        total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)

        # ----------------------------
        # MEMORY USAGE ANALYSIS
        # ----------------------------
        vm = psutil.virtual_memory()

        used_ram_gb = round(vm.used / (1024**3), 2)
        available_ram_gb = round(vm.available / (1024**3), 2)
        memory_percent = vm.percent

        # Base memory reading
        detail = f"{memory_percent}% ({used_ram_gb} GB used, {available_ram_gb} GB available)"

        # Add interpretation
        if memory_percent >= 85:
            detail += " | High utilization in this snapshot; workload context is needed"
        elif memory_percent >= 70:
            detail += " | Moderate memory pressure"
        else:
            detail += " | Below the configured utilization threshold"

        findings.append(Finding(
            id="perf.ram_usage",
            title="Memory usage",
            severity="info",
            detail=detail,
        ))

        # ----------------------------
        # TOP MEMORY PROCESSES
        # ----------------------------
        try:
            processes = []

            for proc in psutil.process_iter(["name", "memory_info"]):
                try:
                    mem = proc.info["memory_info"]
                    if mem:
                        processes.append((proc.info["name"], mem.rss))
                except Exception:
                    continue

            # Sort by memory usage (descending)
            processes.sort(key=lambda x: x[1], reverse=True)

            top_procs = processes[:5]

            for name, mem in top_procs:
                mem_mb = round(mem / (1024**2), 1)
                findings.append(Finding(
                    id="perf.top_process",
                    title="High memory process",
                    severity="info",
                    detail=f"{name} using {mem_mb} MB RAM",
                ))

        except Exception as exc:
            log.warning("Process memory scan failed: %s", exc)

        findings.append(Finding(id="sys.os", title="Operating system", severity="info", detail=f"{os_name} ({os_version})"))
        findings.append(Finding(id="sys.cpu_cores", title="CPU logical cores", severity="info", detail=str(cpu_count)))
        findings.append(Finding(id="sys.ram_total", title="Installed memory", severity="info", detail=f"{total_ram_gb} GB"))
    
        # ----------------------------
        # DEFENDER STATUS (Windows)
        # ----------------------------
        if os_name == "Windows":
            findings.append(_defender_status_finding())

        # ----------------------------
        # PROCESS SCAN (light heuristic)
        # ----------------------------
        suspicious_count = 0

        for proc in psutil.process_iter(["name", "exe"]):
            try:
                exe_path = proc.info.get("exe") or ""
                name = proc.info.get("name") or "unknown"

                exe_lower = exe_path.lower()

                if any(x in exe_lower for x in ["\\temp\\", "\\appdata\\"]):
                    suspicious_count += 1

                    findings.append(Finding(
                        id="proc.suspicious_location",
                        title="Process running from a user-writable location",
                        severity="info",
                        detail=f"{name} ({exe_path}); location alone is not evidence of malicious behavior.",
                        recommended_next="Correlate signer, behavior and provider evidence if investigation is warranted.",
                    ))

                    if suspicious_count >= 5:
                        break

            except Exception:
                continue

        # ----------------------------
        # STARTUP FOLDER CHECK
        # ----------------------------
        try:
            startup_path = Path(os.getenv("APPDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs\\Startup"

            if startup_path.exists():
                for item in startup_path.iterdir():
                    if item.suffix.lower() in {".exe", ".lnk"}:
                        findings.append(Finding(
                            id="startup.entry",
                            title="Startup entry detected",
                            severity="info",
                            detail=str(item),
                        ))

        except Exception as exc:
            log.warning("Startup check failed: %s", exc)

        log.info("Enhanced system diagnostics complete.")

    except Exception as exc:
        log.exception("System diagnostics failed: %s", exc)
        findings.append(
            Finding(
                id="sys.error",
                title="System diagnostics error",
                severity="high",
                detail="Diagnostics encountered an unexpected error.",
                evidence=str(exc),
                recommended_next="Review logs and rerun diagnostics.",
            )
        )

    return findings

def run_file_scan(config, *, user_authorized: bool = False, target_path: str | None = None,
                  executor_factory=None) -> list[Finding]:
    """Compatibility entry point using the canonical scan lifecycle executor."""
    if not user_authorized:
        return [Finding(id="sec.authorization_required", title="Security scan authorization required",
                        severity="info", detail="No scan started. Confirm the scan mode and target first.")]
    from aida.frontend.commands.security import SecurityScanExecutor
    from aida.security.models import SecurityScanMode
    from aida.memory.service import MemoryService
    from aida.security.continuity import SecurityTaskLedger
    from aida.security.stand_down import StandDownService
    memory = MemoryService(config.memory_db_path)
    executor = (executor_factory or SecurityScanExecutor)(
        mode=SecurityScanMode.DEEP if target_path else SecurityScanMode.SURFACE,
        authorization_reason="Explicit CLI confirmation of targeted scan" if target_path else "Explicit CLI confirmation of provider Surface Scan",
        target_path=target_path, user_authorized=True, memory_service=memory,
        task_ledger=SecurityTaskLedger(memory.database, user_id=memory.user_id, device_id=memory.device_id),
        stand_down_service=StandDownService(memory.database, memory),
        max_monitor_seconds=300,
    )
    result = executor.execute()
    return [Finding(id="sec.provider_result", title="Provider security scan status", severity="info",
                    detail=result.transcript_text)]


def run_quickscan(config) -> list[Finding]:
    findings: list[Finding] = []

    try:
        os_name = platform.system()
        os_version = platform.version()
        cpu_count = psutil.cpu_count(logical=True) or 0

        vm = psutil.virtual_memory()
        total_ram_gb = round(vm.total / (1024**3), 2)
        available_ram_gb = round(vm.available / (1024**3), 2)

        findings.append(Finding(
            id="sys.os",
            title="Operating system",
            severity="info",
            detail=f"{os_name} ({os_version})",
        ))

        findings.append(Finding(
            id="sys.cpu",
            title="CPU logical cores",
            severity="info",
            detail=str(cpu_count),
        ))

        findings.append(Finding(
            id="sys.ram",
            title="Memory",
            severity="info",
            detail=f"{total_ram_gb} GB total, {available_ram_gb} GB available",
        ))

        if os_name == "Windows":
            findings.append(_defender_status_finding())

        log.info("Quickscan complete.")

    except Exception as exc:
        log.exception("Quickscan failed: %s", exc)
        findings.append(Finding(
            id="sys.quickscan_error",
            title="Quickscan error",
            severity="high",
            detail=str(exc),
        ))

    return findings

def _defender_status_finding() -> Finding:
    from aida.platform.windows import WindowsAdapter
    status = WindowsAdapter().security_provider_status()
    return Finding(id="sec.defender", title="Defender real-time protection",
        severity="medium" if status.enabled is False else "info",
        detail="Enabled" if status.enabled is True else "Disabled or not fully enabled" if status.enabled is False else "Unknown: provider status could not be verified",
        evidence=status.detail,
        recommended_next="Review the installed security provider's status." if status.enabled is not True else "")
