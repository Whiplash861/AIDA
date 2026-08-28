import {
  loadGatewaySessionToken,
  loadGatewayUrl,
} from '@/src/core/storage/mobile-storage';

export type GatewayConfiguration = {
  baseUrl: string;
  token: string;
  source: 'development' | 'enrolled' | 'none';
};

export async function loadGatewayConfiguration(): Promise<GatewayConfiguration> {
  const developmentUrl = (
    process.env.EXPO_PUBLIC_AIDA_DEV_GATEWAY_URL ?? ''
  ).trim().replace(/\/$/, '');
  const developmentToken = (
    process.env.EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN ?? ''
  ).trim();

  // Development auto-enrollment intentionally takes precedence over stored
  // credentials. The dev launcher creates these values ephemerally in the
  // ignored mobile/.env.local file for one local test session.
  if (developmentUrl && developmentToken) {
    return {
      baseUrl: developmentUrl,
      token: developmentToken,
      source: 'development',
    };
  }

  const [storedUrl, storedToken] = await Promise.all([
    loadGatewayUrl(),
    loadGatewaySessionToken(),
  ]);

  if (storedUrl && storedToken) {
    return {
      baseUrl: storedUrl.replace(/\/$/, ''),
      token: storedToken,
      source: 'enrolled',
    };
  }

  // The production gateway URL is public configuration and may safely ship in
  // an application build. Credentials are deliberately excluded. Returning the
  // URL here only pre-fills Control; AIDA remains unenrolled until a revocable
  // session/enrollment credential is stored in SecureStore.
  const productionUrl = (
    process.env.EXPO_PUBLIC_AIDA_GATEWAY_URL ?? ''
  ).trim().replace(/\/$/, '');

  if (productionUrl) {
    return {
      baseUrl: productionUrl,
      token: '',
      source: 'none',
    };
  }

  return { baseUrl: '', token: '', source: 'none' };
}
