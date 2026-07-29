from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


class BugSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BugCategory(StrEnum):
    FRONTEND = "frontend"
    SECURITY = "security"
    AUTONOMY = "autonomy"
    MEMORY = "memory"
    SPEECH = "speech"
    DIAGNOSTICS = "diagnostics"
    INSTALLATION = "installation"
    OTHER = "other"


class BugDeliveryStatus(StrEnum):
    DRAFT_READY = "draft_ready"
    QUEUED = "queued"
    SENT = "sent"  # Legacy records only; AIDA no longer sends mail automatically.


@dataclass(frozen=True, slots=True)
class BugReportDraft:
    title: str
    category: BugCategory
    severity: BugSeverity
    description: str
    expected_behavior: str = ""
    reproduction_steps: str = ""
    reporter_contact: str = ""
    include_system_info: bool = True
    include_recent_logs: bool = False

    def validated(self) -> BugReportDraft:
        title = self.title.strip()
        description = self.description.strip()
        if len(title) < 4:
            raise ValueError("Bug report title must contain at least four characters.")
        if len(title) > 160:
            raise ValueError("Bug report title cannot exceed 160 characters.")
        if len(description) < 10:
            raise ValueError("Bug description must contain at least ten characters.")
        return BugReportDraft(
            title=title,
            category=self.category,
            severity=self.severity,
            description=description,
            expected_behavior=self.expected_behavior.strip(),
            reproduction_steps=self.reproduction_steps.strip(),
            reporter_contact=self.reporter_contact.strip(),
            include_system_info=self.include_system_info,
            include_recent_logs=self.include_recent_logs,
        )


@dataclass(frozen=True, slots=True)
class BugReport:
    title: str
    category: BugCategory
    severity: BugSeverity
    description: str
    expected_behavior: str
    reproduction_steps: str
    reporter_contact: str
    system_info: dict[str, str] = field(default_factory=dict)
    recent_logs: tuple[str, ...] = ()
    report_id: str = field(default_factory=lambda: f"AIDA-BUG-{uuid4().hex[:12].upper()}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_at": self.created_at.isoformat(),
            "title": self.title,
            "category": self.category.value,
            "severity": self.severity.value,
            "description": self.description,
            "expected_behavior": self.expected_behavior,
            "reproduction_steps": self.reproduction_steps,
            "reporter_contact": self.reporter_contact,
            "system_info": dict(self.system_info),
            "recent_logs": list(self.recent_logs),
        }


@dataclass(frozen=True, slots=True)
class BugReportSubmissionResult:
    report_id: str
    status: BugDeliveryStatus
    message: str
    local_record_path: str
    draft_path: str = ""
