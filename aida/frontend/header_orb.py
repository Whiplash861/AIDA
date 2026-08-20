from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QMouseEvent

from aida.frontend.engine_state import ENGINE_VISUAL_STATE
from aida.frontend.overlay import AIDAOverlay


class HeaderEngineOrb(AIDAOverlay):
    """Embedded AIDA orb used beside the AIDA identity in the main header."""

    def __init__(self, diameter: int = 52) -> None:
        super().__init__(diameter=diameter)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("AIDA Engine activity")

    def _status_color(self) -> QColor:
        snapshot = ENGINE_VISUAL_STATE.snapshot()
        if snapshot.color:
            return QColor(snapshot.color)
        return super()._status_color()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        event.ignore()
