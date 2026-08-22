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
- explicit capability registry and staged-provider reporting
- Precision Glass mobile frontend and AIDA orb

Android-specific deterministic executors, full semantic MemoryService parity, microphone/transcription, camera/perception, notifications, and additional Engine providers remain staged or limited until their real platform implementations are added.

## One-command development workflow

Normal frontend development should not require copying a LAN IP or manually entering a gateway token on the phone.

From the repository root:

```powershell
.\scripts\start-mobile-dev.ps1
```

The launcher:

1. detects the active LAN IPv4 address
2. generates an ephemeral development gateway credential
3. starts the AIDA Services Gateway on port 8787
4. writes an ignored `mobile/.env.local` containing the temporary development URL/token
5. verifies gateway health
6. installs updated mobile dependencies when needed
7. synchronizes the canonical root AIDA sound assets into the Expo bundle
8. runs TypeScript validation
9. starts Expo/Metro
10. removes the temporary environment file and stops the gateway when the session ends

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
    +-- /v1/resolve    -> native AIDA intent resolution
    +-- /v1/reasoning  -> AIDABrain + AIDA_SYSTEM_PROMPT
    +-- /v1/speech     -> canonical ElevenLabs AIDA voice
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
- an ordinary question is answered by canonical AIDABrain rather than the bounded mobile fallback
- a follow-up question uses recent conversation context
- Speech Output produces start cue -> AIDA ElevenLabs voice -> end cue
- Activity identifies gateway/Brain/speech behavior without silent fallback
- a registered command such as a diagnostic request resolves through AIDA's native intent layer; if no Android executor exists yet, AIDA explicitly states that no operation was executed

## Security

Azure/OpenAI and ElevenLabs provider credentials must never be embedded in the Android application.

Development uses only an ephemeral local gateway credential generated by the launcher. Release enrollment will use revocable device/session credentials rather than a bundled provider key.

## Transitional code

The older `aida/mobile_api` desktop bridge remains transitional repository code. It is not the primary runtime architecture for standalone AIDA Mobile.

## Version

Current application milestone:

```text
AIDA Mobile 0.1.0 Early Alpha
```

The permanent Android application/package identifier must be deliberately selected before the first Google Play artifact is created.
