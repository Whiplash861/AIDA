import { ReasoningContext, ReasoningProvider, ReasoningResponse, RoutedDirective } from '@/src/core/reasoning/types';
import { gatewayRequest } from '@/src/core/services/gateway-request';

type Route = { matched: boolean; command_type?: string; intent_id?: string; local_only?: boolean; confidence?: number | null; requires_confirmation?: boolean; target_path?: string | null; slots?: Record<string, unknown>; clarification_text?: string };
export class GatewayReasoningProvider implements ReasoningProvider {
  readonly id = 'aida-gateway';
  private readonly conversationId = 'conversation_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2);
  constructor(private readonly baseUrl: string, private readonly sessionToken: string) {}
  async respond(input: string, context: ReasoningContext, signal?: AbortSignal): Promise<ReasoningResponse> {
    const gateway = {baseUrl: this.baseUrl, token: this.sessionToken, source: 'enrolled' as const};
    const body = { input, context: {...context, conversationId: this.conversationId, conversationContext: context.conversationContext.slice(-12).map(line => line.slice(0, 4000))} };
    const route = await gatewayRequest<Route>(gateway, '/v1/resolve', body, {timeoutMs: 10_000, signal});
    if (typeof route.matched !== 'boolean') throw new Error('Gateway returned an invalid route.');
    if (route.matched) {
      if (typeof route.command_type !== 'string' || !route.command_type) throw new Error('Gateway returned an incomplete route.');
      const routedDirective: RoutedDirective = {
        commandType: route.command_type, intentId: typeof route.intent_id === 'string' ? route.intent_id : '',
        // An unrecognized privacy classification must never opt a command into later Brain history.
        localOnly: route.local_only !== false, confidence: typeof route.confidence === 'number' ? route.confidence : null,
        requiresConfirmation: route.requires_confirmation === true, targetPath: typeof route.target_path === 'string' ? route.target_path : null,
        slots: route.slots && typeof route.slots === 'object' && !Array.isArray(route.slots) ? route.slots : {},
        clarificationText: typeof route.clarification_text === 'string' ? route.clarification_text : '',
      };
      return {text: '', provider: 'aida-intent-router', mode: 'routed', routedDirective};
    }
    const payload = await gatewayRequest<{reply?: string}>(gateway, '/v1/reasoning', body, {signal});
    if (typeof payload.reply !== 'string' || !payload.reply.trim()) throw new Error('Gateway returned an empty brain response.');
    return {text: payload.reply.trim(), provider: this.id, mode: 'remote'};
  }
}
