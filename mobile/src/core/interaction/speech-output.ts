import * as Speech from 'expo-speech';

export type SpeechOutputCallbacks = {
  onStart?: () => void;
  onDone?: () => void;
  onError?: (message: string) => void;
};

export type SpeechProbeResult = {
  available: boolean;
  voiceCount: number;
  selectedVoice?: string;
  selectedLanguage?: string;
  detail: string;
};

let cachedVoiceIdentifier: string | undefined;
let cachedVoiceLanguage: string | undefined;

export async function probeAidaSpeech(): Promise<SpeechProbeResult> {
  try {
    const voices = await Speech.getAvailableVoicesAsync();
    const selected =
      voices.find((voice) => voice.language?.toLowerCase() === 'en-us') ??
      voices.find((voice) => voice.language?.toLowerCase().startsWith('en')) ??
      voices[0];

    cachedVoiceIdentifier = selected?.identifier;
    cachedVoiceLanguage = selected?.language;

    if (!selected) {
      return {
        available: false,
        voiceCount: 0,
        detail: 'Android reported no installed text-to-speech voices.',
      };
    }

    return {
      available: true,
      voiceCount: voices.length,
      selectedVoice: selected.identifier,
      selectedLanguage: selected.language,
      detail: `Android reported ${voices.length} speech voice(s). Selected ${selected.name || selected.identifier} (${selected.language}).`,
    };
  } catch (error) {
    return {
      available: false,
      voiceCount: 0,
      detail:
        error instanceof Error
          ? `Speech voice enumeration failed: ${error.message}`
          : 'Speech voice enumeration failed.',
    };
  }
}

export async function speakAidaText(
  text: string,
  callbacks: SpeechOutputCallbacks = {},
): Promise<void> {
  const clean = normalizeSpeechText(text);
  if (!clean) {
    callbacks.onError?.('Speech text was empty after normalization.');
    return;
  }

  if (!cachedVoiceIdentifier) {
    const probe = await probeAidaSpeech();
    if (!probe.available) {
      callbacks.onError?.(probe.detail);
      return;
    }
  }

  await Speech.stop();
  await wait(120);

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
      language: cachedVoiceLanguage || 'en-US',
      voice: cachedVoiceIdentifier,
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

    await wait(180);
    const active = await Speech.isSpeakingAsync();
    if (!active) {
      callbacks.onError?.(
        'Android accepted the speech request but did not report active playback.',
      );
    }
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

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}
