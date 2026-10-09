from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import math

TECHNOMANCER_COLOR = "#00E5FF"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TelemetrySample:
    timestamp: float
    machine_id: str
    cpu_percent: float | None
    memory_percent: float | None
    swap_percent: float | None
    disk_percent: float | None
    disk_free_gb: float | None
    process_count: int | None
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
    unexpected_shutdowns_30d: int | None = None
    app_crashes_7d: int | None = None
    service_failures_7d: int | None = None
    storage_read_errors: int | None = None
    storage_write_errors: int | None = None
    storage_wear_percent: float | None = None
    battery_health_percent: float | None = None

    def __post_init__(self):
        if not self.machine_id or not math.isfinite(self.timestamp):
            raise ValueError("Sample needs a machine identity and finite timestamp")
        for name in ("cpu_percent", "memory_percent", "swap_percent", "disk_percent", "gpu_percent", "vram_percent", "battery_percent", "wifi_signal_percent"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError(f"Invalid telemetry value: {name}")

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
