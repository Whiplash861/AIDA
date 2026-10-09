from __future__ import annotations

import hashlib
import os
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
        for path in iter_source_files(self.source_root):
            if not path.is_file() or path.is_symlink() or self._ignored(path):
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
        relative = path.relative_to(self.source_root)
        parts = {part.lower() for part in relative.parts}
        return bool(
            parts.intersection(
                {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "logs"}
            )
        )


def iter_source_files(root: Path):
    """Prune generated/private trees before traversing; include aida/memory."""
    ignored = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "build", "logs"}
    for directory, folders, files in os.walk(root, topdown=True, followlinks=False):
        parent = Path(directory)
        folders[:] = sorted(name for name in folders
                            if name.lower() not in ignored
                            and not (parent / name).is_symlink()
                            and not (parent == root and name.lower() == "memory"))
        for name in sorted(files):
            path = parent / name
            if not name.startswith(".env") and not path.is_symlink():
                yield path
