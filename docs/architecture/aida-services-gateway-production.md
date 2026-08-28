# AIDA Services Gateway — Production / Early Alpha Deployment

## Purpose

AIDA Mobile is a standalone AIDA instance. It must not contain provider secrets and it must not depend on Desktop AIDA being open.

The AIDA Services Gateway is the authenticated provider boundary used by standalone clients for services that cannot safely run with embedded credentials:

- native AIDA intent resolution
- canonical AIDABrain reasoning through Azure OpenAI
- canonical AIDA ElevenLabs speech synthesis
- disposable OpenAI voice transcription

Android device commands are never executed by the gateway. A resolved directive returns to the Android runtime and may execute only through an Android-local deterministic provider.

## Why the Play build currently reports reasoning as disconnected

A development session receives a temporary LAN gateway URL and bearer token from `scripts/start-mobile-dev.ps1`. A Play-installed application does not receive those development values.

Without an enrolled gateway URL and credential, mobile intentionally falls back to its bounded local runtime provider. The same condition also prevents ElevenLabs speech and provider-backed voice transcription. The canonical start/end WAV cues remain local, which is why they can still play.

## Container image

The repository root `Dockerfile` packages only the headless AIDA Services Gateway runtime. Desktop-only packages such as PySide, local audio playback, and sound-device libraries are not required by the container.

The image listens on port `8000` and starts:

```text
python -m aida.services_gateway
```

## Required production configuration

The following values must be configured on the trusted gateway host. They must never be committed to GitHub or embedded in an Android/iOS bundle.

| Environment variable | Purpose | Secret? |
| --- | --- | --- |
| `AZURE_OPENAI_ENDPOINT` | AIDABrain Azure OpenAI endpoint | Treat as service configuration |
| `AZURE_OPENAI_API_KEY` | AIDABrain provider credential | Yes |
| `AZURE_OPENAI_API_VERSION` | Azure OpenAI API version | No |
| `AZURE_OPENAI_DEPLOYMENT` | AIDABrain deployment name | No |
| `ELEVENLABS_API_KEY` | Canonical AIDA speech provider credential | Yes |
| `ELEVENLABS_VOICE_ID` | Canonical AIDA voice ID | Treat as private configuration |
| `OPENAI_API_KEY` | Disposable voice transcription credential | Yes |
| `AIDA_TRANSCRIPTION_MODEL` | Transcription model selector | No |
| `AIDA_SERVICES_GATEWAY_TOKEN` | Early Alpha gateway bearer credential | Yes |

For Early Alpha, `AIDA_SERVICES_GATEWAY_TOKEN` is a long random revocable enrollment credential. It is stored server-side as a secret and, after manual enrollment, in Android SecureStore. It is not an `EXPO_PUBLIC_*` value and is not compiled into the APK.

A later release should replace the shared Early Alpha bearer credential with invitation/account exchange and per-device revocable session credentials before broader distribution.

## Azure Container Apps deployment

Azure Container Apps is the initial production host because it provides managed HTTPS ingress, secret-backed runtime environment variables, revisions, logs, and scale-to-zero support.

### 1. Prerequisites

Install/sign in to Azure CLI and add/update the Container Apps extension:

```powershell
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

Run deployment commands from the AIDA repository root after pulling the gateway changes.

### 2. Create the app from repository source

Example Early Alpha resource names:

```powershell
$ResourceGroup = "aida-labs-alpha"
$Environment = "aida-labs-alpha-env"
$AppName = "aida-services-alpha"
$Location = "eastus"

az containerapp up `
  --name $AppName `
  --resource-group $ResourceGroup `
  --location $Location `
  --environment $Environment `
  --source . `
  --ingress external
```

`az containerapp up` uses the root Dockerfile, builds/pushes the image, creates/reuses the Container Apps resources, and exposes the app. The Dockerfile `EXPOSE 8000` instruction identifies the target port.

Do not enable insecure HTTP ingress. The mobile production boundary must use the generated HTTPS FQDN.

### 3. Configure secrets

Create a long random Early Alpha gateway token locally. Do not paste it into chat, GitHub, issue trackers, screenshots, or source files.

Store provider credentials and the gateway token as Container App secrets. Example secret names:

```text
azure-openai-key
elevenlabs-key
openai-transcription-key
aida-gateway-token
```

The Azure portal may be used under the Container App's Secrets section, or Azure CLI may be used with values held in local PowerShell variables.

Then map the secret values to runtime environment variables with `secretref:` references. Non-secret service configuration can be set directly.

Example shape:

```powershell
az containerapp update `
  --name $AppName `
  --resource-group $ResourceGroup `
  --set-env-vars `
    AZURE_OPENAI_ENDPOINT="$env:AZURE_OPENAI_ENDPOINT" `
    AZURE_OPENAI_API_KEY=secretref:azure-openai-key `
    AZURE_OPENAI_API_VERSION="$env:AZURE_OPENAI_API_VERSION" `
    AZURE_OPENAI_DEPLOYMENT="$env:AZURE_OPENAI_DEPLOYMENT" `
    ELEVENLABS_API_KEY=secretref:elevenlabs-key `
    ELEVENLABS_VOICE_ID="$env:ELEVENLABS_VOICE_ID" `
    OPENAI_API_KEY=secretref:openai-transcription-key `
    AIDA_TRANSCRIPTION_MODEL="gpt-4o-mini-transcribe" `
    AIDA_SERVICES_GATEWAY_TOKEN=secretref:aida-gateway-token
```

Do not run the example until the referenced Container App secrets exist.

### 4. Verify gateway readiness

Get the HTTPS FQDN:

```powershell
$Fqdn = az containerapp show `
  --name $AppName `
  --resource-group $ResourceGroup `
  --query properties.configuration.ingress.fqdn `
  -o tsv

"https://$Fqdn"
```

The public health endpoint should return the service and readiness flags:

```powershell
Invoke-RestMethod -Uri "https://$Fqdn/health"
```

Before enrolling a phone, expected Early Alpha readiness is:

```text
reasoning_configured: true
speech_configured: true
transcription_configured: true
intent_resolution_configured: true
```

The authenticated readiness endpoint can be tested locally without exposing the token in source:

```powershell
$Headers = @{ Authorization = "Bearer $GatewayToken" }
Invoke-RestMethod -Uri "https://$Fqdn/v1/ready" -Headers $Headers
```

## Connect the existing Play-installed AIDA build

The current Early Alpha Android runtime already supports manual gateway enrollment, so a new AAB is not required merely to test the hosted provider boundary.

On the phone:

1. Open AIDA.
2. Open **Control**.
3. Under **AIDA Services Gateway**, enter the generated HTTPS URL.
4. Enter the Early Alpha gateway credential.
5. Select **Enroll Gateway**.

The app probes `/v1/ready` before saving enrollment. The URL is stored in device-local application storage and the bearer credential is stored in Expo SecureStore.

After enrollment, verify:

- Brain reports `IDLE` rather than `STAGED`/disconnected.
- An ordinary language question is answered by canonical AIDABrain.
- A registered command is resolved by AIDA's native intent resolver and returned for Android-local execution.
- A response plays `aida_start.wav`, then the canonical ElevenLabs AIDA voice, then `aida_end.wav`.
- Voice Input reports ready and a user-initiated microphone recording can be transcribed.
- Temporary recording/audio files are discarded after processing/playback.

## Future mobile builds

`EXPO_PUBLIC_AIDA_GATEWAY_URL` may contain the production HTTPS service URL so Control can pre-fill it. This is safe because the URL is public configuration.

No credential may be placed in `EXPO_PUBLIC_AIDA_GATEWAY_TOKEN` or any other public Expo variable. Provider credentials and gateway enrollment/session secrets must remain outside the APK.

## Scaling

For a small Early Alpha, Container Apps may use `minReplicas = 0` to reduce idle cost. The first request after scale-to-zero can have a cold-start delay. If that delay harms voice/reasoning UX, set the minimum replica count to `1` during active field testing.

## Release boundary

AIDA's application version and the Services Gateway can evolve independently, but protocol changes must preserve compatibility with supported Play builds. Before changing or removing `/v1/ready`, `/v1/resolve`, `/v1/reasoning`, `/v1/speech`, or `/v1/transcription`, add a versioned migration path or confirm that all supported clients have been upgraded.
