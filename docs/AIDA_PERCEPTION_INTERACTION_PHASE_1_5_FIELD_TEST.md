# AIDA Perception and Interaction Phase 1.5 Field Test

## Scope

This pass hardens local image intake and push-to-talk voice capture without enabling wake-word listening, OCR, or visual diagnosis.

## Voice checks

1. Confirm `MICROPHONE READY` on launch.
2. Click **MIC**, speak, then click **STOP**.
3. Confirm `LISTENING -> PROCESSING -> READY`.
4. Confirm the transcript is inserted into the command field and remains editable.
5. Press **Ctrl+Space** to start and stop a second recording.
6. During transcription, click **CANCEL** and confirm no transcript is inserted.
7. Close AIDA while recording and while processing; confirm shutdown completes without an orphaned microphone stream.
8. Test with the microphone disconnected or occupied by another application and verify a specific error appears in Recent Activity.

Voice recordings are uniquely named in the operating-system temporary directory and are deleted after completion, cancellation, failure, or shutdown.

## Image checks

1. Attach multiple supported images with **IMAGE**.
2. Paste a clipboard image with **PASTE**.
3. Drag multiple images onto the window and confirm the composer highlights while hovering.
4. Reattach the same image and confirm the duplicate is ignored.
5. Attach more than five images and confirm the limit is reported.
6. Attach an unsupported or oversized file and confirm an explicit error.
7. Click **CLEAR** and confirm all attachment state and staged clipboard files are removed.
8. Send a mixed text, voice, and image command and confirm the canonical command interface remains usable.

## Regression checks

Verify Report Bug, Memory, Threats, Tasks, Artificer, Autonomy, security observations, memory history, and shutdown behavior remain unchanged.

## Deferred

Wake-word detection, continuous conversation, OCR, region selection, visual model analysis, webcam capture, and direct image handoff to Diagnostics remain outside this phase.
