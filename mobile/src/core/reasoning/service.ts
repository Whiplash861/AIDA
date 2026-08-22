import { GatewayReasoningProvider } from '@/src/core/reasoning/gateway-provider';
import { LocalRuntimeReasoningProvider } from '@/src/core/reasoning/local-provider';
import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
} from '@/src/core/reasoning/types';
import { loadGatewayConfiguration } from '@/src/core/services/gateway-config';
import {
  saveGatewaySessionToken,
  saveGatewayUrl,
} from '@/src/core/storage/mobile-storage';

export type GatewayRuntimeState = {
  configured: boolean;
  source: 'development' | 'enrolled' | 'none';
  reasoningConfigured: boolean;
  speechConfigured: boolean;
  transcriptionConfigured: boolean;
  error: string;
};

class MobileReasoningService {
  private readonly localProvider = new LocalRuntimeReasoningProvider();
  private provider: ReasoningProvider = this.localProvider;
  private initialized = false;
  private gatewayState: GatewayRuntimeState = {
    configured: false,
    source: 'none',
    reasoningConfigured: false,
    speechConfigured: false,
    transcriptionConfigured: false,
    error: '',
  };

  async initialize(): Promise<void> {
    if (this.initialized) return;
    this.initialized = true;

    const configuration = await loadGatewayConfiguration();
    if (!configuration.baseUrl || !configuration.token) {
      return;
    }

    this.gatewayState = {
      ...this.gatewayState,
      configured: true,
      source: configuration.source,
    };

    try {
      const ready = await probeGateway(configuration.baseUrl, configuration.token);
      this.gatewayState = {
        configured: true,
        source: configuration.source,
        reasoningConfigured: ready.reasoning_configured,
        speechConfigured: ready.speech_configured,
        transcriptionConfigured: ready.transcription_configured,
        error: ready.reasoning_configured
          ? ''
          : 'Gateway reached, but Azure/OpenAI reasoning is not configured.',
      };
      if (ready.reasoning_configured) {
        this.provider = new GatewayReasoningProvider(
          configuration.baseUrl,
          configuration.token,
        );
      }
    } catch (error) {
      this.gatewayState = {
        ...this.gatewayState,
        error: error instanceof Error ? error.message : 'Gateway initialization failed.',
      };
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
      throw new Error(
        'Gateway reached, but Azure/OpenAI reasoning is not configured on the server.',
      );
    }

    await Promise.all([
      saveGatewayUrl(cleanUrl),
      saveGatewaySessionToken(cleanToken),
    ]);
    this.provider = new GatewayReasoningProvider(cleanUrl, cleanToken);
    this.initialized = true;
    this.gatewayState = {
      configured: true,
      source: 'enrolled',
      reasoningConfigured: true,
      speechConfigured: ready.speech_configured,
      transcriptionConfigured: ready.transcription_configured,
      error: '',
    };
  }

  currentProviderId() {
    return this.provider.id;
  }

  isRemoteConfigured() {
    return this.provider.id === 'aida-gateway';
  }

  gatewayRuntimeState(): GatewayRuntimeState {
    return { ...this.gatewayState };
  }

  async respond(
    input: string,
    context: ReasoningContext,
  ): Promise<ReasoningResponse> {
    await this.initialize();

    if (this.provider.id === this.localProvider.id) {
      return this.localProvider.respond(input, context);
    }

    // Once an authenticated gateway is active, do not silently replace a
    // failed native AIDA brain request with a canned mobile response. Native
    // AIDA surfaces brain failures; mobile must do the same.
    return this.provider.respond(input, context);
  }
}

type GatewayReadyResponse = {
  reasoning_configured?: boolean;
  speech_configured?: boolean;
  transcription_configured?: boolean;
  detail?: unknown;
};

async function probeGateway(
  baseUrl: string,
  token: string,
): Promise<{
  reasoning_configured: boolean;
  speech_configured: boolean;
  transcription_configured: boolean;
}> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/ready`, {
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
      signal: controller.signal,
    });
    const payload = (await response.json().catch(() => null)) as
      | GatewayReadyResponse
      | null;
    if (!response.ok) {
      const detail = payload?.detail ? String(payload.detail) : '';
      throw new Error(
        detail || `Gateway enrollment probe returned HTTP ${response.status}.`,
      );
    }
    return {
      reasoning_configured: Boolean(payload?.reasoning_configured),
      speech_configured: Boolean(payload?.speech_configured),
      transcription_configured: Boolean(payload?.transcription_configured),
    };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(
        'Gateway enrollment timed out. Verify the gateway host and network path.',
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export const MOBILE_REASONING = new MobileReasoningService();
