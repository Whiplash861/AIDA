import { RoutedDirective } from '@/src/core/reasoning/types';

export type MobileEngineId =
  | 'aegis'
  | 'artificer'
  | 'technomancer'
  | 'perception';

export type EngineRuntimeState = 'active' | 'limited' | 'staged';
export type EngineSubprocessState = 'supported' | 'limited' | 'staged';
export type EngineAuthority = 'observe' | 'analyze' | 'recommend' | 'execute';

export type EngineSubprocessDefinition = {
  id: string;
  label: string;
  state: EngineSubprocessState;
  authority: EngineAuthority;
  detail: string;
  provider?: string;
};

export type EngineCommandExecutionContext = {
  platform: string;
};

export type EngineCommandResult = {
  transcriptText: string;
  speechText: string;
  includeInContext: boolean;
  executed: boolean;
};

export type MobileEngineDefinition = {
  id: MobileEngineId;
  name: string;
  domain: string;
  state: EngineRuntimeState;
  detail: string;
  commandTypes: readonly string[];
  subprocesses: readonly EngineSubprocessDefinition[];
  execute?: (
    directive: RoutedDirective,
    context: EngineCommandExecutionContext,
  ) => Promise<EngineCommandResult>;
};
