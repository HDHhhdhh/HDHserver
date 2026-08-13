import { createMobileApi } from './student-app-api.js';
import { createBrowserPushPlatform, createPushGate, detectInstallEnvironment } from './student-app-push.js';
import { STATES, isBackwardTransition, normalizeState, studentPageUrl } from './student-app-contract.js';

const BROWSER_PLATFORM = typeof window !== 'undefined' ? createBrowserPushPlatform(window) : null;
const AUTH_INPUT_STATES = new Set(['signed_out', 'activation_code_required', 'credentials_required']);
const PREPARATION_STEPS = Object.freeze([
  { number: 1, label: '계정 확인' },
  { number: 2, label: '보안 설정' },
  { number: 3, label: '설치·알림' },
]);

const COPY = Object.freeze({
  signed_out: { eyebrow: '학생 앱', title: '학습을 시작해 주세요', body: '기존 학생 아이디 또는 이름과 비밀번호를 입력해 주세요. 기존 사이트의 로그인 상태는 앱으로 자동 이동하지 않습니다.', action: '로그인' },
  activation_code_required: { eyebrow: '계정 활성화', title: '활성화 코드를 입력해 주세요', body: '학원에서 받은 코드를 입력하면 학습 공간을 준비합니다.', action: '활성화하기' },
  credentials_required: { eyebrow: '계정 보안', title: '새 로그인 정보를 설정해 주세요', body: '새 아이디와 8자 이상의 새 비밀번호를 설정해야 계속할 수 있습니다.', action: '새 계정 정보 저장' },
  push_required: { eyebrow: '설치와 알림', title: '앱 설치와 학습 알림을 확인해 주세요', body: '버튼을 눌렀을 때만 설치와 알림 권한을 요청합니다.', action: '설치·알림 설정' },
  unsupported_bypass: { eyebrow: '알림 미지원', title: '기본 방식으로 계속할 수 있습니다', body: '이 기기는 웹 알림을 지원하지 않아 24시간 동안 기본 방식으로 이용할 수 있습니다.', action: '24시간 기본 방식으로 계속' },
  ready: { eyebrow: '준비 완료', title: '학습 공간이 준비되었습니다', body: '설정 상태를 확인한 뒤 학생 페이지로 이동하세요.', action: '학생 페이지 열기' },
  error: { eyebrow: '연결 오류', title: '잠시 연결할 수 없습니다', body: '연결을 확인한 뒤 다시 시도해 주세요.', action: '다시 시도' },
});

const text = value => typeof value === 'string' ? value : '';

const PLATFORM_LABELS = Object.freeze({
  ios: 'iPhone·iPad', android: 'Android', windows: 'Windows', macos: 'macOS', chromeos: 'ChromeOS', linux: 'Linux', other: '현재 기기',
});
const BROWSER_LABELS = Object.freeze({
  safari: 'Safari', chrome: 'Chrome', edge: 'Edge', samsung: '삼성 인터넷', firefox: 'Firefox', in_app: '앱 안의 브라우저', other: '현재 브라우저',
});

export function installGuideContent(environment) {
  const platform = text(environment?.platform) || 'other';
  const browser = text(environment?.browser) || 'other';
  const device = PLATFORM_LABELS[platform] || PLATFORM_LABELS.other;
  const browserName = BROWSER_LABELS[browser] || BROWSER_LABELS.other;
  const common = {
    label: `${device} · ${browserName}`,
    title: '학생 앱을 설치해 주세요',
    body: '앱으로 설치하면 홈 화면에서 바로 열 수 있고 학습 알림도 안정적으로 받을 수 있습니다. 지금은 브라우저에서도 계속 이용할 수 있습니다.',
    action: '앱 설치 시도',
  };
  if (platform === 'ios' && browser === 'safari') return Object.freeze({ ...common, action: '설치 순서 확인', steps: [
    'Safari의 더보기 또는 공유 버튼을 누른 뒤 “공유”를 여세요.',
    '목록에서 “홈 화면에 추가”를 선택하세요.',
    '“웹 앱으로 열기”를 켜고 “추가”를 누르세요.',
    '홈 화면에 생긴 학생 앱 아이콘으로 다시 여세요.',
  ] });
  if (platform === 'ios') return Object.freeze({ ...common, action: '설치 순서 확인', steps: [
    '브라우저의 공유 메뉴에서 “Safari에서 열기”를 선택하세요.',
    'Safari에서 더보기 또는 공유 버튼을 누르고 “홈 화면에 추가”를 선택하세요.',
    '“웹 앱으로 열기”를 켜고 “추가”를 누르세요.',
    '홈 화면에 생긴 학생 앱 아이콘으로 다시 여세요.',
  ] });
  if (platform === 'android' && browser === 'chrome') return Object.freeze({ ...common, steps: [
    'Chrome 주소창 오른쪽의 더보기(⋮)를 누르세요.',
    '“홈 화면에 추가”를 누른 뒤 “설치”를 선택하세요.',
    '설치 확인창의 안내를 완료하세요.',
    '홈 화면에 생긴 학생 앱 아이콘으로 다시 여세요.',
  ] });
  if (platform === 'android' && browser === 'in_app') return Object.freeze({ ...common, steps: [
    '현재 앱의 메뉴에서 “외부 브라우저로 열기”를 누르세요.',
    'Chrome으로 이 페이지를 다시 여세요.',
    'Chrome 더보기(⋮)에서 “홈 화면에 추가”와 “설치”를 차례로 누르세요.',
    '홈 화면에 생긴 학생 앱 아이콘으로 다시 여세요.',
  ] });
  if (platform === 'android') return Object.freeze({ ...common, steps: [
    `${browserName} 메뉴를 열고 “앱 설치” 또는 “홈 화면에 추가”를 찾으세요.`,
    '표시되는 설치 확인창을 완료하세요.',
    '메뉴에 설치 항목이 없으면 Chrome에서 이 페이지를 다시 여세요.',
    '홈 화면에 생긴 학생 앱 아이콘으로 다시 여세요.',
  ] });
  if (platform === 'macos' && browser === 'safari') return Object.freeze({ ...common, action: '설치 순서 확인', steps: [
    'Safari의 “파일” 메뉴를 여세요.',
    '“Dock에 추가”를 선택하세요.',
    '이름과 아이콘을 확인한 뒤 “추가”를 누르세요.',
    'Dock 또는 응용 프로그램의 학생 앱으로 다시 여세요.',
  ] });
  if (browser === 'edge') return Object.freeze({ ...common, steps: [
    '주소창의 앱 설치 아이콘을 누르세요.',
    '아이콘이 없으면 더보기(…)의 “앱”에서 “이 사이트를 앱으로 설치”를 선택하세요.',
    '설치 확인창에서 “설치”를 누르세요.',
    '작업 표시줄·Dock 또는 앱 목록의 학생 앱으로 다시 여세요.',
  ] });
  if (browser === 'chrome') return Object.freeze({ ...common, steps: [
    '주소창의 앱 설치 아이콘을 누르세요.',
    '아이콘이 없으면 더보기(⋮)의 “전송, 저장, 공유”에서 “페이지를 앱으로 설치”를 선택하세요.',
    '설치 확인창에서 “설치”를 누르세요.',
    '작업 표시줄·Dock 또는 앱 목록의 학생 앱으로 다시 여세요.',
  ] });
  return Object.freeze({ ...common, action: '설치 순서 확인', steps: [
    'Chrome 또는 Edge로 이 페이지를 다시 여세요.',
    '주소창의 앱 설치 아이콘을 누르세요.',
    '설치 확인창을 완료하세요.',
    '작업 표시줄·Dock 또는 앱 목록의 학생 앱으로 다시 여세요.',
  ] });
}

export function initInstallGuide({ documentRef = document, windowRef = window, platform = BROWSER_PLATFORM } = {}) {
  const overlay = documentRef.querySelector?.('[data-install-guide]');
  const dialog = documentRef.querySelector?.('[data-install-dialog]');
  const opener = documentRef.querySelector?.('[data-install-guide-open]');
  if (!overlay || !dialog || !opener) return null;
  const environment = platform?.installEnvironment?.() ?? detectInstallEnvironment(windowRef);
  if (environment.standalone) {
    opener.hidden = true;
    overlay.hidden = true;
    return Object.freeze({ open: () => {}, close: () => {}, environment });
  }
  const guide = installGuideContent(environment);
  const label = overlay.querySelector('[data-install-environment]');
  const title = overlay.querySelector('[data-install-title]');
  const body = overlay.querySelector('[data-install-body]');
  const steps = overlay.querySelector('[data-install-steps]');
  const action = overlay.querySelector('[data-install-action]');
  const status = overlay.querySelector('[data-install-status]');
  const dismissers = overlay.querySelectorAll('[data-install-dismiss]');
  if (label) label.textContent = guide.label;
  if (title) title.textContent = guide.title;
  if (body) body.textContent = guide.body;
  if (action) action.textContent = guide.action;
  if (steps) {
    steps.replaceChildren(...guide.steps.map(step => {
      const item = documentRef.createElement('li');
      item.textContent = step;
      return item;
    }));
  }
  let previousFocus = null;
  let installPromptInFlight = false;
  let installed = false;
  const background = [...documentRef.querySelectorAll('body > header, body > main, body > footer')];
  const setBackgroundInert = value => background.forEach(node => { node.inert = value; });
  const focusMainAction = () => {
    const target = documentRef.querySelector?.('#student-app input, #student-app select, #student-app button, #student-app [tabindex]:not([tabindex="-1"])')
      ?? documentRef.getElementById?.('student-app');
    target?.focus?.();
  };
  function open() {
    if (installed || opener.hidden) return;
    previousFocus = documentRef.activeElement;
    overlay.hidden = false;
    setBackgroundInert(true);
    dialog.focus();
  }
  function close() {
    overlay.hidden = true;
    setBackgroundInert(false);
    if (installed) { focusMainAction(); return; }
    (previousFocus?.isConnected ? previousFocus : opener).focus?.();
  }
  function finishInstallation() {
    if (installed) return;
    installed = true;
    const wasOpen = !overlay.hidden;
    const openerHadFocus = documentRef.activeElement === opener;
    overlay.hidden = true;
    setBackgroundInert(false);
    opener.hidden = true;
    if (status) status.textContent = '앱 설치가 완료되었습니다. 새 학생 앱 아이콘으로 열어 주세요.';
    if (wasOpen || openerHadFocus) focusMainAction();
  }
  opener.addEventListener('click', open);
  dismissers.forEach(button => button.addEventListener('click', close));
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  overlay.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key !== 'Tab') return;
    const focusable = [...overlay.querySelectorAll('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')];
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && documentRef.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && documentRef.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  action?.addEventListener('click', async () => {
    if (installPromptInFlight || installed) return;
    if (!platform?.hasInstallPrompt?.()) {
      if (status) status.textContent = '아래 순서대로 브라우저 메뉴에서 설치해 주세요.';
      steps?.focus();
      return;
    }
    installPromptInFlight = true;
    action.setAttribute('aria-disabled', 'true');
    dialog.setAttribute('aria-busy', 'true');
    try {
      const outcome = await platform.promptInstall().catch(() => 'unavailable');
      if (outcome === 'accepted') {
        finishInstallation();
        return;
      }
      if (status) status.textContent = '설치를 완료하지 않았습니다. 아래 순서로 다시 시도할 수 있습니다.';
    } finally {
      installPromptInFlight = false;
      action.removeAttribute('aria-disabled');
      dialog.removeAttribute('aria-busy');
      if (!overlay.hidden && action.isConnected) action.focus();
    }
  });
  platform?.onInstalled?.(finishInstallation);
  return Object.freeze({ open, close, environment });
}

function element(documentRef, tag, className, content = '') {
  const node = documentRef.createElement(tag);
  node.className = className;
  node.textContent = content;
  return node;
}

function actionName(status) {
  return { signed_out: 'sign-in', activation_code_required: 'activate', credentials_required: 'credentials', push_required: 'push', unsupported_bypass: 'continue', ready: 'open-student', error: 'retry' }[status];
}

function stateCopy(state) {
  const spec = { ...COPY[state.status] };
  if (state.message) spec.body = state.message;
  if (state.pushMode === 'ios_install') spec.action = '설치 상태 다시 확인';
  if (state.pushMode === 'manual_install') spec.action = '설치 안내 다시 확인';
  if (state.pushMode === 'permission_denied') spec.action = '브라우저 알림 설정 확인';
  if (state.pushMode === 'permission_default' || state.pushMode === 'retry') spec.action = '알림 설정 다시 시도';
  return spec;
}

function currentPreparationStep(status) {
  if (status === 'signed_out' || status === 'activation_code_required') return 1;
  if (status === 'credentials_required') return 2;
  if (status === 'push_required' || status === 'unsupported_bypass') return 3;
  if (status === 'ready') return 4;
  return 0;
}

function appendPreparationSteps(section, documentRef, status) {
  const current = currentPreparationStep(status);
  if (!current) return;
  const list = element(documentRef, 'ol', 'student-app-steps');
  list.setAttribute('aria-label', '학생 앱 준비 단계');
  for (const step of PREPARATION_STEPS) {
    const item = element(documentRef, 'li', 'student-app-step');
    const stepState = current > 3 || step.number < current ? 'complete' : step.number === current ? 'current' : 'upcoming';
    item.dataset.stepState = stepState;
    if (stepState === 'current') item.setAttribute('aria-current', 'step');
    item.append(
      element(documentRef, 'span', 'student-app-step-number', String(step.number)),
      element(documentRef, 'span', 'student-app-step-label', step.label),
    );
    list.append(item);
  }
  section.append(list);
}

function input(documentRef, id, type, autocomplete, describedBy) {
  const node = documentRef.createElement('input');
  node.id = id;
  node.name = id;
  node.type = type;
  node.autocomplete = autocomplete;
  node.required = true;
  node.setAttribute('aria-describedby', `${describedBy} student-app-status`);
  return node;
}

function appendField(section, documentRef, labelText, id, type, autocomplete, describedBy) {
  const label = element(documentRef, 'label', 'student-app-label', labelText);
  label.htmlFor = id;
  const field = input(documentRef, id, type, autocomplete, describedBy);
  section.append(label, field);
  return field;
}

export function createStudentApp(options = {}) {
  const documentRef = options.document ?? document;
  const root = options.root ?? documentRef.getElementById('student-app');
  if (!root) throw new Error('student app root is missing');
  const api = options.api ?? createMobileApi();
  const platform = options.platform ?? BROWSER_PLATFORM;
  const pushGate = options.pushGate ?? (platform
    ? createPushGate({ api, platform })
    : { assess: async value => normalizeState(value), activate: async value => normalizeState(value) });
  const navigate = options.navigate ?? (url => window.location.assign(url));
  const search = options.search ?? (typeof location === 'undefined' ? '' : location.search);
  const autoBootstrap = options.autoBootstrap !== false;
  const autoEnterReady = autoBootstrap && options.autoEnterReady !== false;
  let currentState = normalizeState(options.initialState ?? { status: 'signed_out' });
  let destroyed = false;
  let readyEntryStarted = false;
  if (options.registerShell !== false && platform?.capabilities().serviceWorker) void platform.register().catch(() => {});

  function setStatus(message, state = '') {
    const status = root.querySelector('[data-app-status]');
    if (status) {
      status.textContent = text(message);
      status.dataset.state = text(state);
    }
  }

  function focusState(section, status) {
    const field = status === 'signed_out'
      ? section.querySelector('#student-id')
      : status === 'activation_code_required'
        ? section.querySelector('#activation-code')
        : status === 'credentials_required'
          ? section.querySelector('#credentials-id')
          : null;
    (field ?? section.querySelector('[data-primary-action]') ?? section).focus();
  }

  function submitAuthForm(form, button) {
    if (typeof form.checkValidity === 'function' && !form.checkValidity()) {
      if (typeof form.reportValidity === 'function') form.reportValidity();
      return undefined;
    }
    return handleAction(button);
  }

  function authErrorMessage(error, status) {
    const code = text(error?.code).toLowerCase();
    if (code === 'invalid_credentials') return '아이디 또는 이름과 비밀번호를 확인해 주세요.';
    if (code === 'temporarily_unavailable') return '시도 횟수가 많습니다. 잠시 후 다시 시도해 주세요.';
    if (code === 'unavailable') return '현재 이 계정은 학생 앱을 이용할 수 없습니다. 학원에 문의해 주세요.';
    if (code === 'request_unavailable') return '인터넷 연결을 확인한 뒤 다시 시도해 주세요.';
    if (status === 'activation_code_required') return '6자리 활성화 코드를 확인해 주세요.';
    if (status === 'credentials_required') return '새 아이디와 비밀번호를 확인해 주세요.';
    return '입력한 정보를 확인한 뒤 다시 시도해 주세요.';
  }

  function focusAuthError(status) {
    const field = status === 'activation_code_required'
      ? root.querySelector('#activation-code')
      : status === 'credentials_required'
        ? root.querySelector('#credentials-id')
        : root.querySelector('#student-password');
    field?.setAttribute('aria-invalid', 'true');
    field?.focus();
  }

  function appendAuthFields(section, state, helpId) {
    if (state.status === 'signed_out') {
      appendField(section, documentRef, '학생 아이디 또는 이름', 'student-id', 'text', 'username', helpId);
      appendField(section, documentRef, '비밀번호', 'student-password', 'password', 'current-password', helpId);
    } else if (state.status === 'activation_code_required') {
      const code = appendField(section, documentRef, '6자리 활성화 코드', 'activation-code', 'text', 'one-time-code', helpId);
      code.inputMode = 'numeric'; code.maxLength = 6; code.pattern = '[0-9]{6}';
    } else if (state.status === 'credentials_required') {
      appendField(section, documentRef, '새 학생 아이디', 'credentials-id', 'text', 'username', helpId);
      const password = appendField(section, documentRef, '새 비밀번호', 'credentials-secret', 'password', 'new-password', helpId);
      password.minLength = 8;
    }
  }

  function appendReadySettings(section, state, helpId) {
    if (state.status !== 'ready') return;
    const settings = element(documentRef, 'div', 'student-app-settings');
    settings.setAttribute('aria-label', '학생 앱 설정');
    const notification = element(documentRef, 'p', 'student-app-setting-row', state.notificationLabel || '학습 알림 상태 확인 필요');
    notification.dataset.notificationStatus = 'true';
    settings.append(notification);
    if (state.curris?.length) {
      const label = element(documentRef, 'label', 'student-app-label', '커리큘럼');
      label.htmlFor = 'curriculum-select';
      const select = documentRef.createElement('select');
      select.id = 'curriculum-select'; select.name = 'curriculum'; select.setAttribute('aria-describedby', helpId);
      for (const curriculum of state.curris) {
        const option = documentRef.createElement('option');
        option.value = curriculum.sid; option.textContent = curriculum.cur; option.selected = curriculum.sid === state.sessionSid;
        select.append(option);
      }
      settings.append(label, select);
    }
    const logout = element(documentRef, 'button', 'student-app-secondary', '로그아웃');
    logout.type = 'button'; logout.dataset.secondaryAction = 'logout';
    logout.addEventListener('click', () => handleLogout(logout));
    settings.append(logout);
    section.append(settings);
  }

  function render(value, { allowBackward = false } = {}) {
    if (destroyed) return;
    const next = normalizeState(value);
    currentState = !allowBackward && isBackwardTransition(currentState, next) ? normalizeState({ status: 'error', errorCode: 'invalid_transition', message: '계정 단계를 다시 확인해 주세요.' }) : next;
    const spec = stateCopy(currentState);
    const section = documentRef.createElement('section');
    section.className = 'student-app-state'; section.dataset.state = currentState.status; section.tabIndex = -1;
    section.setAttribute('role', 'region'); section.setAttribute('aria-labelledby', 'student-app-state-title');
    section.append(element(documentRef, 'p', 'student-app-eyebrow', spec.eyebrow));
    appendPreparationSteps(section, documentRef, currentState.status);
    const title = element(documentRef, 'h1', 'student-app-title', spec.title); title.id = 'student-app-state-title'; section.append(title);
    const body = element(documentRef, 'p', 'student-app-copy', spec.body); body.id = 'student-app-state-help'; section.append(body);
    const form = AUTH_INPUT_STATES.has(currentState.status) ? documentRef.createElement('form') : null;
    if (form) {
      form.className = 'student-app-form';
      form.setAttribute('aria-label', spec.title);
      appendAuthFields(form, currentState, body.id);
    } else {
      appendReadySettings(section, currentState, body.id);
    }
    const status = element(documentRef, 'p', 'student-app-status', '');
    status.id = 'student-app-status'; status.dataset.appStatus = 'true'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const action = element(documentRef, 'button', 'student-app-primary', spec.action);
    action.type = form ? 'submit' : 'button'; action.dataset.primaryAction = actionName(currentState.status); action.setAttribute('aria-describedby', `${body.id} ${status.id}`);
    if (form) {
      const submit = event => { event?.preventDefault?.(); return submitAuthForm(form, action); };
      form.addEventListener('submit', submit);
      action.addEventListener('click', submit);
      form.append(status, action);
      section.append(form);
    } else {
      action.addEventListener('click', () => handleAction(action));
      section.append(status, action);
    }
    root.replaceChildren(section); focusState(section, currentState.status);
  }

  async function resolveGate(value) {
    const state = normalizeState(value);
    return state.status === 'ready' ? pushGate.assess(state) : state;
  }

  function enterReady(value) {
    const state = normalizeState(value);
    if (!autoEnterReady || readyEntryStarted || state.status !== 'ready') return false;
    readyEntryStarted = true;
    currentState = state;
    navigate(studentPageUrl(state.sessionSid, search));
    return true;
  }

  async function handleLogout(button) {
    button.disabled = true; setStatus('로그아웃 중입니다.');
    try { await api.logout(currentState.csrfToken || ''); render({ status: 'signed_out' }, { allowBackward: true }); }
    catch { render({ status: 'error', errorCode: 'logout_failed', message: '로그아웃에 실패했습니다. 다시 시도해 주세요.' }, { allowBackward: true }); }
  }

  async function handleAction(button) {
    const actionState = currentState.status;
    root.querySelectorAll('input').forEach(field => field.setAttribute('aria-invalid', 'false'));
    button.disabled = true; button.setAttribute('aria-busy', 'true'); setStatus('처리 중입니다.', 'loading');
    try {
      let next;
      if (currentState.status === 'signed_out') {
        const credentials = { id: root.querySelector('#student-id')?.value.trim() || '', password: root.querySelector('#student-password')?.value || '' };
        next = typeof api.login === 'function' ? await api.login(credentials) : await api.signIn(credentials);
        if ((next?.state ?? next?.status) === 'activation_code_required' && !next.loginId) next = { ...next, loginId: credentials.id };
        next = await resolveGate(next);
      } else if (currentState.status === 'activation_code_required') {
        next = await api.activate(root.querySelector('#activation-code')?.value.trim() || '', currentState.loginId || '');
        if ((next?.state ?? next?.status) === 'activation_code_required' && !next.loginId) next = { ...next, loginId: currentState.loginId };
        next = await resolveGate(next);
      } else if (currentState.status === 'credentials_required') {
        next = await resolveGate(await api.submitCredentials({ studentId: root.querySelector('#credentials-id')?.value.trim() || '', password: root.querySelector('#credentials-secret')?.value || '' }, currentState.csrfToken || ''));
      } else if (currentState.status === 'push_required' || currentState.status === 'unsupported_bypass') {
        next = await pushGate.activate(currentState);
      } else if (currentState.status === 'ready') {
        const targetSid = root.querySelector('#curriculum-select')?.value || currentState.sessionSid;
        if (targetSid !== currentState.sessionSid) {
          next = await resolveGate(await api.switchCurriculum(targetSid, currentState.csrfToken || ''));
          if (normalizeState(next).status !== 'ready') { render(next, { allowBackward: true }); return; }
          currentState = normalizeState(next);
        }
        navigate(studentPageUrl(currentState.sessionSid, search));
        return;
      } else next = await resolveGate(await api.getInitialState());
      if (enterReady(next)) return;
      render(next, { allowBackward: normalizeState(next).status === 'signed_out' });
    } catch (error) {
      if (AUTH_INPUT_STATES.has(actionState) && currentState.status === actionState) {
        button.disabled = false;
        button.setAttribute('aria-busy', 'false');
        setStatus(authErrorMessage(error, actionState), 'error');
        focusAuthError(actionState);
        return;
      }
      render({ status: 'error', errorCode: error?.code || 'request_failed', message: '요청을 완료하지 못했습니다. 다시 시도해 주세요.' }, { allowBackward: true });
    }
  }

  async function bootstrap() {
    render(currentState);
    if (!autoBootstrap) return currentState;
    try {
      const next = await resolveGate(await api.getInitialState());
      if (!enterReady(next)) render(next, { allowBackward: true });
    }
    catch { render({ status: 'error', errorCode: 'request_failed', message: '앱 상태를 불러오지 못했습니다.' }, { allowBackward: true }); }
    return currentState;
  }

  function destroy() { destroyed = true; root.replaceChildren(); }
  const instance = Object.freeze({ bootstrap, destroy, getState: () => currentState, render });
  void bootstrap();
  return instance;
}

let bootStarted = false;
export function bootStudentAppShell(options = {}) {
  const documentRef = options.document ?? (typeof document === 'undefined' ? null : document);
  const windowRef = options.window ?? (typeof window === 'undefined' ? null : window);
  const root = documentRef?.getElementById?.('student-app');
  if (!root) return null;
  const platform = options.platform ?? BROWSER_PLATFORM;
  const createApp = options.createApp ?? createStudentApp;
  const initializeInstallGuide = options.initInstallGuide ?? initInstallGuide;
  const app = createApp({ document: documentRef, root, platform });
  const installGuide = initializeInstallGuide({ documentRef, windowRef, platform });
  return Object.freeze({ app, installGuide });
}

function bootBrowserShell() {
  if (bootStarted || typeof document === 'undefined' || !document.getElementById('student-app')) return;
  bootStarted = true;
  bootStudentAppShell();
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootBrowserShell, { once: true });
  else bootBrowserShell();
}

export { STATES, normalizeState };
