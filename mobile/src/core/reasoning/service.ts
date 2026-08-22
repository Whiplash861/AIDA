import { GatewayReasoningProvider } from '@/src/core/reasoning/gateway-provider';
import { LocalRuntimeReasoningProvider } from '@/src/core/reasoning/local-provider';
import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
} from '@/src/core/reasoning/types';
import {
  loadGatewaySessionToken,
  loadGatewayUrl,
  saveGatewaySessionToken,
  saveGatewayUrl,
} from '@/src/core/storage/mobile-storage';

class MobileReasoningService {
  private readonly localProvider = new LocalRuntimeReasoningProvider();
  private provider: ReasoningProvider = this.localProvider;
  private initialized = false;

  async initialize(): Promise<void> {
    if (this.initialized) return;
    this.initialized = true;

    const [storedUrl, sessionToken] = await Promise.all([
      loadGatewayUrl(),
      loadGatewaySessionToken(),
    ]);
    const environmentUrl = (
      process.env.EXPO_PUBLIC_AIDA_REASONING_GATEWAY_URL ?? ''
    ).trim();
    const gatewayUrl = storedUrl || environmentUrl;

    if (gatewayUrl && sessionToken) {
      this.provider = new GatewayReasoningProvider(gatewayUrl, sessionToken);
    }
  }

  async configureGateway(baseUrl: string, token: string): Promise<void> {
    const cleanUrl = baseUrl.trim().replace(/\/$/, '');
    const cleanToken = token.trim();
    if (!cleanUrl || !cleanToken) {
      throw new Error('Gateway URL and session token are required.');
    }

    await Promise.all([
      saveGatewayUrl(cleanUrl),
      saveGatewaySessionToken(cleanToken),
    ]);
    this.provider = new GatewayReasoningProvider(cleanUrl, cleanToken);
    this.initialized = true;
  }

  setProvider(provider: ReasoningProvider) {
    this.provider = provider;
    this.initialized = true;
  }

  currentProviderId() {
    return this.provider.id;
  }

  isRemoteConfigured() {
    return this.provider.id === 'aida-gateway';
  }

  async respond(
    input: string,
    context: ReasoningContext,
  ): Promise<ReasoningResponse> {
    await this.initialize();

    if (this.provider.id === this.localProvider.id) {
      return this.localProvider.respond(input, context);
    }

    try {
      return await this.provider.respond(input, context);
    } catch {
      return this.localProvider.respond(input, context);
    }
  }
}

export const MOBILE_REASONING = new MobileReasoningService();
