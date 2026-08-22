import { AudioStatus, createAudioPlayer, setAudioModeAsync } from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';
import * as Speech from 'expo-speech';

import {
  loadGatewaySessionToken,
  loadGatewayUrl,
} from '@/src/core/storage/mobile-storage';

export type SpeechOutputCallbacks = {
  onStart?: () => void;
  onDone?: () => void;
  onError?: (message: string) => void;
};

export async function speakAidaText(
  text: string,
  callbacks: SpeechOutputCallbacks = {},
): Promise<'elevenlabs' | 'system'> {
  const clean = normalizeSpeechText(text);
  if (!clean) {
    callbacks.onError?.('Speech text was empty after normalization.');
    return 'system';
  }

  const [gatewayUrl, gatewayToken] = await Promise.all([
    loadGatewayUrl(),
    loadGatewaySessionToken(),
  ]);

  if (gatewayUrl && gatewayToken) {
    try {
      await playGatewaySpeech(clean, gatewayUrl, gatewayToken, callbacks);
      return 'elevenlabs';
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'AIDA gateway speech failed.';
      callbacks.onError?.(`ElevenLabs gateway unavailable. Android fallback engaged. ${message}`);
    }
  }

  await playSystemSpeech(clean, callbacks);
  return 'system';
}

export async function testAidaSpeech(
  callbacks: SpeechOutputCallbacks = {},
): Promise<'elevenlabs' | 'system'> {
  return speakAidaText('Speech output online.', callbacks);
}

export function stopAidaSpeech(): Promise<void> {
  return Speech.stop();
}

async function playGatewaySpeech(
  text: string,
  baseUrl: string,
  token: string,
  callbacks: SpeechOutputCallbacks,
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

    await setAudioModeAsync({ playsInSilentMode: true });
    const player = createAudioPlayer(fileUri, { updateInterval: 120 });

    await new Promise<void>((resolve, reject) => {
      let started = false;
      let settled = false;
      const watchdog = setTimeout(() => {
        if (settled) return;
        settled = true;
        subscription.remove();
        player.remove();
        reject(new Error('ElevenLabs audio playback timed out.'));
      }, 60_000);

      const cleanup = () => {
        clearTimeout(watchdog);
        subscription.remove();
        player.remove();
        void FileSystem.deleteAsync(fileUri, { idempotent: true }).catch(() => undefined);
      };

      const subscription = player.addListener(
        'playbackStatusUpdate',
        (status: AudioStatus) => {
          if (settled) return;
          if (status.error) {
            settled = true;
            cleanup();
            reject(new Error(status.error));
            return;
          }
          if (status.playing && !started) {
            started = true;
            callbacks.onStart?.();
          }
          if (status.didJustFinish) {
            settled = true;
            callbacks.onDone?.();
            cleanup();
            resolve();
          }
        },
      );

      player.play();
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('AIDA speech gateway request timed out.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function playSystemSpeech(
  text: string,
  callbacks: SpeechOutputCallbacks,
): Promise<void> {
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

  Speech.speak(utterance, {
    language: 'en-US',
    voice: englishVoice?.identifier,
    rate: 0.94,
    pitch: 1.0,
    onStart: callbacks.onStart,
    onDone: callbacks.onDone,
    onStopped: callbacks.onDone,
    onError: (error) => {
      callbacks.onError?.(
        error instanceof Error ? error.message : 'AIDA system speech output failed.',
      );
    },
  });
}

function normalizeSpeechText(text: string) {
  return (text || '').trim().replace(/\s+/g, ' ');
}
