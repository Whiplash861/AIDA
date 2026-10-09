import { GatewayReasoningProvider } from '@/src/core/reasoning/gateway-provider';
import { LocalRuntimeReasoningProvider } from '@/src/core/reasoning/local-provider';
import { resolveLocalDirective } from '@/src/core/reasoning/local-router';
import { ReasoningContext, ReasoningProvider, ReasoningResponse } from '@/src/core/reasoning/types';
import { GatewayConfiguration, loadGatewayConfiguration, setDevelopmentSession, validateGatewayUrl } from '@/src/core/services/gateway-config';
import { gatewayRequest } from '@/src/core/services/gateway-request';
import { clearGatewayEnrollment, saveGatewayEnrollment } from '@/src/core/storage/mobile-storage';

export type GatewayRuntimeState = {
  configured: boolean; source: 'development' | 'enrolled' | 'none';
  reasoningConfigured: boolean; speechConfigured: boolean; transcriptionConfigured: boolean; error: string;
};
type Ready = { reasoning_configured: boolean; speech_configured: boolean; transcription_configured: boolean; protocol_version: number };
const emptyState = (): GatewayRuntimeState => ({ configured: false, source: 'none', reasoningConfigured: false, speechConfigured: false, transcriptionConfigured: false, error: '' });

export class MobileReasoningService {
  private readonly localProvider = new LocalRuntimeReasoningProvider();
  private provider: ReasoningProvider = this.localProvider;
  private pending: Promise<void> | null = null;
  private credentialTail: Promise<void> = Promise.resolve();
  private lastAttempt = 0;
  private disconnected = false;
  private gatewayState = emptyState();

  private serializeCredentials<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.credentialTail.then(operation, operation);
    this.credentialTail = result.then(() => undefined, () => undefined);
    return result;
  }

  async initialize(force = false): Promise<void> {
    if (this.pending) return this.pending;
    if (!force && Date.now() - this.lastAttempt < 5_000) return;
    this.lastAttempt = Date.now();
    this.pending = this.serializeCredentials(async () => {
      if (this.disconnected) return;
      try {
        const configuration = await loadGatewayConfiguration();
        if (!configuration.baseUrl || !configuration.token) return;
        const enrolled = configuration.kind === 'bootstrap' ? await this.enroll(configuration) : {configuration, ready: await probeGateway(configuration)};
        this.activate(enrolled.configuration, enrolled.ready);
      } catch {
        this.provider = this.localProvider;
        this.gatewayState = { ...this.gatewayState, reasoningConfigured: false, speechConfigured: false, transcriptionConfigured: false, error: 'Gateway unavailable. Local device commands remain available; refresh or enroll again to reconnect.' };
      }
    }).finally(() => { this.pending = null; });
    return this.pending;
  }

  private async enroll(configuration: GatewayConfiguration): Promise<{configuration: GatewayConfiguration; ready: Ready}> {
    const result = await gatewayRequest<{token: string; device_id: string; expires_at: number; protocol_version: number}>(configuration, '/v1/enroll', {}, {timeoutMs: 8_000});
    if (result.protocol_version !== 2 || typeof result.token !== 'string' || !/^[A-Za-z0-9_-]{32,512}$/.test(result.token) || typeof result.device_id !== 'string' || typeof result.expires_at !== 'number' || result.expires_at <= Date.now() / 1000) throw new Error('Gateway enrollment returned an invalid session.');
    const enrolled: GatewayConfiguration = { ...configuration, token: result.token, kind: 'session', expiresAt: result.expires_at };
    try {
      const ready = await probeGateway(enrolled);
      if (configuration.source === 'development') setDevelopmentSession(enrolled);
      else await saveGatewayEnrollment({version: 2, baseUrl: enrolled.baseUrl, token: enrolled.token, deviceId: result.device_id, expiresAt: result.expires_at});
      return {configuration: enrolled, ready};
    } catch (error) {
      await gatewayRequest(enrolled, '/v1/session', undefined, {method: 'DELETE', timeoutMs: 3_000}).catch(() => undefined);
      throw error;
    }
  }

  private activate(configuration: GatewayConfiguration, ready: Ready) {
    this.provider = ready.reasoning_configured ? new GatewayReasoningProvider(configuration.baseUrl, configuration.token) : this.localProvider;
    this.gatewayState = {
      configured: true, source: configuration.source,
      reasoningConfigured: ready.reasoning_configured, speechConfigured: ready.speech_configured,
      transcriptionConfigured: ready.transcription_configured,
      error: ready.reasoning_configured ? '' : 'Gateway reached; reasoning is not configured.',
    };
  }

  configureGateway(baseUrl: string, token: string): Promise<void> {
    return this.serializeCredentials(async () => {
      const cleanToken = token.trim();
      if (!/^[\x21-\x7E]{1,512}$/.test(cleanToken)) throw new Error('Gateway enrollment token must contain printable ASCII characters.');
      const enrolled = await this.enroll({baseUrl: validateGatewayUrl(baseUrl), token: cleanToken, source: 'enrolled', kind: 'bootstrap'});
      this.disconnected = false;
      this.activate(enrolled.configuration, enrolled.ready);
      this.lastAttempt = Date.now();
    });
  }

  disconnect(): Promise<void> {
    return this.serializeCredentials(async () => {
      const configuration = await loadGatewayConfiguration();
      // A network failure must not be reported as successful remote revocation.
      if (configuration.kind === 'session') await gatewayRequest(configuration, '/v1/session', undefined, {method: 'DELETE', timeoutMs: 8_000});
      await clearGatewayEnrollment();
      setDevelopmentSession(null);
      this.disconnected = true;
      this.provider = this.localProvider;
      this.gatewayState = emptyState();
      this.lastAttempt = Date.now();
    });
  }

  currentProviderId() { return this.provider.id; }
  isRemoteConfigured() { return this.provider.id === 'aida-gateway'; }
  gatewayRuntimeState(): GatewayRuntimeState { return {...this.gatewayState}; }
  async respond(input: string, context: ReasoningContext, signal?: AbortSignal): Promise<ReasoningResponse> {
    if (signal?.aborted) throw new Error('Operation cancelled.');
    const routedDirective = resolveLocalDirective(input);
    if (routedDirective) return {text: '', provider: 'aida-local-router', mode: 'routed', routedDirective};
    await this.initialize();
    if (signal?.aborted) throw new Error('Operation cancelled.');
    return this.provider.respond(input, context, signal);
  }
}

async function probeGateway(configuration: GatewayConfiguration): Promise<Ready> {
  const result = await gatewayRequest<Ready>(configuration, '/v1/ready', undefined, {timeoutMs: 8_000});
  if (result.protocol_version !== 2 || ['reasoning_configured', 'speech_configured', 'transcription_configured'].some(key => typeof result[key as keyof Ready] !== 'boolean')) throw new Error('Gateway returned an incompatible readiness response.');
  return result;
}
export const MOBILE_REASONING = new MobileReasoningService();
