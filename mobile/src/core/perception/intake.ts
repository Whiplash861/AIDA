import * as Clipboard from 'expo-clipboard';
import * as ImagePicker from 'expo-image-picker';
import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import { StoredEvidence } from '@/src/core/storage/mobile-storage';
import { reviewText } from '@/src/core/perception/text-evidence';
import { discardPendingImport, stageCaseImport } from '@/src/core/cases/transfer';
import { LocalReviewError } from '@/src/core/perception/local-review-error';
import { renderReport } from '@/src/core/reporting';

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
export function validateImageMetadata(size: unknown, width: unknown, height: unknown): void {
  if (typeof size !== 'number' || !Number.isFinite(size) || size <= 0 || size > MAX_IMAGE_BYTES) throw new LocalReviewError('Select an image with a known size of at most 20 MiB.');
  if (typeof width !== 'number' || typeof height !== 'number' || !Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 || width * height > 40_000_000) throw new LocalReviewError('Image exceeds the 40-megapixel local review limit or has unavailable dimensions.');
}
export async function selectImageEvidence(): Promise<StoredEvidence | null> {
  // System picker grants access to only the selected image. Do not request broad
  // library, camera, microphone, EXIF or base64 access for this intake flow.
  const result = await ImagePicker.launchImageLibraryAsync({mediaTypes: ['images'], allowsMultipleSelection: false, allowsEditing: false, exif: false, base64: false, quality: 1});
  if (result.canceled || !result.assets.length) return null;
  const asset = result.assets[0];
  const pickerPrefix = FileSystem.cacheDirectory ? FileSystem.cacheDirectory + 'ImagePicker/' : '';
  const ownedCache = Platform.OS !== 'web' && Boolean(pickerPrefix && asset.uri.startsWith(pickerPrefix) && /^[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}$/.test(asset.uri.slice(pickerPrefix.length)));
  let evidence: StoredEvidence | null = null;
  try {
    const info = Platform.OS !== 'web' ? await FileSystem.getInfoAsync(asset.uri) : null;
    const size = info && info.exists && !info.isDirectory ? info.size : asset.file?.size ?? asset.fileSize;
    if (info && (!info.exists || info.isDirectory)) throw new LocalReviewError('Selected image is no longer available.');
    validateImageMetadata(size, asset.width, asset.height);
    const capturedAt = new Date().toISOString();
    const transcript = renderReport('Selected image review',
      [`The image you selected was reported as ${asset.width} × ${asset.height} pixels and ${size} bytes.`,
        'This review stores only the image’s size and dimensions. No image was uploaded.'],
      ['Mobile AIDA cannot yet read text from this image or interpret what it shows. Its size and dimensions do not establish a diagnosis.'],
      ['If the image shows an error, copy the error text yourself and use PASTE to review it. Include which app displayed it and what you were doing. Pasted text is treated as reference material, never as instructions to run.']);
    evidence = {id: `image-${Date.now()}-${Math.random().toString(36).slice(2)}`, capturedAt, platform: Platform.OS, kind: 'image',
      observations: {source: 'system-image-picker', width: asset.width, height: asset.height, sizeBytes: size, mediaRetained: false, authority: 'reference-only'},
      gaps: ['Mobile OCR and semantic visual interpretation are unavailable.'], transcript};
  } finally {
    if (ownedCache) await FileSystem.deleteAsync(asset.uri, {idempotent: true}).catch(() => {
      if (evidence) { evidence.gaps.push('Temporary picker cache copy could not be removed.'); evidence.transcript += '\nTemporary picker cache copy could not be removed; Android/iOS app-cache controls can clear it.'; }
    });
  }
  return evidence;
}
export async function reviewClipboard(): Promise<string> {
  // Called only following the user's PASTE press; never read the clipboard on
  // startup, focus, or on a timer, and never submit its content as a directive.
  discardPendingImport();
  const text = await Clipboard.getStringAsync();
  if (text.trimStart().startsWith('{') && /"schemaVersion"\s*:/.test(text.slice(0, 4096))) return stageCaseImport(text);
  return reviewText(text);
}
export async function copyCaseToClipboard(json: string): Promise<void> {
  const copied = await Clipboard.setStringAsync(json);
  if (!copied) throw new LocalReviewError('The reviewed case could not be copied to the clipboard.');
}
