export type ReasoningContext = {
  platform: string;
  platformVersion: string;
  deviceModel: string;
  instanceId: string;
  supportedCapabilities: string[];
  conversationContext: string[];
};

export type RoutedDirective = {
  commandType: string;
  intentId: string;
  localOnly: boolean;
  confidence: number | null;
  requiresConfirmation: boolean;
  targetPath: string | null;
  slots: Record<string, unknown>;
  clarificationText: string;
};

export type ReasoningResponse = {
  text: string;
  provider: string;
  mode: 'local_fallback' | 'remote' | 'routed';
  routedDirective?: RoutedDirective;
};

export interface ReasoningProvider {
  readonly id: string;
  respond(input: string, context: ReasoningContext): Promise<ReasoningResponse>;
}
