# AIDA Security, Autonomy, Intent, Memory, and Support Foundation

## Purpose

This prototype foundation gives AIDA deterministic, offline-capable infrastructure for security-task continuity, natural-language intent resolution, controlled autonomy policy, operational memory, threat reporting, Stand Down trust exceptions, application-health recovery planning, and local-first bug reporting.

The language model is not an execution authority. Registered local executors, explicit policy, exact-scope confirmations, and provider adapters control operations.

## Implemented in this branch

### Context Prediction Index

- Normalizes typed and speech-derived wording.
- Scores registered intent candidates from actions, objects, modifiers, aliases, conflicts, required slots, and structured session context.
- Preserves diagnostic Quickscan as distinct from Defender Surface Security Scan.
- Supports extensible intent definitions instead of a central wall of regular expressions.
- Returns local clarification when wording is ambiguous.
- Keeps local security, memory, autonomy, application, and support commands outside language-model context.

### Memory Bank

- User- and device-scoped SQLite Event Journal and Memory Bank.
- Plain-language rendering, search, revision history, soft deletion, permanent purge service, preferences, authorizations, process outcomes, Stand Down records, and security-task continuity.
- Frontend Memory Bank with searchable memories and event timeline.
- Recursive secret-field and inline-assignment redaction before persistence.
- Runtime data stored under the current user's local application-data directory.

### Security continuity

- Durable provider state and AIDA tracking state are separate.
- Open tasks survive frontend loss and can be reconciled at startup.
- Recovery requires a matching provider scan type plus matching provider Scan ID or a closely matching provider start time.
- Provider elapsed time and current AIDA monitoring elapsed time can be reported separately.
- Full-System Sweep launch and ten-minute messages explain that full scans may be lengthy.

### Provider-native cancellation

- Quick and Full Defender scans use the Defender `MpCmdRun.exe -Scan -Cancel` path.
- Cancellation requires an exact, single-use, expiring confirmation phrase.
- AIDA verifies that the active provider Scan ID still matches the confirmed scope.
- AIDA does not equate terminating a PowerShell host with cancelling Defender.
- Success is reported only after Defender publishes a terminal scan event.

### Controlled autonomy

- Frontend Autonomy switch defaults to disabled/manual control.
- Disabled autonomy routes operational proposals to the user regardless of severity.
- Read-only observation and urgent reporting remain available.
- A separate kill switch prevents autonomy from being re-enabled until explicitly released.
- Current levels are Manual, Observe, Triage, and Investigate.
- Budgets, cooldowns, quiet hours, and deterministic decision reporting are available.
- The autonomy engine evaluates proposals only; it does not silently execute them.

### Threat intelligence reports

- Separates observed facts from inferred purpose and possible impacts.
- Includes provider severity, predicted classification, confidence, potential damage, current state, and locally observed endpoints.
- Threat-actor attribution defaults to unknown unless provider-supplied evidence exists.
- Endpoint registration region is not represented as the actor's physical location.

### Stand Down

- Creates an AIDA-local user trust exception for an exact file identity.
- Does not create a Microsoft Defender exclusion, allow a threat, or certify a file as safe.
- Binds trust to path, SHA-256, size, modification identity, user, device, reason, and expiration.
- Explicit rescans bypass suppression.
- File changes, new alarms, expiration, or user revocation restore assessment.

### Application health and recovery planning

- Read-only inspection of running processes.
- Conservative health classifications and local evidence reports.
- Offline repair planning for graceful restart, Office repair, application repair, cache recovery, reset, forced termination, and Windows integrity paths.
- High-impact execution remains disabled during early alpha.

### Bug reporting

- The frontend includes a **REPORT BUG** form.
- Reports are sanitized and written atomically to a local outbox before transmission.
- Optional basic system context is enabled by default; recent log excerpts require explicit selection.
- Delivery uses the SendGrid Mail Send API with a verified sender identity.
- The registered sender and recipient are `AIDAdeveloper@outlook.com`.
- The SendGrid API key is loaded from local configuration and can be limited to mail sending.
- AIDA stores no Outlook password and requires no Entra or Microsoft Graph application registration for this transport.
- Failed or unconfigured delivery preserves the report in the pending outbox.

## Deliberately not enabled

- Autonomous quarantine, deletion, restoration, allow-listing, Defender exclusions, firewall changes, credential changes, reboot, shutdown, forced process termination, app reset, cache deletion, Office repair execution, DISM repair, SFC repair, or arbitrary vendor repair execution.
- Autonomous Full-System Sweeps.
- Arbitrary folder selection for autonomous Deep Scans.
- LLM-created commands or LLM-granted authorization.
- Claims of actor identity or physical location without reliable evidence.

## Data-protection status

The Memory Bank is stored in the current Windows user's local application-data directory, scoped by user and device, redacts likely secrets, uses SQLite transactions, WAL, foreign keys, and secure-delete mode where supported. Database-at-rest encryption with Windows user-bound protection is not included in this foundation and remains an early-alpha hardening item.

The SendGrid API key currently resides in AIDA's local `.env` file, which is excluded from Git. Before broader early-alpha distribution, move support-service credentials to Windows Credential Manager or another DPAPI-backed secret store.

## Required Windows field validation

- Fresh and recovered Full Sweep completion.
- Quick and Full cancellation request, rejection, completion race, and provider-confirmed cancellation.
- Startup recovery after app close, crash, Windows sleep, and provider delay.
- Frontend switch persistence and kill-switch lockout.
- Memory UI add, edit, search, soft delete, restart persistence, and multi-user isolation.
- Stand Down identity change and explicit-rescan behavior.
- Bug-report local queue, SendGrid sender verification, API acceptance, and mailbox arrival.
- Offline launch with Azure and ElevenLabs unavailable.
