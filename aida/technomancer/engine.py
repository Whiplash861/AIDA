from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aida.engines.base import EngineDescriptor, EngineRequest, EngineResponse
from aida.engines.bus import EngineBus, EngineEvent
from aida.technomancer.analyzer import analyze
from aida.technomancer.launcher import launch_background, stop_background, data_directory
from aida.technomancer.models import TECHNOMANCER_COLOR, Advisory, HardwareInventory
from aida.technomancer.permissions import PermissionStore, TECHNOMANCER_BACKGROUND_SCOPE
from aida.technomancer.sensors import collect_hardware_inventory, collect_telemetry
from aida.technomancer.storage import TechnomancerStore


class TechnomancerEngine:
    descriptor = EngineDescriptor(
        key="technomancer",
        name="Technomancer",
        color=TECHNOMANCER_COLOR,
        domain="Longitudinal machine health, hardware lifecycle, performance baselines, and upgrade reasoning",
    )

    def __init__(
        self,
        base_dir: str | Path,
        store: TechnomancerStore | None = None,
        permissions: PermissionStore | None = None,
        bus: EngineBus | None = None,
        context_level: str = "basic",
        data_dir: str | Path | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.data_dir = Path(data_dir or (store.path.parent if store else data_directory()))
        memory_dir = self.data_dir
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.store = store or TechnomancerStore(memory_dir / "technomancer.db")
        self.permissions = permissions or PermissionStore(memory_dir / "technomancer_permissions.json")
        self.bus = bus or EngineBus()
        self.context_level = context_level

    @classmethod
    def from_config(cls, config, bus: EngineBus | None = None) -> "TechnomancerEngine":
        directory = Path(getattr(config, "technomancer_data_dir", "") or (Path(config.memory_db_path).parent.parent / "technomancer"))
        _migrate_legacy_store(Path(config.base_dir), directory)
        return cls(base_dir=config.base_dir, bus=bus, data_dir=directory)

    def handle(self, request: EngineRequest) -> EngineResponse:
        intent = request.intent.strip().lower()
        handlers = {
            "health": self.health_report,
            "upgrades": self.upgrade_report,
            "inventory": self.inventory_report,
            "advisories": self.advisory_report,
        }
        if intent in handlers:
            return EngineResponse("technomancer", handlers[intent]())
        return EngineResponse("technomancer", "Technomancer can assess machine health, long-term trends, hardware inventory, advisories, and evidence-based upgrade worthiness.")

    def monitor_cycle(self) -> list[Advisory]:
        inventory = collect_hardware_inventory()
        changed = self.store.record_inventory(inventory)
        sample = collect_telemetry(context_level=self.context_level)
        self.store.record_sample(sample)
        advisories = analyze(self.store, inventory, now_timestamp=sample.timestamp)
        self.store.compact(inventory.machine_id)
        self.store.record_runtime_health(success=True)
        self.bus.publish(EngineEvent(
            topic="technomancer.observation",
            source_engine="technomancer",
            payload={"machine_id": inventory.machine_id, "hardware_changed": changed, "advisories": [item.to_dict() for item in advisories]},
        ))
        return advisories

    def _ensure_current_data(self) -> tuple[HardwareInventory, list[Advisory]]:
        inventory = collect_hardware_inventory()
        self.store.record_inventory(inventory)
        sample = collect_telemetry(context_level=self.context_level)
        self.store.record_sample(sample)
        advisories = analyze(self.store, inventory, now_timestamp=sample.timestamp)
        return inventory, advisories

    def health_report(self) -> str:
        inventory, advisories = self._ensure_current_data()
        sample = self.store.samples_since(inventory.machine_id, time.time() - 3600)[-1]
        health = [item for item in advisories if item.kind == "health"]
        lines = [
            "Technomancer machine-health assessment",
            f"Machine: {inventory.system_manufacturer} {inventory.system_model}",
            f"CPU: {_percent(sample.cpu_percent)} | RAM: {_percent(sample.memory_percent)} | Swap/Pagefile: {_percent(sample.swap_percent)} | Storage used: {_percent(sample.disk_percent)}",
        ]
        if sample.gpu_percent is not None:
            lines.append(f"GPU: {sample.gpu_percent:.1f}%" + (f" | {sample.gpu_temp_c:.1f}°C" if sample.gpu_temp_c is not None else ""))
        days = self.store.observation_days(inventory.machine_id, sample.timestamp)
        lines.append(f"Covered observation history: {days:.1f} days")
        if not health:
            lines.append("No mature machine-health advisory is currently justified. Technomancer will continue building this machine's baseline when authorized.")
        else:
            lines.append("")
            for item in health:
                lines.extend([
                    f"{item.title} [{item.maturity.upper()} | confidence {item.confidence:.0%}]",
                    item.message,
                    f"Evidence class: {item.evidence_type} | observation window: {item.observation_days:.1f} days",
                ])
                if item.recommendation:
                    lines.append(f"Recommended next step: {item.recommendation}")
                lines.append("")
        return "\n".join(lines).strip()

    def upgrade_report(self) -> str:
        inventory, advisories = self._ensure_current_data()
        upgrades = [item for item in advisories if item.kind == "upgrade"]
        days = self.store.observation_days(inventory.machine_id, time.time())
        if not upgrades:
            if days < 30:
                return (
                    "Technomancer upgrade assessment\n"
                    f"I have {days:.1f} days of covered history for this machine. That is not enough longitudinal evidence for a confident hardware purchase recommendation yet. "
                    "I can still identify current pressure, but I will not convert a short snapshot into a sales-like recommendation."
                )
            return "Technomancer upgrade assessment\nNo hardware upgrade is currently justified by the observed evidence."

        lines = ["Technomancer upgrade assessment", "Recommendations are evidence-based and vendor-neutral; no sponsorship or affiliate weighting is used.", ""]
        aptitude, aptitude_confidence = self.store.aptitude("pc_hardware")
        for item in upgrades:
            lines.append(f"{item.title} [confidence {item.confidence:.0%}]")
            lines.append(item.message)
            if item.recommendation:
                if aptitude >= 0.75 and aptitude_confidence >= 0.5:
                    lines.append(item.recommendation)
                else:
                    lines.append(f"Recommendation: {item.recommendation}")
                    if item.category == "memory":
                        lines.append(f"System basis: {inventory.board_manufacturer} {inventory.board_model}; {inventory.ram_slots_used or '?'} of {inventory.ram_slots_total or '?'} memory slots populated.")
            if item.expected_benefit:
                lines.append(f"Expected benefit: {item.expected_benefit}")
            lines.append("")
        return "\n".join(lines).strip()

    def inventory_report(self) -> str:
        inventory = collect_hardware_inventory()
        self.store.record_inventory(inventory)
        return "\n".join([
            "Technomancer hardware inventory",
            f"Machine ID: {inventory.machine_id}",
            f"System: {inventory.system_manufacturer} {inventory.system_model}",
            f"Motherboard: {inventory.board_manufacturer} {inventory.board_model}",
            f"CPU: {inventory.cpu_model}",
            f"RAM: {inventory.total_ram_gb:.1f} GB" + (f" {inventory.ram_generation}" if inventory.ram_generation else "") + (f" @ {inventory.ram_speed_mhz} MT/s" if inventory.ram_speed_mhz else ""),
            f"Memory slots: {inventory.ram_slots_used or '?'} used / {inventory.ram_slots_total or '?'} total",
            f"Maximum memory reported: {inventory.max_ram_gb:.1f} GB" if inventory.max_ram_gb else "Maximum memory reported: unavailable",
            f"GPU(s): {', '.join(inventory.gpus) if inventory.gpus else 'Telemetry unavailable'}",
            f"Storage: {', '.join(inventory.disks) if inventory.disks else 'Telemetry unavailable'}",
            f"BIOS: {inventory.bios_version or 'Unknown'}",
        ])

    def advisory_report(self) -> str:
        items = self.store.active_advisories()
        if not items:
            return "Technomancer has no active mature advisories."
        return "\n\n".join(f"{item.title} ({item.kind}, {item.maturity}, {item.confidence:.0%})\n{item.message}" for item in items)

    def set_autonomy(self, enabled: bool) -> str:
        self.permissions.set_autonomy(enabled)
        if not enabled:
            stop_background(self.base_dir, data_dir=self.data_dir)
        elif self.permissions.scope_enabled(TECHNOMANCER_BACKGROUND_SCOPE):
            return launch_background(self.base_dir, self.permissions, data_dir=self.data_dir)[1]
        return f"Technomancer autonomy permission synchronized: {'enabled' if enabled else 'disabled'}."

    def set_background_monitoring(self, enabled: bool) -> str:
        self.permissions.set_scope(TECHNOMANCER_BACKGROUND_SCOPE, enabled)
        if not enabled:
            return stop_background(self.base_dir, data_dir=self.data_dir)[1]
        if not self.permissions.autonomy_enabled:
            return "Technomancer background-monitoring consent is enabled, but the runtime will remain inactive until AIDA Autonomy is enabled."
        return launch_background(self.base_dir, self.permissions, data_dir=self.data_dir)[1]

    def record_recommendation_outcome(self, advisory_id: str, outcome: str, notes: str = "") -> None:
        self.store.record_outcome(advisory_id, outcome, notes)

    def update_user_aptitude(self, domain: str, level: float, confidence: float) -> None:
        self.store.update_aptitude(domain, level, confidence)

    def proactive_messages(self, limit: int = 2) -> list[str]:
        now = datetime.now(timezone.utc)
        messages: list[str] = []
        for item in self.store.active_advisories():
            should_surface = False
            if item.last_surfaced_at:
                try:
                    last = datetime.fromisoformat(item.last_surfaced_at)
                    should_surface = now - last >= (timedelta(hours=24) if item.severity == "high" else timedelta(days=7))
                except ValueError:
                    should_surface = True
            else:
                should_surface = True
            if should_surface:
                messages.append(f"Technomancer advisory: {item.title}. {item.message}")
                self.store.mark_surfaced(item.advisory_id, now.isoformat())
            if len(messages) >= limit:
                break
        return messages


def _migrate_legacy_store(base_dir: Path, directory: Path) -> None:
    """Copy legacy observations once; retain the source and do not inherit consent."""
    import sqlite3
    from aida.artificer.state_file import locked_state
    source = base_dir / "memory" / "technomancer.db"
    target = directory / "technomancer.db"
    if not source.is_file() or target.exists():
        return
    with locked_state(target):
        if target.exists():
            return
        import tempfile
        import os
        descriptor, filename = tempfile.mkstemp(prefix="migration-", suffix=".db", dir=directory)
        os.close(descriptor)
        temporary = Path(filename)
        try:
            original = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            copied = sqlite3.connect(temporary)
            try:
                original.backup(copied)
            finally:
                copied.close()
                original.close()
            TechnomancerStore(temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def _percent(value):
    return "unavailable" if value is None else f"{value:.1f}%"
