import * as SecureStore from 'expo-secure-store';
import Storage from 'expo-sqlite/kv-store';

const INSTANCE_ID_KEY = 'aida.mobile.instance-id.v1';
const GATEWAY_SESSION_TOKEN_KEY = 'aida.mobile.gateway-session-token.v1';
const RUNTIME_STATE_KEY = 'aida.mobile.runtime-state.v1';
const ACTIVITY_KEY = 'aida.mobile.activity.v1';

export type StoredRuntimeState = {
  autonomy_enabled: boolean;
  speech_enabled: boolean;
};

export async function loadOrCreateInstanceId(
  platform: string,
): Promise<{ instanceId: string; created: boolean }> {
  const existing = (await SecureStore.getItemAsync(INSTANCE_ID_KEY))?.trim();
  if (existing) {
    return { instanceId: existing, created: false };
  }

  const instanceId = createInstanceId(platform);
  await SecureStore.setItemAsync(INSTANCE_ID_KEY, instanceId);
  return { instanceId, created: true };
}

export async function loadGatewaySessionToken(): Promise<string> {
  return (await SecureStore.getItemAsync(GATEWAY_SESSION_TOKEN_KEY))?.trim() ?? '';
}

export async function saveGatewaySessionToken(token: string): Promise<void> {
  const clean = token.trim();
  if (!clean) {
    await clearGatewaySessionToken();
    return;
  }
  await SecureStore.setItemAsync(GATEWAY_SESSION_TOKEN_KEY, clean);
}

export async function clearGatewaySessionToken(): Promise<void> {
  await SecureStore.deleteItemAsync(GATEWAY_SESSION_TOKEN_KEY);
}

export async function loadRuntimeState(): Promise<StoredRuntimeState> {
  const state = await readJson<Partial<StoredRuntimeState>>(RUNTIME_STATE_KEY, {});
  return {
    autonomy_enabled: Boolean(state.autonomy_enabled),
    speech_enabled: Boolean(state.speech_enabled),
  };
}

export async function saveRuntimeState(state: StoredRuntimeState): Promise<void> {
  await Storage.setItem(RUNTIME_STATE_KEY, JSON.stringify(state));
}

export async function loadActivity<T>(): Promise<T[]> {
  return readJson<T[]>(ACTIVITY_KEY, []);
}

export async function saveActivity<T>(items: T[]): Promise<void> {
  await Storage.setItem(ACTIVITY_KEY, JSON.stringify(items));
}

async function readJson<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await Storage.getItem(key);
    if (!raw) {
      return fallback;
    }
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function createInstanceId(platform: string) {
  const normalizedPlatform = platform.trim().toLowerCase() || 'device';
  const random = `${Math.random().toString(36).slice(2, 10)}${Math.random()
    .toString(36)
    .slice(2, 10)}`;
  return `aida-${normalizedPlatform}-${Date.now().toString(36)}-${random}`;
}
