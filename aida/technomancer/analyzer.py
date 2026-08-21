from __future__ import annotations

import time
from datetime import datetime, timezone

from aida.technomancer.models import Advisory, HardwareInventory, TelemetrySample
from aida.technomancer.storage import TechnomancerStore


def _ratio(samples: list[TelemetrySample], predicate) -> float:
    return sum(1 for sample in samples if predicate(sample)) / len(samples) if samples else 0.0


def _maturity(days: float, ratio: float, urgent: bool = False) -> str:
    if urgent:
        return "urgent"
    if days >= 30 and ratio >= 0.45:
        return "actionable"
    if days >= 14 and ratio >= 0.40:
        return "degrading"
    if days >= 7 and ratio >= 0.35:
        return "impacting"
    if days >= 3 and ratio >= 0.30:
        return "persistent"
    if ratio >= 0.20:
        return "recurring"
    return "transient"


def _advisory(advisory_id: str, category: str, title: str, message: str, kind: str, severity: str, maturity: str, evidence_type: str, confidence: float, days: float, recommendation: str | None = None, benefit: str | None = None) -> Advisory:
    now = datetime.now(timezone.utc).isoformat()
    return Advisory(
        advisory_id=advisory_id,
        category=category,
        title=title,
        message=message,
        kind=kind,
        severity=severity,
        maturity=maturity,
        evidence_type=evidence_type,
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        first_seen=now,
        last_seen=now,
        observation_days=round(days, 1),
        recommendation=recommendation,
        expected_benefit=benefit,
    )


def analyze(store: TechnomancerStore, inventory: HardwareInventory, now_timestamp: float | None = None) -> list[Advisory]:
    now_timestamp = now_timestamp or time.time()
    samples = store.samples_since(inventory.machine_id, now_timestamp - 30 * 86400)
    if not samples:
        return []
    days = store.observation_days(inventory.machine_id, now_timestamp)
    output: list[Advisory] = []

    memory_ratio = _ratio(samples, lambda s: s.memory_percent >= 85.0)
    memory_maturity = _maturity(days, memory_ratio)
    if memory_ratio >= 0.30 and days >= 3:
        output.append(_advisory(
            "health.memory_pressure", "memory", "Persistent memory pressure",
            "RAM utilization has been persistently high. Sustained memory exhaustion can increase paging, latency, stuttering, freezes, and application unresponsiveness.",
            "health", "medium", memory_maturity, "observed", 0.86, days,
        ))

    swap_ratio = _ratio(samples, lambda s: s.swap_percent >= 20.0)
    process_context = any(s.context_level == "process" and s.workload_context for s in samples)
    if days >= 30 and memory_ratio >= 0.40 and swap_ratio >= 0.20:
        target = 32 if inventory.total_ram_gb <= 16 else 64 if inventory.total_ram_gb <= 32 else int(max(64, inventory.total_ram_gb * 2))
        if inventory.max_ram_gb:
            target = int(min(target, inventory.max_ram_gb))
        spec = f"{target} GB"
        if inventory.ram_generation:
            spec += f" {inventory.ram_generation}"
        if inventory.ram_speed_mhz:
            spec += f" around {inventory.ram_speed_mhz} MT/s"
        confidence = 0.84 if process_context else 0.64
        outcome_score = store.outcome_score("upgrade.memory")
        if outcome_score is not None:
            confidence = min(0.95, max(0.45, confidence * 0.8 + outcome_score * 0.2))
        output.append(_advisory(
            "upgrade.memory.capacity", "memory", "Memory capacity upgrade worth considering",
            "Long-term memory pressure and paging are occurring often enough to justify a capacity review.",
            "upgrade", "medium", "actionable", "derived", confidence, days,
            recommendation=f"Consider a matched {spec} memory configuration. Verify the system/motherboard QVL, slot layout, firmware limits, and module form factor before purchase.",
            benefit="More memory headroom should reduce paging and improve responsiveness under the observed workload.",
        ))

    cpu_ratio = _ratio(samples, lambda s: s.cpu_percent >= 90.0)
    if cpu_ratio >= 0.30 and days >= 3:
        output.append(_advisory(
            "health.cpu_saturation", "cpu", "Sustained CPU saturation",
            "CPU demand has repeatedly remained near saturation. Persistent saturation can increase queueing and response latency; thermal limits may also cause throttling.",
            "health", "medium", _maturity(days, cpu_ratio), "observed", 0.82, days,
        ))
    if days >= 30 and cpu_ratio >= 0.45 and process_context:
        output.append(_advisory(
            "upgrade.cpu.capacity", "cpu", "CPU capacity may be limiting the workload",
            "CPU saturation is persistent and process-level workload context is available, making a hardware-capacity hypothesis more defensible.",
            "upgrade", "medium", "actionable", "inferred", 0.67, days,
            recommendation="Review CPU/platform upgrade options only after software, startup load, thermals, drivers, and background processes are ruled out.",
            benefit="A faster CPU/platform may reduce sustained compute bottlenecks in the observed workloads.",
        ))

    disk_ratio = _ratio(samples, lambda s: s.disk_percent >= 90.0)
    if disk_ratio >= 0.30 and days >= 3:
        output.append(_advisory(
            "health.storage_capacity", "storage", "Storage capacity pressure",
            "The primary volume is repeatedly above 90% used. Low free space can reduce update headroom, caching efficiency, and overall responsiveness.",
            "health", "medium", _maturity(days, disk_ratio), "observed", 0.94, days,
        ))

    latest = samples[-1]
    read_errors = latest.storage_read_errors or 0
    write_errors = latest.storage_write_errors or 0
    wear = latest.storage_wear_percent
    if read_errors > 0 or write_errors > 0 or (wear is not None and wear >= 90):
        output.append(_advisory(
            "health.storage_reliability", "storage", "Storage reliability warning",
            "Storage reliability telemetry reports error or wear indicators that warrant prompt backup and device-health verification.",
            "health", "high", "urgent", "observed", 0.92, days,
            recommendation="Back up important data and verify the physical disk with vendor/OS health tools before deciding whether replacement is required.",
        ))

    wifi_values = [s.wifi_signal_percent for s in samples if s.wifi_signal_percent is not None]
    if wifi_values and sum(1 for value in wifi_values if value < 40.0) / len(wifi_values) >= 0.35 and days >= 3:
        output.append(_advisory(
            "health.wifi_signal", "network", "Recurring weak Wi-Fi signal",
            "Wi-Fi signal has repeatedly fallen below the learned usable range. This can contribute to retransmissions, unstable calls, and inconsistent throughput.",
            "health", "medium", _maturity(days, 0.35), "observed", 0.83, days,
        ))

    if latest.unexpected_shutdowns_30d >= 3:
        output.append(_advisory(
            "health.power_stability", "power", "Unexpected power-state instability",
            f"Windows recorded {latest.unexpected_shutdowns_30d} unexpected shutdown/power events in the last 30 days. PSU or power-delivery trouble is one possible cause, but this evidence does not identify the PSU as the cause.",
            "health", "medium", "persistent", "inferred", 0.58, days,
            recommendation="Correlate the events with thermals, drivers, hardware errors, wall power, overclocking, and PSU headroom before attributing the instability to a specific component.",
        ))

    gpu_values = [s for s in samples if s.gpu_percent is not None]
    if gpu_values:
        gpu_ratio = sum(1 for s in gpu_values if (s.gpu_percent or 0) >= 95.0) / len(gpu_values)
        if gpu_ratio >= 0.35 and days >= 3:
            output.append(_advisory(
                "health.gpu_saturation", "gpu", "Recurring GPU saturation",
                "GPU utilization frequently reaches saturation. This is not automatically a problem: gaming, rendering, and compute workloads may intentionally use the GPU fully.",
                "health", "info", _maturity(days, gpu_ratio), "observed", 0.78, days,
            ))
        if days >= 30 and gpu_ratio >= 0.50 and any(s.workload_context for s in gpu_values):
            output.append(_advisory(
                "upgrade.gpu.capacity", "gpu", "GPU capacity may be limiting the workload",
                "Persistent GPU saturation is paired with workload context, so an upgrade hypothesis can be considered rather than inferred from utilization alone.",
                "upgrade", "medium", "actionable", "inferred", 0.62, days,
                recommendation="Compare the observed workload's frame-time/render/compute requirements against the current GPU before selecting a replacement.",
            ))

    for item in output:
        store.upsert_advisory(item)
    return output
