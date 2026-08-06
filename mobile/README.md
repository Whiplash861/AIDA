# AIDA Mobile

React Native / Expo frontend for **AIDA — Analytical Intelligent Diagnostic Agent**.

## Local Early Alpha connection

1. Copy the repository root `.env.example` to `.env` and configure Azure OpenAI.
2. Set a long random `AIDA_MOBILE_TOKEN` in the root `.env`.
3. Install either the complete desktop dependencies or the portable bridge-only set:

   ```powershell
   python -m pip install -r requirements-mobile-bridge.txt
   ```

4. Start the local bridge from the repository root:

   ```powershell
   python -m aida.mobile_api
   ```

5. Find the host machine's LAN IPv4 address.
   - Windows: `ipconfig`
   - macOS/Linux: `ifconfig` or `ip addr`
6. Copy `mobile/.env.example` to `mobile/.env.local`.
7. Set `EXPO_PUBLIC_AIDA_API_URL` to `http://<host-ip>:8765`.
8. Set `EXPO_PUBLIC_AIDA_PAIRING_TOKEN` to the same pairing token.
9. Start Expo from `mobile/`:

   ```powershell
   npx expo start
   ```

The phone or tablet and bridge host must be able to reach one another on the local network. Allow inbound access to TCP port `8765` on trusted private networks only. The Early Alpha bridge uses bearer-token pairing over plain local HTTP, so transport encryption and device-bound credentials remain required before public distribution.

## Platform scope

The Expo frontend can be developed from Windows, macOS, or Linux and can run on physical iOS and Android devices. An iOS Simulator requires macOS and Xcode; Windows and Linux development therefore use a physical iPhone or iPad for iOS testing. Android devices and Android emulators can be used from Windows, macOS, or Linux when the Android development tools are installed.

The Python mobile bridge is intentionally separated from the desktop-only dependency set and is designed to run on Windows, macOS, or Linux. The current production desktop application and several diagnostic executors remain Windows-focused because they depend on Microsoft Defender, PowerShell, Windows settings, and Windows navigation providers. macOS and Linux diagnostic providers must be implemented before full desktop-feature parity exists on those operating systems.

## Current mobile scope

Supported now:

- Authenticated text conversation with AIDA's existing reasoning backend
- Read-only desktop subsystem status
- Read-only recent activity
- Compact mobile navigation designed for small screens

Staged next:

- Tasks
- Threat findings
- Memory review
- Artificer review data
- Bug reporting
- Voice capture
- Image and screenshot analysis

Remote desktop commands, system-wide mobile scans, and remote autonomy changes remain disabled until their permission, reauthentication, and confirmation layers are implemented.
