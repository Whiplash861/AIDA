import { RoutedDirective } from '@/src/core/reasoning/types';

export type MobileCommandResult = {
  transcriptText: string;
  speechText: string;
  includeInContext: boolean;
  executed: boolean;
};

export type MobileCommandExecutionContext = {
  platform: string;
};

/**
 * Android command execution boundary.
 *
 * Native AIDA's CommandRouter may recognize a directive before the Brain. This
 * function is intentionally separate from routing: a recognized Windows-era
 * command is not permission to execute it on Android. Only explicitly ported
 * deterministic providers belong here.
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

  // Platform-provider implementations are added here command by command. Until
  // then, preserve the native resolved intent but do not fake execution.
  const intent = directive.intentId || directive.commandType.toLowerCase();
  const transcriptText =
    `Registered AIDA intent resolved: ${intent}.\n\n` +
    `${context.platform} provider status: unavailable for ${directive.commandType}.\n` +
    'No operation was executed.';
  const speechText =
    `${context.platform} provider unavailable for the resolved command. ` +
    'No operation was executed.';

  return {
    transcriptText,
    speechText,
    includeInContext: !directive.localOnly,
    executed: false,
  };
}
