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

## October 2026 reliability implementation

The desktop now connects Aegis and Technomancer through AIDA's existing command surface. Security results carry provider state and evidence availability separately. Reviewed baselines, expiring scoped confirmations, durable case history, versioned learning, corrected Memory retrieval, and controlled background readers strengthen the local workflow. The existing desktop theme and orb remain unchanged.

See [the implementation review](docs/IMPLEMENTATION_REVIEW_OCT_2026.md) for the change map, validation results, new review commands, configuration and remaining integration checks. The [mobile/gateway contract](docs/architecture/mobile-gateway-reliability-validation.md) covers standalone mobile behavior and per-device enrollment.

Development installation and regression checks:

```powershell
python -m pip install -r requirements-dev.txt -c requirements-lock.txt
python -m pytest -q
node --test mobile/tests/runtime.test.cjs
node mobile/node_modules/typescript/bin/tsc --project mobile/tsconfig.json --noEmit --incremental false
```

The automated tests use temporary state and mocked security/provider boundaries. Live security operations and native-device validation require the controlled checks documented in the implementation review.
