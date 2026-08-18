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
        self._phase = 0.0
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

    def _phase_step(self) -> float:
        return {
            AIDAStatus.STARTUP: 1.7,
            AIDAStatus.STANDBY: 0.65,
            AIDAStatus.LISTENING: 2.1,
            AIDAStatus.ANALYZING: 4.2,
            AIDAStatus.SPEAKING: 3.6,
            AIDAStatus.WARNING: 1.8,
            AIDAStatus.ERROR: 1.5,
            AIDAStatus.SHUTDOWN: 0.35,
        }[self._status]

    def _advance_animation(self) -> None:
        self._sync_visibility()
        self._phase = (self._phase + self._phase_step()) % 360.0

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
                rng.uniform(-2.0, 2.0),
                rng.uniform(-1.4, 1.4),
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

        idle_wave = 0.5 + 0.5 * math.sin(math.radians(self._phase * 1.55))
        notification_wave = 0.0
        if self._notification_progress > 0.0:
            notification_wave = math.sin((1.0 - self._notification_progress) * math.pi)

        transition_boost = 1.45 if self.activation_in_progress or self._reveal_frames > 0 else 1.0
        glow_boost = 0.30 + idle_wave * 0.14 + notification_wave * 0.50

        self._paint_pulse(painter, center)
        self._paint_ambient_glow(painter, full_rect, center, base_color, glow_boost)

        outer_radius = full_rect.width() * 0.485
        main_ring_radius = full_rect.width() * 0.365
        data_radius = full_rect.width() * 0.292
        core_radius = full_rect.width() * 0.220

        self._paint_outer_measure_ring(painter, center, outer_radius, base_color, bright_color)
        self._paint_main_ring(painter, center, main_ring_radius, base_color, bright_color, hot_color)
        self._paint_data_rings(painter, center, data_radius, base_color, bright_color, hot_color)

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

        core_center = QPointF(center.x() + self._core_jitter.x(), center.y() + self._core_jitter.y())
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

    def _paint_outer_measure_ring(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base_color: QColor,
        bright_color: QColor,
    ) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outline = QColor(base_color)
        outline.setAlpha(175)
        painter.setPen(self._pen(outline, 1.35))
        painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0))

        for index in range(96):
            angle = index * 3.75 + self._phase * 0.08
            angle_rad = math.radians(angle)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            long_tick = index % 8 == 0
            inner_radius = radius - (7.5 if long_tick else 4.5)
            outer_radius = radius + 0.5
            start = QPointF(center.x() + cos_a * inner_radius, center.y() + sin_a * inner_radius)
            end = QPointF(center.x() + cos_a * outer_radius, center.y() + sin_a * outer_radius)
            tick = QColor(bright_color if long_tick else base_color)
            tick.setAlpha(205 if long_tick else 78)
            painter.setPen(self._pen(tick, 1.10 if long_tick else 0.70, Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)

    def _paint_main_ring(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
    ) -> None:
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        deep_ring = QColor("#0A203B")
        deep_ring.setAlpha(245)
        painter.setPen(self._pen(deep_ring, 13.5))
        painter.drawEllipse(rect)

        bloom = QColor(base_color)
        bloom.setAlpha(95)
        painter.setPen(self._pen(bloom, 18.0))
        painter.drawEllipse(rect)

        ring = QColor(bright_color)
        ring.setAlpha(245)
        painter.setPen(self._pen(ring, 8.5))
        painter.drawEllipse(rect)

        highlight = QColor(hot_color)
        highlight.setAlpha(255)
        painter.setPen(self._pen(highlight, 4.6, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, int((38.0 + self._phase * 0.24) * 16), int(72.0 * 16))

        cool_sweep = QColor(base_color)
        cool_sweep.setAlpha(225)
        painter.setPen(self._pen(cool_sweep, 3.4, Qt.PenCapStyle.RoundCap))
        painter.drawArc(
            rect.adjusted(2.0, 2.0, -2.0, -2.0),
            int((218.0 - self._phase * 0.17) * 16),
            int(56.0 * 16),
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
        for scale, alpha in ((1.00, 62), (0.78, 48), (0.56, 38)):
            color = QColor(base_color)
            color.setAlpha(alpha)
            r = radius * scale
            painter.setPen(self._pen(color, 1.0))
            painter.drawEllipse(QRectF(center.x() - r, center.y() - r, r * 2.0, r * 2.0))

        arc_specs = (
            (0.96, -0.90, 146.0, 54.0, bright_color, 185, 1.45),
            (0.83, 0.72, 238.0, 38.0, base_color, 160, 1.20),
            (0.69, -0.58, 30.0, 28.0, hot_color, 150, 1.05),
            (0.60, 0.46, 292.0, 24.0, bright_color, 125, 0.95),
        )
        for scale, phase_scale, offset, span, source, alpha, width in arc_specs:
            r = radius * scale
            rect = QRectF(center.x() - r, center.y() - r, r * 2.0, r * 2.0)
            color = QColor(source)
            color.setAlpha(alpha)
            painter.setPen(self._pen(color, width, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect, int((self._phase * phase_scale + offset) * 16), int(span * 16))

        tick_radius = radius * 0.86
        for index in range(32):
            angle = index * 11.25 - self._phase * 0.22
            angle_rad = math.radians(angle)
            tangent = angle_rad + math.pi / 2.0
            anchor = QPointF(
                center.x() + math.cos(angle_rad) * tick_radius,
                center.y() + math.sin(angle_rad) * tick_radius,
            )
            length = 3.4 if index % 4 == 0 else 2.0
            start = QPointF(
                anchor.x() - math.cos(tangent) * length / 2.0,
                anchor.y() - math.sin(tangent) * length / 2.0,
            )
            end = QPointF(
                anchor.x() + math.cos(tangent) * length / 2.0,
                anchor.y() + math.sin(tangent) * length / 2.0,
            )
            color = QColor(bright_color)
            color.setAlpha(145 if index % 4 == 0 else 72)
            painter.setPen(self._pen(color, 0.85))
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
        halo_radius = radius * 1.58
        halo = QRadialGradient(center, halo_radius)
        halo_center = QColor(bright_color)
        halo_center.setAlpha(int(78 + glow_boost * 85))
        halo_mid = QColor(base_color)
        halo_mid.setAlpha(int(36 + glow_boost * 45))
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
        painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0))

        glass_ring = QColor(bright_color)
        glass_ring.setAlpha(190)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._pen(glass_ring, 1.35))
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
            QPointF(center.x() - radius * 1.28, center.y()),
            QPointF(center.x() + radius * 1.28, center.y()),
        )

        vertical = QColor(hot_color)
        vertical.setAlpha(125)
        painter.setPen(self._pen(vertical, 0.85))
        painter.drawLine(
            QPointF(center.x(), center.y() - radius * 0.38),
            QPointF(center.x(), center.y() + radius * 0.38),
        )

        flare_radius = radius * 0.42
        gradient = QRadialGradient(center, flare_radius)
        center_color = QColor("#FFFFFF")
        center_color.setAlpha(255)
        mid = QColor("#BDF1FF")
        mid.setAlpha(175)
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
        radius = 11.0 + eased * (self._orb_diameter * 0.63)
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
            painter.drawEllipse(QRectF(center.x() - r, center.y() - r, r * 2.0, r * 2.0))

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
        specs: list[tuple[float, float, int, float, float, float]]
        if self._glitch_style == self._MICRO_SPIKE:
            specs = [(0.0, 12.0, 74, 7.0, 6.6, 0.90)]
        elif self._glitch_style == self._CONDENSED_WAVE:
            specs = [(0.0, 20.0, 132, 11.5, 8.8, 1.08)]
        elif self._glitch_style == self._TOP_SEGMENT_SPUTTER:
            specs = [(90.0, 30.0, 125, 10.4, 8.4, 1.02)]
        elif self._glitch_style == self._LEFT_ARC_DISTORT:
            specs = [(180.0, 36.0, 138, 12.0, 9.2, 1.06)]
        elif self._glitch_style == self._FULL_RING_INTERFERENCE:
            specs = [
                (38.0, 27.0, 84, 10.2, 9.0, 0.96),
                (124.0, 27.0, 80, 10.2, 9.0, 0.96),
                (212.0, 27.0, 78, 10.2, 9.0, 0.96),
                (307.0, 27.0, 80, 10.2, 9.0, 0.96),
            ]
        else:
            self._paint_ring_glitch_band(
                painter,
                center,
                core_radius * 1.05,
                0.0,
                17.0,
                int(98 * transition_boost),
                8.6,
                5.6,
                base_color,
                bright_color,
                hot_color,
                0.86 * transition_boost,
            )
            self._paint_ring_glitch_band(
                painter,
                center,
                core_radius * 1.05,
                180.0,
                15.0,
                int(56 * transition_boost),
                5.8,
                4.8,
                base_color,
                bright_color,
                hot_color,
                0.62 * transition_boost,
            )
            return

        for angle, span, density, tangent, radial, intensity in specs:
            self._paint_ring_glitch_band(
                painter,
                center,
                ring_radius,
                angle,
                span,
                int(density * transition_boost),
                tangent,
                radial,
                base_color,
                bright_color,
                hot_color,
                intensity * transition_boost,
            )

    def _paint_ring_glitch_band(
        self,
        painter: QPainter,
        center: QPointF,
        ring_radius: float,
        angle_center: float,
        angle_span: float,
        fragments: int,
        tangent_spread: float,
        radial_spread: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
        intensity: float,
    ) -> None:
        """Render fragments strictly from the orb's circular geometry."""
        rng = random.Random(
            self._glitch_seed
            + self._glitch_frames * 131
            + int(angle_center * 17)
            + int(ring_radius * 11)
        )

        for _ in range(fragments):
            angle = angle_center + rng.uniform(-angle_span / 2.0, angle_span / 2.0)
            angle_rad = math.radians(angle)
            tangent_rad = angle_rad + math.pi / 2.0
            radial_offset = rng.uniform(-radial_spread * 0.28, radial_spread)
            orbit_radius = ring_radius + radial_offset
            tangent_offset = rng.uniform(-tangent_spread, tangent_spread) * intensity

            anchor_x = center.x() + math.cos(angle_rad) * orbit_radius
            anchor_y = center.y() + math.sin(angle_rad) * orbit_radius
            px = anchor_x + math.cos(tangent_rad) * tangent_offset
            py = anchor_y + math.sin(tangent_rad) * tangent_offset

            length = rng.uniform(1.2, 5.6) * (0.82 + intensity * 0.22)
            thickness = rng.uniform(0.8, 2.1)
            roll = rng.random()
            if roll < 0.12:
                color = QColor(hot_color)
                color.setAlpha(rng.randint(175, 245))
            elif roll < 0.55:
                color = QColor(bright_color)
                color.setAlpha(rng.randint(145, 230))
            else:
                color = QColor(base_color)
                color.setAlpha(rng.randint(105, 205))

            painter.save()
            painter.translate(px, py)
            painter.rotate(angle + 90.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRect(QRectF(-length / 2.0, -thickness / 2.0, length, thickness))
            painter.restore()

            if rng.random() < 0.30:
                streak_len = rng.uniform(3.0, 10.0) * intensity
                direction = -1.0 if rng.random() < 0.5 else 1.0
                streak = QColor(color)
                streak.setAlpha(min(255, color.alpha() + 20))
                painter.setPen(self._pen(streak, rng.uniform(0.65, 1.45), Qt.PenCapStyle.RoundCap))
                painter.drawLine(
                    QPointF(px, py),
                    QPointF(
                        px + math.cos(tangent_rad) * streak_len * direction,
                        py + math.sin(tangent_rad) * streak_len * direction,
                    ),
                )

            if rng.random() < 0.18:
                spike_len = rng.uniform(2.0, 6.2) * intensity
                outward = 1.0 if rng.random() < 0.78 else -1.0
                spike = QColor(bright_color)
                spike.setAlpha(rng.randint(110, 195))
                painter.setPen(self._pen(spike, rng.uniform(0.65, 1.20), Qt.PenCapStyle.RoundCap))
                painter.drawLine(
                    QPointF(anchor_x, anchor_y),
                    QPointF(
                        anchor_x + math.cos(angle_rad) * spike_len * outward,
                        anchor_y + math.sin(angle_rad) * spike_len * outward,
                    ),
                )

        arc = QColor(bright_color)
        arc.setAlpha(min(230, int(135 * intensity)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._pen(arc, 1.35, Qt.PenCapStyle.RoundCap))
        rect = QRectF(
            center.x() - ring_radius,
            center.y() - ring_radius,
            ring_radius * 2.0,
            ring_radius * 2.0,
        )
        painter.drawArc(
            rect,
            int((angle_center - angle_span * 0.48) * 16),
            int(angle_span * 0.70 * 16),
        )
        painter.drawArc(
            rect.adjusted(1.8, 1.8, -1.8, -1.8),
            int((angle_center - angle_span * 0.28) * 16),
            int(angle_span * 0.40 * 16),
        )

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
