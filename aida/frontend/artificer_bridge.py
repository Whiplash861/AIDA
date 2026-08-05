from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from aida.artificer.engine import ArtificerEngine
from aida.artificer.models import ArtificerSnapshot


class ArtificerQtBridge(QObject):
    """Marshals Artificer snapshots from worker threads onto the Qt thread."""

    snapshot_changed = Signal(object)
    status_changed = Signal(str)

    def __init__(self, engine: ArtificerEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._closed = False
        self.engine.subscribe(self._receive_snapshot)

    def _receive_snapshot(self, snapshot: ArtificerSnapshot) -> None:
        if self._closed:
            return
        self.status_changed.emit(snapshot.status)
        self.snapshot_changed.emit(snapshot)

    @Slot()
    def emit_current(self) -> None:
        self._receive_snapshot(self.engine.snapshot())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.engine.unsubscribe(self._receive_snapshot)
