import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
  RoutedDirective,
} from '@/src/core/reasoning/types';

type GatewayReasoningResponse = {
  reply?: string;
  text?: string;
  detail?: unknown;
};

type GatewayResolveResponse = {
  matched?: boolean;
  command_type?: string;
  intent_id?: string;
  local_only?: boolean;
  confidence?: number | null;
  requires_confirmation?: boolean;
  target_path?: string | null;
  slots?: Record<string, unknown>;
  clarification_text?: string;
  detail?: unknown;
};

export class GatewayReasoningProvider implements ReasoningProvider {
  readonly id = 'aida-gateway';

  constructor(
    private readonly baseUrl: string,
    private readonly sessionToken: string,
  ) {}

  async respond(
    input: string,
    context: ReasoningContext,
  ): Promise<ReasoningResponse> {
    const routePayload = await this.postJson<GatewayResolveResponse>(
      '/v1/resolve',
      { input, context },
      10_000,
    );

    if (routePayload.matched) {
      const routedDirective: RoutedDirective = {
        commandType: (routePayload.command_type ?? '').trim(),
        intentId: (routePayload.intent_id ?? '').trim(),
        localOnly: Boolean(routePayload.local_only),
        confidence:
          typeof routePayload.confidence === 'number'
            ? routePayload.confidence
            : null,
        requiresConfirmation: Boolean(routePayload.requires_confirmation),
        targetPath: routePayload.target_path ?? null,
        slots: routePayload.slots ?? {},
        clarificationText: (routePayload.clarification_text ?? '').trim(),
      };

      if (!routedDirective.commandType) {
        throw new Error('AIDA intent resolver returned an incomplete route.');
      }

      return {
        text: '',
        provider: 'aida-intent-router',
        mode: 'routed',
        routedDirective,
      };
    }

    const payload = await this.postJson<GatewayReasoningResponse>(
      '/v1/reasoning',
      { input, context },
      25_000,
    );
    const text = (payload.reply ?? payload.text ?? '').trim();
    if (!text) {
      throw new Error('AIDA gateway returned an empty brain response.');
    }

    return {
      text,
      provider: this.id,
      mode: 'remote',
    };
  }

  private async postJson<T extends { detail?: unknown }>(
    path: string,
    body: unknown,
    timeoutMs: number,
  ): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(`${this.baseUrl.replace(/\/$/, '')}${path}`, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.sessionToken}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      const payload = (await response.json().catch(() => null)) as T | null;
      if (!response.ok) {
        const detail = payload?.detail ? String(payload.detail) : '';
        throw new Error(
          detail || `AIDA gateway returned HTTP ${response.status} for ${path}.`,
        );
      }
      if (!payload) {
        throw new Error(`AIDA gateway returned invalid JSON for ${path}.`);
      }
      return payload;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error(`AIDA gateway request timed out for ${path}.`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
}
