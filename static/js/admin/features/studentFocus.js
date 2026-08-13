import { getAdminDate } from '../core/adminDate.js';
import { api } from '../core/api.js';

const CLASS_KEYS = ['classId', 'endAt', 'kind', 'sessions', 'startAt'];
const SESSION_KEYS = ['endedAt', 'focusMs', 'grade', 'hiddenCount', 'hiddenMs', 'longestHiddenMs', 'name', 'school', 'sid', 'startedAt', 'state', 'unknownMs'];
const STATES = new Set(['active', 'finished', 'unknown']);
const KINDS = new Set(['regular', 'extra', 'makeup']);

function exactKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function validIso(value, nullable = false) {
  if (nullable && value === null) return true;
  return typeof value === 'string' && value.trim() !== '' && Number.isFinite(Date.parse(value));
}

function validCount(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function normalizeSession(value) {
  if (!exactKeys(value, SESSION_KEYS) || !STATES.has(value.state)) return null;
  if (!validIso(value.startedAt) || !validIso(value.endedAt, true)) return null;
  if (!['focusMs', 'hiddenCount', 'hiddenMs', 'longestHiddenMs', 'unknownMs'].every(key => validCount(value[key]))) return null;
  if (![value.sid, value.name, value.school, value.grade].every(item => typeof item === 'string' && item.length <= 128)) return null;
  return Object.freeze({ ...value });
}

function normalizePayload(value) {
  if (!exactKeys(value, ['classes', 'date', 'ok', 'serverNow']) || value.ok !== true) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value.date) || !validIso(value.serverNow) || !Array.isArray(value.classes)) return null;
  const classes = [];
  for (const item of value.classes) {
    if (!exactKeys(item, CLASS_KEYS) || !/^fcl_[A-Za-z0-9_-]{20,40}$/.test(item.classId)) return null;
    if (!KINDS.has(item.kind) || !validIso(item.startAt) || !validIso(item.endAt) || !Array.isArray(item.sessions)) return null;
    const sessions = item.sessions.map(normalizeSession);
    if (sessions.some(session => !session)) return null;
    classes.push(Object.freeze({ ...item, sessions: Object.freeze(sessions) }));
  }
  return Object.freeze({ date: value.date, serverNow: value.serverNow, classes: Object.freeze(classes) });
}

function duration(milliseconds) {
  const minutes = Math.floor(Math.max(0, Number(milliseconds) || 0) / 60_000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}시간 ${minutes % 60}분` : `${minutes}분`;
}

function kindLabel(kind) {
  return ({ regular: '정규수업', extra: '추가수업', makeup: '보강' })[kind] || '수업';
}

function stateLabel(state) {
  return ({ active: '진행 중', finished: '종료', unknown: '일부 확인 불가' })[state] || '확인 불가';
}

function node(tag, className = '', text = '') {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

export function initStudentFocus() {
  const openButton = document.getElementById('studentFocusOpen');
  const modal = document.getElementById('studentFocusAdminModal');
  const closeButton = document.getElementById('studentFocusAdminClose');
  const refreshButton = document.getElementById('studentFocusAdminRefresh');
  const dateNode = document.getElementById('studentFocusAdminDate');
  const statusNode = document.getElementById('studentFocusAdminStatus');
  const list = document.getElementById('studentFocusAdminList');
  if (!openButton || !modal || !closeButton || !refreshButton || !dateNode || !statusNode || !list) return;

  let frozenDate = '';
  let opener = null;
  let requestId = 0;

  function setBusy(busy) {
    modal.setAttribute('aria-busy', busy ? 'true' : 'false');
    refreshButton.disabled = busy;
  }

  function render(payload) {
    list.replaceChildren();
    if (payload.classes.length === 0) {
      list.append(node('p', 'student-focus-admin-empty', '이 날짜에 저장된 집중 세션이 없습니다.'));
      return;
    }
    payload.classes.forEach(group => {
      const section = node('section', 'student-focus-admin-class');
      const heading = node('div', 'student-focus-admin-class-head');
      heading.append(
        node('h4', '', `${kindLabel(group.kind)} · ${new Date(group.startAt).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`),
        node('span', '', `${group.sessions.length}명`),
      );
      section.append(heading);
      const rows = node('div', 'student-focus-admin-sessions');
      group.sessions.forEach(session => {
        const card = node('article', 'student-focus-admin-card');
        const cardHead = node('div', 'student-focus-admin-card-head');
        const identity = node('div');
        identity.append(node('strong', '', session.name || session.sid), node('span', '', [session.school, session.grade].filter(Boolean).join(' · ')));
        cardHead.append(identity, node('span', `student-focus-admin-state is-${session.state}`, stateLabel(session.state)));
        const metrics = node('dl', 'student-focus-admin-metrics');
        [
          ['집중시간', duration(session.focusMs)],
          ['이탈 추정', `${session.hiddenCount}회`],
          ['총 이탈시간', duration(session.hiddenMs)],
          ['최장 이탈시간', duration(session.longestHiddenMs)],
        ].forEach(([label, value]) => {
          const row = node('div');
          row.append(node('dt', '', label), node('dd', '', value));
          metrics.append(row);
        });
        card.append(cardHead, metrics);
        if (session.unknownMs > 0) card.append(node('p', 'student-focus-admin-unknown', `확인 불가 시간 ${duration(session.unknownMs)}`));
        rows.append(card);
      });
      section.append(rows);
      list.append(section);
    });
  }

  async function load() {
    const token = ++requestId;
    setBusy(true);
    statusNode.classList.remove('is-error');
    statusNode.textContent = '집중 기록을 불러오는 중입니다.';
    try {
      const raw = await api.getStrict(`/api/admin/student-focus/summary?date=${encodeURIComponent(frozenDate)}`, 'student focus summary', { cache: 'no-store' });
      if (token !== requestId) return;
      const payload = normalizePayload(raw);
      if (!payload || payload.date !== frozenDate) throw new Error('focus summary is malformed');
      render(payload);
      statusNode.textContent = `${payload.classes.reduce((sum, item) => sum + item.sessions.length, 0)}명의 수업별 요약입니다. 원시 전환 기록은 표시하지 않습니다.`;
    } catch (error) {
      if (token !== requestId) return;
      list.replaceChildren();
      statusNode.classList.add('is-error');
      statusNode.textContent = error?.status === 404
        ? '집중 기록 기능이 아직 활성화되지 않았습니다.'
        : '집중 기록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
    } finally {
      if (token === requestId) setBusy(false);
    }
  }

  function close() {
    requestId += 1;
    modal.style.display = 'none';
    modal.hidden = true;
    document.body.classList.remove('student-focus-admin-open');
    if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
  }

  function trap(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== 'Tab') return;
    const controls = [...modal.querySelectorAll('button:not([disabled]):not([hidden])')];
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (!controls.includes(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }

  openButton.addEventListener('click', () => {
    opener = document.activeElement;
    frozenDate = getAdminDate();
    dateNode.textContent = `${frozenDate} 수업`;
    modal.hidden = false;
    modal.style.display = 'flex';
    document.body.classList.add('student-focus-admin-open');
    closeButton.focus();
    void load();
  });
  closeButton.addEventListener('click', close);
  refreshButton.addEventListener('click', () => void load());
  modal.addEventListener('keydown', trap);
}

export const __test = Object.freeze({ normalizePayload, duration });
