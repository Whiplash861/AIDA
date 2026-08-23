import * as Battery from 'expo-battery';
import * as Device from 'expo-device';
import * as FileSystem from 'expo-file-system/legacy';
import * as Network from 'expo-network';
import { Platform } from 'react-native';

export type AndroidEvidenceGap = {
  id: string;
  detail: string;
};

export type AndroidSystemEvidence = {
  capturedAt: string;
  platform: string;
  platformVersion: string;
  apiLevel: number | null;
  manufacturer: string | null;
  brand: string | null;
  modelName: string | null;
  productName: string | null;
  designName: string | null;
  osName: string | null;
  osVersion: string | null;
  osBuildId: string | null;
  osBuildFingerprint: string | null;
  cpuArchitectures: string[];
  totalMemoryBytes: number | null;
  maxAppMemoryBytes: number | null;
  uptimeMs: number | null;
  totalStorageBytes: number | null;
  freeStorageBytes: number | null;
  batteryLevel: number | null;
  batteryState: string;
  lowPowerMode: boolean | null;
  batteryOptimizationEnabled: boolean | null;
  networkType: string;
  networkConnected: boolean | null;
  internetReachable: boolean | null;
  ipAddress: string | null;
  airplaneMode: boolean | null;
  rootedIndicator: boolean | null;
  platformFeatureCount: number | null;
  gaps: AndroidEvidenceGap[];
};

type SafeReadResult<T> = { value: T | null; gap?: AndroidEvidenceGap };

export async function captureAndroidSystemEvidence(): Promise<AndroidSystemEvidence> {
  const gaps: AndroidEvidenceGap[] = [];

  const [
    maxAppMemory,
    uptime,
    storageTotal,
    storageFree,
    powerState,
    batteryOptimization,
    networkState,
    ipAddress,
    airplaneMode,
    rootedIndicator,
    platformFeatures,
  ] = await Promise.all([
    safeRead('memory.app-ceiling', 'Android app memory ceiling is unavailable.', async () =>
      Platform.OS === 'android' ? Device.getMaxMemoryAsync() : null,
    ),
    safeRead('system.uptime', 'Device uptime is unavailable.', () => Device.getUptimeAsync()),
    safeRead('storage.total', 'Total internal storage is unavailable.', () =>
      FileSystem.getTotalDiskCapacityAsync(),
    ),
    safeRead('storage.free', 'Free internal storage is unavailable.', () =>
      FileSystem.getFreeDiskStorageAsync(),
    ),
    safeRead('power.state', 'Battery and power state are unavailable.', () =>
      Battery.getPowerStateAsync(),
    ),
    safeRead('power.optimization', 'Battery optimization state is unavailable.', async () =>
      Platform.OS === 'android' ? Battery.isBatteryOptimizationEnabledAsync() : null,
    ),
    safeRead('network.state', 'Network connectivity state is unavailable.', () =>
      Network.getNetworkStateAsync(),
    ),
    safeRead('network.ip', 'Local IP address is unavailable.', () => Network.getIpAddressAsync()),
    safeRead('network.airplane', 'Airplane-mode state is unavailable.', async () =>
      Platform.OS === 'android' ? Network.isAirplaneModeEnabledAsync() : null,
    ),
    safeRead('security.root-indicator', 'Root indicator could not be evaluated.', () =>
      Device.isRootedExperimentalAsync(),
    ),
    safeRead('system.features', 'Android platform feature inventory is unavailable.', async () =>
      Platform.OS === 'android' ? Device.getPlatformFeaturesAsync() : [],
    ),
  ]);

  for (const result of [
    maxAppMemory,
    uptime,
    storageTotal,
    storageFree,
    powerState,
    batteryOptimization,
    networkState,
    ipAddress,
    airplaneMode,
    rootedIndicator,
    platformFeatures,
  ]) {
    if (result.gap) gaps.push(result.gap);
  }

  const power = powerState.value;
  const network = networkState.value;

  return {
    capturedAt: new Date().toISOString(),
    platform: Platform.OS,
    platformVersion: String(Platform.Version),
    apiLevel: Device.platformApiLevel ?? null,
    manufacturer: Device.manufacturer ?? null,
    brand: Device.brand ?? null,
    modelName: Device.modelName ?? null,
    productName: Device.productName ?? null,
    designName: Device.designName ?? null,
    osName: Device.osName ?? null,
    osVersion: Device.osVersion ?? null,
    osBuildId: Device.osBuildId ?? null,
    osBuildFingerprint: Device.osBuildFingerprint ?? null,
    cpuArchitectures: [...(Device.supportedCpuArchitectures ?? [])],
    totalMemoryBytes: Device.totalMemory ?? null,
    maxAppMemoryBytes: maxAppMemory.value,
    uptimeMs: uptime.value,
    totalStorageBytes: storageTotal.value,
    freeStorageBytes: storageFree.value,
    batteryLevel:
      power && power.batteryLevel >= 0 ? power.batteryLevel : null,
    batteryState: batteryStateLabel(power?.batteryState),
    lowPowerMode: typeof power?.lowPowerMode === 'boolean' ? power.lowPowerMode : null,
    batteryOptimizationEnabled: batteryOptimization.value,
    networkType: String(network?.type ?? 'UNKNOWN'),
    networkConnected:
      typeof network?.isConnected === 'boolean' ? network.isConnected : null,
    internetReachable:
      typeof network?.isInternetReachable === 'boolean' ? network.isInternetReachable : null,
    ipAddress: normalizeIp(ipAddress.value),
    airplaneMode: airplaneMode.value,
    rootedIndicator: rootedIndicator.value,
    platformFeatureCount: platformFeatures.value?.length ?? null,
    gaps,
  };
}

export function storageUsedPercent(evidence: AndroidSystemEvidence): number | null {
  const total = evidence.totalStorageBytes;
  const free = evidence.freeStorageBytes;
  if (!total || total <= 0 || free == null || free < 0) return null;
  return clampPercent(((total - free) / total) * 100);
}

export function formatBytes(bytes: number | null): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return 'Unavailable';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  const precision = index >= 3 ? 2 : index >= 2 ? 1 : 0;
  return `${value.toFixed(precision)} ${units[index]}`;
}

export function formatDuration(ms: number | null): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return 'Unavailable';
  const totalMinutes = Math.floor(ms / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

async function safeRead<T>(
  id: string,
  detail: string,
  reader: () => Promise<T | null>,
): Promise<SafeReadResult<T>> {
  try {
    return { value: await reader() };
  } catch {
    return { value: null, gap: { id, detail } };
  }
}

function batteryStateLabel(state: Battery.BatteryState | undefined): string {
  switch (state) {
    case Battery.BatteryState.CHARGING:
      return 'CHARGING';
    case Battery.BatteryState.FULL:
      return 'FULL';
    case Battery.BatteryState.UNPLUGGED:
      return 'UNPLUGGED';
    default:
      return 'UNKNOWN';
  }
}

function normalizeIp(value: string | null): string | null {
  const trimmed = value?.trim();
  if (!trimmed || trimmed === '0.0.0.0') return null;
  return trimmed;
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value * 10) / 10));
}
