from __future__ import annotations

import hashlib
import shutil
import tempfile
import os
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
        descriptor, name = tempfile.mkstemp(prefix=target_path.name + ".rollback.", dir=target_path.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            shutil.copy2(backup_path, temporary)
            temporary.replace(target_path)
        finally:
            temporary.unlink(missing_ok=True)
