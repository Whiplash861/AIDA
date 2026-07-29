# AIDA Bug Reporting

AIDA's frontend includes a **REPORT BUG** button that opens a local-first support form.

## Registered mailbox

The default sender and destination mailbox is:

```text
AIDAdeveloper@outlook.com
```

The mailbox address is not a secret. AIDA never stores the Outlook password.

## Delivery architecture

1. The report is validated and sanitized locally.
2. A JSON copy is written atomically to AIDA's local bug-report outbox.
3. When delivery is configured, AIDA sends the report through the SendGrid Mail Send API.
4. The local report moves from `pending` to `sent` only after SendGrid returns `202 Accepted`.
5. If configuration, network access, or delivery fails, the report remains in `pending` with the failure reason.

The local outbox is stored below the current Windows user's AIDA application-data directory. Reports and delivery records are excluded from Git by the repository's existing database/runtime exclusions.

## SendGrid setup

The Outlook mailbox and SendGrid account are separate. The Outlook mailbox receives and may also appear as the verified sender. SendGrid provides the transactional delivery API.

1. Create a Twilio SendGrid account.
2. Open **Settings > Sender Authentication**.
3. Use **Single Sender Verification** for `AIDAdeveloper@outlook.com`.
4. Open the verification message received in that Outlook inbox and approve the sender.
5. Create an API key with **Mail Send** permission only.
6. Store the key only in AIDA's local `.env` file.

```text
AIDA_BUG_REPORT_SENDER=AIDAdeveloper@outlook.com
AIDA_BUG_REPORT_RECIPIENT=AIDAdeveloper@outlook.com
AIDA_SENDGRID_API_KEY=<mail-send-api-key>
```

The API key is revocable and does not grant access to the Outlook mailbox. Do not enter the Outlook password into AIDA.

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
- Password, API-key, access-token, bearer-token, client-secret, and JWT-like values are redacted before persistence or delivery.
- Log inclusion is disabled by default.
- The report is sent only to the registered developer mailbox.
- A report ID is generated for every submission and stored in AIDA's local Memory Bank event history.
- The SendGrid API key is loaded from local configuration and is never written into the report or Memory Bank.

## Delivery result meanings

**Sent** means SendGrid returned `202 Accepted`. This confirms that SendGrid accepted the message for processing; it is not a guarantee that all downstream mail transport has completed.

**Queued** means AIDA preserved the report locally because email delivery was not configured or did not complete. The report has not been lost.
