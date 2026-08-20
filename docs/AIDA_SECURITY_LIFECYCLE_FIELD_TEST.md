# AIDA Windows Security Lifecycle Field Test

## Scope

This checklist validates five connected early-alpha security features:

1. Provider-owned scan recovery after AIDA restarts.
2. Exact-confirmation, provider-confirmed scan cancellation.
3. Stand Down trust-exception lifecycle.
4. Detection reconciliation and local threat reporting.
5. Controlled Autonomy Observation mode.

Microsoft Defender remains the source of truth. AIDA coordinates, records, and reports; she does not silently remediate.

## Prerequisites

- Pull `agent/security-autonomy-memory-foundation`.
- Run `python -m compileall -q aida`.
- Run `python -m pytest -q` and resolve every failure before live testing.
- Confirm Microsoft Defender is active and signatures are current.
- Keep Autonomy at **Observation** or **Manual**.
- Use harmless test files only. Never download or execute real malware.

Microsoft Defender event meanings used by AIDA:

- Event ID 1000: scan started.
- Event ID 1001: scan completed.
- Event ID 1002: scan cancelled before completion.

## Test 1 — Surface Scan restart recovery

1. Launch AIDA.
2. Run `start a surface security scan`.
3. Wait until the frontend reports one active task.
4. Close AIDA while Defender is still scanning.
5. Wait approximately one minute.
6. Relaunch AIDA.

Expected while the provider scan is still running:

- AIDA identifies the matching provider-owned Quick Scan.
- AIDA does not start a second Defender scan.
- The task counter returns to one active task.
- The transcript identifies the provider Scan ID and original provider start time.
- Heartbeats display **Provider-total elapsed** and **AIDA monitoring-session elapsed** separately.
- Recovery count increments once.
- Memory records the interruption and recovery.
- Completion closes the original durable task without creating a duplicate.

Also validate terminal outcomes while AIDA is closed:

- Let the scan complete before relaunch. AIDA must close the durable task as completed only after finding event ID 1001 for the exact Scan ID.
- Cancel the scan outside AIDA before relaunch. AIDA must close the task as cancelled only after finding event ID 1002 for the exact Scan ID.
- When no matching active or terminal event is available, AIDA records the provider outcome as unknown rather than inventing completion or cancellation.
- When the exact Scan ID still reports running but its mode cannot be adopted safely, AIDA preserves it as interrupted for later review rather than closing it.

Preserve a screenshot of the startup transcript and the corresponding Memory/ledger record for each case.

## Test 2 — Provider-confirmed cancellation

1. Start another Surface Security Scan.
2. Enter `cancel the scan`.
3. Verify AIDA identifies the current provider Scan ID.
4. Enter `confirm scan cancellation` within two minutes.

Expected:

- Confirmation is single-use, expiring, and bound to the exact Scan ID.
- AIDA requests Defender-native cancellation through `MpCmdRun.exe -Scan -Cancel`.
- Killing a local PowerShell host is never treated as scan cancellation.
- AIDA reports success only after Defender publishes event ID 1002 for the same Scan ID.
- Event ID 1001 is reported as completion, not cancellation.
- A transient event-log read failure does not create a false success.
- When cancellation cannot be confirmed, monitoring remains active.
- Memory records the requesting user, confirmation ID, provider Scan ID, request time, exit code, and provider result.

Repeat with a Full-System Sweep only after Surface cancellation passes.

## Test 3 — Stand Down lifecycle

Create a harmless local file:

```powershell
Set-Content -Path "$env:TEMP\AIDA-stand-down-test.txt" -Value "AIDA harmless trust test"
```

Then:

1. Enter `stand down on "<full path>"`.
2. Confirm the warning says **User-trusted; not verified safe** and that no Defender exclusion will be created.
3. Enter `confirm stand down`.
4. Enter `list stand down items`.
5. Explicitly Deep Scan that exact file.
6. Change the file contents and reassess it.
7. Revoke it with `revoke stand down for "<full path>"` and `confirm stand down revocation`.

Expected:

- The record is bound to path, SHA-256, size, modification identity, user, device, reason, and expiry.
- Normal unchanged evaluation suppresses repeated AIDA recommendations only.
- Explicit scan overrides suppression for that assessment without silently deleting unchanged trust.
- Hash, size, or modification identity change suspends the record.
- A new provider alarm suspends the record.
- Expiry and confirmed revocation restore normal recommendations.
- Defender exclusions and allow-list settings remain unchanged.

## Test 4 — Detection Intelligence

Use a recognized harmless antivirus test artifact only after Tests 1–3 pass and only according to the artifact publisher's instructions. Do not execute it.

Validate separately:

- A new or reactivated detection inside the scan window.
- A pre-existing unresolved detection that remains active.
- A provider detection explicitly marked inactive or with successful action.
- A prior detection absent from a later snapshot without explicit resolution evidence.

Expected:

- AIDA separates **new/reactivated**, **pre-existing unresolved**, and **provider-confirmed resolved** findings.
- Old unresolved findings are never mislabeled as newly created by the current scan.
- Missing history alone never creates a neutralization claim.
- Threat reports separate provider observations from AIDA inference.
- Actor and physical location default to Unknown without explicit evidence.
- Endpoint registration region is never presented as actor location.
- Stand Down state is shown separately from the provider's factual detection.
- AIDA creates the appropriate local detection event and takes no remediation action.

## Test 5 — Controlled Autonomy Observation mode

1. Enable Autonomy and confirm the visible level is **Observation**.
2. Enter `observe security posture`.
3. Review the deterministic decision report.
4. Leave AIDA idle for at least fifteen minutes for one scheduled observation.
5. Repeat once with Manual Control enabled.

Expected:

- AIDA reads provider health, real-time protection, signature state, active scan state, unresolved detections, and active Stand Down count when available.
- It records observed evidence, considered action, policy version, disposition, authorization source, remaining risk, and follow-up.
- Read-only reporting is allowed.
- Quarantine, scan, repair, cancellation, and other operational proposals remain routed to the user.
- The report says that no provider mutation was requested.
- No scan, quarantine, repair, termination, exclusion, or other system change occurs.
- A healthy scheduled observation may remain silent while still being recorded locally.
- A condition needing attention may be surfaced, while still taking no operational action.
- Manual Control continues routing every operational proposal to the user.

## Completion criteria

The integrated lifecycle passes when:

- no duplicate provider scan is created during recovery;
- no completion or cancellation is reported without the matching Defender event;
- Stand Down cannot survive identity change, new alarm, expiry, or confirmed revocation;
- existing unresolved detections are never mislabeled as new;
- neutralization is never inferred from missing history alone;
- threat attribution remains evidence-limited;
- Observation mode records decisions but executes zero operational mutations;
- resulting security evidence remains local-only and excluded from language-model context.
