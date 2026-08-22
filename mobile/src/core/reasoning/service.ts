import { GatewayReasoningProvider } from '@/src/core/reasoning/gateway-provider';
import { LocalRuntimeReasoningProvider } from '@/src/core/reasoning/local-provider';
import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
} from '@/src/core/reasoning/types';
import { loadGatewaySessionToken } from '@/src/core/storage/mobile-storage';

class MobileReasoningService {
  private readonly localProvider = new LocalRuntimeReasoningProvider();
  private provider: ReasoningProvider = this.localProvider;
  private initialized = false;

  async initialize(): Promise<void> {
    if (this.initialized) {
      return;
    }
    this.initialized = true;

    const gatewayUrl = (
      process.env.EXPO_PUBLIC_AIDA_REASONING_GATEWAY_URL ?? ''
    ).trim();
    const sessionToken = await loadGatewaySessionToken();

    if (gatewayUrl && sessionToken) {
      this.provider = new GatewayReasoningProvider(gatewayUrl, sessionToken);
    }
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
