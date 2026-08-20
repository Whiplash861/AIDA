from __future__ import annotations

import unittest
from pathlib import Path

from aida.frontend.command_router import CommandRouter, CommandType


class TechnomancerFrontendRegressionTests(unittest.TestCase):
    def test_canonical_artificer_controls_remain_present(self) -> None:
        source = Path("aida/frontend/_window_base.py").read_text(encoding="utf-8")
        self.assertIn('self.artificer_button = self._header_button(', source)
        self.assertIn(
            'self.artificer_button.clicked.connect(self.artificer_requested.emit)',
            source,
        )

    def test_dashboard_keeps_artificer_and_adds_technomancer(self) -> None:
        source = Path("aida/frontend/widgets.py").read_text(encoding="utf-8")
        artificer = '("ARTIFICER", self.artificer_value)'
        technomancer = '("TECHNOMANCER", self.technomancer_value)'
        self.assertIn(artificer, source)
        self.assertIn(technomancer, source)
        self.assertLess(source.index(artificer), source.index(technomancer))
        self.assertNotIn("HeaderEngineOrb", source)
        self.assertNotIn("_install_header_orb", source)

    def test_refined_header_orb_architecture_is_restored(self) -> None:
        source = Path("aida/frontend/window.py").read_text(encoding="utf-8")
        self.assertIn("class _HeaderStatusOrb(AIDAStatusOrb)", source)
        self.assertIn("self._orb_diameter = 80", source)
        self.assertIn("self.setFixedSize(96, 96)", source)
        self.assertIn("CURRENT STATUS", source)
        self.assertIn('QKeySequence("Ctrl+Shift+5")', source)
        self.assertFalse(Path("aida/frontend/header_orb.py").exists())

    def test_technomancer_cyan_is_layered_over_refined_orb(self) -> None:
        source = Path("aida/frontend/engine_status_orb.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("TECHNOMANCER_COLOR", source)
        self.assertIn('QColor("#7CF5FF")', source)
        self.assertIn('return "TECHNOMANCER"', source)
        self.assertIn("_BaseStatusOrb", source)
        self.assertIn('"TECHNOMANCER-FAILURE"', source)

    def test_external_orb_uses_same_engine_aware_status_orb(self) -> None:
        overlay = Path("aida/frontend/live_overlay.py").read_text(encoding="utf-8")
        app = Path("aida/frontend/app.py").read_text(encoding="utf-8")
        self.assertIn(
            "from aida.frontend.engine_status_orb import AIDAStatusOrb",
            overlay,
        )
        self.assertIn("class AIDALiveOverlay(AIDAStatusOrb)", overlay)
        self.assertIn("overlay = AIDALiveOverlay()", app)
        self.assertIn("overlay.report_task_started(task_name)", app)
        self.assertIn("overlay.set_artificer_status", app)

    def test_accepted_red_failure_profiles_remain_intact(self) -> None:
        source = Path("aida/frontend/status_orb.py").read_text(encoding="utf-8")
        self.assertIn("_CORE_PROFILE_MIN_INTERVAL = 3.0", source)
        self.assertIn("_CORE_PROFILE_MAX_INTERVAL = 5.0", source)
        self.assertIn("_CORE_PROFILE_WEIGHTS = (40, 40, 20)", source)
        self.assertIn('(\"interference\", 3.0)', source)

    def test_technomancer_fast_paths_use_canonical_intent_router(self) -> None:
        router = CommandRouter()
        cases = {
            "Technomancer health": CommandType.TECHNOMANCER_HEALTH,
            "Technomancer hardware": CommandType.TECHNOMANCER_HARDWARE,
            "Technomancer upgrades": CommandType.TECHNOMANCER_UPGRADES,
            "Technomancer advisories": CommandType.TECHNOMANCER_ADVISORIES,
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                routed = router.route(phrase)
                self.assertIsNotNone(routed)
                assert routed is not None
                self.assertEqual(routed.command_type, expected)
                self.assertTrue(routed.local_only)


if __name__ == "__main__":
    unittest.main()
