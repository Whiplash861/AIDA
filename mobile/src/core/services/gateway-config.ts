import { loadGatewayEnrollment, loadLegacyGateway } from '@/src/core/storage/mobile-storage';

export type GatewayConfiguration = {
  baseUrl: string; token: string; source: 'development' | 'enrolled' | 'none';
  kind?: 'session' | 'bootstrap'; expiresAt?: number;
};
let developmentSession: GatewayConfiguration | null = null;
export function setDevelopmentSession(value: GatewayConfiguration | null) { developmentSession = value; }

export function validateGatewayUrl(value: string, development = false): string {
  let url: URL;
  try { url = new URL(value.trim()); } catch { throw new Error('Gateway address must be a valid HTTPS URL.'); }
  if (url.username || url.password || url.search || url.hash) throw new Error('Gateway address cannot contain credentials, query parameters, or fragments.');
  if (url.protocol !== 'https:' && !(development && url.protocol === 'http:')) {
    throw new Error('An enrolled gateway requires HTTPS.');
  }
  return url.toString().replace(/\/$/, '');
}
export async function loadGatewayConfiguration(): Promise<GatewayConfiguration> {
  const developmentUrl = (process.env.EXPO_PUBLIC_AIDA_DEV_GATEWAY_URL ?? '').trim();
  const developmentToken = (process.env.EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN ?? '').trim();
  if ((developmentUrl || developmentToken) && !__DEV__) throw new Error('Development gateway credentials are forbidden in release builds.');
  if (__DEV__ && developmentUrl && developmentToken) {
    const baseUrl = validateGatewayUrl(developmentUrl, true);
    if (developmentSession?.baseUrl === baseUrl) return developmentSession;
    return { baseUrl, token: developmentToken, source: 'development', kind: 'bootstrap' };
  }
  const stored = await loadGatewayEnrollment();
  if (stored) return { baseUrl: validateGatewayUrl(stored.baseUrl), token: stored.token, source: 'enrolled', kind: 'session', expiresAt: stored.expiresAt };
  const legacy = await loadLegacyGateway();
  if (legacy) return { baseUrl: validateGatewayUrl(legacy.baseUrl), token: legacy.token, source: 'enrolled', kind: 'bootstrap' };
  const publicUrl = (process.env.EXPO_PUBLIC_AIDA_GATEWAY_URL ?? '').trim();
  return { baseUrl: publicUrl ? validateGatewayUrl(publicUrl) : '', token: '', source: 'none' };
}
