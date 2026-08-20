from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QLabel

from aida.frontend.command_manager import CommandManager
from aida.frontend.engine_overlay import EngineAwareOverlay
from aida.frontend.window import AIDAWindow
from aida.technomancer.models import TECHNOMANCER_COLOR


class TechnomancerFrontendBridge:
    """Keeps Technomancer visible in the Frontend without making it a separate app."""

    def __init__(self, window: AIDAWindow, overlay: EngineAwareOverlay, command_manager: CommandManager) -> None:
        self.window = window
        self.overlay = overlay
        self.command_manager = command_manager

        self.label = QLabel("TECHNOMANCER • IDLE")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(
            "QLabel { color: #00E5FF; background: rgba(5, 35, 44, 205); "
            "border: 1px solid rgba(0, 229, 255, 115); border-radius: 10px; "
            "padding: 7px 10px; font-family: 'Cascadia Mono','Consolas'; "
            "font-size: 8pt; font-weight: 700; letter-spacing: 1px; }"
        )

        dashboard_layout = self.window.dashboard.layout()
        if dashboard_layout is not None:
            dashboard_layout.insertWidget(1, self.label)

        self.command_manager.command_status_changed.connect(self._on_command_status)

    @Slot(str, str)
    def _on_command_status(self, category: str, status: str) -> None:
        if category != "TECHNOMANCER":
            return
        normalized = status.strip().upper()
        self.label.setText(f"TECHNOMANCER • {normalized}")
        if normalized in {"RUNNING", "WORKING", "ANALYZING"}:
            self.overlay.set_engine("technomancer", TECHNOMANCER_COLOR)
        elif normalized == "IDLE":
            self.overlay.set_engine(None)

    def shutdown(self) -> None:
        try:
            self.command_manager.command_status_changed.disconnect(self._on_command_status)
        except RuntimeError:
            pass
        self.overlay.set_engine(None)
