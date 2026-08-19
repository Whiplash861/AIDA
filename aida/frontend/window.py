from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from aida.frontend._window_base import AIDAWindow as _BaseAIDAWindow
from aida.frontend.internal_orb import (
    OrbTroubleCode,
    OrbVisualState,
)
from aida.frontend.status import AIDAStatus
from aida.frontend.status_orb import AIDAStatusOrb


class AIDAWindow(_BaseAIDAWindow):
    """Primary AIDA window with the embedded live-state orb."""

    _TARGETED_ORB_TEST_SECONDS = 10.0

    def __init__(self) -> None:
        super().__init__()

        header = self.findChild(QFrame, "appHeader")
        if header is None:
            raise RuntimeError("AIDA header was not created")
        header_layout = header.layout()
        if not isinstance(header_layout, QHBoxLayout):
            raise RuntimeError("AIDA header layout is not a horizontal layout")

        self.internal_orb = AIDAStatusOrb(parent=header)
        header_layout.insertWidget(
            1,
            self.internal_orb,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        self.orb_override_indicator = QLabel(header)
        self.orb_override_indicator.setObjectName("orbOverrideIndicator")
        self.orb_override_indicator.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.orb_override_indicator.setMinimumWidth(82)
        self.orb_override_indicator.setStyleSheet(
            """
            QLabel#orbOverrideIndicator {
                color: rgba(201, 232, 255, 225);
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
                padding: 1px 3px;
            }
            """
        )
        self.orb_override_indicator.setVisible(False)
        header_layout.insertWidget(
            2,
            self.orb_override_indicator,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.internal_orb.visual_override_changed.connect(
            self._handle_orb_visual_override
        )
        self.internal_orb.set_status(AIDAStatus.STARTUP)

        self._orb_test_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+O"),
            self,
        )
        self._orb_test_shortcut.activated.connect(self.start_orb_color_test)

        self._orb_targeted_test_shortcuts: list[QShortcut] = []
        for key_sequence, state in (
            ("Ctrl+Shift+1", OrbVisualState.BLUE),
            ("Ctrl+Shift+2", OrbVisualState.GREEN),
            ("Ctrl+Shift+3", OrbVisualState.PURPLE),
            ("Ctrl+Shift+4", OrbVisualState.RED),
        ):
            shortcut = QShortcut(QKeySequence(key_sequence), self)
            shortcut.activated.connect(
                lambda state=state: self.start_orb_targeted_color_test(state)
            )
            self._orb_targeted_test_shortcuts.append(shortcut)

        self._orb_live_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+0"),
            self,
        )
        self._orb_live_shortcut.activated.connect(self.return_orb_to_live)

    def set_status(self, status: AIDAStatus) -> None:
        super().set_status(status)
        orb = getattr(self, "internal_orb", None)
        if isinstance(orb, AIDAStatusOrb):
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

    def set_orb_color_for(
        self,
        state: OrbVisualState | str,
        duration_seconds: float,
        *,
        label: str = "COLOR OVERRIDE",
    ) -> None:
        """Temporarily show one orb color without changing AIDA's live state."""
        self.internal_orb.set_temporary_color(
            state,
            duration_seconds,
            label=label,
        )
        normalized = self.internal_orb.current_visual_state.name
        self.dashboard.add_activity(
            f"ORB temporary color: {normalized} for "
            f"{float(duration_seconds):g}s"
        )

    def clear_orb_color_override(self) -> None:
        """End a targeted color shift early and return to live indication."""
        self.internal_orb.clear_temporary_color()

    def start_orb_targeted_color_test(
        self,
        state: OrbVisualState | str,
    ) -> None:
        """Show one test color for ten seconds, then return to live state."""
        self.internal_orb.start_targeted_color_test(
            state,
            self._TARGETED_ORB_TEST_SECONDS,
        )
        normalized = self.internal_orb.current_visual_state.name
        self.dashboard.add_activity(
            f"ORB targeted color test: {normalized} for "
            f"{self._TARGETED_ORB_TEST_SECONDS:g}s"
        )

    @Slot()
    def return_orb_to_live(self) -> None:
        """Cancel any orb visual test and immediately restore live indication."""
        self.internal_orb.return_to_live_state()
        self.dashboard.add_activity("ORB visual test cleared: LIVE")

    @Slot(bool, str, str)
    def _handle_orb_visual_override(
        self,
        active: bool,
        heading: str,
        state_name: str,
    ) -> None:
        if not active:
            self.orb_override_indicator.clear()
            self.orb_override_indicator.setVisible(False)
            return

        safe_heading = heading.strip().upper() or "VISUAL OVERRIDE"
        safe_state = state_name.strip().upper() or "UNKNOWN"
        self.orb_override_indicator.setText(
            f"{safe_heading}\n────────\n{safe_state}"
        )
        self.orb_override_indicator.setVisible(True)

    @Slot()
    def start_orb_color_test(self) -> None:
        """Run BLUE -> GREEN -> PURPLE -> RED -> current live state."""
        self.internal_orb.start_color_test()
        self.dashboard.add_activity(
            "ORB color test: BLUE > GREEN > PURPLE > RED > LIVE"
        )
