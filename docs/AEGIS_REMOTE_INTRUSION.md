# Aegis Remote Intrusion Intelligence and Sentry Attack Protocol

## Purpose

Aegis Remote Intrusion Intelligence extends AIDA's defensive security model from malware/file analysis into active remote-access awareness. Its job is to distinguish ordinary remote activity, explicitly authorized support, anomalous support behavior, suspected unauthorized access, and user-confirmed active intrusion using correlated local evidence.

A remote connection, remote-support executable, public IP address, or Windows network logon is never treated as proof of an attacker by itself.

## Evidence sources

Phase 1 correlates:

- Windows Remote Desktop / Remote Desktop Services sessions through WTS APIs.
- Recent Windows Security logon events when the local account can read the Security log.
- Aegis process identity and parent/child relationships.
- Recognized remote-support/control process families.
- Remote-control tools spawning security-sensitive child processes such as PowerShell, cmd, schtasks, reg, script hosts, or related utilities.
- Current remote endpoints and listening endpoints already collected by Aegis.
- Defender/provider unresolved detections.
- Existing Aegis machine baseline drift, including new persistence and listeners.
- Endpoint-protection health.
- Aegis adaptive-learning anomaly and confidence state.
- Explicit, time-bounded user authorization for legitimate remote support.

Windows Security logon type 10 (RemoteInteractive/RDP) is stronger direct remote-session evidence than logon type 3 (Network), because network logons can occur during ordinary SMB/service activity. Failure to read the Security log lowers evidence coverage rather than being interpreted as a clean result.

## Authorized remote support

The user can create a temporary support context with ordinary language, for example:

```text
authorize Northstar support for two hours
```

or with a known tool fingerprint:

```text
authorize Northstar support using ScreenConnect for two hours
```

The authorization is local, time-bounded, revocable, and may optionally identify expected remote-control tooling. Future revisions may add expected support accounts and source-address fingerprints when those can be captured safely and reliably.

A support authorization is **not** a security whitelist. It does not:

- create a Defender exclusion;
- create an allow rule;
- change the firewall;
- suppress provider detections;
- permanently trust a remote-control tool;
- certify a technician or endpoint identity;
- become machine-learning ground truth.

Strong current security evidence can override support context. An authorized support window with an unresolved provider detection, suspicious persistence creation, disabled protection, or other high-concern evidence may be classified as `SUPPORT_SESSION_ANOMALOUS` rather than ordinary support.

A generic vendor label without an expected account, tool, or source is contextual evidence only. It deliberately receives less support-match confidence than a session whose observable characteristics match the authorization.

## Remote-access classifications

Aegis currently uses:

- `NO_REMOTE_ACTIVITY`
- `AUTHORIZED_SUPPORT`
- `SUPPORT_SESSION_ANOMALOUS`
- `REMOTE_ACCESS_OBSERVED`
- `UNAUTHORIZED_SUSPECTED`
- `LIKELY_INTRUSION`
- `CONFIRMED_INTRUSION`
- `DEGRADED`

`CONFIRMED_INTRUSION` has a deliberately narrow meaning in Phase 1: the local user explicitly confirms that currently observable remote access is unauthorized, and Aegis can still revalidate an active RDP session or recognized remote-control process target. A historical logon alone cannot arm Sentry.

## Background monitoring

Aegis runs a lightweight Remote Intrusion Monitor independently of the slower general Aegis observation interval.

Default interval: 30 seconds.

The monitor does not repeatedly run a heavyweight security scan. It first performs a cheap activity hint:

1. An active RDP session triggers a full Remote Intrusion Assessment.
2. A resident remote-support service by itself does **not** trigger repeated full assessments.
3. A recognized remote-control process spawning a security-sensitive child process triggers a full assessment.

This avoids treating legitimate persistent support software or relay connections as continuous attack activity.

## User emergency language

Phrases such as:

```text
somebody is in my computer
someone is remotely connected to my computer
check for unauthorized remote access
```

route locally to the Remote Intrusion Assessment rather than to a generic malware scan or cloud language-model decision.

This is read-only. Aegis observes and reports before active containment authority is considered.

## Confirming a genuine attacker

A separate user statement is required before Sentry can be armed, for example:

```text
that's not support, that's an attacker
```

Aegis immediately re-runs current remote-access evidence. If no active RDP session or recognized remote-control process target can be revalidated, Sentry is not armed.

If a current target is revalidated, Aegis creates a durable Sentry Attack Protocol plan and a fresh two-minute, exact-scope confirmation. The generated confirmation resembles:

```text
CONFIRM SENTRY ATTACK SENTRY-YYYYMMDD-HHMMSS-xxxxxxxx
```

The confirmation is bound to the plan's exact session/process target identities. Reusing a phrase for another plan or an expired plan is rejected.

## Sentry Attack Protocol — Phase 1

Sentry Phase 1 is active containment, not autonomous remediation.

After exact confirmation, Sentry may:

- revalidate and log off exact RDP sessions captured in the plan;
- revalidate recognized remote-control process targets using PID, name, executable path, process creation time, and parent relationship;
- terminate exact recognized remote-control processes;
- terminate exact security-sensitive children directly captured from recognized remote-control lineage;
- use graceful process termination first and an exact-revalidated hard termination fallback when needed;
- verify whether the targeted session/process identities remain active afterward.

Sentry blocks known critical Windows process names and AIDA's own process from this containment path.

Phase 1 deliberately does **not**:

- disable network adapters;
- create firewall deny rules;
- attribute a relay/server IP to a physical attacker;
- delete files;
- remove persistence;
- change Defender configuration;
- restore or allow threats;
- reboot or shut down the device.

Network isolation is reserved for a later independently governed design because third-party support tools frequently use shared relay infrastructure and blind adapter/firewall changes can disconnect the legitimate user, break AIDA's own visibility, or create a false sense that every foothold was removed.

## Post-containment verification

A successful Sentry result means only that the exact planned containment targets are no longer observable under the identities captured in the plan.

It does not mean the machine is certified clean.

After Sentry containment, the required security workflow is:

```text
Sentry containment
        ↓
Aegis Adaptive Security Scan
        ↓
process / persistence / network / provider correlation
        ↓
targeted investigation if needed
        ↓
Full-System Sweep if Aegis recommends escalation
```

Future Sentry phases can add broader threat-lineage hunting and separately governed network containment once those capabilities have their own exact identity, rollback, authorization, and verification semantics.

## Adaptive learning

Aegis feature schema version 2 adds privacy-preserving remote-control relationship features:

- remote-control process count;
- remote-control security-sensitive child count;
- hashed remote-tool identity pattern;
- hashed remote-tool → security-sensitive-child relationship pattern.

The learning model does not store raw remote endpoints, user paths, support-vendor labels, command lines, or Security Case contents.

A remote-support authorization is not automatically accepted as training truth. Normal Aegis poisoning-resistance gates remain authoritative.

## Artificer boundary

No Artificer implementation changes are required by this phase.

Aegis exposes privacy-safe engineering characteristics so Artificer can later compare these patterns against other Engines:

- remote-intrusion correlation;
- authorized-support disambiguation;
- exact-identity active containment;
- fresh scope-bound confirmations;
- post-containment verification;
- versioned feature-schema migration.

Runtime telemetry to Artificer may contain scalar states and counts such as remote-classification band, session count, tool count, support-context-present, or Sentry target count. It excludes support-vendor labels, accounts, source addresses, paths, hashes, command lines, and case evidence.
