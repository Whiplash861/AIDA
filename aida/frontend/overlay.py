from __future__ import annotations

import math
import random

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

from aida.frontend.status import AIDAStatus


class AIDAOverlay(QWidget):
    """
    Floating always-on-top AIDA status orb.

    Features:
    - Live animated core and segmented outer ring
    - Brief Division-inspired ring glitches during idle operation
    - Click pulse, glitch burst, and fade before restoring the main UI
    - One-shot notification pulse when requested
    - Draggable without taking focus
    """

    clicked = Signal()

    def __init__(
        self,
        diameter: int = 96,
    ) -> None:
        super().__init__()

        self._orb_diameter = diameter
        self._canvas_margin = 14
        canvas_size = diameter + self._canvas_margin * 2

        self._status = AIDAStatus.STARTUP
        self._phase = 0.0
        self._notification_progress = 0.0
        self._click_wave_progress = 0.0

        self._rng = random.Random()
        self._glitch_frames = 0
        self._glitch_seed = 0
        self._frames_until_glitch = self._next_glitch_delay()

        self._activation_frames = 0
        self._activation_signal_sent = False

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

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            True,
        )

        self.setToolTip(
            "Click to open AIDA • Right-drag to move"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(33)
        self._animation_timer.timeout.connect(
            self._advance_animation
        )
        self._animation_timer.start()

    @property
    def activation_in_progress(self) -> bool:
        return self._activation_frames > 0

    def reveal(self) -> None:
        """
        Restores the overlay after the main frontend is minimized.
        """

        if self.activation_in_progress:
            return

        self.setWindowOpacity(1.0)

        if not self.isVisible():
            self.show()

        self.raise_()
        self.update()

    def set_status(
        self,
        status: AIDAStatus,
    ) -> None:
        if not isinstance(status, AIDAStatus):
            raise TypeError(
                "status must be an AIDAStatus value"
            )

        self._status = status
        self.setToolTip(
            f"AIDA status: {status.name}"
        )
        self.update()

    def notify_message(self) -> None:
        """
        Triggers a one-shot notification pulse.
        """

        self._notification_progress = 1.0
        self.update()

    def move_to_default_position(
        self,
        margin: int = 18,
    ) -> None:
        screen = QApplication.primaryScreen()

        if screen is None:
            return

        available = screen.availableGeometry()

        x_position = (
            available.right()
            - self.width()
            - margin
            + 1
        )

        y_position = (
            available.bottom()
            - self.height()
            - margin
            + 1
        )

        self.move(
            x_position,
            y_position,
        )

    def _next_glitch_delay(self) -> int:
        return self._rng.randint(55, 135)

    def _start_glitch(self, frames: int = 4) -> None:
        self._glitch_frames = max(self._glitch_frames, frames)
        self._glitch_seed = self._rng.randint(0, 1_000_000)

    def _start_activation(self) -> None:
        if self.activation_in_progress:
            return

        self._activation_frames = 1
        self._activation_signal_sent = False
        self._click_wave_progress = 0.001
        self._start_glitch(frames=9)
        self.setWindowOpacity(1.0)
        self.update()

    def _advance_animation(self) -> None:
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

        self._phase = (
            self._phase + step
        ) % 360.0

        if self._notification_progress > 0.0:
            self._notification_progress = max(
                0.0,
                self._notification_progress - 0.055,
            )

        if self._click_wave_progress > 0.0:
            self._click_wave_progress += 0.085

            if self._click_wave_progress >= 1.0:
                self._click_wave_progress = 0.0

        if self._glitch_frames > 0:
            self._glitch_frames -= 1

        elif not self.activation_in_progress:
            self._frames_until_glitch -= 1

            if self._frames_until_glitch <= 0:
                self._start_glitch(
                    frames=self._rng.randint(2, 5)
                )
                self._frames_until_glitch = (
                    self._next_glitch_delay()
                )

        if self.activation_in_progress:
            self._advance_activation()

        self.update()

    def _advance_activation(self) -> None:
        self._activation_frames += 1

        if (
            self._activation_frames >= 5
            and not self._activation_signal_sent
        ):
            self._activation_signal_sent = True
            self.clicked.emit()

        if self._activation_frames >= 6:
            fade_progress = min(
                1.0,
                (self._activation_frames - 6) / 7.0,
            )
            self.setWindowOpacity(
                max(0.0, 1.0 - fade_progress)
            )

        if self._activation_frames >= 13:
            self._activation_frames = 0
            self.setWindowOpacity(1.0)
            self.hide()

    def _status_color(self) -> QColor:
        colors = {
            AIDAStatus.STARTUP: QColor("#53d9ff"),
            AIDAStatus.STANDBY: QColor("#45e2aa"),
            AIDAStatus.LISTENING: QColor("#7fe7ff"),
            AIDAStatus.ANALYZING: QColor("#4ab8ff"),
            AIDAStatus.SPEAKING: QColor("#9a7fff"),
            AIDAStatus.WARNING: QColor("#ffd36a"),
            AIDAStatus.ERROR: QColor("#ff6e84"),
            AIDAStatus.SHUTDOWN: QColor("#748392"),
        }

        return colors[self._status]

    def _orb_rect(self) -> QRectF:
        margin = float(self._canvas_margin)
        return QRectF(
            margin,
            margin,
            float(self._orb_diameter),
            float(self._orb_diameter),
        )

    def paintEvent(self, event) -> None:
        del event

        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        full_rect = self._orb_rect().adjusted(
            2.0,
            2.0,
            -2.0,
            -2.0,
        )

        center = full_rect.center()
        base_color = self._status_color()

        active_status = self._status in {
            AIDAStatus.STARTUP,
            AIDAStatus.LISTENING,
            AIDAStatus.ANALYZING,
            AIDAStatus.SPEAKING,
            AIDAStatus.WARNING,
            AIDAStatus.ERROR,
        }

        idle_wave = 0.5 + 0.5 * math.sin(
            math.radians(self._phase * 1.6)
        )

        notification_wave = 0.0
        if self._notification_progress > 0.0:
            notification_wave = math.sin(
                (1.0 - self._notification_progress)
                * math.pi
            )

        glow_boost = (
            0.32 + idle_wave * 0.18
            if active_status
            else 0.16 + idle_wave * 0.06
        )

        glow_boost += notification_wave * 0.6

        self._paint_click_wave(
            painter,
            center,
            base_color,
        )

        ambient_rect = full_rect.adjusted(
            2.0,
            2.0,
            -2.0,
            -2.0,
        )

        ambient_gradient = QRadialGradient(
            center,
            ambient_rect.width() / 2.0
            + notification_wave * 9.0,
        )

        ambient_center = QColor(base_color)
        ambient_center.setAlpha(
            int(36 + glow_boost * 135)
        )

        ambient_mid = QColor(base_color)
        ambient_mid.setAlpha(
            int(18 + glow_boost * 65)
        )

        ambient_edge = QColor(base_color)
        ambient_edge.setAlpha(0)

        ambient_gradient.setColorAt(
            0.0,
            ambient_center,
        )
        ambient_gradient.setColorAt(
            0.55,
            ambient_mid,
        )
        ambient_gradient.setColorAt(
            1.0,
            ambient_edge,
        )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ambient_gradient)
        painter.drawEllipse(ambient_rect)

        ring_rect = full_rect.adjusted(
            12.0,
            12.0,
            -12.0,
            -12.0,
        )

        ring_pen_color = QColor(base_color)
        ring_pen_color.setAlpha(
            int(160 + glow_boost * 55)
        )

        ring_pen = QPen(ring_pen_color, 2.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(ring_pen)
        painter.drawEllipse(ring_rect)

        segment_rect = ring_rect.adjusted(
            6.0,
            6.0,
            -6.0,
            -6.0,
        )

        segment_pen_color = QColor(base_color)
        segment_pen_color.setAlpha(
            int(165 + glow_boost * 70)
        )

        segment_pen = QPen(
            segment_pen_color,
            3.1,
        )
        segment_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )
        painter.setPen(segment_pen)

        painter.drawArc(
            segment_rect,
            int(self._phase * 16),
            72 * 16,
        )

        painter.drawArc(
            segment_rect,
            int((self._phase + 118.0) * 16),
            48 * 16,
        )

        painter.drawArc(
            segment_rect,
            int((self._phase + 216.0) * 16),
            34 * 16,
        )

        if self._glitch_frames > 0:
            self._paint_glitch(
                painter,
                ring_rect,
                segment_rect,
                base_color,
            )

        accent_pen_color = QColor("#88c7ff")
        if self._status == AIDAStatus.SPEAKING:
            accent_pen_color = QColor("#b290ff")

        accent_pen_color.setAlpha(
            int(60 + glow_boost * 55)
        )

        accent_pen = QPen(accent_pen_color, 1.5)
        accent_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )
        painter.setPen(accent_pen)

        accent_rect = segment_rect.adjusted(
            6.0,
            6.0,
            -6.0,
            -6.0,
        )

        painter.drawArc(
            accent_rect,
            int((-self._phase * 0.7 + 145.0) * 16),
            46 * 16,
        )

        glitch_rng = random.Random(
            self._glitch_seed + self._glitch_frames * 97
        )
        jitter_x = 0.0
        jitter_y = 0.0

        if self._glitch_frames > 0:
            jitter_x = glitch_rng.uniform(-1.8, 1.8)
            jitter_y = glitch_rng.uniform(-1.2, 1.2)

        core_rect = accent_rect.adjusted(
            9.0 + jitter_x,
            9.0 + jitter_y,
            -9.0 + jitter_x,
            -9.0 + jitter_y,
        )

        core_gradient = QRadialGradient(
            core_rect.center(),
            core_rect.width() / 2.0,
        )

        core_center = QColor(base_color)
        core_center.setAlpha(
            int(230 + glow_boost * 25)
        )

        mid_flare = QColor("#b8efff")
        mid_flare.setAlpha(
            int(70 + glow_boost * 85)
        )

        core_edge = QColor("#07111a")
        core_edge.setAlpha(245)

        core_gradient.setColorAt(0.0, core_center)
        core_gradient.setColorAt(0.24, mid_flare)
        core_gradient.setColorAt(
            0.62,
            QColor("#0b2130"),
        )
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

        flare_gradient = QRadialGradient(
            flare_rect.center(),
            flare_rect.width() / 2.0,
        )

        flare_center = QColor("#eaffff")
        flare_center.setAlpha(
            int(150 + glow_boost * 75)
        )

        flare_edge = QColor(base_color)
        flare_edge.setAlpha(0)

        flare_gradient.setColorAt(0.0, flare_center)
        flare_gradient.setColorAt(1.0, flare_edge)

        painter.setBrush(flare_gradient)
        painter.drawEllipse(flare_rect)

        center_dot = QRectF(
            center.x() - 3.5,
            center.y() - 3.5,
            7.0,
            7.0,
        )

        painter.setBrush(base_color)
        painter.drawEllipse(center_dot)

        line_pen = QPen(
            QColor("#e5fbff"),
            1.45,
        )
        line_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )
        painter.setPen(line_pen)

        line_width = 10.0
        gap = 8.0

        painter.drawLine(
            int(center.x() - gap - line_width),
            int(center.y()),
            int(center.x() - gap),
            int(center.y()),
        )

        painter.drawLine(
            int(center.x() + gap),
            int(center.y()),
            int(center.x() + gap + line_width),
            int(center.y()),
        )

        painter.end()

    def _paint_click_wave(
        self,
        painter: QPainter,
        center,
        base_color: QColor,
    ) -> None:
        progress = self._click_wave_progress

        if progress <= 0.0:
            return

        eased = 1.0 - (1.0 - progress) ** 2
        radius = 8.0 + eased * (
            self._orb_diameter * 0.58
        )
        alpha = int(105 * (1.0 - progress) ** 1.45)

        wave_color = QColor("#6fdcff")
        wave_color.setAlpha(max(0, alpha))

        painter.setBrush(Qt.BrushStyle.NoBrush)

        for offset, width, scale in (
            (0.0, 2.0, 1.0),
            (3.5, 1.2, 0.55),
            (7.0, 0.8, 0.28),
        ):
            color = QColor(wave_color)
            color.setAlpha(
                int(wave_color.alpha() * scale)
            )
            painter.setPen(QPen(color, width))
            painter.drawEllipse(
                center,
                radius + offset,
                radius + offset,
            )

        soft_fill = QColor(base_color)
        soft_fill.setAlpha(
            int(28 * (1.0 - progress))
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(soft_fill)
        painter.drawEllipse(
            center,
            max(2.0, radius * 0.32),
            max(2.0, radius * 0.32),
        )

    def _paint_glitch(
        self,
        painter: QPainter,
        ring_rect: QRectF,
        segment_rect: QRectF,
        base_color: QColor,
    ) -> None:
        rng = random.Random(
            self._glitch_seed + self._glitch_frames * 131
        )

        strength = min(
            1.0,
            0.45 + self._glitch_frames / 9.0,
        )

        fragment_color = QColor(base_color)
        fragment_color.setAlpha(
            int(120 + 115 * strength)
        )

        fragment_pen = QPen(
            fragment_color,
            1.6 + 1.5 * strength,
        )
        fragment_pen.setCapStyle(
            Qt.PenCapStyle.FlatCap
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(fragment_pen)

        for _ in range(rng.randint(3, 6)):
            radial_offset = rng.uniform(-4.0, 7.0) * strength
            fragment_rect = segment_rect.adjusted(
                -radial_offset,
                -radial_offset,
                radial_offset,
                radial_offset,
            )
            start = rng.uniform(0.0, 360.0)
            span = rng.uniform(4.0, 18.0)
            painter.drawArc(
                fragment_rect,
                int(start * 16),
                int(span * 16),
            )

        spike_color = QColor("#a8ecff")
        spike_color.setAlpha(
            int(95 + 130 * strength)
        )
        spike_pen = QPen(
            spike_color,
            1.0 + 0.6 * strength,
        )
        spike_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )
        painter.setPen(spike_pen)

        center = ring_rect.center()
        base_radius = ring_rect.width() / 2.0

        for _ in range(rng.randint(4, 8)):
            angle = math.radians(
                rng.uniform(0.0, 360.0)
            )
            inner = base_radius + rng.uniform(-1.0, 2.0)
            outer = inner + rng.uniform(3.0, 11.0) * strength

            x1 = center.x() + math.cos(angle) * inner
            y1 = center.y() + math.sin(angle) * inner
            x2 = center.x() + math.cos(angle) * outer
            y2 = center.y() + math.sin(angle) * outer

            painter.drawLine(
                int(x1),
                int(y1),
                int(x2),
                int(y2),
            )

    def mousePressEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_activation()
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._drag_press_global = (
                event.globalPosition().toPoint()
            )

            self._drag_window_origin = (
                self.frameGeometry().topLeft()
            )

            self._dragging = True

            self.setCursor(
                Qt.CursorShape.ClosedHandCursor
            )

            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if (
            self._dragging
            and self._drag_press_global is not None
            and self._drag_window_origin is not None
            and event.buttons()
            & Qt.MouseButton.RightButton
        ):
            movement = (
                event.globalPosition().toPoint()
                - self._drag_press_global
            )

            self.move(
                self._drag_window_origin
                + movement
            )

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._drag_press_global = None
            self._drag_window_origin = None
            self._dragging = False

            self.setCursor(
                Qt.CursorShape.PointingHandCursor
            )

            event.accept()
            return

        super().mouseReleaseEvent(event)
