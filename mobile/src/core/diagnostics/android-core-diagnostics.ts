import {
  captureAndroidSystemEvidence,
  formatBytes,
  formatDuration,
  storageUsedPercent,
} from '@/src/core/platform/android/system-evidence';
import { EngineCommandResult } from '@/src/core/engines/types';

export async function executeAndroidCoreDiagnostic(
  commandType: string,
  includeInContext: boolean,
): Promise<EngineCommandResult | null> {
  if (commandType === 'QUICKSCAN') {
    return runAndroidQuickscan(includeInContext);
  }
  if (commandType === 'PERFORMANCE_SCAN') {
    return runAndroidPerformanceScan(includeInContext);
  }
  return null;
}

async function runAndroidQuickscan(includeInContext: boolean): Promise<EngineCommandResult> {
  const evidence = await captureAndroidSystemEvidence();
  const storagePercent = storageUsedPercent(evidence);
  const findings = quickscanFindings(evidence, storagePercent);
  const warnings = findings.filter((item) => item.severity !== 'INFO');

  const lines = [
    'AIDA QUICKSCAN',
    '',
    `Device: ${deviceLabel(evidence.manufacturer, evidence.modelName)}`,
    `Operating system: ${evidence.osName ?? 'Android'} ${evidence.osVersion ?? evidence.platformVersion}`,
    `Android API level: ${evidence.apiLevel ?? 'Unavailable'}`,
    `Installed memory: ${formatBytes(evidence.totalMemoryBytes)}`,
    `Internal storage: ${formatStorage(evidence.totalStorageBytes, evidence.freeStorageBytes, storagePercent)}`,
    `Battery: ${formatBattery(evidence.batteryLevel, evidence.batteryState, evidence.lowPowerMode)}`,
    `Network: ${formatNetwork(evidence.networkType, evidence.networkConnected, evidence.internetReachable)}`,
    `Device uptime: ${formatDuration(evidence.uptimeMs)}`,
    '',
    'Findings:',
    ...findings.map((item) => `- [${item.severity}] ${item.text}`),
  ];

  if (evidence.gaps.length > 0) {
    lines.push('', 'Visibility notes:');
    for (const gap of evidence.gaps) lines.push(`- ${gap.detail}`);
  }

  const speechText = warnings.length === 0
    ? 'Quickscan complete. Android device posture is within available operating parameters.'
    : `Quickscan complete. ${warnings.length} condition${warnings.length === 1 ? '' : 's'} require attention.`;

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
  };
}

async function runAndroidPerformanceScan(includeInContext: boolean): Promise<EngineCommandResult> {
  const evidence = await captureAndroidSystemEvidence();
  const storagePercent = storageUsedPercent(evidence);
  const warnings: string[] = [];

  if (storagePercent != null && storagePercent >= 90) {
    warnings.push(`Internal storage pressure is critical at ${storagePercent}% used.`);
  } else if (storagePercent != null && storagePercent >= 80) {
    warnings.push(`Internal storage pressure is elevated at ${storagePercent}% used.`);
  }
  if (evidence.lowPowerMode === true) {
    warnings.push('Android power saver is enabled and may constrain background or peak performance.');
  }
  if (evidence.batteryOptimizationEnabled === true) {
    warnings.push('Battery optimization is enabled for this application and may constrain background AIDA tasks.');
  }
  if (evidence.internetReachable === false) {
    warnings.push('Internet reachability is unavailable on the active network.');
  }

  const lines = [
    'AIDA PERFORMANCE SCAN',
    '',
    `Device: ${deviceLabel(evidence.manufacturer, evidence.modelName)}`,
    `Installed memory: ${formatBytes(evidence.totalMemoryBytes)}`,
    `AIDA app memory ceiling: ${formatBytes(evidence.maxAppMemoryBytes)}`,
    `CPU architectures: ${evidence.cpuArchitectures.length ? evidence.cpuArchitectures.join(', ') : 'Unavailable'}`,
    `Internal storage: ${formatStorage(evidence.totalStorageBytes, evidence.freeStorageBytes, storagePercent)}`,
    `Battery state: ${formatBattery(evidence.batteryLevel, evidence.batteryState, evidence.lowPowerMode)}`,
    `Battery optimization: ${booleanLabel(evidence.batteryOptimizationEnabled)}`,
    `Network: ${formatNetwork(evidence.networkType, evidence.networkConnected, evidence.internetReachable)}`,
    `Device uptime: ${formatDuration(evidence.uptimeMs)}`,
    `Android platform features visible: ${evidence.platformFeatureCount ?? 'Unavailable'}`,
    '',
    'Performance assessment:',
  ];

  if (warnings.length === 0) {
    lines.push('- [INFO] No storage, power-state, or connectivity pressure was identified in Android-visible telemetry.');
  } else {
    for (const warning of warnings) lines.push(`- [WARNING] ${warning}`);
  }

  lines.push(
    '',
    'Coverage:',
    '- Android does not expose global CPU utilization, free system RAM, or other applications\' process memory to this Expo runtime.',
    '- Those unavailable signals are reported as coverage limits, not interpreted as healthy values.',
  );

  if (evidence.gaps.length > 0) {
    for (const gap of evidence.gaps) lines.push(`- ${gap.detail}`);
  }

  const speechText = warnings.length === 0
    ? 'Performance scan complete. No Android-visible storage, power, or connectivity pressure detected. Process-level visibility remains limited by Android.'
    : `Performance scan complete. ${warnings.length} Android-visible performance condition${warnings.length === 1 ? '' : 's'} detected.`;

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
  };
}

type Finding = { severity: 'INFO' | 'WARNING' | 'HIGH'; text: string };

type EvidenceShape = Awaited<ReturnType<typeof captureAndroidSystemEvidence>>;

function quickscanFindings(evidence: EvidenceShape, storagePercent: number | null): Finding[] {
  const findings: Finding[] = [];

  if (evidence.rootedIndicator === true) {
    findings.push({
      severity: 'HIGH',
      text: 'Android root indicators were reported. Elevated system modification can weaken platform security boundaries.',
    });
  }
  if (storagePercent != null && storagePercent >= 90) {
    findings.push({ severity: 'WARNING', text: `Internal storage is ${storagePercent}% used.` });
  }
  if (evidence.batteryLevel != null && evidence.batteryLevel <= 0.15 && evidence.batteryState === 'UNPLUGGED') {
    findings.push({ severity: 'WARNING', text: `Battery level is ${Math.round(evidence.batteryLevel * 100)}% and the device is unplugged.` });
  }
  if (evidence.networkConnected === false) {
    findings.push({ severity: 'WARNING', text: 'No active network connection is reported.' });
  } else if (evidence.internetReachable === false) {
    findings.push({ severity: 'WARNING', text: 'A network is connected but internet reachability is unavailable.' });
  }
  if (evidence.osBuildFingerprint?.toLowerCase().includes('test-keys')) {
    findings.push({ severity: 'WARNING', text: 'Android build fingerprint contains test-keys; verify that this is expected for the installed OS build.' });
  }

  if (findings.length === 0) {
    findings.push({ severity: 'INFO', text: 'No actionable anomaly was identified in Android-visible Quickscan telemetry.' });
  }
  return findings;
}

function deviceLabel(manufacturer: string | null, model: string | null): string {
  return [manufacturer, model].filter(Boolean).join(' ') || 'Android device';
}

function formatStorage(total: number | null, free: number | null, usedPercent: number | null): string {
  if (total == null || free == null) return 'Unavailable';
  const percent = usedPercent == null ? '' : `, ${usedPercent}% used`;
  return `${formatBytes(total)} total, ${formatBytes(free)} free${percent}`;
}

function formatBattery(level: number | null, state: string, lowPower: boolean | null): string {
  const percent = level == null ? 'level unavailable' : `${Math.round(level * 100)}%`;
  const saver = lowPower == null ? 'power saver unknown' : lowPower ? 'power saver enabled' : 'power saver disabled';
  return `${percent}, ${state.toLowerCase()}, ${saver}`;
}

function formatNetwork(type: string, connected: boolean | null, reachable: boolean | null): string {
  const connectedLabel = connected == null ? 'connection unknown' : connected ? 'connected' : 'disconnected';
  const reachableLabel = reachable == null ? 'internet unknown' : reachable ? 'internet reachable' : 'internet unreachable';
  return `${type}, ${connectedLabel}, ${reachableLabel}`;
}

function booleanLabel(value: boolean | null): string {
  if (value == null) return 'Unavailable';
  return value ? 'Enabled' : 'Disabled';
}
