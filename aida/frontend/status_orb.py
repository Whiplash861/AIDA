from __future__ import annotations

from PySide6.QtCore import QPointF, QTimer, Signal
from PySide6.QtGui import QColor

from aida.frontend.internal_orb import (
    AIDAInternalOrb,
    OrbTroubleCode,
    OrbVisualState,
    _ACTIVE_ARTIFICER_STATES,
    _PALETTES,
)


_VIOLET_PALETTE = (
    QColor("#B13CFF"),
    QColor("#D985FF"),
    QColor("#FFF3FF"),
    QColor("#2A073D"),
    QColor("#0D0215"),
)


class AIDAStatusOrb(AIDAInternalOrb):
    """Header orb with temporary visual overrides and explicit test context.

    Live AIDA/Artificer/trouble state continues updating while a visual override
    is active. When the override ends, the orb resolves the current live state
    instead of restoring a stale snapshot.
    """

    visual_override_changed = Signal(bool, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

        # Keep the header footprint at 70x70 while allowing the rendered orb to
        # fill more of the available vertical space without touching the frame.
        self._orb_diameter = 66
        self._internal_scale = 66.0 / 120.0
        self._canvas_margin = 2
        self.setFixedSize(70, 70)

        self._temporary_override_state: OrbVisualState | None = None
        self._temporary_override_timer = QTimer(self)
        self._temporary_override_timer.setSingleShot(True)
        self._temporary_override_timer.timeout.connect(
            self._finish_temporary_override
        )

    @staticmethod
    def _coerce_visual_state(
        state: OrbVisualState | str,
    ) -> OrbVisualState:
        if isinstance(state, OrbVisualState):
            return state
        normalized = str(state).strip().lower()
        try:
            return OrbVisualState(normalized)
        except ValueError as exc:
            allowed = ", ".join(item.name for item in OrbVisualState)
            raise ValueError(
                f"unknown orb color {state!r}; expected one of: {allowed}"
            ) from exc

    @staticmethod
    def _display_name(state: OrbVisualState) -> str:
        return "VIOLET" if state is OrbVisualState.PURPLE else state.name

    @staticmethod
    def _state_palette(
        state: OrbVisualState,
    ) -> tuple[QColor, QColor, QColor, QColor, QColor]:
        if state is OrbVisualState.PURPLE:
            return _VIOLET_PALETTE
        return _PALETTES[state]

    def current_live_status_text(self) -> str:
        """Return an accessible semantic label for AIDA's real live state."""
        if OrbTroubleCode.BACKEND_DISCONNECTED.value in self._trouble_codes:
            return "DISCONNECTED"
        if self._trouble_codes or self._live_status.name == "ERROR":
            return "SYSTEM FAULT"
        if self._live_status.name == "SHUTDOWN":
            return "OFFLINE"
        if (
            self._active_artificer_tasks
            or self._artificer_status in _ACTIVE_ARTIFICER_STATES
        ):
            return "ARTIFICER"
        if self._live_status.name == "WARNING":
            return "WARNING"
        if self._live_status.name == "STARTUP":
            return "STARTING"
        if self._live_status.name == "LISTENING":
            return "LISTENING"
        if self._live_status.name == "ANALYZING":
            return "ANALYZING"
        if self._live_status.name == "SPEAKING":
            return "SPEAKING"
        if self._active_task_count > 0:
            return "WORKING"
        return "STANDBY"

    def _palette_for_layer(
        self,
        layer: str,
    ) -> tuple[QColor, QColor, QColor, QColor, QColor]:
        target = self._state_palette(self._display_state)
        if self._transition_from_state is None:
            return (
                QColor(target[0]),
                QColor(target[1]),
                QColor(target[2]),
                QColor(target[3]),
                QColor(target[4]),
            )

        source = self._state_palette(self._transition_from_state)
        progress = self._layer_progress(layer)
        mixed = tuple(
            self._mix_color(first, second, progress)
            for first, second in zip(source, target, strict=True)
        )
        return mixed[0], mixed[1], mixed[2], mixed[3], mixed[4]

    def set_temporary_color(
        self,
        state: OrbVisualState | str,
        duration_seconds: float,
        *,
        label: str = "COLOR OVERRIDE",
    ) -> None:
        """Display one requested color temporarily, then return to live state."""
        duration = float(duration_seconds)
        if duration <= 0.0:
            raise ValueError("duration_seconds must be greater than zero")

        target = self._coerce_visual_state(state)
        self._test_timer.stop()
        self._test_active = False
        self._cancel_temporary_override(return_to_live=False, announce=False)

        self._temporary_override_state = target
        self._set_display_state(target)
        heading = label.strip().upper() or "COLOR OVERRIDE"
        self.visual_override_changed.emit(
            True,
            heading,
            self._display_name(target),
        )
        self._temporary_override_timer.start(
            max(1, int(round(duration * 1000.0)))
        )

    def start_targeted_color_test(
        self,
        state: OrbVisualState | str,
        duration_seconds: float = 10.0,
    ) -> None:
        """Show one test color for a fixed interval, then return to live state."""
        self.set_temporary_color(
            state,
            duration_seconds,
            label="COLOR TEST",
        )

    def clear_temporary_color(self) -> None:
        """Cancel a targeted color shift and return to the current live state."""
        self._cancel_temporary_override(return_to_live=True, announce=True)

    def return_to_live_state(self) -> None:
        """Cancel any visual test/override and immediately resolve live state."""
        had_cycle = self._test_active
        had_temporary = self._temporary_override_state is not None

        self._test_timer.stop()
        self._test_active = False
        self._temporary_override_timer.stop()
        self._temporary_override_state = None

        if had_cycle or had_temporary:
            self.visual_override_changed.emit(False, "", "")
        self._set_display_state(self._resolve_live_state())

    def _cancel_temporary_override(
        self,
        *,
        return_to_live: bool,
        announce: bool,
    ) -> None:
        had_override = self._temporary_override_state is not None
        self._temporary_override_timer.stop()
        self._temporary_override_state = None
        if announce and had_override:
            self.visual_override_changed.emit(False, "", "")
        if return_to_live and had_override:
            self._set_display_state(self._resolve_live_state())

    def _finish_temporary_override(self) -> None:
        self._cancel_temporary_override(return_to_live=True, announce=True)

    def start_color_test(self) -> None:
        """Run BLUE -> GREEN -> VIOLET -> RED -> current live state."""
        self._cancel_temporary_override(return_to_live=False, announce=False)
        self._test_timer.stop()
        self._test_active = True
        self._test_index = 0
        self._test_fallback_state = self._resolve_live_state()
        self._show_cycle_test_state(self._test_sequence[0])
        self._test_timer.start(self._TEST_HOLD_MS)

    def _show_cycle_test_state(self, state: OrbVisualState) -> None:
        self._set_display_state(state)
        self.visual_override_changed.emit(
            True,
            "CYCLE TEST",
            self._display_name(state),
        )

    def _advance_color_test(self) -> None:
        if not self._test_active:
            return

        self._test_index += 1
        if self._test_index < len(self._test_sequence):
            self._show_cycle_test_state(
                self._test_sequence[self._test_index]
            )
            self._test_timer.start(self._TEST_HOLD_MS)
            return

        self._test_active = False
        self.visual_override_changed.emit(False, "", "")
        live_state = self._resolve_live_state()
        self._set_display_state(live_state or self._test_fallback_state)

    def _refresh_live_visual_state(self) -> None:
        if self._test_active or self._temporary_override_state is not None:
            return
        self._set_display_state(self._resolve_live_state())

    def _start_red_profile(self) -> None:
        styles = (
            self._RING_SPIKE,
            self._RING_WAVE,
            self._RING_SPUTTER,
            self._CORE_SPIKE,
            self._CORE_WAVE,
            self._FULL_ICON_INTERFERENCE,
        )
        # Local ring/core disruptions remain dominant, but full-orb interference
        # is now noticeably more common during a genuine RED state.
        weights = (13, 13, 13, 19, 19, 23)
        style = self._rng.choices(styles, weights=weights, k=1)[0]
        if style == self._FULL_ICON_INTERFERENCE:
            duration = self._rng.uniform(0.42, 0.92)
        else:
            duration = self._rng.uniform(1.10, 3.20)
        self._glitch_duration = 0.0
        super()._start_glitch(style=style, duration=duration)

    def _profile(self, target: str) -> tuple[float, float, float]:
        span, radial, tangent = super()._profile(target)
        return span * 1.12, radial * 1.18, tangent * 1.18

    def _full_offset(self, layer: int) -> QPointF:
        offset = super()._full_offset(layer)
        return QPointF(offset.x() * 1.24, offset.y() * 1.24)
