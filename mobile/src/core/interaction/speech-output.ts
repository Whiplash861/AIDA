import { AudioStatus, createAudioPlayer, setAudioModeAsync } from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import { loadGatewayConfiguration } from '@/src/core/services/gateway-config';
import { gatewayRequest } from '@/src/core/services/gateway-request';

const START_TONE = require('../../../assets/sounds/aida_start.wav');
const END_TONE = require('../../../assets/sounds/aida_end.wav');
export type SpeechTransport = 'elevenlabs' | 'silent' | 'cancelled';
export type SpeechOutputCallbacks = {onStart?: () => void; onDone?: () => void; onWarning?: (message: string) => void; onError?: (message: string) => void};
let speechTail: Promise<unknown> = Promise.resolve();
let generation = 0;
let queued = 0;
let activeAbort: AbortController | null = null;
let cancelPlayback: (() => void) | null = null;

export function speakAidaText(text: string, callbacks: SpeechOutputCallbacks = {}): Promise<SpeechTransport> {
  const clean = (text || '').trim().replace(/\s+/g, ' ').slice(0, 5000);
  if (!clean || queued >= 4) return Promise.resolve('silent');
  const epoch = generation;
  queued += 1;
  const result = speechTail.then(async (): Promise<SpeechTransport> => {
    if (epoch !== generation) return 'cancelled';
    const controller = new AbortController();
    activeAbort = controller;
    const check = () => { if (controller.signal.aborted || epoch !== generation) throw new Error('cancelled'); };
    try {
      callbacks.onStart?.();
      await setAudioModeAsync({playsInSilentMode: true});
      check();
      try { await playAudioSourceAndWait(START_TONE, 12_000); }
      catch { check(); callbacks.onWarning?.('AIDA start tone was unavailable.'); }
      check();
      let transport: SpeechTransport = 'silent';
      const gateway = await loadGatewayConfiguration();
      check();
      if (gateway.token && gateway.baseUrl && gateway.kind !== 'bootstrap') {
        try {
          const payload = await gatewayRequest<{audio_base64?: string; content_type?: string}>(gateway, '/v1/speech', {text: clean}, {signal: controller.signal});
          check();
          if (typeof payload.audio_base64 !== 'string' || !payload.audio_base64 || payload.audio_base64.length > 16_777_216) throw new Error('invalid audio');
          const directory = FileSystem.cacheDirectory;
          if (!directory) throw new Error('cache unavailable');
          const uri = directory + 'aida-elevenlabs-' + Date.now() + '-' + Math.random().toString(36).slice(2) + '.mp3';
          try {
            await FileSystem.writeAsStringAsync(uri, payload.audio_base64, {encoding: FileSystem.EncodingType.Base64});
            check();
            await playAudioSourceAndWait(uri, 60_000);
            check();
            transport = 'elevenlabs';
          } finally {
            await FileSystem.deleteAsync(uri, {idempotent: true}).catch(() => callbacks.onWarning?.('Temporary speech audio could not be removed.'));
          }
        } catch {
          check();
          callbacks.onWarning?.('AIDA voice service is temporarily unavailable.');
        }
      } else callbacks.onWarning?.('AIDA voice service is not configured. Spoken payload skipped.');
      check();
      try { await playAudioSourceAndWait(END_TONE, 12_000); }
      catch { check(); callbacks.onWarning?.('AIDA end tone was unavailable.'); }
      return transport;
    } catch {
      if (controller.signal.aborted || epoch !== generation) return 'cancelled';
      callbacks.onError?.('Audio output is temporarily unavailable.');
      return 'silent';
    } finally {
      if (activeAbort === controller) activeAbort = null;
      callbacks.onDone?.();
    }
  }).finally(() => { queued -= 1; });
  speechTail = result.catch(() => undefined);
  return result;
}
export function testAidaSpeech(callbacks: SpeechOutputCallbacks = {}) { return speakAidaText('Speech output online.', callbacks); }
export async function stopAidaSpeech(): Promise<void> {
  generation += 1;
  activeAbort?.abort();
  cancelPlayback?.();
  // Queued entries carry the previous generation and settle without audio.
}
export async function cleanupAidaSpeechCache(): Promise<void> {
  const directory = FileSystem.cacheDirectory;
  if (!directory || activeAbort) return;
  try {
    const files = await FileSystem.readDirectoryAsync(directory);
    for (const name of files.filter(name => /^aida-elevenlabs-[0-9]+-[a-z0-9]+\.mp3$/.test(name))) {
      const info = await FileSystem.getInfoAsync(directory + name);
      if (info.exists && 'modificationTime' in info && typeof info.modificationTime === 'number' && info.modificationTime < Date.now() / 1000 - 3600) {
        await FileSystem.deleteAsync(directory + name, {idempotent: true});
      }
    }
  } catch { /* A missing cache must not block runtime initialization. */ }
}
function playAudioSourceAndWait(source: Parameters<typeof createAudioPlayer>[0], timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const player = createAudioPlayer(source, {updateInterval: 80});
    let settled = false;
    let subscription: {remove(): void} | undefined;
    const cancel = () => settle(new Error('cancelled'));
    const watchdog = setTimeout(() => settle(new Error('playback timeout')), timeoutMs);
    function settle(error?: Error) {
      if (settled) return;
      settled = true;
      clearTimeout(watchdog);
      subscription?.remove();
      try { player.pause(); player.remove(); } catch { /* already disposed */ }
      if (cancelPlayback === cancel) cancelPlayback = null;
      if (error) reject(error); else resolve();
    }
    cancelPlayback = cancel;
    try {
      subscription = player.addListener('playbackStatusUpdate', (status: AudioStatus) => { if (status.didJustFinish) settle(); });
      player.play();
    } catch { settle(new Error('playback unavailable')); }
  });
}
