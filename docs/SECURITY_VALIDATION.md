# Security execution and verification

The reliability work preserves AIDA's local security workflow and existing interface appearance. It does not grant learned inference permission to act or enable autonomous remediation.

## Execution contracts

- A direct frontend scan executor requires explicit authorization provenance. Recovery validates the durable task, provider, mode, and native scan identity, then attaches without calling the scan-start operation.
- Fresh Defender scans may bind a unique native start at or after the request. Older same-mode scans cannot be silently adopted. Timestamp-only Quick/Full scan observations cannot terminate a scan host. Ambiguous multi-target custom-scan events do not prove that every requested target completed.
- Provider execution state and findings availability are separate. A completed scan with an unreadable findings interface stays completed, with an unknown threat result. Consumers must check `SecurityScanOutcome.detections_available` before making a clean assessment or using the result as baseline evidence.
- Security and assistance task updates read and write within one database transaction. Terminal security states cannot regress under delayed polling. Cancelled prepared assistance tasks require fresh preparation; bound approval tokens are revoked. Running tasks stop at their implemented safe checkpoints.
- Confirmations expire even after confirmation but before consumption, bind a copied exact scope, and remain single use. Stand Down approvals bind the reviewed path, hash, size, and modification time. Stand Down suppresses eligible repeated recommendations while preserving provider facts.
- Current response plans collect a new analysis. Later detection snapshots take precedence over earlier scan-window records in both resolution and reactivation cases. Native Windows PowerShell JSON timestamps are supported.
- Application shutdown releases the scan monitoring worker without cancelling its provider-owned scan. The durable task remains recoverable, with its last observed provider state preserved. In-flight provider reads remain subject to their provider timeout; shutdown wakes an idle polling wait immediately.

## Reviewed baselines and case resolution

Baseline candidates retain their qualifying case and provider scan reference. Only verified full scans with fresh evidence, healthy sensor coverage, and successful analysis of every selected candidate can qualify. Candidate acceptance freezes the exact evidence revision and existing baseline identity, then rechecks current provider findings and reference drift. No scan silently installs a baseline. A provider adapter handle identifies the verified request; it is not necessarily the Windows event-log scan GUID.

Case resolution binds both reviewed case revisions. Its verification scan must have started after the latest open-case assessment; a later report timestamp alone is insufficient. Verification older than one day, incomplete candidate analysis, changed provider findings, or changed reference evidence blocks closure. Legacy records without scan provenance remain readable but cannot qualify as verification. Concurrent stale assessments remain in history without replacing newer or resolved state.

## Elevated Defender operations

Remediation rechecks the file hash, detection ID, Threat ID, and exact file resources inside the elevated process. Unknown or additional resources block the exact-file workflow. Scan cancellation rechecks the native scan ID, mode, and start time after elevation. Provider events, rather than command exit status alone, establish cancellation.

Defender's `Remove-MpThreat` acts on active threats, and `MpCmdRun -Scan -Cancel` acts on a provider scan. Neither exposes an atomic compare-identity-and-act operation for AIDA's requested scope. Revalidation minimizes the interval in which provider state can change; it cannot eliminate that interval. The displayed remediation plan identifies this broader provider operation. AIDA does not claim a provider-level atomic exact-file mutation or that an already-issued native action can be rolled back by cancelling its local task.

## Remote access and Sentry

- A generic support window is context. Account and address matches must occur within the same session, and a tool's presence does not establish who controls it. Unmatched concurrent activity cannot inherit a verified support classification.
- Remote session evidence includes the native WTS logon generation. Missing account, source, or generation data cannot authorize session termination. Native layout follows [Microsoft's WTSINFOW documentation](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ns-wtsapi32-wtsinfow).
- Sentry preparation uses unchanged targets from the confirmed assessment and displays each exact session and process before approval. Processes require executable path, parent ID, and exact creation time. A plan contains at most 32 targets.
- The persisted plan is atomically consumed with a two-minute validity window. A stale caller object, a substituted scope, another service instance, or a replay cannot obtain a second execution. Per-target action and verification outcomes are retained.
- Startup interruption reconciliation checks the execution owner's PID and process creation identity. It preserves live or uninspectable owners. Legacy unowned executing records receive a fifteen-minute grace period.
- Access denial is unknown evidence, never proof of absence. Failed final collection, changed identities, remaining sessions, or restarted targeted remote tools prevent a completed containment verdict. Newly discovered processes are reported for review rather than inheriting a previous process's authority.
- WTS logoff accepts a session number, not an atomic logon-generation condition. AIDA checks the generation immediately before the call, but Windows does not provide this workflow an atomic compare-and-logoff guarantee.
- The monitor tracks identities rather than only counts, resets ended activity episodes, and periodically reviews quiet periods for logon evidence. Stopping a worker does not discard its identity while it is still alive.

## Validation performed

Focused tests use fake providers, fake processes/sessions, and temporary databases/files. They cover scan attachment without launch, authorization requirements, completion with unavailable findings, delayed and concurrent ledger updates, cancellation, changing trust targets, native timestamp parsing, confirmation expiry and scope copying, persistent Sentry replay/expiry/concurrency, denied inspection, reused identities, restarted remote tools, session-specific support matching, and monitor episode handling.

The generated elevated and parent Defender scripts were parsed using the Windows PowerShell language parser. Parsing did not execute those scripts.

No live antivirus scans, elevation prompts, remediation, session logoffs, process termination, or cloud-provider calls were used for this validation. Controlled Windows integration testing remains necessary for Defender event timing, actual UAC behavior, WTS permissions and structure compatibility, provider restart behavior, and third-party security-product environments. These checks should use disposable test targets and an isolated Windows environment.

The autonomy engine remains conservative: Observation records decisions without executing operational proposals; learned scores do not create authority. Before adding autonomous scan execution, its policy evaluation and budget consumption must be a single execution reservation, with equivalent limits for targeted scans. The current separate proposal/budget APIs are not an execution authorization.
