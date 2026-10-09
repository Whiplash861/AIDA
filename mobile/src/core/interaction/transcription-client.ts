import * as FileSystem from 'expo-file-system/legacy';
import { loadGatewayConfiguration } from '@/src/core/services/gateway-config';
import { gatewayRequest } from '@/src/core/services/gateway-request';

export async function transcribeAidaRecording(uri: string, signal?: AbortSignal): Promise<string> {
  if (!uri.trim()) throw new Error('Temporary voice recording is unavailable.');
  if (signal?.aborted) throw new Error('Operation cancelled.');
  const gateway = await loadGatewayConfiguration();
  if (!gateway.baseUrl || !gateway.token || gateway.kind === 'bootstrap') throw new Error('AIDA voice transcription gateway is not configured.');
  const info = await FileSystem.getInfoAsync(uri);
  if (!info.exists || !('size' in info) || info.size > 12_000_000) throw new Error('Recording is unavailable or exceeds the supported size.');
  const audio = await FileSystem.readAsStringAsync(uri, {encoding: FileSystem.EncodingType.Base64});
  if (!audio.trim()) throw new Error('No microphone audio was captured.');
  const payload = await gatewayRequest<{transcript?: string}>(gateway, '/v1/transcription', {audio_base64: audio, file_extension: extensionFromUri(uri)}, {signal});
  if (typeof payload.transcript !== 'string' || !payload.transcript.trim()) throw new Error('No intelligible speech was detected in the recording.');
  if (payload.transcript.length > 8000) throw new Error('Voice transcription exceeds the supported directive length.');
  return payload.transcript.trim();
}
export async function discardAidaRecording(uri: string | null | undefined) {
  if (uri?.trim()) await FileSystem.deleteAsync(uri, {idempotent: true});
}
function extensionFromUri(uri: string) {
  const extension = uri.split('?', 1)[0].match(/\.[a-zA-Z0-9]+$/)?.[0].toLowerCase();
  return extension && ['.m4a', '.wav', '.mp3', '.webm', '.mp4', '.ogg'].includes(extension) ? extension : '.m4a';
}
