from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class RollbackManager:
    def __init__(self, rollback_root: str | Path) -> None:
        self.rollback_root = Path(rollback_root)
        self.rollback_root.mkdir(parents=True, exist_ok=True)

    def create_backup(self, source: str | Path, attempt_id: str) -> Path:
        source_path = Path(source)
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
        backup_dir = self.rollback_root / attempt_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{source_path.name}.{digest}.bak"
        shutil.copy2(source_path, backup)
        return backup

    def restore(self, backup: str | Path, target: str | Path) -> None:
        backup_path = Path(backup)
        target_path = Path(target)
        temporary = target_path.with_suffix(target_path.suffix + ".rollback.tmp")
        shutil.copy2(backup_path, temporary)
        temporary.replace(target_path)
