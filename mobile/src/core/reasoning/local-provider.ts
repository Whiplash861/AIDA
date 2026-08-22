import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
} from '@/src/core/reasoning/types';

export class LocalRuntimeReasoningProvider implements ReasoningProvider {
  readonly id = 'local-runtime';

  async respond(
    input: string,
    context: ReasoningContext,
  ): Promise<ReasoningResponse> {
    const normalized = input.trim().toLowerCase();
    let text: string;

    if (
      containsAny(normalized, [
        'identify yourself',
        'who are you',
        'what are you',
        'your identity',
        'your name',
      ])
    ) {
      text =
        'AIDA. Analytical Intelligent Diagnostic Agent. ' +
        `Instance: ${context.instanceId}. ` +
        `Platform: ${context.platform} ${context.platformVersion}. ` +
        `Device: ${context.deviceModel}. ` +
        'Local runtime and registered device-local capabilities are online. ' +
        'Provider-backed language reasoning: unavailable.';
    } else if (containsAny(normalized, ['status', 'system status'])) {
      text =
        `Status: local AIDA runtime online on ${context.platform} ${context.platformVersion}. ` +
        'Provider-backed language reasoning: unavailable.';
    } else if (containsAny(normalized, ['platform', 'android', 'device'])) {
      text =
        `Platform: ${context.platform} ${context.platformVersion}. ` +
        `Device: ${context.deviceModel}.`;
    } else if (containsAny(normalized, ['identity', 'instance id', 'instance'])) {
      text =
        `Instance identity: ${context.instanceId}. ` +
        'Storage: secure device-local persistence.';
    } else if (containsAny(normalized, ['capability', 'capabilities', 'what can you do'])) {
      text =
        `Registered local capabilities: ${context.supportedCapabilities.join(', ')}. ` +
        'Unregistered operations remain unavailable.';
    } else {
      text =
        'Analysis unavailable. Provider-backed language reasoning is not connected. ' +
        'Local runtime status and registered device-local capabilities remain available.';
    }

    return {
      text,
      provider: this.id,
      mode: 'local_fallback',
    };
  }
}

function containsAny(value: string, candidates: string[]) {
  return candidates.some((candidate) => value.includes(candidate));
}
