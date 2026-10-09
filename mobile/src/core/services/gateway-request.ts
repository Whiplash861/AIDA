import { GatewayConfiguration } from '@/src/core/services/gateway-config';

export async function gatewayRequest<T>(
  gateway: GatewayConfiguration, path: string, body?: unknown,
  options: { timeoutMs?: number; signal?: AbortSignal; method?: string } = {},
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timeout = setTimeout(abort, options.timeoutMs ?? 35_000);
  try {
    const response = await fetch(gateway.baseUrl + path, {
      method: options.method ?? (body === undefined ? 'GET' : 'POST'),
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: 'Bearer ' + gateway.token },
      body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
    });
    if (!response.ok) {
      if (response.status === 401) throw new Error('Gateway session expired or revoked. Enroll again.');
      if (response.status === 429) throw new Error('Gateway request limit reached. Please retry shortly.');
      if (response.status === 413 || response.status === 422) throw new Error('The request exceeds the supported gateway limits.');
      throw new Error('AIDA provider is unavailable (HTTP ' + response.status + ').');
    }
    const value: unknown = await response.json();
    if (!value || typeof value !== 'object') throw new Error('Gateway returned an invalid response.');
    return value as T;
  } catch (error) {
    if (controller.signal.aborted) throw new Error(options.signal?.aborted ? 'Operation cancelled.' : 'Gateway request timed out.');
    // Do not propagate fetch/native errors containing URLs or provider payloads.
    if (error instanceof Error && /^(Gateway |AIDA provider |The request |Operation cancelled)/.test(error.message)) throw error;
    throw new Error('Gateway connection is unavailable.');
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener('abort', abort);
  }
}
