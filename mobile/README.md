# AIDA Mobile

React Native / Expo frontend for **AIDA — Analytical Intelligent Diagnostic Agent**.

## Local Early Alpha connection

1. Copy the repository root `.env.example` to `.env` and configure Azure OpenAI.
2. Set a long random `AIDA_MOBILE_TOKEN` in the root `.env`.
3. Start the local bridge from the repository root:

   ```powershell
   python -m aida.mobile_api
   ```

4. Find the desktop's LAN IPv4 address with `ipconfig`.
5. Copy `mobile/.env.example` to `mobile/.env.local`.
6. Set `EXPO_PUBLIC_AIDA_API_URL` to `http://<desktop-ip>:8765`.
7. Set `EXPO_PUBLIC_AIDA_PAIRING_TOKEN` to the same pairing token.
8. Start Expo from `mobile/`:

   ```powershell
   npx expo start
   ```

The iPhone or iPad and desktop must be able to reach one another on the local network. Windows may ask for firewall permission when the bridge first starts; allow private networks only. The Early Alpha bridge uses bearer-token pairing over plain local HTTP, so test it only on a trusted private network. Transport encryption and device-bound credentials are required before public distribution.

## Current scope

The mobile bridge supports authenticated text conversation with AIDA's existing reasoning backend. Remote desktop commands, system-wide mobile scans, voice capture, and image analysis remain disabled until their permission and authorization layers are implemented.
