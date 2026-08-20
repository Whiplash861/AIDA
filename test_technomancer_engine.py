from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from aida.engines import EngineCoordinator, EngineDescriptor, EngineRequest, EngineResponse
from aida.technomancer.analyzer import analyze
from aida.technomancer.models import HardwareInventory, TelemetrySample
from aida.technomancer.permissions import PermissionStore, TECHNOMANCER_BACKGROUND_SCOPE
from aida.technomancer.storage import TechnomancerStore


class DummyEngine:
    def __init__(self, key: str) -> None:
        self.descriptor = EngineDescriptor(key=key, name=key.title(), color="#fff", domain="test")

    def handle(self, request: EngineRequest) -> EngineResponse:
        return EngineResponse(self.descriptor.key, f"{self.descriptor.key}:{request.intent}")


class TechnomancerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = TechnomancerStore(root / "technomancer.db")
        self.permissions = PermissionStore(root / "permissions.json")
        self.machine = "test-machine"
        self.inventory = HardwareInventory(
            machine_id=self.machine,
            system_manufacturer="Test",
            system_model="Rig",
            board_manufacturer="BoardCo",
            board_model="X1",
            cpu_model="CPU",
            total_ram_gb=16.0,
            ram_generation="DDR5",
            ram_speed_mhz=5600,
            ram_slots_total=4,
            ram_slots_used=2,
            max_ram_gb=128,
        )
        self.store.record_inventory(self.inventory)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def sample(self, timestamp: float, **overrides) -> TelemetrySample:
        data = dict(
            timestamp=timestamp,
            machine_id=self.machine,
            cpu_percent=25.0,
            memory_percent=45.0,
            swap_percent=0.0,
            disk_percent=55.0,
            disk_free_gb=300.0,
            process_count=100,
            context_level="basic",
        )
        data.update(overrides)
        return TelemetrySample(**data)

    def test_background_requires_autonomy_and_scope(self) -> None:
        self.assertFalse(self.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE))
        self.permissions.set_scope(TECHNOMANCER_BACKGROUND_SCOPE, True)
        self.assertFalse(self.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE))
        self.permissions.set_autonomy(True)
        self.assertTrue(self.permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE))

    def test_five_minute_cadence_can_mature_multi_day_condition(self) -> None:
        now = time.time()
        start = now - 4 * 86400
        for i in range(4 * 24 * 12):
            ts = start + i * 300
            self.store.record_sample(self.sample(ts, memory_percent=91.0, swap_percent=25.0))
        items = analyze(self.store, self.inventory, now_timestamp=now)
        memory = [item for item in items if item.advisory_id == "health.memory_pressure"]
        self.assertEqual(len(memory), 1)
        self.assertIn(memory[0].maturity, {"persistent", "impacting", "degrading", "actionable"})
        self.assertGreaterEqual(memory[0].observation_days, 3.9)

    def test_longitudinal_ram_pressure_can_produce_upgrade_advisory(self) -> None:
        now = time.time()
        start = now - 35 * 86400
        for i in range(35 * 24):
            ts = start + i * 3600
            self.store.record_sample(self.sample(ts, memory_percent=92.0, swap_percent=35.0, context_level="process", workload_context="editor, browser"))
        items = analyze(self.store, self.inventory, now_timestamp=now)
        upgrade = [item for item in items if item.advisory_id == "upgrade.memory.capacity"]
        self.assertEqual(len(upgrade), 1)
        self.assertIn("32 GB DDR5", upgrade[0].recommendation or "")
        self.assertGreater(upgrade[0].confidence, 0.8)

    def test_basic_cpu_telemetry_does_not_become_purchase_advice(self) -> None:
        now = time.time()
        start = now - 35 * 86400
        for i in range(35 * 24):
            self.store.record_sample(self.sample(start + i * 3600, cpu_percent=98.0, context_level="basic"))
        items = analyze(self.store, self.inventory, now_timestamp=now)
        self.assertTrue(any(item.advisory_id == "health.cpu_saturation" for item in items))
        self.assertFalse(any(item.advisory_id == "upgrade.cpu.capacity" for item in items))

    def test_power_events_do_not_claim_psu_failure(self) -> None:
        now = time.time()
        start = now - 4 * 86400
        for i in range(96):
            self.store.record_sample(self.sample(start + i * 3600, unexpected_shutdowns_30d=4))
        items = analyze(self.store, self.inventory, now_timestamp=now)
        power = next(item for item in items if item.advisory_id == "health.power_stability")
        self.assertIn("one possible cause", power.message)
        self.assertIn("does not identify the PSU", power.message)

    def test_hardware_change_invalidates_old_advisories(self) -> None:
        now = time.time()
        for i in range(100):
            self.store.record_sample(self.sample(now - 4 * 86400 + i * 3600, memory_percent=95.0))
        analyze(self.store, self.inventory, now_timestamp=now)
        self.assertTrue(self.store.active_advisories())
        changed = HardwareInventory(**{**self.inventory.to_dict(), "captured_at": "later", "total_ram_gb": 32.0})
        self.assertTrue(self.store.record_inventory(changed))
        self.assertEqual(self.store.active_advisories(), [])

    def test_engine_handoff_returns_to_previous_engine(self) -> None:
        coordinator = EngineCoordinator()
        coordinator.register(DummyEngine("technomancer"))
        coordinator.register(DummyEngine("artificer"))
        coordinator.activate("technomancer")
        response = coordinator.handoff("artificer", EngineRequest(intent="audit"))
        self.assertEqual(response.engine_key, "artificer")
        self.assertEqual(coordinator.foreground_engine, "technomancer")


if __name__ == "__main__":
    unittest.main()
