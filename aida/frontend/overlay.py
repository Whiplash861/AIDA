from __future__ import annotations

import math

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
    - Click-to-restore behavior via the clicked signal
    - One-shot notification pulse when requested
    - Draggable without taking focus
    """

    clicked = Signal()

    def __init__(
        self,
        diameter: int = 96,
    ) -> None:
        super().__init__()

        self._status = AIDAStatus.STARTUP
        self._phase = 0.0
        self._notification_progress = 0.0

        self._press_global: QPoint | None = None
        self._drag_origin: QPoint | None = None
        self._dragging = False

        self.setFixedSize(diameter, diameter)
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
        margin: int = 24,
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

        self.update()

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

    def paintEvent(self, event) -> None:
        del event

        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        full_rect = QRectF(
            2.0,
            2.0,
            self.width() - 4.0,
            self.height() - 4.0,
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

        # Ambient outer glow
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

        # Main outer ring
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

        # Division-like segmented rotating arcs
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

        # Secondary accent arc for futuristic depth
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

        # Core flare
        core_rect = accent_rect.adjusted(
            9.0,
            9.0,
            -9.0,
            -9.0,
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

        # Inner flare halo
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

        # Center dot
        center_dot = QRectF(
            center.x() - 3.5,
            center.y() - 3.5,
            7.0,
            7.0,
        )

        painter.setBrush(base_color)
        painter.drawEllipse(center_dot)

        # Minimal horizontal stabilizer marks
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

    def mousePressEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
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