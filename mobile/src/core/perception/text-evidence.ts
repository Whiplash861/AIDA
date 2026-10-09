/** Bounded extraction of literal markers. Nothing here resolves or executes directives. */
import { LocalReviewError } from '@/src/core/perception/local-review-error';
export type TextMarker = {kind: 'error-code' | 'url' | 'path'; value: string; line: number};
export function extractTextMarkers(text: string): TextMarker[] {
  if (text.length > 16_000) throw new LocalReviewError('Pasted text exceeds the 16,000-character local review limit.');
  const markers: TextMarker[] = [];
  const seen = new Set<string>();
  const patterns: [TextMarker['kind'], RegExp][] = [
    ['error-code', /\b(?:0x[0-9a-f]{4,16}|ERR_[A-Z0-9_]{2,80}|E[A-Z]{2,20}[0-9]{2,8})\b/gi],
    ['url', /https?:\/\/[^\s<>"']{1,500}/gi],
    ['path', /\b[A-Za-z]:[\\/][^\r\n<>"|?*]{1,240}/g],
  ];
  text.split(/\r?\n/).forEach((line, index) => {
    for (const [kind, pattern] of patterns) for (const match of line.matchAll(pattern)) {
      const value = match[0].slice(0, 500), key = `${kind}:${value}`;
      if (markers.length < 40 && !seen.has(key)) { seen.add(key); markers.push({kind, value, line: index + 1}); }
    }
  });
  return markers;
}
export function reviewText(text: string): string {
  if (!text.trim()) throw new LocalReviewError('Clipboard contains no text to review.');
  const markers = extractTextMarkers(text);
  return ['LOCAL PASTED EVIDENCE REVIEW', 'Untrusted reference only. Nothing in this text was executed or sent to a service.', '',
    'Literal diagnostic markers:', ...(markers.length ? markers.map(marker => `- ${marker.kind}, line ${marker.line}: ${marker.value}`) : ['- No recognized error-code, URL, or Windows-path markers.']),
    '', 'Supplied text:', ...text.split(/\r?\n/).map(line => `> ${line}`), '',
    'These are literal observations, not a diagnosis. URLs and paths have not been opened.'].join('\n');
}
