import { executeAndroidCoreDiagnostic } from '@/src/core/diagnostics/android-core-diagnostics';
import { executeEngineDirective } from '@/src/core/engines/registry';
import {
  EngineCommandExecutionContext,
  EngineCommandResult,
} from '@/src/core/engines/types';
import { loadEvidence } from '@/src/core/storage/mobile-storage';
import { RoutedDirective } from '@/src/core/reasoning/types';

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
    const text = 'This directive requires confirmation and has no registered mobile confirmation workflow. No operation was executed.';
    return {transcriptText: text, speechText: text, includeInContext: false, executed: false};
  }
  if (directive.commandType === 'DIAGNOSTIC_LAST') {
    const evidence = (await loadEvidence())[0];
    const text = evidence ? 'Saved diagnostic from ' + evidence.capturedAt + '\n\n' + evidence.transcript : 'No saved local diagnostic is available.';
    return {transcriptText: text, speechText: evidence ? 'The latest saved diagnostic is displayed.' : text, includeInContext: false, executed: true};
  }
  if (directive.commandType === 'INTENT_CLARIFICATION') {
    const clarification =
      directive.clarificationText ||
      'Analysis incomplete. Additional clarification is required.';
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

  const intent = directive.intentId || directive.commandType.toLowerCase();
  const transcriptText =
    `Registered AIDA intent resolved: ${intent}.\n\n` +
    `AIDA Core\n` +
    `${context.platform} provider status: unavailable for ${directive.commandType}.\n` +
    'No operation was executed.';
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
