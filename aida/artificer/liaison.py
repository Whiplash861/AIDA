from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from datetime import datetime

from aida.artificer.models import CapabilityResult, PlatformProfile, utc_now
from aida.platform.base import PlatformAdapter


class Liaison:
    """Builds the current platform profile and verifies AIDA capabilities."""

    TRACKED_DEPENDENCIES = (
        "openai",
        "python-dotenv",
        "psutil",
        "PySide6",
        "requests",
        "playsound",
        "simpleaudio",
        "cryptography",
    )

    def __init__(self, adapter: PlatformAdapter) -> None:
        self.adapter = adapter

    def capture_profile(self) -> PlatformProfile:
        now = datetime.now().astimezone()
        timezone_name = now.tzname() or "unknown"
        offset = now.utcoffset()
        offset_seconds = int(offset.total_seconds()) if offset else 0
        dependencies: dict[str, str] = {}
        for dependency in self.TRACKED_DEPENDENCIES:
            try:
                dependencies[dependency] = importlib.metadata.version(dependency)
            except importlib.metadata.PackageNotFoundError:
                dependencies[dependency] = "not-installed"

        payload = {
            "os_family": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "kernel": platform.platform(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "timezone_name": timezone_name,
            "utc_offset_seconds": offset_seconds,
            "permission_level": self.adapter.permission_level(),
            "available_shell": self.adapter.available_shell(),
            "security_provider": self.adapter.security_provider_status().provider,
            "capabilities": self.adapter.capabilities(),
            "dependency_versions": dependencies,
        }
        profile_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        return PlatformProfile(
            profile_id=profile_id,
            captured_at_utc=utc_now(),
            os_family=payload["os_family"],
            os_release=payload["os_release"],
            os_version=payload["os_version"],
            kernel=payload["kernel"],
            architecture=payload["architecture"],
            python_version=payload["python_version"],
            python_implementation=payload["python_implementation"],
            timezone_name=timezone_name,
            utc_offset_seconds=offset_seconds,
            permission_level=payload["permission_level"],
            available_shell=payload["available_shell"],
            security_provider=payload["security_provider"],
            capabilities=payload["capabilities"],
            dependency_versions=dependencies,
        )

    def verify_capabilities(self, profile: PlatformProfile) -> list[CapabilityResult]:
        verified_at = utc_now()
        return [
            CapabilityResult(
                capability=name,
                status=status,
                detail=f"{name} reported as {status} by {self.adapter.name} adapter",
                verified_at_utc=verified_at,
                profile_id=profile.profile_id,
            )
            for name, status in profile.capabilities.items()
        ]
