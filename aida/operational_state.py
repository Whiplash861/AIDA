from __future__ import annotations

import json
import os
import platform
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


DEFAULT_STATUSES: dict[str, str] = {
    "agent": "OFFLINE",
    "brain": "IDLE",
    "speech": "IDLE",
    "diagnostics": "IDLE",
    "memory": "READY",
    "artificer": "READY",
    "perception": "READY",
    "microphone": "READY",
    "tasks": "0 ACTIVE",
}

_STATUS_ORDER = tuple(DEFAULT_STATUSES)
_MAX_ACTIVITY_ITEMS = 50


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def operational_state_path() -> Path:
    configured = (os.getenv("AIDA_OPERATIONAL_STATE_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data) / "AIDA"
    else:
        root = Path.home() / ".aida"
    return root / "runtime" / "operational_state.json"


def status_tone(text: str) -> str:
    normalized = text.strip().upper()
    if any(token in normalized for token in ("ERROR", "FAILED", "CRITICAL", "HIGH")):
        return "error"
    if any(token in normalized for token in ("WARNING", "ELEVATED", "MEDIUM")):
        return "warning"
    if normalized in {
        "STANDBY",
        "READY",
        "COMPLETE",
        "COMPLETED",
        "EVIDENCE READY",
        "ENABLED",
    }:
        return "ready"
    if normalized in {"OFFLINE", "DISCONNECTED"}:
        return "offline"
    if normalized in {"IDLE", "MANUAL", "0 ACTIVE"}:
        return "idle"
    if any(
        token in normalized
        for token in (
            "STARTUP",
            "LISTENING",
            "ANALYZING",
            "PROCESSING",
            "SPEAKING",
            "RUNNING",
            "WORKING",
            "ACTIVE",
            "CAPTURING",
            "EXTRACTING",
            "REVIEWING",
        )
    ):
        return "active"
    return "idle"


def activity_severity(text: str) -> str:
    normalized = text.strip().upper()
    if any(token in normalized for token in ("ERROR", "FAILED", "CRITICAL")):
        return "error"
    if any(token in normalized for token in ("WARNING", "ELEVATED")):
        return "warning"
    return "info"


class OperationalStateStore:
    """Cross-process read-only status source for desktop and mobile clients."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_activity_items: int = _MAX_ACTIVITY_ITEMS,
    ) -> None:
        self.path = Path(path) if path is not None else operational_state_path()
        self.max_activity_items = max(1, max_activity_items)
        self._lock = threading.RLock()

    def read_raw(self) -> dict[str, Any]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                return self._default_payload()
            return self._normalize_payload(payload)

    def read_snapshot(self) -> dict[str, Any]:
        payload = self.read_raw()
        desktop_online = self._heartbeat_is_fresh(payload)
        if not desktop_online:
            payload["statuses"]["agent"] = "OFFLINE"
        statuses = [
            {
                "id": key,
                "label": key.replace("_", " ").upper(),
                "value": payload["statuses"].get(key, DEFAULT_STATUSES[key]),
                "tone": status_tone(
                    payload["statuses"].get(key, DEFAULT_STATUSES[key])
                ),
            }
            for key in _STATUS_ORDER
        ]
        return {
            "host_platform": payload["host_platform"],
            "desktop_online": desktop_online,
            "updated_at": payload["updated_at"],
            "heartbeat_at": payload["heartbeat_at"],
            "statuses": statuses,
            "autonomy": deepcopy(payload["autonomy"]),
        }

    def read_activity(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = min(max(1, limit), self.max_activity_items)
        return deepcopy(self.read_raw()["activities"][:safe_limit])

    def mark_online(self, agent_status: str = "STARTUP") -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["desktop_online"] = True
            payload["statuses"]["agent"] = self._clean_status(agent_status)
            payload["heartbeat_at"] = utc_now_iso()

        self._update(mutate)

    def mark_offline(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["desktop_online"] = False
            payload["statuses"]["agent"] = "OFFLINE"
            payload["heartbeat_at"] = utc_now_iso()

        self._update(mutate)

    def heartbeat(self) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["heartbeat_at"] = utc_now_iso()

        self._update(mutate)

    def set_status(self, name: str, value: str) -> None:
        key = name.strip().lower()
        if key not in DEFAULT_STATUSES:
            raise ValueError(f"Unknown operational status: {name}")

        def mutate(payload: dict[str, Any]) -> None:
            payload["statuses"][key] = self._clean_status(value)

        self._update(mutate)

    def set_autonomy(self, enabled: bool, label: str | None = None) -> None:
        def mutate(payload: dict[str, Any]) -> None:
            payload["autonomy"] = {
                "enabled": bool(enabled),
                "label": (
                    self._clean_status(label)
                    if label
                    else ("ENABLED" if enabled else "MANUAL")
                ),
            }

        self._update(mutate)

    def add_activity(
        self,
        message: str,
        *,
        category: str | None = None,
        severity: str | None = None,
        source: str = "desktop",
    ) -> None:
        clean_message = message.strip()
        if not clean_message:
            return
        inferred_category = (
            category.strip().upper()
            if category and category.strip()
            else clean_message.split(maxsplit=1)[0].upper()
        )
        normalized_severity = (
            severity.strip().lower()
            if severity and severity.strip()
            else activity_severity(clean_message)
        )
        if normalized_severity not in {"info", "warning", "error"}:
            normalized_severity = "info"

        def mutate(payload: dict[str, Any]) -> None:
            payload["activities"].insert(
                0,
                {
                    "id": uuid4().hex,
                    "category": inferred_category[:32],
                    "message": clean_message[:1_000],
                    "severity": normalized_severity,
                    "source": source.strip().lower()[:32] or "desktop",
                    "created_at": utc_now_iso(),
                },
            )
            del payload["activities"][self.max_activity_items :]

        self._update(mutate)

    def _update(self, mutator: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            payload = self.read_raw()
            mutator(payload)
            payload["updated_at"] = utc_now_iso()
            self._write(payload)

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _default_payload(self) -> dict[str, Any]:
        now = utc_now_iso()
        return {
            "schema_version": 1,
            "host_platform": platform.system() or "Unknown",
            "desktop_online": False,
            "updated_at": now,
            "heartbeat_at": now,
            "statuses": deepcopy(DEFAULT_STATUSES),
            "autonomy": {"enabled": False, "label": "MANUAL"},
            "activities": [],
        }

    def _normalize_payload(self, payload: Any) -> dict[str, Any]:
        default = self._default_payload()
        if not isinstance(payload, dict):
            return default

        statuses = payload.get("statuses")
        if not isinstance(statuses, dict):
            statuses = {}
        default["statuses"].update(
            {
                key: self._clean_status(str(statuses.get(key, value)))
                for key, value in DEFAULT_STATUSES.items()
            }
        )

        autonomy = payload.get("autonomy")
        if isinstance(autonomy, dict):
            enabled = bool(autonomy.get("enabled", False))
            default["autonomy"] = {
                "enabled": enabled,
                "label": self._clean_status(
                    str(
                        autonomy.get(
                            "label",
                            "ENABLED" if enabled else "MANUAL",
                        )
                    )
                ),
            }

        activities = payload.get("activities")
        if isinstance(activities, list):
            default["activities"] = [
                item
                for item in activities[: self.max_activity_items]
                if isinstance(item, dict)
            ]

        default["schema_version"] = int(payload.get("schema_version", 1))
        default["host_platform"] = str(
            payload.get("host_platform") or default["host_platform"]
        )
        default["desktop_online"] = bool(payload.get("desktop_online", False))
        default["updated_at"] = str(payload.get("updated_at") or default["updated_at"])
        default["heartbeat_at"] = str(
            payload.get("heartbeat_at") or default["heartbeat_at"]
        )
        return default

    @staticmethod
    def _heartbeat_is_fresh(payload: dict[str, Any]) -> bool:
        if not bool(payload.get("desktop_online", False)):
            return False
        try:
            heartbeat = datetime.fromisoformat(str(payload["heartbeat_at"]))
        except (KeyError, TypeError, ValueError):
            return False
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)
        return age.total_seconds() <= 90

    @staticmethod
    def _clean_status(value: str) -> str:
        return value.strip().upper()[:64] or "IDLE"
