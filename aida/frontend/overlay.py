from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
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
    Small always-on-top indicator representing AIDA's current state.
    """

    def __init__(
        self,
        diameter: int = 92,
    ) -> None:
        super().__init__()

        self._status = AIDAStatus.STARTUP
        self._phase = 0.0
        self._drag_offset: QPoint | None = None

        self.setFixedSize(
            diameter,
            diameter,
        )

        self.setWindowTitle(
            "AIDA Status"
        )

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
            "AIDA operational status"
        )

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
            AIDAStatus.LISTENING: 3.0,
            AIDAStatus.ANALYZING: 5.0,
            AIDAStatus.SPEAKING: 4.0,
            AIDAStatus.WARNING: 2.0,
            AIDAStatus.ERROR: 1.5,
            AIDAStatus.SHUTDOWN: 0.3,
        }[self._status]

        self._phase = (
            self._phase + step
        ) % 360.0

        self.update()

    def _status_color(self) -> QColor:
        colors = {
            AIDAStatus.STARTUP: QColor("#4cc9f0"),
            AIDAStatus.STANDBY: QColor("#43e6a6"),
            AIDAStatus.LISTENING: QColor("#7ae7ff"),
            AIDAStatus.ANALYZING: QColor("#45a9ff"),
            AIDAStatus.SPEAKING: QColor("#9b7bff"),
            AIDAStatus.WARNING: QColor("#ffcf66"),
            AIDAStatus.ERROR: QColor("#ff6b78"),
            AIDAStatus.SHUTDOWN: QColor("#6d7b88"),
        }

        return colors[self._status]

    def paintEvent(
        self,
        event,
    ) -> None:
        del event

        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        widget_rect = QRectF(
            4.0,
            4.0,
            self.width() - 8.0,
            self.height() - 8.0,
        )

        center = widget_rect.center()
        base_color = self._status_color()

        pulse = (
            0.5
            + 0.5
            * math.sin(
                math.radians(
                    self._phase * 2.0
                )
            )
        )

        active_status = self._status in {
            AIDAStatus.STARTUP,
            AIDAStatus.LISTENING,
            AIDAStatus.ANALYZING,
            AIDAStatus.SPEAKING,
            AIDAStatus.WARNING,
            AIDAStatus.ERROR,
        }

        glow_alpha = (
            int(55 + pulse * 75)
            if active_status
            else 42
        )

        glow = QRadialGradient(
            center,
            widget_rect.width() / 2.0,
        )

        glow_center = QColor(base_color)
        glow_center.setAlpha(glow_alpha)

        glow_edge = QColor(base_color)
        glow_edge.setAlpha(0)

        glow.setColorAt(
            0.0,
            glow_center,
        )

        glow.setColorAt(
            1.0,
            glow_edge,
        )

        painter.setPen(
            Qt.PenStyle.NoPen
        )
        painter.setBrush(glow)
        painter.drawEllipse(widget_rect)

        outer_rect = widget_rect.adjusted(
            8.0,
            8.0,
            -8.0,
            -8.0,
        )

        outer_pen_color = QColor(base_color)
        outer_pen_color.setAlpha(175)

        outer_pen = QPen(
            outer_pen_color,
            2.0,
        )

        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )
        painter.setPen(outer_pen)
        painter.drawEllipse(outer_rect)

        rotating_rect = outer_rect.adjusted(
            7.0,
            7.0,
            -7.0,
            -7.0,
        )

        arc_color = QColor(base_color)
        arc_color.setAlpha(
            int(130 + pulse * 100)
        )

        arc_pen = QPen(
            arc_color,
            3.0,
        )

        arc_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(arc_pen)

        painter.drawArc(
            rotating_rect,
            int(self._phase * 16),
            105 * 16,
        )

        painter.drawArc(
            rotating_rect,
            int((self._phase + 180.0) * 16),
            55 * 16,
        )

        core_rect = rotating_rect.adjusted(
            10.0,
            10.0,
            -10.0,
            -10.0,
        )

        core_gradient = QRadialGradient(
            core_rect.center(),
            core_rect.width() / 2.0,
        )

        core_center = QColor(base_color)
        core_center.setAlpha(245)

        core_edge = QColor("#071019")
        core_edge.setAlpha(245)

        core_gradient.setColorAt(
            0.0,
            core_center,
        )

        core_gradient.setColorAt(
            0.65,
            QColor("#102534"),
        )

        core_gradient.setColorAt(
            1.0,
            core_edge,
        )

        painter.setPen(
            Qt.PenStyle.NoPen
        )
        painter.setBrush(core_gradient)
        painter.drawEllipse(core_rect)

        center_dot = QRectF(
            center.x() - 3.5,
            center.y() - 3.5,
            7.0,
            7.0,
        )

        painter.setBrush(base_color)
        painter.drawEllipse(center_dot)

        line_pen = QPen(
            QColor("#dff8ff"),
            1.5,
        )

        line_pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(line_pen)

        line_width = 9.0
        gap = 7.0

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
        if (
            event.button()
            == Qt.MouseButton.LeftButton
        ):
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )

            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if (
            self._drag_offset is not None
            and event.buttons()
            & Qt.MouseButton.LeftButton
        ):
            self.move(
                event.globalPosition().toPoint()
                - self._drag_offset
            )

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(
        self,
        event: QMouseEvent,
    ) -> None:
        if (
            event.button()
            == Qt.MouseButton.LeftButton
        ):
            self._drag_offset = None
            event.accept()
            return

        super().mouseReleaseEvent(event)