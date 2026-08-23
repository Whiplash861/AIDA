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
 * Native AIDA's CommandRouter recognizes intent before platform execution. The
 * mobile runtime now dispatches Engine-owned commands through the Engine
 * registry first, keeping Aegis/Technomancer/etc. responsible for their own
 * subprocesses and provider boundaries. Non-Engine core commands remain here
 * until their Android core providers are ported.
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

  // Core/platform-provider implementations such as Quickscan and Performance
  // Scan remain outside any named Engine. They will be ported into dedicated
  // Android core-provider modules instead of being incorrectly assigned to an
  // Engine merely to make them executable.
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
