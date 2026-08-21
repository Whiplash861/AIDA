import { LocalRuntimeReasoningProvider } from '@/src/core/reasoning/local-provider';
import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
} from '@/src/core/reasoning/types';

class MobileReasoningService {
  private provider: ReasoningProvider = new LocalRuntimeReasoningProvider();

  setProvider(provider: ReasoningProvider) {
    this.provider = provider;
  }

  currentProviderId() {
    return this.provider.id;
  }

  respond(
    input: string,
    context: ReasoningContext,
  ): Promise<ReasoningResponse> {
    return this.provider.respond(input, context);
  }
}

export const MOBILE_REASONING = new MobileReasoningService();
