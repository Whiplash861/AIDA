from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter

from aida.frontend.internal_orb import OrbVisualState
from aida.frontend.status_orb import AIDAStatusOrb as _BaseStatusOrb
from aida.technomancer.models import TECHNOMANCER_COLOR


_CYAN_PALETTE = (
    QColor(TECHNOMANCER_COLOR),
    QColor("#7CF5FF"),
    QColor("#F4FEFF"),
    QColor("#04333A"),
    QColor("#011114"),
)

_ACTIVE_TECHNOMANCER_STATES = {
    "running",
    "working",
    "analyzing",
    "reviewing",
    "monitoring",
}


class AIDAStatusOrb(_BaseStatusOrb):
    """Refined AIDA orb with Technomancer's cyan engine state layered in.

    The established Blue/Green/Violet/Red state engine, transition timing, and
    RED ring/core failure schedulers remain owned by ``_BaseStatusOrb``.
    Technomancer uses GREEN only as an internal non-fault carrier state while
    this subclass supplies the canonical cyan palette and semantic status. That
    keeps the accepted renderer untouched while allowing smooth transitions to
    and from Technomancer, including overlap with Artificer.
    """

    def __init__(self, parent=None) -> None:
        self._technomancer_status = "idle"
        self._active_technomancer_tasks: set[str] = set()
        self._current_palette_is_cyan = False
        self._transition_source_cyan = False
        self._transition_target_cyan = False
        self._cyan_test_active = False
        self._starting_cyan_test = False
        super().__init__(parent=parent)

    def _technomancer_is_active(self) -> bool:
        return bool(
            self._active_technomancer_tasks
            or self._technomancer_status in _ACTIVE_TECHNOMANCER_STATES
        )

    def _effective_cyan_target(self, state: OrbVisualState) -> bool:
        if state is OrbVisualState.RED:
            return False
        if self._cyan_test_active:
            return True
        if self._test_active or self._temporary_override_state is not None:
            return False
        return self._technomancer_is_active()

    def _resolve_live_state(self) -> OrbVisualState:
        state = super()._resolve_live_state()
        if state is OrbVisualState.RED:
            return state
        if self._technomancer_is_active():
            # GREEN remains the internal carrier only; the visible palette is
            # canonical Technomancer cyan and the semantic label is TECHNOMANCER.
            return OrbVisualState.GREEN
        return state

    def _set_display_state(
        self,
        state: OrbVisualState,
        *,
        animated: bool = True,
    ) -> None:
        target_cyan = self._effective_cyan_target(state)
        source_cyan = getattr(self, "_current_palette_is_cyan", False)

        if state is self._display_state and source_cyan != target_cyan:
            self._transition_source_cyan = source_cyan
            self._transition_target_cyan = target_cyan
            self._current_palette_is_cyan = target_cyan
            if animated:
                self._transition_from_state = state
                self._transition_started_at = time.perf_counter()
            else:
                self._transition_from_state = None
                self._transition_started_at = None
            self.update()
            return

        if state is self._display_state:
            return

        self._transition_source_cyan = source_cyan
        self._transition_target_cyan = target_cyan
        super()._set_display_state(state, animated=animated)
        self._current_palette_is_cyan = target_cyan

    @staticmethod
    def _copy_palette(
        palette: tuple[QColor, QColor, QColor, QColor, QColor],
    ) -> tuple[QColor, QColor, QColor, QColor, QColor]:
        return tuple(QColor(color) for color in palette)  # type: ignore[return-value]

    def _palette_for_layer(
        self,
        layer: str,
    ) -> tuple[QColor, QColor, QColor, QColor, QColor]:
        if self._transition_from_state is None:
            if self._current_palette_is_cyan:
                return self._copy_palette(_CYAN_PALETTE)
            return super()._palette_for_layer(layer)

        source = (
            _CYAN_PALETTE
            if self._transition_source_cyan
            else _BaseStatusOrb._state_palette(self._transition_from_state)
        )
        target = (
            _CYAN_PALETTE
            if self._transition_target_cyan
            else _BaseStatusOrb._state_palette(self._display_state)
        )
        progress = self._layer_progress(layer)
        mixed = tuple(
            self._mix_color(first, second, progress)
            for first, second in zip(source, target, strict=True)
        )
        return mixed[0], mixed[1], mixed[2], mixed[3], mixed[4]

    def _paint_pulse(self, painter: QPainter, center: QPointF) -> None:
        if self._transition_from_state is None:
            return
        progress = self._transition_progress()
        eased = 1.0 - (1.0 - progress) ** 2
        radius = 3.0 + eased * (self._orb_diameter * 0.53)
        target = (
            _CYAN_PALETTE
            if self._transition_target_cyan
            else _BaseStatusOrb._state_palette(self._display_state)
        )
        pulse = QColor(target[1])
        pulse.setAlpha(int(210 * math.sin(min(1.0, progress) * math.pi)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._pen(pulse, 2.4, Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(
            QRectF(
                center.x() - radius,
                center.y() - radius,
                radius * 2.0,
                radius * 2.0,
            )
        )

        secondary = QColor(pulse)
        secondary.setAlpha(max(0, pulse.alpha() // 3))
        painter.setPen(self._pen(secondary, 1.2, Qt.PenCapStyle.RoundCap))
        outer = radius + 3.5 * self._internal_scale
        painter.drawEllipse(
            QRectF(
                center.x() - outer,
                center.y() - outer,
                outer * 2.0,
                outer * 2.0,
            )
        )

    def current_live_status_text(self) -> str:
        base_status = super().current_live_status_text()
        if base_status in {"DISCONNECTED", "SYSTEM FAULT", "OFFLINE"}:
            return base_status
        if self._technomancer_is_active():
            return "TECHNOMANCER"
        return base_status

    def set_technomancer_status(self, text: str) -> None:
        normalized = text.strip().lower() or "idle"
        self._technomancer_status = normalized
        self.set_trouble_code(
            "TECHNOMANCER-FAILURE",
            active=normalized in {"error", "failed", "failure"},
        )
        self._refresh_live_visual_state()

    def report_task_started(self, task_name: str) -> None:
        super().report_task_started(task_name)
        normalized = task_name.strip().lower()
        if not normalized.startswith("technomancer"):
            return
        self._active_technomancer_tasks.add(normalized)
        self._technomancer_status = "running"
        self.clear_trouble_code("TECHNOMANCER-FAILURE")
        self._refresh_live_visual_state()

    def report_task_finished(self, task_name: str) -> None:
        super().report_task_finished(task_name)
        normalized = task_name.strip().lower()
        if not normalized.startswith("technomancer"):
            return
        self._active_technomancer_tasks.discard(normalized)
        if not self._active_technomancer_tasks:
            self._technomancer_status = "idle"
        # TaskManager updates the aggregate task count immediately after this
        # callback. Defer the visual resolve until that count is current so a
        # completed Technomancer task transitions cleanly from CYAN to its true
        # live destination instead of briefly flashing generic GREEN.
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._refresh_live_visual_state)

    def report_task_failed(self, task_name: str) -> None:
        normalized = task_name.strip().lower()
        if not normalized.startswith("technomancer"):
            super().report_task_failed(task_name)
            return
        self._active_technomancer_tasks.discard(normalized)
        self._technomancer_status = "error"
        self.set_trouble_code("TECHNOMANCER-FAILURE", active=True)

    def set_temporary_color(
        self,
        state: OrbVisualState | str,
        duration_seconds: float,
        *,
        label: str = "COLOR OVERRIDE",
    ) -> None:
        if not self._starting_cyan_test:
            self._cyan_test_active = False
        super().set_temporary_color(
            state,
            duration_seconds,
            label=label,
        )

    def start_cyan_color_test(self, duration_seconds: float = 10.0) -> None:
        self._starting_cyan_test = True
        self._cyan_test_active = True
        try:
            super().set_temporary_color(
                OrbVisualState.GREEN,
                duration_seconds,
                label="COLOR TEST",
            )
        finally:
            self._starting_cyan_test = False
        # Replace the carrier-state display name with its real semantic color.
        self.visual_override_changed.emit(True, "COLOR TEST", "CYAN")

    def _finish_temporary_override(self) -> None:
        self._cyan_test_active = False
        super()._finish_temporary_override()

    def clear_temporary_color(self) -> None:
        self._cyan_test_active = False
        super().clear_temporary_color()

    def return_to_live_state(self) -> None:
        self._cyan_test_active = False
        super().return_to_live_state()
