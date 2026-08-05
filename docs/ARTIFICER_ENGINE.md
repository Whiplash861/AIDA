# AIDA Artificer Engine

The Artificer Engine is AIDA's governed internal engineering, platform-concordance, and self-policing subsystem. It converts real operational behavior into durable evidence, identifies weaknesses in AIDA's own capabilities, recommends versioned improvements, and permits only narrowly defined, reversible internal maintenance.

## Current integration state

The Artificer backend and the Perception/voice foundation are now integrated on `agent/artificer-perception-integration`.

At application startup AIDA explicitly:

1. Builds one `ArtificerEngine` instance.
2. Registers it as the active runtime instance.
3. Captures the current platform profile.
4. Starts the local Ledger, Watchtower, Liaison, and review scheduler.
5. Connects live snapshots to the canonical Artificer status row and Artificer Center.
6. Schedules the first source/platform/telemetry review outside the UI thread.
7. Connects privacy-minimized Perception, voice, task, and Autonomy events.
8. Stops the scheduler, disconnects listeners, and clears the active instance during shutdown.

The canonical frontend remains intact. Report Bug, Memory, Threats, Tasks, Autonomy, Perception, Microphone, the transcript, Recent Activity, and the command interface retain their existing roles.

A standalone backend probe remains available:

```powershell
python -m aida.artificer
python -m aida.artificer --export
python -m aida.artificer --no-review
```

## Design principles

1. Evidence precedes recommendations.
2. Language-model reasoning is never authorization.
3. The component proposing a change does not approve the change.
4. Protected governance, consent, credential, recipient, and audit components are never autonomously modified.
5. Field telemetry is local-only by default.
6. Outbound data must pass consent, sanitization, recipient authorization, and encryption policy.
7. A change is not successful until post-change verification supports that conclusion.
8. A frontend control never grants additional Artificer authority.
9. Perception evidence and voice interaction are observed without storing their private contents in normal telemetry.

## Runtime flow

AIDA subsystems publish structured `OperationalEvent` records to the shared `EventBus`. The `Watchtower` sanitizes and writes accepted events into the SQLite Artificer Ledger. The `Appraiser`, `Liaison`, and `Codewright` convert recurring operational patterns, platform capability probes, and deterministic source checks into `ArtificerFinding` records. The `Architect` can convert mature findings into `UpgradeProposal` records. The `Warden` independently evaluates every requested modification against protected paths and maintenance rules. The `Forge` performs only authorized, minimal, validated, atomic, and reversible changes.

The current production bridge records:

- Perception evidence attachment outcomes.
- Evidence kind and source.
- Media type, byte size, confidence, and evidence-field counts.
- Voice lifecycle state and elapsed duration.
- Voice transcript character and word counts.
- Voice error category without raw error text.
- Background task start, duration, completion, and failure.
- Autonomy enabled/disabled state.

The bridge does not record image bytes, extracted image content, personal file paths, SHA-256 values, voice recordings, transcript text, raw task error messages, or user conversation content.

## Major components

- **Watchtower** — collects internal operational evidence.
- **Ledger** — stores events, profiles, findings, proposals, decisions, modifications, validation results, rollback events, consent history, and dispatch state.
- **Liaison** — profiles the host OS, runtime, dependencies, permissions, security provider, timezone, and verified capabilities.
- **Codewright** — performs deterministic source inspection inside AIDA's configured source root.
- **Appraiser** — correlates repeated failures, latency, and routing fallback patterns.
- **Architect** — creates reviewable versioned upgrade proposals.
- **Warden** — enforces authority boundaries and protected paths.
- **Forge** — creates backups, validates candidate changes, writes atomically, and supports rollback.
- **Developer Registry** — restricts who may receive reports and decide proposals.
- **Dispatch** — queues sanitized local exports or encrypted HTTPS reports.
- **Platform adapters** — normalize Windows, Linux, macOS, and unsupported-platform behavior.
- **Operational Bridge** — translates live frontend, Perception, voice, task, and Autonomy state into privacy-minimized events.
- **Qt Bridge** — safely moves Artificer snapshots from worker threads onto the frontend thread.

## Authority model

### Observation

The Artificer may collect explicitly supplied telemetry, inspect the configured AIDA source tree, profile the current OS, and create findings.

### Recommendation

The Artificer may create upgrade proposals with evidence, expected outcomes, risks, tests, compatibility requirements, and rollback procedures.

### Bounded maintenance

The Artificer may apply a change only when an explicit maintenance rule authorizes the exact path and file type, evidence and confidence thresholds pass, implementation risk is within policy, a rollback asset exists, and all required validation succeeds.

The initial bounded rules cover:

- AST-equivalent Python formatting corrections.
- Approved generated-index rebuilding.
- Approved timezone-data refreshes.
- Future approved geofencing-data refreshes that do not change policy.

Syntax repair requires owner approval even when the candidate compiles. Automatic maintenance is disabled by default and is not invoked by application startup.

### Protected governance

The policy, Warden, consent manager, sanitizer, developer registry, complete Ledger implementation, protected-path manifest, credential handling, and owner controls are approval-gated and cannot be autonomously modified.

## Platform concordance

The platform layer currently provides adapters for:

- Windows
- Linux
- macOS
- Unsupported or unverified platforms

Adapters expose capabilities rather than assuming every OS behaves the same. Security-provider status, settings navigation, file-manager navigation, permissions, shell availability, and capability probes are resolved through the active adapter.

Windows uses Microsoft Defender and PowerShell when available. Linux supports ClamAV when `clamscan` is installed. macOS reports platform-protection presence but does not claim an unsupported on-demand security scan. Mobile platforms remain unsupported until a native runtime and permission model are designed.

## Telemetry and privacy

Telemetry levels are:

- `local_only`
- `anonymous`
- `pseudonymous`
- `full_diagnostic`

Early Alpha defaults to `local_only`. Raw conversations, file contents, credentials, tokens, exact personal paths, email addresses, IP addresses, voice recordings, transcript text, and precise location are not included in normal operational telemetry. Full diagnostic bundles require a separate explicit user submission.

Remote dispatch requires:

1. A non-local telemetry level.
2. Consent for the report category.
3. An active authorized developer recipient.
4. Sanitization success.
5. A recipient public encryption key.
6. A configured HTTPS receiver endpoint.

Without a receiver service, reports remain local or export to the configured Artificer export directory.

## Storage and configuration

Artificer state is stored under AIDA's user-data root rather than inside the repository:

```text
%LOCALAPPDATA%\AIDA\artificer\
```

The directory contains the Ledger, consent state, developer registry, rollback assets, and local exports. Relevant environment controls include:

- `AIDA_ARTIFICER_ENABLED`
- `AIDA_ARTIFICER_MODE`
- `AIDA_ARTIFICER_REVIEW_INTERVAL_SECONDS`
- `AIDA_ARTIFICER_TELEMETRY_LEVEL`
- `AIDA_ARTIFICER_LOCAL_EXPORT_ENABLED`
- `AIDA_ARTIFICER_DISPATCH_ENDPOINT`
- `AIDA_ARTIFICER_AUTO_MAINTENANCE_ENABLED`

Safe defaults are enabled engine availability, local-only telemetry, a six-hour review interval, local exports, no remote endpoint, and automatic maintenance disabled.

## Frontend

The canonical desktop now provides a live Artificer Center with:

- Overview of state, platform, review time, findings, proposals, queue depth, and telemetry level.
- Evidence-backed Findings display.
- Platform Compatibility display.
- Pending Proposals display.
- Governance and privacy boundaries.
- Background `Run Review` control.
- Local `Export Report` control.

The Artificer status row is driven by real engine snapshots. Reviews and exports run through AIDA's shared `TaskManager` rather than blocking the Qt event loop.

The current interface does not expose autonomous deployment or maintenance controls. Proposal existence is not treated as approval.

## Validation

The combined test suite covers:

- Event-bus listener isolation.
- Ledger persistence and chain verification.
- Payload sanitization.
- Protected-path enforcement.
- Deterministic source findings.
- AST-equivalent Forge maintenance.
- Consent-gated dispatch.
- Platform profiling and report export.
- Proposal governance.
- Safe configuration defaults and user-data storage.
- Explicit engine startup and shutdown lifecycle.
- Canonical frontend preservation.
- Live Artificer review and export controls.
- Perception telemetry privacy.
- Voice transcript-content exclusion.
- Background-task duration tracking.
- Prevention of false completion events after task failure.

Run validation with:

```powershell
python -m pytest -q
python -m compileall -q aida tests
python -m aida.artificer --export
python -m aida.frontend
```

## Known Early Alpha boundaries

- The Ledger hash chain verifies audit linkage and audit-record hashes. It is not a remote notarization service.
- AIDA does not yet include a hosted developer receiver API.
- Production security, diagnostic, memory, command-routing, brain, and speech-output telemetry are not yet comprehensively instrumented.
- Perception Phase 1 records image evidence metadata but does not yet perform complete visual interpretation.
- Voice transcription depends on the separately configured transcription provider.
- macOS on-demand provider scanning is not implemented.
- iOS and Android require separate native applications and platform-specific permission models.
- Major refactors, model changes, dependency replacements, permissions, and security-policy changes remain owner-approved work.
- Generated code is never deployed solely because a language model recommends it.
