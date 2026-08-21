from __future__ import annotations

import json
import threading
from pathlib import Path

from aida.aegis.learning.online_model import OnlineAnomalyModel


class AegisLearningStore:
    """Small local JSON store for the current Aegis learning model.

    The model stores aggregate numeric statistics and hashed identity tokens,
    never raw paths, command lines, network endpoints, or Security Case text.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> OnlineAnomalyModel | None:
        with self._lock:
            if not self.path.exists():
                return None
            try:
                record = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                return None
        try:
            return OnlineAnomalyModel.from_record(dict(record))
        except (TypeError, ValueError):
            return None

    def save(self, model: OnlineAnomalyModel) -> None:
        payload = json.dumps(model.to_record(), indent=2, sort_keys=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with self._lock:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(self.path)
