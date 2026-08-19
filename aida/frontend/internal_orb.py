from __future__ import annotations

import math
import random
import time
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from aida.artificer.models import ArtificerStatus
from aida.frontend.overlay import AIDAOverlay
from aida.frontend.status import AIDAStatus


class OrbVisualState(str, Enum):
    BLUE = "blue"
    GREEN = "green"
    PURPLE = "purple"
    RED = "red"


class OrbTroubleCode(str, Enum):
    BACKEND_DISCONNECTED = "APP-BACKEND-DISCONNECTED"
    STARTUP_FAILURE = "APP-STARTUP-FAILURE"
    RUNTIME_FAILURE = "APP-RUNTIME-FAILURE"
    ARTIFICER_FAILURE = "ARTIFICER-FAILURE"


_TROUBLE_CODE_STATES: dict[str, OrbVisualState] = {
    OrbTroubleCode.BACKEND_DISCONNECTED.value: OrbVisualState.RED,
    OrbTroubleCode.STARTUP_FAILURE.value: OrbVisualState.RED,
    OrbTroubleCode.RUNTIME_FAILURE.value: OrbVisualState.RED,
    OrbTroubleCode.ARTIFICER_FAILURE.value: OrbVisualState.RED,
}

_PALETTES: dict[
    OrbVisualState,
    tuple[QColor, QColor, QColor, QColor, QColor],
] = {
    OrbVisualState.BLUE: (
        QColor("#278DFF"),
        QColor("#6EDBFF"),
        QColor("#F2FDFF"),
        QColor("#071A31"),
        QColor("#020711"),
    ),
    OrbVisualState.GREEN: (
        QColor("#20C879"),
        QColor("#68F0B2"),
        QColor("#F1FFF8"),
        QColor("#06291B"),
        QColor("#020B07"),
    ),
    OrbVisualState.PURPLE: (
        QColor("#8A5CFF"),
        QColor("#C19CFF"),
        QColor("#FBF7FF"),
        QColor("#1B0C38"),
        QColor("#090314"),
    ),
    OrbVisualState.RED: (
        QColor("#FF3A50"),
        QColor("#FF7A89"),
        QColor("#FFF3F5"),
        QColor("#35070E"),
        QColor("#100204"),
    ),
}

_ACTIVE_ARTIFICER_STATES = {
    ArtificerStatus.OBSERVING.value,
    ArtificerStatus.REVIEWING.value,
    ArtificerStatus.MAINTENANCE.value,
    ArtificerStatus.ROLLBACK.value,
}


class AIDAInternalOrb(AIDAOverlay):
    """Embedded AIDA state orb used inside the primary frontend header.

    The renderer and glitch physics come directly from ``AIDAOverlay`` so the
    detached and embedded orbs stay visually related. The embedded orb adds a
    live-state palette, center-out color propagation, a temporary color test,
    and a continuous controlled-instability scheduler while in RED.
    """

    _STATE_TRANSITION_SECONDS = 0.72
    _TEST_HOLD_MS = 1250

    def __init__(self, parent: QWidget | None = None) -> None:
        self._internal_scale = 60.0 / 120.0
        super().__init__(diameter=60)

        self.setParent(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._canvas_margin = 5
        self.setFixedSize(70, 70)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip(
            "AIDA live application-state indicator • Test: Ctrl+Shift+O"
        )

        self._live_status = AIDAStatus.STARTUP
        self._active_task_count = 0
        self._artificer_status = ArtificerStatus.READY.value
        self._active_artificer_tasks: set[str] = set()
        self._trouble_codes: dict[str, OrbVisualState] = {}

        self._display_state = OrbVisualState.GREEN
        self._transition_from_state: OrbVisualState | None = None
        self._transition_started_at: float | None = None

        self._test_active = False
        self._test_index = 0
        self._test_fallback_state = self._display_state
        self._test_sequence = (
            OrbVisualState.BLUE,
            OrbVisualState.GREEN,
            OrbVisualState.PURPLE,
            OrbVisualState.RED,
        )
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.timeout.connect(self._advance_color_test)

        self._next_glitch_due = float("inf")
        self._glitch_duration = 0.0
        self._glitch_elapsed = 0.0
        self._rng = random.Random()

        self._set_display_state(self._resolve_live_state(), animated=False)

    def _pen(
        self,
        color: QColor,
        width: float,
        cap: Qt.PenCapStyle | None = None,
    ) -> QPen:
        return AIDAOverlay._pen(
            color,
            width * self._internal_scale,
            cap,
        )

    def _sync_visibility(self) -> None:
        return

    def _schedule_next_glitch(self) -> None:
        self._next_glitch_due = float("inf")

    def set_status(self, status: AIDAStatus) -> None:
        if not isinstance(status, AIDAStatus):
            raise TypeError("status must be an AIDAStatus value")
        self._status = status
        self._live_status = status
        self.setToolTip(
            f"AIDA live state: {status.name} • Test: Ctrl+Shift+O"
        )
        self._refresh_live_visual_state()

    def set_active_task_count(self, count: int) -> None:
        self._active_task_count = max(0, int(count))
        self._refresh_live_visual_state()

    def set_artificer_status(self, text: str) -> None:
        normalized = text.strip().lower()
        self._artificer_status = normalized
        self.set_trouble_code(
            OrbTroubleCode.ARTIFICER_FAILURE,
            active=normalized == ArtificerStatus.ERROR.value,
        )
        self._refresh_live_visual_state()

    def report_task_started(self, task_name: str) -> None:
        normalized = task_name.strip().lower()
        if normalized.startswith("artificer"):
            self._active_artificer_tasks.add(normalized)
            self._refresh_live_visual_state()

    def report_task_finished(self, task_name: str) -> None:
        normalized = task_name.strip().lower()
        if normalized in self._active_artificer_tasks:
            self._active_artificer_tasks.discard(normalized)
            self._refresh_live_visual_state()

    def report_task_failed(self, task_name: str) -> None:
        self.report_task_finished(task_name)

    def set_backend_connected(self, connected: bool) -> None:
        self.set_trouble_code(
            OrbTroubleCode.BACKEND_DISCONNECTED,
            active=not connected,
        )

    def set_trouble_code(
        self,
        code: str | OrbTroubleCode,
        *,
        active: bool = True,
        state: OrbVisualState | None = None,
    ) -> None:
        normalized = (
            code.value
            if isinstance(code, OrbTroubleCode)
            else str(code).strip().upper()
        )
        if not normalized:
            raise ValueError("trouble code cannot be empty")
        if active:
            self._trouble_codes[normalized] = (
                state
                or _TROUBLE_CODE_STATES.get(normalized)
                or OrbVisualState.RED
            )
        else:
            self._trouble_codes.pop(normalized, None)
        self._refresh_live_visual_state()

    def clear_trouble_code(self, code: str | OrbTroubleCode) -> None:
        self.set_trouble_code(code, active=False)

    def clear_all_trouble_codes(self) -> None:
        self._trouble_codes.clear()
        self._refresh_live_visual_state()

    @property
    def current_visual_state(self) -> OrbVisualState:
        return self._display_state

    @property
    def active_trouble_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._trouble_codes))

    def start_color_test(self) -> None:
        """Run BLUE -> GREEN -> PURPLE -> RED -> current live state."""
        self._test_timer.stop()
        self._test_active = True
        self._test_index = 0
        self._test_fallback_state = self._resolve_live_state()
        self._set_display_state(self._test_sequence[0])
        self._test_timer.start(self._TEST_HOLD_MS)

    def _advance_color_test(self) -> None:
        if not self._test_active:
            return
        self._test_index += 1
        if self._test_index < len(self._test_sequence):
            self._set_display_state(self._test_sequence[self._test_index])
            self._test_timer.start(self._TEST_HOLD_MS)
            return

        self._test_active = False
        live_state = self._resolve_live_state()
        self._set_display_state(live_state or self._test_fallback_state)

    def _refresh_live_visual_state(self) -> None:
        if self._test_active:
            return
        self._set_display_state(self._resolve_live_state())

    def _resolve_live_state(self) -> OrbVisualState:
        if self._trouble_codes:
            states = set(self._trouble_codes.values())
            if OrbVisualState.RED in states:
                return OrbVisualState.RED
            if OrbVisualState.PURPLE in states:
                return OrbVisualState.PURPLE
            if OrbVisualState.GREEN in states:
                return OrbVisualState.GREEN

        if self._live_status in {AIDAStatus.ERROR, AIDAStatus.SHUTDOWN}:
            return OrbVisualState.RED

        if (
            self._active_artificer_tasks
            or self._artificer_status in _ACTIVE_ARTIFICER_STATES
        ):
            return OrbVisualState.PURPLE

        if self._active_task_count > 0:
            return OrbVisualState.GREEN

        if self._live_status in {
            AIDAStatus.STARTUP,
            AIDAStatus.LISTENING,
            AIDAStatus.ANALYZING,
            AIDAStatus.SPEAKING,
        }:
            return OrbVisualState.GREEN

        return OrbVisualState.BLUE

    def _set_display_state(
        self,
        state: OrbVisualState,
        *,
        animated: bool = True,
    ) -> None:
        if not isinstance(state, OrbVisualState):
            raise TypeError("state must be an OrbVisualState")
        if state is self._display_state and self._transition_from_state is None:
            return

        previous = self._display_state
        self._display_state = state
        if animated and previous is not state:
            self._transition_from_state = previous
            self._transition_started_at = time.perf_counter()
        else:
            self._transition_from_state = None
            self._transition_started_at = None
        self.update()

    def _transition_progress(self) -> float:
        if self._transition_started_at is None:
            return 1.0
        elapsed = time.perf_counter() - self._transition_started_at
        return min(
            1.0,
            max(0.0, elapsed / self._STATE_TRANSITION_SECONDS),
        )

    @staticmethod
    def _mix_color(first: QColor, second: QColor, progress: float) -> QColor:
        p = min(1.0, max(0.0, progress))
        return QColor(
            round(first.red() + (second.red() - first.red()) * p),
            round(first.green() + (second.green() - first.green()) * p),
            round(first.blue() + (second.blue() - first.blue()) * p),
            round(first.alpha() + (second.alpha() - first.alpha()) * p),
        )

    def _layer_progress(self, layer: str) -> float:
        if self._transition_from_state is None:
            return 1.0
        progress = self._transition_progress()
        if layer == "core":
            return min(1.0, progress / 0.48)
        if layer == "ambient":
            return min(1.0, progress / 0.62)
        if layer == "data":
            return min(1.0, max(0.0, (progress - 0.16) / 0.56))
        if layer == "ring":
            return min(1.0, max(0.0, (progress - 0.36) / 0.64))
        return progress

    def _palette_for_layer(
        self,
        layer: str,
    ) -> tuple[QColor, QColor, QColor, QColor, QColor]:
        target = _PALETTES[self._display_state]
        if self._transition_from_state is None:
            return (
                QColor(target[0]),
                QColor(target[1]),
                QColor(target[2]),
                QColor(target[3]),
                QColor(target[4]),
            )

        source = _PALETTES[self._transition_from_state]
        progress = self._layer_progress(layer)
        mixed = tuple(
            self._mix_color(first, second, progress)
            for first, second in zip(source, target, strict=True)
        )
        return mixed[0], mixed[1], mixed[2], mixed[3], mixed[4]

    def _palette(self) -> tuple[QColor, QColor, QColor, QColor, QColor]:
        return self._palette_for_layer("data")

    def _paint_ambient_glow(
        self,
        painter: QPainter,
        rect: QRectF,
        center: QPointF,
        base: QColor,
        boost: float,
    ) -> None:
        palette = self._palette_for_layer("ambient")
        super()._paint_ambient_glow(
            painter,
            rect,
            center,
            palette[0],
            boost,
        )

    def _paint_main_ring(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base: QColor,
        bright: QColor,
        hot: QColor,
        boost: float,
    ) -> None:
        palette = self._palette_for_layer("ring")
        super()._paint_main_ring(
            painter,
            center,
            radius,
            palette[0],
            palette[1],
            palette[2],
            boost,
        )

    def _paint_data_rings(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base: QColor,
        bright: QColor,
        hot: QColor,
    ) -> None:
        palette = self._palette_for_layer("data")
        super()._paint_data_rings(
            painter,
            center,
            radius,
            palette[0],
            palette[1],
            palette[2],
        )

    def _paint_energy_core(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base: QColor,
        bright: QColor,
        hot: QColor,
        deep: QColor,
        edge: QColor,
        glow: float,
        boost: float,
    ) -> None:
        palette = self._palette_for_layer("core")
        super()._paint_energy_core(
            painter,
            center,
            radius,
            palette[0],
            palette[1],
            palette[2],
            palette[3],
            palette[4],
            glow,
            boost,
        )

    def _paint_pulse(self, painter: QPainter, center: QPointF) -> None:
        if self._transition_from_state is None:
            return
        progress = self._transition_progress()
        eased = 1.0 - (1.0 - progress) ** 2
        radius = 3.0 + eased * (self._orb_diameter * 0.53)
        pulse = QColor(_PALETTES[self._display_state][1])
        pulse.setAlpha(
            int(210 * math.sin(min(1.0, progress) * math.pi))
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            self._pen(pulse, 2.4, Qt.PenCapStyle.RoundCap)
        )
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
        painter.setPen(
            self._pen(secondary, 1.2, Qt.PenCapStyle.RoundCap)
        )
        outer = radius + 3.5 * self._internal_scale
        painter.drawEllipse(
            QRectF(
                center.x() - outer,
                center.y() - outer,
                outer * 2.0,
                outer * 2.0,
            )
        )

    def _red_layer_fraction(self, layer: str) -> float:
        if self._transition_from_state is None:
            return (
                1.0
                if self._display_state is OrbVisualState.RED
                else 0.0
            )

        progress = self._layer_progress(layer)
        source_is_red = self._transition_from_state is OrbVisualState.RED
        target_is_red = self._display_state is OrbVisualState.RED
        if source_is_red and target_is_red:
            return 1.0
        if source_is_red:
            return 1.0 - progress
        if target_is_red:
            return progress
        return 0.0

    def _red_fraction(self, target: str) -> float:
        return self._red_layer_fraction(
            "ring" if target == "ring" else "core"
        )

    def _red_mode_active(self) -> bool:
        return max(
            self._red_layer_fraction("ring"),
            self._red_layer_fraction("data"),
            self._red_layer_fraction("core"),
        ) > 0.001

    def _start_red_profile(self) -> None:
        styles = (
            self._RING_SPIKE,
            self._RING_WAVE,
            self._RING_SPUTTER,
            self._CORE_SPIKE,
            self._CORE_WAVE,
            self._FULL_ICON_INTERFERENCE,
        )
        weights = (15, 15, 15, 20, 20, 15)
        style = self._rng.choices(styles, weights=weights, k=1)[0]
        if style == self._FULL_ICON_INTERFERENCE:
            duration = self._rng.uniform(0.32, 0.78)
        else:
            duration = self._rng.uniform(1.0, 3.0)
        self._glitch_duration = 0.0
        super()._start_glitch(style=style, duration=duration)

    def _life(self) -> float:
        if not self.glitch_active:
            return 0.0
        base = super()._life()
        if self._red_mode_active():
            return 0.34 + base * 0.66
        return base

    def _profile(self, target: str) -> tuple[float, float, float]:
        span, radial, tangent = super()._profile(target)
        scale = self._internal_scale * 1.24
        return span * 1.12, radial * scale, tangent * scale

    def _displacement(
        self,
        angle: float,
        index: int,
        boost: float,
        target: str,
    ) -> tuple[bool, float, float, float]:
        affected, radial, tangent, energy = super()._displacement(
            angle,
            index,
            boost,
            target,
        )
        factor = self._red_fraction(target)
        if not affected or factor <= 0.001:
            return False, 0.0, 0.0, 0.0
        return (
            True,
            radial * factor,
            tangent * factor,
            energy * factor,
        )

    def _full_offset(self, layer: int) -> QPointF:
        offset = super()._full_offset(layer)
        factor = self._red_layer_fraction("data")
        return QPointF(
            offset.x() * self._internal_scale * 1.18 * factor,
            offset.y() * self._internal_scale * 1.18 * factor,
        )

    def _advance_animation(self) -> None:
        if self._red_mode_active() and not self.glitch_active:
            self._start_red_profile()
        elif not self._red_mode_active():
            self._glitch_duration = 0.0
            self._glitch_elapsed = 0.0
            self._next_glitch_due = float("inf")

        super()._advance_animation()

        if (
            self._transition_started_at is not None
            and self._transition_progress() >= 1.0
        ):
            self._transition_started_at = None
            self._transition_from_state = None

        if self._red_mode_active() and not self.glitch_active:
            self._start_red_profile()
        self.update()
