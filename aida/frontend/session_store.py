from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

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
    ) -> None:
        self.base_directory = Path(base_directory)
        self.base_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

        self.session_path = (
            self.base_directory
            / f"session_{timestamp}.jsonl"
        )

    def save_message(self, message: ChatMessage) -> None:
        record: dict[str, Any] = asdict(message)

        record["sender"] = message.sender.name
        record["timestamp"] = (
            message.timestamp.isoformat()
        )

        with self.session_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
            )
            file.write("\n")