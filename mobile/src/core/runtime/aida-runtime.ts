import Constants from 'expo-constants';
import { Platform } from 'react-native';

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

type Listener = (snapshot: MobileRuntimeSnapshot) => void;

let snapshot: MobileRuntimeSnapshot | null = null;
let activity: RuntimeActivityItem[] = [];
const listeners = new Set<Listener>();

export function bootstrapAidaRuntime(): MobileRuntimeSnapshot {
  if (snapshot) {
    return snapshot;
  }

  const now = new Date().toISOString();
  const platform = platformLabel();
  const model = deviceModel();

  snapshot = {
    instance_id: createSessionInstanceId(),
    runtime_mode: 'standalone',
    status: 'STANDBY',
    platform,
    platform_version: String(Platform.Version),
    device_model: model,
    app_version: Constants.expoConfig?.version ?? '0.1.0',
    initialized_at: now,
    updated_at: now,
    autonomy: {
      enabled: false,
      label: 'LOCAL SAFE MODE',
    },
    statuses: [
      status('agent', 'AGENT', 'STANDBY', 'ready'),
      status('brain', 'BRAIN', 'GATEWAY PENDING', 'warning'),
      status('speech', 'SPEECH', 'IDLE', 'idle'),
      status('diagnostics', 'DIAGNOSTICS', 'READY', 'ready'),
      status('memory', 'MEMORY', 'SESSION', 'idle'),
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
        id: 'platform.identity',
        label: 'Platform awareness',
        state: 'supported',
        detail: `AIDA identifies this host as ${platform} ${String(Platform.Version)}.`,
      },
      {
        id: 'conversation.local',
        label: 'Local directive intake',
        state: 'supported',
        detail: 'The mobile runtime can accept directives locally while cloud reasoning is staged separately.',
      },
      {
        id: 'activity.local',
        label: 'Local activity journal',
        state: 'supported',
        detail: 'Runtime events are available to the mobile interface for this application session.',
      },
      {
        id: 'memory.persistent',
        label: 'Persistent mobile memory',
        state: 'staged',
        detail: 'Durable encrypted local storage is the next standalone-runtime milestone.',
      },
      {
        id: 'reasoning.gateway',
        label: 'AIDA reasoning gateway',
        state: 'staged',
        detail: 'Secure independent reasoning will be connected without embedding Azure credentials in the application.',
      },
    ],
  };

  addActivity(
    'RUNTIME',
    `Standalone AIDA runtime initialized on ${platform} ${String(Platform.Version)} (${model}).`,
    'info',
    'mobile.runtime',
  );
  addActivity(
    'PLATFORM',
    'Desktop bridge dependency disabled for primary mobile operation.',
    'info',
    'mobile.runtime',
  );

  return snapshot;
}

export function getRuntimeSnapshot(): MobileRuntimeSnapshot {
  return bootstrapAidaRuntime();
}

export function getRuntimeActivity(limit = 30): RuntimeActivityItem[] {
  bootstrapAidaRuntime();
  const safeLimit = Math.max(1, Math.min(100, Math.trunc(limit)));
  return activity.slice(0, safeLimit);
}

export function subscribeRuntime(listener: Listener): () => void {
  listeners.add(listener);
  listener(bootstrapAidaRuntime());
  return () => listeners.delete(listener);
}

export async function submitLocalDirective(message: string): Promise<string> {
  const clean = message.trim();
  if (!clean) {
    throw new Error('Directive cannot be empty.');
  }

  setAgentState('ANALYZING', 'LOCAL', 'active');
  addActivity('DIRECTIVE', 'Local directive received.', 'info', 'mobile.runtime');

  await wait(220);

  const normalized = clean.toLowerCase();
  let reply: string;

  if (containsAny(normalized, ['status', 'system status', 'how are you'])) {
    const current = getRuntimeSnapshot();
    reply =
      `Local AIDA runtime is online and ${current.status.toLowerCase()} on ` +
      `${current.platform} ${current.platform_version}. ` +
      'This mobile instance is operating independently of Desktop AIDA.';
  } else if (containsAny(normalized, ['platform', 'android', 'device', 'where are you'])) {
    const current = getRuntimeSnapshot();
    reply =
      `I recognize this host as ${current.platform} ${current.platform_version} ` +
      `on ${current.device_model}. I am running as a standalone mobile AIDA instance.`;
  } else if (containsAny(normalized, ['capability', 'capabilities', 'what can you do'])) {
    const supported = getRuntimeSnapshot().capabilities
      .filter((item) => item.state === 'supported')
      .map((item) => item.label)
      .join(', ');
    reply =
      `Current local capabilities: ${supported}. ` +
      'Persistent memory, independent cloud reasoning, and deeper Android providers are staged next.';
  } else if (containsAny(normalized, ['hello', 'hi', 'hey'])) {
    reply =
      'AIDA Mobile runtime online. Android environment recognized. ' +
      'I am operating locally without requiring Desktop AIDA.';
  } else {
    reply =
      'Directive received by the local AIDA runtime. The Android instance is online, ' +
      'but full language-model reasoning has not been connected to the standalone gateway yet. ' +
      'I can currently report local runtime status, platform identity, and staged capabilities.';
  }

  addActivity('AIDA', 'Local runtime response generated.', 'info', 'mobile.runtime');
  setAgentState('STANDBY', 'GATEWAY PENDING', 'ready');
  return reply;
}

function setAgentState(
  next: LocalRuntimeStatus,
  brainValue: string,
  agentTone: StatusTone,
) {
  const current = bootstrapAidaRuntime();
  const statuses = current.statuses.map((item) => {
    if (item.id === 'agent') {
      return { ...item, value: next, tone: agentTone };
    }
    if (item.id === 'brain') {
      return {
        ...item,
        value: brainValue,
        tone: brainValue === 'LOCAL' ? ('active' as const) : ('warning' as const),
      };
    }
    return item;
  });

  snapshot = {
    ...current,
    status: next,
    statuses,
    updated_at: new Date().toISOString(),
  };
  notify();
}

function addActivity(
  category: string,
  message: string,
  severity: RuntimeActivityItem['severity'],
  source: string,
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
}

function notify() {
  if (!snapshot) {
    return;
  }
  for (const listener of listeners) {
    listener(snapshot);
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

function createSessionInstanceId() {
  return `aida-${Platform.OS}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

function containsAny(value: string, candidates: string[]) {
  return candidates.some((candidate) => value.includes(candidate));
}

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}
