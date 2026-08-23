import { executeAndroidAegisCommand } from '@/src/core/engines/aegis/android-provider';
import { AEGIS_ENGINE } from '@/src/core/engines/aegis/manifest';
import { ARTIFICER_ENGINE } from '@/src/core/engines/artificer/manifest';
import { PERCEPTION_ENGINE } from '@/src/core/engines/perception/manifest';
import { TECHNOMANCER_ENGINE } from '@/src/core/engines/technomancer/manifest';
import {
  EngineCommandExecutionContext,
  EngineCommandResult,
  MobileEngineDefinition,
} from '@/src/core/engines/types';
import { RoutedDirective } from '@/src/core/reasoning/types';

export const MOBILE_ENGINE_CATALOG: readonly MobileEngineDefinition[] = [
  AEGIS_ENGINE,
  ARTIFICER_ENGINE,
  TECHNOMANCER_ENGINE,
  PERCEPTION_ENGINE,
];

const COMMAND_ENGINE_MAP = new Map<string, MobileEngineDefinition>();
for (const engine of MOBILE_ENGINE_CATALOG) {
  for (const commandType of engine.commandTypes) {
    if (COMMAND_ENGINE_MAP.has(commandType)) {
      throw new Error(`Mobile command ${commandType} is owned by more than one Engine.`);
    }
    COMMAND_ENGINE_MAP.set(commandType, engine);
  }
}

export function engineForCommand(commandType: string): MobileEngineDefinition | null {
  return COMMAND_ENGINE_MAP.get(commandType) ?? null;
}

export async function executeEngineDirective(
  directive: RoutedDirective,
  context: EngineCommandExecutionContext,
): Promise<EngineCommandResult | null> {
  const engine = engineForCommand(directive.commandType);
  if (!engine) return null;

  // Platform providers are attempted before the Engine's staged fallback.
  // This keeps the Engine contract stable while allowing Android capability
  // slices to graduate independently as genuine providers become available.
  if (engine.id === 'aegis') {
    const androidAegisResult = await executeAndroidAegisCommand(directive, context);
    if (androidAegisResult) return androidAegisResult;
  }

  if (!engine.execute) {
    const intent = directive.intentId || directive.commandType.toLowerCase();
    return {
      transcriptText:
        `Registered AIDA intent resolved: ${intent}.\n\n` +
        `Engine: ${engine.name}\n` +
        `${context.platform} Engine provider status: ${engine.state}.\n` +
        'No operation was executed.',
      speechText:
        `${engine.name} recognized the directive, but its ${context.platform} provider is ` +
        `${engine.state}. No operation was executed.`,
      includeInContext: !directive.localOnly,
      executed: false,
    };
  }

  return engine.execute(directive, context);
}

export function engineSubprocessTotals(engine: MobileEngineDefinition) {
  const total = engine.subprocesses.length;
  const supported = engine.subprocesses.filter((item) => item.state === 'supported').length;
  const limited = engine.subprocesses.filter((item) => item.state === 'limited').length;
  const staged = engine.subprocesses.filter((item) => item.state === 'staged').length;
  return { total, supported, limited, staged };
}
