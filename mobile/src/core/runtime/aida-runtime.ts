import Constants from 'expo-constants';
import { Platform } from 'react-native';

import { executeMobileRoutedDirective } from '@/src/core/commands/mobile-command-executor';
import { speakAidaText, testAidaSpeech } from '@/src/core/interaction/speech-output';
import { MOBILE_REASONING } from '@/src/core/reasoning/service';
import {
  loadActivity,
  loadOrCreateInstanceId,
  loadRuntimeState,
  saveActivity,
  saveRuntimeState,
} from '@/src/core/storage/mobile-storage';

export type StatusTone = 'ready' | 'active' | 'warning' | 'error' | 'idle' | 'offline';
export type LocalRuntimeStatus =
  | 'STARTING'
  | 'STANDBY'
  | 'LISTENING'
  | 'ANALYZING'
  | 'SPEAKING'
  | 'WARNING'
  | 'ERROR'
  | 'SHUTDOWN';

export type SubsystemStatus = { id: string; label: string; value: string; tone: StatusTone };
export type RuntimeCapability = {
  id: string;
  label: string;
  state: 'supported' | 'limited' | 'staged';
  detail: string;
};
export type RuntimeActivityItem = {
  id: string;
  category: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
  source: string;
  created_at: string;
};
export type MobileRuntimeSnapshot = {
  instance_id: string;
  identity_persistent: boolean;
  runtime_mode: 'standalone';
  status: LocalRuntimeStatus;
  platform: string;
  platform_version: string;
  device_model: string;
  app_version: string;
  initialized_at: string;
  updated_at: string;
  speech_enabled: boolean;
  autonomy: { enabled: boolean; label: string };
  statuses: SubsystemStatus[];
  capabilities: RuntimeCapability[];
};

export type DirectiveSubmissionResult = {
  text: string;
  speechText: string;
  includeInContext: boolean;
  localOnly: boolean;
  routeIntentId: string;
};

type RuntimeListener = (snapshot: MobileRuntimeSnapshot) => void;
type ActivityListener = (items: RuntimeActivityItem[]) => void;

let snapshot = createStartingSnapshot();
let activity: RuntimeActivityItem[] = [];
let initialization: Promise<MobileRuntimeSnapshot> | null = null;
const runtimeListeners = new Set<RuntimeListener>();
const activityListeners = new Set<ActivityListener>();

export function getRuntimeSnapshot(): MobileRuntimeSnapshot {
  void initializeAidaRuntime();
  return snapshot;
}

export async function initializeAidaRuntime(): Promise<MobileRuntimeSnapshot> {
  if (initialization) return initialization;
  initialization = hydrateRuntime();
  return initialization;
}

export function getRuntimeActivity(limit = 30): RuntimeActivityItem[] {
  void initializeAidaRuntime();
  return activity.slice(0, Math.max(1, Math.min(100, Math.trunc(limit))));
}

export function subscribeRuntime(listener: RuntimeListener): () => void {
  runtimeListeners.add(listener);
  listener(snapshot);
  void initializeAidaRuntime();
  return () => runtimeListeners.delete(listener);
}

export function subscribeRuntimeActivity(listener: ActivityListener): () => void {
  activityListeners.add(listener);
  listener([...activity]);
  void initializeAidaRuntime();
  return () => activityListeners.delete(listener);
}

export async function configureServicesGateway(baseUrl: string, token: string): Promise<void> {
  await initializeAidaRuntime();
  await MOBILE_REASONING.configureGateway(baseUrl, token);
  const gateway = MOBILE_REASONING.gatewayRuntimeState();
  snapshot = {
    ...snapshot,
    updated_at: new Date().toISOString(),
    statuses: snapshot.statuses.map((item) => {
      if (item.id === 'brain') {
        return { ...item, value: 'IDLE', tone: 'ready' as const };
      }
      if (item.id === 'microphone') {
        return {
          ...item,
          value: gateway.transcriptionConfigured ? 'READY' : 'STAGED',
          tone: gateway.transcriptionConfigured ? ('ready' as const) : ('idle' as const),
        };
      }
      return item;
    }),
    capabilities: buildCapabilities(
      snapshot.platform,
      true,
      gateway.speechConfigured,
      gateway.transcriptionConfigured,
      gateway.source,
    ),
  };
  notifyRuntime();
  await addActivity(
    'GATEWAY',
    'Authenticated AIDA services gateway enrolled for this mobile instance.',
    'info',
    'mobile.reasoning',
  );
}

export async function setSpeechEnabled(enabled: boolean): Promise<void> {
  await initializeAidaRuntime();
  snapshot = {
    ...snapshot,
    speech_enabled: enabled,
    updated_at: new Date().toISOString(),
    statuses: snapshot.statuses.map((item) =>
      item.id === 'speech'
        ? { ...item, value: enabled ? 'TESTING' : 'MUTED', tone: enabled ? 'active' : 'idle' }
        : item,
    ),
  };
  notifyRuntime();
  await saveRuntimeState({
    autonomy_enabled: snapshot.autonomy.enabled,
    speech_enabled: enabled,
  });
  await addActivity(
    'SPEECH',
    enabled ? 'AIDA speech output enabled.' : 'AIDA speech output muted.',
    'info',
    'mobile.speech',
  );

  if (!enabled) {
    setRuntimeStatus('STANDBY', 'ready');
    return;
  }

  const transport = await testAidaSpeech({
    onStart: () => {
      setRuntimeStatus('SPEAKING', 'active');
      setSubsystemStatus('speech', 'SPEAKING', 'active');
    },
    onDone: () => {
      setSubsystemStatus('speech', 'READY', 'ready');
      setRuntimeStatus('STANDBY', 'ready');
    },
    onWarning: (message) => {
      void addActivity('SPEECH', message, 'warning', 'mobile.speech');
    },
    onError: (message) => {
      setSubsystemStatus('speech', 'ERROR', 'warning');
      void addActivity('SPEECH', `Speech self-test failed: ${message}`, 'warning', 'mobile.speech');
    },
  });
  await addActivity(
    'SPEECH',
    `Speech self-test completed through ${transport}.`,
    transport === 'silent' ? 'warning' : 'info',
    'mobile.speech',
  );
}

export async function beginVoiceListening(): Promise<void> {
  await initializeAidaRuntime();
  setRuntimeStatus('LISTENING', 'active');
  setSubsystemStatus('microphone', 'LISTENING', 'active');
  await addActivity(
    'VOICE',
    'Microphone capture started.',
    'info',
    'mobile.voice',
  );
}

export async function beginVoiceProcessing(): Promise<void> {
  await initializeAidaRuntime();
  setRuntimeStatus('ANALYZING', 'active');
  setSubsystemStatus('microphone', 'PROCESSING', 'active');
  await addActivity(
    'VOICE',
    'Disposable microphone recording submitted for transcription.',
    'info',
    'mobile.voice',
  );
}

export async function completeVoiceInput(): Promise<void> {
  await initializeAidaRuntime();
  setSubsystemStatus('microphone', 'READY', 'ready');
  setRuntimeStatus('STANDBY', 'ready');
  await addActivity(
    'VOICE',
    'Voice transcription completed. Temporary recording discarded.',
    'info',
    'mobile.voice',
  );
}

export async function failVoiceInput(message: string): Promise<void> {
  await initializeAidaRuntime();
  const clean = message.trim() || 'Voice input failed.';
  setSubsystemStatus('microphone', 'ERROR', 'warning');
  await addActivity('VOICE', clean, 'error', 'mobile.voice');
  const gateway = MOBILE_REASONING.gatewayRuntimeState();
  setSubsystemStatus(
    'microphone',
    gateway.transcriptionConfigured ? 'READY' : 'STAGED',
    gateway.transcriptionConfigured ? 'ready' : 'idle',
  );
  setRuntimeStatus('STANDBY', 'ready');
}

export async function submitLocalDirective(
  message: string,
  conversationContext: string[] = [],
): Promise<DirectiveSubmissionResult> {
  await initializeAidaRuntime();
  const clean = message.trim();
  if (!clean) throw new Error('Directive cannot be empty.');

  const remote = MOBILE_REASONING.isRemoteConfigured();
  setAgentState('ANALYZING', remote ? 'ANALYZING' : 'STAGED', 'active');
  await addActivity('DIRECTIVE', 'Directive received.', 'info', 'mobile.runtime');

  try {
    const response = await MOBILE_REASONING.respond(clean, {
      platform: snapshot.platform,
      platformVersion: snapshot.platform_version,
      deviceModel: snapshot.device_model,
      instanceId: snapshot.instance_id,
      supportedCapabilities: snapshot.capabilities
        .filter((item) => item.state === 'supported')
        .map((item) => item.label),
      conversationContext: conversationContext.slice(-12),
    });

    if (response.mode === 'routed' && response.routedDirective) {
      const command = await executeMobileRoutedDirective(response.routedDirective, {
        platform: snapshot.platform,
      });
      await addActivity(
        'COMMAND',
        command.executed
          ? `Resolved intent ${response.routedDirective.intentId || response.routedDirective.commandType} completed through the mobile executor.`
          : `Resolved intent ${response.routedDirective.intentId || response.routedDirective.commandType} has no Android executor.`,
        command.executed ? 'info' : 'warning',
        'mobile.commands',
      );
      setAgentState('STANDBY', 'IDLE', 'ready');
      void speakResponseIfEnabled(command.speechText);
      return {
        text: command.transcriptText,
        speechText: command.speechText,
        includeInContext: command.includeInContext,
        localOnly: response.routedDirective.localOnly,
        routeIntentId: response.routedDirective.intentId,
      };
    }

    await addActivity(
      'AIDA',
      `Response generated by ${response.provider} (${response.mode}).`,
      'info',
      response.provider,
    );
    setAgentState(
      'STANDBY',
      response.mode === 'remote' ? 'IDLE' : 'STAGED',
      'ready',
    );
    void speakResponseIfEnabled(response.text);
    return {
      text: response.text,
      speechText: response.text,
      includeInContext: true,
      localOnly: false,
      routeIntentId: '',
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'AIDA brain request failed.';
    setAgentState('STANDBY', 'ERROR', 'ready');
    await addActivity('BRAIN', `AIDA brain request failed: ${message}`, 'error', 'mobile.reasoning');
    throw error;
  }
}

async function hydrateRuntime(): Promise<MobileRuntimeSnapshot> {
  const platform = platformLabel();
  const model = deviceModel();
  try {
    const [identity, state, storedActivity] = await Promise.all([
      loadOrCreateInstanceId(Platform.OS),
      loadRuntimeState(),
      loadActivity<RuntimeActivityItem>(),
    ]);
    await MOBILE_REASONING.initialize();

    activity = storedActivity.slice(0, 100);
    const gatewayReady = MOBILE_REASONING.isRemoteConfigured();
    const gateway = MOBILE_REASONING.gatewayRuntimeState();
    const now = new Date().toISOString();
    const brainValue = gatewayReady
      ? 'IDLE'
      : gateway.configured && gateway.error
        ? 'ERROR'
        : 'STAGED';
    const brainTone: StatusTone = gatewayReady
      ? 'ready'
      : gateway.configured && gateway.error
        ? 'warning'
        : 'idle';

    snapshot = {
      instance_id: identity.instanceId,
      identity_persistent: true,
      runtime_mode: 'standalone',
      status: 'STANDBY',
      platform,
      platform_version: String(Platform.Version),
      device_model: model,
      app_version: Constants.expoConfig?.version ?? '0.1.0',
      initialized_at: now,
      updated_at: now,
      speech_enabled: state.speech_enabled,
      autonomy: {
        enabled: state.autonomy_enabled,
        label: state.autonomy_enabled ? 'ENABLED' : 'LOCAL SAFE MODE',
      },
      statuses: [
        status('agent', 'AGENT', 'STANDBY', 'ready'),
        status('brain', 'BRAIN', brainValue, brainTone),
        status('speech', 'SPEECH', state.speech_enabled ? 'READY' : 'MUTED', state.speech_enabled ? 'ready' : 'idle'),
        status('diagnostics', 'DIAGNOSTICS', 'READY', 'ready'),
        status('memory', 'MEMORY', 'READY', 'ready'),
        status('artificer', 'ARTIFICER', 'STAGED', 'idle'),
        status('technomancer', 'TECHNOMANCER', 'STAGED', 'idle'),
        status('perception', 'PERCEPTION', 'STAGED', 'idle'),
        status(
          'microphone',
          'MICROPHONE',
          gateway.transcriptionConfigured ? 'READY' : 'STAGED',
          gateway.transcriptionConfigured ? 'ready' : 'idle',
        ),
        status('tasks', 'TASKS', '0 ACTIVE', 'idle'),
        status('platform', 'PLATFORM', platform.toUpperCase(), 'ready'),
      ],
      capabilities: buildCapabilities(
        platform,
        gatewayReady,
        gateway.speechConfigured,
        gateway.transcriptionConfigured,
        gateway.source,
      ),
    };

    await addActivity(
      'RUNTIME',
      identity.created
        ? `Created persistent AIDA instance ${identity.instanceId} on ${platform} ${String(Platform.Version)} (${model}).`
        : `Restored persistent AIDA instance ${identity.instanceId} on ${platform} ${String(Platform.Version)} (${model}).`,
      'info',
      'mobile.runtime',
    );
    if (gateway.source === 'development' && gatewayReady) {
      await addActivity(
        'GATEWAY',
        'Development services gateway auto-enrolled for this Expo session.',
        'info',
        'mobile.reasoning',
      );
    } else if (gateway.configured && gateway.error) {
      await addActivity(
        'GATEWAY',
        gateway.error,
        'warning',
        'mobile.reasoning',
      );
    }
    notifyRuntime();
    return snapshot;
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'Unknown storage error';
    snapshot = {
      ...snapshot,
      status: 'WARNING',
      updated_at: new Date().toISOString(),
      statuses: snapshot.statuses.map((item) =>
        item.id === 'memory'
          ? { ...item, value: 'DEGRADED', tone: 'warning' as const }
          : item.id === 'agent'
            ? { ...item, value: 'WARNING', tone: 'warning' as const }
            : item,
      ),
    };
    await addActivity(
      'STORAGE',
      `Persistent mobile storage initialization failed: ${detail}`,
      'warning',
      'mobile.storage',
      false,
    );
    notifyRuntime();
    return snapshot;
  }
}

async function speakResponseIfEnabled(text: string) {
  if (!snapshot.speech_enabled || !text.trim()) return;
  const transport = await speakAidaText(text, {
    onStart: () => {
      setRuntimeStatus('SPEAKING', 'active');
      setSubsystemStatus('speech', 'SPEAKING', 'active');
    },
    onDone: () => {
      setSubsystemStatus('speech', 'READY', 'ready');
      setRuntimeStatus('STANDBY', 'ready');
    },
    onWarning: (message) => {
      void addActivity('SPEECH', message, 'warning', 'mobile.speech');
    },
    onError: (message) => {
      setSubsystemStatus('speech', 'ERROR', 'warning');
      void addActivity('SPEECH', `Speech output failed: ${message}`, 'warning', 'mobile.speech');
    },
  });
  void addActivity(
    'SPEECH',
    `Response speech completed through ${transport}.`,
    transport === 'silent' ? 'warning' : 'info',
    'mobile.speech',
  );
}

function setRuntimeStatus(next: LocalRuntimeStatus, agentTone: StatusTone) {
  snapshot = {
    ...snapshot,
    status: next,
    updated_at: new Date().toISOString(),
    statuses: snapshot.statuses.map((item) =>
      item.id === 'agent' ? { ...item, value: next, tone: agentTone } : item,
    ),
  };
  notifyRuntime();
}

function setSubsystemStatus(id: string, value: string, tone: StatusTone) {
  snapshot = {
    ...snapshot,
    updated_at: new Date().toISOString(),
    statuses: snapshot.statuses.map((item) =>
      item.id === id ? { ...item, value, tone } : item,
    ),
  };
  notifyRuntime();
}

function buildCapabilities(
  platform: string,
  gatewayReady: boolean,
  speechConfigured: boolean,
  transcriptionConfigured: boolean,
  gatewaySource: 'development' | 'enrolled' | 'none',
): RuntimeCapability[] {
  return [
    {
      id: 'runtime.local',
      label: 'Local AIDA runtime',
      state: 'supported',
      detail: 'AIDA initializes and maintains runtime state on this device without a desktop bridge.',
    },
    {
      id: 'identity.persistent',
      label: 'Persistent instance identity',
      state: 'supported',
      detail: 'This AIDA instance retains a secure device-local identity across application restarts.',
    },
    {
      id: 'platform.identity',
      label: 'Platform awareness',
      state: 'supported',
      detail: `AIDA identifies this host as ${platform} ${String(Platform.Version)}.`,
    },
    {
      id: 'intent.native',
      label: 'Native AIDA intent resolution',
      state: gatewayReady ? 'supported' : 'staged',
      detail: gatewayReady
        ? 'Registered directives are resolved through the same AIDA intent registry before language-model reasoning.'
        : 'Native intent resolution requires the AIDA services gateway in this Early Alpha build.',
    },
    {
      id: 'conversation.context',
      label: 'Native recent conversation context',
      state: 'supported',
      detail: 'The last 12 eligible User, AIDA, and System messages are supplied to the AIDA brain as on desktop.',
    },
    {
      id: 'activity.persistent',
      label: 'Persistent activity journal',
      state: 'supported',
      detail: 'Runtime activity is stored locally and restored when this mobile AIDA instance starts again.',
    },
    {
      id: 'memory.persistent',
      label: 'Persistent mobile storage',
      state: 'supported',
      detail: 'AIDA has persistent local runtime storage; full semantic-memory parity remains staged.',
    },
    {
      id: 'reasoning.gateway',
      label: 'Native AIDA reasoning',
      state: gatewayReady ? 'supported' : 'staged',
      detail: gatewayReady
        ? `AIDABrain is connected through the ${gatewaySource} services gateway and uses the canonical AIDA system prompt.`
        : 'Native AIDABrain reasoning is unavailable; only the bounded local fallback is active.',
    },
    {
      id: 'speech.output',
      label: 'AIDA speech output',
      state: speechConfigured ? 'supported' : 'limited',
      detail: speechConfigured
        ? 'Responses use canonical start/end chimes and the configured ElevenLabs AIDA voice.'
        : 'Canonical chimes are available; Android TTS is a degraded fallback until the AIDA voice service is available.',
    },
    {
      id: 'speech.queue',
      label: 'Serialized speech queue',
      state: 'supported',
      detail: 'AIDA utterances are serialized so voice output and audio cues do not overlap.',
    },
    {
      id: 'voice.input',
      label: 'Voice input and transcription',
      state: transcriptionConfigured ? 'supported' : 'staged',
      detail: transcriptionConfigured
        ? 'Push-to-talk microphone capture uses native LISTENING/PROCESSING states, disposable audio, and AIDA transcription.'
        : 'Microphone capture is present, but secure AIDA transcription requires an authenticated transcription provider.',
    },
  ];
}

function createStartingSnapshot(): MobileRuntimeSnapshot {
  const now = new Date().toISOString();
  const platform = platformLabel();
  return {
    instance_id: 'initializing',
    identity_persistent: false,
    runtime_mode: 'standalone',
    status: 'STARTING',
    platform,
    platform_version: String(Platform.Version),
    device_model: deviceModel(),
    app_version: Constants.expoConfig?.version ?? '0.1.0',
    initialized_at: now,
    updated_at: now,
    speech_enabled: false,
    autonomy: { enabled: false, label: 'LOCAL SAFE MODE' },
    statuses: [
      status('agent', 'AGENT', 'STARTING', 'active'),
      status('brain', 'BRAIN', 'STAGED', 'idle'),
      status('speech', 'SPEECH', 'MUTED', 'idle'),
      status('diagnostics', 'DIAGNOSTICS', 'STARTING', 'active'),
      status('memory', 'MEMORY', 'LOADING', 'active'),
      status('artificer', 'ARTIFICER', 'STAGED', 'idle'),
      status('technomancer', 'TECHNOMANCER', 'STAGED', 'idle'),
      status('perception', 'PERCEPTION', 'STAGED', 'idle'),
      status('microphone', 'MICROPHONE', 'STAGED', 'idle'),
      status('tasks', 'TASKS', '0 ACTIVE', 'idle'),
      status('platform', 'PLATFORM', platform.toUpperCase(), 'ready'),
    ],
    capabilities: [],
  };
}

function setAgentState(next: LocalRuntimeStatus, brainValue: string, agentTone: StatusTone) {
  snapshot = {
    ...snapshot,
    status: next,
    updated_at: new Date().toISOString(),
    statuses: snapshot.statuses.map((item) => {
      if (item.id === 'agent') return { ...item, value: next, tone: agentTone };
      if (item.id === 'brain') {
        return {
          ...item,
          value: brainValue,
          tone:
            brainValue === 'ANALYZING'
              ? ('active' as const)
              : brainValue === 'IDLE'
                ? ('ready' as const)
                : brainValue === 'ERROR'
                  ? ('warning' as const)
                  : ('idle' as const),
        };
      }
      return item;
    }),
  };
  notifyRuntime();
}

async function addActivity(
  category: string,
  message: string,
  severity: RuntimeActivityItem['severity'],
  source: string,
  persist = true,
) {
  const item: RuntimeActivityItem = {
    id: `activity-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    category,
    message,
    severity,
    source,
    created_at: new Date().toISOString(),
  };
  activity = [item, ...activity].slice(0, 100);
  notifyActivity();
  if (persist) {
    try {
      await saveActivity(activity);
    } catch {
      // Runtime operation must not fail merely because activity persistence did.
    }
  }
}

function notifyRuntime() {
  for (const listener of runtimeListeners) listener(snapshot);
}

function notifyActivity() {
  const copy = [...activity];
  for (const listener of activityListeners) listener(copy);
}

function status(id: string, label: string, value: string, tone: StatusTone): SubsystemStatus {
  return { id, label, value, tone };
}

function platformLabel() {
  if (Platform.OS === 'android') return 'Android';
  if (Platform.OS === 'ios') return 'iOS';
  return Platform.OS;
}

function deviceModel() {
  const constants = Platform.constants as { Model?: string };
  return constants?.Model?.trim() || `${platformLabel()} device`;
}
