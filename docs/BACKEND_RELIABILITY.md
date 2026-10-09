# Backend reliability and evidence boundaries

This document describes the local backend changes made in the October 2026 reliability pass. Specialist Engines remain separate: Artificer governs AIDA maintenance, Technomancer observes the host, Aegis assesses security, Memory stores scoped evidence, and execution remains subject to its owning authorization boundary. These changes do not establish production readiness, calibrated prediction, a successful live repair, or a hardware purchasing requirement.

## Memory

- Revision reads, conflict checking, numbering, and updates run in one SQLite transaction. `revise_memory(..., category=..., expected_updated_at=...)` supports stale-editor rejection through `MemoryConflictError`.
- A user correction to a summary with existing facts preserves those facts and the previous revision. The current record becomes `DISPUTED` until replacement facts reconcile it. Replacement facts mark it `USER_CORRECTED`. Plain-language correction is not automatic factual verification.
- `retrieve_context(query, limit=8)` excludes disputed, stale, revoked, deleted, superseded, and expired records. Management views retain access to revision history. Retrieval is user/device scoped.
- Operational event promotion records its source event and labels causal success unverified. Reported success is not proof that a repair caused an improvement.
- Explicit purge removes the selected memory, revisions, linked source events when not shared, and copied management records. SQLite secure deletion is enabled; this is not a guarantee of erasure from operating-system, OneDrive, or external backups.
- Schema version 2 adds source-event links through an additive migration and rejects newer schemas. Connections close after use.
- The event journal defaults to 10,000 events and 90 days per user/device. Constructor options `journal_limit` and `journal_retention_days` configure bounded limits. Expiring a journal event preserves saved memory facts and revisions. Saved memories are not silently aged away.
- A 256 MiB SQLite page budget stops growth rather than deleting saved memories or security/governance records. Existing databases larger than the budget are not truncated. WAL files, backups, and filesystem overhead are separate from this page budget.

## Artificer

Disabled engines do not ingest operational events. Persisted consent survives configuration defaults. Consent and developer state use atomic, process-locked JSON updates; dispatch reloads consent and recipient identity immediately before sending. Revoked consent, changed consent revision, removed recipients, and rotated recipient keys block stale queued payloads. HTTPS transport requires encryption and validated HTTPS endpoints. Anonymous summaries contain aggregate fields rather than unrestricted diagnostic prose.

The ledger serializes complete updates across connections, verifies payload hashes and current row snapshots, records proposal decisions, and detects modifications to audited records. Migration establishes an explicit checkpoint; it cannot retroactively prove historical data. Findings resolve when their scoped evidence disappears and reopen when it returns. Source inventory includes AIDA's Memory implementation while pruning dependencies, environment files, and generated trees before walking them. Capability declarations remain unverified until evidence exists. Operational findings group the same operation and use a recent evidence window.

Retention defaults are 5,000 operational events, 64 platform snapshots, and 2,000 capability observations. When these bounds or 20,000 excess audit entries are reached, older observations are pruned and the already-verified current records are checkpointed. The new audit anchor records the retired chain tip and counts, and `retention_status()` explicitly reports `history_complete=False`. This verifies retained current state and subsequent history; it does not claim the discarded historical chain remains available. Governance, modification, validation, and rollback records are preserved. A 256 MiB database page ceiling fails closed when preserved records fill the budget. Local hashes are integrity checks, not signatures against an actor who can rewrite the whole database.

### Forge maintenance

- Canonical target authorization and protected-path checks run before target content is read or backed up.
- Scores must be finite and within policy bounds. A caller's `owner_approved=True` flag does not authorize an operation. `Warden.issue_approval` requires an injected trusted approval authorizer; a short-lived, one-use token binds the exact path, rule, original digest, and proposed digest.
- Candidate validation runs in a temporary copy of the source tree. Python syntax/AST or supported data-format checks run there; behavioral and data changes require selected tests against the candidate tree.
- Source digests are checked after validation, while preparing the backup, and immediately before atomic replacement. A durable prepared record precedes replacement. Failure restores original bytes only when the current bytes still match the attempted candidate.
- Rollback requires the exact applied ledger record, original backup digest, matching current candidate digest, and fresh scoped approval when the rule requires it. It writes rollback preparation and outcome records.
- `inspect_pending_recovery()` reports interrupted operations. Further application to a path with a pending operation is blocked for review. Recovery is not automatic and a filesystem replacement cannot share an atomic transaction with SQLite.

Candidate tests are subprocesses, not an operating-system sandbox. Production owner-approval UI integration, isolated test execution for hostile code, rule-specific data semantics, and end-to-end live maintenance validation remain separate work. No live source application or rollback was performed as part of this change.

## Technomancer

Monitoring data lives in the local user-data area rather than the source checkout. Legacy database migration copies through SQLite backup and retains the original; it does not transfer background-monitoring consent. Monitoring permissions persist atomically. Runtime identity includes PID, process creation time, executable, and module/data-directory arguments; stale or unrelated processes are not terminated by PID alone. Runtime health records failed cycles and the last successful observation.

Hardware changes start a new evidence epoch and retire stale advisories. Future or non-finite observations are rejected. Observation maturity uses actual hour/day coverage, not elapsed time since the first sample. Raw samples default to 30-day retention; complete older days compact into weighted summaries, retaining coverage. Daily summaries default to 730 days, and event/outcome tables retain at most 10,000 rows. The database has a 256 MiB page ceiling. A record-count limit and a page budget do not constitute measured runtime or disk benchmarks.

Inventory, storage, and reliability queries are cached at different intervals; hardware inventory is gathered in one structured PowerShell request. Missing metrics remain unknown. Multiple devices contribute worst observed readings instead of assuming the first device represents the machine. Advisory severity ordering, first-seen timestamps, dismissal of absent conditions, and resurfacing cooldowns are explicit. Self-reported outcome feedback is retained but does not increase causal confidence. User aptitude combines observations with age decay; it is not a calibrated proficiency test.

Sustained utilization supports investigation. It does not by itself establish unresponsiveness, active paging, a faulty component, or the correct replacement hardware. Purchase suggestions remain hypotheses requiring workload evidence and compatibility checks. Wi-Fi thresholds and heuristic confidence scores are not learned or experimentally calibrated.

## Aegis learning persistence

`AegisLearningStore(path, history_limit=16)` stores a versioned envelope, bounded to 2–64 model snapshots. Compatible legacy schema-2 model files migrate on the next successful write. Incompatible or corrupt state raises `LearningStoreError` and remains untouched; callers must show learning as unavailable rather than silently reset the baseline. Numeric values must be finite; identity features must be bounded hashed tokens. Hashing reduces raw identity exposure but does not provide encryption or prevent dictionary guesses.

`AegisLearningService.learn_if_safe(features, eligible=True)` additionally requires explicit zero detection, suspicious-analysis, and sensor-error counts. Accepted training reloads and updates under a cross-process lock. An unsuccessful write does not update the service's cached model. `store.save(model, expected_version=...)` rejects stale writers with `LearningConflictError`. Assessment and snapshots reload the active persisted model; session acceptance/rejection counts are labelled as session metrics.

Version and recovery APIs:

- `store.history()` lists retained version metadata; `store.load_version(version)` loads a retained snapshot.
- `service.rollback(version, expected_active_version=current, reason=...)` restores a retained active model as a new monotonic version. Rollback survives restart and does not overwrite the historical version.
- `service.stage_shadow(candidate, expected_active_version=current, reason=...)` persists a shadow without activating it. `assess_shadow(version, features)` assesses it independently.
- `service.evaluate_shadow(version, samples, expected_active_version=current)` accepts independently labelled holdout pairs `(AegisFeatureVector, anomalous_bool)`, 20–10,000 total and at least ten of each label. Only dataset digests and aggregate metrics are retained. The decision threshold is 0.5; promotion gates require candidate false-positive rate <= 10%, recall >= 80%, and no more than five percentage points of degradation versus the active model on that same set.
- `service.promote_shadow(version, expected_active_version=current, evidence=recorded_evaluation, reviewed_by=..., reason=...)` requires the persisted passing evaluation, matching model digests, unchanged active version, and a reviewer/reason. A supplied `passed=True` dictionary cannot substitute for evaluation. Promotion is never automatic.
- `store.recover_previous(expected_file_digest=sha256_of_current_bytes, reason=...)` explicitly recovers the previous valid envelope, first retaining the unreadable current file as a content-addressed `.corrupt-*` artifact. Recovery fails if the current file changed. These explicit recovery artifacts require operator retention review; they are not automatically deleted.

These APIs do not prove that submitted labels are correct or independent of training. Small or unrepresentative holdout sets cannot establish real-world false-positive rates. Confidence measures sample support and is separate from anomaly score; neither is a calibrated malware probability. The store keeps only a bounded history, so rollback to an evicted version is unavailable. JSON snapshot history and its previous envelope incur bounded write amplification; production performance still requires measurement. Offline evaluation/approval interfaces are backend APIs; a dedicated model-management UI is not part of this pass.

## Observation lifecycle and autonomy settings

`ObservationRuntime.apply(settings)` records the desired observation state and may construct an Engine following explicit enablement. `reconcile()` only operates an existing Engine: it retries starts after a preceding observer finishes stopping, and never retries failed initialization. Disabling the parent Aegis Engine also stops its remote monitor. Consent revocation and shutdown can update the desired state while construction is pending, so a late constructor result cannot start observers after permission was withdrawn. Stop requests are immediate; an already-running provider read still exits cooperatively.

Autonomy settings are persisted before becoming current or notifying listeners. Failed writes preserve the previous committed settings for enable, disable, kill, and release. Lifecycle callbacks execute outside the settings lock, allowing a concurrent revocation during initialization. A settings write that succeeds is not undone if subsequent event logging fails. Technomancer's separate process accepts only actual Boolean consent flags; a present authority level must permit observation. Existing runtime permission checks continue to reread persisted consent between observation cycles.

The lifecycle regression suite uses mocked observers and temporary databases. It covers rapid disable/re-enable, pending constructor revocation/close, disabled-parent remote suppression, initialization-failure retry limits, shutdown failure isolation, persisted callback ordering, and storage-failure rollback. No host observation threads are started by these tests.

## Diagnostics, navigation, applications, and support

Legacy direct antivirus execution delegates to the canonical security executor with explicit authorization and bounded monitoring. Platform adapters no longer duplicate scan execution. Unavailable findings are not translated into a clean scan. CLI provider scans require explicit confirmation, passive CLI resource checks default off and can be enabled for that session, and resource pressure no longer triggers unsupported system-file repair advice. AppData placement and high GPU utilization alone are informational context. Failed metric sensors produce partial results instead of fabricated zeros.

Navigation checks hashes and metadata consistently, honors caller budgets, checks deadlines while hashing, and notices changed files during reads. macOS uses the system `open` command. Process status does not prove GUI responsiveness; absent responsiveness sensors report unknown. Unsupported application repair plans are manual guidance, and potential unsaved-work loss is explicit. Bug-report log reads are bounded, local writes are atomic, and outbox transitions serialize across instances. Bug-report drafting remains a local review workflow and does not claim confirmed delivery.

## Validation

The subsequent source-review increment adds exact code annotations, stale-source guards, inert candidate exports, and bounded local resource observations. Its workflow, schema-3 migration, validation limits, and APIs are documented in [ARTIFICER_SOURCE_REVIEW.md](ARTIFICER_SOURCE_REVIEW.md). Candidate staging does not enable live Forge application or establish behavioral correctness.

Focused tests use temporary files/databases and mocked providers, process identities, and transports. Run from the repository root:

```powershell
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests/artificer tests/test_memory_foundation.py test_technomancer_engine.py tests/test_technomancer_reliability.py tests/test_application_foundation.py tests/test_navigation_evidence.py tests/test_diagnostic_reliability.py tests/test_bug_reporting.py tests/aegis/test_learning.py -q
```

Coverage includes stale memory edits and reconciliation, scoped purge/expiry/retention, concurrent finding identity, current-row tampering and retention checkpoint integrity, consent revocation, protected pre-read Forge paths, candidate test/source-change guards, rollback and failed-commit recovery, invalid scores, sparse and future telemetry, hardware epochs, compaction, PID reuse, unavailable metrics, file identity/budgets, model concurrency, bounded history, corruption preservation, persisted rollback, legacy migration, and failed/forged model promotions. No production host maintenance, live malware remediation, telemetry dispatch, app startup, or source-tree Forge application is used by these tests. Hardware, provider, platform, and production performance validation remain necessary before broad deployment.
