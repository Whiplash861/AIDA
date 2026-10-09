# Artificer source reviews and local candidates

Artificer Center retains the existing application theme and adds **Source Reviews** and **Resources** tabs. These are local, explicit review operations. They do not enable automatic maintenance or authorize changes to the running application.

## Review workflow

1. Run Review. Codewright applies its existing deterministic checks to Python source. Supported checks cover duplicate top-level definitions, repeated bare exception handlers, executable Windows behavior outside approved adapters, syntax errors, empty modules, and conflicting version declarations.
2. Select a Source Review. The record shows the exact captured file, line span, enclosing symbol, numbered code, full-file SHA-256, and span SHA-256. It states the proposed addition or change, rationale, observed evidence, expected outcome, and required validation. Expected outcomes are explicitly unverified.
3. The selected record is checked against the current source in a background task. Stale records remain inspectable and exportable, but cannot be used to stage a candidate or create an anchored proposal. Run Review again after editing source.
4. Create Proposal links the current source review records to the existing governed proposal. A proposal grants no execution authority.
5. Export Review writes the captured annotation and its current/stale state into a user-selected existing directory.
6. Stage Candidate opens the captured span for an explicit replacement. Choose an export directory. Artificer checks the complete source hash and open finding before staging and again after static validation. It never writes to the reviewed file.

An annotation is structured review data in the local ledger, not an unsolicited comment inserted into source. Source excerpts are not operational telemetry and are not queued for remote dispatch. Explicit local report exports now include captured source review records; review their contents before sharing.

## Candidate contents and limits

Each uniquely named staging directory contains `candidate.py.txt` (the complete, inert candidate), `candidate.diff`, `annotation.json`, and `manifest.json`. The candidate preserves surrounding source, the original line-ending convention, and any UTF-8 BOM. The manifest binds the original and candidate hashes, identifies the exact replacement span, records static parse/compile checks, and distinguishes failed checks from passed checks.

No candidate code is imported, executed, installed, or applied. No generated test is run. A passing parse/compile check is **not** behavioral validation. The manifest therefore records `behavior_verified: false` and `execution_authority: false`. Public-interface regression tests, platform checks, owner review, and the separately governed Forge/rollback requirements remain necessary before any application of a change. Protected source is identified in the manifest and remains protected.

Source reads and candidates are limited to 1 MiB per file, replacements to 128 KiB, and annotations to 200 lines/32 KiB per span and 12 spans per finding per file. An oversized single line is left as a finding without an editable annotation. The current checks are a narrow deterministic review capability; they do not amount to an exhaustive semantic code audit or an automatically learned repair model.

The ledger schema is version 3. Existing version-2 audit content is verified before upgrading. Source records are immutable; staging publication transitions from `prepared` to `ready` in the audit chain. File publication is an atomic directory rename. A crash between publication and the final ledger update can leave a published inert artifact whose ledger state remains `prepared`; inspect the manifest and original hashes before reusing it. The existing 256 MiB ledger budget still applies; governance records are retained, rather than silently discarded to make room.

## Artificer and Technomancer resource evidence

Measure AIDA requests a bounded one-second sample in a background task. Technomancer's `SelfResourceObserver` samples AIDA's process family (at most 64 processes) and aggregate host CPU/memory counters. It returns CPU on both one-core and machine-capacity bases, summed resident memory, and process I/O deltas. Only processes present at both endpoints with matching PID **and creation time** contribute deltas. Missing counters are unavailable, not zero; incomplete coverage, process-set changes, and traversal truncation produce a partial observation.

Artificer stores the aggregate observation in its operational ledger with an optional operation/case correlation ID. PID values, process names, command lines, and source excerpts are not in that event. The observation describes concurrent resource activity; it does not identify the cause of a slowdown. Summed RSS can double-count shared pages, process I/O is not proof of physical disk traffic, and short-lived children can escape endpoint sampling. Sampling overhead is included. There is no automatic intervention or newly enabled background sampling.

## APIs and focused verification

`ArtificerEngine.inspect_source_review`, `export_source_review`, `stage_source_candidate`, and `measure_self_resources` back the desktop workflow. `ArtificerSnapshot.source_reviews` and `UpgradeProposal.source_review_ids` provide the integration records. The dialog uses the application's existing TaskManager.

Focused regressions cover exact annotation content, immutable inspected bytes, stale/closed finding rejection (including changes during validation), path containment, BOM/CRLF preservation, inert exports, truthful static-validation failure, audit migration integrity, proposal linkage, mocked resource counters and PID reuse, and offscreen dialog callback sequencing. They do not run live candidate code or real host diagnostics.
