import { EngineCommandExecutionContext, EngineCommandResult } from '@/src/core/engines/types';
import {
  captureAndroidSystemEvidence,
  formatBytes,
  storageUsedPercent,
} from '@/src/core/platform/android/system-evidence';
import { RoutedDirective } from '@/src/core/reasoning/types';

export async function executeAndroidAegisCommand(
  directive: RoutedDirective,
  context: EngineCommandExecutionContext,
): Promise<EngineCommandResult | null> {
  if (context.platform.toLowerCase() !== 'android') return null;

  if (directive.commandType === 'SECURITY_STATUS') {
    return runSecurityStatus(!directive.localOnly);
  }
  if (directive.commandType === 'SECURITY_SURFACE_SCAN') {
    return runSurfaceSecurityScan(!directive.localOnly);
  }
  return null;
}

async function runSecurityStatus(includeInContext: boolean): Promise<EngineCommandResult> {
  const evidence = await captureAndroidSystemEvidence();
  const rooted = evidence.rootedIndicator;
  const testKeys = evidence.osBuildFingerprint?.toLowerCase().includes('test-keys') ?? false;

  const lines = [
    'AEGIS SECURITY STATUS',
    '',
    `Platform: ${evidence.osName ?? 'Android'} ${evidence.osVersion ?? evidence.platformVersion}`,
    `Android API level: ${evidence.apiLevel ?? 'Unavailable'}`,
    `OS build: ${evidence.osBuildId ?? 'Unavailable'}`,
    `Root indicator: ${rooted == null ? 'Unavailable' : rooted ? 'DETECTED' : 'Not detected'}`,
    `Build signing posture: ${testKeys ? 'TEST-KEYS REPORTED' : 'No test-key indicator reported'}`,
    `Network: ${evidence.networkType}, ${connectivityLabel(evidence.networkConnected, evidence.internetReachable)}`,
    '',
    'Provider visibility:',
    '- Android platform/Play Protect health is not exposed to this Expo runtime.',
    '- Aegis does not interpret unavailable provider telemetry as healthy provider status.',
  ];

  if (evidence.gaps.length > 0) {
    lines.push('', 'Visibility notes:');
    for (const gap of evidence.gaps) lines.push(`- ${gap.detail}`);
  }

  const warningCount = Number(rooted === true) + Number(testKeys);
  const speechText = warningCount > 0
    ? `Aegis security status complete. ${warningCount} Android-visible security condition${warningCount === 1 ? '' : 's'} require attention. Provider visibility remains limited.`
    : 'Aegis security status complete. No Android-visible root or test-key indicator detected. Security-provider visibility remains limited.';

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
  };
}

async function runSurfaceSecurityScan(includeInContext: boolean): Promise<EngineCommandResult> {
  const evidence = await captureAndroidSystemEvidence();
  const findings: { severity: 'INFO' | 'WARNING' | 'HIGH'; text: string }[] = [];
  const testKeys = evidence.osBuildFingerprint?.toLowerCase().includes('test-keys') ?? false;
  const storagePercent = storageUsedPercent(evidence);

  if (evidence.rootedIndicator === true) {
    findings.push({
      severity: 'HIGH',
      text: 'Android root indicators were detected. Root access can weaken application isolation and platform trust boundaries.',
    });
  } else if (evidence.rootedIndicator === false) {
    findings.push({
      severity: 'INFO',
      text: 'No root indicator was reported by the available experimental Android check. This is not proof that root concealment is impossible.',
    });
  } else {
    findings.push({ severity: 'WARNING', text: 'Root posture could not be evaluated.' });
  }

  if (testKeys) {
    findings.push({
      severity: 'WARNING',
      text: 'The Android build fingerprint contains test-keys. Verify that the installed OS build is expected and trusted.',
    });
  }

  if (evidence.networkConnected === false) {
    findings.push({ severity: 'INFO', text: 'No active network connection is currently reported.' });
  } else if (evidence.internetReachable === false) {
    findings.push({ severity: 'WARNING', text: 'The active network does not currently report internet reachability.' });
  } else {
    findings.push({ severity: 'INFO', text: `Active network type: ${evidence.networkType}.` });
  }

  if (storagePercent != null && storagePercent >= 95) {
    findings.push({
      severity: 'WARNING',
      text: `Internal storage is ${storagePercent}% used. Severe storage pressure can interfere with updates, logging, and security tooling.`,
    });
  }

  const highCount = findings.filter((item) => item.severity === 'HIGH').length;
  const warningCount = findings.filter((item) => item.severity === 'WARNING').length;
  const coverage = calculateSurfaceCoverage(evidence);

  const lines = [
    'AEGIS SURFACE SECURITY SCAN',
    '',
    `Device: ${[evidence.manufacturer, evidence.modelName].filter(Boolean).join(' ') || 'Android device'}`,
    `OS: ${evidence.osName ?? 'Android'} ${evidence.osVersion ?? evidence.platformVersion} (API ${evidence.apiLevel ?? 'Unavailable'})`,
    `Installed memory: ${formatBytes(evidence.totalMemoryBytes)}`,
    `Network: ${evidence.networkType}, ${connectivityLabel(evidence.networkConnected, evidence.internetReachable)}`,
    `Android surface evidence coverage: ${coverage.percent}%`,
    '',
    'Findings:',
    ...findings.map((item) => `- [${item.severity}] ${item.text}`),
    '',
    'Coverage limits:',
    '- Play Protect/provider detection status is not exposed to Expo Go.',
    '- Global process and per-app activity inspection is restricted by Android.',
    '- Startup/persistence inventory is not available through the current provider.',
    '- Arbitrary filesystem scanning is not permitted without a native or user-authorized file provider.',
    '- Missing evidence reduces Aegis coverage; it is not counted as a clean result.',
  ];

  for (const gap of evidence.gaps) lines.push(`- ${gap.detail}`);

  let speechText: string;
  if (highCount > 0) {
    speechText = `Aegis Surface Security Scan complete. ${highCount} high-risk Android-visible condition${highCount === 1 ? '' : 's'} detected. Evidence coverage is ${coverage.percent} percent.`;
  } else if (warningCount > 0) {
    speechText = `Aegis Surface Security Scan complete. ${warningCount} condition${warningCount === 1 ? '' : 's'} require review. Evidence coverage is ${coverage.percent} percent.`;
  } else {
    speechText = `Aegis Surface Security Scan complete. No high-confidence Android-visible threat indicator detected. Evidence coverage is ${coverage.percent} percent and remains platform-limited.`;
  }

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
  };
}

function calculateSurfaceCoverage(
  evidence: Awaited<ReturnType<typeof captureAndroidSystemEvidence>>,
): { available: number; total: number; percent: number } {
  const checks = [
    evidence.rootedIndicator != null,
    Boolean(evidence.osBuildFingerprint || evidence.osBuildId),
    evidence.networkConnected != null,
    false, // provider detections / Play Protect
    false, // process and persistence inventory
    false, // arbitrary file analysis
  ];
  const available = checks.filter(Boolean).length;
  return { available, total: checks.length, percent: Math.round((available / checks.length) * 100) };
}

function connectivityLabel(connected: boolean | null, reachable: boolean | null): string {
  const connection = connected == null ? 'connection unknown' : connected ? 'connected' : 'disconnected';
  const reachability = reachable == null ? 'internet unknown' : reachable ? 'internet reachable' : 'internet unreachable';
  return `${connection}, ${reachability}`;
}
