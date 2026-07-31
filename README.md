# AIDA

Analytical Intelligence & Diagnostic Agent.

AIDA is a Windows-focused desktop diagnostic and security prototype built around deterministic local executors, explicit authorization, operational memory, controlled autonomy policy, and provider-backed security evidence.

## Prototype capabilities

- System and application diagnostics
- Microsoft Defender status and user-authorized security scans
- Durable recovery of provider-owned Quick and Full scans after AIDA restarts
- Exact-confirmation, provider-confirmed scan cancellation
- Detection reconciliation that separates new, unresolved historical, and resolved findings
- AIDA-local Stand Down trust exceptions with identity-change, alarm, expiry, and revocation controls
- User-specific Memory Bank and Event Journal
- Context Prediction Index for natural-language command resolution
- Controlled Autonomy settings, policy enforcement, and read-only Observation mode
- Local-first bug reporting through reviewable `.eml` drafts and webmail handoff

Bug reports are saved locally and sanitized before AIDA opens a review window. Outlook Web is the validated primary handoff to `AIDAdeveloper@outlook.com`; Gmail Web, the default mail application, clipboard copy, and the local draft folder remain available as alternatives. The user reviews the report and clicks **Send**. No mail-service subscription, API key, or mailbox password is required.

See `docs/AIDA_SECURITY_AUTONOMY_MEMORY_FOUNDATION.md`, `docs/AIDA_SECURITY_LIFECYCLE_FIELD_TEST.md`, and `docs/AIDA_BUG_REPORTING.md` for current prototype boundaries and validation requirements.
