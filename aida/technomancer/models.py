from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

TECHNOMANCER_COLOR = "#00E5FF"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TelemetrySample:
    timestamp: float
    machine_id: str
    cpu_percent: float
    memory_percent: float
    swap_percent: float
    disk_percent: float
    disk_free_gb: float
    process_count: int
    gpu_percent: float | None = None
    vram_percent: float | None = None
    gpu_temp_c: float | None = None
    battery_percent: float | None = None
    battery_plugged: bool | None = None
    wifi_signal_percent: float | None = None
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0
    idle_seconds: float | None = None
    context_level: str = "basic"
    workload_context: str | None = None
    unexpected_shutdowns_30d: int = 0
    app_crashes_7d: int = 0
    service_failures_7d: int = 0
    storage_read_errors: int | None = None
    storage_write_errors: int | None = None
    storage_wear_percent: float | None = None
    battery_health_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HardwareInventory:
    machine_id: str
    captured_at: str = field(default_factory=utc_now_iso)
    system_manufacturer: str = "Unknown"
    system_model: str = "Unknown"
    board_manufacturer: str = "Unknown"
    board_model: str = "Unknown"
    cpu_model: str = "Unknown"
    total_ram_gb: float = 0.0
    ram_generation: str | None = None
    ram_speed_mhz: int | None = None
    ram_slots_total: int | None = None
    ram_slots_used: int | None = None
    max_ram_gb: float | None = None
    gpus: list[str] = field(default_factory=list)
    disks: list[str] = field(default_factory=list)
    bios_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Advisory:
    advisory_id: str
    category: str
    title: str
    message: str
    kind: str
    severity: str
    maturity: str
    evidence_type: str
    confidence: float
    first_seen: str
    last_seen: str
    observation_days: float
    recommendation: str | None = None
    expected_benefit: str | None = None
    active: bool = True
    last_surfaced_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
