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
        return {
            "process.telemetry": "native",
            "system.settings": "native",
            "filesystem.reveal": "native",
            "security.provider": "unverified",
            "security.quick_scan": "unverified",
            "background.execution": "compatible",
            "notifications": "compatible",
        }

    def security_provider_status(self) -> SecurityProviderStatus:
        try:
            result = self._run_powershell(
                "$ErrorActionPreference='Stop'; Get-MpComputerStatus | Select-Object "
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
            if not isinstance(payload, dict) or any(not isinstance(payload.get(key), bool) for key in ("AMServiceEnabled", "AntivirusEnabled", "RealTimeProtectionEnabled")):
                raise ValueError("Provider status fields are missing or invalid")
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
        return SecurityScanResult("Microsoft Defender", "unsupported",
            "Use AIDA's authorized security orchestrator for provider scan lifecycle and verified outcomes.")

    def open_settings(self, target: str) -> None:
        uri = self.SETTINGS_URIS.get(target, target)
        if not uri.startswith("ms-settings:"):
            raise ValueError(f"Unknown Windows settings target: {target}")
        os.startfile(uri)

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
