# Mobile local investigation workflows

These workflows extend the standalone mobile AIDA instance. Existing colors,
styles, layout, and orb presentation are retained. No desktop bridge or services
gateway is needed for these operations.

## Diagnostic follow-through

1. Run `quick scan` or `performance scan` on Android.
2. Type `save baseline` to retain the most recent local diagnostic independently
   of the rolling 30-observation history. This is a chosen comparison point, not
   a declaration that the device is healthy. Saving again replaces that baseline.
3. Type `compare baseline` to compare the latest saved diagnostic, or
   `run follow-up scan` to collect fresh observations before comparison.

The comparison reports storage, battery, power saver, app battery optimization,
connectivity, OS build, and experimental root-indicator changes where both scans
contain comparable values. Missing fields remain unknown. Suggestions are manual
checks in Android Settings; AIDA does not change settings or identify unobserved
processes. A delta does not establish the cause of a symptom or prove a repair.
Baselines require this installation's persistent identity. Imported cases and
images cannot become baselines.

## IMAGE and PASTE

The existing IMAGE control opens the system image picker. A single selected image
is accepted only with a known positive size up to 20 MiB and reported dimensions
up to 40 million pixels. AIDA records local metadata and displays the review in
the existing transcript. It does not retain raw media in its evidence store,
request EXIF/base64, request broad library access, or upload the image. A known
picker-owned cache copy is removed after review; a cleanup failure is reported.
The user's original file is never deleted. The picker itself may perform native
decoding before AIDA receives metadata; the metadata limit is not a sandbox for
the operating system's image decoder.

Mobile OCR and semantic visual interpretation remain unavailable. This is selected
image intake and provenance review, not screenshot diagnosis. Desktop's optional
Windows local OCR remains separately opt-in and requires physical validation.
Desktop OCR review now identifies bounded literal error-code, URL, and path
markers with line references; those observations do not become commands or a
diagnosis, and URLs/paths are not opened.

PASTE reads the clipboard only when pressed. Up to 16,000 characters are reviewed
as untrusted reference text. Literal error codes, URLs, and Windows paths are
shown without opening or executing anything. Pasted text and local attachment
reviews are excluded from cloud conversation context. Clipboard text is not
automatically saved as semantic memory or a directive.

Expo SDK 54 dependencies are `expo-image-picker ~17.0.11` and
`expo-clipboard ~8.0.8`, pinned by the existing lockfile. The picker config blocks
camera and broad Android storage permissions. Existing microphone permission for
push-to-talk remains intact. No camera capture or microphone recording occurs in
the IMAGE flow. A new native binary must include these modules/config changes;
existing installed binaries cannot gain native modules from a JavaScript-only
update.

## Deliberate case transfer

1. Type `export diagnostic case` after a local diagnostic. Review the displayed
   redacted summary and exact JSON. Export allows only selected numeric/boolean
   observations; no raw transcript, image, file path, account, address, credential,
   approval token, or execution plan is included. The source instance ID is shown
   and included so the user can decide whether to share it.
2. Type `copy reviewed case` to put the reviewed JSON on the clipboard. This is an
   explicit disclosure step; operating-system clipboard synchronization is outside
   AIDA's control. AIDA does not send the case over the network.
3. On the destination mobile instance, press PASTE and review the case. Type
   `import reviewed case` to retain it locally or `discard reviewed case` to clear
   the pending review. `show imported case` retrieves the most recently accepted
   imported case. Mobile currently retains one imported reference case; accepting
   another replaces that slot.

Reviews expire after ten minutes. A new paste replaces the pending import review.
Acceptance consumes one immutable reviewed snapshot. Imported cases receive a
local `IMPORT-*` identity while retaining the sender's case/source identifiers as
unverified provenance. They never import local baseline eligibility, device
permissions, approval phrases, or executable authority.

The shared version-1 JSON contract requires `authority: "reference-only"`, bounded
IDs/text, timezone-bearing ISO timestamps, unique evidence IDs, at most 500
evidence entries and 100 entries per text list, and at most 1 MiB serialized UTF-8.
Unknown fields are rejected. Mobile additionally refuses an import whose complete
human-readable review exceeds 32,000 characters; reduce the exported case first.
Python case adapters live in `aida/investigations/service.py`.

## Verification and remaining acceptance

Behavior checks: `node --test mobile/tests/investigation.test.cjs mobile/tests/runtime.test.cjs mobile/tests/report-language.test.cjs`.
Perception checks: `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/test_perception_foundation.py tests/test_perception_indicators.py tests/frontend/test_multimodal_hardening.py`.

This implementation passed 46 mobile behavior tests and 15 perception/frontend
tests. Full `tsc --noEmit --incremental false` passed against an isolated copy of
the complete TypeScript source tree and the same package lock, installed with
`npm ci --ignore-scripts` outside OneDrive. The original checkout compiler stalled
on a synchronous read of an existing `react-native-svg` declaration; its process
was stopped without changing that dependency. A Python/TypeScript version-1 case
round trip also passed. Native device behavior is not established by these tests.

Physical acceptance remains required: Android/iOS system picker selection and
cancellation; cache cleanup on actual picker URIs; clipboard permissions on iOS
and browsers; Android manifest checks after native prebuild; microphone permission
retained after picker config; fresh observations before/after manual Settings
changes; process death/restart persistence; device-to-desktop case transfer in both
directions; and malformed/oversize imports. No real provider calls, microphone
capture, cloud media upload, native build, or deployment were performed for these
local tests.

Primary API references checked before edits:
- [Expo SDK 54](https://docs.expo.dev/versions/v54.0.0/)
- [SDK 54 ImagePicker](https://docs.expo.dev/versions/v54.0.0/sdk/imagepicker/)
- [SDK 54 Clipboard](https://docs.expo.dev/versions/v54.0.0/sdk/clipboard/)

## Reading diagnostic messages

Mobile reports separate observations from checks that could not complete. The
displayed messages use sentence-case descriptions instead of raw INFO, WARNING,
or HIGH prefixes, and explain what was observed, what it can mean, and a practical
next step. Technical gap details remain in saved evidence; the readable report
explains missing results without calling them detected threats. Internal severity
values, coverage calculations, engine states, and permissions are unchanged.

For example, an unavailable root check says that AIDA could not check for
unrestricted system access and suggests retrying or reviewing device settings.
A positive experimental root result still needs review, but it does not establish
that malware is present. Low battery is described as a charging reminder;
connectivity failures explain how to check Wi-Fi or mobile data. The percentage
of checks with results describes how much information was available, not a device
risk score. A limited scan cannot certify that the device is secure.
