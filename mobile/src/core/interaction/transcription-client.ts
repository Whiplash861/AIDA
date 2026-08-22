import * as FileSystem from 'expo-file-system/legacy';

import { loadGatewayConfiguration } from '@/src/core/services/gateway-config';

type TranscriptionResponse = {
  transcript?: string;
  detail?: unknown;
};

export async function transcribeAidaRecording(uri: string): Promise<string> {
  const cleanUri = uri.trim();
  if (!cleanUri) {
    throw new Error('Temporary voice recording is unavailable.');
  }

  const gateway = await loadGatewayConfiguration();
  if (!gateway.baseUrl || !gateway.token) {
    throw new Error('AIDA voice transcription gateway is not configured.');
  }

  const audioBase64 = await FileSystem.readAsStringAsync(cleanUri, {
    encoding: FileSystem.EncodingType.Base64,
  });
  if (!audioBase64.trim()) {
    throw new Error('No microphone audio was captured.');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60_000);

  try {
    const response = await fetch(
      `${gateway.baseUrl.replace(/\/$/, '')}/v1/transcription`,
      {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          Authorization: `Bearer ${gateway.token}`,
        },
        body: JSON.stringify({
          audio_base64: audioBase64,
          file_extension: extensionFromUri(cleanUri),
        }),
        signal: controller.signal,
      },
    );

    const payload = (await response.json().catch(() => null)) as
      | TranscriptionResponse
      | null;
    if (!response.ok) {
      const detail = payload?.detail ? String(payload.detail) : '';
      throw new Error(
        detail || `AIDA transcription gateway returned HTTP ${response.status}.`,
      );
    }

    const transcript = payload?.transcript?.trim() ?? '';
    if (!transcript) {
      throw new Error('No intelligible speech was detected in the recording.');
    }
    return transcript;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('AIDA voice transcription timed out.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function discardAidaRecording(uri: string | null | undefined) {
  const cleanUri = uri?.trim() ?? '';
  if (!cleanUri) return;
  await FileSystem.deleteAsync(cleanUri, { idempotent: true }).catch(() => undefined);
}

function extensionFromUri(uri: string) {
  const withoutQuery = uri.split('?', 1)[0];
  const slash = withoutQuery.lastIndexOf('/');
  const dot = withoutQuery.lastIndexOf('.');
  if (dot <= slash) {
    return '.m4a';
  }
  const extension = withoutQuery.slice(dot).toLowerCase();
  return extension.length <= 16 ? extension : '.m4a';
}
