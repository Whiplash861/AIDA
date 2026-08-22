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
        'I am AIDA, the Analytical Intelligent Diagnostic Agent. ' +
        `This is my standalone mobile instance ${context.instanceId}, running locally on ` +
        `${context.platform} ${context.platformVersion} on ${context.deviceModel}. ` +
        'My full language-model reasoning gateway is not connected yet, but my local runtime, platform awareness, persistent identity, and supported device-local capabilities are online.';
    } else if (containsAny(normalized, ['status', 'system status', 'how are you'])) {
      text =
        `Local AIDA runtime is online on ${context.platform} ${context.platformVersion}. ` +
        'This mobile instance is operating independently of Desktop AIDA.';
    } else if (containsAny(normalized, ['platform', 'android', 'device', 'where are you'])) {
      text =
        `I recognize this host as ${context.platform} ${context.platformVersion} ` +
        `on ${context.deviceModel}. I am running as a standalone mobile AIDA instance.`;
    } else if (containsAny(normalized, ['identity', 'instance id', 'instance'])) {
      text =
        `This device is registered locally as ${context.instanceId}. ` +
        'The instance identity is stored securely on this device and is reused across AIDA restarts.';
    } else if (containsAny(normalized, ['capability', 'capabilities', 'what can you do'])) {
      text =
        `Current local capabilities: ${context.supportedCapabilities.join(', ')}. ` +
        'Independent cloud reasoning and deeper Android providers are staged next.';
    } else if (containsAny(normalized, ['hello', 'hi', 'hey'])) {
      text =
        'AIDA Mobile runtime online. Android environment recognized. ' +
        'I am operating locally without requiring Desktop AIDA.';
    } else {
      text =
        'Directive received by the local AIDA runtime. The Android instance is online, ' +
        'but full language-model reasoning has not been connected to the standalone gateway yet. ' +
        'I can currently report local runtime status, platform identity, persistent instance identity, and capabilities.';
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
