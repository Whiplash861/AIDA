from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    path: str
    size_bytes: int
    sha256: str
    suffix: str


class SourceInventory:
    def __init__(self, source_root: str | Path) -> None:
        self.source_root = Path(source_root).resolve()

    def collect(self) -> tuple[SourceFileRecord, ...]:
        records: list[SourceFileRecord] = []
        for path in sorted(self.source_root.rglob("*")):
            if not path.is_file() or self._ignored(path):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            records.append(
                SourceFileRecord(
                    path=str(path.relative_to(self.source_root)).replace("\\", "/"),
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    suffix=path.suffix.lower(),
                )
            )
        return tuple(records)

    def _ignored(self, path: Path) -> bool:
        parts = {part.lower() for part in path.parts}
        return bool(
            parts.intersection(
                {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "logs", "memory"}
            )
        )
