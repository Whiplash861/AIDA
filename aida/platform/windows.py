from __future__ import annotations

import ctypes
import json
import os
import subprocess
from pathlib import Path

from aida.platform.base import PlatformAdapter
from aida.platform.models import SecurityProviderStatus, SecurityScanResult


class WindowsAdapter(PlatformAdapter):
    name = "Windows"

    SETTINGS_URIS = {
        "bluetooth": "ms-settings:bluetooth",
        "wifi": "ms-settings:network-wifi",
        "network": "ms-settings:network",
        "windows_update": "ms-settings:windowsupdate",
        "apps_features": "ms-settings:appsfeatures",
        "display": "ms-settings:display",
        "sound": "ms-settings:sound",
        "privacy": "ms-settings:privacy",
    }

    def _run_powershell(self, script: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

    def capabilities(self) -> dict[str, str]:
        status = self.security_provider_status()
        return {
            "process.telemetry": "native",
            "system.settings": "native",
            "filesystem.reveal": "native",
            "security.provider": "native" if status.available else "blocked",
            "security.quick_scan": "native" if status.available else "blocked",
            "background.execution": "compatible",
            "notifications": "compatible",
        }

    def security_provider_status(self) -> SecurityProviderStatus:
        try:
            result = self._run_powershell(
                "Get-MpComputerStatus | Select-Object "
                "AMServiceEnabled,AntivirusEnabled,RealTimeProtectionEnabled "
                "| ConvertTo-Json -Compress",
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return SecurityProviderStatus("Microsoft Defender", False, None, str(exc))
        if result.returncode != 0 or not result.stdout.strip():
            detail = (result.stderr or result.stdout or "Defender status unavailable").strip()
            return SecurityProviderStatus("Microsoft Defender", False, None, detail)
        try:
            payload = json.loads(result.stdout)
            enabled = bool(
                payload.get("AMServiceEnabled")
                and payload.get("AntivirusEnabled")
                and payload.get("RealTimeProtectionEnabled")
            )
            return SecurityProviderStatus(
                "Microsoft Defender",
                True,
                enabled,
                "Real-time protection enabled" if enabled else "Protection is not fully enabled",
            )
        except (ValueError, TypeError) as exc:
            return SecurityProviderStatus("Microsoft Defender", True, None, f"Unparsed status: {exc}")

    def request_security_scan(self, scope: str = "quick") -> SecurityScanResult:
        scan_type = "QuickScan" if scope.lower() != "full" else "FullScan"
        status = self.security_provider_status()
        if not status.available:
            return SecurityScanResult(status.provider, "unsupported", status.detail)
        try:
            scan = self._run_powershell(
                "$ProgressPreference='SilentlyContinue'; "
                f"Start-MpScan -ScanType {scan_type}; "
                "Write-Output 'AIDA_SCAN_COMPLETED'",
                timeout=900 if scan_type == "QuickScan" else 7200,
            )
        except subprocess.TimeoutExpired:
            return SecurityScanResult(
                status.provider,
                "unknown",
                "Security scan exceeded the verification timeout",
            )
        except FileNotFoundError as exc:
            return SecurityScanResult(status.provider, "failed", str(exc))
        if scan.returncode != 0 or "AIDA_SCAN_COMPLETED" not in scan.stdout:
            detail = (scan.stderr or scan.stdout or "Defender scan failed").strip()
            return SecurityScanResult(status.provider, "failed", detail)

        threat_result = self._run_powershell(
            "Get-MpThreat | Where-Object {$_.IsActive -eq $true} | "
            "Select-Object ThreatID,IsActive,SeverityID | ConvertTo-Json -Compress",
            timeout=30,
        )
        threats: list[str] = []
        if threat_result.returncode == 0 and threat_result.stdout.strip():
            try:
                parsed = json.loads(threat_result.stdout)
                rows = parsed if isinstance(parsed, list) else [parsed]
                for row in rows[-10:]:
                    threats.append(
                        f"ThreatID {row.get('ThreatID', 'unknown')} "
                        f"(active: {row.get('IsActive', 'unknown')}; "
                        f"severity: {row.get('SeverityID', 'unknown')})"
                    )
            except (ValueError, TypeError):
                pass
        if threats:
            return SecurityScanResult(
                status.provider,
                "completed",
                "Threat detections were returned",
                tuple(threats),
            )
        return SecurityScanResult(
            status.provider,
            "completed",
            "Scan completed with no active detections returned",
        )

    def open_settings(self, target: str) -> None:
        uri = self.SETTINGS_URIS.get(target, target)
        if not uri.startswith("ms-settings:"):
            raise ValueError(f"Unknown Windows settings target: {target}")
        subprocess.run(["cmd", "/c", "start", "", uri], check=False)

    def reveal_path(self, target: Path) -> None:
        subprocess.run(["explorer", "/select,", str(target.resolve())], check=False)

    def open_folder(self, folder: Path) -> None:
        subprocess.run(["explorer", str(folder.resolve())], check=False)

    def permission_level(self) -> str:
        try:
            return "administrator" if ctypes.windll.shell32.IsUserAnAdmin() else "standard"
        except Exception:
            return "unknown"

    def available_shell(self) -> str | None:
        return "PowerShell"
