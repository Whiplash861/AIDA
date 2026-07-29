# AIDA Bug Reporting

AIDA's frontend includes a **REPORT BUG** button that opens a local-first support form.

## Registered mailbox

The default destination is:

```text
AIDAdeveloper@outlook.com
```

The mailbox address is not a secret. AIDA never stores the Outlook password.

## Delivery architecture

1. The report is validated and sanitized locally.
2. A JSON copy is written atomically to AIDA's local bug-report outbox.
3. When Microsoft delivery is configured, AIDA signs in through Microsoft Graph using delegated `Mail.Send` permission.
4. Microsoft Graph accepts the message for delivery.
5. The local report moves from `pending` to `sent`.
6. If authentication, network access, or delivery fails, the report remains in `pending` with the failure reason.

The local outbox is stored below the current Windows user's AIDA application-data directory. Reports and delivery records are excluded from Git by the repository's existing database/runtime exclusions.

## Microsoft application registration

The Outlook mailbox and the Microsoft application registration are separate objects. The mailbox receives the reports. The application registration gives the installed AIDA desktop application permission to send mail after the mailbox owner signs in.

Create a Microsoft Entra application registration with these properties:

- Supported account type: personal Microsoft accounts, or organizational directories plus personal Microsoft accounts.
- Public client flow: enabled.
- Microsoft Graph delegated permission: `Mail.Send` only.
- No client secret is required or permitted in the AIDA desktop configuration.

Copy the **Application (client) ID** into the local `.env` file:

```text
AIDA_BUG_REPORT_RECIPIENT=AIDAdeveloper@outlook.com
AIDA_MICROSOFT_GRAPH_CLIENT_ID=<application-client-id>
```

Then update the virtual environment:

```powershell
python -m pip install -r requirements.txt
```

On the first submitted report, AIDA displays Microsoft's device-code sign-in instructions. Sign in as `AIDAdeveloper@outlook.com`. Later submissions use the encrypted Microsoft token cache when a valid delegated token can be refreshed silently.

## Token protection

AIDA uses Microsoft Authentication Library Extensions for encrypted desktop token persistence. On Windows, the persistence layer uses Windows data protection. AIDA refuses to fall back to plaintext token storage.

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
- Password, API-key, access-token, and similar inline secret assignments are redacted before persistence or delivery.
- Log inclusion is disabled by default.
- The report is sent only to the registered developer mailbox.
- A report ID is generated for every submission and stored in AIDA's local Memory Bank event history.

## Delivery result meanings

**Sent** means Microsoft Graph returned `202 Accepted`. This confirms that Graph accepted the message for processing; it is not a guarantee that all downstream mail transport has completed.

**Queued** means AIDA preserved the report locally because Microsoft delivery was not configured or did not complete. The report has not been lost.
