from __future__ import annotations

import ast
from pathlib import Path


BASE_WINDOW_PATH = Path("aida/frontend/_window_base.py")
WINDOW_PATH = Path("aida/frontend/window.py")
VOICE_PATH = Path("aida/interaction/voice_capture.py")
BRIDGE_PATH = Path("aida/interaction/qt_bridge.py")


def test_canonical_window_includes_hardened_multimodal_controls() -> None:
    source = BASE_WINDOW_PATH.read_text(encoding="utf-8")
    ast.parse(source)
    for token in (
        '"MIC"',
        '"IMAGE"',
        '"PASTE"',
        '"CLEAR"',
        'QKeySequence("Ctrl+Space")',
        "def _attach_clipboard_image(",
        "def _clear_evidence(",
        "def _set_drag_highlight(",
    ):
        assert token in source


def test_modern_header_order_remains_canonical() -> None:
    source = WINDOW_PATH.read_text(encoding="utf-8")
    ast.parse(source)

    order = [
        source.index("self.orb_status_panel,"),
        source.index("self.autonomy_panel,"),
        source.index("self.bug_report_button,"),
        source.index("self.memory_button,"),
        source.index("self.threat_center_button,"),
        source.index("self.task_center_button,"),
        source.index("self.artificer_button,"),
    ]
    assert order == sorted(order)
    assert "header_layout.insertStretch(insert_at, 1)" in source


def test_voice_capture_uses_unique_disposable_files() -> None:
    source = VOICE_PATH.read_text(encoding="utf-8")
    ast.parse(source)
    assert "uuid.uuid4().hex" in source
    assert "def discard(" in source
    assert "max_duration_seconds" in source


def test_voice_bridge_exposes_cancel_and_processing_state() -> None:
    source = BRIDGE_PATH.read_text(encoding="utf-8")
    ast.parse(source)
    assert "processing_changed = Signal(bool)" in source
    assert "def cancel(" in source
    assert "def is_processing(" in source
    assert "self._capture.discard(self._audio_path)" in source
