# AIDA Security Lifecycle Field Validation

This checklist validates the Windows-specific behavior that cannot be proven by unit tests alone. Perform the tests on a harmless test system with Microsoft Defender active. Keep Controlled Autonomy at Observation level unless a step explicitly says otherwise.

## Safety boundaries

- AIDA does not delete, quarantine, restore, allow, or exclude files.
- Full-System Sweeps, scan cancellation, and Stand Down remain manual.
- Stand Down is AIDA-local and means **User-trusted; not verified safe**.
- Observation mode records proposals and policy decisions but executes no operational action.
- Defender event IDs are authoritative for provider scan state:
  - 1000: scan started
  - 1001: scan completed
  - 1002: scan cancelled before completion

## 1. Active Surface Scan restart recovery

1. Start a Surface Security Scan.
2. Confirm AIDA shows one active task and a Defender provider Scan ID.
3. Close AIDA while Defender continues scanning.
4. Wait approximately one minute.
5. Relaunch AIDA.

Expected:

- AIDA finds the same provider Scan ID.
- AIDA reports that local monitoring was recovered without starting another scan.
- Provider-total elapsed time preserves the original Defender start time.
- AIDA monitoring-session elapsed time restarts from the relaunch.
- Recovery count increments once.
- The task counter returns to one active task.
- Completion closes the original durable task rather than creating a duplicate.

Also test the two terminal restart cases:

- Let the scan complete while AIDA is closed. On restart, the ledger must close it as completed from event ID 1001.
- Cancel the scan outside AIDA while AIDA is closed. On restart, the ledger must close it as cancelled from event ID 1002.

AIDA must not report either outcome when the exact provider event cannot be confirmed.

## 2. Provider-confirmed cancellation

1. Start a Surface Security Scan.
2. Request cancellation.
3. Confirm the exact phrase: `confirm scan cancellation`.
4. Observe the result.

Expected:

- The confirmation is single-use, scope-bound, and expires after two minutes.
- AIDA calls Defender's native `MpCmdRun.exe -Scan -Cancel` path.
- AIDA reports cancellation only after Defender event ID 1002 is observed for the same Scan ID.
- Event ID 1001 is reported as completion, not cancellation.
- A timeout or event-log read failure leaves the task under monitoring and does not create a false success.
- Memory records requesting user, confirmation ID, provider Scan ID, request result, provider result, and timestamp.

Repeat with a Full-System Sweep only after Surface cancellation passes.

## 3. Stand Down lifecycle

Use a harmless local file created only for this test.

1. Request Stand Down for the exact file path.
2. Confirm the exact phrase: `confirm stand down`.
3. Verify the displayed state is **User-trusted; not verified safe**.
4. Confirm the active record contains path, SHA-256, size, modification identity, user, reason, and expiry.
5. Explicitly scan the file. The scan must override normal Stand Down suppression for that assessment.
6. Modify the file contents and evaluate it again.
7. Create a new provider alarm for the same file only with a harmless antivirus test artifact in a controlled test.
8. Revoke the Stand Down using its confirmation flow.

Expected:

- No Defender exclusion or Windows Security allow action is created.
- Unchanged identity suppresses repeated AIDA recommendations only.
- Explicit scan does not delete the record but bypasses suppression for that assessment.
- Hash, size, or modification identity change suspends the record.
- A new provider alarm suspends the record.
- Expiry and manual revocation restore normal AIDA recommendations.

## 4. Detection Intelligence and threat reporting

Use a recognized harmless antivirus test artifact only after the manual lifecycle tests pass.

Expected:

- AIDA captures a pre-scan and post-scan provider snapshot.
- New or reactivated detections are separated from existing unresolved detections.
- Existing unresolved findings are not reported as newly created by the current scan.
- Resolution is recorded only when the provider reports inactivity or successful action.
- Threat reports separate observed facts from inferred behavior.
- Actor attribution and physical location default to Unknown without explicit evidence.
- Network registration region is described as endpoint registration information, never actor location.
- AIDA takes no remediation action.

## 5. Controlled Autonomy — Observation mode

1. Enable Controlled Autonomy at Observation level.
2. Run `observe security` manually.
3. Allow one scheduled observation while AIDA is idle.
4. Repeat with a degraded test condition or unresolved harmless detection.

Expected:

- AIDA reads provider health, real-time protection, signature state, active scan state, active Stand Down count, and provider detections.
- It records observed evidence, action considered, policy version, disposition, authorization source, remaining risk, and follow-up.
- Read-only reporting is allowed.
- Quarantine, scan, repair, cancellation, and other operational proposals remain routed to the user.
- The Observation executor states that no provider mutation was requested.
- No scan or remediation begins automatically at Observation level.
- Disabling Autonomy immediately returns all operational decisions to Manual Control.

## Completion criteria

The five areas pass only when:

- all automated tests pass;
- no false completion or cancellation is reported;
- no duplicate durable scan record is created during recovery;
- no Defender exclusion or remediation action is created by Stand Down;
- no unsupported threat actor or location claim appears;
- Observation mode produces zero operational mutations;
- Memory contains the expected interruption, recovery, authorization, cancellation, Stand Down, detection, and decision events.
