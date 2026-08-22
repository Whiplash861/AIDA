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
        `Standalone mobile instance ${context.instanceId}. ` +
        `Platform: ${context.platform} ${context.platformVersion}. ` +
        `Device: ${context.deviceModel}. ` +
        'Local runtime, platform awareness, persistent identity, and registered device-local capabilities are online. ' +
        'Language-model reasoning gateway: not connected.';
    } else if (containsAny(normalized, ['status', 'system status', 'how are you'])) {
      text =
        `Status: local AIDA runtime online on ${context.platform} ${context.platformVersion}. ` +
        'Standalone mobile operation confirmed. Desktop AIDA not required.';
    } else if (containsAny(normalized, ['platform', 'android', 'device', 'where are you'])) {
      text =
        `Platform identified: ${context.platform} ${context.platformVersion}. ` +
        `Device: ${context.deviceModel}. Runtime mode: standalone mobile instance.`;
    } else if (containsAny(normalized, ['identity', 'instance id', 'instance'])) {
      text =
        `Instance identity: ${context.instanceId}. ` +
        'Identity storage: secure device-local persistence. Reused across application restarts.';
    } else if (containsAny(normalized, ['capability', 'capabilities', 'what can you do'])) {
      text =
        `Registered local capabilities: ${context.supportedCapabilities.join(', ')}. ` +
        'Independent language-model reasoning and deeper platform providers remain staged.';
    } else if (containsAny(normalized, ['hello', 'hi', 'hey'])) {
      text =
        'AIDA Mobile runtime online. Android environment recognized. Standalone operation confirmed.';
    } else {
      text =
        'Input received. Local runtime online. ' +
        'Language-model reasoning gateway not connected. ' +
        'Available local functions include runtime status, platform identity, persistent instance identity, and registered capability reporting.';
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
