from __future__ import annotations

import json
import os
import re
import time
import hashlib
from dataclasses import dataclass, asdict
from typing import List, Optional

from aida.logging_utils import get_logger

log = get_logger(__name__)


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def fingerprint(app: str, symptoms: str, error_codes: str = "") -> str:
    base = f"app={_norm(app)}|symptoms={_norm(symptoms)}|codes={_norm(error_codes)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


@dataclass
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
        # Simple v1 score (we’ll improve with confidence scaling next phase)
        total = self.success_count + self.fail_count
        if total == 0:
            return 0.0
        return self.success_count / total


class SolutionStore:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._cache: List[SolutionRecord] = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if not os.path.exists(self.path):
            self._cache = []
            return

        records: List[SolutionRecord] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    records.append(SolutionRecord(**d))
                except Exception:
                    continue
        self._cache = records

    def find_best(self, fp: str) -> Optional[SolutionRecord]:
        self._load()
        matches = [r for r in self._cache if r.fp == fp]
        if not matches:
            return None
        matches.sort(key=lambda r: (r.score, r.success_count, r.last_used_ts), reverse=True)
        return matches[0]

    def upsert_attempt(self, rec: SolutionRecord, worked: bool) -> None:
        self._load()
        now = time.time()

        existing = None
        for r in self._cache:
            if r.fp == rec.fp and r.solution_steps.strip() == rec.solution_steps.strip():
                existing = r
                break

        if existing is None:
            rec.created_ts = now
            rec.last_used_ts = now
            if worked:
                rec.success_count = 1
            else:
                rec.fail_count = 1
            self._cache.append(rec)
            self._append_line(rec)
            return

        existing.last_used_ts = now
        if worked:
            existing.success_count += 1
        else:
            existing.fail_count += 1

        self._rewrite_all()

    def _append_line(self, rec: SolutionRecord) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    def _rewrite_all(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in self._cache:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)
