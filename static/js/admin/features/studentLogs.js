import { ensureOk, fetchJsonChecked, sendJson } from '../../shared/api.js';


const API_URL = '/api/student-logs';
const LOG_KIND_LABELS = Object.freeze({
  homework_insufficient: '숙제미흡',
});

const logState = {
  logs: [],
  loading: true,
  busy: false,
};


function setStatus(root, message, state = '') {
  const status = root.querySelector('#studentLogStatus');
  if (!status) return;
  status.textContent = message;
  status.dataset.state = state;
}


function syncControls(root) {
  const clear = root.querySelector('#studentLogClear');
  if (clear) clear.disabled = logState.loading || logState.busy || !logState.logs.length;
}


function logLine(log) {
  const name = String(log?.student_name || log?.studentName || log?.sid || '').trim();
  const kind = LOG_KIND_LABELS[String(log?.kind || '').trim()] || String(log?.kind || '').trim() || '로그';
  const comment = String(log?.comment || '').trim();
  return [name, kind, comment].filter(Boolean).join('-');
}


function renderLogs(root) {
  const list = root.querySelector('#studentLogList');
  if (!list) return;
  list.replaceChildren();

  if (!logState.logs.length) {
    const empty = document.createElement('li');
    empty.className = 'student-log-empty';
    empty.textContent = '등록된 학생 로그가 없습니다.';
    list.appendChild(empty);
    syncControls(root);
    return;
  }

  logState.logs.forEach((log) => {
    const item = document.createElement('li');
    item.className = 'student-log-item';
    item.dataset.studentLogId = String(log?.id || '');

    const line = document.createElement('span');
    line.className = 'student-log-content';
    line.textContent = logLine(log);
    item.appendChild(line);

    list.appendChild(item);
  });
  syncControls(root);
}


async function loadLogs(root) {
  logState.loading = true;
  syncControls(root);
  root.setAttribute('aria-busy', 'true');
  setStatus(root, '학생 로그를 불러오는 중입니다.');
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
    setStatus(root, '학생 로그를 불러오지 못했습니다.', 'error');
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
  setStatus(root, '학생 로그를 정리하는 중입니다.');
  try {
    const response = await fetch(API_URL, {
      method: 'DELETE',
      cache: 'no-store',
      credentials: 'same-origin',
    });
    await ensureOk(response, 'student log clear');
    logState.logs = [];
    renderLogs(root);
    setStatus(root, '학생 로그를 정리했습니다.', 'success');
  } catch (error) {
    console.error('[student logs] clear failed', error);
    setStatus(root, '학생 로그를 정리하지 못했습니다.', 'error');
  } finally {
    logState.busy = false;
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
  return data.log;
}


export function initStudentLogs() {
  const root = document.getElementById('studentLogPanel');
  if (!root || root.dataset.studentLogsReady === '1') return;
  const list = root.querySelector('#studentLogList');
  const clear = root.querySelector('#studentLogClear');
  if (!list || !clear) return;

  root.dataset.studentLogsReady = '1';
  clear.addEventListener('click', () => { void clearLogs(root); });
  window.addEventListener('student-log:created', (event) => {
    appendLog(root, event.detail);
    setStatus(root, '학생 로그를 등록했습니다.', 'success');
  });

  renderLogs(root);
  void loadLogs(root);
}
