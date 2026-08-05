from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from aida.artificer.models import utc_now


@dataclass(frozen=True, slots=True)
class DeveloperRecord:
    developer_id: str
    display_name: str
    role: str
    authorized_report_categories: tuple[str, ...]
    public_key_pem: str | None = None
    active: bool = True
    assigned_by: str = "owner"
    assigned_at_utc: str = field(default_factory=lambda: utc_now().isoformat())


class DeveloperRegistry:
    def __init__(self, path: str | Path, *, owner_name: str = "Austin Jolly") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.owner_name = owner_name
        self._records = self._load()
        if not self._records:
            self._records = {
                "owner": DeveloperRecord(
                    developer_id="owner",
                    display_name=owner_name,
                    role="owner",
                    authorized_report_categories=("*",),
                    active=True,
                    assigned_by="system_bootstrap",
                )
            }
            self._save()

    def list_active(self, report_type: str | None = None) -> tuple[DeveloperRecord, ...]:
        records = []
        for record in self._records.values():
            if not record.active:
                continue
            if report_type is not None and "*" not in record.authorized_report_categories:
                if report_type not in record.authorized_report_categories:
                    continue
            records.append(record)
        return tuple(records)

    def add_or_update(self, record: DeveloperRecord, *, acting_developer_id: str) -> None:
        actor = self._records.get(acting_developer_id)
        if actor is None or not actor.active or actor.role != "owner":
            raise PermissionError("Only an active owner may change developer recipients")
        self._records[record.developer_id] = record
        self._save()

    def deactivate(self, developer_id: str, *, acting_developer_id: str) -> None:
        actor = self._records.get(acting_developer_id)
        if actor is None or not actor.active or actor.role != "owner":
            raise PermissionError("Only an active owner may change developer recipients")
        if developer_id == "owner":
            raise PermissionError("The owner record cannot be deactivated by the Artificer")
        existing = self._records.get(developer_id)
        if existing is None:
            raise KeyError(developer_id)
        self._records[developer_id] = DeveloperRecord(
            developer_id=existing.developer_id,
            display_name=existing.display_name,
            role=existing.role,
            authorized_report_categories=existing.authorized_report_categories,
            public_key_pem=existing.public_key_pem,
            active=False,
            assigned_by=existing.assigned_by,
            assigned_at_utc=existing.assigned_at_utc,
        )
        self._save()

    def _load(self) -> dict[str, DeveloperRecord]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return {
                item["developer_id"]: DeveloperRecord(
                    developer_id=item["developer_id"],
                    display_name=item["display_name"],
                    role=item["role"],
                    authorized_report_categories=tuple(item.get("authorized_report_categories", [])),
                    public_key_pem=item.get("public_key_pem"),
                    active=bool(item.get("active", True)),
                    assigned_by=item.get("assigned_by", "owner"),
                    assigned_at_utc=item.get("assigned_at_utc", ""),
                )
                for item in payload.get("developers", [])
            }
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def _save(self) -> None:
        payload = {"developers": [asdict(record) for record in self._records.values()]}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)
