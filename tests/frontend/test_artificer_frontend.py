from __future__ import annotations

import ast
from pathlib import Path

from aida.frontend.artificer_dialog import ArtificerFrontendSnapshot


WINDOW_PATH = Path("aida/frontend/window.py")
WIDGETS_PATH = Path("aida/frontend/widgets.py")
APP_PATH = Path("aida/frontend/app.py")


def test_canonical_header_controls_are_preserved_with_artificer() -> None:
    source = WINDOW_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    for label in (
        'QPushButton("REPORT BUG")',
        'QPushButton("MEMORY")',
        'QPushButton("THREATS")',
        'QPushButton("TASKS")',
        'QPushButton("ARTIFICER")',
        'QCheckBox("AUTONOMY")',
    ):
        assert label in source

    assert "bug_report_requested = Signal()" in source
    assert "memory_requested = Signal()" in source
    assert "threat_center_requested = Signal()" in source
    assert "task_center_requested = Signal()" in source
    assert "artificer_requested = Signal()" in source
    assert "autonomy_toggled = Signal(bool)" in source

    order = [
        source.index("header_layout.addWidget(self.bug_report_button)"),
        source.index("header_layout.addWidget(self.memory_button)"),
        source.index("header_layout.addWidget(self.threat_center_button)"),
        source.index("header_layout.addWidget(self.task_center_button)"),
        source.index("header_layout.addWidget(self.artificer_button)"),
        source.index("header_layout.addLayout(autonomy_layout)"),
        source.index("header_layout.addWidget(self.status_label)"),
    ]
    assert order == sorted(order)


def test_artificer_is_a_peer_dashboard_subsystem() -> None:
    source = WIDGETS_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    assert 'name="MEMORY"' in source
    assert 'name="ARTIFICER"' in source
    assert 'name="TASKS"' in source
    assert source.index('name="MEMORY"') < source.index('name="ARTIFICER"')
    assert source.index('name="ARTIFICER"') < source.index('name="TASKS"')
    assert "def set_artificer_status(" in source


def test_artificer_dialog_lifecycle_is_symmetric() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    assert source.count("window.artificer_requested.connect(") == 1
    assert source.count("window.artificer_requested.disconnect(") == 1
    assert "artificer_dialog = ArtificerCenterDialog(parent=window)" in source
    assert "artificer_dialog.close()" in source


def test_frontend_snapshot_is_explicitly_non_operational() -> None:
    snapshot = ArtificerFrontendSnapshot.capture()

    assert snapshot.interface_state == "READY"
    assert snapshot.engine_state == "PENDING INTEGRATION"
    assert snapshot.authority == "READ-ONLY FRONTEND"
    assert snapshot.telemetry == "LOCAL ONLY"
    assert snapshot.automatic_maintenance == "DISABLED"
    assert snapshot.operating_system
    assert snapshot.python_version
