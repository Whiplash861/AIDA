from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from aida.artificer.engine import ArtificerEngine
from aida.artificer.models import ArtificerSnapshot


class ArtificerQtBridge(QObject):
    """Thread-safe Qt bridge for Artificer snapshots."""

    snapshot_changed = Signal(object)

    def __init__(self, engine: ArtificerEngine) -> None:
        super().__init__()
        self.engine = engine
        self.engine.subscribe(self._receive)

    def _receive(self, snapshot: ArtificerSnapshot) -> None:
        self.snapshot_changed.emit(snapshot)

    @Slot()
    def refresh(self) -> None:
        self.snapshot_changed.emit(self.engine.snapshot())

    def close(self) -> None:
        self.engine.unsubscribe(self._receive)
