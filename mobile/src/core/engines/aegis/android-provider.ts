import { EngineCommandExecutionContext, EngineCommandResult } from '@/src/core/engines/types';
import {
  captureAndroidSystemEvidence,
  formatBytes,
  storageUsedPercent,
} from '@/src/core/platform/android/system-evidence';
import { RoutedDirective } from '@/src/core/reasoning/types';
import { explainAndroidCheckGap } from '@/src/core/diagnostics/android-core-diagnostics';

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
    'Aegis security check',
    '',
    `Platform: ${evidence.osName ?? 'Android'} ${evidence.osVersion ?? evidence.platformVersion}`,
    `Android API level: ${evidence.apiLevel ?? 'Unavailable'}`,
    `OS build: ${evidence.osBuildId ?? 'Unavailable'}`,
    `System access: ${rooted == null ? 'Check unavailable' : rooted ? 'Signs of unrestricted access (root); review below' : 'No root indicator reported by this check'}`,
    `System software: ${!evidence.osBuildFingerprint ? 'Signing check unavailable' : testKeys ? 'Test signing key reported; review below' : 'No test signing key reported'}`,
    `Network: ${evidence.networkType}, ${connectivityLabel(evidence.networkConnected, evidence.internetReachable)}`,
    '',
    'What this check means:',
    ...(rooted === true ? ['- Review system access: an experimental check found signs of unrestricted system access, also called root. This can be intentional and does not establish that malware is present. If unexpected, check the device’s software with its manufacturer or a trusted technician.'] : []),
    ...(testKeys ? ['- Review system software: the installed system reports a test signing key. This can be expected on development or custom systems. If unexpected, verify the installed system with the device manufacturer. This result alone does not establish that malware is present.'] : []),
    '- These limited checks cannot confirm that the device is secure.',
    '',
    'Checks not available in this version:',
    '- AIDA cannot read Play Protect’s results, so it cannot tell whether Play Protect found a problem. Check Play Protect in the Play Store, if available on your device.',
    ...(!evidence.osBuildFingerprint ? ['- System software signing could not be checked. This is missing information, not evidence that the software is unsafe. Check system details in Settings if needed.'] : []),
    ...(rooted == null ? [`- ${explainAndroidCheckGap('security.root-indicator')}`] : []),
  ];

  if (evidence.gaps.some(gap => gap.id !== 'security.root-indicator')) {
    lines.push('', 'Other checks AIDA could not complete:');
    for (const gap of evidence.gaps) if (gap.id !== 'security.root-indicator') lines.push(`- ${explainAndroidCheckGap(gap.id)}`);
  }

  const warningCount = Number(rooted === true) + Number(testKeys);
  const speechText = warningCount > 0
    ? `Aegis security check finished. ${warningCount} system setting${warningCount === 1 ? '' : 's'} to review. These may be intentional changes; the check does not establish that malware is present. The report explains how to follow up.`
    : 'Aegis security check finished. No root or test-signing concern was established from the available information. Some security checks are unavailable, so this is not a full security assessment.';

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
    evidence: {id: evidence.capturedAt + '-' + Math.random().toString(36).slice(2), capturedAt: evidence.capturedAt, platform: evidence.platform, kind: 'aegis', observations: {...evidence}, gaps: evidence.gaps.map(gap => gap.detail), transcript: lines.join('\n')},
  };
}

async function runSurfaceSecurityScan(includeInContext: boolean): Promise<EngineCommandResult> {
  const evidence = await captureAndroidSystemEvidence();
  const findings: { severity: 'INFO' | 'WARNING' | 'HIGH'; text: string; unavailable?: boolean }[] = [];
  const testKeys = evidence.osBuildFingerprint?.toLowerCase().includes('test-keys') ?? false;
  const storagePercent = storageUsedPercent(evidence);

  if (evidence.rootedIndicator === true) {
    findings.push({
      severity: 'HIGH',
      text: 'Review system access: an experimental check found signs of unrestricted system access, also called root. Root access can reduce protections between apps. This can be an intentional modification and does not establish that malware is present. If unexpected, check the device’s software with its manufacturer or a trusted technician.',
    });
  } else if (evidence.rootedIndicator === false) {
    findings.push({
      severity: 'INFO',
      text: 'System access check: no root indicator was reported by this experimental check. This result alone cannot confirm that the device is secure.',
    });
  } else {
    findings.push({ severity: 'WARNING', unavailable: true, text: explainAndroidCheckGap('security.root-indicator') });
  }

  if (testKeys) {
    findings.push({
      severity: 'WARNING',
      text: 'Review system software: Android reports a test signing key in its software identification. This can be expected on a development or custom system; it does not establish that malware is present. If unexpected, verify the installed system with the device manufacturer.',
    });
  }

  if (evidence.networkConnected === false) {
    findings.push({ severity: 'INFO', text: 'Device is offline: Android reports no network connection. Check Wi-Fi or mobile data in Settings if you want to connect. Being offline is not itself a security threat.' });
  } else if (evidence.internetReachable === false) {
    findings.push({ severity: 'WARNING', text: 'Internet connection needs a check: Android reports that the current connection cannot reach the internet. Online services may not work. Check Wi-Fi or mobile data in Settings and retry. This result alone does not indicate a security threat.' });
  } else {
    findings.push({ severity: 'INFO', unavailable: evidence.networkConnected == null, text: evidence.networkConnected == null
      ? 'Connection check incomplete: Android did not report whether the device is connected. Check Wi-Fi or mobile data in Settings if needed.'
      : `Connection information: Android reports ${evidence.networkType.toLowerCase()}. This does not assess the network’s security.` });
  }

  if (storagePercent != null && storagePercent >= 95) {
    findings.push({
      severity: 'WARNING',
      text: `Storage almost full: ${storagePercent}% is used. There may be too little space for updates and other apps. Review Storage in Android Settings and choose files you no longer need. This does not by itself indicate a security threat.`,
    });
  }

  const highCount = findings.filter((item) => item.severity === 'HIGH').length;
  const warningCount = findings.filter((item) => item.severity === 'WARNING').length;
  const unavailableCount = findings.filter((item) => item.unavailable && item.severity === 'WARNING').length;
  const concernsToReview = warningCount - unavailableCount;
  const coverage = calculateSurfaceCoverage(evidence);

  const lines = [
    'Aegis surface security check',
    '',
    `Device: ${[evidence.manufacturer, evidence.modelName].filter(Boolean).join(' ') || 'Android device'}`,
    `OS: ${evidence.osName ?? 'Android'} ${evidence.osVersion ?? evidence.platformVersion} (API ${evidence.apiLevel ?? 'Unavailable'})`,
    `Installed memory: ${formatBytes(evidence.totalMemoryBytes)}`,
    `Network: ${evidence.networkType}, ${connectivityLabel(evidence.networkConnected, evidence.internetReachable)}`,
    `Checks with results: ${coverage.available} of ${coverage.total} (${coverage.percent}%). This measures available information, not your risk level.`,
    '',
    'What AIDA observed:',
    ...findings.filter((item) => !item.unavailable).map((item) => `- ${item.text}`),
    '',
    'Checks AIDA could not complete:',
    ...findings.filter((item) => item.unavailable).map((item) => `- ${item.text}`),
    ...(!evidence.osBuildFingerprint ? ['- System software signing: Android did not return the information needed for this check. This does not show that the software is unsafe. Check system details in Settings if needed.'] : []),
    '- Play Protect results: this version of AIDA cannot read them. Check Play Protect in the Play Store, if available on your device.',
    '- Other apps and automatic startup: Android does not give this version of AIDA enough access to inspect them. Review unfamiliar apps in Android Settings if you have a concern.',
    '- All device files: this check does not scan your files for malware. It cannot establish whether a file is safe.',
    '- An unavailable check means a result is missing. It is not a detected threat or a successful check.',
  ];

  for (const gap of evidence.gaps) if (gap.id !== 'security.root-indicator') lines.push(`- ${explainAndroidCheckGap(gap.id)}`);

  let speechText: string;
  if (highCount > 0) {
    speechText = 'Aegis check finished. The system access result needs review. It can reflect an intentional modification and does not establish that malware is present. The report explains the next step and which checks were unavailable.';
  } else if (concernsToReview > 0) {
    speechText = `Aegis check finished. ${concernsToReview} item${concernsToReview === 1 ? '' : 's'} to review. The report explains the result, what to do next, and which checks were unavailable.`;
  } else {
    speechText = 'Aegis check finished. No concern was established from the information AIDA could read. Some security checks are unavailable; this is not a full assessment of whether the device is secure.';
  }

  return {
    transcriptText: lines.join('\n'),
    speechText,
    includeInContext,
    executed: true,
    evidence: {id: evidence.capturedAt + '-' + Math.random().toString(36).slice(2), capturedAt: evidence.capturedAt, platform: evidence.platform, kind: 'aegis', observations: {...evidence}, gaps: evidence.gaps.map(gap => gap.detail), transcript: lines.join('\n')},
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
