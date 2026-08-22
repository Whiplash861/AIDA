import {
  AudioStatus,
  createAudioPlayer,
  setAudioModeAsync,
} from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import * as Speech from 'expo-speech';

import { loadGatewayConfiguration } from '@/src/core/services/gateway-config';

const START_TONE = require('../../../assets/sounds/aida_start.wav');
const END_TONE = require('../../../assets/sounds/aida_end.wav');

export type SpeechTransport = 'elevenlabs' | 'system' | 'silent';

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
  await Speech.stop();
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
  let hardFailure: string | null = null;

  try {
    // Native AIDA brackets every spoken line with the same canonical WAV
    // cues. These files are synchronized from the root repository before
    // Metro starts so desktop and mobile cannot drift independently.
    await playAudioSourceAndWait(START_TONE, 12_000);

    const gateway = await loadGatewayConfiguration();
    if (gateway.baseUrl && gateway.token) {
      try {
        await playGatewaySpeech(text, gateway.baseUrl, gateway.token);
        transport = 'elevenlabs';
      } catch (error) {
        const message =
          error instanceof Error ? error.message : 'AIDA voice service failed.';
        callbacks.onWarning?.(`AIDA ElevenLabs voice unavailable. ${message}`);
        // When AIDA voice is configured, do not impersonate it with a
        // different operating-system voice. Native AIDA simply completes the
        // speech cycle when provider audio is unavailable.
        transport = 'silent';
      }
    } else {
      callbacks.onWarning?.(
        'AIDA voice service is not configured. Android speech fallback engaged.',
      );
      await playSystemSpeech(text);
      transport = 'system';
    }
  } catch (error) {
    hardFailure =
      error instanceof Error ? error.message : 'AIDA speech sequence failed.';
  } finally {
    try {
      await playAudioSourceAndWait(END_TONE, 12_000);
    } catch (error) {
      const toneError =
        error instanceof Error ? error.message : 'AIDA end tone failed.';
      hardFailure = hardFailure ? `${hardFailure} ${toneError}` : toneError;
    }
  }

  if (hardFailure) {
    callbacks.onError?.(hardFailure);
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

async function playSystemSpeech(text: string): Promise<void> {
  await Speech.stop();

  const exposedLimit = Number(Speech.maxSpeechInputLength);
  const safeLimit =
    Number.isFinite(exposedLimit) && exposedLimit > 0
      ? Math.trunc(exposedLimit)
      : 3500;
  const utterance = text.slice(0, safeLimit);
  if (!utterance) {
    throw new Error('Speech utterance was empty.');
  }

  const voices = await Speech.getAvailableVoicesAsync();
  const englishVoice = voices.find((voice) =>
    voice.language?.toLowerCase().startsWith('en'),
  );

  await new Promise<void>((resolve, reject) => {
    Speech.speak(utterance, {
      language: 'en-US',
      voice: englishVoice?.identifier,
      rate: 0.94,
      pitch: 1.0,
      onDone: resolve,
      onStopped: resolve,
      onError: (error) => {
        reject(
          error instanceof Error
            ? error
            : new Error('AIDA system speech output failed.'),
        );
      },
    });
  });
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
        if (status.error) {
          settle(new Error(status.error));
          return;
        }
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
