# Security report language

Security reports use the shared `aida.reporting.render_report` format: **What AIDA found**, **What remains unknown**, and **What to do next**. Recorded identities, raw scores, provider details, and internal states remain available under technical details. Short acknowledgments and progress messages stay brief.

## Covered report surfaces

- Antivirus protection status, completed scans, comparisons with earlier findings, unreadable findings, failed scans, and interrupted local monitoring.
- Aegis intelligent scans, background-monitoring status, saved comparisons (baselines), and case-review summaries. Intelligent scan wording uses the same evidence explanation as saved security notices, rather than presenting an old generic risk summary as a new fact.
- File security analysis and antivirus threat reports, including incomplete checks, possible effects, and limits on actor attribution.
- Remote-access assessments and support authorization records. Recorded support expectations do not prove operator identity or imply that background monitoring is running.
- Sentry containment previews and results. Exact session/process identities and the expiring, single-use approval phrase remain visible. Unverified targets are not described as successfully stopped.
- Automatic monitoring decisions and permissions, scan cancellation, Stand Down previews/results, guarded Defender response previews/results, and the transcript summaries of Threat Center and Task Center.

## Meaning preserved

This is a presentation change. It does not alter detection thresholds, internal severity, provider calls, permission checks, approval scope or expiry, storage privacy, or frontend appearance. An urgent recorded classification remains prominent. A heuristic score is not presented as a probability of infection. A running program, startup entry, network connection, or baseline change alone does not establish malware.

A completed scan and readable findings are separate facts. A response being requested, attempted, and verified are separate outcomes. An unchanged user-trusted file remains **not verified safe**. A missing check is not an all-clear. Saved reports describe the time of their recorded evidence.

## Verification and limits

Focused tests exercise ordinary running/startup associations without an accepted baseline, missing findings, unavailable remote checks, confirmed antivirus findings, unknown protection status, exact Sentry targets and phrases, and partial versus verified containment. Existing fake-provider lifecycle and authorization tests are retained. These tests do not perform live security scans, remediation, elevation, or remote-session termination.

Raw antivirus or operating-system error text can still appear in technical details. Historical stored summaries are retained rather than rewritten. Learned risk scoring remains unchanged; its calibration and native Windows qualification are separate work from making reports accurate and understandable.
