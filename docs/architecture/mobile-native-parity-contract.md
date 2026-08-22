# AIDA Mobile Native-Parity Contract

## Purpose

AIDA Mobile is a platform port of AIDA, not a separately designed assistant.

The Windows/Python AIDA runtime is the present behavioral reference implementation. Mobile may replace platform-specific providers, rendering technology, storage APIs, permissions, and audio playback mechanisms, but it must not independently redefine AIDA's identity, language, command semantics, safety model, speech identity, or operational states.

The governing question for mobile work is:

> How does AIDA already perform this behavior, and which implementation detail must change for Android or iOS?

It is not:

> How should Mobile AIDA behave?

## 1. Identity and language

Authoritative source: `aida/brain/system_prompt.py`.

All full language-model responses must pass through `AIDABrain` and the canonical `AIDA_SYSTEM_PROMPT`.

Required communication characteristics include:

- AIDA identifies as the Analytical Intelligent Diagnostic Agent.
- Professional, objective, respectful, concise output.
- Short, declarative sentences.
- No first-person language: no `I`, `me`, or `my`.
- No invented capability claims.
- Plain-text response contract for Brain output.
- Diagnostic evidence and user authority remain primary.

Mobile-specific canned personality must not become an alternate source of truth. A bounded offline fallback may report local runtime facts, but it must remain clearly limited and must follow the same language rules.

## 2. Startup transcript

Authoritative source: `aida/frontend/controller.py`.

A normal frontend session begins with:

System:
`Analytical Intelligent Diagnostic Agent is activated.`

AIDA:
`State malfunction parameters.`

Platform information may be shown in status surfaces, but it must not replace AIDA's canonical activation language with an independently invented mobile greeting.

## 3. Operational state vocabulary

Authoritative source: `aida/frontend/status.py`.

The canonical frontend states are:

- STARTUP
- STANDBY
- LISTENING
- ANALYZING
- SPEAKING
- WARNING
- ERROR
- SHUTDOWN

Mobile may have internal provider substates, but public AIDA state must map into this vocabulary.

## 4. Orb state contract

Authoritative source: `aida/frontend/internal_orb.py`.

Default live-state resolution presently follows:

- STANDBY -> BLUE
- STARTUP -> GREEN
- LISTENING -> GREEN
- ANALYZING -> GREEN
- SPEAKING -> GREEN
- ERROR -> RED
- SHUTDOWN -> RED
- active task count -> GREEN
- active Artificer work -> PURPLE
- trouble codes may override normal status according to native precedence

Mobile must not assign a new semantic color to an existing AIDA state merely because another color looks suitable on a phone.

## 5. Directive routing order

Authoritative sources:

- `aida/frontend/controller.py`
- `aida/frontend/command_router.py`
- `aida/intent/*`

Every directive follows this order:

1. Normalize and resolve through AIDA's registered intent system.
2. If a registered command resolves, use a deterministic platform executor.
3. If clarification is required, return AIDA's clarification path.
4. Only unresolved conversational/diagnostic language reaches AIDABrain.

A platform port may not bypass the native intent layer and send all text directly to the language model.

The services gateway may resolve an intent for a standalone client, but it must never execute a device-local command on the gateway host. Resolution and execution are separate authorities.

## 6. Platform executors

A resolved command is not proof that a platform can execute it.

Android and iOS must maintain explicit provider registries. Until a provider exists, AIDA must state that the command was recognized but no supported platform executor is available. It must not simulate successful execution.

This preserves the canonical capability boundary:

> Never claim that an operation ran unless a deterministic executor confirmed it.

Examples:

- A Windows Defender scan intent may resolve on Android, but it must not run Defender on the gateway PC.
- A Windows Explorer navigation intent may resolve, but it must not claim Android opened an equivalent location unless an Android executor actually did so.
- Platform-neutral commands may be ported when their underlying policy/storage services have genuine mobile implementations.

## 7. Conversation context

Authoritative source: `aida/frontend/models.py`.

Before a Brain request, native AIDA supplies up to 12 recent context-eligible messages rendered as:

- `User: ...`
- `AIDA: ...`
- `System: ...`

Local-only command exchanges are excluded from later Brain context.

Mobile must preserve:

- the 12-message limit
- sender labels
- message order
- context eligibility
- exclusion of local-only command exchanges

## 8. Command transcript versus speech

Authoritative source: `aida/frontend/command_manager.py` and command executors.

A deterministic command may produce:

- a detailed `transcript_text`
- a shorter `speech_text`

Mobile must not assume displayed text and spoken text are always identical.

When an Android/iOS executor is ported, its transcript, speech line, start message, confirmation behavior, and context eligibility should match the native command contract unless the platform difference requires an explicit adaptation.

## 9. Speech sequence

Authoritative sources:

- `aida/ui/cli.py`
- `aida/audio/tones.py`
- `aida/audio/voice.py`

Every normal AIDA spoken line follows this sequence:

1. Play canonical `aida_start.wav` to completion.
2. Apply canonical TTS text cleanup.
3. Speak using AIDA's configured ElevenLabs voice.
4. Play canonical `aida_end.wav` to completion.
5. Return to the appropriate operational state.

The canonical sound files live in:

- `assets/sounds/aida_start.wav`
- `assets/sounds/aida_end.wav`

Mobile build tooling must synchronize those files rather than maintain separately edited copies.

## 10. Canonical TTS cleanup

Authoritative shared helper: `aida/audio/text.py`.

Current behavior includes:

- `|` becomes a natural sentence pause.
- `:` becomes a natural sentence pause.
- `.exe` is spoken as `executable`.
- `.lnk` is spoken as `shortcut`.
- `.msi` is spoken as `installer`.
- noisy Windows paths are reduced to `file path`.
- repeated whitespace is collapsed.

Equivalent remote/mobile speech must use this cleanup before provider synthesis.

## 11. Voice identity

Authoritative source: `aida/audio/voice.py`.

AIDA's current ElevenLabs settings are shared, not redefined per frontend:

- model: `eleven_multilingual_v2`
- stability: `0.25`
- similarity boost: `0.85`
- voice ID: configured through AIDA's trusted environment

Provider credentials must not be embedded in mobile builds.

The AIDA Services Gateway may synthesize speech server-side by calling the same canonical voice module used by desktop AIDA.

Android/iOS operating-system TTS must not substitute for AIDA's configured ElevenLabs voice. If the AIDA voice service is unavailable, the client may complete the canonical cue cycle and surface the provider failure, but it must not impersonate AIDA with another voice.

## 12. Speech serialization

Authoritative source: `aida/frontend/controller.py` and `aida/audio/voice.py`.

AIDA voice lines must not overlap. A new utterance arriving during active speech is queued.

Mobile must serialize the complete audio cycle, including start tone, provider speech, and end tone.

## 13. Voice input state machine

Authoritative sources:

- `aida/interaction/qt_bridge.py`
- `aida/interaction/voice_capture.py`
- `aida/interaction/transcription.py`

The interaction contract is:

READY -> LISTENING -> PROCESSING -> transcript/result -> READY

Cancellation and errors are explicit states/events.

Android/iOS recording APIs may differ, but the user-facing state machine must remain AIDA's existing one. Capture remains user-initiated, bounded to 120 seconds, disposable, and excluded from AIDA memory as raw audio. The resulting transcript enters the same directive path as typed input.

## 14. Reasoning and provider service boundary

Standalone mobile AIDA must not depend on Desktop AIDA being open.

During Early Alpha, provider-backed reasoning, voice, and transcription may be supplied through the AIDA Services Gateway. The gateway:

- holds Azure/OpenAI, OpenAI transcription, and ElevenLabs credentials server-side
- invokes canonical AIDABrain
- invokes canonical AIDA voice synthesis
- invokes AIDA's existing transcription provider for disposable audio
- may expose canonical intent resolution
- must not execute client-device commands on the gateway host

A future hosted deployment may move this boundary off the development PC without changing the mobile AIDA behavior contract.

## 15. Development enrollment

Manual token entry is not part of normal frontend development.

`scripts/start-mobile-dev.ps1` creates an ephemeral development credential, discovers the PC LAN address, starts the services gateway, writes an ignored Expo `.env.local`, synchronizes canonical sound assets, validates TypeScript, and starts Metro.

Release builds must not contain this development credential path as a production enrollment mechanism. Early Alpha and production enrollment remain revocable device-session flows.

## 16. Memory and persistence

Device-local identity, runtime state, and activity are currently implemented on mobile.

Full semantic-memory parity is not complete. Until ported, mobile must label that capability accurately rather than imply the complete desktop MemoryService is present.

Conversation/session persistence should preserve native sender and context-eligibility semantics when implemented.

## 17. Engines

Artificer, Technomancer, Perception, security, diagnostics, and other Engines retain their existing AIDA definitions.

Mobile implementation follows two layers:

1. shared Engine policy/intent/behavior contract
2. Android/iOS platform providers

An Engine must not be renamed, reinterpreted, or given a separate mobile personality. If an Engine feature has no mobile provider yet, its status is STAGED or LIMITED, not simulated.

## 18. Parity review checklist

Before a mobile behavior is considered complete, verify:

- Does the same native AIDA input resolve to the same intent?
- If it reaches the Brain, does it use the canonical AIDA system prompt?
- Does it receive the same recent-context semantics?
- Does displayed wording follow AIDA's native language contract?
- Does a command preserve transcript-versus-speech distinction?
- Are capability claims backed by a deterministic mobile provider?
- Does speech use start tone -> canonical ElevenLabs voice -> end tone?
- Is any substitute operating-system voice prohibited?
- Are utterances serialized?
- Does voice input preserve LISTENING -> PROCESSING -> transcript semantics and delete raw audio?
- Do public statuses use AIDA's canonical state vocabulary?
- Does the orb follow native state/color precedence?
- Are local-only exchanges excluded from Brain context?
- Are provider credentials absent from the mobile artifact?
- Is any platform adaptation explicit rather than silently changing AIDA behavior?

This document is the parity gate for future Android and iOS work.
