from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout

from aida.frontend._window_base import AIDAWindow as _BaseAIDAWindow
from aida.frontend.internal_orb import (
    AIDAInternalOrb,
    OrbTroubleCode,
    OrbVisualState,
)
from aida.frontend.status import AIDAStatus


class AIDAWindow(_BaseAIDAWindow):
    """Primary AIDA window with the embedded live-state orb."""

    def __init__(self) -> None:
        super().__init__()

        header = self.findChild(QFrame, "appHeader")
        if header is None:
            raise RuntimeError("AIDA header was not created")
        header_layout = header.layout()
        if not isinstance(header_layout, QHBoxLayout):
            raise RuntimeError("AIDA header layout is not a horizontal layout")

        self.internal_orb = AIDAInternalOrb(parent=header)
        header_layout.insertWidget(
            1,
            self.internal_orb,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.internal_orb.set_status(AIDAStatus.STARTUP)

        self._orb_test_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+O"),
            self,
        )
        self._orb_test_shortcut.activated.connect(self.start_orb_color_test)

    def set_status(self, status: AIDAStatus) -> None:
        super().set_status(status)
        orb = getattr(self, "internal_orb", None)
        if isinstance(orb, AIDAInternalOrb):
            orb.set_status(status)

    def set_artificer_status(self, text: str) -> None:
        super().set_artificer_status(text)
        self.internal_orb.set_artificer_status(text)

    def set_active_task_count(self, count: int) -> None:
        super().set_active_task_count(count)
        self.internal_orb.set_active_task_count(count)

    def report_task_started(self, task_name: str) -> None:
        super().report_task_started(task_name)
        self.internal_orb.report_task_started(task_name)

    def report_task_finished(self, task_name: str) -> None:
        super().report_task_finished(task_name)
        self.internal_orb.report_task_finished(task_name)

    def report_task_failed(self, task_name: str, error_message: str) -> None:
        super().report_task_failed(task_name, error_message)
        self.internal_orb.report_task_failed(task_name)

    def set_backend_connected(self, connected: bool) -> None:
        """Update the orb's structured backend-connectivity trouble state."""
        self.internal_orb.set_backend_connected(connected)

    def set_orb_trouble_code(
        self,
        code: str | OrbTroubleCode,
        *,
        active: bool = True,
        state: OrbVisualState | None = None,
    ) -> None:
        """Set or clear a structured trouble code consumed by the live orb."""
        self.internal_orb.set_trouble_code(
            code,
            active=active,
            state=state,
        )

    def clear_orb_trouble_code(self, code: str | OrbTroubleCode) -> None:
        self.internal_orb.clear_trouble_code(code)

    @Slot()
    def start_orb_color_test(self) -> None:
        """Run BLUE -> GREEN -> PURPLE -> RED -> current live state."""
        self.internal_orb.start_color_test()
        self.dashboard.add_activity(
            "ORB color test: BLUE > GREEN > PURPLE > RED > LIVE"
        )
