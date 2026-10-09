# Investigation workflows and source reviews

These additions build on the October reliability checkpoint. AIDA owns the conversation and coordinates explicitly selected read-only Engine checks. Evidence, inference, a proposed response, authorization, and verified results remain separate records.

## Desktop investigation commands

- `investigate: my computer slowed down after installing a program` starts a local case, retrieves relevant eligible Memory, and collects Aegis provider status and Technomancer machine-health evidence through the Engine coordinator. The objective labels the case; it cannot generate executable commands.
- `show investigations` lists cases; `show investigation CASE-ID` displays the timeline.
- `pause investigation` requests a pause after the current bounded reader returns. `resume investigation CASE-ID` runs only incomplete read-only checks in a general investigation. Recorded failures remain visible. Imported cases and existing security-provider cases retain their original workflows.
- `prepare investigation response CASE-ID` creates a persistent response review. `show investigation plan PLAN-ID` reads its current evidence-based progress. A plan contains no executable permission or reusable approval.
- `show investigation memory CASE-ID` retrieves eligible linked history. Links can identify a case, application identity, observation, and action. Relevance ranking precedes recency; disputed, superseded and expired conclusions do not enter reasoning context.
- `conclude investigation CASE-ID: your conclusion` prepares a general-case review bound to the current revision. The existing expiring confirmation flow must approve it before it is recorded as a human conclusion. It cannot close a security-provider case or claim a verified cause.
- `show security alerts` lists unacknowledged alerts; `acknowledge alert ALERT-ID` records acknowledgement without resolving the incident.

The existing Threat Center also contains Investigations and Security Alerts tabs. File operations are disabled when a case or alert is selected. Case transfer uses a bounded JSON reference format. Export is redacted by default; import displays the captured contents for review and preserves reference-only authority. Importing does not execute any embedded text or enable operation of another device.

The main window, stylesheet, dashboard and orb components remain unchanged. Threat Center and Artificer review dialogs use the existing dark palette explicitly so native Qt controls do not render the application's light text on white backgrounds. Their new tabs and actions retain AIDA's colors and typography. An offscreen visual check confirms readable contrast and unclipped controls; native rendering remains part of desktop acceptance.

## Response and evidence continuity

File analysis and guarded Defender responses link to a case timeline and Memory. Aegis case revisions, remote-access episodes, Sentry outcomes, and verification evidence are recorded by their originating services. Engine findings can be incomplete or unavailable; worker completion never establishes a clean machine or a successful remedy.

Remote alerts retain episode identity and acknowledgement across restarts. Unchanged activity does not repeatedly interrupt the user. The desktop delivery bridge reads the durable inbox in its own thread, sends notifications through Qt, excludes evidence from cloud chat context, and ignores callbacks after shutdown. Background evidence collection still follows existing observation consent.

Incremental Windows event evidence uses bounded forward reads and persisted record identities. Initial backfill limits, inaccessible logs, resets, wrapping and pending pages remain visible as coverage gaps. It never changes audit policy or requests elevation. Query syntax is based on [Microsoft's wevtutil documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil). Actual Windows event timing and permissions require native qualification.

## Artificer source annotations

The Artificer Center's Source Reviews tab presents each supported static finding with:

1. The file, symbol, line span, captured numbered source, and file/span SHA-256 identities.
2. The exact addition or change being proposed.
3. The observed evidence and the reasoning for the proposal.
4. Expected outcomes, explicitly marked as unverified.
5. The validation needed before accepting the change.

Annotations are durable review records linked to findings and proposals. They do not insert speculative comments into live production code. Rechecking detects changed or unavailable source and findings that are no longer open. Exporting a review produces a local annotation artifact.

Stage Candidate lets the owner edit the reviewed span and export an inert candidate, unified diff, annotation, and validation manifest into a selected directory. Source identity is checked before and after validation. Parsing and compilation do not execute the candidate and do not prove its behavior. The source is not overwritten. Applying a candidate still requires the existing governed maintenance path and an appropriate owner authorizer; this increment does not enable unattended self-modification.

The Resources tab measures AIDA's own process family and same-window host counters. This joins Artificer's operational context with Technomancer's resource evidence. Missing counters remain unknown; temporal correlation is not labeled a proven cause.

## Practical limits

General investigations currently have a deterministic read-only check set, rather than a model-generated execution plan. Evidence is bounded and longer Engine output is explicitly excerpted. Review the original Engine report for full detail. A result requires human review before a supported response is chosen.

Application recovery plans now include a fresh health observation. Application-changing repair recipes remain unsupported until their exact application/version behavior has been validated; the prototype does not claim generic recovery or rollback.

Mobile adds local baseline comparisons, follow-up observations, selected-image metadata intake, literal text indicators, and reviewed case transfer. Semantic mobile OCR/visual diagnosis and live remote-device operation remain unavailable. Desktop OCR indicator extraction supplies observations, not executable instructions or a malware verdict.

Native Windows provider/UAC/WTS tests, physical-device mobile acceptance, and externally hosted gateway acceptance remain distinct from deterministic automated tests. No live provider mutation or deployment is part of these code tests.

## Validation recorded on October 9, 2026

- The complete Python suite passed: **565 tests**, with one upstream Starlette/httpx deprecation warning.
- Mobile behavior tests passed: **39 tests**. Full TypeScript checking passed in an isolated copy with the same lockfile after a OneDrive dependency read stalled in the original checkout.
- Python compilation, dependency consistency and Git whitespace checks passed. Desktop/mobile case transfer also passed a Python-to-TypeScript roundtrip check.
- An offscreen visual review confirmed readable new investigation controls using AIDA's existing dark colors. Main-window, theme and orb files match the reliability checkpoint; mobile Home, Systems, More and orb style declarations also match it.
- A read-only native Windows probe retrieved seven Defender events, followed by zero new records with its checkpoint preserved. Security log access was unavailable and remained explicitly unknown. See the [sanitized probe result](validation/windows-event-reader-oct-2026.json) and [remaining native qualification matrix](INVESTIGATIONS_SECURITY_BACKEND.md#native-qualification-still-required).

Detailed feature boundaries are documented in the [Artificer source review guide](ARTIFICER_SOURCE_REVIEW.md), [investigation backend guide](INVESTIGATIONS_SECURITY_BACKEND.md), and [mobile workflow guide](architecture/mobile-investigation-workflows.md).
