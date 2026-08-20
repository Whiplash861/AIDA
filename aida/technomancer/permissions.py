from __future__ import annotations

import json
from pathlib import Path

TECHNOMANCER_BACKGROUND_SCOPE = "technomancer.background_monitoring"


class PermissionStore:
    """Machine-local autonomy permissions. Autonomy is necessary but never blanket authority."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"autonomy_enabled": False, "scopes": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"autonomy_enabled": False, "scopes": {}}
        data.setdefault("autonomy_enabled", False)
        data.setdefault("scopes", {})
        return data

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    @property
    def autonomy_enabled(self) -> bool:
        return bool(self._load().get("autonomy_enabled"))

    def set_autonomy(self, enabled: bool) -> None:
        data = self._load()
        data["autonomy_enabled"] = bool(enabled)
        self._save(data)

    def set_scope(self, scope: str, enabled: bool) -> None:
        data = self._load()
        data["scopes"][scope] = bool(enabled)
        self._save(data)

    def scope_enabled(self, scope: str) -> bool:
        return bool(self._load().get("scopes", {}).get(scope, False))

    def permitted(self, scope: str) -> bool:
        return self.autonomy_enabled and self.scope_enabled(scope)
