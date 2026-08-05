# AIDA Artificer Engine

The Artificer Engine is AIDA's governed internal engineering, platform-concordance, and self-policing subsystem. It converts real operational behavior into durable evidence, identifies weaknesses in AIDA's own capabilities, recommends versioned improvements, and permits only narrowly defined, reversible internal maintenance.

## Current integration boundary

This branch provides the **Artificer backend foundation only**.

The canonical Early Alpha frontend remains unchanged from `agent/early-alpha-artificer-frontend`. Its Artificer button continues to open the existing read-only placeholder dialog. The backend is not constructed, started, scheduled, subscribed to the frontend, or connected to any button or status signal.

This separation is intentional while the Perception Engine is under parallel development. Future integration must explicitly construct the backend through `build_artificer_engine()` and define the shared event contract before any frontend or Perception Engine wiring is added.

A standalone backend probe is available without launching the frontend:

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
8. Importing or constructing the backend does not grant it frontend or operational authority.

## Runtime flow

AIDA subsystems will eventually publish structured `OperationalEvent` records to the shared `EventBus`. The `Watchtower` sanitizes and writes accepted events into the SQLite Artificer Ledger. The `Appraiser`, `Liaison`, and `Codewright` convert recurring operational patterns, platform capability probes, and deterministic source checks into `ArtificerFinding` records. The `Architect` can convert mature findings into `UpgradeProposal` records. The `Warden` independently evaluates every requested modification against protected paths and maintenance rules. The `Forge` performs only authorized, minimal, validated, atomic, and reversible changes.

On this branch, the backend can be exercised independently, but no production AIDA subsystem publishes into it yet.

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

Syntax repair requires owner approval even when the candidate compiles. Automatic maintenance is disabled by default and is not invoked by application startup on this branch.

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

Early Alpha defaults to `local_only`. Raw conversations, file contents, credentials, tokens, exact personal paths, email addresses, IP addresses, voice recordings, and precise location are not included in normal operational telemetry. Full diagnostic bundles require a separate explicit user submission.

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

Safe defaults are enabled backend availability, local-only telemetry, six-hour review interval, local exports, no remote endpoint, and automatic maintenance disabled.

## Frontend status

The canonical desktop currently includes:

- An `ARTIFICER` header button.
- An Artificer subsystem row in the status dashboard.
- A read-only Artificer Center placeholder.

Those controls are intentionally **not connected to this backend on this branch**. No changes were made to `aida/frontend/app.py`, `window.py`, `widgets.py`, the controller, command router, or button behavior while adding the backend.

Backend-to-frontend integration will occur only after the Perception Engine work is complete and a shared event and lifecycle contract is reviewed.

## Validation

The backend test package covers:

- Event-bus listener isolation.
- Ledger persistence and chain verification.
- Payload sanitization.
- Protected-path enforcement.
- Deterministic source findings.
- AST-equivalent Forge maintenance.
- Consent-gated dispatch.
- Platform profiling and report export.
- Proposal governance.
- Safe configuration defaults.
- User-data storage location.
- Explicit proof that frontend startup does not construct or start the backend.

Run validation with:

```powershell
python -m pytest -q
python -m compileall -q aida tests
python -m aida.artificer --export
```

## Known Early Alpha boundaries

- The Ledger hash chain verifies audit linkage and audit-record hashes. It is not a remote notarization service.
- AIDA does not yet include a hosted developer receiver API.
- Production diagnostics, autonomy, security, Perception Engine, speech, memory, and task telemetry are not yet attached to the Artificer Event Bus.
- The frontend is not yet driven by live Artificer snapshots.
- macOS on-demand provider scanning is not implemented.
- iOS and Android require separate native applications and platform-specific permission models.
- Major refactors, model changes, dependency replacements, permissions, and security-policy changes remain owner-approved work.
- Generated code is never deployed solely because a language model recommends it.
