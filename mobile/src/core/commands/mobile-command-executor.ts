import { executeAndroidCoreDiagnostic } from '@/src/core/diagnostics/android-core-diagnostics';
import { executeEngineDirective } from '@/src/core/engines/registry';
import {
  EngineCommandExecutionContext,
  EngineCommandResult,
} from '@/src/core/engines/types';
import { loadEvidence } from '@/src/core/storage/mobile-storage';
import { RoutedDirective } from '@/src/core/reasoning/types';
import { renderReport, unavailableReport } from '@/src/core/reporting';

export type MobileCommandResult = EngineCommandResult;
export type MobileCommandExecutionContext = EngineCommandExecutionContext;

/**
 * Android command execution boundary.
 *
 * Native AIDA's CommandRouter recognizes intent before platform execution.
 * Engine-owned commands dispatch through the Engine registry first. Core
 * diagnostics remain AIDA Core capabilities and use their own Android provider.
 */
export async function executeMobileRoutedDirective(
  directive: RoutedDirective,
  context: MobileCommandExecutionContext,
): Promise<MobileCommandResult> {
  if (directive.requiresConfirmation) {
    const text = 'This action needs approval, but mobile AIDA cannot request and apply that approval yet. No operation was executed. Open Systems to review available features.';
    return {transcriptText: text, speechText: text, includeInContext: false, executed: false};
  }
  const localResult = (text: string, executed = true): MobileCommandResult => ({transcriptText: text, speechText: 'Local review is displayed.', includeInContext: false, executed});
  const checkpoint = () => { if (context.signal?.aborted) throw new Error('Operation cancelled.'); };
  if (['SAVE_BASELINE', 'COMPARE_BASELINE', 'FOLLOW_UP_SCAN'].includes(directive.commandType)) {
    const {saveBaseline, loadBaseline, latestDiagnostic, compareBaseline} = await import('@/src/core/diagnostics/baseline');
    checkpoint();
    if (context.platform.toLowerCase() !== 'android' || !context.instanceId) return localResult('This comparison requires a persistent Android device identity and locally captured diagnostics.', false);
    if (directive.commandType === 'SAVE_BASELINE') {
      checkpoint();
      const baseline = await saveBaseline(context.instanceId);
      return localResult(renderReport('Saved comparison ready', [`Saved the diagnostic captured at ${baseline.evidence.capturedAt} as this device’s baseline for future comparisons.`], ['This records observations, not a claim that the device is healthy. It does not show what caused any problem.'], ['Type "run follow-up scan" after your next check or when the symptom occurs. AIDA will compare the new observations with this saved scan.']));
    }
    const baseline = await loadBaseline(context.instanceId);
    checkpoint();
    if (!baseline) return localResult('No baseline exists for this device. Run a quick scan, then type: save baseline.', false);
    if (directive.commandType === 'FOLLOW_UP_SCAN') {
      const result = await executeAndroidCoreDiagnostic('QUICKSCAN', false);
      checkpoint();
      if (!result?.evidence) return localResult('A fresh diagnostic could not be collected.', false);
      return {...result, transcriptText: compareBaseline(baseline, result.evidence, context.instanceId).transcript, speechText: 'Follow-up observations compared with your baseline. Review the changes and coverage limits.', includeInContext: false};
    }
    const current = await latestDiagnostic();
    checkpoint();
    return localResult(current ? compareBaseline(baseline, current, context.instanceId).transcript : 'No local diagnostic is available.');
  }
  if (directive.commandType.startsWith('CASE_')) {
    const {casePreview, discardReviewedCase, importReviewedCase, loadImportedCase, reviewedCaseExport, stageDiagnosticExport} = await import('@/src/core/cases/transfer');
    const {latestDiagnostic} = await import('@/src/core/diagnostics/baseline');
    checkpoint();
    if (directive.commandType === 'CASE_EXPORT') {
      const evidence = await latestDiagnostic();
      checkpoint();
      return localResult(evidence && context.instanceId ? stageDiagnosticExport(evidence, context.instanceId) : 'Run a local diagnostic on a device with persistent identity before exporting a case.');
    }
    if (directive.commandType === 'CASE_COPY') {
      const {copyCaseToClipboard} = await import('@/src/core/perception/intake');
      checkpoint();
      await copyCaseToClipboard(reviewedCaseExport());
      return localResult('Reviewed case copied to your clipboard. Paste it on the destination device and review it there before import. Clipboard sharing is controlled by your operating system.');
    }
    if (directive.commandType === 'CASE_IMPORT') {
      const imported = await importReviewedCase();
      return localResult(`Reference case retained locally as ${imported.localId}. No commands, baseline, permissions, or action approvals were imported.\n\n${casePreview(imported.envelope)}`);
    }
    if (directive.commandType === 'CASE_DISCARD') { discardReviewedCase(); return localResult('Pending case review discarded.'); }
    if (directive.commandType === 'CASE_SHOW') {
      const imported = await loadImportedCase();
      return localResult(imported ? `${imported.localId}\n${casePreview(imported.envelope)}` : 'No imported reference case is saved.');
    }
  }
  if (directive.commandType === 'DIAGNOSTIC_LAST') {
    const evidence = (await loadEvidence()).find(item => item.kind === 'diagnostic' || item.kind === 'aegis');
    const text = evidence ? renderReport('Saved diagnostic', [`Found a report captured at ${evidence.capturedAt}. No fresh check ran.`], ['This report describes the earlier check, not the device’s current condition. Older reports may use older labels.'], ['Review the original report below. Run a new local scan if you need current observations.']) + '\n\nOriginal saved report\n' + evidence.transcript : 'No saved local diagnostic is available. Run a quick scan to collect one.';
    return {transcriptText: text, speechText: evidence ? 'The latest saved diagnostic is displayed.' : text, includeInContext: false, executed: true};
  }
  if (directive.commandType === 'INTENT_CLARIFICATION') {
    const clarification =
      directive.clarificationText ||
      'AIDA needs more detail. Describe what you want checked and which device or app is involved.';
    return {
      transcriptText: clarification,
      speechText: clarification,
      includeInContext: !directive.localOnly,
      executed: true,
    };
  }

  const engineResult = await executeEngineDirective(directive, context);
  if (engineResult) {
    return engineResult;
  }

  const coreDiagnostic = context.platform.toLowerCase() === 'android' ? await executeAndroidCoreDiagnostic(
    directive.commandType,
    !directive.localOnly,
  ) : null;
  if (coreDiagnostic) {
    return coreDiagnostic;
  }

  const transcriptText = unavailableReport('AIDA Core', 'this check', context.platform);
  const speechText =
    `${context.platform} core provider unavailable for the resolved command. ` +
    'No operation was executed.';

  return {
    transcriptText,
    speechText,
    includeInContext: !directive.localOnly,
    executed: false,
  };
}
