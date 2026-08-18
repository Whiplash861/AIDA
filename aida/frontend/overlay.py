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

    def __init__(self, diameter: int = 112) -> None:
        super().__init__()

        self._orb_diameter = diameter
        self._canvas_margin = 22
        canvas_size = diameter + self._canvas_margin * 2

        self._status = AIDAStatus.STARTUP
        self._phase = 0.0
        self._notification_progress = 0.0
        self._click_wave_progress = 0.0

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

        self._core_jitter_offset = QPointF(0.0, 0.0)

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

    def _start_glitch(self, frames: int | None = None, style: int | None = None) -> None:
        if self._glitch_frames > 0:
            return
        self._glitch_style = self._rng.randrange(6) if style is None else style
        self._glitch_seed = self._rng.randint(0, 1_000_000)
        self._glitch_frames = frames if frames is not None else self._rng.randint(4, 7)

    def _start_reveal(self) -> None:
        self._reveal_frames = 1
        self._click_wave_progress = 0.001
        self._start_glitch(frames=9)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.update()

    def _start_activation(self) -> None:
        if self.activation_in_progress:
            return
        self._activation_frames = 1
        self._activation_signal_sent = False
        self._click_wave_progress = 0.001
        self._glitch_frames = 0
        self._start_glitch(frames=11)
        self.setWindowOpacity(1.0)
        self.update()

    def _advance_animation(self) -> None:
        self._sync_visibility()

        step = {
            AIDAStatus.STARTUP: 2.0,
            AIDAStatus.STANDBY: 0.8,
            AIDAStatus.LISTENING: 2.4,
            AIDAStatus.ANALYZING: 4.8,
            AIDAStatus.SPEAKING: 4.0,
            AIDAStatus.WARNING: 2.0,
            AIDAStatus.ERROR: 1.8,
            AIDAStatus.SHUTDOWN: 0.4,
        }[self._status]
        self._phase = (self._phase + step) % 360.0

        if self._notification_progress > 0.0:
            self._notification_progress = max(0.0, self._notification_progress - 0.055)

        if self._click_wave_progress > 0.0:
            self._click_wave_progress += 0.072
            if self._click_wave_progress >= 1.0:
                self._click_wave_progress = 0.0

        if self._glitch_frames > 0:
            self._glitch_frames -= 1
        elif self.isVisible() and not self.activation_in_progress and self._reveal_frames == 0:
            self._frames_until_glitch -= 1
            if self._frames_until_glitch <= 0:
                self._start_glitch()
                self._frames_until_glitch = self._next_glitch_delay()

        if self._glitch_style == self._CORE_JITTER and self._glitch_frames > 0:
            rng = random.Random(self._glitch_seed + self._glitch_frames * 53)
            self._core_jitter_offset = QPointF(
                rng.uniform(-1.5, 1.5),
                rng.uniform(-1.2, 1.2),
            )
        else:
            self._core_jitter_offset = QPointF(0.0, 0.0)

        if self._reveal_frames > 0:
            self._advance_reveal()

        if self.activation_in_progress:
            self._advance_activation()

        self.update()

    def _advance_reveal(self) -> None:
        self._reveal_frames += 1
        progress = min(1.0, self._reveal_frames / 11.0)
        eased = 1.0 - (1.0 - progress) ** 2
        self.setWindowOpacity(eased)
        if self._reveal_frames >= 11:
            self._reveal_frames = 0
            self.setWindowOpacity(1.0)
            self._frames_until_glitch = self._next_glitch_delay()

    def _advance_activation(self) -> None:
        self._activation_frames += 1

        if self._activation_frames >= 5 and not self._activation_signal_sent:
            self._activation_signal_sent = True
            self.clicked.emit()

        if self._activation_frames >= 5:
            fade_progress = min(1.0, (self._activation_frames - 5) / 8.0)
            self.setWindowOpacity(max(0.0, 1.0 - fade_progress))

        if self._activation_frames >= 13:
            self._activation_frames = 0
            self.setWindowOpacity(1.0)
            self.hide()
            self._frames_until_glitch = self._next_glitch_delay()

    @staticmethod
    def _base_palette() -> tuple[QColor, QColor, QColor, QColor, QColor]:
        return (
            QColor("#53b8ff"),
            QColor("#82d7ff"),
            QColor("#dff8ff"),
            QColor("#0b1b31"),
            QColor("#040b15"),
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

        base_color, bright_color, hot_color, deep_color, edge_color = self._base_palette()

        idle_wave = 0.5 + 0.5 * math.sin(math.radians(self._phase * 1.7))
        notification_wave = 0.0
        if self._notification_progress > 0.0:
            notification_wave = math.sin((1.0 - self._notification_progress) * math.pi)
        glow_boost = 0.18 + idle_wave * 0.12 + notification_wave * 0.55

        self._paint_click_wave(painter, center, base_color)

        ambient_rect = full_rect.adjusted(-3.0, -3.0, 3.0, 3.0)
        ambient_gradient = QRadialGradient(center, ambient_rect.width() / 2.0 + notification_wave * 9.0)
        c0 = QColor(base_color)
        c0.setAlpha(int(35 + glow_boost * 150))
        c1 = QColor(base_color)
        c1.setAlpha(int(16 + glow_boost * 70))
        c2 = QColor(base_color)
        c2.setAlpha(0)
        ambient_gradient.setColorAt(0.0, c0)
        ambient_gradient.setColorAt(0.55, c1)
        ambient_gradient.setColorAt(1.0, c2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ambient_gradient)
        painter.drawEllipse(ambient_rect)

        self._paint_outer_measure_ring(painter, center, full_rect.width() * 0.485, base_color, bright_color)
        self._paint_energy_ring(painter, center, full_rect.width() * 0.37, base_color, bright_color, hot_color)
        self._paint_inner_rings(painter, center, full_rect.width() * 0.29, base_color)

        if self._glitch_frames > 0:
            self._paint_glitch(painter, center, full_rect.width() * 0.37, base_color, bright_color, hot_color)

        core_center = QPointF(center.x() + self._core_jitter_offset.x(), center.y() + self._core_jitter_offset.y())
        self._paint_core(painter, core_center, full_rect.width() * 0.235, base_color, bright_color, hot_color, deep_color, edge_color, glow_boost)
        self._paint_center_flare(painter, center, full_rect.width() * 0.21, hot_color)

        painter.end()

    def _paint_outer_measure_ring(self, painter: QPainter, center: QPointF, radius: float, base_color: QColor, bright_color: QColor) -> None:
        outer_color = QColor(base_color)
        outer_color.setAlpha(180)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(outer_color, 1.3))
        painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0))

        tick_radius_outer = radius + 0.3
        tick_radius_inner = radius - 5.4
        for index in range(72):
            angle = index * 5.0 + self._phase * 0.08
            angle_rad = math.radians(angle)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            inner = tick_radius_inner + (-1.7 if index % 6 == 0 else 0.0)
            start = QPointF(center.x() + cos_a * inner, center.y() + sin_a * inner)
            end = QPointF(center.x() + cos_a * tick_radius_outer, center.y() + sin_a * tick_radius_outer)
            tick_color = QColor(bright_color if index % 9 == 0 else base_color)
            tick_color.setAlpha(210 if index % 9 == 0 else 95)
            painter.setPen(QPen(tick_color, 1.1 if index % 9 == 0 else 0.8, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)

    def _paint_energy_ring(self, painter: QPainter, center: QPointF, radius: float, base_color: QColor, bright_color: QColor, hot_color: QColor) -> None:
        ring_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)

        shadow_color = QColor("#102645")
        shadow_color.setAlpha(230)
        painter.setPen(QPen(shadow_color, 10.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(ring_rect)

        glow_color = QColor(base_color)
        glow_color.setAlpha(120)
        painter.setPen(QPen(glow_color, 13.0))
        painter.drawEllipse(ring_rect)

        ring_color = QColor(bright_color)
        ring_color.setAlpha(240)
        painter.setPen(QPen(ring_color, 8.2))
        painter.drawEllipse(ring_rect)

        sweep_color = QColor(hot_color)
        sweep_color.setAlpha(255)
        painter.setPen(QPen(sweep_color, 5.0, cap=Qt.PenCapStyle.RoundCap))
        painter.drawArc(ring_rect, int((42.0 + self._phase * 0.25) * 16), int(70.0 * 16))

        secondary = QColor(base_color)
        secondary.setAlpha(210)
        painter.setPen(QPen(secondary, 3.3, cap=Qt.PenCapStyle.RoundCap))
        painter.drawArc(ring_rect.adjusted(2.2, 2.2, -2.2, -2.2), int((218.0 - self._phase * 0.18) * 16), int(54.0 * 16))

    def _paint_inner_rings(self, painter: QPainter, center: QPointF, radius: float, base_color: QColor) -> None:
        line_color = QColor(base_color)
        line_color.setAlpha(58)
        painter.setPen(QPen(line_color, 1.0))
        painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0))
        painter.drawEllipse(QRectF(center.x() - radius * 0.72, center.y() - radius * 0.72, radius * 1.44, radius * 1.44))

    def _paint_core(
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
        core_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        gradient = QRadialGradient(center, radius)
        c0 = QColor(hot_color)
        c0.setAlpha(250)
        c1 = QColor(bright_color)
        c1.setAlpha(int(210 + glow_boost * 35))
        c2 = QColor(base_color)
        c2.setAlpha(185)
        c3 = QColor(deep_color)
        c3.setAlpha(245)
        c4 = QColor(edge_color)
        c4.setAlpha(250)
        gradient.setColorAt(0.0, c0)
        gradient.setColorAt(0.14, c1)
        gradient.setColorAt(0.32, c2)
        gradient.setColorAt(0.72, c3)
        gradient.setColorAt(1.0, c4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(core_rect)

    def _paint_center_flare(self, painter: QPainter, center: QPointF, radius: float, hot_color: QColor) -> None:
        flare = QColor(hot_color)
        flare.setAlpha(190)
        painter.setPen(QPen(flare, 1.1))
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius * 0.06), QPointF(center.x(), center.y() + radius * 0.06))

        dot_gradient = QRadialGradient(center, radius * 0.33)
        d0 = QColor("#f7ffff")
        d0.setAlpha(255)
        d1 = QColor("#9ce6ff")
        d1.setAlpha(120)
        d2 = QColor("#9ce6ff")
        d2.setAlpha(0)
        dot_gradient.setColorAt(0.0, d0)
        dot_gradient.setColorAt(0.55, d1)
        dot_gradient.setColorAt(1.0, d2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_gradient)
        r = radius * 0.33
        painter.drawEllipse(QRectF(center.x() - r, center.y() - r, r * 2.0, r * 2.0))

    def _paint_click_wave(self, painter: QPainter, center: QPointF, base_color: QColor) -> None:
        progress = self._click_wave_progress
        if progress <= 0.0:
            return

        eased = 1.0 - (1.0 - progress) ** 2
        radius = 10.0 + eased * (self._orb_diameter * 0.56)
        alpha = int(110 * (1.0 - progress) ** 1.5)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for offset, width, scale in ((0.0, 2.1, 1.0), (4.0, 1.35, 0.55), (8.0, 0.95, 0.28)):
            color = QColor("#82d7ff")
            color.setAlpha(int(alpha * scale))
            painter.setPen(QPen(color, width))
            painter.drawEllipse(QRectF(center.x() - radius - offset, center.y() - radius - offset, (radius + offset) * 2.0, (radius + offset) * 2.0))

        fill = QColor(base_color)
        fill.setAlpha(int(30 * (1.0 - progress)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        inner = max(2.0, radius * 0.35)
        painter.drawEllipse(QRectF(center.x() - inner, center.y() - inner, inner * 2.0, inner * 2.0))

    def _paint_glitch(self, painter: QPainter, center: QPointF, ring_radius: float, base_color: QColor, bright_color: QColor, hot_color: QColor) -> None:
        if self._glitch_style == self._MICRO_SPIKE:
            self._paint_arc_glitch_cloud(painter, center, ring_radius, 0.0, 14.0, 68, 7.0, 7.5, base_color, bright_color, hot_color, 0.9)
        elif self._glitch_style == self._CONDENSED_WAVE:
            self._paint_arc_glitch_cloud(painter, center, ring_radius, -3.0, 18.0, 118, 11.5, 10.5, base_color, bright_color, hot_color, 1.15)
        elif self._glitch_style == self._TOP_SEGMENT_SPUTTER:
            self._paint_arc_glitch_cloud(painter, center, ring_radius, 90.0, 28.0, 110, 10.0, 8.0, base_color, bright_color, hot_color, 1.0)
        elif self._glitch_style == self._LEFT_ARC_DISTORT:
            self._paint_arc_glitch_cloud(painter, center, ring_radius, 182.0, 34.0, 124, 12.0, 9.5, base_color, bright_color, hot_color, 1.08)
        elif self._glitch_style == self._FULL_RING_INTERFERENCE:
            for angle, density in ((42.0, 80), (126.0, 76), (214.0, 74), (310.0, 72)):
                self._paint_arc_glitch_cloud(painter, center, ring_radius, angle, 26.0, density, 10.0, 9.2, base_color, bright_color, hot_color, 0.95)
        elif self._glitch_style == self._CORE_JITTER:
            self._paint_arc_glitch_cloud(painter, center, ring_radius * 0.88, 0.0, 16.0, 96, 8.5, 6.5, base_color, bright_color, hot_color, 0.82)
            self._paint_arc_glitch_cloud(painter, center, ring_radius * 0.88, 180.0, 14.0, 54, 6.0, 5.0, base_color, bright_color, hot_color, 0.6)

    def _paint_arc_glitch_cloud(
        self,
        painter: QPainter,
        center: QPointF,
        ring_radius: float,
        angle_center: float,
        angle_span: float,
        density: int,
        tangent_spread: float,
        radial_spread: float,
        base_color: QColor,
        bright_color: QColor,
        hot_color: QColor,
        intensity: float,
    ) -> None:
        rng = random.Random(
            self._glitch_seed
            + self._glitch_frames * 137
            + int(angle_center * 10)
            + int(ring_radius * 10)
        )

        painter.setPen(Qt.PenStyle.NoPen)
        tangent_lengths = [2.8, 4.0, 5.6, 7.2, 8.4]

        for _ in range(density):
            angle = angle_center + rng.uniform(-angle_span / 2.0, angle_span / 2.0)
            angle_rad = math.radians(angle)
            tangent_rad = angle_rad + math.pi / 2.0

            radial_offset = rng.uniform(-radial_spread * 0.33, radial_spread)
            orbit_radius = ring_radius + radial_offset
            anchor_x = center.x() + math.cos(angle_rad) * orbit_radius
            anchor_y = center.y() + math.sin(angle_rad) * orbit_radius

            tangent_offset = rng.uniform(-tangent_spread, tangent_spread) * intensity
            px = anchor_x + math.cos(tangent_rad) * tangent_offset
            py = anchor_y + math.sin(tangent_rad) * tangent_offset

            size = rng.uniform(1.1, 3.1) * (0.85 + intensity * 0.28)
            color_roll = rng.random()
            if color_roll < 0.14:
                color = QColor(hot_color)
                color.setAlpha(rng.randint(150, 225))
            elif color_roll < 0.52:
                color = QColor(bright_color)
                color.setAlpha(rng.randint(125, 210))
            else:
                color = QColor(base_color)
                color.setAlpha(rng.randint(90, 185))

            painter.setBrush(color)
            painter.drawRect(QRectF(px - size * 0.5, py - size * 0.45, size, size * rng.uniform(0.85, 1.25)))

            if rng.random() < 0.48:
                length = rng.choice(tangent_lengths) * intensity
                streak = QColor(color)
                streak.setAlpha(min(255, color.alpha() + 25))
                painter.setPen(QPen(streak, rng.uniform(0.8, 1.8), cap=Qt.PenCapStyle.RoundCap))
                start = QPointF(px, py)
                end = QPointF(
                    px + math.cos(tangent_rad) * length,
                    py + math.sin(tangent_rad) * length,
                )
                painter.drawLine(start, end)
                painter.setPen(Qt.PenStyle.NoPen)

        arc_color = QColor(bright_color)
        arc_color.setAlpha(int(135 * intensity))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(arc_color, 1.35, cap=Qt.PenCapStyle.RoundCap))
        rect = QRectF(center.x() - ring_radius, center.y() - ring_radius, ring_radius * 2.0, ring_radius * 2.0)
        painter.drawArc(rect, int((angle_center - angle_span * 0.48) * 16), int(angle_span * 0.72 * 16))
        painter.drawArc(rect.adjusted(1.6, 1.6, -1.6, -1.6), int((angle_center - angle_span * 0.30) * 16), int(angle_span * 0.4 * 16))

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
