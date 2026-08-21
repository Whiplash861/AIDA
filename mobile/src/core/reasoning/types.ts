export type ReasoningContext = {
  platform: string;
  platformVersion: string;
  deviceModel: string;
  instanceId: string;
  supportedCapabilities: string[];
};

export type ReasoningResponse = {
  text: string;
  provider: string;
  mode: 'local_fallback' | 'remote';
};

export interface ReasoningProvider {
  readonly id: string;
  respond(input: string, context: ReasoningContext): Promise<ReasoningResponse>;
}
