from __future__ import annotations

import math
import random

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from aida.frontend.status import AIDAStatus


class AIDAOverlay(QWidget):
    """Floating always-on-top AIDA status orb."""

    clicked = Signal()

    _MICRO_SPIKE = 0
    _CONDENSED_WAVE = 1
    _TOP_SEGMENT_SPUTTER = 2
    _LEFT_ARC_DISTORT = 3
    _FULL_RING_INTERFERENCE = 4
    _CORE_JITTER = 5

    def __init__(self, diameter: int = 120) -> None:
        super().__init__()

        self._orb_diameter = diameter
        self._canvas_margin = 28
        canvas_size = diameter + self._canvas_margin * 2

        self._status = AIDAStatus.STARTUP
        self._breath_phase = 0.0
        self._ring_hot_rotation = 38.0
        self._ring_cool_rotation = 218.0
        self._data_rotations = [146.0, 238.0, 30.0, 292.0]
        self._data_tick_rotation = 0.0
        self._notification_progress = 0.0
        self._pulse_progress = 0.0

        self._rng = random.Random()
        self._glitch_frames = 0
        self._glitch_seed = 0
        self._glitch_style = self._MICRO_SPIKE
        self._frames_until_glitch = self._next_glitch_delay()

        self._activation_frames = 0
        self._activation_signal_sent = False
        self._reveal_frames = 0

        self._drag_press_global: QPoint | None = None
        self._drag_window_origin: QPoint | None = None
        self._dragging = False
        self._core_jitter = QPointF(0.0, 0.0)

        self.setFixedSize(canvas_size, canvas_size)
        self.setWindowTitle("AIDA Status")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setToolTip("Click to open AIDA • Right-drag to move")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(33)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._animation_timer.start()

    @staticmethod
    def _pen(
        color: QColor,
        width: float,
        cap: Qt.PenCapStyle | None = None,
    ) -> QPen:
        pen = QPen(color)
        pen.setWidthF(width)
        if cap is not None:
            pen.setCapStyle(cap)
        return pen

    @staticmethod
    def _wrapped(angle: float) -> float:
        return angle % 360.0

    @property
    def activation_in_progress(self) -> bool:
        return self._activation_frames > 0

    def set_status(self, status: AIDAStatus) -> None:
        if not isinstance(status, AIDAStatus):
            raise TypeError("status must be an AIDAStatus value")
        self._status = status
        self.setToolTip(f"AIDA status: {status.name}")
        self.update()

    def notify_message(self) -> None:
        self._notification_progress = 1.0
        self.update()

    def move_to_default_position(self, margin: int = 18) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(
            available.right() - self.width() - margin + 1,
            available.bottom() - self.height() - margin + 1,
        )

    def _main_window(self) -> QMainWindow | None:
        for widget in QApplication.topLevelWidgets():
            if widget is self:
                continue
            if isinstance(widget, QMainWindow) and widget.windowTitle() == "AIDA":
                return widget
        return None

    def _sync_visibility(self) -> None:
        window = self._main_window()
        if window is None:
            return

        minimized = bool(window.windowState() & Qt.WindowState.WindowMinimized)
        frontend_open = window.isVisible() and not minimized

        if frontend_open:
            if self.activation_in_progress or self._reveal_frames > 0:
                return
            if self.isVisible():
                self.hide()
            return

        if minimized and not self.isVisible() and not self.activation_in_progress:
            self._start_reveal()

    def _next_glitch_delay(self) -> int:
        # 33 ms frames => approximately 5–10 seconds.
        return self._rng.randint(152, 303)

    def _start_glitch(
        self,
        frames: int | None = None,
        style: int | None = None,
    ) -> None:
        if self._glitch_frames > 0:
            return
        self._glitch_style = self._rng.randrange(6) if style is None else style
        self._glitch_seed = self._rng.randint(0, 1_000_000)
        self._glitch_frames = frames if frames is not None else self._rng.randint(4, 7)

    def _start_reveal(self) -> None:
        self._reveal_frames = 1
        self._pulse_progress = 0.001
        self._glitch_frames = 0
        self._start_glitch(frames=12)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.update()

    def _start_activation(self) -> None:
        if self.activation_in_progress:
            return
        self._activation_frames = 1
        self._activation_signal_sent = False
        self._pulse_progress = 0.001
        self._glitch_frames = 0
        self._start_glitch(frames=14)
        self.setWindowOpacity(1.0)
        self.update()

    def _motion_scale(self) -> float:
        return {
            AIDAStatus.STARTUP: 1.25,
            AIDAStatus.STANDBY: 0.72,
            AIDAStatus.LISTENING: 1.45,
            AIDAStatus.ANALYZING: 2.15,
            AIDAStatus.SPEAKING: 1.80,
            AIDAStatus.WARNING: 1.30,
            AIDAStatus.ERROR: 1.20,
            AIDAStatus.SHUTDOWN: 0.30,
        }[self._status]

    def _advance_rotations(self) -> None:
        scale = self._motion_scale()
        self._breath_phase = self._wrapped(self._breath_phase + 0.82 * scale)
        self._ring_hot_rotation = self._wrapped(self._ring_hot_rotation + 0.72 * scale)
        self._ring_cool_rotation = self._wrapped(self._ring_cool_rotation - 0.51 * scale)

        velocities = (-0.86, 0.63, -0.47, 0.38)
        for index, velocity in enumerate(velocities):
            self._data_rotations[index] = self._wrapped(
                self._data_rotations[index] + velocity * scale
            )
        self._data_tick_rotation = self._wrapped(
            self._data_tick_rotation - 0.34 * scale
        )

    def _advance_animation(self) -> None:
        self._sync_visibility()
        self._advance_rotations()

        if self._notification_progress > 0.0:
            self._notification_progress = max(
                0.0,
                self._notification_progress - 0.05,
            )

        if self._pulse_progress > 0.0:
            self._pulse_progress += 0.065
            if self._pulse_progress >= 1.0:
                self._pulse_progress = 0.0

        if self._glitch_frames > 0:
            self._glitch_frames -= 1
        elif self.isVisible() and not self.activation_in_progress and self._reveal_frames == 0:
            self._frames_until_glitch -= 1
            if self._frames_until_glitch <= 0:
                self._start_glitch()
                self._frames_until_glitch = self._next_glitch_delay()

        if self._glitch_style == self._CORE_JITTER and self._glitch_frames > 0:
            rng = random.Random(self._glitch_seed + self._glitch_frames * 73)
            self._core_jitter = QPointF(
                rng.uniform(-1.7, 1.7),
                rng.uniform(-1.2, 1.2),
            )
        else:
            self._core_jitter = QPointF(0.0, 0.0)

        if self._reveal_frames > 0:
            self._advance_reveal()
        if self.activation_in_progress:
            self._advance_activation()
        self.update()

    def _advance_reveal(self) -> None:
        self._reveal_frames += 1
        progress = min(1.0, self._reveal_frames / 14.0)
        eased = 1.0 - (1.0 - progress) ** 2
        self.setWindowOpacity(eased)
        if self._reveal_frames >= 14:
            self._reveal_frames = 0
            self.setWindowOpacity(1.0)
            self._frames_until_glitch = self._next_glitch_delay()

    def _advance_activation(self) -> None:
        self._activation_frames += 1
        if self._activation_frames >= 6 and not self._activation_signal_sent:
            self._activation_signal_sent = True
            self.clicked.emit()

        if self._activation_frames >= 6:
            fade_progress = min(1.0, (self._activation_frames - 6) / 11.0)
            self.setWindowOpacity(max(0.0, 1.0 - fade_progress))

        if self._activation_frames >= 17:
            self._activation_frames = 0
            self.setWindowOpacity(1.0)
            self.hide()
            self._frames_until_glitch = self._next_glitch_delay()

    @staticmethod
    def _palette() -> tuple[QColor, QColor, QColor, QColor, QColor]:
        return (
            QColor("#278DFF"),
            QColor("#6EDBFF"),
            QColor("#F2FDFF"),
            QColor("#071A31"),
            QColor("#020711"),
        )

    def _orb_rect(self) -> QRectF:
        margin = float(self._canvas_margin)
        return QRectF(margin, margin, float(self._orb_diameter), float(self._orb_diameter))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        full_rect = self._orb_rect().adjusted(2.0, 2.0, -2.0, -2.0)
        center = full_rect.center()
        base_color, bright_color, hot_color, deep_color, edge_color = self._palette()

        idle_wave = 0.5 + 0.5 * math.sin(math.radians(self._breath_phase * 1.55))
        notification_wave = 0.0
        if self._notification_progress > 0.0:
            notification_wave = math.sin((1.0 - self._notification_progress) * math.pi)

        transition_boost = 1.45 if self.activation_in_progress or self._reveal_frames > 0 else 1.0
        glow_boost = 0.30 + idle_wave * 0.14 + notification_wave * 0.50

        self._paint_pulse(painter, center)
        self._paint_ambient_glow(painter, full_rect, center, base_color, glow_boost)

        # The luminous ring now occupies the former outer-divider position.
        main_ring_radius = full_rect.width() * 0.465
        data_radius = full_rect.width() * 0.302
        core_radius = full_rect.width() * 0.205

        self._paint_main_ring(
            painter,
            center,
            main_ring_radius,
            base_color,
            bright_color,
            hot_color,
        )
        self._paint_data_rings(
            painter,
            center,
            data_radius,
            base_color,
            bright_color,
            hot_color,
        )

        if self._glitch_frames > 0:
            self._paint_glitch(
                painter,
                center,
                main_ring_radius,
                core_radius,
                base_color,
                bright_color,
                hot_color,
                transition_boost,
            )

        core_center = QPointF(
            center.x() + self._core_jitter.x(),
            center.y() + self._core_jitter.y(),
        )
        self._paint_energy_core(
            painter,
            core_center,
            core_radius,
            base_color,
            bright_color,
            hot_color,
            deep_color,
            edge_color,
            glow_boost,
        )
        self._paint_core_flare(painter, center, core_radius, hot_color)
        painter.end()

    def _paint_ambient_glow(
        self,
        painter: QPainter,
        full_rect: QRectF,
        center: QPointF,
        base_color: QColor,
        glow_boost: float,
    ) -> None:
        glow_rect = full_rect.adjusted(-8.0, -8.0, 8.0, 8.0)
        gradient = QRadialGradient(center, glow_rect.width() / 2.0)
        inner = QColor(base_color)
        inner.setAlpha(int(42 + glow_boost * 145))
        middle = QColor(base_color)
        middle.setAlpha(int(18 + glow_boost * 78))
        edge = QColor(base_color)
        edge.setAlpha(0)
        gradient.setColorAt(0.0, inner)
        gradient.setColorAt(0.58, middle)
        gradient.setColorAt(1.0, edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(glow_rect)

    def _paint_main_ring(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
    ) -> None:
        rect = QRectF(
            center.x() - radius,
            center.y() - radius,
            radius * 2.0,
            radius * 2.0,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)

        glow = QColor(base_color)
        glow.setAlpha(92)
        painter.setPen(self._pen(glow, 14.5))
        painter.drawEllipse(rect)

        ring = QColor(bright_color)
        ring.setAlpha(248)
        painter.setPen(self._pen(ring, 7.4))
        painter.drawEllipse(rect)

        inner_edge = QColor("#1D86DC")
        inner_edge.setAlpha(215)
        painter.setPen(self._pen(inner_edge, 2.0))
        painter.drawEllipse(rect.adjusted(3.0, 3.0, -3.0, -3.0))

        highlight = QColor(hot_color)
        highlight.setAlpha(250)
        painter.setPen(
            self._pen(highlight, 3.4, Qt.PenCapStyle.RoundCap)
        )
        painter.drawArc(
            rect,
            int(self._ring_hot_rotation * 16),
            int(68.0 * 16),
        )

        cool_sweep = QColor(base_color)
        cool_sweep.setAlpha(225)
        painter.setPen(
            self._pen(cool_sweep, 2.6, Qt.PenCapStyle.RoundCap)
        )
        painter.drawArc(
            rect.adjusted(1.8, 1.8, -1.8, -1.8),
            int(self._ring_cool_rotation * 16),
            int(50.0 * 16),
        )

    def _paint_data_rings(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
    ) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for scale, alpha in ((1.00, 58), (0.76, 46), (0.52, 34)):
            color = QColor(base_color)
            color.setAlpha(alpha)
            r = radius * scale
            painter.setPen(self._pen(color, 0.95))
            painter.drawEllipse(
                QRectF(
                    center.x() - r,
                    center.y() - r,
                    r * 2.0,
                    r * 2.0,
                )
            )

        arc_specs = (
            (0.98, 54.0, bright_color, 178, 1.35),
            (0.82, 38.0, base_color, 154, 1.12),
            (0.67, 28.0, hot_color, 145, 1.00),
            (0.57, 24.0, bright_color, 120, 0.90),
        )
        for index, (scale, span, source, alpha, width) in enumerate(arc_specs):
            r = radius * scale
            rect = QRectF(
                center.x() - r,
                center.y() - r,
                r * 2.0,
                r * 2.0,
            )
            color = QColor(source)
            color.setAlpha(alpha)
            painter.setPen(
                self._pen(color, width, Qt.PenCapStyle.RoundCap)
            )
            painter.drawArc(
                rect,
                int(self._data_rotations[index] * 16),
                int(span * 16),
            )

        tick_radius = radius * 0.87
        for index in range(28):
            angle = index * (360.0 / 28.0) + self._data_tick_rotation
            angle_rad = math.radians(angle)
            tangent = angle_rad + math.pi / 2.0
            anchor = QPointF(
                center.x() + math.cos(angle_rad) * tick_radius,
                center.y() + math.sin(angle_rad) * tick_radius,
            )
            length = 3.0 if index % 4 == 0 else 1.8
            start = QPointF(
                anchor.x() - math.cos(tangent) * length / 2.0,
                anchor.y() - math.sin(tangent) * length / 2.0,
            )
            end = QPointF(
                anchor.x() + math.cos(tangent) * length / 2.0,
                anchor.y() + math.sin(tangent) * length / 2.0,
            )
            color = QColor(bright_color)
            color.setAlpha(132 if index % 4 == 0 else 64)
            painter.setPen(self._pen(color, 0.80))
            painter.drawLine(start, end)

    def _paint_energy_core(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
        deep_color: QColor,
        edge_color: QColor,
        glow_boost: float,
    ) -> None:
        halo_radius = radius * 1.72
        halo = QRadialGradient(center, halo_radius)
        halo_center = QColor(bright_color)
        halo_center.setAlpha(int(82 + glow_boost * 88))
        halo_mid = QColor(base_color)
        halo_mid.setAlpha(int(38 + glow_boost * 48))
        halo_edge = QColor(base_color)
        halo_edge.setAlpha(0)
        halo.setColorAt(0.0, halo_center)
        halo.setColorAt(0.48, halo_mid)
        halo.setColorAt(1.0, halo_edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(
            QRectF(
                center.x() - halo_radius,
                center.y() - halo_radius,
                halo_radius * 2.0,
                halo_radius * 2.0,
            )
        )

        body = QRadialGradient(center, radius)
        white = QColor(hot_color)
        white.setAlpha(255)
        cyan = QColor(bright_color)
        cyan.setAlpha(248)
        blue = QColor(base_color)
        blue.setAlpha(215)
        deep = QColor(deep_color)
        deep.setAlpha(248)
        edge = QColor(edge_color)
        edge.setAlpha(252)
        body.setColorAt(0.0, white)
        body.setColorAt(0.12, cyan)
        body.setColorAt(0.30, blue)
        body.setColorAt(0.68, deep)
        body.setColorAt(1.0, edge)
        painter.setBrush(body)
        painter.drawEllipse(
            QRectF(
                center.x() - radius,
                center.y() - radius,
                radius * 2.0,
                radius * 2.0,
            )
        )

        glass_ring = QColor(bright_color)
        glass_ring.setAlpha(188)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._pen(glass_ring, 1.25))
        glass_radius = radius * 0.92
        painter.drawEllipse(
            QRectF(
                center.x() - glass_radius,
                center.y() - glass_radius,
                glass_radius * 2.0,
                glass_radius * 2.0,
            )
        )

    def _paint_core_flare(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        hot_color: QColor,
    ) -> None:
        flare = QColor(hot_color)
        flare.setAlpha(220)
        painter.setPen(self._pen(flare, 1.25))
        painter.drawLine(
            QPointF(center.x() - radius * 1.36, center.y()),
            QPointF(center.x() + radius * 1.36, center.y()),
        )

        vertical = QColor(hot_color)
        vertical.setAlpha(120)
        painter.setPen(self._pen(vertical, 0.80))
        painter.drawLine(
            QPointF(center.x(), center.y() - radius * 0.38),
            QPointF(center.x(), center.y() + radius * 0.38),
        )

        flare_radius = radius * 0.44
        gradient = QRadialGradient(center, flare_radius)
        center_color = QColor("#FFFFFF")
        center_color.setAlpha(255)
        mid = QColor("#BDF1FF")
        mid.setAlpha(178)
        edge = QColor("#6EDBFF")
        edge.setAlpha(0)
        gradient.setColorAt(0.0, center_color)
        gradient.setColorAt(0.52, mid)
        gradient.setColorAt(1.0, edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(
            QRectF(
                center.x() - flare_radius,
                center.y() - flare_radius,
                flare_radius * 2.0,
                flare_radius * 2.0,
            )
        )

    def _paint_pulse(self, painter: QPainter, center: QPointF) -> None:
        progress = self._pulse_progress
        if progress <= 0.0:
            return

        eased = 1.0 - (1.0 - progress) ** 2
        radius = 11.0 + eased * (self._orb_diameter * 0.66)
        base_alpha = int(135 * (1.0 - progress) ** 1.45)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for offset, width, scale in (
            (0.0, 2.3, 1.0),
            (4.0, 1.55, 0.55),
            (8.5, 1.0, 0.28),
        ):
            color = QColor("#6EDBFF")
            color.setAlpha(int(base_alpha * scale))
            painter.setPen(self._pen(color, width))
            r = radius + offset
            painter.drawEllipse(
                QRectF(
                    center.x() - r,
                    center.y() - r,
                    r * 2.0,
                    r * 2.0,
                )
            )

    def _paint_glitch(
        self,
        painter: QPainter,
        center: QPointF,
        ring_radius: float,
        core_radius: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
        transition_boost: float,
    ) -> None:
        specs: list[tuple[float, float, int, float, float]]

        if self._glitch_style == self._MICRO_SPIKE:
            specs = [(0.0, 11.0, 13, 1.5, 0.90)]
        elif self._glitch_style == self._CONDENSED_WAVE:
            specs = [(0.0, 20.0, 23, 2.6, 1.08)]
        elif self._glitch_style == self._TOP_SEGMENT_SPUTTER:
            specs = [(90.0, 29.0, 28, 2.4, 1.03)]
        elif self._glitch_style == self._LEFT_ARC_DISTORT:
            specs = [(180.0, 35.0, 32, 3.0, 1.07)]
        elif self._glitch_style == self._FULL_RING_INTERFERENCE:
            specs = [
                (38.0, 24.0, 20, 2.5, 0.96),
                (124.0, 24.0, 19, 2.4, 0.96),
                (212.0, 24.0, 19, 2.4, 0.96),
                (307.0, 24.0, 19, 2.5, 0.96),
            ]
        else:
            # Core jitter still disturbs the nearest circular data boundary.
            self._paint_integrated_arc_glitch(
                painter,
                center,
                core_radius * 1.18,
                0.0,
                18.0,
                int(20 * transition_boost),
                2.0,
                base_color,
                bright_color,
                hot_color,
                0.88 * transition_boost,
                source_width=2.2,
            )
            self._paint_integrated_arc_glitch(
                painter,
                center,
                core_radius * 1.18,
                180.0,
                15.0,
                int(12 * transition_boost),
                1.6,
                base_color,
                bright_color,
                hot_color,
                0.64 * transition_boost,
                source_width=2.0,
            )
            return

        for angle, span, slices, displacement, intensity in specs:
            self._paint_integrated_arc_glitch(
                painter,
                center,
                ring_radius,
                angle,
                span,
                max(8, int(slices * transition_boost)),
                displacement,
                base_color,
                bright_color,
                hot_color,
                intensity * transition_boost,
                source_width=7.6,
            )

    def _paint_integrated_arc_glitch(
        self,
        painter: QPainter,
        center: QPointF,
        ring_radius: float,
        angle_center: float,
        angle_span: float,
        slices: int,
        displacement: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
        intensity: float,
        *,
        source_width: float,
    ) -> None:
        """Break and displace the ring's own pixels instead of overlaying a cloud."""
        rng = random.Random(
            self._glitch_seed
            + self._glitch_frames * 149
            + int(angle_center * 19)
            + int(ring_radius * 13)
        )

        source_rect = QRectF(
            center.x() - ring_radius,
            center.y() - ring_radius,
            ring_radius * 2.0,
            ring_radius * 2.0,
        )
        slice_span = max(0.42, angle_span / max(1, slices) * 0.76)

        # First remove tiny source slices. Those holes make the distortion read as
        # the actual ring breaking rather than a separate sprite placed over it.
        painter.save()
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Clear
        )
        clear_pen = self._pen(QColor(0, 0, 0, 0), source_width + 1.8)
        painter.setPen(clear_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        source_angles: list[float] = []
        for _ in range(slices):
            angle = angle_center + rng.uniform(-angle_span / 2.0, angle_span / 2.0)
            source_angles.append(angle)
            painter.drawArc(
                source_rect,
                int((angle - slice_span / 2.0) * 16),
                max(1, int(slice_span * 16)),
            )
        painter.restore()

        # Redraw those exact slices nearby with tiny radial/tangential shears.
        for index, angle in enumerate(source_angles):
            frame_rng = random.Random(
                self._glitch_seed
                + self._glitch_frames * 211
                + index * 31
                + int(angle * 7)
            )
            angle_rad = math.radians(angle)
            radial_shift = frame_rng.uniform(-0.6, displacement) * intensity
            angular_shift = frame_rng.uniform(-1.2, 1.2) * intensity
            shifted_radius = ring_radius + radial_shift
            shifted_rect = QRectF(
                center.x() - shifted_radius,
                center.y() - shifted_radius,
                shifted_radius * 2.0,
                shifted_radius * 2.0,
            )

            color_roll = frame_rng.random()
            if color_roll < 0.11:
                color = QColor(hot_color)
                color.setAlpha(frame_rng.randint(205, 250))
            elif color_roll < 0.54:
                color = QColor(bright_color)
                color.setAlpha(frame_rng.randint(185, 245))
            else:
                color = QColor(base_color)
                color.setAlpha(frame_rng.randint(160, 225))

            displaced_pen = self._pen(
                color,
                max(1.0, source_width - frame_rng.uniform(0.4, 1.8)),
                Qt.PenCapStyle.FlatCap,
            )
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(displaced_pen)
            painter.drawArc(
                shifted_rect,
                int((angle + angular_shift - slice_span / 2.0) * 16),
                max(1, int(slice_span * frame_rng.uniform(0.72, 1.18) * 16)),
            )

            # A few micro-fragments peel from the exact source coordinate.
            if frame_rng.random() < 0.42:
                source_x = center.x() + math.cos(angle_rad) * ring_radius
                source_y = center.y() + math.sin(angle_rad) * ring_radius
                tangent_rad = angle_rad + math.pi / 2.0
                tangent_len = frame_rng.uniform(1.5, 4.8) * intensity
                radial_len = frame_rng.uniform(0.5, 2.8) * intensity
                direction = -1.0 if frame_rng.random() < 0.5 else 1.0
                end = QPointF(
                    source_x
                    + math.cos(tangent_rad) * tangent_len * direction
                    + math.cos(angle_rad) * radial_len,
                    source_y
                    + math.sin(tangent_rad) * tangent_len * direction
                    + math.sin(angle_rad) * radial_len,
                )
                fragment = QColor(color)
                fragment.setAlpha(min(255, color.alpha() + 8))
                painter.setPen(
                    self._pen(
                        fragment,
                        frame_rng.uniform(0.55, 1.25),
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                painter.drawLine(QPointF(source_x, source_y), end)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_activation()
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._drag_press_global = event.globalPosition().toPoint()
            self._drag_window_origin = self.frameGeometry().topLeft()
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._dragging
            and self._drag_press_global is not None
            and self._drag_window_origin is not None
            and event.buttons() & Qt.MouseButton.RightButton
        ):
            movement = event.globalPosition().toPoint() - self._drag_press_global
            self.move(self._drag_window_origin + movement)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._drag_press_global = None
            self._drag_window_origin = None
            self._dragging = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            event.accept()
            return

        super().mouseReleaseEvent(event)
