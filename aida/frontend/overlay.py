from __future__ import annotations

import math
import random

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
)
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

    def __init__(self, diameter: int = 96) -> None:
        super().__init__()

        self._orb_diameter = diameter
        self._canvas_margin = 18
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
        # 33 ms frames => roughly 5–10 seconds.
        return self._rng.randint(152, 303)

    def _start_glitch(self, frames: int | None = None, style: int | None = None) -> None:
        if self._glitch_frames > 0:
            return
        self._glitch_style = self._rng.randrange(6) if style is None else style
        self._glitch_seed = self._rng.randint(0, 1_000_000)
        self._glitch_frames = frames if frames is not None else self._rng.randint(3, 6)

    def _start_reveal(self) -> None:
        self._reveal_frames = 1
        self._click_wave_progress = 0.001
        self._start_glitch(frames=8)
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
        self._start_glitch(frames=10)
        self.setWindowOpacity(1.0)
        self.update()

    def _advance_animation(self) -> None:
        self._sync_visibility()

        step = {
            AIDAStatus.STARTUP: 2.0,
            AIDAStatus.STANDBY: 0.8,
            AIDAStatus.LISTENING: 2.6,
            AIDAStatus.ANALYZING: 5.2,
            AIDAStatus.SPEAKING: 4.1,
            AIDAStatus.WARNING: 2.2,
            AIDAStatus.ERROR: 1.8,
            AIDAStatus.SHUTDOWN: 0.4,
        }[self._status]
        self._phase = (self._phase + step) % 360.0

        if self._notification_progress > 0.0:
            self._notification_progress = max(0.0, self._notification_progress - 0.055)

        if self._click_wave_progress > 0.0:
            self._click_wave_progress += 0.075
            if self._click_wave_progress >= 1.0:
                self._click_wave_progress = 0.0

        if self._glitch_frames > 0:
            self._glitch_frames -= 1
        elif self.isVisible() and not self.activation_in_progress and self._reveal_frames == 0:
            self._frames_until_glitch -= 1
            if self._frames_until_glitch <= 0:
                self._start_glitch()
                self._frames_until_glitch = self._next_glitch_delay()

        if self._reveal_frames > 0:
            self._advance_reveal()

        if self.activation_in_progress:
            self._advance_activation()

        self.update()

    def _advance_reveal(self) -> None:
        self._reveal_frames += 1
        progress = min(1.0, self._reveal_frames / 10.0)
        eased = 1.0 - (1.0 - progress) ** 2
        self.setWindowOpacity(eased)
        if self._reveal_frames >= 10:
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

    def _status_color(self) -> QColor:
        return {
            AIDAStatus.STARTUP: QColor("#53d9ff"),
            AIDAStatus.STANDBY: QColor("#45e2aa"),
            AIDAStatus.LISTENING: QColor("#7fe7ff"),
            AIDAStatus.ANALYZING: QColor("#4ab8ff"),
            AIDAStatus.SPEAKING: QColor("#9a7fff"),
            AIDAStatus.WARNING: QColor("#ffd36a"),
            AIDAStatus.ERROR: QColor("#ff6e84"),
            AIDAStatus.SHUTDOWN: QColor("#748392"),
        }[self._status]

    def _orb_rect(self) -> QRectF:
        margin = float(self._canvas_margin)
        return QRectF(margin, margin, float(self._orb_diameter), float(self._orb_diameter))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        full_rect = self._orb_rect().adjusted(2.0, 2.0, -2.0, -2.0)
        center = full_rect.center()
        base_color = self._status_color()

        idle_wave = 0.5 + 0.5 * math.sin(math.radians(self._phase * 1.6))
        notification_wave = 0.0
        if self._notification_progress > 0.0:
            notification_wave = math.sin((1.0 - self._notification_progress) * math.pi)

        active_status = self._status is not AIDAStatus.STANDBY
        glow_boost = 0.32 + idle_wave * 0.18 if active_status else 0.16 + idle_wave * 0.06
        glow_boost += notification_wave * 0.6

        self._paint_click_wave(painter, center, base_color)

        ambient_rect = full_rect.adjusted(2.0, 2.0, -2.0, -2.0)
        ambient_gradient = QRadialGradient(
            center,
            ambient_rect.width() / 2.0 + notification_wave * 9.0,
        )
        ambient_center = QColor(base_color)
        ambient_center.setAlpha(int(36 + glow_boost * 135))
        ambient_mid = QColor(base_color)
        ambient_mid.setAlpha(int(18 + glow_boost * 65))
        ambient_edge = QColor(base_color)
        ambient_edge.setAlpha(0)
        ambient_gradient.setColorAt(0.0, ambient_center)
        ambient_gradient.setColorAt(0.55, ambient_mid)
        ambient_gradient.setColorAt(1.0, ambient_edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ambient_gradient)
        painter.drawEllipse(ambient_rect)

        ring_rect = full_rect.adjusted(12.0, 12.0, -12.0, -12.0)
        ring_color = QColor(base_color)
        ring_color.setAlpha(int(160 + glow_boost * 55))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ring_color, 2.0))
        painter.drawEllipse(ring_rect)

        segment_rect = ring_rect.adjusted(6.0, 6.0, -6.0, -6.0)
        segment_color = QColor(base_color)
        segment_color.setAlpha(int(165 + glow_boost * 70))
        segment_pen = QPen(segment_color, 3.1)
        segment_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(segment_pen)
        painter.drawArc(segment_rect, int(self._phase * 16), 72 * 16)
        painter.drawArc(segment_rect, int((self._phase + 118.0) * 16), 48 * 16)
        painter.drawArc(segment_rect, int((self._phase + 216.0) * 16), 34 * 16)

        accent_color = QColor("#b290ff") if self._status == AIDAStatus.SPEAKING else QColor("#88c7ff")
        accent_color.setAlpha(int(60 + glow_boost * 55))
        accent_pen = QPen(accent_color, 1.5)
        accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(accent_pen)
        accent_rect = segment_rect.adjusted(6.0, 6.0, -6.0, -6.0)
        painter.drawArc(accent_rect, int((-self._phase * 0.7 + 145.0) * 16), 46 * 16)

        core_jitter_x = 0.0
        core_jitter_y = 0.0
        if self._glitch_frames > 0 and self._glitch_style == self._CORE_JITTER:
            jitter_rng = random.Random(self._glitch_seed + self._glitch_frames * 97)
            core_jitter_x = jitter_rng.uniform(-2.0, 2.0)
            core_jitter_y = jitter_rng.uniform(-1.0, 1.0)

        core_rect = accent_rect.adjusted(
            9.0 + core_jitter_x,
            9.0 + core_jitter_y,
            -9.0 + core_jitter_x,
            -9.0 + core_jitter_y,
        )
        core_gradient = QRadialGradient(core_rect.center(), core_rect.width() / 2.0)
        core_center = QColor(base_color)
        core_center.setAlpha(int(230 + glow_boost * 25))
        mid_flare = QColor("#b8efff")
        mid_flare.setAlpha(int(70 + glow_boost * 85))
        core_edge = QColor("#07111a")
        core_edge.setAlpha(245)
        core_gradient.setColorAt(0.0, core_center)
        core_gradient.setColorAt(0.24, mid_flare)
        core_gradient.setColorAt(0.62, QColor("#0b2130"))
        core_gradient.setColorAt(1.0, core_edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core_gradient)
        painter.drawEllipse(core_rect)

        flare_rect = QRectF(
            center.x() - 8.0 - notification_wave * 1.5,
            center.y() - 8.0 - notification_wave * 1.5,
            16.0 + notification_wave * 3.0,
            16.0 + notification_wave * 3.0,
        )
        flare_gradient = QRadialGradient(flare_rect.center(), flare_rect.width() / 2.0)
        flare_center = QColor("#eaffff")
        flare_center.setAlpha(int(150 + glow_boost * 75))
        flare_edge = QColor(base_color)
        flare_edge.setAlpha(0)
        flare_gradient.setColorAt(0.0, flare_center)
        flare_gradient.setColorAt(1.0, flare_edge)
        painter.setBrush(flare_gradient)
        painter.drawEllipse(flare_rect)

        painter.setBrush(base_color)
        painter.drawEllipse(QRectF(center.x() - 3.5, center.y() - 3.5, 7.0, 7.0))

        line_pen = QPen(QColor("#e5fbff"), 1.45)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(line_pen)
        line_width = 10.0
        gap = 8.0
        painter.drawLine(int(center.x() - gap - line_width), int(center.y()), int(center.x() - gap), int(center.y()))
        painter.drawLine(int(center.x() + gap), int(center.y()), int(center.x() + gap + line_width), int(center.y()))

        if self._glitch_frames > 0:
            self._paint_glitch(painter, ring_rect, segment_rect, core_rect, base_color)

        painter.end()

    def _paint_click_wave(self, painter: QPainter, center: QPointF, base_color: QColor) -> None:
        progress = self._click_wave_progress
        if progress <= 0.0:
            return
        eased = 1.0 - (1.0 - progress) ** 2
        radius = 8.0 + eased * (self._orb_diameter * 0.62)
        alpha = int(110 * (1.0 - progress) ** 1.45)
        wave = QColor("#6fdcff")
        wave.setAlpha(max(0, alpha))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for offset, width, scale in ((0.0, 2.0, 1.0), (3.0, 1.2, 0.55), (6.0, 0.8, 0.26)):
            color = QColor(wave)
            color.setAlpha(int(wave.alpha() * scale))
            painter.setPen(QPen(color, width))
            painter.drawEllipse(center, radius + offset, radius + offset)
        fill = QColor(base_color)
        fill.setAlpha(int(28 * (1.0 - progress)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(center, max(2.0, radius * 0.30), max(2.0, radius * 0.30))

    def _paint_glitch(
        self,
        painter: QPainter,
        ring_rect: QRectF,
        segment_rect: QRectF,
        core_rect: QRectF,
        base_color: QColor,
    ) -> None:
        rng = random.Random(self._glitch_seed + self._glitch_frames * 173)
        style = self._glitch_style

        if style == self._MICRO_SPIKE:
            self._paint_micro_spike(painter, ring_rect, base_color, rng)
        elif style == self._CONDENSED_WAVE:
            self._paint_condensed_wave(painter, ring_rect, base_color, rng)
        elif style == self._TOP_SEGMENT_SPUTTER:
            self._paint_arc_pixel_cloud(painter, ring_rect, base_color, rng, -90.0, 34.0, 84)
        elif style == self._LEFT_ARC_DISTORT:
            self._paint_arc_pixel_cloud(painter, ring_rect, base_color, rng, 180.0, 52.0, 96)
        elif style == self._FULL_RING_INTERFERENCE:
            self._paint_full_ring_interference(painter, segment_rect, base_color, rng)
        else:
            self._paint_core_jitter(painter, core_rect, base_color, rng)

    def _pixel_color(self, base_color: QColor, rng: random.Random) -> QColor:
        roll = rng.random()
        if roll < 0.68:
            color = QColor(base_color)
        elif roll < 0.90:
            color = QColor("#c8f6ff")
        else:
            color = QColor("#7c93ff")
        color.setAlpha(rng.randint(90, 235))
        return color

    def _paint_micro_spike(self, painter: QPainter, ring_rect: QRectF, base_color: QColor, rng: random.Random) -> None:
        center = ring_rect.center()
        angle = math.radians(rng.uniform(-14.0, 14.0))
        radius = ring_rect.width() / 2.0
        anchor = QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius)
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(62):
            x = anchor.x() + rng.uniform(-4.0, 14.0)
            y = anchor.y() + rng.uniform(-9.0, 9.0)
            w = rng.uniform(0.8, 4.0)
            h = rng.uniform(0.7, 1.8)
            painter.setBrush(self._pixel_color(base_color, rng))
            painter.drawRect(QRectF(x, y, w, h))

    def _paint_condensed_wave(self, painter: QPainter, ring_rect: QRectF, base_color: QColor, rng: random.Random) -> None:
        center = ring_rect.center()
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(118):
            side = -1.0 if rng.random() < 0.45 else 1.0
            x = center.x() + side * rng.uniform(10.0, 54.0)
            y = center.y() + rng.gauss(0.0, 5.2)
            w = rng.uniform(1.0, 8.0)
            h = rng.uniform(0.6, 1.8)
            painter.setBrush(self._pixel_color(base_color, rng))
            painter.drawRect(QRectF(x, y, w, h))

    def _paint_arc_pixel_cloud(
        self,
        painter: QPainter,
        ring_rect: QRectF,
        base_color: QColor,
        rng: random.Random,
        angle_center: float,
        angle_span: float,
        count: int,
    ) -> None:
        center = ring_rect.center()
        base_radius = ring_rect.width() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(count):
            angle = math.radians(rng.uniform(angle_center - angle_span / 2.0, angle_center + angle_span / 2.0))
            radius = base_radius + rng.uniform(-8.0, 10.0)
            x = center.x() + math.cos(angle) * radius + rng.uniform(-2.0, 2.0)
            y = center.y() + math.sin(angle) * radius + rng.uniform(-2.0, 2.0)
            w = rng.uniform(0.8, 6.0)
            h = rng.uniform(0.7, 2.0)
            painter.setBrush(self._pixel_color(base_color, rng))
            painter.drawRect(QRectF(x, y, w, h))

    def _paint_full_ring_interference(self, painter: QPainter, ring_rect: QRectF, base_color: QColor, rng: random.Random) -> None:
        center = ring_rect.center()
        base_radius = ring_rect.width() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(148):
            angle = rng.uniform(0.0, math.tau)
            radius = base_radius + rng.uniform(-9.0, 10.0)
            x = center.x() + math.cos(angle) * radius
            y = center.y() + math.sin(angle) * radius
            w = rng.uniform(0.7, 5.0)
            h = rng.uniform(0.6, 1.9)
            painter.setBrush(self._pixel_color(base_color, rng))
            painter.drawRect(QRectF(x, y, w, h))

    def _paint_core_jitter(self, painter: QPainter, core_rect: QRectF, base_color: QColor, rng: random.Random) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        center = core_rect.center()
        for _ in range(104):
            x = center.x() + rng.gauss(0.0, core_rect.width() * 0.34)
            y = center.y() + rng.gauss(0.0, core_rect.height() * 0.15)
            w = rng.uniform(0.8, 6.0)
            h = rng.uniform(0.6, 1.7)
            painter.setBrush(self._pixel_color(base_color, rng))
            painter.drawRect(QRectF(x, y, w, h))

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
