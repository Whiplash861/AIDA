# AIDA Windows Security Lifecycle Field Test

## Scope

This checklist validates the five connected security-lifecycle features added for early alpha:

1. Provider-owned scan recovery after AIDA restarts.
2. Exact-confirmation, provider-confirmed scan cancellation.
3. Stand Down trust-exception lifecycle.
4. Detection reconciliation and local threat reporting.
5. Controlled Autonomy Observation mode.

These tests use Microsoft Defender as the antivirus provider. AIDA remains a local coordinator and reporter; Defender remains the source of scan and detection truth.

## Prerequisites

- Pull the current `agent/security-autonomy-memory-foundation` branch.
- Run `python -m compileall -q aida`.
- Run `python -m pytest -q` and resolve every failure before live testing.
- Confirm Microsoft Defender is active and signatures are current.
- Keep Autonomy at **Observation** or **Manual**. Do not enable autonomous Triage actions.
- Use only harmless test files. Do not download or execute real malware.

## Test 1 — Surface Scan restart recovery

1. Launch AIDA.
2. Run `start a surface security scan`.
3. Wait until the frontend reports one active task.
4. Close AIDA while Defender is still scanning.
5. Wait approximately one minute.
6. Relaunch AIDA.

Expected:

- AIDA identifies the matching provider-owned Quick Scan.
- AIDA does not start a second Defender scan.
- The task counter returns to one active task.
- The transcript identifies the provider Scan ID and original provider start time.
- Heartbeats display **Provider-total elapsed** and **AIDA monitoring-session elapsed** separately.
- Memory records the interruption, recovery count, reattachment, and final provider result.
- The scan reaches a provider-confirmed terminal state without duplicate durable tasks.
- When Defender reports no matching active scan, stale Quick/Full records close as **abandoned with unknown provider outcome**, not completed or cancelled.

Failure evidence to preserve:

- Screenshot of the startup transcript.
- Memory event IDs for the interruption and recovery.
- The corresponding row from the local `security_tasks` ledger.

## Test 2 — Surface Scan cancellation

1. Start another Surface Security Scan.
2. Enter `cancel the scan`.
3. Verify AIDA identifies the current provider Scan ID and asks for the exact phrase.
4. Enter `confirm scan cancellation` within two minutes.

Expected:

- AIDA sends Defender's native Quick/Full cancellation request.
- AIDA does not terminate the PowerShell monitoring process as a substitute for cancellation.
- Success appears only after Defender publishes its cancellation event.
- The durable task closes as `CANCELLED` only after provider confirmation.
- The Memory Bank records the requesting user, confirmation ID, provider Scan ID, request time, exit code, and result.
- When Defender completes before cancellation, AIDA reports the completion race and does not claim cancellation.
- When cancellation cannot be confirmed, monitoring remains active.

Repeat this test with a Full-System Sweep only after the Surface cancellation path passes.

## Test 3 — Stand Down lifecycle

Create a harmless local file, for example:

```powershell
Set-Content -Path "$env:TEMP\AIDA-stand-down-test.txt" -Value "AIDA harmless trust test"
```

Then:

1. Enter `stand down on "<full path>"`.
2. Verify the warning says **User-trusted; not verified safe** and explains that no Defender exclusion will be created.
3. Enter `confirm stand down`.
4. Enter `list stand down items`.
5. Explicitly Deep Scan that exact file.
6. Confirm the explicit scan overrides recommendation suppression for that assessment but does not silently revoke unchanged trust.
7. Change the file contents.
8. Reassess or list the item.

Expected:

- The record is bound to path, SHA-256, size, modification identity, user, device, reason, and expiry.
- Changing the file suspends the exception and restores normal recommendations.
- A new provider alarm also suspends the exception, even during an explicit scan.
- Creating a replacement exception supersedes the older active record.
- `revoke stand down for "<full path>"` asks for `confirm stand down revocation` and restores normal AIDA assessment after confirmation.
- Defender exclusions and allow-list settings remain unchanged throughout.

## Test 4 — Detection Intelligence

Use a recognized harmless antivirus test artifact only after the previous tests pass and only in accordance with the test artifact publisher's instructions. Do not execute the artifact.

Validate these states separately:

- A newly reported or reactivated provider detection inside the scan window.
- A pre-existing unresolved provider detection that remains active.
- A provider detection whose later record explicitly reports inactive state or successful provider action.
- A prior detection absent from a later history snapshot without any explicit provider resolution state.

Expected:

- AIDA separates **new/reactivated**, **pre-existing unresolved**, and **provider-confirmed resolved** findings.
- A scan with no new finding does not claim that an old unresolved threat was newly detected.
- AIDA creates `THREAT_NEUTRALIZED` only from explicit provider state or action evidence.
- A missing history record alone does not produce a neutralization claim.
- Threat reports distinguish provider observations from AIDA inference.
- Attribution defaults to unknown without provider-supplied evidence.
- Endpoint registration or region is never presented as an actor's physical location.
- Stand Down status is shown separately from the provider's factual detection.
- Memory creates `THREAT_DETECTED`, `THREAT_STILL_UNRESOLVED`, or `THREAT_NEUTRALIZED` events only when the corresponding evidence is available.

## Test 5 — Controlled Autonomy Observation mode

1. Enable Autonomy. Confirm the visible level is **Observation**.
2. Enter `observe security posture`.
3. Review the deterministic decision report.
4. Leave AIDA idle for at least fifteen minutes to permit one scheduled observation.
5. Repeat once with Manual Control enabled.

Expected:

- The explicit command reports provider health, real-time protection, signatures, active scan state, unresolved findings, and active Stand Down count when available.
- Observation records the action it considered and the governing policy version.
- Any operational response is routed to the user.
- No scan, quarantine, repair, termination, exclusion, or other system change is executed.
- A healthy scheduled observation remains silent but is recorded locally.
- A scheduled observation that identifies a condition needing attention may speak and surface the report, while still taking no operational action.
- Manual Control continues routing every operational proposal to the user.

## Completion criteria

The integrated lifecycle passes when:

- No duplicate provider scan is created during recovery.
- No cancellation is reported without a Defender cancellation event.
- Stand Down cannot survive identity change, new alarm, expiry, or confirmed revocation.
- Old unresolved detections are never mislabeled as new findings.
- Neutralization is never inferred from missing history alone.
- Observation mode records decisions but never executes an operational response.
- All resulting security evidence remains local-only and excluded from language-model context.
