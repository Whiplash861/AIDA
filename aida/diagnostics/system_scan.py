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
            detail += " | Critical load condition"
        elif memory_percent >= 70:
            detail += " | Moderate memory pressure"
        else:
            detail += " | Operating within normal parameters"

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
            try:
                import subprocess

                result = subprocess.run(
                    ["powershell", "-Command", "Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                output = result.stdout.lower()

                if "true" in output:
                    findings.append(Finding(
                        id="sec.defender",
                        title="Defender real-time protection",
                        severity="info",
                        detail="Enabled",
                    ))
                else:
                    findings.append(Finding(
                        id="sec.defender",
                        title="Defender real-time protection",
                        severity="high",
                        detail="Disabled",
                        recommended_next="Enable real-time protection in Windows Security.",
                    ))

            except Exception as exc:
                log.warning("Defender check failed: %s", exc)

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
                        title="Process running from suspicious location",
                        severity="medium",
                        detail=f"{name} ({exe_path})",
                        recommended_next="Verify legitimacy of this process.",
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

    Finding(
        id="...",
        title="...",
        severity="info | medium | high",
        detail="...",
        recommended_next="..."  # optional but preferred
    )
    return findings

def run_file_scan(config) -> list:
    findings = []

    try:
        import subprocess
        import time
        import os

        startupinfo = None
        creationflags = 0

        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW

        # Start Defender quick scan without waiting for full completion
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "$ProgressPreference='SilentlyContinue'; Start-MpScan -ScanType QuickScan | Out-Null"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

        # Give Defender a moment to initialize
        time.sleep(5)

        # Check for detections
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "$ProgressPreference='SilentlyContinue'; Get-MpThreatDetection | Out-String"
            ],
            capture_output=True,
            text=True,
            timeout=10,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

        output = (result.stdout or "").strip()

        if not output:
            findings.append(Finding(
                id="sec.no_threats",
                title="Threat scan result",
                severity="info",
                detail="No active threats detected",
            ))
        else:
            # Extract threat names (basic parsing)
            threats = []

            for line in output.splitlines():
                line = line.strip()
                if line and "ThreatName" not in line:
                    threats.append(line)

            if threats:
                for threat in threats[:3]:  # limit output
                    findings.append(Finding(
                        id="sec.threat_detail",
                        title="Threat detected",
                        severity="high",
                        detail=threat,
                        recommended_next="Review and quarantine in Windows Security.",
                    ))
            else:
                findings.append(Finding(
                    id="sec.threat_detected",
                    title="Threats detected",
                    severity="high",
                    detail="Threats detected but could not parse details",
                ))

    except Exception as exc:
        findings.append(Finding(
            id="sec.scan_error",
            title="Antivirus scan failed",
            severity="high",
            detail=str(exc),
        ))

    Finding(
        id="...",
        title="...",
        severity="info | medium | high",
        detail="...",
        recommended_next="..."  # optional but preferred
    )
    return findings

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
            import subprocess

            result = subprocess.run(
                ["powershell", "-Command", "Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if "true" in result.stdout.lower():
                findings.append(Finding(
                    id="sec.defender",
                    title="Defender status",
                    severity="info",
                    detail="Real-time protection enabled",
                ))
            else:
                findings.append(Finding(
                    id="sec.defender",
                    title="Defender status",
                    severity="high",
                    detail="Real-time protection disabled",
                ))

        log.info("Quickscan complete.")

    except Exception as exc:
        log.exception("Quickscan failed: %s", exc)
        findings.append(Finding(
            id="sys.quickscan_error",
            title="Quickscan error",
            severity="high",
            detail=str(exc),
        ))

    Finding(
        id="...",
        title="...",
        severity="info | medium | high",
        detail="...",
        recommended_next="..."  # optional but preferred
    )
    return findings