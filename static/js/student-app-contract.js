export const STATES = Object.freeze([
  'signed_out',
  'activation_code_required',
  'credentials_required',
  'push_required',
  'unsupported_bypass',
  'ready',
  'error',
]);

const ANNOUNCEMENT_ID = /[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/;
const NOTIFICATION_EVENT_ID = /evt_[A-Za-z0-9_-]{32}/;
const HOMEWORK_EVENT_ID = NOTIFICATION_EVENT_ID;

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function safeSid(value) {
  const sid = typeof value === 'string' ? value.trim() : '';
  if (!sid || sid.length > 128 || sid === '.' || sid === '..') return '';
  return /[\s/\\%,\u0000-\u001f\u007f]/.test(sid) ? '' : sid;
}

export function safeAnnouncementId(value) {
  const id = typeof value === 'string' ? value : '';
  const match = ANNOUNCEMENT_ID.exec(id);
  return match?.index === 0 && match[0] === id ? id : '';
}

export function safeNotificationEventId(value, view = '') {
  const id = typeof value === 'string' ? value : '';
  const matcher = view === 'homework' ? HOMEWORK_EVENT_ID : NOTIFICATION_EVENT_ID;
  const match = matcher.exec(id);
  return match?.index === 0 && match[0] === id ? id : '';
}

export function requestedAnnouncement(search) {
  const params = new URLSearchParams(String(search || ''));
  const values = params.getAll('announcement');
  if (values.length !== 1 || params.has('view') || params.has('item')) return '';
  return safeAnnouncementId(values[0]);
}

export function requestedStudentTarget(search) {
  const params = new URLSearchParams(String(search || ''));
  if (params.has('announcement')) return null;
  const views = params.getAll('view');
  const items = params.getAll('item');
  if (views.length !== 1) return null;
  if (views[0] === 'home') return items.length === 0 ? Object.freeze({ view: 'home' }) : null;
  if (!['homework', 'board'].includes(views[0]) || items.length !== 1) return null;
  const item = safeNotificationEventId(items[0], views[0]);
  return item ? Object.freeze({ view: views[0], item }) : null;
}

export function studentPageUrl(sidValue, search = '') {
  const sid = safeSid(sidValue);
  if (!sid) return '/app';
  const announcement = requestedAnnouncement(search);
  if (announcement) return `/student/${encodeURIComponent(sid)}?announcement=${encodeURIComponent(announcement)}`;
  const target = requestedStudentTarget(search);
  const suffix = target?.view === 'home'
    ? '?view=home'
    : target?.item
      ? `?view=${target.view}&item=${encodeURIComponent(target.item)}`
      : '';
  return `/student/${encodeURIComponent(sid)}${suffix}`;
}

function normalizeCurris(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const result = [];
  for (const item of value) {
    const sid = safeSid(item?.sid);
    if (!sid || seen.has(sid)) continue;
    seen.add(sid);
    const cur = typeof item?.cur === 'string' ? item.cur.trim().slice(0, 160) : '';
    result.push({ sid, cur: cur || sid });
  }
  return result;
}

function stateName(value) {
  const name = value?.status ?? value?.state;
  return typeof name === 'string' && STATES.includes(name) ? name : '';
}

function text(value, limit) {
  return typeof value === 'string' ? value.trim().slice(0, limit) : '';
}

export function normalizeState(value) {
  const status = isRecord(value) ? stateName(value) : '';
  if (!status) return { status: 'error', errorCode: 'malformed_input', message: '' };
  const result = { status };
  const sid = safeSid(value.sessionSid ?? value.sid);
  const curris = normalizeCurris(value.curris);
  if (sid) result.sessionSid = sid;
  if (curris.length) result.curris = curris;
  const csrfToken = text(value.csrfToken, 512);
  if (csrfToken) result.csrfToken = csrfToken;
  for (const key of ['pushState', 'loginId', 'pushMode', 'notificationState', 'notificationLabel']) {
    const selected = text(value[key], key === 'notificationLabel' ? 240 : 160);
    if (selected) result[key] = selected;
  }
  if (Number.isFinite(Number(value.bypassExpiresAt))) result.bypassExpiresAt = Number(value.bypassExpiresAt);
  if (isRecord(value.capabilities)) {
    result.capabilities = Object.fromEntries(['serviceWorker', 'pushManager', 'notification', 'standalone'].map(key => [key, value.capabilities[key] === true]));
  }
  const deviceId = text(value.deviceId, 128);
  if (deviceId) result.deviceId = deviceId;
  if (status === 'ready' && !sid) return { status: 'error', errorCode: 'malformed_input', message: '' };
  if (status === 'error') {
    result.errorCode = text(value.errorCode ?? value.code, 80) || 'unknown';
    result.message = text(value.message, 240);
  } else {
    const message = text(value.message, 240);
    if (message) result.message = message;
  }
  return result;
}

export function isBackwardTransition(currentValue, nextValue) {
  const rank = { signed_out: 0, activation_code_required: 1, credentials_required: 2, push_required: 3, unsupported_bypass: 3, ready: 4 };
  const current = stateName(currentValue);
  const next = stateName(nextValue);
  if (!current || !next || current === 'error' || next === 'error' || next === 'signed_out') return false;
  return Number(rank[next]) < Number(rank[current]);
}
