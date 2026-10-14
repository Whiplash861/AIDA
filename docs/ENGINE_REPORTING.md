# Engine report language

AIDA's substantive user-facing reports use three questions: **What AIDA found**, **What remains unknown**, and **What to do next**. A short **What this means** explanation can connect observations to a cautious interpretation. Progress messages, acknowledgments, and simple answers can remain brief.

The shared Python formatter is `aida/reporting.py`; mobile presentation helpers are in `mobile/src/core/reporting.ts`. These helpers format supplied evidence. They do not assign risk, grant permissions, run actions, or infer success from an empty result. The AIDA reasoning prompt follows the same standard for generated investigation recaps.

## Writing and evidence rules

- Explain the observation and its scope before presenting a conclusion. Identify the affected item and observation time when available. A saved report is historical information, not a fresh inspection.
- Distinguish a measured zero, no recorded findings, an unavailable measurement, and a check that never ran. None is interchangeable with another. Missing information belongs with the limitations; it does not establish damage, infection, or safety.
- Describe ordinary running programs, startup entries, high resource use, and network connections in context. These associations alone do not prove harmful behavior or hardware damage.
- Keep supported urgent findings and required user action prominent. Do not turn unavailable telemetry into an urgent computer-health warning. Retain original severity and diagnostic identifiers in technical details where needed.
- Explain technical terms before relying on them. Provide a practical next step that exists in the current interface or a clearly identified operating-system control. A plan is not execution, and a completed task is not necessarily a verified fix.
- Label proposed causes and expected improvements as unverified. Internal confidence and priority scores are not measured probabilities of infection, damage, or correctness.
- Preserve exact file identities, source excerpts, confirmation phrases, approval requirements, and original evidence. Do not rewrite quoted material as if AIDA had verified it. Technical details remain available for investigation.
- A brief spoken summary must preserve urgency and uncertainty. It must not declare normal operation merely because no high-severity finding was returned.

## Current presentation coverage

| Area | Reports and limits explained |
| --- | --- |
| Aegis and security providers | Intelligent scans, provider status and scan outcomes, baseline review, file analysis, antivirus detections, reconciliation, incomplete checks and historical security notices. |
| Remote security and Sentry | Recorded sessions and remote tools, consent/support windows, proposed defensive actions, execution and verification outcomes. No claim to identify an attacker from a user declaration alone. |
| Technomancer | Current resource observations, covered history, saved advisories, hardware inventory, upgrade reasoning and AIDA's own resource measurements. Unknown counters and unverified causes remain explicit. |
| Artificer | Overview, compatibility, findings, source annotations, proposals, governance, and inert candidate exports. Exact reviewed code and proposed change remain linked to rationale, expected outcomes and required validation. Static checks do not prove runtime behavior. |
| Memory | Saved memories, revised/disputed records, search results, timeline events and linked investigation history. A prior record or user correction is not independent verification. |
| Perception | Selected local image review, extracted text and literal diagnostic markers. Missing OCR differs from OCR that returned no text; quoted content is not executed or treated as diagnosis. |
| Diagnostics and application assistance | Desktop Quickscan/performance reports and speech, legacy CLI scan output, application health/recovery plans, evidence location, Task Center and investigation response workflows. |
| Automatic monitoring | Policy decisions, observations, provider responses and follow-up recommendations. A permission decision does not establish that an action ran or succeeded. |
| Mobile | Android diagnostics/Aegis, staged Engine replies, local fallback replies, comparisons, selected IMAGE/PASTE review, case previews, saved reports, Activity and feature availability. See the [mobile inventory](architecture/mobile-investigation-workflows.md). |

Existing alert-to-evidence references and historical provenance are retained. Security scores, thresholds, confirmation gates, and action authority are unchanged by the language work. Application resource observations now preserve unavailable values instead of inventing zero use; this prevents a missing measurement from supporting a healthy classification. GPU reports also preserve available values when another field is missing.

## Appearance and acceptance

The main theme, colors and orb behavior remain intact. Existing report controls display the clearer text. Memory details scroll within the existing dialog so the longer explanations remain accessible, and its native controls use the established dark review palette for readable contrast. Mobile changes retain the original StyleSheet declarations.

Automated regression tests cover absent/partial data, urgent results, historical records, unverified plans, OCR limits, unsupported mobile features and exact action controls. Native Windows provider actions, physical-device accessibility/wrapping and deployed gateway behavior require their own acceptance checks. These report changes do not deploy a mobile build or execute a repair.

## Validation recorded on October 14, 2026

- Complete Python suite: **701 passed**, with one upstream Starlette/httpx deprecation warning. A final historical-summary clarification then passed **26 focused investigation and notice tests**. Python compilation and Git whitespace checks passed.
- Mobile: **52 behavior tests passed** and full TypeScript checking passed in the isolated validation copy with the matching dependency lockfile. The four modified UI files retain their exact original StyleSheet declarations; theme and orb files were not changed.
- Regression cases include the original Aegis pattern of ordinary running/startup associations with no accepted baseline, unavailable antivirus results, unavailable application resource counters, partial graphics measurements, interrupted tasks, and saved plans that may already have earlier actions in their history.
- Offscreen checks of the actual Memory dialog at 900×620 and 720×480 confirmed readable dark-theme contrast, scrollable reports and visible controls without overlapping the detail panel. The checks used synthetic records and an isolated temporary store.
