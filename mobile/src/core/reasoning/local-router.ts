import { RoutedDirective } from '@/src/core/reasoning/types';

const LOCAL_ROUTES: { pattern: RegExp; command: string; intent: string }[] = [
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
