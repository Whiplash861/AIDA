# AIDA Mobile Engine Runtime Architecture

## Purpose

AIDA Mobile organizes named Engine behavior by Engine ownership rather than by a single platform command executor.

The Android and iOS runtimes are platform ports of the same AIDA Engines. A mobile Engine is not a renamed command category and is not a second personality. The Engine retains its existing domain, policy, state model, evidence contract, and authority boundaries. The platform supplies only the providers required to operate on that device.

## Runtime shape

```text
AIDA directive
    |
    +-- native intent resolution
    |
    +-- Engine registry
    |      |
    |      +-- Aegis
    |      +-- Artificer
    |      +-- Technomancer
    |      +-- Perception
    |
    +-- AIDA Core provider registry
           |
           +-- Quickscan
           +-- Performance diagnostics
           +-- Memory
           +-- Navigation
           +-- other non-Engine core capabilities
```

A command may be owned by a named Engine or by AIDA Core. Non-Engine commands must not be assigned to an Engine merely to gain an executor.

## Engine definition

Each mobile Engine defines:

- stable Engine ID and name
- domain
- runtime state (`active`, `limited`, or `staged` at the mobile integration level)
- command types owned by the Engine
- complete subprocess manifest
- authority per subprocess (`observe`, `analyze`, `recommend`, or `execute`)
- provider slot for each subprocess
- optional Engine command executor

The manifest represents architectural readiness. It does not prove that Android or iOS can execute the subprocess.

## Provider registry

A provider registry binds a stable Engine subprocess to a platform implementation.

A subprocess is `staged` until a real implementation is registered. It may become `limited` when only part of the native evidence surface is available. It becomes `supported` only when the provider can deterministically perform its declared contract.

No Engine may report a subprocess as completed unless the registered provider actually ran and returned a result.

## Aegis Android contract

The current Android Aegis manifest is based on the native Aegis Early Alpha / Intelligence architecture and reserves slots for the complete current Engine surface:

### Observation and sensors

- Background Observation
- Security Provider Health
- Process and App Activity Sensor
- Persistence Sensor
- Network Exposure Sensor
- Provider Detection Intake

### Baseline and scanning

- Security Baseline and Drift
- Adaptive Security Scan
- Surface Security Scan
- Deep Security Scan
- Full-System Sweep
- Security Scan Control

### Intelligence and investigation

- Adaptive Candidate Selection
- Targeted Threat Analysis
- Multi-Axis Risk Assessment
- Evidence Coverage Assessment
- Competing Hypotheses
- Evidence Graph
- Security Case Store

### Response and authority

- Response Recommendation
- Remediation Authority Gate
- Threat Stand-Down Policy

### Learning and engineering

- Privacy-Safe Feature Learning
- Versioned Online Model
- Poisoning-Resistant Training Gate
- Artificer Engineering Bridge

These slots mirror the Engine architecture; they do not imply that Android exposes the same evidence as Windows.

## Aegis platform adaptation

Native Windows Aegis injects Windows-specific security-provider health/detection readers and uses a bounded read-only system sensor. Android must preserve the Engine behavior while replacing those providers with Android equivalents.

Examples:

- Windows process image inventory -> Android-visible process/application activity evidence
- Windows Run/Startup persistence -> Android-visible package/service/startup/persistence evidence
- Windows Defender health/detections -> available Android security-provider and platform protection signals
- Windows network listener/process mapping -> permission-available Android connectivity/exposure evidence
- local SQLite case/baseline storage -> device-local mobile storage

Where Android cannot expose equivalent evidence, Aegis must reduce evidence coverage and report uncertainty instead of fabricating parity.

## Aegis state contract

Android Aegis retains the native Engine state model:

- `stopped`
- `observing`
- `investigating`
- `elevated`
- `threat_confirmed`
- `degraded`

A staged provider manifest is not a running Engine. The mobile runtime may enter `observing` only after its required background-observation provider is genuinely available.

## Authority contract

Aegis Early Alpha remains bounded. Porting the Engine to Android does not grant new authority.

Aegis may observe, correlate, investigate, assess, learn within its governed learning contract, build cases, and recommend escalation. Consequential response remains behind AIDA authorization and platform permission boundaries.

Learned inference does not override provider evidence, user authority, or AIDA policy.

## Other Engines

The same pattern applies to:

- **Technomancer** — hardware/device inventory, compatibility health, advisories, upgrade guidance, background technical observation.
- **Artificer** — OS compatibility observation, engineering review, bounded maintenance, consent/telemetry governance, developer registry.
- **Perception** — camera/image/screenshot evidence intake, analysis, and provenance.

Each Engine gains providers independently while retaining a stable manifest and command ownership surface.

## Implementation locations

```text
mobile/src/core/engines/
├── types.ts
├── registry.ts
├── aegis/
│   ├── manifest.ts
│   ├── provider-registry.ts
│   └── runtime.ts
├── artificer/
│   └── manifest.ts
├── technomancer/
│   └── manifest.ts
└── perception/
    └── manifest.ts
```

`mobile/src/core/commands/mobile-command-executor.ts` is now a dispatch boundary rather than the owner of every mobile capability.

## Porting rule

For every future Engine subprocess:

1. identify the authoritative native Engine behavior
2. identify the evidence/provider contract required by that behavior
3. determine the Android/iOS evidence actually available
4. implement the platform provider
5. register it against the existing subprocess slot
6. mark the slot `limited` or `supported` according to real coverage
7. preserve Engine policy, uncertainty reporting, and authority boundaries

This prevents platform ports from becoming independent reinterpretations of AIDA's Engines.
