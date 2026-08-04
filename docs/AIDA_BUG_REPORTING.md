# AIDA Bug Reporting

## Purpose

AIDA's bug reporter gives early-alpha testers a local, reviewable way to prepare a support report for `AIDAdeveloper@outlook.com` without storing a mailbox password, API key, paid-mail-service credential, or hosted-backend secret.

## Workflow

1. The tester selects **REPORT BUG**.
2. AIDA collects the entered title, category, severity, description, expected behavior, reproduction steps, and optional contact information.
3. Basic AIDA, Windows, architecture, and Python information can be included.
4. Recent log excerpts remain optional and require explicit selection.
5. AIDA sanitizes likely passwords, bearer tokens, API keys, client secrets, and JWT-style credentials.
6. A JSON record is written atomically to the local outbox.
7. AIDA creates a standards-compliant `.eml` draft addressed to `AIDAdeveloper@outlook.com`.
8. AIDA opens a local review window showing the complete prepared report.
9. The tester chooses an external handoff and manually clicks **Send**.

AIDA never claims that an external service accepted or delivered the message.

## Handoff choices

- **Outlook Web — Recommended:** validated to open a correctly encoded compose window and deliver to the developer inbox.
- **Gmail Web — Fallback:** technically functional, but Outlook may initially classify a Gmail-originated test report as junk.
- **Default mail application:** opens the local `.eml` association. An unconfigured desktop client may display its account-setup screen instead of a compose window.
- **Copy full report:** copies the complete sanitized report for manual pasting.
- **Open draft folder:** opens the preserved local draft location.

Webmail handoff percent-encodes spaces and line breaks. The complete report is also copied to the clipboard before a webmail compose page opens. Large reports may be shortened in the browser URL while the full sanitized report remains copied and stored locally.

## Local storage

Reports are stored beneath:

```text
%LOCALAPPDATA%\AIDA\support\bug_reports\
```

Subdirectories preserve pending records, prepared draft records, and `.eml` files. A failed external handoff does not delete the local report.

## Optional configuration

The registered destination may be overridden locally:

```text
AIDA_BUG_REPORT_RECIPIENT=AIDAdeveloper@outlook.com
```

No sender address or credential is configured. The user chooses the sending account in the external mail application or webmail session.

## Privacy boundaries

- Bug reports remain local-only until the tester deliberately chooses an external handoff.
- Security evidence and bug-report contents are excluded from language-model context.
- Recent logs are opt-in.
- The tester can review the complete prepared body before sending.
- No Outlook password, Gmail password, Entra client ID, Microsoft Graph token, SendGrid key, or SMTP credential is stored.
- Redaction reduces accidental secret exposure but does not replace user review.

## Status meanings

**Draft ready** means AIDA preserved the report, generated the `.eml` file, and opened her local review window. The user must still choose a handoff, review the external compose window, and send it.

**Queued** means the report remains safely stored locally because the draft could not be prepared. It has not been lost.

AIDA cannot confirm delivery because sending occurs in an external mail service controlled by the user.

## Validated behavior

- Local record creation and persistence
- `.eml` construction with destination, subject, report ID, and unsent marker
- Secret redaction
- Report-model normalization when Qt returns combo-box values as plain strings
- Local review window
- Outlook Web compose and inbox delivery
- Gmail Web compose and delivery, with junk-folder warning
- Correct percent encoding of spaces, line breaks, and literal plus signs
- Preservation when the default mail application is unavailable or unconfigured

## Remaining hardening

- At-rest encryption for sensitive local support records
- Retention controls and user-visible outbox management
- Attachment review and optional screenshot support
- Alpha packaging tests across systems with different default browser and mail associations
