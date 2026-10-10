# Investigation journal, alerts and event evidence

The journal lives at `investigations.db` beside the Aegis database, under the existing configured Aegis data directory. Opening `build_investigation_service(config, memory=memory)` does not construct a sensor or start background work. It reconciles up to 100 existing Aegis case snapshots. The original Aegis database retains earlier native assessment revisions; this reconciliation does not invent their chronology.

## Reachable workflows

The desktop's case and alert commands and Threat Center use the same service instance. Aegis assessments, exact file analyses, guarded action results and Sentry outcomes add typed timeline records. Repeated file identities reuse the case selected by `(source_kind, source_reference)`; a changed content identity can create a separate investigation. Source links are references, never delegated authority.

Remote assessments create durable activity episodes. The classification and exact session/process identities determine whether an alert changed. Acknowledgement survives process restart and concurrent monitors. A cheap monitor trigger returning false cannot end an episode; only complete quiet evidence can do so. Ended alerts remain historical records, and the active inbox filters them before applying its limit. Acknowledgement does not resolve a case.

Database schema version 2 adds immutable alert-to-evidence references without changing the reference-only transfer format. `get_alert_context(alert_id)` returns the triggering timeline entry, its channel, and `exact`, `legacy`, or `unavailable` provenance. For legacy notices, the original notice creation time bounds the search; matching must be unambiguous. Later case summaries, repeat observations and acknowledgement timestamps cannot replace the original evidence. Shared presentation translates missing checks and observed findings into plain language while retaining original priority and raw details.

Response plans persist review steps and linked results, without approval tokens or executable commands. File, remote and Aegis cases require their existing guarded response and subsequent verification workflows. Containment success does not mean that a machine is clean. General investigations instead offer relevant read-only checks, a reviewed intervention, fresh observations and a human conclusion. `review_conclusion` accepts only local manual/AIDA investigations and the exact reviewed case revision; it records `human_review`, not a provider verdict. Security closure remains governed by Aegis's later verified full-scan and current-evidence checks.

## API boundaries

- `create_case`, `case_for_source`, `link_source`, `add_evidence`, `set_phase`, `get_case`, `list_cases` and `timeline` support the deterministic investigation runner.
- `record_aegis_case`, `record_analysis`, `record_remote`, `record_action`, `record_sentry` and `record_verification` link originating service results. None invokes an action.
- `prepare_response` and `get_plan` retain review requirements across restart. Changing evidence cannot replay an approval.
- `list_alerts`, `acknowledge_alert`, `subscribe` and `unsubscribe` support the inbox and delivery bridge. Subscribers run on the publishing thread; GUI callers must marshal events to Qt. Failed delivery cannot undo committed evidence.
- `export_payload`, `export_case`, `validate_import` and reviewed `import_case` implement the shared mobile/desktop reference schema.

Imports require schema version 1, `authority: reference-only`, explicit timezone timestamps, unique evidence IDs, no unknown keys, at most 500 evidence records, 100 entries per text list, and one MiB total. Import is atomic and cannot prepare a response, record a local action or establish a baseline. Exports omit raw evidence data. Redaction replaces free text with structural summaries and hashes source references by default; it does not claim to scrub arbitrary text while retaining that text. A chosen export path is created exclusively and never overwrites an existing file.

SQLite writes serialize with `BEGIN IMMEDIATE`. Timeline identity is unique per case/kind/source reference; equal event timestamps retain insertion order. Reads are bounded. Each record is capped at one MiB, the native event cache at 10,000 rows, and the main database at 128 MiB. WAL side files can temporarily exceed the main-database ceiling. Full-database errors remain errors; AIDA does not erase historical investigations to make room. Native action ledgers remain authoritative if the secondary journal fails. Startup reconciles current Aegis case snapshots; it does not replay past actions.

## Incremental Windows events

The reader uses the query-only `wevtutil qe` operation with explicit event IDs, direction, count, XML output and a five-second timeout per subprocess. An initial enrollment or reset reads at most the newest 128 selected events from the last 24 hours. Subsequent polls read forward from an exact record identity. An extra event detects pending backlog. At most three commands are needed per channel, so an inaccessible two-channel poll may take approximately 30 seconds before returning.

Supported channels are Security (4624, 4625, 1102) and Microsoft-Windows-Windows Defender/Operational (1000, 1001, 1002, 1116, 1117, 5007). The bookmark includes record number, event fingerprint and an epoch. A missing, changed or backwards bookmark signals reset/wrap; access errors never advance it. Event insertion and bookmark advancement share a transaction, and competing collectors recheck the bookmark before writing. Native event timestamps are retained. Only selected event fields are stored; raw messages and arbitrary EventData fields are excluded.

Initial-window limits, truncated history, pending pages, unavailable permissions, parse failures and resets remain explicit coverage gaps. Discarded/reset history remains uncertain for the complete 30-minute remote evidence window, including across restarts and quiet polls. Recent cache eviction and the 512-result logon window also report incomplete coverage. These gaps prevent trusted Aegis learning and baseline acceptance. Detection and security-log-clear events can create review alerts; their presence grants no response authority. Event monitoring follows the existing observation consent. Remote assessment consumes the cached Security evidence; Aegis observation and foreground security assessments also poll Defender events. This is polling, not a guaranteed real-time subscription. Defaults inherit the existing remote assessment and Aegis observation intervals. The reader never changes audit policy, enables a log or requests elevation.

Query semantics follow [Microsoft's wevtutil documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil). Automated tests mock native calls. A limited read-only host probe read seven Defender events (1000, 1002, 5007), then zero new records while preserving the checkpoint. Security access was unavailable on both reads and remained explicitly unknown. The sanitized result is in `validation/windows-event-reader-oct-2026.json`. This validates that host's basic query/parse/forward-read path, not the full privilege, encoding, reset, load or provider-timing matrix below.

## Native qualification still required

An explicit read-only probe is available:

```powershell
.\.venv\Scripts\python.exe -B -m aida.aegis.qualify_event_reader --read-native
```

It reads bounded pages twice, reports counts, event IDs, gaps and bookmark continuity, and writes no application state. It omits accounts, IP addresses, paths and raw event contents. It does not run a scan, change privileges, mutate logs or exercise containment. Only the limited host probe described above has run during implementation; the remaining matrix is still required.

| Qualification environment | Required observation | Acceptance |
| --- | --- | --- |
| Supported Windows desktop, ordinary user | Both channel reads and restricted Security access | Evidence or explicit access gap; no elevation prompt |
| Approved Windows VM with suitable log-read access | First read followed by forward read | Stable identity, no duplicate insertion, native UTC timestamps preserved |
| VM under normal event load | More than one bounded page of selected events | Pending-page gap until backlog drains; advancing bookmark |
| Preconfigured rotated/reset log in a disposable VM | Existing bookmark no longer matches | New epoch and persistent reset gap, no invented continuity |
| Non-English Windows and non-ASCII account/path examples | XML decoding and field preservation | Exact native values or explicit parse gap, never a clean result from malformed data |
| App restart and two concurrent app instances | Same episode and same record observed twice | One active alert, durable acknowledgement, one event identity |
| Observation disabled or application closing during a read | Reader returns after cancellation | No late event or bookmark writes; bounded subprocess finishes |

Provider scan/remediation, UAC, WTS containment, rollback and physical-device acceptance remain covered by their separate qualification plans in `SECURITY_VALIDATION.md`. This read-only probe does not qualify those operations.
