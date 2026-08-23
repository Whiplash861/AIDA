import { MobileEngineDefinition } from '@/src/core/engines/types';

export const ARTIFICER_ENGINE: MobileEngineDefinition = {
  id: 'artificer',
  name: 'Artificer',
  domain: 'Compatibility review, maintenance, and engineering governance',
  state: 'staged',
  detail:
    'Android Artificer owns platform compatibility observation, bounded maintenance proposals, developer reporting, and cross-Engine engineering review without silently expanding its authority.',
  commandTypes: [],
  subprocesses: [
    {
      id: 'observer.os-compatibility',
      label: 'OS Compatibility Observer',
      state: 'staged',
      authority: 'observe',
      provider: 'android.platform',
      detail: 'Compares Android capabilities, permissions, dependencies, and behavior against AIDA implementation requirements.',
    },
    {
      id: 'review.engineering',
      label: 'Engineering Review',
      state: 'staged',
      authority: 'analyze',
      provider: 'artificer.review',
      detail: 'Reviews AIDA and Engine compatibility findings and produces auditable recommendations.',
    },
    {
      id: 'maintenance.low-risk',
      label: 'Bounded Low-Risk Maintenance',
      state: 'staged',
      authority: 'execute',
      provider: 'artificer.policy',
      detail: 'Reserves only explicitly authorized low-risk maintenance operations for future Android support.',
    },
    {
      id: 'telemetry.consent',
      label: 'Consent and Telemetry Governance',
      state: 'staged',
      authority: 'observe',
      provider: 'artificer.governance',
      detail: 'Keeps field telemetry opt-in, minimized, sanitized, auditable, and revocable.',
    },
    {
      id: 'developers.registry',
      label: 'Developer Registry',
      state: 'staged',
      authority: 'observe',
      provider: 'artificer.governance',
      detail: 'Maintains the controlled destination registry for authorized Artificer findings and engineering reports.',
    },
  ],
};
