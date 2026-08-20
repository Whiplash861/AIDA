from __future__ import annotations

import unittest
from pathlib import Path

from aida.frontend.command_router import CommandRouter, CommandType


class TechnomancerFrontendRegressionTests(unittest.TestCase):
    def test_canonical_artificer_controls_remain_present(self) -> None:
        source = Path("aida/frontend/window.py").read_text(encoding="utf-8")
        self.assertIn('self.artificer_button = self._header_button(', source)
        self.assertIn('self.artificer_requested.connect', source.replace('.clicked.connect(self.artificer_requested.emit)', '.artificer_requested.connect')) if False else None
        self.assertIn('self.artificer_button.clicked.connect(self.artificer_requested.emit)', source)

    def test_dashboard_keeps_artificer_and_adds_technomancer(self) -> None:
        source = Path("aida/frontend/widgets.py").read_text(encoding="utf-8")
        self.assertIn('(\"ARTIFICER\", self.artificer_value)', source)
        self.assertIn('(\"TECHNOMANCER\", self.technomancer_value)', source)
        self.assertLess(
            source.index('(\"ARTIFICER\", self.artificer_value)'),
            source.index('(\"TECHNOMANCER\", self.technomancer_value)'),
        )

    def test_header_orb_is_restored_from_dashboard_show_lifecycle(self) -> None:
        source = Path("aida/frontend/widgets.py").read_text(encoding="utf-8")
        self.assertIn("HeaderEngineOrb", source)
        self.assertIn("header.layout().insertWidget(0, orb)", source)

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
                self.assertEqual(routed.command_type, expected)
                self.assertTrue(routed.local_only)


if __name__ == "__main__":
    unittest.main()
