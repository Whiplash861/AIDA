from __future__ import annotations

import ast
from pathlib import Path


WINDOW_PATH = Path("aida/frontend/window.py")
WIDGETS_PATH = Path("aida/frontend/widgets.py")
APP_PATH = Path("aida/frontend/app.py")
DIALOG_PATH = Path("aida/frontend/artificer_dialog.py")


def test_canonical_header_controls_are_preserved_with_artificer() -> None:
    source = WINDOW_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    for label in (
        '"REPORT BUG"',
        '"MEMORY"',
        '"THREATS"',
        '"TASKS"',
        '"ARTIFICER"',
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
        source.index("self.bug_report_button,"),
        source.index("self.memory_button,"),
        source.index("self.threat_center_button,"),
        source.index("self.task_center_button,"),
        source.index("self.artificer_button,"),
        source.index("header_layout.addLayout(autonomy_layout)"),
        source.index("header_layout.addWidget(self.status_label)"),
    ]
    assert order == sorted(order)


def test_artificer_remains_a_peer_dashboard_subsystem() -> None:
    source = WIDGETS_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    memory_row = '("MEMORY", self.memory_value)'
    artificer_row = '("ARTIFICER", self.artificer_value)'
    perception_row = '("PERCEPTION", self.perception_value)'
    microphone_row = '("MICROPHONE", self.microphone_value)'
    tasks_row = '("TASKS", self.tasks_value)'

    for row in (memory_row, artificer_row, perception_row, microphone_row, tasks_row):
        assert row in source

    order = [
        source.index(memory_row),
        source.index(artificer_row),
        source.index(perception_row),
        source.index(microphone_row),
        source.index(tasks_row),
    ]
    assert order == sorted(order)
    assert "def set_artificer_status(" in source


def test_artificer_dialog_lifecycle_is_symmetric_and_engine_backed() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    assert source.count("window.artificer_requested.connect(") == 1
    assert source.count("window.artificer_requested.disconnect(") == 1
    assert "artificer_dialog = ArtificerCenterDialog(artificer_engine" in source
    assert "artificer_dialog.close()" in source
    assert "artificer_engine.start(run_startup_review=False)" in source
    assert "artificer_engine.stop()" in source


def test_artificer_center_exposes_live_review_and_export_controls() -> None:
    source = DIALOG_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    assert "review_requested = Signal()" in source
    assert "export_requested = Signal()" in source
    assert 'QPushButton("Run Review")' in source
    assert 'QPushButton("Export Report")' in source
    assert "self.engine.snapshot()" in source
    assert "apply_snapshot" in source
    assert "snapshot.open_findings" in source
    assert "snapshot.pending_proposals" in source
    assert "Automatic maintenance: DISABLED" in source
