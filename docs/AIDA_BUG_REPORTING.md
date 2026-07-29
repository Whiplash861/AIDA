# AIDA Bug Reporting

AIDA's frontend includes a **REPORT BUG** button that opens a local-first support form.

## Registered mailbox

The default destination is:

```text
AIDAdeveloper@outlook.com
```

The address is not a secret. AIDA does not sign in to that mailbox and stores no mailbox password, API key, client secret, or service credential.

## Delivery architecture

1. The report is validated and sanitized locally.
2. A JSON copy is written atomically to AIDA's local bug-report outbox.
3. AIDA creates an RFC 5322 `.eml` file addressed to the registered developer mailbox.
4. AIDA marks the message as unsent so compatible desktop mail clients can open it as an editable draft.
5. Windows opens the file through the user's default `.eml` application.
6. The user reviews the complete draft and clicks **Send** in the mail application.
7. AIDA records that the draft was prepared, but never claims that the message was delivered.

No Entra tenant, Microsoft Graph registration, SendGrid account, SMTP password, paid subscription, or hosted backend is required.

## Local storage

Runtime files are stored below the current Windows user's AIDA application-data directory:

```text
%LOCALAPPDATA%\AIDA\support\bug_reports\
```

Subdirectories include:

- `pending` — JSON reports whose draft handoff did not complete.
- `drafts` — JSON records for successfully prepared drafts.
- `mail_drafts` — reviewable `.eml` files.

A draft-opening failure does not discard the report. AIDA preserves both the JSON record and, when creation succeeded, the `.eml` file for manual opening.

## Optional configuration

The registered destination may be overridden locally:

```text
AIDA_BUG_REPORT_RECIPIENT=AIDAdeveloper@outlook.com
```

No sender address or credential is configured. The user's default mail client selects the sending account when the user sends the draft.

## Form contents

The form includes:

- Title
- Category
- Severity
- Description
- Expected behavior
- Reproduction steps
- Optional reporter contact
- Optional basic system information
- Optional recent AIDA log excerpts

System information is limited to AIDA version, Windows version, architecture, and Python version. Recent logs are excluded by default and require an explicit checkbox selection.

## Privacy rules

- Reports bypass the language model.
- Reports are not added to Azure/OpenAI conversation context.
- Password, API-key, access-token, bearer-token, client-secret, and JWT-like values are redacted before persistence or draft creation.
- Log inclusion is disabled by default.
- The complete draft remains visible to the user before transmission.
- The user retains final authority by clicking **Send**.
- A report ID is generated for every submission and stored in AIDA's local Memory Bank event history.

## Status meanings

**Draft ready** means AIDA preserved the report, generated the `.eml` file, and asked the operating system to open it. The user must still review and send it.

**Queued** means the report remains safely stored locally because the draft could not be prepared or opened automatically. It has not been lost.

AIDA cannot confirm delivery because sending occurs in the user's external mail application.
