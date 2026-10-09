import { RoutedDirective } from '@/src/core/reasoning/types';

const LOCAL_ROUTES: { pattern: RegExp; command: string; intent: string }[] = [
  { pattern: /^(?:save|set)\s+(?:diagnostic\s+)?baseline[.!]?$/i, command: 'SAVE_BASELINE', intent: 'diagnostics.baseline.save' },
  { pattern: /^(?:compare|show\s+changes\s+(?:from|since))\s+(?:the\s+)?baseline[.!]?$/i, command: 'COMPARE_BASELINE', intent: 'diagnostics.baseline.compare' },
  { pattern: /^(?:run\s+)?follow[- ]up\s+scan[.!]?$/i, command: 'FOLLOW_UP_SCAN', intent: 'diagnostics.followup' },
  { pattern: /^export\s+(?:diagnostic\s+)?case[.!]?$/i, command: 'CASE_EXPORT', intent: 'case.export.review' },
  { pattern: /^copy\s+reviewed\s+case[.!]?$/i, command: 'CASE_COPY', intent: 'case.export.copy' },
  { pattern: /^import\s+reviewed\s+case[.!]?$/i, command: 'CASE_IMPORT', intent: 'case.import.accept' },
  { pattern: /^discard\s+reviewed\s+case[.!]?$/i, command: 'CASE_DISCARD', intent: 'case.review.discard' },
  { pattern: /^show\s+imported\s+case[.!]?$/i, command: 'CASE_SHOW', intent: 'case.import.show' },
  { pattern: /^(?:(?:run|perform|start)\s+)?(?:a\s+)?quick\s*scan[.!]?$/i, command: 'QUICKSCAN', intent: 'diagnostics.quickscan' },
  { pattern: /^(?:(?:run|perform|start)\s+)?(?:a\s+)?performance\s+scan[.!]?$/i, command: 'PERFORMANCE_SCAN', intent: 'diagnostics.performance' },
  { pattern: /^(?:(?:show|check)\s+)?(?:aegis\s+)?security\s+status[.!]?$/i, command: 'SECURITY_STATUS', intent: 'security.status' },
  { pattern: /^(?:(?:run|perform|start)\s+)?(?:a\s+)?surface\s+(?:security\s+)?scan[.!]?$/i, command: 'SECURITY_SURFACE_SCAN', intent: 'security.scan.surface' },
  { pattern: /^show\s+(?:the\s+)?last\s+(?:diagnostic|scan|result)[.!]?$/i, command: 'DIAGNOSTIC_LAST', intent: 'diagnostics.last' },
];
// Local/private command families fail closed when no mobile executor is registered.
// Quoted prose and explanatory questions do not become executable local commands.
const PRIVATE_COMMAND = /^(?:(?:please|aida)[, ]+)?(?:remember\b|(?:add|save|delete|forget|revise|search|show)\s+memor(?:y|ies)\b|(?:run\s+)?deep\s+scan\b|(?:run\s+)?full(?:-system)?\s+sweep\b|stand\s+down\b|(?:analyze|remediate|delete)\s+(?:that|this|the)\s+(?:file|threat)\b|(?:show\s+)?(?:hardware\s+inventory|technomancer\b|autonomy\b))/i;

export function resolveLocalDirective(input: string): RoutedDirective | null {
  const clean = input.trim().replace(/^please\s+/i, '');
  const found = LOCAL_ROUTES.find((route) => route.pattern.test(clean));
  if (!found && !PRIVATE_COMMAND.test(clean)) return null;
  return {
    commandType: found?.command ?? 'MOBILE_UNAVAILABLE', intentId: found?.intent ?? 'mobile.private.unavailable',
    localOnly: true, confidence: 1, requiresConfirmation: false, targetPath: null, slots: {}, clarificationText: '',
  };
}
