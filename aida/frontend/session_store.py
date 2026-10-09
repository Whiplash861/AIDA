from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from threading import Lock
from aida.memory.privacy import sanitize_text

from aida.frontend.models import ChatMessage


class SessionStore:
    """
    Writes the active frontend conversation to a JSON Lines file.

    Each message is appended immediately so the session remains
    recoverable even if the application closes unexpectedly.
    """

    def __init__(
        self,
        base_directory: str | Path = "logs/sessions",
        *, retention_days: int = 30,
    ) -> None:
        self.base_directory = Path(base_directory)
        self._lock = Lock()
        self.base_directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        cutoff = (datetime.now() - timedelta(days=max(1, retention_days))).timestamp()
        for previous in self.base_directory.glob("session_*.jsonl"):
            try:
                if previous.is_file() and not previous.is_symlink() and previous.stat().st_mtime < cutoff:
                    previous.unlink()
            except OSError:
                # Retention must not prevent a new session from opening.
                continue

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        self.session_path = (
            self.base_directory
            / f"session_{timestamp}_{uuid4().hex}.jsonl"
        )

    def save_message(self, message: ChatMessage) -> None:
        record: dict[str, Any] = asdict(message)

        record["sender"] = message.sender.name
        record["text"] = sanitize_text(message.text)
        record["timestamp"] = (
            message.timestamp.isoformat()
        )

        with self._lock, self.session_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
