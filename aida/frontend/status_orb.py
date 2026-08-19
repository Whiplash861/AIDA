from __future__ import annotations

from PySide6.QtCore import QTimer, Signal

from aida.frontend.internal_orb import AIDAInternalOrb, OrbVisualState


class AIDAStatusOrb(AIDAInternalOrb):
    """Header orb with temporary visual overrides and explicit test context.

    Live AIDA/Artificer/trouble state continues updating while a visual override
    is active. When the override ends, the orb resolves the current live state
    instead of restoring a stale snapshot.
    """

    visual_override_changed = Signal(bool, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

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
        self.visual_override_changed.emit(True, heading, target.name)
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
        """Run BLUE -> GREEN -> PURPLE -> RED -> current live state."""
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
            state.name,
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
