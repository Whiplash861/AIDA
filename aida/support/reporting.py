from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Callable, Protocol

import requests

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
    pass


AuthenticationPrompt = Callable[[str], None]


class BugReportTransport(Protocol):
    @property
    def configured(self) -> bool:
        ...

    def send(
        self,
        report: BugReport,
        *,
        authentication_prompt: AuthenticationPrompt | None = None,
    ) -> None:
        ...


@dataclass(frozen=True, slots=True)
class MicrosoftGraphMailConfig:
    client_id: str
    recipient_address: str
    expected_account: str
    token_cache_path: str
    authority: str = "https://login.microsoftonline.com/consumers"

    @property
    def configured(self) -> bool:
        values = (
            self.client_id,
            self.recipient_address,
            self.expected_account,
            self.token_cache_path,
        )
        return all(value.strip() for value in values)


class MicrosoftGraphBugReportTransport:
    """Delegated Microsoft Graph mail transport for a personal Outlook mailbox."""

    _SCOPES = ("Mail.Send",)

    def __init__(
        self,
        config: MicrosoftGraphMailConfig,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return self.config.configured

    def send(
        self,
        report: BugReport,
        *,
        authentication_prompt: AuthenticationPrompt | None = None,
    ) -> None:
        if not self.configured:
            raise BugReportConfigurationError(
                "Microsoft Graph bug-report delivery is not configured."
            )
        _validate_email(self.config.recipient_address, "recipient address")
        _validate_email(self.config.expected_account, "connected mailbox")

        app = self._build_client()
        result = self._acquire_token(
            app,
            authentication_prompt=authentication_prompt,
        )
        access_token = str(result.get("access_token", "")).strip()
        if not access_token:
            description = sanitize_text(
                str(result.get("error_description", "Authentication failed."))
            )
            raise BugReportDeliveryError(description[:800])

        self._verify_account(result)
        payload = {
            "message": {
                "subject": (
                    f"[{report.severity.value.upper()}] "
                    f"{report.report_id}: {report.title}"
                ),
                "body": {
                    "contentType": "Text",
                    "content": render_bug_report_email(report),
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": self.config.recipient_address.strip()
                        }
                    }
                ],
            },
            "saveToSentItems": True,
        }
        try:
            response = self.session.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise BugReportDeliveryError(
                "Microsoft Graph could not be reached."
            ) from exc
        if response.status_code != 202:
            detail = sanitize_text((response.text or "").strip())[:500]
            suffix = f" Details: {detail}" if detail else ""
            raise BugReportDeliveryError(
                f"Microsoft Graph rejected the report with HTTP "
                f"{response.status_code}.{suffix}"
            )

    def _build_client(self):
        try:
            import msal
            from msal_extensions import (
                PersistedTokenCache,
                build_encrypted_persistence,
            )
        except ImportError as exc:
            raise BugReportConfigurationError(
                "Install the msal and msal-extensions packages to connect the "
                "AIDA developer mailbox."
            ) from exc

        cache_path = Path(self.config.token_cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            persistence = build_encrypted_persistence(str(cache_path))
            cache = PersistedTokenCache(persistence)
        except Exception as exc:
            raise BugReportConfigurationError(
                "AIDA could not create an encrypted Microsoft token cache. "
                "Plaintext token storage is not permitted."
            ) from exc

        return msal.PublicClientApplication(
            self.config.client_id.strip(),
            authority=self.config.authority.strip(),
            token_cache=cache,
        )

    def _acquire_token(
        self,
        app,
        *,
        authentication_prompt: AuthenticationPrompt | None,
    ) -> dict:
        accounts = app.get_accounts(username=self.config.expected_account.strip())
        if accounts:
            result = app.acquire_token_silent(
                list(self._SCOPES),
                account=accounts[0],
            )
            if result:
                return result

        flow = app.initiate_device_flow(scopes=list(self._SCOPES))
        if "user_code" not in flow:
            raise BugReportDeliveryError(
                "Microsoft sign-in could not be started."
            )
        message = str(flow.get("message", "")).strip()
        if authentication_prompt is not None and message:
            authentication_prompt(message)
        return app.acquire_token_by_device_flow(flow)

    def _verify_account(self, result: dict) -> None:
        claims = result.get("id_token_claims")
        if not isinstance(claims, dict):
            return
        signed_in = str(
            claims.get("preferred_username")
            or claims.get("email")
            or ""
        ).strip()
        if signed_in and signed_in.casefold() != self.config.expected_account.casefold():
            raise BugReportDeliveryError(
                "The connected Microsoft account does not match the registered "
                f"AIDA mailbox ({self.config.expected_account})."
            )


class BugReportOutbox:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.pending_dir = self.root / "pending"
        self.sent_dir = self.root / "sent"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.sent_dir.mkdir(parents=True, exist_ok=True)

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

    def mark_sent(self, report: BugReport) -> Path:
        pending = self.pending_dir / f"{report.report_id}.json"
        sent = self.sent_dir / f"{report.report_id}.json"
        existing = _read_json(pending)
        _atomic_json_write(
            sent,
            {
                **existing,
                "delivery_status": BugDeliveryStatus.SENT.value,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "last_error": "",
                "report": report.to_dict(),
            },
        )
        pending.unlink(missing_ok=True)
        return sent


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
        return bool(self.transport is not None and self.transport.configured)

    def submit(
        self,
        draft: BugReportDraft,
        *,
        authentication_prompt: AuthenticationPrompt | None = None,
    ) -> BugReportSubmissionResult:
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
                "Bug report saved to AIDA's local outbox. Microsoft email "
                "delivery is not connected yet."
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
            self.transport.send(
                report,
                authentication_prompt=authentication_prompt,
            )
        except (BugReportConfigurationError, BugReportDeliveryError) as exc:
            queued_path = self.outbox.mark_failed(report, str(exc))
            message = (
                "Bug report was preserved in AIDA's local outbox because email "
                f"delivery failed: {exc}"
            )
            self._record(
                report,
                "BUG_REPORT_DELIVERY_FAILED",
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

        sent_path = self.outbox.mark_sent(report)
        message = (
            f"Bug report {report.report_id} was accepted by Microsoft Graph for "
            f"delivery to {self.transport.config.recipient_address}."
        )
        self._record(
            report,
            "BUG_REPORT_SENT",
            message,
            ProcessOutcome.SUCCEEDED,
            sent_path,
        )
        return BugReportSubmissionResult(
            report_id=report.report_id,
            status=BugDeliveryStatus.SENT,
            message=message,
            local_record_path=str(sent_path),
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
        excerpt = "\n".join(sanitize_text(line) for line in lines[-max_lines_per_file:])
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


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
