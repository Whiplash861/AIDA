from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr
from pathlib import Path
from typing import Callable, Protocol

from aida.memory.models import ProcessOutcome
from aida.memory.privacy import sanitize_text
from aida.memory.service import MemoryService
from aida.support.models import (
    BugDeliveryStatus,
    BugReport,
    BugReportDraft,
    BugReportSubmissionResult,
)


class BugReportConfigurationError(RuntimeError):
    pass


class BugReportDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        draft_path: str | Path | None = None,
    ) -> None:
        super().__init__(message)
        self.draft_path = Path(draft_path) if draft_path is not None else None


DraftLauncher = Callable[[Path], None]


class BugReportTransport(Protocol):
    @property
    def configured(self) -> bool:
        ...

    @property
    def destination_address(self) -> str:
        ...

    def prepare(self, report: BugReport) -> Path:
        ...


@dataclass(frozen=True, slots=True)
class EmlDraftConfig:
    recipient_address: str
    drafts_dir: str | Path
    subject_prefix: str = "AIDA Bug Report"

    @property
    def configured(self) -> bool:
        _, address = parseaddr(self.recipient_address.strip())
        return bool(address and "@" in address)


class EmlBugReportTransport:
    """Create a reviewable local email draft and open the default mail client."""

    def __init__(
        self,
        config: EmlDraftConfig,
        *,
        launcher: DraftLauncher | None = None,
    ) -> None:
        self.config = config
        self.launcher = launcher or _open_with_default_application

    @property
    def configured(self) -> bool:
        return self.config.configured

    @property
    def destination_address(self) -> str:
        return self.config.recipient_address.strip()

    def prepare(self, report: BugReport) -> Path:
        if not self.configured:
            raise BugReportConfigurationError(
                "The AIDA bug-report destination address is invalid."
            )
        _validate_email(self.destination_address, "recipient address")

        drafts_dir = Path(self.config.drafts_dir)
        drafts_dir.mkdir(parents=True, exist_ok=True)
        target = drafts_dir / f"{report.report_id}.eml"

        message = EmailMessage(policy=policy.default)
        message["To"] = self.destination_address
        message["Subject"] = _single_line(
            f"[{report.severity.value.upper()}] "
            f"{self.config.subject_prefix}: {report.report_id} - {report.title}"
        )
        message["Date"] = format_datetime(report.created_at)
        message["Message-ID"] = make_msgid(domain="aida.local")
        message["X-AIDA-Report-ID"] = report.report_id
        # Outlook and several desktop clients recognize this as an editable draft.
        message["X-Unsent"] = "1"
        message.set_content(render_bug_report_email(report))

        _atomic_bytes_write(target, message.as_bytes(policy=policy.default))
        try:
            self.launcher(target)
        except OSError as exc:
            raise BugReportDeliveryError(
                "The email draft was created, but Windows could not open it in "
                f"the default mail application. Open it manually: {target}",
                draft_path=target,
            ) from exc
        return target


class BugReportOutbox:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.pending_dir = self.root / "pending"
        self.drafts_dir = self.root / "drafts"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    def queue(self, report: BugReport) -> Path:
        target = self.pending_dir / f"{report.report_id}.json"
        _atomic_json_write(
            target,
            {
                "delivery_status": BugDeliveryStatus.QUEUED.value,
                "attempt_count": 0,
                "last_error": "",
                "report": report.to_dict(),
            },
        )
        return target

    def mark_failed(self, report: BugReport, error_message: str) -> Path:
        target = self.pending_dir / f"{report.report_id}.json"
        existing = _read_json(target)
        attempts = int(existing.get("attempt_count", 0)) + 1
        _atomic_json_write(
            target,
            {
                "delivery_status": BugDeliveryStatus.QUEUED.value,
                "attempt_count": attempts,
                "last_error": sanitize_text(error_message)[:1000],
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                "report": report.to_dict(),
            },
        )
        return target

    def mark_draft_ready(
        self,
        report: BugReport,
        draft_path: str | Path,
    ) -> Path:
        pending = self.pending_dir / f"{report.report_id}.json"
        ready = self.drafts_dir / f"{report.report_id}.json"
        existing = _read_json(pending)
        _atomic_json_write(
            ready,
            {
                **existing,
                "delivery_status": BugDeliveryStatus.DRAFT_READY.value,
                "draft_created_at": datetime.now(timezone.utc).isoformat(),
                "draft_path": str(Path(draft_path)),
                "last_error": "",
                "report": report.to_dict(),
            },
        )
        pending.unlink(missing_ok=True)
        return ready


class BugReportService:
    def __init__(
        self,
        *,
        version: str,
        log_dir: str | Path,
        outbox: BugReportOutbox,
        memory: MemoryService,
        transport: BugReportTransport | None,
    ) -> None:
        self.version = version
        self.log_dir = Path(log_dir)
        self.outbox = outbox
        self.memory = memory
        self.transport = transport

    @property
    def delivery_configured(self) -> bool:
        """Compatibility name for the frontend's draft-handoff readiness."""
        return bool(self.transport is not None and self.transport.configured)

    def submit(self, draft: BugReportDraft) -> BugReportSubmissionResult:
        clean = draft.validated()
        report = BugReport(
            title=sanitize_text(clean.title),
            category=clean.category,
            severity=clean.severity,
            description=sanitize_text(clean.description),
            expected_behavior=sanitize_text(clean.expected_behavior),
            reproduction_steps=sanitize_text(clean.reproduction_steps),
            reporter_contact=sanitize_text(clean.reporter_contact),
            system_info=(
                collect_system_info(self.version)
                if clean.include_system_info
                else {}
            ),
            recent_logs=(
                collect_recent_logs(self.log_dir)
                if clean.include_recent_logs
                else ()
            ),
        )
        queued_path = self.outbox.queue(report)

        if not self.delivery_configured:
            message = (
                "Bug report saved to AIDA's local outbox. The email-draft "
                "handoff is not available."
            )
            self._record(
                report,
                "BUG_REPORT_QUEUED",
                message,
                ProcessOutcome.PARTIAL,
                queued_path,
            )
            return BugReportSubmissionResult(
                report_id=report.report_id,
                status=BugDeliveryStatus.QUEUED,
                message=message,
                local_record_path=str(queued_path),
            )

        try:
            assert self.transport is not None
            draft_path = self.transport.prepare(report)
        except (BugReportConfigurationError, BugReportDeliveryError) as exc:
            queued_path = self.outbox.mark_failed(report, str(exc))
            saved_draft = (
                str(exc.draft_path)
                if isinstance(exc, BugReportDeliveryError)
                and exc.draft_path is not None
                else ""
            )
            message = (
                "Bug report was preserved in AIDA's local outbox. "
                f"The email draft could not be opened automatically: {exc}"
            )
            self._record(
                report,
                "BUG_REPORT_DRAFT_FAILED",
                message,
                ProcessOutcome.PARTIAL,
                queued_path,
            )
            return BugReportSubmissionResult(
                report_id=report.report_id,
                status=BugDeliveryStatus.QUEUED,
                message=message,
                local_record_path=str(queued_path),
                draft_path=saved_draft,
            )

        record_path = self.outbox.mark_draft_ready(report, draft_path)
        destination = self.transport.destination_address
        message = (
            f"Bug report {report.report_id} was saved locally and opened as an "
            f"email draft addressed to {destination}. Review it and click Send "
            "in your mail application. AIDA cannot confirm delivery."
        )
        self._record(
            report,
            "BUG_REPORT_DRAFT_READY",
            message,
            ProcessOutcome.PARTIAL,
            record_path,
        )
        return BugReportSubmissionResult(
            report_id=report.report_id,
            status=BugDeliveryStatus.DRAFT_READY,
            message=message,
            local_record_path=str(record_path),
            draft_path=str(draft_path),
        )

    def _record(
        self,
        report: BugReport,
        event_type: str,
        summary: str,
        outcome: ProcessOutcome,
        path: Path,
    ) -> None:
        self.memory.log_event(
            event_type,
            "support.bug_report",
            summary,
            payload={
                "report_id": report.report_id,
                "category": report.category.value,
                "severity": report.severity.value,
                "title": report.title,
                "local_record_path": str(path),
            },
            outcome=outcome,
            confidence=1.0,
            promote=True,
        )


def collect_system_info(version: str) -> dict[str, str]:
    return {
        "aida_version": version,
        "operating_system": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
    }


def collect_recent_logs(
    log_dir: str | Path,
    *,
    max_files: int = 2,
    max_lines_per_file: int = 120,
    max_total_characters: int = 40_000,
) -> tuple[str, ...]:
    root = Path(log_dir)
    if not root.exists():
        return ()
    files = sorted(
        (path for path in root.glob("*.log") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:max_files]
    collected: list[str] = []
    remaining = max_total_characters
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        excerpt = "\n".join(
            sanitize_text(line) for line in lines[-max_lines_per_file:]
        )
        excerpt = excerpt[:remaining]
        if excerpt:
            collected.append(f"--- {path.name} ---\n{excerpt}")
            remaining -= len(excerpt)
        if remaining <= 0:
            break
    return tuple(collected)


def render_bug_report_email(report: BugReport) -> str:
    system_lines = (
        "\n".join(f"- {key}: {value}" for key, value in report.system_info.items())
        or "- Not included"
    )
    logs = "\n\n".join(report.recent_logs) or "Not included"
    return (
        "AIDA BUG REPORT\n"
        "===============\n\n"
        "This draft was generated locally by AIDA. Review all included details "
        "before sending.\n\n"
        f"Report ID: {report.report_id}\n"
        f"Created: {report.created_at.astimezone().isoformat()}\n"
        f"Category: {report.category.value}\n"
        f"Severity: {report.severity.value}\n"
        f"Title: {report.title}\n\n"
        "DESCRIPTION\n"
        f"{report.description}\n\n"
        "EXPECTED BEHAVIOR\n"
        f"{report.expected_behavior or 'Not provided'}\n\n"
        "REPRODUCTION STEPS\n"
        f"{report.reproduction_steps or 'Not provided'}\n\n"
        "REPORTER CONTACT\n"
        f"{report.reporter_contact or 'Not provided'}\n\n"
        "SYSTEM INFORMATION\n"
        f"{system_lines}\n\n"
        "RECENT LOG EXCERPTS\n"
        f"{logs}\n"
    )


def _open_with_default_application(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(
        command,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _single_line(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:240]


def _validate_email(value: str, label: str) -> None:
    _, address = parseaddr(value.strip())
    if not address or "@" not in address:
        raise BugReportConfigurationError(f"Invalid {label}: {value!r}")


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_bytes_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
