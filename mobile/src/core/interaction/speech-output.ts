import * as Speech from 'expo-speech';

export type SpeechOutputCallbacks = {
  onStart?: () => void;
  onDone?: () => void;
  onError?: (message: string) => void;
};

export async function speakAidaText(
  text: string,
  callbacks: SpeechOutputCallbacks = {},
): Promise<void> {
  const clean = normalizeSpeechText(text);
  if (!clean) {
    callbacks.onError?.('Speech text was empty after normalization.');
    return;
  }

  await Speech.stop();

  const exposedLimit = Number(Speech.maxSpeechInputLength);
  const safeLimit =
    Number.isFinite(exposedLimit) && exposedLimit > 0
      ? Math.trunc(exposedLimit)
      : 3500;
  const utterance = clean.slice(0, safeLimit);

  if (!utterance) {
    callbacks.onError?.('Speech utterance was empty.');
    return;
  }

  try {
    Speech.speak(utterance, {
      language: 'en-US',
      rate: 0.94,
      pitch: 1.0,
      onStart: callbacks.onStart,
      onDone: callbacks.onDone,
      onStopped: callbacks.onDone,
      onError: (error) => {
        callbacks.onError?.(
          error instanceof Error ? error.message : 'AIDA speech output failed.',
        );
      },
    });
  } catch (error) {
    callbacks.onError?.(
      error instanceof Error ? error.message : 'AIDA speech output failed.',
    );
  }
}

export async function testAidaSpeech(
  callbacks: SpeechOutputCallbacks = {},
): Promise<void> {
  await speakAidaText('Speech output online.', callbacks);
}

export function stopAidaSpeech(): Promise<void> {
  return Speech.stop();
}

function normalizeSpeechText(text: string) {
  return (text || '').trim().replace(/\s+/g, ' ');
}
