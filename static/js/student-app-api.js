import { STATES } from './student-app-contract.js';

export class MobileApiError extends Error {
  constructor(code, status = 0) {
    super(code || 'request_failed');
    this.name = 'MobileApiError';
    this.code = code || 'request_failed';
    this.status = Number(status) || 0;
  }
}

function jsonInit(method, body, csrfToken = '') {
  const headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  return { method, headers, body: JSON.stringify(body) };
}

async function payload(response) {
  try { return await response.json(); }
  catch { return null; }
}

export function createMobileApi(fetchImpl = fetch) {
  async function request(url, init = {}, authMode = '') {
    let response;
    try {
      response = await fetchImpl(url, {
        ...init,
        cache: init.cache ?? 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', ...(init.headers || {}) },
      });
    } catch {
      throw new MobileApiError('request_unavailable');
    }
    const body = await payload(response);
    if (response.ok && body && typeof body === 'object') return body;
    const state = String(body?.state || body?.status || '');
    if (authMode && STATES.includes(state) && state !== 'error') return body;
    if ((authMode === 'session' || authMode === 'bound') && response.status === 401) return { state: 'signed_out' };
    throw new MobileApiError(String(body?.code || 'request_failed'), response.status);
  }

  return Object.freeze({
    getInitialState: () => request('/api/mobile/auth/session', {}, 'session'),
    login: credentials => request('/api/mobile/auth/login', jsonInit('POST', credentials), 'exchange'),
    activate: (code, loginId) => request('/api/mobile/auth/login', jsonInit('POST', { id: loginId, password: '', activationCode: code }), 'exchange'),
    submitCredentials: (credentials, csrfToken) => request('/api/mobile/auth/credentials', jsonInit('POST', credentials, csrfToken), 'bound'),
    switchCurriculum: (sid, csrfToken) => request('/api/mobile/auth/switch', jsonInit('POST', { sid }, csrfToken), 'bound'),
    logout: csrfToken => request('/api/mobile/auth/logout', jsonInit('POST', {}, csrfToken), 'bound'),
    getPushPublicKey: async () => {
      const result = await request('/api/mobile/push/public-key');
      const key = typeof result.publicKey === 'string' ? result.publicKey.trim() : '';
      if (!key) throw new MobileApiError('push_unavailable');
      return key;
    },
    getPushStatus: deviceId => request(`/api/mobile/push/status?deviceId=${encodeURIComponent(deviceId)}`),
    subscribePush: (body, csrfToken) => request('/api/mobile/push/subscribe', jsonInit('POST', body, csrfToken)),
    unsubscribePush: (body, csrfToken) => request('/api/mobile/push/unsubscribe', jsonInit('POST', body, csrfToken)),
    bypassPush: (body, csrfToken) => request('/api/mobile/push/bypass', jsonInit('POST', body, csrfToken)),
  });
}
