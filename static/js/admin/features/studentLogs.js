import { ensureOk, fetchJsonChecked, sendJson } from '../../shared/api.js';
import { state } from '../core/state.js';


const API_URL = '/api/student-logs';
const LOG_KIND_LABELS = Object.freeze({
  homework_insufficient: '숙제 미흡',
});
const LOG_FILTER_LABELS = Object.freeze({ today: '오늘', all: '전체' });

const logState = {
  logs: [],
  loading: true,
  busy: false,
  deletingId: '',
  filter: 'today',
};


function setStatus(root, message, state = '') {
  const status = root.querySelector('#studentLogStatus');
  if (!status) return;
  status.textContent = message;
  status.dataset.state = state;
}


function logName(log) {
  return String(log?.student_name || log?.studentName || log?.sid || '').trim();
}


function logSubject(log) {
  const explicit = String(log?.subject || log?.curriculum || log?.course || '').trim();
  if (explicit) return explicit;
  const sid = String(log?.sid || '').trim();
  if (!sid || !Array.isArray(state.students)) return '';
  const student = state.students.find((item) => String(item?.id || '').trim() === sid);
  return String(student?.curriculum || student?.subject || student?.course || '').trim();
}


function logDisplayName(log) {
  return [logName(log), logSubject(log)].filter(Boolean).join('-');
}


function logKind(log) {
  const raw = String(log?.kind || '').trim();
  return LOG_KIND_LABELS[raw] || raw || '로그';
}


function logComment(log) {
  return String(log?.comment || '').trim();
}


function logDateKey(log) {
  const raw = String(log?.date || log?.created_at || log?.createdAt || '').trim();
  if (!raw) return '';
  const match = raw.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (match) return match.slice(1).join('-');
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return '';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}


function todayDateKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}


function offsetDateKey(baseKey, offset) {
  const match = String(baseKey || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return '';
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}


function formatLogDate(dateKey) {
  const match = String(dateKey || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return '날짜 없음';
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  if (Number.isNaN(date.getTime())) return '날짜 없음';
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    weekday: 'short',
  }).format(date);
}


function formatLogTime(log) {
  const raw = String(log?.created_at || log?.createdAt || '').trim();
  if (!raw) return '';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}


function logSortValue(log) {
  const raw = String(log?.created_at || log?.createdAt || log?.date || '').trim();
  const timestamp = raw ? Date.parse(raw) : NaN;
  return Number.isNaN(timestamp) ? 0 : timestamp;
}


function visibleLogs() {
  const today = todayDateKey();
  return logState.logs
    .filter((log) => logState.filter !== 'today' || logDateKey(log) === today)
    .slice()
    .sort((left, right) => logSortValue(right) - logSortValue(left));
}

function syncFilterButtons(root) {
  root.querySelectorAll('[data-student-log-filter]').forEach((button) => {
    const selected = button.dataset.studentLogFilter === logState.filter;
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    button.disabled = logState.loading || logState.busy || Boolean(logState.deletingId);
  });
}


function syncControls(root) {
  const clear = root.querySelector('#studentLogClear');
  const locked = logState.loading || logState.busy || Boolean(logState.deletingId);
  if (clear) clear.disabled = locked || !logState.logs.length;
  root.querySelectorAll('[data-student-log-delete]').forEach((button) => {
    button.disabled = locked;
  });
  syncFilterButtons(root);
}

function createStudentLogItem(log) {
  const logId = String(log?.id || '').trim();
  const item = document.createElement('li');
  item.className = 'student-log-item';
  item.dataset.studentLogId = logId;

  const marker = document.createElement('span');
  marker.className = 'student-log-marker';
  marker.setAttribute('aria-hidden', 'true');
  item.appendChild(marker);

  const body = document.createElement('div');
  body.className = 'student-log-item-body';

  const head = document.createElement('div');
  head.className = 'student-log-item-head';
  const identity = document.createElement('div');
  identity.className = 'student-log-identity';

  const name = document.createElement('strong');
  name.className = 'student-log-student';
  name.textContent = logDisplayName(log) || '이름 없음';
  identity.appendChild(name);

  const kind = document.createElement('span');
  kind.className = 'student-log-kind';
  kind.textContent = logKind(log);
  identity.appendChild(kind);
  head.appendChild(identity);

  const meta = document.createElement('div');
  meta.className = 'student-log-meta';
  const timeText = formatLogTime(log);
  if (timeText) {
    const time = document.createElement('time');
    time.className = 'student-log-time';
    time.textContent = timeText;
    if (log?.created_at || log?.createdAt) time.dateTime = String(log.created_at || log.createdAt);
    meta.appendChild(time);
  }
  if (logId) {
    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'student-log-delete';
    deleteButton.dataset.studentLogDelete = logId;
    deleteButton.textContent = '\uC0AD\uC81C';
    deleteButton.setAttribute('aria-label', `${logDisplayName(log) || '\uD559\uC0DD \uB85C\uADF8'} \uC0AD\uC81C`);
    deleteButton.disabled = logState.loading || logState.busy || Boolean(logState.deletingId);
    meta.appendChild(deleteButton);
  }

  if (timeText || logId) head.appendChild(meta);
  body.appendChild(head);

  const comment = document.createElement('p');
  comment.className = 'student-log-comment';
  comment.textContent = logComment(log) || '내용 없음';
  body.appendChild(comment);
  item.appendChild(body);
  return item;
}


function renderLogs(root) {
  const list = root.querySelector('#studentLogList');
  if (!list) return;
  list.replaceChildren();

  const logs = visibleLogs();
  root.dataset.studentLogVisibleCount = String(logs.length);
  const count = root.querySelector('#studentLogCount');
  if (count) count.textContent = `${logs.length}건`;

  if (!logState.logs.length) {
    const empty = document.createElement('li');
    empty.className = 'student-log-empty';
    empty.textContent = '등록된 숙제 미흡 알림이 없습니다.';
    list.appendChild(empty);
    syncControls(root);
    return;
  }

  if (!logs.length) {
    const empty = document.createElement('li');
    empty.className = 'student-log-empty';
    empty.textContent = '오늘 등록된 숙제 미흡 알림이 없습니다.';
    list.appendChild(empty);
    syncControls(root);
    return;
  }

  const groups = [];
  const groupMap = new Map();
  const today = todayDateKey();
  const yesterday = offsetDateKey(today, -1);
  logs.forEach((log) => {
    const key = logDateKey(log) || 'unknown';
    let group = groupMap.get(key);
    if (!group) {
      group = { key, logs: [] };
      groupMap.set(key, group);
      groups.push(group);
    }
    group.logs.push(log);
  });

  groups.forEach((group) => {
    const groupItem = document.createElement('li');
    groupItem.className = 'student-log-group';
    if (logState.filter === 'all') {
      const label = document.createElement('div');
      label.className = 'student-log-group-label';
      const title = document.createElement('strong');
      title.textContent = group.key === today ? '오늘' : group.key === yesterday ? '어제' : formatLogDate(group.key);
      label.appendChild(title);
      const groupCount = document.createElement('span');
      groupCount.className = 'student-log-group-count';
      groupCount.textContent = `${group.logs.length}건`;
      label.appendChild(groupCount);
      groupItem.appendChild(label);
    }

    const groupList = document.createElement('ul');
    groupList.className = 'student-log-group-items';
    group.logs.forEach((log) => groupList.appendChild(createStudentLogItem(log)));
    groupItem.appendChild(groupList);
    list.appendChild(groupItem);
  });
  syncControls(root);
}


async function loadLogs(root) {
  logState.loading = true;
  syncControls(root);
  root.setAttribute('aria-busy', 'true');
  setStatus(root, '숙제 미흡 알림을 불러오는 중입니다.');
  try {
    const payload = await fetchJsonChecked(API_URL, 'student log list', {
      cache: 'no-store',
      credentials: 'same-origin',
    });
    logState.logs = Array.isArray(payload?.logs) ? payload.logs : [];
    renderLogs(root);
    setStatus(root, '');
  } catch (error) {
    console.error('[student logs] load failed', error);
    logState.logs = [];
    renderLogs(root);
    setStatus(root, '숙제 미흡 알림을 불러오지 못했습니다.', 'error');
  } finally {
    logState.loading = false;
    syncControls(root);
    root.removeAttribute('aria-busy');
  }
}


function appendLog(root, log) {
  if (!log || typeof log !== 'object') return;
  const id = String(log.id || '');
  if (id && logState.logs.some(item => String(item?.id || '') === id)) return;
  logState.logs = [log, ...logState.logs];
  renderLogs(root);
}


async function clearLogs(root) {
  if (logState.busy || !logState.logs.length) return;
  logState.busy = true;
  syncControls(root);
  setStatus(root, '숙제 미흡 알림을 정리하는 중입니다.');
  try {
    const response = await fetch(API_URL, {
      method: 'DELETE',
      cache: 'no-store',
      credentials: 'same-origin',
    });
    await ensureOk(response, 'student log clear');
    logState.logs = [];
    renderLogs(root);
    setStatus(root, '숙제 미흡 알림을 정리했습니다.', 'success');
  } catch (error) {
    console.error('[student logs] clear failed', error);
    setStatus(root, '숙제 미흡 알림을 정리하지 못했습니다.', 'error');
  } finally {
    logState.busy = false;
    syncControls(root);
  }
}


async function deleteStudentLog(root, id, button) {
  const logId = String(id || '').trim();
  if (!logId || logState.busy || logState.deletingId) return;
  if (!logState.logs.some((log) => String(log?.id || '').trim() === logId)) return;

  logState.deletingId = logId;
  if (button) button.disabled = true;
  syncControls(root);
  try {
    const response = await fetch(`${API_URL}/${encodeURIComponent(logId)}`, {
      method: 'DELETE',
      cache: 'no-store',
      credentials: 'same-origin',
    });
    await ensureOk(response, 'student log delete');
    logState.logs = logState.logs.filter((log) => String(log?.id || '').trim() !== logId);
    renderLogs(root);
    setStatus(root, '\uD559\uC0DD \uB85C\uADF8\uB97C \uC0AD\uC81C\uD588\uC2B5\uB2C8\uB2E4.', 'success');
  } catch (error) {
    console.error('[student logs] delete failed', error);
    setStatus(root, '\uD559\uC0DD \uB85C\uADF8\uB97C \uC0AD\uC81C\uD558\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.', 'error');
  } finally {
    logState.deletingId = '';
    if (button && button.isConnected) button.disabled = false;
    syncControls(root);
  }
}


export async function createStudentLog(payload) {
  const response = await sendJson(API_URL, payload, {
    cache: 'no-store',
    credentials: 'same-origin',
  });
  await ensureOk(response, 'student log create');
  const data = await response.json();
  if (!data?.log) throw new Error('created student log is missing');
  const subject = String(payload?.subject || '').trim();
  return subject ? { ...data.log, subject } : data.log;
}


export function initStudentLogs() {
  const root = document.getElementById('studentLogPanel');
  if (!root || root.dataset.studentLogsReady === '1') return;
  const list = root.querySelector('#studentLogList');
  const clear = root.querySelector('#studentLogClear');
  if (!list || !clear) return;

  root.dataset.studentLogsReady = '1';
  logState.filter = 'today';
  clear.addEventListener('click', () => { void clearLogs(root); });
  root.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const button = target?.closest('[data-student-log-delete]');
    if (!button || !root.contains(button)) return;
    event.preventDefault();
    void deleteStudentLog(root, button.dataset.studentLogDelete, button);
  });

  root.querySelectorAll('[data-student-log-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      const nextFilter = button.dataset.studentLogFilter;
      if (!LOG_FILTER_LABELS[nextFilter] || nextFilter === logState.filter) return;
      logState.filter = nextFilter;
      renderLogs(root);
    });
  });
  window.addEventListener('student-log:created', (event) => {
    appendLog(root, event.detail);
    setStatus(root, '');
  });

  renderLogs(root);
  void loadLogs(root);
}
