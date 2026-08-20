# AIDA Early Alpha Threat Assistance

This checkpoint adds a local-first bridge between antivirus findings and safe user action. All security evidence remains excluded from language-model context.

## 1. Stand Down workspace

Stand Down remains an AIDA-local user trust exception. It never creates a Microsoft Defender exclusion, never chooses **Allow on device**, and never certifies a file as safe.

Each record is bound to the exact path, SHA-256, size, modification identity, available signer/certificate identity, file version, user, device, reason, and expiry. A new provider alarm, explicit scan, expiry, missing file, hash change, signer change, certificate-thumbprint change, or version change resumes normal assessment.

## 2. Threat Detection Analysis v2

The read-only analyzer records:

- Exact file path, SHA-256 within the configured size limit, size, timestamps, extension, and detected file-header type.
- Authenticode status, signer, certificate thumbprint, publisher, product name, and version when Windows exposes them.
- Exact-path process matches, parent PID, sanitized command line, and observed remote endpoints.
- Read-only Startup/Run/RunOnce persistence references.
- Deterministic static indicators such as extension/header mismatch, deceptive double extensions, invalid signatures, suspicious script indicators, and user-writable launch placement.

The target is never executed, imported, or dynamically loaded. Provider classification, AIDA assessment, severity, confidence, potential impact, current activity, and remaining uncertainty are presented separately. Actor identity and physical location default to unknown.

## 3. Evidence navigation

The Threat Center can open the containing folder, select an exact item in File Explorer, copy a path, reanalyze, locate, prepare a response plan, review Stand Down, or review remediation. Navigation never launches the suspicious file.

When the original path is missing, bounded search prefers exact SHA-256, then exact recorded identity, then filename-only candidates. Weak matches are labeled **POSSIBLE MATCH — USER VERIFICATION REQUIRED** and inherit no threat label or authorization.

## 4. Task Center and guided response

Long-running assistance work is stored in SQLite with states including running, awaiting authorization, verifying, completed, failed, cancelled, interrupted, and recovering. Analysis and location tasks support cooperative cancellation at safe checkpoints. Nonterminal tasks are marked interrupted after an AIDA restart rather than falsely completed.

Permanent raw deletion is blocked in Early Alpha. The available provider-remediation path requires:

1. A prior exact-file analysis.
2. Exactly one active Defender threat.
3. Matching path, Threat ID, and SHA-256.
4. A fresh, exact, single-use confirmation.
5. Windows elevation after confirmation.
6. Provider revalidation before action and verification afterward.

No exclusion, allow action, or raw filesystem deletion is performed.

## 5. Observation integration

Observation Mode may collect read-only local analysis for up to three unresolved file-based findings, record a response plan, and explain what it recommends. It executes no scan, remediation, deletion, process termination, Stand Down change, exclusion, or repair.

## User commands

Examples:

```text
analyze threat "C:\\Path\\sample.exe"
locate threat file "C:\\Path\\sample.exe"
open containing folder "C:\\Path\\sample.exe"
select in explorer "C:\\Path\\sample.exe"
prepare threat response "C:\\Path\\sample.exe"
remediate threat "C:\\Path\\sample.exe"
confirm defender remediation
delete suspicious file "C:\\Path\\sample.exe"
show threat center
show task center
```

## Field-validation order

1. Create Stand Down for harmless test material and verify snapshot fields.
2. Modify the test file and confirm Stand Down suspension.
3. Analyze a harmless PE-like fixture and verify the file is never launched.
4. Move a test file and locate it by SHA-256.
5. Exercise Task Center cancellation during a bounded location search.
6. Verify permanent deletion remains blocked.
7. Use a recognized harmless antivirus test artifact to validate provider analysis and guarded-remediation preparation. Do not run live remediation until the exact sole-active-threat guard is confirmed.
8. Enable Observation and verify analysis/reporting occurs without operational action.
