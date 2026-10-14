import {
  EngineCommandExecutionContext,
  EngineCommandResult,
  MobileEngineDefinition,
} from '@/src/core/engines/types';
import { RoutedDirective } from '@/src/core/reasoning/types';
import { unavailableReport } from '@/src/core/reporting';

const TECHNOMANCER_COMMAND_TYPES = [
  'TECHNOMANCER_HEALTH',
  'TECHNOMANCER_HARDWARE',
  'TECHNOMANCER_UPGRADES',
  'TECHNOMANCER_ADVISORIES',
  'TECHNOMANCER_BACKGROUND_ENABLE',
  'TECHNOMANCER_BACKGROUND_DISABLE',
] as const;

const COMMAND_SUBPROCESS: Record<string, string> = {
  TECHNOMANCER_HEALTH: 'health.compatibility',
  TECHNOMANCER_HARDWARE: 'inventory.hardware',
  TECHNOMANCER_UPGRADES: 'advice.upgrades',
  TECHNOMANCER_ADVISORIES: 'advice.compatibility',
  TECHNOMANCER_BACKGROUND_ENABLE: 'observer.background',
  TECHNOMANCER_BACKGROUND_DISABLE: 'observer.background',
};

async function executeTechnomancerDirective(
  directive: RoutedDirective,
  context: EngineCommandExecutionContext,
): Promise<EngineCommandResult> {
  const subprocessId = COMMAND_SUBPROCESS[directive.commandType] ?? 'engine.dispatch';
  const subprocess = TECHNOMANCER_ENGINE.subprocesses.find((item) => item.id === subprocessId);
  const label = subprocess?.label ?? subprocessId;

  return {
    transcriptText: unavailableReport('Technomancer', label, context.platform),
    speechText:
      `Technomancer recognized the request. ${label} is not yet available on ${context.platform}. No operation was executed. Open Systems to review available checks.`,
    includeInContext: !directive.localOnly,
    executed: false,
  };
}

export const TECHNOMANCER_ENGINE: MobileEngineDefinition = {
  id: 'technomancer',
  name: 'Technomancer',
  domain: 'Hardware, platform compatibility, and technical assistance',
  state: 'staged',
  detail:
    'Technomancer hardware advice and background technical checks are planned for mobile but are not available yet. Core quick and performance scans are separate, limited checks.',
  commandTypes: TECHNOMANCER_COMMAND_TYPES,
  subprocesses: [
    {
      id: 'health.compatibility',
      label: 'Platform Compatibility Health',
      state: 'staged',
      authority: 'analyze',
      provider: 'android.platform',
      detail: 'Compares Android/device capabilities against AIDA requirements and known compatibility limits.',
    },
    {
      id: 'inventory.hardware',
      label: 'Hardware and Device Inventory',
      state: 'staged',
      authority: 'observe',
      provider: 'android.device-info',
      detail: 'Reads Android-visible device, hardware, storage, display, battery, and platform inventory.',
    },
    {
      id: 'advice.upgrades',
      label: 'Upgrade Guidance',
      state: 'staged',
      authority: 'recommend',
      provider: 'technomancer.analysis',
      detail: 'Produces evidence-backed upgrade or configuration recommendations from current device capability.',
    },
    {
      id: 'advice.compatibility',
      label: 'Compatibility Advisories',
      state: 'staged',
      authority: 'recommend',
      provider: 'technomancer.analysis',
      detail: 'Reports compatibility warnings and known platform limitations without fabricating unavailable access.',
    },
    {
      id: 'observer.background',
      label: 'Background Technical Observation',
      state: 'staged',
      authority: 'observe',
      provider: 'android.background-observer',
      detail: 'Permission-aware technical observation that can be explicitly enabled or disabled by the user.',
    },
  ],
  execute: executeTechnomancerDirective,
};
