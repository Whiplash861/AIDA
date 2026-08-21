# AIDA Mobile — Standalone Early Alpha

React Native / Expo frontend and mobile runtime for **AIDA — Analytical Intelligent Diagnostic Agent**.

## Current development target

AIDA Mobile is being developed as an independent AIDA instance rather than a remote frontend for Desktop AIDA.

The current Expo Go milestone initializes a device-local runtime that:

- recognizes the host platform and Android version
- creates a local session instance identity
- maintains local runtime and subsystem status
- exposes a local capability registry
- records local runtime activity
- accepts basic local directives without contacting Desktop AIDA
- preserves AIDA's Precision Glass visual identity and live-state orb

Full language-model reasoning, durable encrypted mobile memory, deeper Android diagnostics, native notifications, microphone, camera, and Engine implementations are staged for later milestones.

## Run in Expo Go

From the repository root, switch to the standalone mobile branch and enter the mobile project:

```powershell
git switch feature/aida-mobile-standalone-alpha
cd mobile
```

Install the JavaScript dependencies if needed:

```powershell
npm install
```

Start Expo:

```powershell
npx expo start
```

On the Android device:

1. Keep the computer and phone on the same reachable network when using LAN mode.
2. Open **Expo Go**.
3. Scan the QR code shown by Expo.
4. AIDA Mobile should initialize directly on the phone.

No Desktop AIDA process, FastAPI mobile bridge, Azure key, or mobile pairing token is required for this standalone UI/runtime milestone.

## What to test first

On the AIDA home screen, confirm that:

- the interface identifies the device as Android
- the orb and Precision Glass theme render correctly
- the runtime reports `STANDBY`
- the communication feed says the local runtime is online
- entering `status`, `platform`, `capabilities`, or `hello` returns a local runtime response
- the **Systems** tab reports the mobile instance rather than a desktop host
- the **Activity** tab contains local runtime bootstrap events
- the **Control** tab describes mobile systems and Engines without desktop dependency language

## Architecture direction

The mobile runtime will evolve toward:

```text
AIDA Mobile UI
      |
Mobile Runtime
      |
+-----+------------------+
|     |                  |
Memory / Engines / Policy
      |
Capability Registry
      |
Android Provider
      |
Android OS
```

The existing `aida/mobile_api` bridge remains in the repository as transitional code and may later become an optional trusted-device pairing path. It is not the primary runtime architecture for standalone AIDA Mobile.

## Reasoning security

Production Azure/OpenAI credentials must never be embedded in the Android application. Independent cloud reasoning will use a secure authenticated AIDA reasoning gateway or another provider architecture that keeps privileged service credentials off the device.

## Version

Current application milestone:

```text
AIDA Mobile 0.1.0 Early Alpha
```

The permanent Android application/package identifier must be deliberately selected before the first Google Play artifact is created.
