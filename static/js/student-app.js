const STATES = Object.freeze([
  'signed_out',
  'activation_code_required',
  'credentials_required',
  'push_required',
  'unsupported_bypass',
  'ready',
  'error',
]);

const COPY = Object.freeze({
  signed_out: { eyebrow: '학생 앱', title: '학습을 시작해 주세요', body: '등록된 학생 계정으로 안전하게 연결합니다.', action: '로그인' },
  activation_code_required: { eyebrow: '계정 활성화', title: '활성화 코드를 입력해 주세요', body: '학원에서 받은 코드를 입력하면 학습 공간을 준비합니다.', action: '활성화하기' },
  credentials_required: { eyebrow: '계정 확인', title: '로그인 정보를 확인해 주세요', body: '학생 계정 정보를 확인한 뒤 학습 공간으로 이동합니다.', action: '계정 확인' },
  push_required: { eyebrow: '알림 안내', title: '알림 설정을 확인해 주세요', body: '알림은 기기 설정에서 직접 허용할 수 있습니다. 이 화면에서는 권한을 자동으로 요청하지 않습니다.', action: '알림 설정 안내' },
  unsupported_bypass: { eyebrow: '브라우저 안내', title: '기본 방식으로 계속할 수 있습니다', body: '현재 브라우저에서 일부 설치 기능을 사용할 수 없습니다.', action: '기본 방식으로 계속' },
  ready: { eyebrow: '준비 완료', title: '학습 공간이 준비되었습니다', body: '학생 페이지에서 오늘의 학습을 확인하세요.', action: '학생 페이지 열기' },
  error: { eyebrow: '연결 오류', title: '잠시 연결할 수 없습니다', body: '연결을 확인한 뒤 다시 시도해 주세요.', action: '다시 시도' },
});

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function sessionSid(value) {
  const sid = typeof value === 'string' ? value.trim() : '';
  if (!sid || sid.length > 128 || sid === '.' || sid === '..') return '';
  return /[\s/\\%,\u0000-\u001f\u007f]/.test(sid) ? '' : sid;
}

function normalizeCurris(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const result = [];
  for (const item of value) {
    const sid = sessionSid(item?.sid);
    if (!sid || seen.has(sid)) continue;
    seen.add(sid);
    const cur = typeof item?.cur === 'string' ? item.cur.trim().slice(0, 160) : '';
    result.push({ sid, cur: cur || sid });
  }
  return result;
}

function normalizedStateName(value) {
  const state = value?.status ?? value?.state;
  return typeof state === 'string' ? state : '';
}

export function normalizeState(value) {
  if (!isRecord(value) || !STATES.includes(normalizedStateName(value))) {
    return { status: 'error', errorCode: 'malformed_input' };
  }
  const status = normalizedStateName(value);
  const result = { status };
  const curris = normalizeCurris(value.curris);
  if (curris.length) result.curris = curris;
  if (typeof value.csrfToken === 'string' && value.csrfToken.trim()) result.csrfToken = value.csrfToken.trim();
  if (typeof value.pushState === 'string' && value.pushState.trim()) result.pushState = value.pushState.trim();
  if (typeof value.loginId === 'string' && value.loginId.trim()) result.loginId = value.loginId.trim().slice(0, 160);

  if (status === 'ready') {
    const sid = sessionSid(value.sessionSid ?? value.sid);
    return sid ? { ...result, sessionSid: sid } : { status: 'error', errorCode: 'malformed_input' };
  }
  if (status === 'error') {
    const message = typeof value.message === 'string' ? value.message.trim().slice(0, 240) : '';
    return { ...result, errorCode: String(value.errorCode || value.code || 'unknown').slice(0, 80), message };
  }
  return result;
}

async function requestJson(url, init = {}) {
  const response = await fetch(url, { ...init, credentials: 'same-origin', headers: { Accept: 'application/json', ...(init.headers || {}) } });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const state = normalizedStateName(payload) || (STATES.includes(payload?.code) ? payload.code : '');
    if (state) return normalizeState({ ...payload, state });
    throw new Error(`mobile request failed (${response.status})`);
  }
  return normalizeState(payload);
}

function jsonRequest(method, body, csrfToken = '') {
  const headers = { 'Content-Type': 'application/json' };
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  return { method, headers, body: JSON.stringify(body) };
}

function createDefaultApi() {
  return Object.freeze({
    getInitialState: () => requestJson('/api/mobile/auth/session'),
    login: (credentials) => requestJson('/api/mobile/auth/login', jsonRequest('POST', credentials)),
    activate: (code, loginId) => requestJson('/api/mobile/auth/login', jsonRequest('POST', { id: loginId, password: '', activationCode: code })),
    submitCredentials: (credentials, csrfToken) => requestJson('/api/mobile/auth/credentials', jsonRequest('POST', credentials, csrfToken)),
    switchCurriculum: (sid, csrfToken) => requestJson('/api/mobile/auth/switch', jsonRequest('POST', { sid }, csrfToken)),
    logout: (csrfToken) => requestJson('/api/mobile/auth/logout', jsonRequest('POST', {}, csrfToken)),
  });
}

function safeText(value) {
  return typeof value === 'string' ? value : '';
}

function addText(documentRef, tag, className, text) {
  const element = documentRef.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}

function actionFor(status) {
  return {
    signed_out: 'sign-in',
    activation_code_required: 'activate',
    credentials_required: 'credentials',
    push_required: 'push',
    unsupported_bypass: 'continue',
    ready: 'open-student',
    error: 'retry',
  }[status];
}

export function createStudentApp(options = {}) {
  const documentRef = options.document ?? document;
  const root = options.root ?? documentRef.getElementById('student-app');
  if (!root) throw new Error('student app root is missing');
  const api = options.api ?? createDefaultApi();
  const navigate = options.navigate ?? ((url) => { window.location.assign(url); });
  const autoBootstrap = options.autoBootstrap !== false;
  let currentState = normalizeState(options.initialState ?? { status: 'signed_out' });
  let destroyed = false;

  function setStatus(message) {
    const status = root.querySelector('[data-app-status]');
    if (status) status.textContent = safeText(message);
  }

  function focusState(section, status) {
    const field = status === 'activation_code_required' ? section.querySelector('#activation-code') : status === 'credentials_required' ? section.querySelector('#credentials-id') : null;
    (field ?? section.querySelector('[data-primary-action]') ?? section).focus();
  }

  function render(state) {
    if (destroyed) return;
    currentState = normalizeState(state);
    const spec = COPY[currentState.status];
    const section = documentRef.createElement('section');
    section.className = 'student-app-state';
    section.dataset.state = currentState.status;
    section.tabIndex = -1;
    section.setAttribute('role', 'region');
    section.setAttribute('aria-labelledby', 'student-app-state-title');

    section.append(addText(documentRef, 'p', 'student-app-eyebrow', spec.eyebrow));
    section.append(addText(documentRef, 'h1', 'student-app-title', spec.title));
    const body = addText(documentRef, 'p', 'student-app-copy', spec.body);
    body.id = 'student-app-state-help';
    section.querySelector('.student-app-title').id = 'student-app-state-title';
    section.append(body);

    if (currentState.status === 'signed_out') {
      const idLabel = addText(documentRef, 'label', 'student-app-label', '학생 아이디');
      idLabel.htmlFor = 'student-id';
      const idInput = documentRef.createElement('input');
      idInput.id = 'student-id'; idInput.name = 'studentId'; idInput.type = 'text'; idInput.autocomplete = 'username'; idInput.required = true; idInput.setAttribute('aria-describedby', body.id);
      const secretLabel = addText(documentRef, 'label', 'student-app-label', '비밀번호');
      secretLabel.htmlFor = 'student-password';
      const secretInput = documentRef.createElement('input');
      secretInput.id = 'student-password'; secretInput.name = 'password'; secretInput.type = 'password'; secretInput.autocomplete = 'current-password'; secretInput.required = true; secretInput.setAttribute('aria-describedby', body.id);
      section.append(idLabel, idInput, secretLabel, secretInput);
    }

    if (currentState.status === 'activation_code_required') {
      const label = addText(documentRef, 'label', 'student-app-label', '활성화 코드');
      label.htmlFor = 'activation-code';
      const input = documentRef.createElement('input');
      input.id = 'activation-code'; input.name = 'activationCode'; input.type = 'text'; input.autocomplete = 'one-time-code'; input.inputMode = 'text'; input.required = true; input.setAttribute('aria-describedby', body.id);
      section.append(label, input);
    }
    if (currentState.status === 'credentials_required') {
      const idLabel = addText(documentRef, 'label', 'student-app-label', '학생 아이디');
      idLabel.htmlFor = 'credentials-id';
      const idInput = documentRef.createElement('input');
      idInput.id = 'credentials-id'; idInput.name = 'studentId'; idInput.type = 'text'; idInput.autocomplete = 'username'; idInput.required = true; idInput.setAttribute('aria-describedby', body.id);
      const secretLabel = addText(documentRef, 'label', 'student-app-label', '비밀번호');
      secretLabel.htmlFor = 'credentials-secret';
      const secretInput = documentRef.createElement('input');
      secretInput.id = 'credentials-secret'; secretInput.name = 'password'; secretInput.type = 'password'; secretInput.autocomplete = 'current-password'; secretInput.required = true; secretInput.setAttribute('aria-describedby', body.id);
      section.append(idLabel, idInput, secretLabel, secretInput);
    }

    if (currentState.status === 'ready' && currentState.curris?.length > 1) {
      const label = addText(documentRef, 'label', 'student-app-label', '커리큘럼');
      label.htmlFor = 'curriculum-select';
      const select = documentRef.createElement('select');
      select.id = 'curriculum-select'; select.name = 'curriculum'; select.setAttribute('aria-describedby', body.id);
      for (const curriculum of currentState.curris) {
        const option = documentRef.createElement('option');
        option.value = curriculum.sid;
        option.textContent = curriculum.cur;
        if (curriculum.sid === currentState.sessionSid) option.selected = true;
        select.append(option);
      }
      section.append(label, select);
    }

    const status = addText(documentRef, 'p', 'student-app-status', '');
    status.dataset.appStatus = 'true'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    section.append(status);
    const action = documentRef.createElement('button');
    action.type = 'button'; action.className = 'student-app-primary'; action.dataset.primaryAction = actionFor(currentState.status); action.textContent = spec.action;
    action.setAttribute('aria-describedby', body.id);
    action.addEventListener('click', () => handleAction(action));
    section.append(action);
    root.replaceChildren(section);
    focusState(section, currentState.status);
  }

  async function handleAction(button) {
    button.disabled = true; button.setAttribute('aria-busy', 'true'); setStatus('처리 중입니다.');
    try {
      let next;
      if (currentState.status === 'signed_out') {
        const credentials = { id: root.querySelector('#student-id')?.value.trim() || '', password: root.querySelector('#student-password')?.value || '' };
        next = typeof api.login === 'function' ? await api.login(credentials) : await api.signIn();
        if (next?.status === 'activation_code_required' && !next.loginId && credentials.id) next = { ...next, loginId: credentials.id };
      } else if (currentState.status === 'activation_code_required') {
        next = await api.activate(root.querySelector('#activation-code')?.value.trim() || '', currentState.loginId || '');
      } else if (currentState.status === 'credentials_required') {
        next = await api.submitCredentials({ studentId: root.querySelector('#credentials-id')?.value.trim() || '', password: root.querySelector('#credentials-secret')?.value || '' }, currentState.csrfToken || '');
  } else if (currentState.status === 'ready') {
    const targetSid = root.querySelector('#curriculum-select')?.value || currentState.sessionSid;
    if (targetSid !== currentState.sessionSid && typeof api.switchCurriculum === 'function') {
      next = await api.switchCurriculum(targetSid, currentState.csrfToken || '');
      const switched = normalizeState(next);
          if (switched.status !== 'ready') { render(switched); return; }
          currentState = switched;
    }
    navigate(`/student/${encodeURIComponent(currentState.sessionSid)}`);
    return;
  } else if (currentState.status === 'push_required' && typeof api.setupPush === 'function') {
    next = await api.setupPush();
  } else if (currentState.status === 'unsupported_bypass' && typeof api.continueUnsupported === 'function') {
    next = await api.continueUnsupported();
  } else next = await api.getInitialState();
      render(normalizeState(next));
    } catch (error) {
      render({ status: 'error', errorCode: 'request_failed', message: error instanceof Error ? error.message : '' });
    }
  }

  async function bootstrap() {
    render(currentState);
    if (!autoBootstrap) return currentState;
    try { render(await api.getInitialState()); }
    catch (error) { render({ status: 'error', errorCode: 'request_failed', message: error instanceof Error ? error.message : '' }); }
    return currentState;
  }

  function destroy() { destroyed = true; root.replaceChildren(); }
  const instance = Object.freeze({ bootstrap, destroy, getState: () => currentState, render });
  void bootstrap();
  return instance;
}

let bootStarted = false;
function bootBrowserShell() {
  if (bootStarted || typeof document === 'undefined' || !document.getElementById('student-app')) return;
  bootStarted = true;
  createStudentApp();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootBrowserShell, { once: true });
  else bootBrowserShell();
}

export { STATES };
