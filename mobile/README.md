# AIDA Mobile — Standalone Early Alpha

React Native / Expo frontend and mobile runtime for **AIDA — Analytical Intelligent Diagnostic Agent**.

## Development principle

AIDA Mobile is a platform port of AIDA, not a separately designed assistant or remote frontend for Desktop AIDA.

The native Windows/Python implementation is the present behavioral reference. Android may replace PySide, Windows diagnostics, filesystem navigation, audio playback, storage APIs, and other operating-system providers, but AIDA's identity, language rules, intent semantics, reasoning prompt, speech identity, audio cues, safety boundaries, and public operational states remain shared.

See:

`docs/architecture/mobile-native-parity-contract.md`

## Current Early Alpha foundation

The mobile runtime currently provides:

- standalone device-local AIDA instance identity
- Android/platform awareness
- persistent runtime state and activity journal
- AIDA's canonical startup transcript
- native-style recent conversation context for Brain requests
- native AIDA intent resolution before language-model reasoning when the Services Gateway is available
- canonical AIDABrain reasoning through the shared Services Gateway
- canonical AIDA start and end WAV cues
- canonical ElevenLabs voice synthesis through the same server-side voice implementation used by desktop AIDA
- serialized speech sequencing
- push-to-talk Android microphone capture with native `LISTENING` / `PROCESSING` behavior
- disposable voice recording with the same 120-second bound as native AIDA
- authenticated transcription through AIDA's existing `OpenAITranscriptionProvider`
- automatic routing of a completed voice transcript through the same directive path as typed input
- explicit capability registry and staged-provider reporting
- Precision Glass mobile frontend and AIDA orb

Android-specific deterministic diagnostic executors, full semantic MemoryService parity, camera/perception, notifications, and additional Engine providers remain staged or limited until their real platform implementations are added.

## One-command development workflow

Normal frontend development should not require copying a LAN IP or manually entering a gateway token on the phone.

From the repository root:

```powershell
.\scripts\start-mobile-dev.ps1
```

The launcher:

1. validates parity-critical Python modules
2. detects the active LAN IPv4 address
3. generates an ephemeral development gateway credential
4. starts the AIDA Services Gateway on port 8787
5. writes an ignored `mobile/.env.local` containing the temporary development URL/token
6. verifies intent, reasoning, speech, and transcription provider readiness
7. reconciles mobile dependencies
8. synchronizes the canonical root AIDA sound assets into the Expo bundle
9. runs TypeScript validation
10. starts Expo/Metro
11. removes the temporary environment file and stops the gateway when the session ends

To force a clean Metro cache:

```powershell
.\scripts\start-mobile-dev.ps1 -ClearMetro
```

The Galaxy and development computer must still have a reachable network path to each other when Expo uses LAN mode.

## Development gateway versus Desktop AIDA

The Services Gateway is not the old Desktop AIDA mobile bridge.

Desktop AIDA does not need to be open. The gateway is a provider boundary that exposes authenticated native AIDA services while privileged credentials remain server-side:

```text
AIDA Mobile
    |
    +-- /v1/resolve        -> native AIDA intent resolution
    +-- /v1/reasoning      -> AIDABrain + AIDA_SYSTEM_PROMPT
    +-- /v1/speech         -> canonical ElevenLabs AIDA voice
    +-- /v1/transcription  -> native AIDA transcription provider
```

The gateway does not execute a resolved Android directive on the development PC. Device operations require explicit Android providers.

For production/field use, this boundary can later be hosted so the standalone mobile instance does not depend on the development computer being reachable.

## Speech contract

Mobile speech mirrors native AIDA's sequence:

```text
aida_start.wav
      -> canonical TTS cleanup
      -> configured ElevenLabs AIDA voice
      -> aida_end.wav
```

The root files are the source of truth:

```text
assets/sounds/aida_start.wav
assets/sounds/aida_end.wav
```

`mobile/scripts/sync-aida-assets.js` copies those exact files into the Expo bundle before normal start commands.

Android system TTS is a degraded fallback only when no AIDA voice service is configured. It is not AIDA's normal voice identity.

## Voice-input contract

Mobile voice input mirrors native AIDA's push-to-talk behavior:

```text
STANDBY
   -> user presses MIC
LISTENING
   -> user presses STOP MIC
MICROPHONE: PROCESSING
   -> authenticated transcription
transcript
   -> normal AIDA directive routing
```

Important guarantees:

- microphone permission is requested only after a user-initiated MIC action
- capture is bounded to 120 seconds
- raw audio is temporary and is not written to AIDA memory or the Activity transcript
- the Expo cache recording is deleted after success or failure
- the gateway's temporary provider file is deleted in `finally`
- the resulting text is treated exactly like a typed user directive
- if transcription is unavailable, no recording is started and Control reports Voice Input as staged

The development gateway reports transcription readiness from `OPENAI_API_KEY` and `AIDA_TRANSCRIPTION_MODEL` remains the native provider model selector.

## Reasoning and command routing

Mobile follows the native routing order:

```text
User directive
     |
Native AIDA intent resolver
     |
     +-- registered directive -> Android executor boundary
     |
     +-- unresolved language -> AIDABrain
```

A recognized command with no Android executor is reported as unavailable and no operation is claimed. This preserves AIDA's rule that an action cannot be reported as completed unless a deterministic provider confirmed it.

## Expo Go test sequence

After starting the development launcher, scan the Expo QR code and verify:

- startup transcript reads `Analytical Intelligent Diagnostic Agent is activated.` followed by `State malfunction parameters.`
- status settles to `STANDBY`
- Brain shows `IDLE` when the development Services Gateway is healthy
- Control shows `DEVELOPMENT AUTO` instead of requiring manual gateway enrollment
- Voice Input shows `READY` when the transcription provider is configured
- an ordinary typed question is answered by canonical AIDABrain rather than the bounded mobile fallback
- a follow-up typed question uses recent conversation context
- Speech Output produces start cue -> AIDA ElevenLabs voice -> end cue
- pressing MIC requests Android microphone permission only when needed
- while recording, AIDA enters `LISTENING` and the orb follows the native GREEN active-state mapping
- pressing `STOP MIC` enters transcription processing and the resulting transcript appears as the user directive
- the voice-generated directive receives the same routing/reasoning behavior and ElevenLabs response as typed input
- Activity identifies gateway/Brain/speech/voice behavior without storing raw audio
- a registered command such as a diagnostic request resolves through AIDA's native intent layer; if no Android executor exists yet, AIDA explicitly states that no operation was executed

## Security

Azure/OpenAI, OpenAI transcription, and ElevenLabs provider credentials must never be embedded in the Android application.

Development uses only an ephemeral local gateway credential generated by the launcher. Release enrollment will use revocable device/session credentials rather than a bundled provider key.

## Transitional code

The older `aida/mobile_api` desktop bridge remains transitional repository code. It is not the primary runtime architecture for standalone AIDA Mobile.

## Version

Current application milestone:

```text
AIDA Mobile 0.1.0 Early Alpha
```

The permanent Android application/package identifier must be deliberately selected before the first Google Play artifact is created.
