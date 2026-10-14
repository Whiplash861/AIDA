"""Plain-language explanations of collected machine data and stored advice."""
from __future__ import annotations

import re

from aida.reporting import render_report
from aida.technomancer.models import Advisory, HardwareInventory, TelemetrySample


def _value(value, suffix="") -> str:
    return "unavailable" if value is None else f"{value}{suffix}"


def _percent(value) -> str:
    return "unavailable" if value is None else f"{value:.1f}%"


def _plain(text: str) -> str:
    """Explain vocabulary in both current and previously saved advisories."""
    replacements = {
        "system/motherboard QVL": "manufacturer's tested memory compatibility list",
        "slot layout": "available memory slots", "firmware limits": "limits set by the computer's built-in software",
        "module form factor": "memory module size and type", "PSU headroom": "power supply's spare capacity",
        "PSU": "power supply", "hardware-capacity hypothesis": "possible explanation involving limited hardware capacity",
        "CPU saturation": "processor use near full capacity", "GPU saturation": "graphics processor use near full capacity",
        "RAM utilization": "working memory use", "RAM pressure": "heavy working memory use",
        "swap occupancy": "use of extra memory on disk", "active paging": "moving working data between memory and disk",
        "paging": "moving working data between memory and disk", "latency": "response delays",
        "thermal limits": "temperature limits", "thermals": "temperatures and cooling",
        "throttling": "automatic slowing to stay within safe operating limits",
        "retransmissions": "repeated network transfers", "throughput": "transfer speed",
        "primary volume": "main storage drive", "storage reliability telemetry": "storage health measurements",
        "CPU/platform": "processor or computer", "compute bottlenecks": "delays in demanding calculations",
        "frame-time/render/compute requirements": "needs for smooth graphics, image rendering, or demanding calculations",
    }
    meanings = {key.lower(): value for key, value in replacements.items()}
    pattern = re.compile("|".join(re.escape(term) for term in sorted(meanings, key=len, reverse=True)), re.IGNORECASE)
    return pattern.sub(lambda match: meanings[match.group().lower()], text)


def _next(item: Advisory) -> str:
    if item.recommendation:
        return _plain(item.recommendation)
    return {
        "health.memory_pressure": "Check which applications use the most memory in Task Manager. Save your work before closing unused applications, then repeat the check.",
        "health.cpu_saturation": "Check which applications use the most processor time in Task Manager. Compare the result during normal work and while idle before changing hardware.",
        "health.storage_capacity": "Review Storage in Windows Settings. Back up important files and choose what to remove yourself before checking free space again.",
        "health.wifi_signal": "Compare the connection closer to your router and note whether calls or transfers improve.",
        "health.gpu_saturation": "Compare graphics use during demanding work and while idle. High use during a game or rendering task can be expected.",
    }.get(item.advisory_id, "Compare this observation with what you were doing at the time, then repeat the health check if the problem continues.")


def render_advisories(items: list[Advisory], *, title="Technomancer advisories") -> str:
    found, unknown, steps, details = [], [], [], []
    for item in items:
        priority = "Review promptly: " if item.severity in {"high", "critical"} else ""
        found.append(f"{priority}{_plain(item.title)}. {_plain(item.message)}")
        unknown.append(f"{_plain(item.title)}: this advice is based on {item.observation_days:.1f} days of covered observations; it does not establish the cause by itself.")
        if item.expected_benefit:
            unknown.append(f"Expected benefit, not yet verified: {_plain(item.expected_benefit)}")
        steps.append(_next(item))
        details.append(f"{item.advisory_id}: {item.kind}; evidence {item.evidence_type}; maturity {item.maturity}; internal confidence estimate {item.confidence:.0%}; last observed {item.last_seen}.")
        details.append(f"Original advisory: {item.message} Recommendation: {item.recommendation or 'not recorded'}")
    if not items:
        found.append("There are no active advisories in the saved record.")
        unknown.append("An empty advice list does not establish that every part of the computer was checked or is working correctly.")
        steps.append("Run Technomancer health for a current snapshot, especially if you are noticing a problem.")
    else:
        unknown.append("These are saved observations; conditions may have changed since they were recorded.")
    return render_report(title, found=found, unknown=unknown, next_steps=steps, details=details)


def render_health(inventory: HardwareInventory, sample: TelemetrySample | None,
                  advisories: list[Advisory], days: float) -> str:
    found = [f"Computer: {inventory.system_manufacturer} {inventory.system_model}.",
             f"Covered observation history: {days:.1f} days."]
    unknown = ["A snapshot can show a busy computer without identifying why it is busy. It does not test every component or establish that the computer is free of security threats."]
    details = []
    if sample is None:
        unknown.append("No recent resource measurement was available. Current processor, memory, and storage use remain unknown.")
    else:
        for label, value in (("Processor use (CPU)", sample.cpu_percent), ("Memory use (RAM)", sample.memory_percent),
                             ("Extra memory on disk (swap/pagefile)", sample.swap_percent), ("Storage space used", sample.disk_percent),
                             ("Graphics processor use (GPU)", sample.gpu_percent)):
            if value is None:
                unknown.append(f"{label}: measurement unavailable.")
            else:
                found.append(f"{label}: {_percent(value)}.")
        if sample.gpu_temp_c is not None:
            found.append(f"Graphics processor temperature: {sample.gpu_temp_c:.1f}°C.")
        details.append(f"Sample timestamp (Unix seconds): {sample.timestamp}; machine: {inventory.machine_id}.")
    health = [item for item in advisories if item.kind == "health"]
    steps = []
    for item in health:
        priority = "Review promptly: " if item.severity in {"high", "critical"} else ""
        found.append(f"{priority}{_plain(item.title)}. {_plain(item.message)}")
        steps.append(_next(item))
        details.append(f"{item.advisory_id}: {item.maturity}; internal confidence estimate {item.confidence:.0%}; evidence {item.evidence_type}; {item.observation_days:.1f} covered days.")
    if not health:
        found.append("The available observations did not produce a machine-health advisory.")
    if days < 1:
        unknown.append("There is not yet enough covered history to describe a typical day of use reliably.")
    steps.append("If you notice a slowdown, repeat this check while it happens and note which applications you are using. Save your work before closing applications.")
    return render_report("Technomancer machine-health assessment", found=found, unknown=unknown, next_steps=steps, details=details)


def render_upgrades(inventory: HardwareInventory, advisories: list[Advisory], days: float) -> str:
    upgrades = [item for item in advisories if item.kind == "upgrade"]
    found = [f"AIDA has {days:.1f} days of covered observations for this computer."]
    unknown = ["An upgrade's benefit and compatibility have not been verified by installing or testing new hardware."]
    steps, details = [], []
    if not upgrades:
        found.append("The available observations do not justify a hardware purchase recommendation.")
        if days < 30:
            unknown.append("There is less than 30 days of covered history, so persistent hardware limits cannot yet be assessed reliably.")
        steps.append("Use Technomancer health to investigate any current slowdown. Collect observations during normal use before considering a purchase; background monitoring requires your permission.")
    for item in upgrades:
        found.append(f"{_plain(item.title)}. {_plain(item.message)}")
        if item.expected_benefit:
            unknown.append(f"Expected benefit, not yet verified: {_plain(item.expected_benefit)}")
        steps.append(_next(item))
        details.append(f"{item.advisory_id}: {item.observation_days:.1f} covered days; internal confidence estimate {item.confidence:.0%}.")
        details.append(f"Original advisory: {item.message} Recommendation: {item.recommendation or 'not recorded'}")
    if upgrades:
        steps.append("Before buying anything, verify your computer's supported parts, available slots, cost, and whether a software adjustment would address the problem.")
        details.append(f"Motherboard: {inventory.board_manufacturer} {inventory.board_model}; memory slots: {_value(inventory.ram_slots_used)} used / {_value(inventory.ram_slots_total)} total.")
    return render_report("Technomancer upgrade assessment", found=found, unknown=unknown, next_steps=steps, details=details)


def render_inventory(inventory: HardwareInventory) -> str:
    found, unknown = [], []
    values = [("Computer", f"{inventory.system_manufacturer} {inventory.system_model}"),
              ("Motherboard", f"{inventory.board_manufacturer} {inventory.board_model}"),
              ("Processor (CPU)", inventory.cpu_model),
              ("Installed memory (RAM)", f"{inventory.total_ram_gb:.1f} GB" if inventory.total_ram_gb > 0 else None),
              ("Memory generation", inventory.ram_generation), ("Memory speed", _value(inventory.ram_speed_mhz, " MT/s")),
              ("Memory slots used", _value(inventory.ram_slots_used)), ("Memory slots total", _value(inventory.ram_slots_total)),
              ("Maximum memory reported", _value(inventory.max_ram_gb, " GB")),
              ("Graphics hardware", ", ".join(inventory.gpus)), ("Storage hardware", ", ".join(inventory.disks))]
    for label, value in values:
        if not value or str(value).lower() in {"unknown", "unknown unknown", "unavailable"}:
            unknown.append(f"{label}: not reported by this check.")
        else:
            found.append(f"{label}: {value}.")
    unknown.append("This inventory identifies reported hardware; it does not test component health or guarantee upgrade compatibility.")
    return render_report("Technomancer hardware inventory", found=found, unknown=unknown,
                         next_steps=["Use this inventory when investigating a problem. Verify the manufacturer's specifications before replacing or upgrading a part."],
                         details=[f"Machine ID: {inventory.machine_id}", f"Recorded: {inventory.captured_at}", f"BIOS: {inventory.bios_version or 'unavailable'}"])
