import * as SecureStore from 'expo-secure-store';
import Storage from '@/src/core/storage/local-kv';
import { Platform } from 'react-native';

const INSTANCE_ID_KEY = 'aida.mobile.instance-id.v1';
const ENROLLMENT_KEY = 'aida.mobile.gateway-enrollment.v2';
const LEGACY_TOKEN_KEY = 'aida.mobile.gateway-session-token.v1';
const LEGACY_URL_KEY = 'aida.mobile.gateway-url.v1';
const RUNTIME_STATE_KEY = 'aida.mobile.runtime-state.v1';
const ACTIVITY_KEY = 'aida.mobile.activity.v1';
const EVIDENCE_KEY = 'aida.mobile.evidence.v1';
let webEnrollment: GatewayEnrollment | null = null;

export type GatewayEnrollment = {
  version: 2; baseUrl: string; token: string; deviceId: string; expiresAt: number;
};
export type StoredRuntimeState = { autonomy_enabled: boolean; speech_enabled: boolean };
export type StoredEvidence = {
  id: string; capturedAt: string; platform: string; kind: string;
  observations: Record<string, unknown>; gaps: string[]; transcript: string;
};

async function getValue(key: string): Promise<string | null> {
  if (Platform.OS === 'web') return typeof localStorage === 'undefined' ? null : localStorage.getItem(key);
  return Storage.getItem(key);
}
async function setValue(key: string, value: string): Promise<void> {
  if (Platform.OS === 'web') {
    if (typeof localStorage === 'undefined') throw new Error('Browser storage is unavailable.');
    localStorage.setItem(key, value);
    return;
  }
  await Storage.setItem(key, value);
}
function object(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
async function readJson(key: string): Promise<unknown> {
  const raw = await getValue(key);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export async function loadOrCreateInstanceId(platform: string): Promise<{ instanceId: string; created: boolean }> {
  const existing = Platform.OS === 'web' ? await getValue(INSTANCE_ID_KEY) : await SecureStore.getItemAsync(INSTANCE_ID_KEY);
  if (existing && /^[a-zA-Z0-9_-]{1,160}$/.test(existing)) return { instanceId: existing, created: false };
  const instanceId = 'aida-' + platform + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  if (Platform.OS === 'web') await setValue(INSTANCE_ID_KEY, instanceId);
  else await SecureStore.setItemAsync(INSTANCE_ID_KEY, instanceId);
  return { instanceId, created: true };
}

export async function loadGatewayEnrollment(): Promise<GatewayEnrollment | null> {
  if (Platform.OS === 'web') return webEnrollment; // Never persist bearer credentials in browser storage.
  const raw = await SecureStore.getItemAsync(ENROLLMENT_KEY);
  if (!raw) return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  if (!object(value) || value.version !== 2 || typeof value.baseUrl !== 'string' ||
      typeof value.token !== 'string' || typeof value.deviceId !== 'string' ||
      typeof value.expiresAt !== 'number') return null;
  return value as GatewayEnrollment;
}

export async function saveGatewayEnrollment(value: GatewayEnrollment): Promise<void> {
  if (Platform.OS === 'web') { webEnrollment = { ...value }; return; }
  // A single secure write binds endpoint and credential. Failed replacement retains the old pair.
  await SecureStore.setItemAsync(ENROLLMENT_KEY, JSON.stringify(value));
  await SecureStore.deleteItemAsync(LEGACY_TOKEN_KEY).catch(() => undefined);
  await Storage.removeItem(LEGACY_URL_KEY).catch(() => undefined);
}
export async function clearGatewayEnrollment(): Promise<void> {
  webEnrollment = null;
  if (Platform.OS !== 'web') {
    await SecureStore.deleteItemAsync(ENROLLMENT_KEY);
    await SecureStore.deleteItemAsync(LEGACY_TOKEN_KEY);
    await Storage.removeItem(LEGACY_URL_KEY);
  }
}
export async function loadLegacyGateway(): Promise<{ baseUrl: string; token: string } | null> {
  if (Platform.OS === 'web') return null;
  const [baseUrl, token] = await Promise.all([Storage.getItem(LEGACY_URL_KEY), SecureStore.getItemAsync(LEGACY_TOKEN_KEY)]);
  return baseUrl && token ? { baseUrl, token } : null;
}
export async function loadRuntimeState(): Promise<StoredRuntimeState> {
  const state = await readJson(RUNTIME_STATE_KEY);
  return {
    autonomy_enabled: object(state) && state.autonomy_enabled === true,
    speech_enabled: object(state) && typeof state.speech_enabled === 'boolean' ? state.speech_enabled : true,
  };
}
let runtimeStateTail: Promise<void> = Promise.resolve();
export function saveRuntimeState(state: StoredRuntimeState): Promise<void> {
  const serialized = JSON.stringify(state);
  const result = runtimeStateTail.then(() => setValue(RUNTIME_STATE_KEY, serialized));
  runtimeStateTail = result.catch(() => undefined);
  return result;
}
export async function loadActivity<T>(): Promise<T[]> {
  const items = await readJson(ACTIVITY_KEY);
  if (!Array.isArray(items)) return [];
  return items.filter((item) => object(item) &&
    ['id', 'category', 'message', 'source', 'created_at'].every((key) => typeof item[key] === 'string') &&
    ['info', 'warning', 'error'].includes(String(item.severity))).slice(0, 100) as T[];
}
export async function saveActivity<T>(items: T[]): Promise<void> {
  await setValue(ACTIVITY_KEY, JSON.stringify(items.slice(0, 100)));
}
export async function loadEvidence(): Promise<StoredEvidence[]> {
  const value = await readJson(EVIDENCE_KEY);
  return Array.isArray(value) ? value.filter((item) => object(item) && typeof item.id === 'string' &&
    typeof item.capturedAt === 'string' && typeof item.transcript === 'string' &&
    typeof item.kind === 'string' && typeof item.platform === 'string' &&
    object(item.observations) && Array.isArray(item.gaps) && item.gaps.every((gap: unknown) => typeof gap === 'string')).slice(0, 30) as StoredEvidence[] : [];
}
let evidenceTail: Promise<void> = Promise.resolve();
export function saveEvidence(item: StoredEvidence): Promise<void> {
  const save = evidenceTail.then(async () => {
    const previous = await loadEvidence();
    await setValue(EVIDENCE_KEY, JSON.stringify([item, ...previous.filter((old) => old.id !== item.id)].slice(0, 30)));
  });
  evidenceTail = save.catch(() => undefined);
  return save;
}
