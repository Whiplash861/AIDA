# Mobile and services gateway reliability contract

The mobile instance remains standalone. Android observations and supported deterministic commands execute on that device. The services gateway supplies the shared AIDA Brain, voice and transcription providers; it does not execute the resolved mobile command on its host. The optional desktop bridge is separate.

## Enrollment and transport

Protocol version 2 exchanges the operator's `AIDA_SERVICES_GATEWAY_TOKEN` at `POST /v1/enroll` for a random device session. The bootstrap credential cannot call provider routes. Only SHA-256 session hashes are stored in SQLite; sessions expire after seven days and `DELETE /v1/session` revokes the authenticated session and clears its route context. Another device's session remains valid. Persist the gateway state volume in production; a lost session database requires re-enrollment.

`AIDA_GATEWAY_SESSION_DB` selects the SQLite path. The container runs as UID 10001 with a writable /home/aida/state volume. TLS should terminate at the hosting platform/reverse proxy; enrolled mobile endpoints require HTTPS. Browser deployments must explicitly set `AIDA_GATEWAY_CORS_ORIGINS` to their exact allowed origins.

Mobile saves URL, token, device identifier and expiry in one SecureStore envelope. Legacy split values migrate through enrollment rather than becoming provider credentials. Browser session credentials stay in memory. Development credentials are accepted only under `__DEV__`; the EAS pre-install release validator rejects public development/legacy bearer credentials from process environment and dotenv files. The development launcher uses process-scoped settings and restores them; it does not rewrite or delete .env.local.

`MOBILE_REASONING.disconnect()` performs authenticated revocation before clearing credentials. It intentionally does not claim successful revocation if the gateway is unreachable. The optional desktop client has explicit `configureDesktopBridge(httpsUrl, pairingToken)` and `disconnectDesktopBridge()` functions, storing the separate desktop pairing token only in memory. A desktop connection screen remains staged.

## Privacy and execution

Unclassified/pending user turns are excluded from Brain history. Successful conversational turns opt in; local commands and failures remain excluded. This is a context-retention policy: remote intent resolution, reasoning, voice and transcription still transmit their explicitly requested inputs to the configured provider.

Supported offline commands include Quickscan, performance scan, security status, surface security scan and retrieval of the last retained diagnostic. Known private command families without a mobile executor receive a local unavailable response. iOS/web do not invoke Android diagnostic providers. Confirmation-required commands cannot execute until a mobile confirmation workflow is registered.

Diagnostic records retain timestamp, platform, observations, coverage gaps and transcript locally, bounded to 30 entries. Aegis manual providers are registered to real executors. Missing background observation, security-provider telemetry, semantic memory, remediation and other unimplemented Engine capabilities remain staged or limited.

Gateway requests use bounded schemas, body size limits, upload deadlines, per-session rate limits and a concurrency ceiling. Public errors omit rejected input, provider bodies and host paths. Provider SDK retries/timeouts and mobile aborts are bounded. Client cancellation does not forcibly terminate an already dispatched provider call on the server; that call remains bounded by its provider timeout and concurrency slot.

## Automated verification

Commands run from the repository root, without real recording, external providers or listening servers:

```powershell
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/test_gateway_security.py tests/test_services_gateway_parity.py tests/test_mobile_api.py
node --test mobile/tests/runtime.test.cjs
```

The Python suite uses TestClient, temporary session databases and fake providers. It checks bootstrap/session separation, device identity binding, revocation/expiry, Unicode auth, private validation errors, body/concurrency limits, isolated router context and disposable audio.

The Node suite compiles production TypeScript in memory with the installed TypeScript compiler and replaces native/network boundaries with fakes. It checks operation ownership, retry, atomic storage, browser credential lifetime, private history, platform/confirmation gates, evidence retention, speech cancellation and microphone permission/start races. It also tests production Home functions through test-only capture instrumentation; no production debug entry points are added.

Verification completed on 2026-10-09: 37 targeted gateway/mobile-API/tone tests passed (58 with the related perception, voice-lifecycle and interaction suites); 23 Node behavior tests passed; `node mobile/node_modules/typescript/bin/tsc --project mobile/tsconfig.json --noEmit --incremental false` completed with exit code 0. Dependency resolution initially stalled during OneDrive hydration; a compiler trace showed progress through the React Navigation, Reanimated and SVG declaration files before completing without diagnostics. Native builds, physical-device tests, live provider integration and release distribution were not performed. The TestClient suite emits one upstream httpx deprecation warning.

## Native acceptance checks before distribution

1. On Android and iOS, double-tap MIC while the permission prompt is open. Only one recorder may prepare/start. Deny permission, grant it, then retry.
2. Background, lock, navigate away or unmount during permission, preparation, recording and transcription. Native recording must stop; temporary audio must be removed; stale callbacks must not unlock a newer operation. Record past 120 seconds with a stalled JS thread to verify native duration enforcement.
3. Mute during the start cue, network synthesis, playback and queued speech. Audio and queued utterances must stop promptly. Mute during reasoning must preserve ANALYZING and reject another directive.
4. Start without network, run supported local diagnostics, reconnect and refresh Systems. Provider capabilities must recover without restarting the app. Verify rejected/local/failed command content is absent from a later reasoning request.
5. Enroll two physical devices against one gateway, reuse a client-supplied instance identifier, revoke one session and verify that context/credentials remain isolated. Restart the gateway with the same session volume.
6. Force storage-write failure during enrollment and ensure the previous endpoint/token remain paired. Force temporary audio-write/delete failure and verify cleanup warnings and recovery.
7. Build preview/production with clean credentials, then verify the release validator rejects development credentials. Compare Home, Systems, Control and orb appearance with the existing reference on the same viewport. Active-state styles, colors, geometry and orb render parameters are preserved; background/unfocused/reduced-motion animation pauses.
