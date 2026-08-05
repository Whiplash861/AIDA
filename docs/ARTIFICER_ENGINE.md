# AIDA Artificer Engine

The Artificer Engine is AIDA's governed internal engineering, platform-concordance, and self-policing subsystem. It converts real operational behavior into durable evidence, identifies weaknesses in AIDA's own capabilities, recommends versioned improvements, and permits only narrowly defined, reversible internal maintenance.

## Design principles

1. Evidence precedes recommendations.
2. Language-model reasoning is never authorization.
3. The component proposing a change does not approve the change.
4. Protected governance, consent, credential, recipient, and audit components are never autonomously modified.
5. Field telemetry is local-only by default.
6. Outbound data must pass consent, sanitization, recipient authorization, and encryption policy.
7. A change is not successful until post-change verification supports that conclusion.

## Runtime flow

AIDA subsystems publish structured `OperationalEvent` records to the shared `EventBus`. The `Watchtower` sanitizes and writes accepted events into the SQLite Artificer Ledger. The `Appraiser`, `Liaison`, and `Codewright` convert recurring operational patterns, platform capability probes, and deterministic source checks into `ArtificerFinding` records. The `Architect` can convert mature findings into `UpgradeProposal` records. The `Warden` independently evaluates every requested modification against protected paths and maintenance rules. The `Forge` performs only authorized, minimal, validated, atomic, and reversible changes.

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

## Authority model

### Observation

The Artificer may collect telemetry, inspect the configured AIDA source tree, profile the current OS, and create findings.

### Recommendation

The Artificer may create upgrade proposals with evidence, expected outcomes, risks, tests, compatibility requirements, and rollback procedures.

### Bounded maintenance

The Artificer may apply a change only when an explicit maintenance rule authorizes the exact path and file type, the evidence and confidence thresholds pass, implementation risk is within policy, a rollback asset exists, and all required validation succeeds.

The initial bounded rules cover:

- AST-equivalent Python formatting corrections.
- Approved generated-index rebuilding.
- Approved timezone-data refreshes.
- Future approved geofencing-data refreshes that do not change policy.

Syntax repair requires owner approval even when the candidate compiles.

### Protected governance

The policy, Warden, consent manager, sanitizer, developer registry, complete Ledger implementation, protected-path manifest, credential handling, and owner controls are approval-gated and cannot be autonomously modified.

## Platform concordance

The platform layer currently provides adapters for:

- Windows
- Linux
- macOS
- Unsupported or unverified platforms

Adapters expose capabilities rather than assuming every OS behaves the same. Security scans, settings navigation, file-manager navigation, permissions, shell availability, and provider status are resolved through the active adapter.

Windows uses Microsoft Defender and PowerShell when available. Linux supports ClamAV when `clamscan` is installed. macOS reports platform-protection presence but does not claim an on-demand security scan capability. Mobile platforms remain unsupported until a native runtime and permission model are designed.

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

## Frontend

The desktop frontend includes:

- An Artificer status row in the system dashboard.
- An `OPEN ARTIFICER` control.
- Overview, Findings, Compatibility, Proposals, and Privacy tabs.
- Evidence and reasoning summaries for each finding.
- Proposal creation and owner decisions.
- Telemetry consent controls.
- Removal of unsent field reports.
- Manual report export.
- Overlay notification pulses for findings, proposals, rollback, and errors.

Supported commands include:

- `artificer status`
- `run an artificer review`
- `show artificer findings`
- `show platform compatibility report`
- `export artificer report`
- `open artificer`
- `run a security scan`

The CLI uses the same command router, diagnostic executors, platform adapters, and Artificer instance as the desktop frontend. Its resource monitor runs independently of blocking console input.

## Early Alpha defaults

- Artificer enabled.
- Local-only telemetry.
- Automatic code maintenance disabled.
- Scheduled review every six hours.
- Startup review enabled in the CLI and queued shortly after desktop launch.
- Remote dispatch disabled unless an endpoint is configured.
- Owner record bootstrapped to Austin Jolly.

## Validation

The implementation includes tests for:

- Event-bus listener isolation.
- Ledger persistence and chain verification.
- Payload sanitization.
- Protected-path enforcement.
- Deterministic source findings.
- AST-equivalent Forge maintenance.
- Consent-gated dispatch.
- Platform profiling and report export.
- Proposal governance.
- Telemetry consent revocation.
- Artificer and security command routing.
- Normalized system-information collection.

Run validation with:

```bash
PYTHONPATH=. python -m pytest -q
python -m compileall -q aida utils tests
```

## Known Early Alpha boundaries

- The Ledger hash chain verifies audit linkage and audit-record hashes. It is not a remote notarization service.
- AIDA does not yet include a hosted developer receiver API.
- macOS on-demand provider scanning is not implemented.
- iOS and Android require separate native applications and platform-specific permission models.
- Major refactors, model changes, dependency replacements, permissions, and security-policy changes remain owner-approved work.
- Generated code is never deployed solely because a language model recommends it.
