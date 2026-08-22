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

    const ready = await probeGateway(cleanUrl, cleanToken);
    if (!ready.reasoning_configured) {
      throw new Error('Gateway reached, but Azure/OpenAI reasoning is not configured on the server.');
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

    return this.provider.respond(input, context);
  }
}

type GatewayReadyResponse = {
  reasoning_configured?: boolean;
  speech_configured?: boolean;
};

async function probeGateway(
  baseUrl: string,
  token: string,
): Promise<{ reasoning_configured: boolean; speech_configured: boolean }> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);

  try {
    const response = await fetch(`${baseUrl}/v1/ready`, {
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
      signal: controller.signal,
    });
    const payload = (await response.json().catch(() => null)) as GatewayReadyResponse | null;
    if (!response.ok) {
      const detail =
        payload && typeof payload === 'object' && 'detail' in payload
          ? String((payload as { detail?: unknown }).detail ?? '')
          : '';
      throw new Error(
        detail || `Gateway enrollment probe returned HTTP ${response.status}.`,
      );
    }
    return {
      reasoning_configured: Boolean(payload?.reasoning_configured),
      speech_configured: Boolean(payload?.speech_configured),
    };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('Gateway enrollment timed out. Verify the URL, network, and Windows Firewall.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export const MOBILE_REASONING = new MobileReasoningService();
