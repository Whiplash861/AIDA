import {
  AudioStatus,
  createAudioPlayer,
  setAudioModeAsync,
} from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';

import { loadGatewayConfiguration } from '@/src/core/services/gateway-config';

const START_TONE = require('../../../assets/sounds/aida_start.wav');
const END_TONE = require('../../../assets/sounds/aida_end.wav');

export type SpeechTransport = 'elevenlabs' | 'silent';

export type SpeechOutputCallbacks = {
  onStart?: () => void;
  onDone?: () => void;
  onWarning?: (message: string) => void;
  onError?: (message: string) => void;
};

let speechTail: Promise<void> = Promise.resolve();
let activePlayer: ReturnType<typeof createAudioPlayer> | null = null;

export function speakAidaText(
  text: string,
  callbacks: SpeechOutputCallbacks = {},
): Promise<SpeechTransport> {
  const clean = normalizeSpeechText(text);
  if (!clean) {
    callbacks.onError?.('Speech text was empty after normalization.');
    return Promise.resolve('silent');
  }

  return enqueueSpeech(() => runAidaSpeechSequence(clean, callbacks));
}

export function testAidaSpeech(
  callbacks: SpeechOutputCallbacks = {},
): Promise<SpeechTransport> {
  return speakAidaText('Speech output online.', callbacks);
}

export async function stopAidaSpeech(): Promise<void> {
  if (activePlayer) {
    try {
      activePlayer.pause();
      activePlayer.remove();
    } catch {
      // Player may already have completed and removed itself.
    }
    activePlayer = null;
  }
}

function enqueueSpeech(
  operation: () => Promise<SpeechTransport>,
): Promise<SpeechTransport> {
  const result = speechTail.then(operation, operation);
  speechTail = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

async function runAidaSpeechSequence(
  text: string,
  callbacks: SpeechOutputCallbacks,
): Promise<SpeechTransport> {
  callbacks.onStart?.();
  await setAudioModeAsync({ playsInSilentMode: true });

  let transport: SpeechTransport = 'silent';

  // Native AIDA treats missing/failed cue playback as an audio warning and
  // continues the spoken line. A tone failure must not suppress ElevenLabs.
  try {
    await playAudioSourceAndWait(START_TONE, 12_000);
  } catch (error) {
    callbacks.onWarning?.(`AIDA start tone failed. ${errorMessage(error)}`);
  }

  const gateway = await loadGatewayConfiguration();
  if (gateway.baseUrl && gateway.token) {
    try {
      await playGatewaySpeech(text, gateway.baseUrl, gateway.token);
      transport = 'elevenlabs';
    } catch (error) {
      callbacks.onWarning?.(
        `AIDA ElevenLabs voice unavailable. ${errorMessage(error)}`,
      );
      // Native AIDA never substitutes a different operating-system voice for
      // the configured ElevenLabs identity. Complete the cue cycle silently.
      transport = 'silent';
    }
  } else {
    callbacks.onWarning?.(
      'AIDA voice service is not configured. Spoken payload skipped.',
    );
  }

  try {
    await playAudioSourceAndWait(END_TONE, 12_000);
  } catch (error) {
    callbacks.onWarning?.(`AIDA end tone failed. ${errorMessage(error)}`);
  }

  callbacks.onDone?.();
  return transport;
}

async function playGatewaySpeech(
  text: string,
  baseUrl: string,
  token: string,
): Promise<void> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 50_000);

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/speech`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });

    const payload = (await response.json().catch(() => null)) as
      | { audio_base64?: string; content_type?: string; detail?: string }
      | null;

    if (!response.ok) {
      throw new Error(
        payload?.detail || `AIDA speech gateway returned HTTP ${response.status}.`,
      );
    }

    const audioBase64 = payload?.audio_base64?.trim() ?? '';
    if (!audioBase64) {
      throw new Error('AIDA speech gateway returned empty audio.');
    }

    const cacheDirectory = FileSystem.cacheDirectory;
    if (!cacheDirectory) {
      throw new Error('AIDA audio cache directory is unavailable.');
    }

    const fileUri = `${cacheDirectory}aida-elevenlabs-${Date.now()}.mp3`;
    await FileSystem.writeAsStringAsync(fileUri, audioBase64, {
      encoding: FileSystem.EncodingType.Base64,
    });

    try {
      await playAudioSourceAndWait(fileUri, 60_000);
    } finally {
      await FileSystem.deleteAsync(fileUri, { idempotent: true }).catch(
        () => undefined,
      );
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('AIDA speech gateway request timed out.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function playAudioSourceAndWait(
  source: Parameters<typeof createAudioPlayer>[0],
  timeoutMs: number,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const player = createAudioPlayer(source, { updateInterval: 80 });
    activePlayer = player;
    let settled = false;

    const watchdog = setTimeout(() => {
      settle(new Error('AIDA audio playback timed out.'));
    }, timeoutMs);

    const subscription = player.addListener(
      'playbackStatusUpdate',
      (status: AudioStatus) => {
        // Expo SDK 54 AudioStatus has no playback error field. Playback API
        // exceptions are handled synchronously and an uncompleted player is
        // bounded by the watchdog below.
        if (status.didJustFinish) {
          settle();
        }
      },
    );

    function settle(error?: Error) {
      if (settled) return;
      settled = true;
      clearTimeout(watchdog);
      subscription.remove();
      try {
        player.remove();
      } catch {
        // No-op if Expo already disposed the player.
      }
      if (activePlayer === player) {
        activePlayer = null;
      }
      if (error) reject(error);
      else resolve();
    }

    try {
      player.play();
    } catch (error) {
      settle(
        error instanceof Error ? error : new Error('AIDA audio playback failed.'),
      );
    }
  });
}

function normalizeSpeechText(text: string) {
  return (text || '').trim().replace(/\s+/g, ' ');
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Unknown audio error.';
}
