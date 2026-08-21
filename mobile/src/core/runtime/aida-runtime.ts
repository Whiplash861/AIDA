import Constants from 'expo-constants';
import { Platform } from 'react-native';

import {
  loadActivity,
  loadOrCreateInstanceId,
  loadRuntimeState,
  saveActivity,
} from '@/src/core/storage/mobile-storage';

export type StatusTone =
  | 'ready'
  | 'active'
  | 'warning'
  | 'error'
  | 'idle'
  | 'offline';

export type LocalRuntimeStatus =
  | 'STARTING'
  | 'STANDBY'
  | 'ANALYZING'
  | 'WARNING'
  | 'ERROR';

export type SubsystemStatus = {
  id: string;
  label: string;
  value: string;
  tone: StatusTone;
};

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
  autonomy: {
    enabled: boolean;
    label: string;
  };
  statuses: SubsystemStatus[];
  capabilities: RuntimeCapability[];
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
  if (initialization) {
    return initialization;
  }

  initialization = hydrateRuntime();
  return initialization;
}

export function getRuntimeActivity(limit = 30): RuntimeActivityItem[] {
  void initializeAidaRuntime();
  const safeLimit = Math.max(1, Math.min(100, Math.trunc(limit)));
  return activity.slice(0, safeLimit);
}

export function subscribeRuntime(listener: RuntimeListener): () => void {
  runtimeListeners.add(listener);
  listener(snapshot);
  void initializeAidaRuntime();
  return () => runtimeListeners.delete(listener);
}

export function subscribeRuntimeActivity(
  listener: ActivityListener,
): () => void {
  activityListeners.add(listener);
  listener([...activity]);
  void initializeAidaRuntime();
  return () => activityListeners.delete(listener);
}

export async function submitLocalDirective(message: string): Promise<string> {
  await initializeAidaRuntime();
  const clean = message.trim();
  if (!clean) {
    throw new Error('Directive cannot be empty.');
  }

  setAgentState('ANALYZING', 'LOCAL', 'active');
  await addActivity('DIRECTIVE', 'Local directive received.', 'info', 'mobile.runtime');

  await wait(220);

  const normalized = clean.toLowerCase();
  let reply: string;

  if (containsAny(normalized, ['status', 'system status', 'how are you'])) {
    const current = snapshot;
    reply =
      `Local AIDA runtime is online and ${current.status.toLowerCase()} on ` +
      `${current.platform} ${current.platform_version}. ` +
      'This mobile instance is operating independently of Desktop AIDA.';
  } else if (containsAny(normalized, ['platform', 'android', 'device', 'where are you'])) {
    const current = snapshot;
    reply =
      `I recognize this host as ${current.platform} ${current.platform_version} ` +
      `on ${current.device_model}. I am running as a standalone mobile AIDA instance.`;
  } else if (containsAny(normalized, ['identity', 'instance id', 'instance'])) {
    reply =
      `This device is registered locally as ${snapshot.instance_id}. ` +
      'The instance identity is stored securely on this device and is reused across AIDA restarts.';
  } else if (containsAny(normalized, ['capability', 'capabilities', 'what can you do'])) {
    const supported = snapshot.capabilities
      .filter((item) => item.state === 'supported')
      .map((item) => item.label)
      .join(', ');
    reply =
      `Current local capabilities: ${supported}. ` +
      'Independent cloud reasoning and deeper Android providers are staged next.';
  } else if (containsAny(normalized, ['hello', 'hi', 'hey'])) {
    reply =
      'AIDA Mobile runtime online. Android environment recognized. ' +
      'I am operating locally without requiring Desktop AIDA.';
  } else {
    reply =
      'Directive received by the local AIDA runtime. The Android instance is online, ' +
      'but full language-model reasoning has not been connected to the standalone gateway yet. ' +
      'I can currently report local runtime status, platform identity, persistent instance identity, and capabilities.';
  }

  await addActivity('AIDA', 'Local runtime response generated.', 'info', 'mobile.runtime');
  setAgentState('STANDBY', 'STAGED', 'ready');
  return reply;
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

    activity = storedActivity.slice(0, 100);
    const now = new Date().toISOString();
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
      autonomy: {
        enabled: state.autonomy_enabled,
        label: state.autonomy_enabled ? 'ENABLED' : 'LOCAL SAFE MODE',
      },
      statuses: [
        status('agent', 'AGENT', 'STANDBY', 'ready'),
        status('brain', 'BRAIN', 'STAGED', 'idle'),
        status('speech', 'SPEECH', 'STAGED', 'idle'),
        status('diagnostics', 'DIAGNOSTICS', 'READY', 'ready'),
        status('memory', 'MEMORY', 'READY', 'ready'),
        status('artificer', 'ARTIFICER', 'STAGED', 'idle'),
        status('technomancer', 'TECHNOMANCER', 'STAGED', 'idle'),
        status('perception', 'PERCEPTION', 'STAGED', 'idle'),
        status('microphone', 'MICROPHONE', 'STAGED', 'idle'),
        status('tasks', 'TASKS', '0 ACTIVE', 'idle'),
        status('platform', 'PLATFORM', platform.toUpperCase(), 'ready'),
      ],
      capabilities: [
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
          id: 'conversation.local',
          label: 'Local directive intake',
          state: 'supported',
          detail: 'The mobile runtime accepts directives locally while cloud reasoning is staged separately.',
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
          detail: 'AIDA now has persistent local storage for runtime state; the full semantic memory layer remains a later milestone.',
        },
        {
          id: 'reasoning.gateway',
          label: 'AIDA reasoning gateway',
          state: 'staged',
          detail: 'Secure independent reasoning will be connected without embedding Azure credentials in the application.',
        },
        {
          id: 'voice.mobile',
          label: 'Voice and speech',
          state: 'staged',
          detail: 'Microphone capture, transcription, and AIDA speech output are planned as permission-aware mobile capabilities.',
        },
      ],
    };

    await addActivity(
      'RUNTIME',
      identity.created
        ? `Created persistent AIDA instance ${identity.instanceId} on ${platform} ${String(Platform.Version)} (${model}).`
        : `Restored persistent AIDA instance ${identity.instanceId} on ${platform} ${String(Platform.Version)} (${model}).`,
      'info',
      'mobile.runtime',
    );
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
    autonomy: {
      enabled: false,
      label: 'LOCAL SAFE MODE',
    },
    statuses: [
      status('agent', 'AGENT', 'STARTING', 'active'),
      status('brain', 'BRAIN', 'STAGED', 'idle'),
      status('speech', 'SPEECH', 'STAGED', 'idle'),
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

function setAgentState(
  next: LocalRuntimeStatus,
  brainValue: string,
  agentTone: StatusTone,
) {
  const statuses = snapshot.statuses.map((item) => {
    if (item.id === 'agent') {
      return { ...item, value: next, tone: agentTone };
    }
    if (item.id === 'brain') {
      return {
        ...item,
        value: brainValue,
        tone: brainValue === 'LOCAL' ? ('active' as const) : ('idle' as const),
      };
    }
    return item;
  });

  snapshot = {
    ...snapshot,
    status: next,
    statuses,
    updated_at: new Date().toISOString(),
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
  for (const listener of runtimeListeners) {
    listener(snapshot);
  }
}

function notifyActivity() {
  const copy = [...activity];
  for (const listener of activityListeners) {
    listener(copy);
  }
}

function status(
  id: string,
  label: string,
  value: string,
  tone: StatusTone,
): SubsystemStatus {
  return { id, label, value, tone };
}

function platformLabel() {
  if (Platform.OS === 'android') {
    return 'Android';
  }
  if (Platform.OS === 'ios') {
    return 'iOS';
  }
  return Platform.OS;
}

function deviceModel() {
  const constants = Platform.constants as { Model?: string };
  return constants?.Model?.trim() || `${platformLabel()} device`;
}

function containsAny(value: string, candidates: string[]) {
  return candidates.some((candidate) => value.includes(candidate));
}

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}
