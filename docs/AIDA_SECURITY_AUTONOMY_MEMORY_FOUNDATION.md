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
- Resolves read-only Observation checks and exact-scope Stand Down revocation commands locally.

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
- A recovered task preserves the original provider start time while beginning a new AIDA monitoring-session clock.
- Recovery count, last recovery time, provider Scan ID, cancellation request time, and provider-confirmed cancellation time are persisted.
- Heartbeats report **Provider-total elapsed** and **AIDA monitoring-session elapsed** as separate clocks.
- Full-System Sweep launch and ten-minute messages explain that full scans may be lengthy.
- Startup reattachment records interruption and recovery events without granting new authority.
- Stale Quick/Full records with no matching active provider scan are closed as **abandoned with unknown provider outcome**, never falsely labeled completed or cancelled.

### Provider-native cancellation

- Quick and Full Defender scans use the Defender `MpCmdRun.exe -Scan -Cancel` path.
- Cancellation requires the exact, single-use, expiring phrase `confirm scan cancellation`.
- AIDA verifies that the active provider Scan ID still matches the confirmed scope.
- AIDA does not equate terminating a PowerShell host with cancelling Defender.
- Success is reported only after Defender publishes a cancellation event.
- Completion-before-cancellation and unconfirmed cancellation remain distinct outcomes.
- Unconfirmed cancellation leaves the durable scan task active and monitoring continues.
- A missing provider Scan ID is linked to an AIDA task only when exactly one open Quick/Full Defender task makes that association unambiguous.

### Detection Intelligence

- Captures complete Defender detection snapshots before and after a fresh scan when available.
- Reconciles provider history with the scan window instead of treating all historical detections as new.
- Classifies findings as new, reactivated, unchanged active, status changed, resolved, or historical.
- Separately reports new/reactivated detections, pre-existing unresolved detections, and provider-confirmed resolved detections.
- Records resolution only when Defender explicitly reports an inactive state or successful provider action.
- Absence from a later history snapshot alone never produces `THREAT_NEUTRALIZED`.
- Stores `THREAT_DETECTED`, `THREAT_STILL_UNRESOLVED`, and `THREAT_NEUTRALIZED` events locally when their evidence requirements are met.
- Feeds unresolved findings into evidence-limited threat reports and Stand Down evaluation.

### Controlled autonomy

- Frontend Autonomy switch defaults to disabled/manual control.
- Disabled autonomy routes operational proposals to the user regardless of severity.
- A separate kill switch prevents autonomy from being re-enabled until explicitly released.
- Current levels are Manual, Observe, Triage, and Investigate.
- The implemented Observation service reads provider health, real-time protection, signature state, active scan state, unresolved detections, and active Stand Down count when available.
- Observation produces deterministic decision reports with evidence, policy version, considered action, disposition, remaining risk, and follow-up.
- Observation never executes a scan, quarantine, repair, termination, exclusion, or other operational response.
- Manual Observation commands are announced. Healthy scheduled observations run only while AIDA is idle and remain silent while still recording their result locally.
- A scheduled observation that identifies a user-action condition may surface the report but still takes no operational action.
- Surface and Deep autonomy remain gated behind higher policy levels, explicit settings, scope, cooldowns, and budgets.

### Threat intelligence reports

- Separates observed facts from inferred purpose and possible impacts.
- Includes provider severity, predicted classification, confidence, potential damage, current state, and locally observed endpoints.
- Threat-actor attribution defaults to unknown unless provider-supplied evidence exists.
- Endpoint registration region is not represented as the actor's physical location.

### Stand Down

- Creates an AIDA-local user trust exception for an exact file identity.
- Does not create a Microsoft Defender exclusion, allow a threat, or certify a file as safe.
- Binds trust to path, SHA-256, size, modification identity, user, device, reason, alarm count, and expiration.
- A new exception for the same path supersedes the older active record.
- Explicit rescans temporarily bypass recommendation suppression for that assessment.
- A new provider alarm or identity change suspends the exception before explicit-scan override is considered.
- Missing files, file changes, new alarms, expiration, or confirmed user revocation restore normal assessment.
- Revocation is scope-bound to exception ID, path, and hash and requires `confirm stand down revocation`.
- Provider findings remain factual even when an unchanged local trust exception suppresses repeated AIDA recommendations.

### Application health and recovery planning

- Read-only inspection of running processes.
- Conservative health classifications and local evidence reports.
- Offline repair planning for graceful restart, Office repair, application repair, cache recovery, reset, forced termination, and Windows integrity paths.
- High-impact execution remains disabled during early alpha.

### Bug reporting

- The frontend includes a **REPORT BUG** form.
- Reports are sanitized and written atomically to a local outbox before draft creation.
- Optional basic system context is enabled by default; recent log excerpts require explicit selection.
- AIDA creates a reviewable `.eml` draft addressed to `AIDAdeveloper@outlook.com`.
- AIDA opens a local review window with Outlook Web as the validated primary handoff, Gmail Web as a fallback, default mail application handoff, clipboard copy, and draft-folder access.
- The user reviews the report and clicks **Send**; AIDA never claims delivery occurred.
- No Entra tenant, Microsoft Graph registration, SendGrid account, SMTP password, paid subscription, or hosted backend is required.
- Failed handoff preserves the report and generated `.eml` file locally.

## Deliberately not enabled

- Autonomous quarantine, deletion, restoration, allow-listing, Defender exclusions, firewall changes, credential changes, reboot, shutdown, forced process termination, app reset, cache deletion, Office repair execution, DISM repair, SFC repair, or arbitrary vendor repair execution.
- Autonomous Full-System Sweeps.
- Arbitrary folder selection for autonomous Deep Scans.
- Autonomous Limited Triage execution in this implementation checkpoint.
- LLM-created commands or LLM-granted authorization.
- Claims of actor identity or physical location without reliable evidence.

## Data-protection status

The Memory Bank is stored in the current Windows user's local application-data directory, scoped by user and device, redacts likely secrets, uses SQLite transactions, WAL, foreign keys, and secure-delete mode where supported. Database-at-rest encryption with Windows user-bound protection is not included in this foundation and remains an early-alpha hardening item.

Security evidence, decision reports, Stand Down records, and bug reports remain local until an explicitly selected external handoff occurs. AIDA stores no mail-service credentials.

## Validation status

Previously completed Windows validation:

- Frontend launch.
- Memory add, search, revision, and restart persistence.
- Autonomy Enabled and Manual state persistence.
- Bug-report local preservation, Outlook Web handoff, manual sending, and inbox arrival.
- Gmail Web fallback delivery, with a recipient-side junk-folder warning.

Automated validation added in this checkpoint covers:

- Provider and AIDA monitoring-session continuity fields and additive database migration.
- Exact and time-bounded startup recovery matching plus stale-task abandonment.
- Confirmed and unconfirmed cancellation durability.
- Conservative provider Scan ID linking.
- Stand Down creation, supersession, explicit-scan override, new-alarm suspension, identity-change suspension, expiry, and revocation.
- Detection scan-window reconciliation, historical unresolved separation, and explicit evidence requirements for resolution.
- Observation-mode policy reporting without operational execution.
- CPI routing for Observation and Stand Down revocation.

The complete automated suite and Windows lifecycle tests must still be run after pulling this checkpoint. Use `docs/AIDA_SECURITY_LIFECYCLE_FIELD_TEST.md` for the integrated sequence.

## Remaining Windows field validation

- Fresh and recovered Surface and Full Sweep completion.
- Quick and Full cancellation request, rejection, completion race, and provider-confirmed cancellation.
- Startup recovery after app close, crash, Windows sleep, and provider delay.
- Stand Down identity change, new alarm, explicit-rescan behavior, expiry, and revocation.
- Detection Intelligence with a recognized harmless antivirus test artifact.
- Explicit and scheduled Observation-mode behavior.
- Kill-switch lockout and offline launch with Azure and ElevenLabs unavailable.
