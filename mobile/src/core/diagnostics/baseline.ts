import { StoredEvidence, loadEvidence } from '@/src/core/storage/mobile-storage';
import Storage from '@/src/core/storage/local-kv';
import { LocalReviewError } from '@/src/core/perception/local-review-error';
import { renderReport, displayStatus } from '@/src/core/reporting';

const KEY = 'aida.mobile.diagnostic-baseline.v1';
export type Baseline = {version: 1; instanceId: string; savedAt: string; evidence: StoredEvidence};
export type Comparison = {changes: string[]; gaps: string[]; guidance: string[]; transcript: string};
const FIELDS = [
  ['freeStorageBytes', 'Free storage', 'bytes'], ['batteryLevel', 'Battery level', 'percent'],
  ['lowPowerMode', 'Power saver', 'boolean'], ['batteryOptimizationEnabled', 'AIDA battery optimization', 'boolean'],
  ['networkConnected', 'Network connected', 'boolean'], ['internetReachable', 'Internet reachable', 'boolean'],
  ['networkType', 'Network type', 'text'], ['osBuildId', 'OS build', 'text'],
  ['rootedIndicator', 'System access check (experimental)', 'boolean'],
] as const;

export function isLocalDiagnostic(item: StoredEvidence): boolean {
  return item.kind === 'diagnostic' && item.platform.toLowerCase() === 'android' &&
    !item.observations.imported && item.observations.authority !== 'reference-only' &&
    typeof item.observations.capturedAt === 'string' && Number.isFinite(Date.parse(item.capturedAt));
}
export async function latestDiagnostic(): Promise<StoredEvidence | undefined> {
  return (await loadEvidence()).find(isLocalDiagnostic);
}
export async function saveBaseline(instanceId: string): Promise<Baseline> {
  if (!instanceId) throw new LocalReviewError('A persistent local device identity is required.');
  const evidence = await latestDiagnostic();
  if (!evidence) throw new LocalReviewError('Run a local quick scan before saving a baseline.');
  const baseline: Baseline = {version: 1, instanceId, savedAt: new Date().toISOString(), evidence};
  await Storage.setItem(KEY, JSON.stringify(baseline));
  return baseline;
}
export async function loadBaseline(instanceId: string): Promise<Baseline | null> {
  const raw = await Storage.getItem(KEY);
  if (!raw || raw.length > 100_000) return null;
  try {
    const value = JSON.parse(raw) as Baseline;
    return value?.version === 1 && value.instanceId === instanceId && value.evidence &&
      value.evidence.observations && isLocalDiagnostic(value.evidence) ? value : null;
  } catch { return null; }
}
function usable(value: unknown, kind: string): boolean {
  if (kind === 'boolean') return typeof value === 'boolean';
  if (kind === 'text') return typeof value === 'string' && value !== '' && value !== 'UNKNOWN';
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && (kind !== 'percent' || value <= 1);
}
function display(value: unknown, kind: string): string {
  if (kind === 'bytes') return `${((value as number) / 1024 ** 3).toFixed(2)} GiB`;
  if (kind === 'percent') return `${Math.round((value as number) * 100)}%`;
  if (kind === 'boolean') return value ? 'yes' : 'no';
  return displayStatus(String(value).slice(0, 120));
}
export function compareBaseline(baseline: Baseline, current: StoredEvidence, instanceId: string): Comparison {
  if (baseline.instanceId !== instanceId || !isLocalDiagnostic(current)) throw new LocalReviewError('Only diagnostics from this local instance can be compared.');
  if (current.platform !== baseline.evidence.platform) throw new LocalReviewError('Diagnostic platforms do not match.');
  const changes: string[] = [], gaps: string[] = [], guidance: string[] = [];
  for (const [key, label, kind] of FIELDS) {
    const previous = baseline.evidence.observations[key], next = current.observations[key];
    if (!usable(previous, kind) || !usable(next, kind)) { gaps.push(`${label}: unavailable in one or both scans.`); continue; }
    if (previous !== next) changes.push(`${label}: ${display(previous, kind)} → ${display(next, kind)}.`);
  }
  for (const gap of [...baseline.evidence.gaps, ...current.gaps]) if (!gaps.includes(gap)) gaps.push(gap);
  const values = current.observations;
  if (typeof values.totalStorageBytes === 'number' && typeof values.freeStorageBytes === 'number' && values.totalStorageBytes > 0 && values.freeStorageBytes / values.totalStorageBytes <= 0.1) guidance.push('Review storage in Android Settings; select any files to remove yourself, then run a follow-up scan.');
  if (values.internetReachable === false || values.networkConnected === false) guidance.push('Check the selected network in Android Settings, then run a follow-up scan.');
  if (values.lowPowerMode === true) guidance.push('Review whether power saver is intentional before changing it; then run a follow-up scan.');
  if (values.rootedIndicator === true) guidance.push('An experimental check reported unrestricted system access, also called root. If that was unexpected, ask the device manufacturer or a trusted technician to verify the installed software. This indicator alone is not a malware diagnosis.');
  const missingFields = FIELDS.filter(([key, , kind]) => !usable(baseline.evidence.observations[key], kind) || !usable(current.observations[key], kind));
  const transcript = renderReport('Local diagnostic comparison',
    [`Saved comparison captured: ${baseline.evidence.capturedAt}. Scan compared: ${current.capturedAt}.`,
      current.id === baseline.evidence.id ? 'This is the same saved scan; no fresh observations were collected.' : 'Compared observations captured by this AIDA instance.',
      ...(changes.length ? changes : [missingFields.length === FIELDS.length ? 'No fields had results in both scans, so no differences could be assessed.' : 'No differences in the fields with results in both scans.']),
      'No settings were changed.'],
    [...missingFields.map(([, label]) => `${label}: unavailable in one or both scans.`),
      ...(gaps.length ? ['Some checks were incomplete. Missing results do not establish whether a problem is present.'] : []),
      'These observations do not establish total processor load, other apps’ activity, or the cause of a slowdown. A difference does not prove a cause or that a repair succeeded.'],
    guidance.length ? guidance : ['Describe the symptom and run a follow-up scan when it occurs. Compare that result with the saved observations.']);
  return {changes, gaps, guidance, transcript};
}
