from __future__ import annotations

from PySide6.QtGui import QColor

from aida.frontend.overlay import AIDAOverlay


class EngineAwareOverlay(AIDAOverlay):
    """AIDA orb with one optional Engine identity color override."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._engine_key: str | None = None
        self._engine_color: QColor | None = None

    def set_engine(self, engine_key: str | None, color: str | None = None) -> None:
        self._engine_key = engine_key
        self._engine_color = QColor(color) if engine_key and color else None
        if engine_key:
            self.setToolTip(f"AIDA • {engine_key.title()} Engine")
        else:
            self.setToolTip(f"AIDA status: {self._status.name}")
        self.update()

    def _status_color(self) -> QColor:
        if self._engine_color is not None:
            return QColor(self._engine_color)
        return super()._status_color()
