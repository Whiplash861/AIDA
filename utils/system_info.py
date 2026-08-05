from __future__ import annotations

import platform
from dataclasses import asdict, dataclass

import psutil


@dataclass(frozen=True, slots=True)
class SystemInfo:
    os_family: str
    os_release: str
    os_version: str
    architecture: str
    logical_cores: int
    total_memory_gb: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def collect_system_info() -> SystemInfo:
    return SystemInfo(
        os_family=platform.system(),
        os_release=platform.release(),
        os_version=platform.version(),
        architecture=platform.machine(),
        logical_cores=psutil.cpu_count(logical=True) or 0,
        total_memory_gb=round(psutil.virtual_memory().total / (1024 ** 3), 2),
    )
