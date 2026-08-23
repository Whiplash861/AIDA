import { executeAndroidCoreDiagnostic } from '@/src/core/diagnostics/android-core-diagnostics';
import { executeEngineDirective } from '@/src/core/engines/registry';
import {
  EngineCommandExecutionContext,
  EngineCommandResult,
} from '@/src/core/engines/types';
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

  const coreDiagnostic = await executeAndroidCoreDiagnostic(
    directive.commandType,
    !directive.localOnly,
  );
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
