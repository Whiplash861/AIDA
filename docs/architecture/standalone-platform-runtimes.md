# AIDA Standalone Platform Runtimes

## Decision

AIDA will become a family of independent device runtimes rather than a single Windows runtime with remote clients.

Every supported device must remain useful when every other AIDA instance is offline. Synchronization between instances is optional and must never be required for conversation, local memory, local diagnostics, or normal user interaction.

## Definition of an AIDA instance

An AIDA instance is one device-local runtime with its own:

- device identity
- capability registry
- local permissions and authorization state
- local memory and activity history
- local diagnostic providers
- reasoning connection
- user interface
- audit trail
- autonomy scope

An instance may exchange selected data with other trusted instances, but it must not depend on another instance for its core operation.

## Architectural invariants

1. **Local-first operation**
   - Each device owns its local state and can operate without another AIDA device.

2. **Capability honesty**
   - Each runtime advertises only capabilities that the current operating system and granted permissions genuinely support.
   - Unsupported actions fail explicitly; AIDA never fabricates execution results.

3. **Shared behavior, platform-specific execution**
   - Identity, policy, schemas, prompts, status language, and safety rules are shared.
   - Diagnostics, navigation, microphone, camera, storage, notifications, and system integration are implemented by platform providers.

4. **No embedded service secrets in distributed clients**
   - Mobile and packaged desktop clients must not contain raw Azure OpenAI or other privileged service keys.
   - Production reasoning access will use a user-authenticated broker, delegated token, or a user-configured local provider.

5. **Per-device authority**
   - Autonomy and approvals are scoped to the device on which they were granted.
   - One AIDA instance cannot silently expand another instance's authority.

6. **Optional synchronization**
   - Memory, tasks, findings, and preferences sync only after explicit opt-in.
   - Sync conflicts preserve both records until safely reconciled.

## Runtime layers

### 1. AIDA Core Specification

Platform-neutral contracts shared by all runtimes:

- identity and terminology
- request and response schemas
- capability manifests
- status and activity models
- memory record types
- task and finding models
- authorization and confirmation rules
- audit-event schemas
- reasoning-provider interface
- synchronization protocol

The specification is the source of behavioral consistency. It does not assume Python, TypeScript, Windows, or a particular UI toolkit.

### 2. Runtime Host

The device-local coordinator responsible for:

- startup and shutdown
- provider discovery
- capability registration
- local state storage
- reasoning requests
- task scheduling
- status publication
- policy enforcement
- audit logging

### 3. Platform Providers

Providers implement capabilities for one operating-system family.

Initial provider families:

- `windows`
- `macos`
- `linux`
- `ios`
- `android`
- `web_chromeos`

Typical provider contracts:

- system information
- performance telemetry
- security-provider integration
- file and storage access
- navigation and settings
- microphone and speech
- camera and image intake
- notifications
- background execution
- network state

### 4. Local Store

Each instance receives an isolated data directory containing:

- instance identity
- encrypted user settings
- local memory database
- tasks
- findings
- activity history
- approvals and authorizations
- provider state
- local logs

No device writes directly into another device's local store.

### 5. Optional AIDA Mesh

The future mesh layer allows trusted instances to discover and synchronize with each other.

The mesh is not a control plane and is not required for ordinary use. It may support:

- encrypted memory synchronization
- task handoff
- finding replication
- device presence
- cross-device notifications
- user-approved remote requests

All consequential remote operations require target-device authorization and confirmation.

## Runtime implementations

AIDA will share contracts across platforms, but not necessarily one executable implementation.

### Python desktop runtime

Primary targets:

- Windows
- macOS
- Linux

The existing Python runtime will be refactored so portable core services do not import Windows providers. The runtime will select providers through a capability registry.

### React Native mobile runtime

Primary targets:

- iPhone and iPad
- Android phones and tablets
- supported Chromebook Android environments

The mobile runtime will contain its own local store, capability registry, reasoning client, status engine, activity feed, task model, and permission-aware diagnostic providers. It will no longer require a desktop bridge for normal operation.

### Web/PWA runtime

Primary targets:

- Chromebook
- browser-accessible fallback environments

The web runtime will expose only browser-permitted capabilities. It remains a valid independent AIDA instance, but its capability manifest will be narrower than native runtimes.

## Reasoning independence

Device independence does not automatically mean offline reasoning.

Initial standalone instances may use a network reasoning provider, but each instance must authenticate independently and must not route through another user's desktop process.

Supported provider strategy:

1. user-authenticated AIDA reasoning gateway for distributed builds
2. direct user-supplied provider configuration for developer and advanced-user builds
3. optional local-model provider where hardware and packaging permit

The reasoning-provider interface must allow these choices without changing the rest of the runtime.

## Platform scope

### Windows

Existing mature runtime. Windows-specific diagnostics become providers rather than imports in portable core modules.

### iOS/iPadOS

Standalone native mobile runtime with permission-limited diagnostics, local memory, voice, image intake, notifications, and independent reasoning authentication. It will not claim unrestricted process, filesystem, or antivirus control.

### macOS

Standalone desktop runtime using the portable Python core plus macOS providers for system telemetry, security posture, navigation, permissions, notifications, and local storage.

### Linux

Standalone desktop runtime using the portable Python core plus distribution-aware providers. Provider availability will be discovered at runtime rather than assumed.

### Chromebook / ChromeOS

Two supported paths are planned:

- Android application where available
- web/PWA runtime as the broad compatibility baseline

A Linux-container build may be supported for advanced users, but it will be treated as a Linux instance rather than a native ChromeOS authority.

## Repository target structure

```text
aida/
  core/
    capabilities/
    contracts/
    policy/
    reasoning/
    runtime/
    storage/
    sync/
  providers/
    windows/
    macos/
    linux/
  desktop/
    frontend/

mobile/
  src/
    core/
      capabilities/
      contracts/
      policy/
      reasoning/
      runtime/
      storage/
    providers/
      ios/
      android/
      web/
    features/
    ui/

schemas/
  capability-manifest.schema.json
  operational-status.schema.json
  activity-event.schema.json
  memory-record.schema.json
  task.schema.json
```

Shared JSON schemas will prevent the Python and TypeScript implementations from drifting.

## Migration plan

### Phase 1 — Runtime contracts

- define instance identity
- define capability manifest
- define reasoning-provider interface
- define local runtime status
- define platform-provider protocol
- add contract tests

### Phase 2 — Detach Windows from the core

- move Defender, PowerShell, Windows settings, and Windows navigation behind providers
- ensure portable core imports on Windows, macOS, and Linux
- preserve existing Windows behavior

### Phase 3 — Standalone mobile foundation

- replace desktop-bridge-only assumptions
- add mobile local store
- add mobile instance identity
- add independent reasoning authentication
- add mobile capability registry
- retain the bridge as an optional paired-device feature

### Phase 4 — Native mobile capabilities

- iOS and Android system information
- permission-aware device health
- battery and network state
- microphone and voice
- camera, screenshots, and image analysis
- local notifications
- mobile task execution

### Phase 5 — macOS and Linux providers

- system telemetry
- process and storage diagnostics
- security-provider discovery
- platform navigation
- notifications and background services

### Phase 6 — Optional encrypted synchronization

- device enrollment
- trust relationships
- selective memory and task sync
- conflict handling
- remote-request approvals

## First implementation milestone

Create the platform-neutral runtime contracts without changing current Windows or mobile behavior:

- `InstanceIdentity`
- `CapabilityDescriptor`
- `CapabilityManifest`
- `RuntimeContext`
- `ReasoningProvider`
- `PlatformProvider`
- serialization tests shared by Python and TypeScript fixtures

This milestone provides the seam required to turn the existing Windows application and current mobile client into independent AIDA instances safely.
