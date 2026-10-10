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
    'AIDA quickscan',
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
    'What AIDA observed:',
    ...findings.map((item) => `- ${item.text}`),
  ];

  if (evidence.gaps.length > 0) {
    lines.push('', 'Checks AIDA could not complete:');
    for (const gap of evidence.gaps) lines.push(`- ${explainAndroidCheckGap(gap.id)}`);
  }

  const speechText = warnings.length === 0
    ? (evidence.gaps.length ? 'Quickscan finished, but some checks could not complete. That means some results are missing, not that a threat was detected. The report explains what you can check yourself.' : 'Quickscan finished. Nothing to flag in the information AIDA could read. This quick check cannot confirm the device is free of problems.')
    : `Quickscan finished. ${warnings.length} item${warnings.length === 1 ? '' : 's'} to review. The report explains what was observed and what to do next.${evidence.gaps.length ? ' Some checks could not complete; those missing results are listed separately.' : ''}`;

  lines.push('', 'Follow-through: type "save baseline" to retain these observations, "run follow-up scan" to compare fresh observations, or "export diagnostic case" to review a redacted transfer.');

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
    evidence: {id: evidence.capturedAt + '-' + Math.random().toString(36).slice(2), capturedAt: evidence.capturedAt, platform: evidence.platform, kind: 'diagnostic', observations: {...evidence}, gaps: evidence.gaps.map(gap => gap.detail), transcript: lines.join('\n')},
  };
}

async function runAndroidPerformanceScan(includeInContext: boolean): Promise<EngineCommandResult> {
  const evidence = await captureAndroidSystemEvidence();
  const storagePercent = storageUsedPercent(evidence);
  const warnings: string[] = [];

  if (storagePercent != null && storagePercent >= 90) {
    warnings.push(`Storage almost full: ${storagePercent}% is used. This can leave too little room for updates or apps. Review Storage in Android Settings and choose files you no longer need.`);
  } else if (storagePercent != null && storagePercent >= 80) {
    warnings.push(`Storage filling up: ${storagePercent}% is used. Available space is getting low. Review Storage in Android Settings before it fills up.`);
  }
  if (evidence.lowPowerMode === true) {
    warnings.push('Power saver is on: Android may reduce speed or background work to extend battery life. This may be intentional. Review the Battery settings if performance is a problem.');
  }
  if (evidence.batteryOptimizationEnabled === true) {
    warnings.push('Battery saving for AIDA is on: Android may pause AIDA while you use other apps. This is a normal battery-saving setting. Review AIDA’s battery settings only if background work is being interrupted.');
  }
  if (evidence.internetReachable === false) {
    warnings.push('Internet connection needs a check: Android reports that the current connection cannot reach the internet. Online services may not work. Check Wi-Fi or mobile data in Settings and retry. This result alone does not indicate a security threat.');
  }

  const lines = [
    'AIDA performance scan',
    '',
    `Device: ${deviceLabel(evidence.manufacturer, evidence.modelName)}`,
    `Installed memory: ${formatBytes(evidence.totalMemoryBytes)}`,
    `Memory Android lets AIDA use: ${formatBytes(evidence.maxAppMemoryBytes)}`,
    `Processor type: ${evidence.cpuArchitectures.length ? evidence.cpuArchitectures.join(', ') : 'Unavailable'}`,
    `Internal storage: ${formatStorage(evidence.totalStorageBytes, evidence.freeStorageBytes, storagePercent)}`,
    `Battery state: ${formatBattery(evidence.batteryLevel, evidence.batteryState, evidence.lowPowerMode)}`,
    `Battery optimization: ${booleanLabel(evidence.batteryOptimizationEnabled)}`,
    `Network: ${formatNetwork(evidence.networkType, evidence.networkConnected, evidence.internetReachable)}`,
    `Device uptime: ${formatDuration(evidence.uptimeMs)}`,
    `Device features Android reported: ${evidence.platformFeatureCount ?? 'Unavailable'}`,
    '',
    'What AIDA observed:',
  ];

  if (warnings.length === 0) {
    lines.push('- Nothing to flag in the storage, battery, and connection information AIDA could read. Missing results are not counted as successful checks.');
  } else {
    for (const warning of warnings) lines.push(`- ${warning}`);
  }

  lines.push(
    '',
    'What this check cannot tell you:',
    '- This version of AIDA cannot see the device’s total processor load, unused memory, or how much memory other apps use.',
    '- Those limits do not mean something is wrong. They mean this report cannot identify which app is slowing the device down.',
    '- If the slowdown continues, check Battery and Storage in Android Settings and note when the problem happens.',
  );

  if (evidence.gaps.length > 0) {
    lines.push('', 'Checks AIDA could not complete:');
    for (const gap of evidence.gaps) lines.push(`- ${explainAndroidCheckGap(gap.id)}`);
  }

  const speechText = warnings.length === 0
    ? (evidence.gaps.length ? 'Performance check finished, but some results are missing. The report explains which checks could not complete and what to check in Settings.' : 'Performance check finished. Nothing to flag in the storage, battery, and connection information AIDA could read. This check cannot identify which app is causing a slowdown.')
    : `Performance check finished. ${warnings.length} item${warnings.length === 1 ? '' : 's'} to review, with suggested next steps.${evidence.gaps.length ? ' Some checks could not complete; those missing results are listed separately.' : ''}`;

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
    evidence: {id: evidence.capturedAt + '-' + Math.random().toString(36).slice(2), capturedAt: evidence.capturedAt, platform: evidence.platform, kind: 'diagnostic', observations: {...evidence}, gaps: evidence.gaps.map(gap => gap.detail), transcript: lines.join('\n')},
  };
}

type Finding = { severity: 'INFO' | 'WARNING' | 'HIGH'; text: string };

type EvidenceShape = Awaited<ReturnType<typeof captureAndroidSystemEvidence>>;

function quickscanFindings(evidence: EvidenceShape, storagePercent: number | null): Finding[] {
  const findings: Finding[] = [];

  if (evidence.rootedIndicator === true) {
    findings.push({
      severity: 'HIGH',
      text: 'Review system access: an experimental check found signs of unrestricted system access, also called root. This may be an intentional modification and does not establish that malware is present. If you did not expect this, check the device’s software with its manufacturer or a trusted technician.',
    });
  }
  if (storagePercent != null && storagePercent >= 90) {
    findings.push({ severity: 'WARNING', text: `Storage almost full: ${storagePercent}% is used. Apps and updates may need more space. Review Storage in Android Settings and choose files you no longer need.` });
  }
  if (evidence.batteryLevel != null && evidence.batteryLevel <= 0.15 && evidence.batteryState === 'UNPLUGGED') {
    findings.push({ severity: 'WARNING', text: `Battery low: ${Math.round(evidence.batteryLevel * 100)}% remains and the device is not charging. Connect a charger when convenient. This is a power reminder, not a security alert.` });
  }
  if (evidence.networkConnected === false) {
    findings.push({ severity: 'WARNING', text: 'No network connection: Android reports that the device is offline. Online services may not work. Check Wi-Fi, mobile data, or airplane mode in Settings if you want to connect.' });
  } else if (evidence.internetReachable === false) {
    findings.push({ severity: 'WARNING', text: 'Internet connection needs a check: the device is connected to a network, but Android reports no internet access. Try opening a website or checking Wi-Fi/mobile data in Settings. This result alone does not indicate a security threat.' });
  }
  if (evidence.osBuildFingerprint?.toLowerCase().includes('test-keys')) {
    findings.push({ severity: 'WARNING', text: 'Review system software: Android reports a test signing key in its software identification. This may be expected on a development or custom system; it does not establish that malware is present. If unexpected, verify the installed system with the device manufacturer.' });
  }

  if (findings.length === 0) {
    findings.push({ severity: 'INFO', text: 'Nothing to flag in the information AIDA could read. This quick check cannot confirm that the device is free of problems.' });
  }
  return findings;
}

/** Explain collection gaps without changing their retained technical evidence. */
export function explainAndroidCheckGap(id: string): string {
  const explanations: Record<string, string> = {
    'memory.app-ceiling': 'App memory check unavailable: AIDA could not read how much memory Android allows it to use. This does not show a memory problem. Try the check again later.',
    'system.uptime': 'Restart timing unavailable: AIDA could not read how long the device has been running. This does not show a problem with the device. Try again later if you need that information.',
    'storage.total': 'Storage size unavailable: AIDA could not read the device’s storage capacity. Check Storage in Android Settings to see the available space.',
    'storage.free': 'Free-space check unavailable: AIDA could not read how much storage is free. This does not mean the storage is full. Check Storage in Android Settings.',
    'power.state': 'Battery check unavailable: AIDA could not read the battery and charging information. Check the device’s battery display or Battery settings.',
    'power.optimization': 'Battery-saving setting unavailable: AIDA could not read whether Android limits its background work. Check AIDA’s battery settings if background work is being interrupted.',
    'network.state': 'Connection check unavailable: AIDA could not read the current network status. This does not mean the internet is disconnected. Check Wi-Fi or mobile data in Settings.',
    'network.ip': 'Network address unavailable: AIDA could not read the device’s local network address. This alone does not show a connection or security problem. Check network details in Settings if you need the address.',
    'network.airplane': 'Airplane-mode check unavailable: AIDA could not read this setting. Check the device’s quick settings if you are troubleshooting a connection.',
    'security.root-indicator': 'System access check unavailable: AIDA could not check for unrestricted system access, also called root. This is a missing result, not a detected threat. Retry later; review the device’s security settings if you are concerned.',
    'system.features': 'Device-feature list unavailable: Android did not return the feature list for this check. This does not show a hardware fault. Try the check again later.',
  };
  return explanations[id] ?? 'A device check could not complete, so its result is unknown. No problem was established by that missing result. Try the check again later.';
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
