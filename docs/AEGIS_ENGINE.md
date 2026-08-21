# AIDA Aegis Engine

Aegis is AIDA's background defensive-intelligence Engine. It amplifies AIDA's existing security capabilities by correlating antivirus-provider evidence with machine-specific baseline drift, volatile process state, persistence, network exposure, local file analysis, hypotheses, and durable Security Cases.

Aegis is intentionally not represented by a dedicated frontend button or status row. Existing Threat Center, Task Center, the normal transcript, and security commands remain the user-facing surfaces.

## Early Alpha role

Aegis may:

- Remain active as a low-cost read-only background observer.
- Read the active antivirus provider state and detection snapshot.
- Observe processes, process image paths, parent relationships, command-line metadata, remote endpoints, and listening endpoints.
- Observe bounded Windows startup and Run/RunOnce persistence locations.
- Compare current observations against an established local machine baseline.
- Build an evidence graph connecting files, processes, provider detections, persistence, and network endpoints.
- Generate competing malicious, benign, and unknown hypotheses.
- Track threat likelihood, potential impact, activity, persistence, exposure, urgency, and evidence coverage separately.
- Run an explicitly requested Intelligent Security Scan.
- Build durable local Security Cases.
- Recommend a targeted investigation or Full-System Sweep when evidence supports escalation.
- Emit privacy-minimized operational metadata to Artificer for reliability/performance review.

Aegis may not autonomously:

- Delete files.
- Quarantine or restore threats.
- Terminate processes.
- Create Defender exclusions or allow rules.
- Disable security controls.
- Change firewall policy.
- Start a Full-System Sweep.
- Perform provider remediation.

Existing authorization and Autonomy policy boundaries remain authoritative.

## Runtime lifecycle

The Command Registry is created during normal frontend startup. It obtains the hidden Aegis runtime through `ensure_aegis_engine()`. The runtime starts one daemon observation thread and is stopped through the registered process-exit cleanup.

Aegis does not repeatedly scan the computer in the background. Its normal loop performs bounded read-only snapshots at a configurable interval. Background observations do not start Defender scans.

Environment controls:

- `AIDA_AEGIS_ENABLED` — default `true`
- `AIDA_AEGIS_DATA_DIR` — optional local storage override
- `AIDA_AEGIS_OBSERVATION_INTERVAL_SECONDS` — default 900 seconds
- `AIDA_AEGIS_INITIAL_DELAY_SECONDS` — default 5 seconds

Default local storage is `%LOCALAPPDATA%\AIDA\aegis\aegis.db` on Windows.

## Intelligent Security Scan

An explicit phrase such as `run intelligent security scan` routes to `SECURITY_INTELLIGENT_SCAN`.

The scan preserves AIDA's proven security stack by composing two stages:

1. Run the existing Surface Security Scan using the existing provider adapter, scan continuity, detection reconciliation, Stand Down integration, and provider monitoring.
2. Run the Aegis adaptive correlation phase against the newly refreshed security state.

The Aegis phase:

1. Captures current provider health, processes, persistence, and network listeners.
2. Reads the current provider detection snapshot.
3. Compares current state to the local security baseline when one exists.
4. Selects a bounded set of security-relevant file candidates from provider detections, new persistence, and newly observed network-active or suspicious-path process images.
5. Uses the existing read-only `ThreatAnalysisService` for local file analysis.
6. Builds an evidence graph.
7. Calculates multi-axis risk and evidence coverage.
8. Generates competing hypotheses rather than searching only for evidence of compromise.
9. Creates a durable Security Case.
10. Recommends escalation when justified.

Aegis never claims an Intelligent Security Scan is identical to a Full-System Sweep. A Full Sweep remains the provider's exhaustive configured scan path.

## Machine baseline

Aegis does not continuously rewrite its baseline. This prevents newly introduced malicious persistence from becoming silently normalized.

The initial baseline may be established only after an explicitly requested Intelligent Security Scan when:

- no provider detections are present,
- overall risk is low,
- the provider is not known to be inactive or unhealthy,
- no sensor degradation is present.

Future baseline-refresh policy should remain explicit and reviewable.

## Evidence graph

Aegis correlates entities rather than treating every observation as an isolated alert. Current graph node categories include:

- file
- process
- provider detection
- persistence
- network endpoint

Current relationships include:

- `DETECTED_AS`
- `EXECUTES`
- `CONNECTED_TO`
- `PERSISTS_AS`

This foundation is intended to expand into future threat lineage and the reserved Sentry threat-hunting process.

## Reasoning model

Aegis separates:

- threat likelihood
- potential impact
- current activity
- persistence concern
- exposure concern
- urgency
- evidence coverage

This avoids collapsing different security questions into one score.

Aegis also records hypotheses with evidence for, evidence against, and unresolved questions. A valid signer, normal installation context, or lack of active provider evidence can count against a malicious hypothesis; weak indicators are not automatically promoted to proof.

Uncertainty is first-class output. Missing baseline data, unavailable provider state, inaccessible process/network data, failed local analysis, and other visibility gaps lower coverage and can themselves justify additional evidence collection.

## Artificer link

Aegis does not modify Artificer internals.

Artificer already reviews AIDA's configured source root, so `aida/aegis/` automatically enters normal Codewright source-health and compatibility reviews.

At runtime, `AegisArtificerBridge` publishes only privacy-minimized operational metadata to the already-active Artificer event bus. Examples include:

- Aegis state
- scan/observation duration
- case status
- provider detection count
- analyzed file count
- baseline-change count
- risk band
- coverage band
- escalation category
- sensor-error count

It does not send file paths, hashes, command lines, network endpoints, threat-case contents, or user conversation content.

This lets Artificer detect repeated Aegis failures, latency, and source-code problems without giving Artificer security execution authority or giving Aegis self-modification authority.

## Future Aegis expansion

Planned high-value additions include:

- broader persistence inventory: scheduled tasks, services, WMI subscriptions, Winlogon, PowerShell profiles, and additional persistence classes;
- Windows Security/Defender/PowerShell/Task Scheduler event timeline correlation;
- richer PE, script, archive, and Office static analysis;
- file-intelligence caching and NTFS change-journal acceleration;
- resource-aware investigation budgets;
- richer network exposure and process-lineage correlation;
- security-specific Perception analysis;
- local rule-based scanning;
- protected at-rest security intelligence storage;
- resumable read-only investigation tasks;
- Sentry, a future separately governed active threat-hunting process.

Sentry is reserved and is not implemented by this branch.
