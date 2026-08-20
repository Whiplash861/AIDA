# AIDA Perception and Interaction Phase 1

## Scope

Phase 1 adds multimodal intake to the canonical Artificer-enabled frontend without replacing the existing command interface.

Implemented foundations:

- Push-to-talk microphone capture.
- Asynchronous transcription into the editable command field.
- Seamless continuation through typed input.
- Image selection and drag-and-drop attachment.
- Local-only evidence hashing and metadata.
- Explicit Perception and Microphone dashboard states.
- Separation between observed, extracted, inferred, and unknown evidence.

## Safety and privacy

The Perception subsystem produces evidence; it does not diagnose. Image bytes remain local in Phase 1. Attached evidence is represented to downstream systems by local metadata and a SHA-256 digest. Voice audio is written to the operating-system temporary directory and is not promoted into AIDA memory.

Transcription is optional and requires `OPENAI_API_KEY`. The model defaults to `gpt-4o-mini-transcribe` and can be overridden with `AIDA_TRANSCRIPTION_MODEL`.

## Deferred

- Always-listening wake word.
- Continuous conversation mode.
- OCR and visual interpretation.
- Camera and webcam capture.
- Region highlighting.
- Automatic deletion policy for temporary audio beyond operating-system cleanup.

These are intentionally deferred until microphone ownership, cancellation, and interruption behavior have passed field testing.
