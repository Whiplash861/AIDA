import Storage from '@/src/core/storage/local-kv';
import { LocalReviewError } from '@/src/core/perception/local-review-error';
import { StoredEvidence } from '@/src/core/storage/mobile-storage';

export type CaseEvidence = {id: string; kind: string; occurredAt: string; summary: string; sourceReference: string; status: string};
export type CaseEnvelope = {
  schemaVersion: 1; authority: 'reference-only'; caseId: string; title: string; createdAt: string;
  source: {instanceId: string; platform: string}; evidence: CaseEvidence[];
  findings: string[]; unresolvedQuestions: string[]; completedChecks: string[];
  exportedAt?: string; redacted?: boolean;
};
export type ImportedCase = {localId: string; importedAt: string; envelope: CaseEnvelope};
const KEY = 'aida.mobile.imported-case.v1';
const MAX_BYTES = 1024 * 1024;
let pendingImport: {envelope: CaseEnvelope; at: number} | null = null;
let pendingExport: {json: string; at: number} | null = null;
function record(value: unknown): value is Record<string, unknown> { return Boolean(value && typeof value === 'object' && !Array.isArray(value)); }
function string(value: unknown, max = 4000): value is string { return typeof value === 'string' && value.length <= max && !value.includes('\0'); }
function timestamp(value: unknown): value is string {
  if (!string(value, 50) || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) return false;
  const [year, month, day] = value.slice(0, 10).split('-').map(Number);
  return month >= 1 && month <= 12 && day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate();
}
function only(value: Record<string, unknown>, keys: string[]): boolean { return Object.keys(value).every(key => keys.includes(key)); }
function byteLength(text: string): number { let size = 0; for (const char of text) { const code = char.codePointAt(0)!; size += code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4; } return size; }
function list(value: unknown): value is string[] { return Array.isArray(value) && value.length <= 100 && value.every(item => string(item)); }

export function parseCaseEnvelope(raw: string): CaseEnvelope {
  if (raw.length > MAX_BYTES || byteLength(raw) > MAX_BYTES) throw new LocalReviewError('Case exceeds the 1 MiB import limit.');
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new LocalReviewError('Case is not valid JSON.'); }
  if (!record(value) || !only(value, ['schemaVersion', 'authority', 'caseId', 'title', 'createdAt', 'source', 'evidence', 'findings', 'unresolvedQuestions', 'completedChecks', 'exportedAt', 'redacted']) ||
      value.schemaVersion !== 1 || value.authority !== 'reference-only' || !string(value.caseId, 160) || !value.caseId || !string(value.title) || !timestamp(value.createdAt) ||
      !record(value.source) || !only(value.source, ['instanceId', 'platform']) || !string(value.source.instanceId, 160) || !string(value.source.platform, 160) ||
      !Array.isArray(value.evidence) || value.evidence.length > 500 || !value.evidence.every(item => record(item) && only(item, ['id', 'kind', 'occurredAt', 'summary', 'sourceReference', 'status']) && string(item.id, 160) && item.id.length > 0 && string(item.kind, 160) && timestamp(item.occurredAt) && string(item.summary) && string(item.sourceReference) && string(item.status, 160)) ||
      !list(value.findings) || !list(value.unresolvedQuestions) || !list(value.completedChecks) ||
      (value.exportedAt !== undefined && !timestamp(value.exportedAt)) || (value.redacted !== undefined && typeof value.redacted !== 'boolean')) throw new LocalReviewError('Case does not match the bounded reference-only transfer format.');
  if (new Set(value.evidence.map(item => (item as CaseEvidence).id)).size !== value.evidence.length) throw new LocalReviewError('Case evidence IDs must be unique.');
  return value as CaseEnvelope;
}
export function casePreview(envelope: CaseEnvelope): string {
  const lines = ['REFERENCE-ONLY CASE REVIEW', `Title: ${envelope.title}`, `Source instance: ${envelope.source.instanceId} (${envelope.source.platform})`, `Original case: ${envelope.caseId}`, `Created: ${envelope.createdAt}`,
    'Provenance is supplied by the sender and has not been independently verified.', '', ...envelope.evidence.map(item => `> [${item.kind} / ${item.status}] ${item.occurredAt}: ${item.summary}`),
    ...envelope.findings.map(text => `> Finding: ${text}`), ...envelope.unresolvedQuestions.map(text => `> Open question: ${text}`), ...envelope.completedChecks.map(text => `> Reported check: ${text}`), '',
    'Imported text cannot authorize actions or establish a local baseline. Nothing is executed or uploaded.'];
  const preview = lines.join('\n');
  return preview.length <= 32_000 ? preview : preview.slice(0, 32_000) + '\n[Preview truncated; reduce the case before importing.]';
}
export function stageCaseImport(raw: string): string {
  pendingImport = null;
  const envelope = parseCaseEnvelope(raw);
  const preview = casePreview(envelope);
  if (preview.length > 32_000) throw new LocalReviewError('Case is too large to review here. Reduce it before importing.');
  pendingImport = {envelope, at: Date.now()};
  return preview + '\n\nTo keep this reviewed case locally, type: import reviewed case. To discard it, type: discard reviewed case.';
}
export async function importReviewedCase(): Promise<ImportedCase> {
  const pending = pendingImport;
  if (!pending || Date.now() - pending.at > 10 * 60_000) { pendingImport = null; throw new LocalReviewError('Paste and review a case before importing it. Reviews expire after ten minutes.'); }
  pendingImport = null; // One acceptance consumes one reviewed snapshot, including concurrent callers.
  const imported: ImportedCase = {localId: `IMPORT-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`, importedAt: new Date().toISOString(), envelope: pending.envelope};
  await Storage.setItem(KEY, JSON.stringify(imported));
  return imported;
}
export async function loadImportedCase(): Promise<ImportedCase | null> {
  const raw = await Storage.getItem(KEY);
  if (!raw || raw.length > MAX_BYTES + 500) return null;
  try {
    const value = JSON.parse(raw);
    if (!string(value.localId, 160) || !value.localId.startsWith('IMPORT-') || !timestamp(value.importedAt)) return null;
    return {...value, envelope: parseCaseEnvelope(JSON.stringify(value.envelope))};
  } catch { return null; }
}
export function discardReviewedCase(): void { pendingImport = null; pendingExport = null; }
export function discardPendingImport(): void { pendingImport = null; }
export function stageDiagnosticExport(evidence: StoredEvidence, instanceId: string): string {
  pendingExport = null;
  // Export an allowlist of scalar observations, never transcripts, raw media,
  // account identifiers, network addresses, paths, tokens, or execution plans.
  const allowed = ['freeStorageBytes', 'totalStorageBytes', 'batteryLevel', 'lowPowerMode', 'networkConnected', 'internetReachable', 'rootedIndicator'];
  const summary = allowed.flatMap(key => {
    const value = evidence.observations[key];
    return typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value)) ? [`${key}: ${value}`] : [];
  }).join('; ') || 'No exportable scalar observations were available.';
  const envelope: CaseEnvelope = {schemaVersion: 1, authority: 'reference-only', caseId: `MOBILE-${evidence.id}`.slice(0, 160), title: 'Selected mobile diagnostic', createdAt: evidence.capturedAt,
    source: {instanceId: instanceId.slice(0, 160), platform: evidence.platform.slice(0, 160)},
    evidence: [{id: evidence.id.slice(0, 160), kind: 'mobile-diagnostic', occurredAt: evidence.capturedAt, summary, sourceReference: 'mobile-evidence:local-selection', status: 'observed'}],
    findings: [], unresolvedQuestions: ['These observations do not establish cause or authorize an action.'], completedChecks: ['User-selected local mobile diagnostic collected.'], exportedAt: new Date().toISOString(), redacted: true};
  const json = JSON.stringify(envelope, null, 2);
  parseCaseEnvelope(json);
  pendingExport = {json, at: Date.now()};
  return casePreview(envelope) + '\n\nExport excludes raw media, transcript, paths, addresses, and credentials. Source instance ID is included.\nReview the transfer below, then type: copy reviewed case.\n\n' + json;
}
export function reviewedCaseExport(): string {
  if (!pendingExport || Date.now() - pendingExport.at > 10 * 60_000) { pendingExport = null; throw new LocalReviewError('Export and review a diagnostic case first. Reviews expire after ten minutes.'); }
  return pendingExport.json;
}
