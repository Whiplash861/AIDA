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
from aida.technomancer.renderer import render_health, render_upgrades, render_inventory, render_advisories


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
        samples = self.store.samples_since(inventory.machine_id, time.time() - 3600)
        sample = samples[-1] if samples else None
        days = self.store.observation_days(inventory.machine_id, sample.timestamp if sample else time.time())
        return render_health(inventory, sample, advisories, days)

    def upgrade_report(self) -> str:
        inventory, advisories = self._ensure_current_data()
        days = self.store.observation_days(inventory.machine_id, time.time())
        return render_upgrades(inventory, advisories, days)

    def inventory_report(self) -> str:
        inventory = collect_hardware_inventory()
        self.store.record_inventory(inventory)
        return render_inventory(inventory)

    def advisory_report(self) -> str:
        return render_advisories(self.store.active_advisories())

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
                messages.append(render_advisories([item], title="Technomancer advisory"))
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
