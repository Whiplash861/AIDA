export type HealthResponse = {
  service: string;
  status: 'ready' | 'degraded';
  version: string;
  brain_configured: boolean;
  pairing_configured: boolean;
};

export type ChatHistoryMessage = {
  role: 'user' | 'assistant';
  content: string;
};

export type MobileDevice = {
  platform: string;
  model: string;
  app_version: string;
};

export type ChatResponse = {
  request_id: string;
  reply: string;
  status: 'complete';
  created_at: string;
};

export type StatusTone =
  | 'ready'
  | 'active'
  | 'warning'
  | 'error'
  | 'idle'
  | 'offline';

export type SubsystemStatus = {
  id: string;
  label: string;
  value: string;
  tone: StatusTone;
};

export type OperationalStatusResponse = {
  host_platform: string;
  desktop_online: boolean;
  updated_at: string;
  heartbeat_at: string;
  statuses: SubsystemStatus[];
  autonomy: {
    enabled: boolean;
    label: string;
  };
};

export type ActivityItem = {
  id: string;
  category: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
  source: string;
  created_at: string;
};

export type ActivityResponse = {
  items: ActivityItem[];
};

const API_URL = (process.env.EXPO_PUBLIC_AIDA_API_URL ?? '')
  .trim()
  .replace(/\/$/, '');

const PAIRING_TOKEN = (
  process.env.EXPO_PUBLIC_AIDA_PAIRING_TOKEN ?? ''
).trim();

export function configuredApiUrl() {
  return API_URL;
}

export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health', { method: 'GET' }, false);
}

export async function getOperationalStatus(): Promise<OperationalStatusResponse> {
  return request<OperationalStatusResponse>(
    '/v1/status',
    { method: 'GET' },
    true,
  );
}

export async function getActivity(limit = 20): Promise<ActivityResponse> {
  const safeLimit = Math.max(1, Math.min(50, Math.trunc(limit)));
  return request<ActivityResponse>(
    `/v1/activity?limit=${safeLimit}`,
    { method: 'GET' },
    true,
  );
}

export async function sendChat(input: {
  message: string;
  history: ChatHistoryMessage[];
  device: MobileDevice;
}): Promise<ChatResponse> {
  return request<ChatResponse>(
    '/v1/chat',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
    true,
  );
}

async function request<T>(
  path: string,
  init: RequestInit,
  authenticated: boolean,
): Promise<T> {
  if (!API_URL) {
    throw new Error(
      'Mobile bridge address is not configured. Set EXPO_PUBLIC_AIDA_API_URL.',
    );
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  };

  if (authenticated && PAIRING_TOKEN) {
    headers.Authorization = `Bearer ${PAIRING_TOKEN}`;
  }

  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });

    const payload = await response.json().catch(() => null);

    if (!response.ok) {
      const detail =
        payload && typeof payload.detail === 'string'
          ? payload.detail
          : `AIDA mobile bridge returned HTTP ${response.status}.`;
      throw new Error(detail);
    }

    return payload as T;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('AIDA mobile bridge timed out.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
