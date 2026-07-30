from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import quote, urlencode

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


_BROWSER_BODY_LIMIT = 6_000


@dataclass(frozen=True, slots=True)
class PreparedEmailDraft:
    path: Path
    recipient: str
    subject: str
    body: str


def read_prepared_email_draft(path: str | Path) -> PreparedEmailDraft:
    draft_path = Path(path)
    message = BytesParser(policy=policy.default).parsebytes(draft_path.read_bytes())
    body_part = message.get_body(preferencelist=("plain",))
    if body_part is not None:
        body = body_part.get_content()
    elif message.is_multipart():
        body = ""
    else:
        body = message.get_content()
    return PreparedEmailDraft(
        path=draft_path,
        recipient=str(message.get("To", "")).strip(),
        subject=str(message.get("Subject", "")).strip(),
        body=str(body),
    )


def browser_handoff_body(body: str) -> str:
    if len(body) <= _BROWSER_BODY_LIMIT:
        return body
    suffix = (
        "\n\n[The report was shortened for browser handoff. AIDA copied the "
        "complete report to the clipboard and retained the full local .eml draft.]"
    )
    return body[: _BROWSER_BODY_LIMIT - len(suffix)] + suffix


def _webmail_query(parameters: dict[str, str]) -> str:
    """Encode webmail query values without form-style '+' space substitution.

    Outlook Web can display '+' literally inside the compose body even though
    application/x-www-form-urlencoded normally treats it as a space. Percent
    encoding spaces as %20 is accepted by both Outlook Web and Gmail and keeps
    the report human-readable.
    """

    return urlencode(parameters, quote_via=quote, safe="")


def build_gmail_compose_url(draft: PreparedEmailDraft) -> str:
    return "https://mail.google.com/mail/?" + _webmail_query(
        {
            "view": "cm",
            "fs": "1",
            "to": draft.recipient,
            "su": draft.subject,
            "body": browser_handoff_body(draft.body),
        }
    )


def build_outlook_compose_url(draft: PreparedEmailDraft) -> str:
    return "https://outlook.live.com/mail/0/deeplink/compose?" + _webmail_query(
        {
            "to": draft.recipient,
            "subject": draft.subject,
            "body": browser_handoff_body(draft.body),
        }
    )


class BugReportDraftReviewDialog(QDialog):
    """Review a prepared bug report before choosing an external mail handoff."""

    def __init__(
        self,
        draft_path: str | Path,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.draft = read_prepared_email_draft(draft_path)

        self.setWindowTitle("Review AIDA Bug Report")
        self.setObjectName("bugReportReviewDialog")
        self.resize(780, 680)
        self.setMinimumSize(660, 540)

        destination = QLabel(
            f"Destination: {self.draft.recipient}\n"
            "AIDA has prepared this report locally but has not sent it. Review the "
            "contents below, then choose a mail handoff. Gmail Web is the primary "
            "path for this installation."
        )
        destination.setWordWrap(True)

        subject = QLabel(f"Subject: {self.draft.subject}")
        subject.setWordWrap(True)

        self.body_view = QTextEdit()
        self.body_view.setReadOnly(True)
        self.body_view.setPlainText(self.draft.body)

        self.status_label = QLabel(
            "No delivery has occurred. Webmail actions copy the complete report to "
            "the clipboard before opening the compose page."
        )
        self.status_label.setWordWrap(True)

        self.gmail_button = QPushButton("Copy + Open Gmail Web")
        self.outlook_button = QPushButton("Copy + Open Outlook Web")
        self.default_button = QPushButton("Open Default Mail App")
        self.copy_button = QPushButton("Copy Full Report")
        self.folder_button = QPushButton("Open Draft Folder")
        self.close_button = QPushButton("Close")

        primary_actions = QHBoxLayout()
        primary_actions.addWidget(self.gmail_button)
        primary_actions.addWidget(self.outlook_button)

        secondary_actions = QHBoxLayout()
        secondary_actions.addWidget(self.default_button)
        secondary_actions.addWidget(self.copy_button)
        secondary_actions.addWidget(self.folder_button)
        secondary_actions.addStretch()
        secondary_actions.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(destination)
        layout.addWidget(subject)
        layout.addWidget(self.body_view, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(primary_actions)
        layout.addLayout(secondary_actions)

        self.gmail_button.clicked.connect(self.open_gmail)
        self.outlook_button.clicked.connect(self.open_outlook)
        self.default_button.clicked.connect(self.open_default_mail_app)
        self.copy_button.clicked.connect(self.copy_full_report)
        self.folder_button.clicked.connect(self.open_draft_folder)
        self.close_button.clicked.connect(self.close)

    @Slot()
    def copy_full_report(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.draft.body)
        self.status_label.setText(
            "The complete sanitized report is now on the clipboard. No delivery "
            "has occurred."
        )

    @Slot()
    def open_gmail(self) -> None:
        self._open_webmail(build_gmail_compose_url(self.draft), "Gmail Web")

    @Slot()
    def open_outlook(self) -> None:
        self._open_webmail(build_outlook_compose_url(self.draft), "Outlook Web")

    def _open_webmail(self, url: str, provider_name: str) -> None:
        self.copy_full_report()
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(
                self,
                "Webmail could not open",
                f"AIDA could not open {provider_name}. The full report remains on "
                "the clipboard and in the local draft file.",
            )
            return
        self.status_label.setText(
            f"{provider_name} was opened and the complete report was copied to the "
            "clipboard. Review the compose window and click Send yourself. AIDA "
            "cannot confirm delivery."
        )

    @Slot()
    def open_default_mail_app(self) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.draft.path))):
            QMessageBox.warning(
                self,
                "Mail application could not open",
                "Windows could not open the local .eml draft. Use Gmail Web, "
                "Outlook Web, or open the draft folder instead.",
            )
            return
        self.status_label.setText(
            "Windows opened the registered .eml application. AIDA cannot determine "
            "whether that application is configured or whether the report was sent."
        )

    @Slot()
    def open_draft_folder(self) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["explorer", f"/select,{self.draft.path}"],
                    close_fds=True,
                )
            else:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(self.draft.path.parent))
                )
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Draft folder could not open",
                f"Open this path manually:\n{self.draft.path}\n\nError: {exc}",
            )
            return
        self.status_label.setText(
            f"Opened the local draft location: {self.draft.path}"
        )
