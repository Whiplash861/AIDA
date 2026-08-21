# AIDA Aegis Engine

Aegis is AIDA's hidden background defensive-intelligence Engine and the architectural owner of AIDA security functions. Security providers such as Microsoft Defender remain authoritative specialist tools; Aegis supplies the machine-specific observation, correlation, reasoning, learning, case construction, scan orchestration, and governed escalation around them.

Aegis is intentionally not represented by a dedicated frontend button or status row. Existing Threat Center, Task Center, the normal transcript, and security commands remain the user-facing surfaces. AIDA's diagnostic Quickscan remains outside Aegis because it answers a system-health question rather than a security question.

## Security ownership model

All currently serviceable security scans now receive Aegis intelligence:

- **Adaptive Security Scan** — the default when the user asks for a security, malware, virus, or Aegis scan without prescribing depth. It begins with the economical Surface provider scan and then applies Aegis correlation and adaptive learning.
- **Surface Security Scan** — preserves the fast provider scan scope and adds Aegis correlation, baseline comparison, evidence graph, hypotheses, risk/coverage reasoning, and learned-behavior assessment.
- **Deep Security Scan** — preserves the explicit targeted provider scan scope and adds the same Aegis intelligence around the target and current machine evidence.
- **Full-System Sweep** — preserves exhaustive provider coverage and adds Aegis post-scan correlation. An Adaptive scan may recommend a Full-System Sweep but does not autonomously start one.

The existing provider scan stack, continuity/recovery, detection reconciliation, Stand Down semantics, and authorization rules remain the execution foundation underneath Aegis.

## Natural-language scan routing

Aegis security intent is semantic rather than dependent on one literal command string. Examples that route to Adaptive include:

- `run an intelligent security scan`
- `Aegis adaptive scan`
- `run a security scan`
- `check my computer for malware`
- `scan my PC for viruses`
- `check for threats`

Explicit mode language still wins. Surface, targeted/deep, and full/exhaustive wording resolve to the corresponding Aegis scan strategy. A bare ambiguous request such as `scan` can still trigger clarification. A conversational `Cancel` while a clarification is pending cancels the clarification rather than being reinterpreted as scan cancellation or Stand Down revocation.

## Early Alpha authority

Aegis may:

- remain active as a bounded read-only background observer;
- read provider state and unresolved detection evidence;
- observe process identities and parent relationships without collecting routine command-line contents;
- observe current network/listener relationships;
- observe bounded Windows startup and Run/RunOnce persistence;
- compare current observations against a local machine baseline;
- perform provider-authorized Surface, Deep, and Full scans through the existing governed scan stack when explicitly requested;
- run Adaptive Security Scans;
- use existing read-only Threat Analysis on bounded candidate files;
- build evidence graphs and competing hypotheses;
- calculate separate likelihood, impact, activity, persistence, exposure, urgency, and coverage measurements;
- use its local adaptive-learning model as bounded advisory evidence;
- create durable local Security Cases;
- recommend additional targeted investigation or Full-System Sweep escalation;
- expose privacy-minimized engineering metadata to Artificer.

Aegis may not autonomously:

- delete files;
- quarantine or restore threats;
- terminate arbitrary processes;
- create Defender exclusions or allow rules;
- disable or weaken security controls;
- change firewall policy;
- perform provider remediation;
- turn a learned anomaly directly into destructive action;
- override current provider evidence, current identity, authorization, or security policy.

Machine learning increases intelligence, not authority.

## Runtime lifecycle

The Command Registry obtains one hidden Aegis runtime through `ensure_aegis_engine()`. The Engine starts one daemon observation thread and is stopped by process-exit cleanup.

Aegis does not repeatedly run antivirus scans in the background. Its normal loop captures bounded read-only security snapshots at a configurable interval. Background observations never start Defender scans.

Environment controls:

- `AIDA_AEGIS_ENABLED` — default `true`
- `AIDA_AEGIS_DATA_DIR` — optional local storage override
- `AIDA_AEGIS_OBSERVATION_INTERVAL_SECONDS` — default `900`
- `AIDA_AEGIS_INITIAL_DELAY_SECONDS` — default `5`
- `AIDA_AEGIS_LEARNING_MINIMUM_SAMPLES` — default `8`; minimum `3`

Default Windows storage is under `%LOCALAPPDATA%\AIDA\aegis\` and currently includes the Aegis SQLite database plus `learning-model.json`.

## Adaptive-learning foundation

Aegis Phase 1 learning is intentionally local, incremental, explainable, and dependency-light. It does not use a cloud model or give the language model security execution authority.

The active learning model maintains online statistics and novelty history for privacy-preserving machine-security features. Current numeric features include process count, persistence count, listeners, remote-activity count, parent/child relationship count, security-relevant baseline deltas, provider-detection count, local-analysis count, suspicious-analysis count, and sensor-error count.

Aegis also learns hashed identity and relationship tokens for patterns such as:

- process identities;
- persistence identities;
- listener identities;
- parent/child process relationships;
- whether a particular process identity normally exhibits remote activity;
- whether a particular process identity normally exposes a listener.

Raw paths, raw network endpoints, command-line contents, and Security Case text are not written into the learning model. Identity patterns are one-way SHA-256-derived tokens used only for local novelty comparison.

### Warmup and confidence

The model begins in a warmup state. While trusted-sample count is below the configured minimum, learned anomaly output is not allowed to influence security risk. Model confidence rises with accumulated trusted samples and remains separate from threat likelihood.

This distinction is deliberate: **model confidence is confidence in the learned baseline, not probability that an object is malicious.**

### Poisoning-resistant training gate

Repeated observation is not automatically treated as normal or trusted. Aegis trains only when deterministic evidence first makes the sample eligible.

Current scan-training requirements include:

- a machine security baseline exists or was safely established by the current clean assessment;
- no unresolved provider detection is present;
- deterministic overall risk remains low;
- no sensor degradation is present;
- no local Threat Analysis result is Suspicious, Likely Malicious, or Provider-Confirmed Malicious;
- after model warmup, the current learned anomaly itself must remain below the training threshold.

Background learning is stricter about drift and requires an existing machine baseline, no active provider finding, no degraded visibility, and only small baseline changes.

This prevents the rule `frequent = trusted` and makes it harder for persistent malicious behavior to train itself into the baseline.

### Learned evidence boundary

Learned anomaly is deliberately capped as advisory evidence. Even a mature high anomaly can raise investigation priority, add a learned-anomaly hypothesis, or elevate observation state, but it cannot by itself:

- create provider-confirmed malicious status;
- grant remediation authority;
- override a valid current provider state;
- override Stand Down identity rules;
- override security policy or authorization.

The deterministic and provider-evidence layers remain authoritative.

## Evidence graph and hypotheses

Aegis correlates entities rather than treating observations as isolated alerts. Current graph categories include files, processes, provider detections, persistence, and network endpoints. Current relationships include detection, execution, connection, and persistence relationships.

The learning layer complements this graph by learning privacy-preserving relationship novelty. An unusual parent/child pairing can therefore raise investigation priority even when both individual process identities have been seen previously.

Aegis continues to form competing hypotheses with supporting evidence, counter-evidence, and unresolved questions. Learned anomaly adds a hypothesis such as `Behavior deviates from Aegis learned machine baseline`; the hypothesis explicitly records that anomaly is not proof of malware.

## Machine baseline versus learned baseline

Aegis deliberately maintains two related but different concepts:

1. **Machine security baseline** — an explicit durable snapshot used for deterministic drift comparison. It is not continuously rewritten.
2. **Learned behavior baseline** — aggregate statistics and hashed pattern frequency learned only through the governed training gate.

The first clean Adaptive assessment may establish the machine baseline when provider state, deterministic risk, and visibility meet the existing safety requirements. The learning layer can then begin collecting trusted observations. Future baseline replacement policy remains explicit and reviewable rather than automatic normalization.

## Artificer engineering thread

Aegis does not modify Artificer implementation files.

Artificer already reviews AIDA's configured source tree, so the complete `aida/aegis/` learning implementation automatically enters Codewright review. Aegis additionally exposes an `engineering_manifest()` describing its reusable engineering patterns and model-health contract.

Current manifest patterns include:

- deterministic + learned hybrid reasoning;
- evidence graphs;
- competing hypotheses;
- multi-axis risk and coverage;
- adaptive scan orchestration;
- privacy-preserving feature learning;
- poisoning-resistant training gates;
- versioned model lifecycle contracts;
- shadow-model-ready architecture;
- rollback-ready model contracts.

The manifest explicitly assigns cross-Engine comparison/recommendation ownership to **Artificer**. Aegis does not decide that another Engine should adopt ML or any Aegis pattern. It exposes the architecture and measurements; Artificer may later compare those patterns with other Engines and recommend reuse when appropriate.

Runtime bridge events remain privacy minimized. Artificer may receive scalar engineering data such as model version, model stage, trusted sample count, ready/warmup state, anomaly/confidence bands, scan strategy, capability count, and shadow/rollback support. The bridge does not send raw paths, file hashes, network endpoints, command lines, learning feature tokens, Security Case contents, or user conversation content.

## Model evolution contract

Phase 1 uses one active local online model, but the model contract already includes explicit version, lifecycle stage, shadow-model support, and rollback support metadata. This intentionally prepares later work for:

- candidate models;
- shadow evaluation against the active model;
- decision-divergence measurement;
- precision/false-positive/calibration evaluation;
- promoted/retired model states;
- safe rollback after regression.

A later model should not replace the active model merely because it is newer.

## Future Aegis expansion

High-value additions still planned include:

- broader persistence inventory: scheduled tasks, services/drivers, WMI subscriptions, Winlogon, PowerShell profiles, and additional persistence classes;
- Windows Security/Defender/PowerShell/Task Scheduler event timeline correlation;
- richer PE, script, archive, and Office static analysis;
- file-intelligence caching and NTFS change-journal acceleration;
- resource-aware investigation budgets;
- richer process lineage and graph learning;
- calibrated historical outcome learning;
- candidate/shadow model evaluation and promotion;
- security-specific Perception analysis;
- local rule-based scanning;
- protected at-rest security intelligence storage;
- resumable read-only investigations;
- Sentry, a future separately governed active threat-hunting process.

Sentry is reserved and is not implemented by this branch.
