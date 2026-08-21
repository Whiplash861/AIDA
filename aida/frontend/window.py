from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from aida.frontend._window_base import AIDAWindow as _BaseAIDAWindow
from aida.frontend.status_orb import AIDAStatusOrb
from aida.frontend.internal_orb import (
    OrbTroubleCode,
    OrbVisualState,
)
from aida.frontend.status import AIDAStatus


class _HeaderStatusOrb(AIDAStatusOrb):
    """Header-sized live orb with a slightly fuller visual footprint."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

        # Keep the existing 96x96 transparent safety canvas, but reclaim some
        # of its unused center space for the orb itself. An 80px source field
        # still leaves enough room for the state-transition pulse, RED glitch
        # displacement, and ambient glow to finish without clipping.
        self._orb_diameter = 80
        self._internal_scale = 76.0 / 120.0
        self._canvas_margin = 8
        self.setFixedSize(96, 96)


class AIDAWindow(_BaseAIDAWindow):
    """Primary AIDA window with the embedded live-state orb."""

    _TARGETED_ORB_TEST_SECONDS = 10.0

    _HEADER_MODULE_STYLE = """
        QFrame#headerControlModule,
        QFrame#headerStateModule {
            background:
                qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 rgba(12, 35, 49, 218),
                    stop: 1 rgba(5, 21, 31, 232)
                );
            border: 1px solid rgba(91, 207, 240, 72);
            border-radius: 12px;
        }
        QFrame#headerControlModule:hover,
        QFrame#headerStateModule:hover {
            border-color: rgba(91, 220, 255, 120);
        }
        QLabel#headerControlCaption {
            color: #718c9d;
            font-family: "Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI";
            font-size: 8px;
            font-weight: 650;
            letter-spacing: 2px;
        }
    """

    _AUTONOMY_STYLE = """
        QCheckBox#autonomySwitch {
            spacing: 0;
            padding: 0;
        }
        QCheckBox#autonomySwitch::indicator {
            width: 28px;
            height: 14px;
            border: 1px solid rgba(139, 168, 186, 105);
            border-radius: 7px;
            background: rgba(23, 38, 48, 235);
        }
        QCheckBox#autonomySwitch::indicator:hover {
            border-color: rgba(105, 220, 255, 175);
        }
        QCheckBox#autonomySwitch::indicator:checked {
            background:
                qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(25, 155, 104, 240),
                    stop: 1 rgba(53, 231, 166, 245)
                );
            border-color: rgba(102, 246, 190, 210);
        }
        QLabel#autonomyStateLabel {
            color: #91a5b3;
            font-family: "Cascadia Mono", "Consolas";
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1px;
        }
        QLabel#autonomyStateLabel[state="enabled"] { color: #59f0b3; }
        QLabel#autonomyStateLabel[state="disabled"] { color: #91a5b3; }
        QLabel#autonomyStateLabel[state="updating"] { color: #68d8ff; }
        QLabel#autonomyStateLabel[state="locked"] { color: #ff9b79; }
    """

    def __init__(self) -> None:
        super().__init__()

        header = self.findChild(QFrame, "appHeader")
        if header is None:
            raise RuntimeError("AIDA header was not created")
        header_layout = header.layout()
        if not isinstance(header_layout, QHBoxLayout):
            raise RuntimeError("AIDA header layout is not a horizontal layout")

        # The orb uses a larger transparent render canvas so pulse/glitch pixels
        # can travel beyond the visible ring without being clipped. Tightening
        # only the vertical header padding keeps the overall header close to its
        # previous height while preserving a small gap to the frame itself.
        header_layout.setContentsMargins(14, 1, 14, 1)
        header_layout.setSpacing(6)

        self.internal_orb = _HeaderStatusOrb(parent=header)
        header_layout.insertWidget(
            1,
            self.internal_orb,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        self._orb_visual_override_active = False
        self.orb_status_indicator = QLabel(header)
        self.orb_status_indicator.setObjectName("orbStatusIndicator")
        self.orb_status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.orb_status_indicator.setFixedWidth(92)
        self.orb_status_indicator.setStyleSheet(
            """
            QLabel#orbStatusIndicator {
                color: rgba(201, 232, 255, 225);
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
                padding: 1px 3px;
            }
            """
        )
        header_layout.insertWidget(
            2,
            self.orb_status_indicator,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.internal_orb.visual_override_changed.connect(
            self._handle_orb_visual_override
        )
        self.internal_orb.set_status(AIDAStatus.STARTUP)
        self._refresh_orb_status_indicator()

        self._modernize_header_controls(header, header_layout)
        self._protect_dashboard_status_values()

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
            ("Ctrl+Shift+5", OrbVisualState.CYAN),
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

    def _modernize_header_controls(
        self,
        header: QFrame,
        header_layout: QHBoxLayout,
    ) -> None:
        """Build one compact autonomy module and retire redundant header state UI."""
        # The base window originally adds AUTONOMY as a nested layout and the
        # legacy AIDA status as a separate widget. Remove those layout entries
        # explicitly before reusing their widgets; simply reparenting a widget
        # can leave its old QLayoutItem behind and consume space as a ghost.
        for index in range(header_layout.count() - 1, -1, -1):
            item = header_layout.itemAt(index)
            if item.widget() is self.status_label:
                header_layout.takeAt(index)
                continue

            nested = item.layout()
            if nested is None:
                continue
            contains_autonomy = any(
                nested.itemAt(child_index).widget()
                in {self.autonomy_switch, self.autonomy_state_label}
                for child_index in range(nested.count())
            )
            if contains_autonomy:
                header_layout.takeAt(index)

        # CURRENT STATUS beside the orb supersedes the old CORE STATE tile.
        # Keep the legacy label alive for existing status-update code, but do
        # not allocate any header geometry to it.
        self.status_label.hide()
        self.status_label.setMinimumWidth(0)
        self.status_label.setMaximumWidth(0)

        # Protect AIDA's identity copy from being squeezed by action buttons.
        self.app_title.setMinimumWidth(96)
        self.app_subtitle.setMinimumWidth(188)
        self.app_title.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Preferred,
        )
        self.app_subtitle.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Preferred,
        )

        self.autonomy_panel = QFrame(header)
        self.autonomy_panel.setObjectName("headerControlModule")
        self.autonomy_panel.setFixedSize(136, 50)
        self.autonomy_panel.setStyleSheet(
            self._HEADER_MODULE_STYLE + self._AUTONOMY_STYLE
        )

        autonomy_caption = QLabel("AUTONOMY", self.autonomy_panel)
        autonomy_caption.setObjectName("headerControlCaption")

        self.autonomy_switch.setParent(self.autonomy_panel)
        self.autonomy_switch.setText("")
        self.autonomy_switch.setFixedSize(32, 18)
        self.autonomy_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autonomy_switch.setToolTip("Enable or disable Controlled Autonomy.")

        self.autonomy_state_label.setParent(self.autonomy_panel)
        self.autonomy_state_label.setMinimumWidth(72)
        self.autonomy_state_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.autonomy_state_label.setProperty("state", "disabled")
        if self.autonomy_state_label.text().strip().upper() == "MANUAL":
            self.autonomy_state_label.setText("DISABLED")

        autonomy_value_layout = QHBoxLayout()
        autonomy_value_layout.setContentsMargins(0, 0, 0, 0)
        autonomy_value_layout.setSpacing(6)
        autonomy_value_layout.addWidget(self.autonomy_switch)
        autonomy_value_layout.addWidget(self.autonomy_state_label, stretch=1)

        autonomy_layout = QVBoxLayout(self.autonomy_panel)
        autonomy_layout.setContentsMargins(9, 5, 9, 5)
        autonomy_layout.setSpacing(1)
        autonomy_layout.addWidget(autonomy_caption)
        autonomy_layout.addLayout(autonomy_value_layout)

        header_layout.addWidget(
            self.autonomy_panel,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

    def _protect_dashboard_status_values(self) -> None:
        """Keep dashboard values readable instead of allowing text clipping."""
        self.dashboard.setMinimumWidth(258)
        self.dashboard.setMaximumWidth(400)
        for label in self.dashboard.findChildren(QLabel, "statusValue"):
            label.setMinimumWidth(104)
        self.workspace_splitter.setSizes([268, 882])

    def set_autonomy_status(self, text: str) -> None:
        """Present autonomy as ENABLED / DISABLED while preserving model semantics."""
        normalized = text.strip().upper() or "DISABLED"
        if normalized == "MANUAL":
            normalized = "DISABLED"
        super().set_autonomy_status(normalized)
        if normalized == "ENABLED":
            state = "enabled"
        elif normalized == "LOCKED":
            state = "locked"
        elif normalized == "UPDATING":
            state = "updating"
        else:
            state = "disabled"
        self.autonomy_state_label.setProperty("state", state)
        style = self.autonomy_state_label.style()
        style.unpolish(self.autonomy_state_label)
        style.polish(self.autonomy_state_label)
        self.autonomy_state_label.update()

    def _set_orb_status_text(self, heading: str, value: str) -> None:
        self.orb_status_indicator.setText(
            f"{heading.strip().upper()}\n────────\n{value.strip().upper()}"
        )

    def _refresh_orb_status_indicator(self) -> None:
        if self._orb_visual_override_active:
            return
        self._set_orb_status_text(
            "CURRENT STATUS",
            self.internal_orb.current_live_status_text(),
        )

    def set_status(self, status: AIDAStatus) -> None:
        super().set_status(status)
        orb = getattr(self, "internal_orb", None)
        if isinstance(orb, AIDAStatusOrb):
            orb.set_status(status)
            self._refresh_orb_status_indicator()

    def set_artificer_status(self, text: str) -> None:
        super().set_artificer_status(text)
        self.internal_orb.set_artificer_status(text)
        self._refresh_orb_status_indicator()

    def set_technomancer_status(self, text: str) -> None:
        self.dashboard.set_technomancer_status(text)
        self.internal_orb.set_technomancer_status(text)
        self._refresh_orb_status_indicator()

    def set_active_task_count(self, count: int) -> None:
        super().set_active_task_count(count)
        self.internal_orb.set_active_task_count(count)
        self._refresh_orb_status_indicator()

    def report_task_started(self, task_name: str) -> None:
        super().report_task_started(task_name)
        if task_name.strip().lower().startswith("technomancer"):
            self.dashboard.set_technomancer_status("RUNNING")
        self.internal_orb.report_task_started(task_name)
        self._refresh_orb_status_indicator()

    def report_task_finished(self, task_name: str) -> None:
        super().report_task_finished(task_name)
        if task_name.strip().lower().startswith("technomancer"):
            self.dashboard.set_technomancer_status("IDLE")
        self.internal_orb.report_task_finished(task_name)
        self._refresh_orb_status_indicator()

    def report_task_failed(self, task_name: str, error_message: str) -> None:
        super().report_task_failed(task_name, error_message)
        if task_name.strip().lower().startswith("technomancer"):
            self.dashboard.set_technomancer_status("ERROR")
        self.internal_orb.report_task_failed(task_name)
        self._refresh_orb_status_indicator()

    def set_backend_connected(self, connected: bool) -> None:
        """Update the orb's structured backend-connectivity trouble state."""
        self.internal_orb.set_backend_connected(connected)
        self._refresh_orb_status_indicator()

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
        self._refresh_orb_status_indicator()

    def clear_orb_trouble_code(self, code: str | OrbTroubleCode) -> None:
        self.internal_orb.clear_trouble_code(code)
        self._refresh_orb_status_indicator()

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
    def start_orb_cyan_test(self) -> None:
        """Show Technomancer cyan for ten seconds, then return to live state."""
        self.start_orb_targeted_color_test(OrbVisualState.CYAN)

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
        self._orb_visual_override_active = active
        if not active:
            self._refresh_orb_status_indicator()
            return

        safe_heading = heading.strip().upper() or "VISUAL OVERRIDE"
        safe_state = state_name.strip().upper() or "UNKNOWN"
        self._set_orb_status_text(safe_heading, safe_state)

    @Slot()
    def start_orb_color_test(self) -> None:
        """Run BLUE -> GREEN -> VIOLET -> CYAN -> RED -> current live state."""
        self.internal_orb.start_color_test()
        self.dashboard.add_activity(
            "ORB color test: BLUE > GREEN > VIOLET > CYAN > RED > LIVE"
        )
