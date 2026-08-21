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
  const clean = text.trim();
  if (!clean) {
    return;
  }

  await Speech.stop();

  Speech.speak(clean.slice(0, Speech.maxSpeechInputLength), {
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
}

export function stopAidaSpeech(): Promise<void> {
  return Speech.stop();
}
