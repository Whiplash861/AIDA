from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from aida.artificer.event_bus import EventBus
from aida.artificer.events import make_event
from aida.logging_utils import get_logger

log = get_logger(__name__)


def _norm(value: str) -> str:
    normalized = (value or "").lower().strip()
    return re.sub(r"\s+", " ", normalized)


def fingerprint(app: str, symptoms: str, error_codes: str = "") -> str:
    base = f"app={_norm(app)}|symptoms={_norm(symptoms)}|codes={_norm(error_codes)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class SolutionRecord:
    fp: str
    app: str
    symptoms: str
    error_codes: str
    solution_steps: str
    success_count: int = 0
    fail_count: int = 0
    last_used_ts: float = 0.0
    created_ts: float = 0.0

    @property
    def score(self) -> float:
        total = self.success_count + self.fail_count
        return 0.0 if total == 0 else self.success_count / total


class SolutionStore:
    def __init__(
        self,
        path: str,
        *,
        event_bus: EventBus | None = None,
        aida_version: str = "unknown",
    ) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.event_bus = event_bus
        self.aida_version = aida_version
        self._cache: List[SolutionRecord] = []
        self._loaded = False
        self.corrupt_line_count = 0

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(self.path):
            return
        records: List[SolutionRecord] = []
        with open(self.path, "r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(SolutionRecord(**json.loads(line)))
                except (ValueError, TypeError):
                    self.corrupt_line_count += 1
                    log.error("Invalid SolutionStore record at line %d", line_number)
        self._cache = records
        if self.corrupt_line_count:
            self._publish(
                "solution_store_corruption",
                "failed",
                {"corrupt_line_count": self.corrupt_line_count},
            )

    def find_best(self, fp: str) -> Optional[SolutionRecord]:
        self._load()
        matches = [record for record in self._cache if record.fp == fp]
        if not matches:
            self._publish("solution_lookup", "not_found", {"fingerprint": fp})
            return None
        matches.sort(
            key=lambda record: (record.score, record.success_count, record.last_used_ts),
            reverse=True,
        )
        selected = matches[0]
        self._publish(
            "solution_lookup",
            "selected",
            {
                "fingerprint": fp,
                "score": selected.score,
                "success_count": selected.success_count,
                "fail_count": selected.fail_count,
            },
        )
        return selected

    def upsert_attempt(self, record: SolutionRecord, worked: bool) -> None:
        self._load()
        now = time.time()
        existing = next(
            (
                item
                for item in self._cache
                if item.fp == record.fp
                and item.solution_steps.strip() == record.solution_steps.strip()
            ),
            None,
        )
        if existing is None:
            record.created_ts = now
            record.last_used_ts = now
            record.success_count = 1 if worked else 0
            record.fail_count = 0 if worked else 1
            self._cache.append(record)
            self._append_line(record)
            selected = record
        else:
            existing.last_used_ts = now
            if worked:
                existing.success_count += 1
            else:
                existing.fail_count += 1
            self._rewrite_all()
            selected = existing
        self._publish(
            "solution_outcome",
            "worked" if worked else "failed",
            {
                "fingerprint": selected.fp,
                "score": selected.score,
                "success_count": selected.success_count,
                "fail_count": selected.fail_count,
            },
        )

    def _append_line(self, record: SolutionRecord) -> None:
        with open(self.path, "a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _rewrite_all(self) -> None:
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as file:
            for record in self._cache:
                file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        os.replace(temporary, self.path)

    def _publish(self, event_type: str, status: str, metadata: dict[str, object]) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            make_event(
                source="memory.solution_store",
                event_type=event_type,
                status=status,
                aida_version=self.aida_version,
                metadata=metadata,
            )
        )
