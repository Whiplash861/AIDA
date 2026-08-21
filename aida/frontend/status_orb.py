from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap

from aida.frontend.internal_orb import (
    AIDAInternalOrb,
    OrbTroubleCode,
    OrbVisualState,
    _ACTIVE_ARTIFICER_STATES,
    _PALETTES,
)
from aida.frontend.overlay import AIDAOverlay


_VIOLET_PALETTE = (
    QColor("#B13CFF"),
    QColor("#D985FF"),
    QColor("#FFF3FF"),
    QColor("#2A073D"),
    QColor("#0D0215"),
)


class AIDAStatusOrb(AIDAInternalOrb):
    """Header orb with live state, test overrides, and RED failure profiles.

    RED uses two independent failure systems. The outer ring glitches continuously
    with no recovery gap. The core remains stable between randomized profile events
    and runs its own animation state machine. Profile 3 temporarily owns the whole
    orb for a three-second interference event, then returns control to both systems.
    """

    visual_override_changed = Signal(bool, str, str)

    _CORE_PROFILE_MIN_INTERVAL = 3.0
    _CORE_PROFILE_MAX_INTERVAL = 5.0
    _CORE_PROFILE_WEIGHTS = (40, 40, 20)

    def __init__(self, parent=None) -> None:
        self._technomancer_status = "idle"
        self._active_technomancer_tasks: set[str] = set()
        super().__init__(parent=parent)

        # The visible orb remains 74px, while every offscreen glitch layer gets a
        # 96px transparent safety canvas so pulses and displaced pixels do not clip.
        self._orb_diameter = 74
        self._internal_scale = 70.0 / 120.0
        self._canvas_margin = 11
        self.setFixedSize(96, 96)

        self._temporary_override_state: OrbVisualState | None = None
        self._temporary_override_timer = QTimer(self)
        self._temporary_override_timer.setSingleShot(True)
        self._temporary_override_timer.timeout.connect(
            self._finish_temporary_override
        )

        self._core_scheduler_red = False
        self._core_profile: int | None = None
        self._core_stages: list[tuple[str, float]] = []
        self._core_stage_index = 0
        self._core_stage_started_at = 0.0
        self._core_effect_seed = 0
        self._next_core_profile_due = float("inf")

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
        if self._technomancer_is_active():
            return "TECHNOMANCER"
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

    def _paint_pulse(self, painter: QPainter, center: QPointF) -> None:
        """Paint the center-out state pulse using the true target palette."""
        if self._transition_from_state is None:
            return
        progress = self._transition_progress()
        eased = 1.0 - (1.0 - progress) ** 2
        radius = 3.0 + eased * (self._orb_diameter * 0.53)
        pulse = QColor(self._state_palette(self._display_state)[1])
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
        """Run BLUE -> GREEN -> VIOLET -> CYAN -> RED -> current live state."""
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

    # ------------------------------------------------------------------
    # Technomancer live state
    # ------------------------------------------------------------------

    def _technomancer_is_active(self) -> bool:
        return bool(
            self._active_technomancer_tasks
            or self._technomancer_status
            in {"running", "working", "analyzing", "reviewing", "monitoring"}
        )

    def _resolve_live_state(self) -> OrbVisualState:
        state = super()._resolve_live_state()
        if state is OrbVisualState.RED:
            return state
        if self._technomancer_is_active():
            return OrbVisualState.CYAN
        return state

    def set_technomancer_status(self, text: str) -> None:
        normalized = text.strip().lower() or "idle"
        self._technomancer_status = normalized
        self.set_trouble_code(
            "TECHNOMANCER-FAILURE",
            active=normalized in {"error", "failed", "failure"},
        )
        self._refresh_live_visual_state()

    def report_task_started(self, task_name: str) -> None:
        normalized = task_name.strip().lower()
        if normalized.startswith("technomancer"):
            self._active_technomancer_tasks.add(normalized)
            self._technomancer_status = "running"
            self.clear_trouble_code("TECHNOMANCER-FAILURE")
        super().report_task_started(task_name)
        if normalized.startswith("technomancer"):
            self._refresh_live_visual_state()

    def report_task_finished(self, task_name: str) -> None:
        normalized = task_name.strip().lower()
        if normalized.startswith("technomancer"):
            self._active_technomancer_tasks.discard(normalized)
            if not self._active_technomancer_tasks:
                self._technomancer_status = "idle"
        super().report_task_finished(task_name)
        if normalized.startswith("technomancer"):
            QTimer.singleShot(0, self._refresh_live_visual_state)

    def report_task_failed(self, task_name: str) -> None:
        normalized = task_name.strip().lower()
        if not normalized.startswith("technomancer"):
            super().report_task_failed(task_name)
            return
        self._active_technomancer_tasks.discard(normalized)
        self._technomancer_status = "error"
        self.set_trouble_code("TECHNOMANCER-FAILURE", active=True)

    # ------------------------------------------------------------------
    # RED ring scheduler
    # ------------------------------------------------------------------

    def _start_red_profile(self) -> None:
        """Start the next continuous outer-ring glitch profile.

        Profiles 1 and 2 in the core are independent and do not affect this
        channel. Profile 3 suppresses this method for its exclusive duration.
        """
        if self._core_profile == 3:
            return
        style = self._rng.choice(
            (
                self._RING_SPIKE,
                self._RING_WAVE,
                self._RING_SPUTTER,
            )
        )
        duration = self._rng.uniform(0.90, 2.20)
        self._glitch_duration = 0.0
        super()._start_glitch(style=style, duration=duration)

    def _profile(self, target: str) -> tuple[float, float, float]:
        # Preserve the stronger RED ring disruption established in the prior pass.
        span, radial, tangent = super()._profile(target)
        return span * 1.25, radial * 1.75, tangent * 1.85

    def _full_offset(self, layer: int) -> QPointF:
        # Used only by Profile 3's full-orb interference.
        offset = super()._full_offset(layer)
        return QPointF(offset.x() * 2.40, offset.y() * 2.40)

    # ------------------------------------------------------------------
    # RED core scheduler
    # ------------------------------------------------------------------

    def _schedule_next_core_profile(self, now: float) -> None:
        self._next_core_profile_due = now + self._rng.uniform(
            self._CORE_PROFILE_MIN_INTERVAL,
            self._CORE_PROFILE_MAX_INTERVAL,
        )

    def _clear_core_profile(self) -> None:
        self._core_profile = None
        self._core_stages = []
        self._core_stage_index = 0
        self._core_stage_started_at = 0.0
        self._core_effect_seed = 0

    def _begin_core_profile(self, now: float) -> None:
        profile = self._rng.choices(
            (1, 2, 3),
            weights=self._CORE_PROFILE_WEIGHTS,
            k=1,
        )[0]
        self._core_profile = profile
        self._core_stage_index = 0
        self._core_stage_started_at = now
        self._core_effect_seed = self._rng.randint(0, 1_000_000)

        if profile == 1:
            # Core Split -> Horizontal Fracture -> Core Collapse -> Recover.
            self._core_stages = [
                ("split", self._rng.uniform(0.30, 0.42)),
                ("fracture", self._rng.uniform(0.32, 0.46)),
                ("collapse", self._rng.uniform(0.28, 0.40)),
                ("recover", self._rng.uniform(0.32, 0.50)),
            ]
            return

        if profile == 2:
            # Phase Jump -> Radial Tear -> Recover.
            self._core_stages = [
                ("phase_jump", self._rng.uniform(0.45, 0.65)),
                ("radial_tear", self._rng.uniform(0.55, 0.80)),
                ("recover", self._rng.uniform(0.35, 0.55)),
            ]
            return

        # Profile 3 owns the whole orb for exactly three seconds. Cancel the
        # current ring profile and replace it with one full-icon interference run.
        self._core_stages = [("interference", 3.0)]
        self._glitch_duration = 0.0
        self._glitch_elapsed = 0.0
        super()._start_glitch(
            style=self._FULL_ICON_INTERFERENCE,
            duration=3.0,
        )

    def _finish_core_profile(self, now: float) -> None:
        was_interference = self._core_profile == 3
        self._clear_core_profile()
        if was_interference:
            self._glitch_duration = 0.0
            self._glitch_elapsed = 0.0
        self._schedule_next_core_profile(now)

    def _advance_core_scheduler(self, now: float) -> None:
        red_now = self._display_state is OrbVisualState.RED

        if red_now and not self._core_scheduler_red:
            self._core_scheduler_red = True
            self._clear_core_profile()
            self._schedule_next_core_profile(now)
        elif not red_now and self._core_scheduler_red:
            self._core_scheduler_red = False
            if self._core_profile == 3:
                self._glitch_duration = 0.0
                self._glitch_elapsed = 0.0
            self._clear_core_profile()
            self._next_core_profile_due = float("inf")
            return

        if not red_now:
            return

        if self._core_profile is None:
            if now >= self._next_core_profile_due:
                self._begin_core_profile(now)
            return

        if not self._core_stages:
            self._finish_core_profile(now)
            return

        _, duration = self._core_stages[self._core_stage_index]
        if now - self._core_stage_started_at < duration:
            return

        self._core_stage_index += 1
        if self._core_stage_index >= len(self._core_stages):
            self._finish_core_profile(now)
            return

        self._core_stage_started_at = now
        self._core_effect_seed = self._rng.randint(0, 1_000_000)

    def _current_core_effect(self) -> str | None:
        if self._core_profile is None or not self._core_stages:
            return None
        return self._core_stages[self._core_stage_index][0]

    def _core_stage_progress(self) -> float:
        if self._core_profile is None or not self._core_stages:
            return 0.0
        duration = self._core_stages[self._core_stage_index][1]
        if duration <= 0.0:
            return 1.0
        return min(
            1.0,
            max(
                0.0,
                (time.perf_counter() - self._core_stage_started_at) / duration,
            ),
        )

    def _core_bucket_rng(self, rate: float, salt: int = 0) -> random.Random:
        elapsed = max(0.0, time.perf_counter() - self._core_stage_started_at)
        bucket = int(elapsed * rate)
        return random.Random(
            self._core_effect_seed + bucket * 137 + salt * 10_007
        )

    # ------------------------------------------------------------------
    # Core profile rendering
    # ------------------------------------------------------------------

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
        # Profile 3 intentionally reuses the severe shared full-orb interference
        # renderer. Profiles 1 and 2 bypass the ring glitch channel completely.
        if self._core_profile == 3:
            super()._paint_energy_core(
                painter,
                center,
                radius,
                base,
                bright,
                hot,
                deep,
                edge,
                glow,
                boost,
            )
            return

        palette = self._palette_for_layer("core")
        source = AIDAOverlay._render_core(
            self,
            center,
            radius,
            palette[0],
            palette[1],
            palette[2],
            palette[3],
            palette[4],
            glow,
        )
        effect = self._current_core_effect()
        if effect is None:
            painter.drawPixmap(0, 0, source)
            return

        progress = self._core_stage_progress()
        if effect == "split":
            self._paint_core_split(painter, source, center, radius, progress)
        elif effect == "fracture":
            self._paint_core_fracture(
                painter,
                source,
                center,
                radius,
                progress,
            )
        elif effect == "collapse":
            self._paint_core_collapse(painter, source, center, progress)
        elif effect == "phase_jump":
            self._paint_core_phase_jump(painter, source, center, radius, progress)
        elif effect == "radial_tear":
            self._paint_core_radial_tear(
                painter,
                source,
                center,
                radius,
                progress,
            )
        elif effect == "recover":
            self._paint_core_recovery(painter, source, center, progress)
        else:
            painter.drawPixmap(0, 0, source)

    def _paint_core_split(
        self,
        painter: QPainter,
        source: QPixmap,
        center: QPointF,
        radius: float,
        progress: float,
    ) -> None:
        del progress
        rng = self._core_bucket_rng(20.0, 1)
        offset = rng.choice((3, 4, 5, 6))
        y_jitter = rng.choice((-1, 0, 0, 1))
        flicker = rng.choice((0.62, 0.74, 0.86, 1.0))

        core_box = QRectF(
            center.x() - radius * 1.80,
            center.y() - radius * 1.60,
            radius * 3.60,
            radius * 3.20,
        )
        half_width = core_box.width() / 2.0
        left = QRectF(
            core_box.left(),
            core_box.top(),
            half_width,
            core_box.height(),
        )
        right = QRectF(
            center.x(),
            core_box.top(),
            half_width,
            core_box.height(),
        )

        painter.save()
        painter.setClipRect(core_box)
        painter.setOpacity(0.16)
        painter.drawPixmap(0, 0, source)

        painter.setOpacity(flicker)
        painter.save()
        painter.setClipRect(left)
        painter.drawPixmap(-offset, y_jitter, source)
        painter.restore()

        painter.save()
        painter.setClipRect(right)
        painter.drawPixmap(offset, -y_jitter, source)
        painter.restore()

        band_y = center.y() + rng.uniform(-radius * 0.55, radius * 0.55)
        band = QRectF(
            core_box.left(),
            band_y,
            core_box.width(),
            rng.choice((1.8, 2.2, 2.8)),
        )
        painter.save()
        painter.setClipRect(band)
        painter.setOpacity(rng.choice((0.48, 0.72, 0.92)))
        painter.drawPixmap(rng.choice((-7, -5, 5, 7)), 0, source)
        painter.restore()
        painter.restore()

    def _paint_core_fracture(
        self,
        painter: QPainter,
        source: QPixmap,
        center: QPointF,
        radius: float,
        progress: float,
    ) -> None:
        del progress
        rng = self._core_bucket_rng(22.0, 2)
        result = QPixmap(source)
        rp = QPainter(result)

        core_left = center.x() - radius * 1.75
        core_width = radius * 3.50
        y_offsets = (-7.0, -3.0, 0.5, 4.0, 7.0)
        for index, y_offset in enumerate(y_offsets):
            height = rng.choice((1.8, 2.2, 2.8, 3.2))
            band = QRectF(
                core_left,
                center.y() + y_offset,
                core_width,
                height,
            )
            dx = rng.choice((-6, -4, -3, 3, 4, 6))
            dy = rng.choice((-1, 0, 0, 1))

            rp.save()
            rp.setClipRect(band)
            rp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear
            )
            rp.fillRect(band, QColor(0, 0, 0, 0))
            rp.restore()

            # A few bands intentionally drop out instead of redrawing, creating
            # sputtering data loss rather than a smooth physical tear.
            if rng.random() < 0.22 and index % 2:
                continue

            rp.save()
            rp.setClipRect(band)
            rp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            rp.setOpacity(rng.choice((0.48, 0.66, 0.84, 1.0)))
            rp.drawPixmap(dx, dy, source)
            rp.restore()

        rp.end()

        flicker = rng.choice((0.34, 0.52, 0.70, 0.86, 1.0, 1.0))
        x_spasm = rng.choice((-2, -1, 0, 0, 1, 2))
        y_spasm = rng.choice((-1, 0, 0, 1))
        painter.save()
        painter.setOpacity(flicker)
        painter.drawPixmap(x_spasm, y_spasm, result)
        painter.restore()

    def _paint_core_collapse(
        self,
        painter: QPainter,
        source: QPixmap,
        center: QPointF,
        progress: float,
    ) -> None:
        levels = (1.0, 0.78, 0.56, 0.34, 0.18, 0.10)
        index = min(len(levels) - 1, int(progress * len(levels)))
        height_factor = levels[index]
        target_height = max(5.0, self.height() * height_factor)
        rng = self._core_bucket_rng(24.0, 3)
        target = QRectF(
            float(rng.choice((-1, 0, 0, 1))),
            center.y() - target_height / 2.0,
            float(self.width()),
            target_height,
        )
        flicker = rng.choice((0.42, 0.60, 0.78, 1.0, 1.0))
        painter.save()
        painter.setOpacity(flicker)
        painter.drawPixmap(target, source, QRectF(source.rect()))
        painter.restore()

    def _paint_core_phase_jump(
        self,
        painter: QPainter,
        source: QPixmap,
        center: QPointF,
        radius: float,
        progress: float,
    ) -> None:
        del progress
        rng = self._core_bucket_rng(18.0, 4)
        dx = rng.choice((-4, -3, -2, 0, 0, 2, 3, 4))
        dy = rng.choice((-2, -1, 0, 0, 1, 2))
        main_opacity = rng.choice((0.42, 0.58, 0.74, 0.90, 1.0, 1.0))

        core_box = QRectF(
            center.x() - radius * 1.75,
            center.y() - radius * 1.60,
            radius * 3.50,
            radius * 3.20,
        )
        painter.save()
        painter.setClipRect(core_box)
        painter.setOpacity(0.10)
        painter.drawPixmap(0, 0, source)
        painter.setOpacity(main_opacity)
        painter.drawPixmap(dx, dy, source)

        # Brief packet-like bands jump independently of the main core position.
        for _ in range(2):
            band = QRectF(
                core_box.left(),
                center.y() + rng.uniform(-radius * 0.70, radius * 0.70),
                core_box.width(),
                rng.choice((1.5, 2.0, 2.6)),
            )
            painter.save()
            painter.setClipRect(band)
            painter.setOpacity(rng.choice((0.38, 0.62, 0.88)))
            painter.drawPixmap(
                dx + rng.choice((-4, -2, 2, 4)),
                dy,
                source,
            )
            painter.restore()
        painter.restore()

    def _paint_core_radial_tear(
        self,
        painter: QPainter,
        source: QPixmap,
        center: QPointF,
        radius: float,
        progress: float,
    ) -> None:
        del progress
        rng = self._core_bucket_rng(22.0, 5)
        result = QPixmap(source.size())
        result.fill(Qt.GlobalColor.transparent)
        rp = QPainter(result)

        x_spasm = rng.choice((-2, -1, 0, 0, 1, 2))
        y_spasm = rng.choice((-1, 0, 0, 1))
        flicker = rng.choice((0.28, 0.42, 0.58, 0.76, 0.92, 1.0, 1.0))
        rp.setOpacity(flicker)
        rp.drawPixmap(x_spasm, y_spasm, source)
        rp.setOpacity(1.0)

        core_left = center.x() - radius * 1.75
        core_width = radius * 3.50
        for _ in range(6):
            y = center.y() + rng.uniform(-radius * 1.05, radius * 1.05)
            height = rng.choice((1.4, 1.8, 2.2, 2.8))
            band = QRectF(core_left, y, core_width, height)

            rp.save()
            rp.setClipRect(band)
            rp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear
            )
            rp.fillRect(band, QColor(0, 0, 0, 0))
            rp.restore()

            # Some slices vanish entirely for a frame; the rest sputter only a
            # few pixels so the effect reads as corrupted data, not sliding glass.
            if rng.random() < 0.24:
                continue

            rp.save()
            rp.setClipRect(band)
            rp.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            rp.setOpacity(rng.choice((0.38, 0.56, 0.74, 0.92, 1.0)))
            rp.drawPixmap(
                x_spasm + rng.choice((-4, -3, -2, 2, 3, 4)),
                y_spasm + rng.choice((-1, 0, 0, 1)),
                source,
            )
            rp.restore()

        rp.end()
        painter.drawPixmap(0, 0, result)

    def _paint_core_recovery(
        self,
        painter: QPainter,
        source: QPixmap,
        center: QPointF,
        progress: float,
    ) -> None:
        rng = self._core_bucket_rng(18.0, 6)
        if self._core_profile == 1:
            levels = (0.12, 0.26, 0.44, 0.64, 0.84, 1.0)
            index = min(len(levels) - 1, int(progress * len(levels)))
            target_height = max(5.0, self.height() * levels[index])
            target = QRectF(
                float(rng.choice((-1, 0, 0, 1))),
                center.y() - target_height / 2.0,
                float(self.width()),
                target_height,
            )
            painter.save()
            painter.setOpacity(rng.choice((0.62, 0.78, 0.92, 1.0)))
            painter.drawPixmap(target, source, QRectF(source.rect()))
            painter.restore()
            return

        remaining = max(0.0, 1.0 - progress)
        max_jitter = max(0, int(round(3.0 * remaining)))
        if max_jitter:
            dx = rng.randint(-max_jitter, max_jitter)
            dy = rng.randint(-max(1, max_jitter // 2), max(1, max_jitter // 2))
        else:
            dx = 0
            dy = 0
        opacity = min(
            1.0,
            0.58 + progress * 0.42 + rng.choice((-0.10, 0.0, 0.0, 0.08)),
        )
        painter.save()
        painter.setOpacity(max(0.35, opacity))
        painter.drawPixmap(dx, dy, source)
        painter.restore()

    def _advance_animation(self) -> None:
        self._advance_core_scheduler(time.perf_counter())
        super()._advance_animation()
