import {
  ReasoningContext,
  ReasoningProvider,
  ReasoningResponse,
} from '@/src/core/reasoning/types';
import { renderReport } from '@/src/core/reporting';

export class LocalRuntimeReasoningProvider implements ReasoningProvider {
  readonly id = 'local-runtime';

  async respond(
    input: string,
    context: ReasoningContext,
  ): Promise<ReasoningResponse> {
    const normalized = input.trim().toLowerCase();
    let text: string;

    if (
      containsAny(normalized, [
        'identify yourself',
        'who are you',
        'what are you',
        'your identity',
        'your name',
      ])
    ) {
      text = renderReport('About this AIDA instance',
        ['AIDA means Analytical Intelligent Diagnostic Agent.', `This instance is running on ${context.deviceModel}, using ${context.platform} ${context.platformVersion}.`, `Instance identifier: ${context.instanceId}.`],
        ['The reasoning service is unavailable. This local reply does not inspect the device or establish its health.'],
        ['Open Systems to see available checks, or type "quick scan" on Android. Configure the service connection in Control if you want language reasoning.']);
    } else if (containsAny(normalized, ['status', 'system status'])) {
      text = renderReport('AIDA session status', [`Local AIDA is running on ${context.platform} ${context.platformVersion}.`],
        ['The reasoning service is unavailable. A running app does not establish that the device is healthy or secure.'],
        ['Open Systems for feature availability. On Android, type "quick scan" to collect limited local observations.']);
    } else if (containsAny(normalized, ['platform', 'android', 'device'])) {
      text = renderReport('Device information', [`Platform: ${context.platform} ${context.platformVersion}. Device: ${context.deviceModel}.`],
        ['Device identity alone does not establish hardware condition or compatibility.'], ['Open Systems for supported checks. On Android, type "performance scan" to review available battery, storage, and connection information.']);
    } else if (containsAny(normalized, ['identity', 'instance id', 'instance'])) {
      text = renderReport('AIDA instance identity', [`Instance identifier: ${context.instanceId}.`],
        ['This identifier does not by itself verify whether storage is working or whether the session will be restored after restart.'], ['Check the local storage status in Systems.']);
    } else if (containsAny(normalized, ['capability', 'capabilities', 'what can you do'])) {
      text = renderReport('Available AIDA features',
        context.supportedCapabilities.length ? context.supportedCapabilities : ['No fully available features were reported for this session.'],
        ['Limited and planned features are shown separately in Systems. A feature being available does not mean a check has run or passed.'],
        ['Open Systems to review each feature’s limits. Use IMAGE or PASTE for a selected local evidence review, or type "quick scan" on Android.']);
    } else {
      text =
        'The reasoning service is not connected, so AIDA cannot answer this request here. Open Systems to review available local features, or configure the service connection in Control. Android quick scans and selected IMAGE/PASTE reviews remain available without it.';
    }

    return {
      text,
      provider: this.id,
      mode: 'local_fallback',
    };
  }
}

function containsAny(value: string, candidates: string[]) {
  return candidates.some((candidate) => value.includes(candidate));
}
