import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
} from '@/src/core/reasoning/types';

type GatewayResponse = {
  reply?: string;
  text?: string;
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
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);

    try {
      const response = await fetch(`${this.baseUrl.replace(/\/$/, '')}/v1/reasoning`, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.sessionToken}`,
        },
        body: JSON.stringify({ input, context }),
        signal: controller.signal,
      });

      const payload = (await response.json().catch(() => null)) as GatewayResponse | null;
      if (!response.ok) {
        throw new Error(`AIDA gateway returned HTTP ${response.status}.`);
      }

      const text = (payload?.reply ?? payload?.text ?? '').trim();
      if (!text) {
        throw new Error('AIDA gateway returned an empty response.');
      }

      return {
        text,
        provider: this.id,
        mode: 'remote',
      };
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('AIDA gateway request timed out.');
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
}
