import {
  DEMO_STORAGE_KEY,
  cloneDemoValue,
  loadDemoStore,
  resetDemoStore,
  saveDemoStore,
} from './store.js';
import { createDemoFetch } from './fetch.js';
import { applyOperationNotesRequest, isOperationNotesPath } from './operationNotesContract.js';
import { applyStudentLogsRequest } from './studentLogsContract.js';
import { installDemoTutorial } from './tutorial.js';

const DEMO_ROOT_PATH = '/demo/rh3123';
const DEMO_PATHS = new Set([
  DEMO_ROOT_PATH,
  `${DEMO_ROOT_PATH}/students`,
  `${DEMO_ROOT_PATH}/school-cal`,
  `${DEMO_ROOT_PATH}/video-manage`,
  `${DEMO_ROOT_PATH}/tests`,
]);
const DEMO_ROUTE_MAP = new Map([
  ['/admin', DEMO_ROOT_PATH],
  ['/dh1130', DEMO_ROOT_PATH],
  ['/students', `${DEMO_ROOT_PATH}/students`],
  ['/school-cal', `${DEMO_ROOT_PATH}/school-cal`],
  ['/video-manage', `${DEMO_ROOT_PATH}/video-manage`],
  ['/tests', `${DEMO_ROOT_PATH}/tests`],
]);
const DEMO_RESET_PATH = DEMO_ROOT_PATH;
const BLOCK_MESSAGE = '데모 모드에서는 실제 관리 화면이나 외부 자료를 열지 않습니다.';
var toastTimer = null;

const currentPath = normalizePath(window.location.pathname);

if (isDemoPath(currentPath)) {
  installDemoBootstrap();
}

function normalizePath(pathname) {
  const path = String(pathname || '/').replace(/\/+$/, '');
  return path || '/';
}

function isDemoPath(pathname) {
  return DEMO_PATHS.has(normalizePath(pathname));
}

function installDemoBootstrap() {
  const demo = window.__adminDemo && typeof window.__adminDemo === 'object'
    ? window.__adminDemo
    : {};

  demo.enabled = true;
  demo.mode = 'admin-training-demo';
  demo.rootPath = DEMO_ROOT_PATH;
  demo.currentPath = currentPath;
  demo.blockedNavigations = Array.isArray(demo.blockedNavigations) ? demo.blockedNavigations : [];
  demo.fetchLog = Array.isArray(demo.fetchLog) ? demo.fetchLog : [];
  demo.forwardedApiCalls = Array.isArray(demo.forwardedApiCalls) ? demo.forwardedApiCalls : [];
  demo.bootstrapEvents = Array.isArray(demo.bootstrapEvents) ? demo.bootstrapEvents : [];
  demo.fetchInstalledBeforeBootstrap = false;
  demo.showMessage = showDemoMessage;
  demo.reset = resetDemoSession;
  demo.registerFetchHandler = (handler) => {
    demo.fetchHandler = typeof handler === 'function' ? handler : null;
  };
  demo.bootstrapEvents.push({
    at: new Date().toISOString(),
    type: 'bootstrap:start',
    pathname: window.location.pathname,
  });

  window.__adminDemo = demo;
  try {
    const demoFetch = createDemoFetch({
      window,
      originalFetch: window.fetch.bind(window),
    });
    demo.registerFetchHandler(({ input, init }) => demoFetch(input, init));
    demo.fetchLayerLoaded = true;
    demo.bootstrapEvents.push({
      at: new Date().toISOString(),
      type: 'fetch-layer:loaded',
      source: 'fetch.js',
    });
  } catch (err) {
    demo.fetchLayerLoaded = false;
    demo.errors = Array.isArray(demo.errors) ? demo.errors : [];
    demo.errors.push({
      at: new Date().toISOString(),
      type: 'fetch-layer-load-failed',
      message: err?.message || String(err),
    });
  }
  installFetchGuard(demo);
  demo.fetchInstalledBeforeBootstrap = true;
  demo.bootstrapEvents.push({
    at: new Date().toISOString(),
    type: 'fetch:installed-before-admin-main',
  });
  installNavigationGuard(demo);
  installWindowOpenGuard(demo);
  onReady(() => {
    injectDemoControls();
    installDemoTutorial({ window, demo });
  });
  showDemoMessage('데모 모드입니다. 모든 응답은 더미 데이터 기준입니다.', { quiet: true });
}

function onReady(fn) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fn, { once: true });
  } else {
    fn();
  }
}

function installFetchGuard(demo) {
  if (demo.fetchGuardInstalled) return;

  const originalFetch = window.fetch.bind(window);
  demo.originalFetch = originalFetch;

  window.fetch = async (input, init = {}) => {
    const request = normalizeFetchRequest(input, init);
    if (!request) return originalFetch(input, init);

    const { method, url } = request;
    const path = normalizePath(url.pathname);
    const isDemoApi = url.origin === window.location.origin
      && (path.startsWith('/api/') || path === '/arrive-time' || path.startsWith('/arrive-time/'));

    if (!isDemoApi) {
      return originalFetch(input, init);
    }

    const apiCall = {
      at: new Date().toISOString(),
      method,
      url: `${path}${url.search}`,
    };

    try {
      if (typeof demo.fetchHandler === 'function') {
        const handled = await demo.fetchHandler({ input, init, request, originalFetch });
        if (handled instanceof Response) {
          demo.fetchLog.push({ ...apiCall, handledBy: 'registered' });
          return handled;
        }
      }

      const response = await handleDemoApiRequest(request, input, init, demo);
      demo.fetchLog.push({ ...apiCall, handledBy: response.headers.get('X-Admin-Demo-Handler') || 'bootstrap' });
      return response;
    } catch (err) {
      demo.fetchLog.push({ ...apiCall, handledBy: 'bootstrap-error', error: err?.message || String(err) });
      return demoJson({
        ok: false,
        demo: true,
        error: '데모 응답을 만드는 중 오류가 발생했습니다.',
      }, { status: 200, handler: 'bootstrap-error' });
    }
  };

  demo.fetchGuardInstalled = true;
}

function normalizeFetchRequest(input, init = {}) {
  try {
    const requestLike = typeof Request !== 'undefined' && input instanceof Request ? input : null;
    const rawUrl = requestLike ? requestLike.url : input;
    const url = new URL(rawUrl, window.location.origin);
    const method = String(init.method || requestLike?.method || 'GET').toUpperCase();
    return { method, url };
  } catch {
    return null;
  }
}

async function handleDemoApiRequest(request, input, init, demo) {
  const { method, url } = request;
  const path = normalizePath(url.pathname);

  if (isOperationNotesPath(path)) {
    const body = method === 'GET' ? {} : await readJsonBody(input, init);
    const store = loadDemoStore();
    const result = applyOperationNotesRequest({
      method,
      path,
      body,
      store,
      createdAt: () => new Date().toISOString(),
    });
    if (result.changed) saveDemoStore(store);
    return demoJson(result.payload, {
      status: result.status,
      handler: 'bootstrap-fallback',
    });
  }

  if (method !== 'GET') {
    const mutation = await handleFallbackMutation(path, input, init);
    return demoJson(mutation, { handler: 'bootstrap-fallback' });
  }

  const store = loadDemoStore();
  const payload = fallbackPayloadForGet(path, url.searchParams, store);
  return demoJson(payload, { handler: 'bootstrap-fallback' });
}

function demoJson(payload, { status = 200, handler = 'bootstrap' } = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Admin-Demo': '1',
      'X-Admin-Demo-Handler': handler,
    },
  });
}

async function readJsonBody(input, init = {}) {
  const raw = init.body ?? await requestBodyText(input);
  if (!raw) return {};
  if (typeof FormData !== 'undefined' && raw instanceof FormData) return Object.fromEntries(raw.entries());
  if (typeof URLSearchParams !== 'undefined' && raw instanceof URLSearchParams) return Object.fromEntries(raw.entries());
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch {
      return { message: raw };
    }
  }
  if (raw && typeof raw === 'object') return raw;
  return {};
}

async function requestBodyText(input) {
  if (typeof Request === 'undefined' || !(input instanceof Request)) return '';
  try {
    return await input.clone().text();
  } catch {
    return '';
  }
}

function fallbackPayloadForGet(path, params, store) {
  switch (path) {
    case '/api/students':
      return cloneDemoValue(store.students || []);
    case '/api/videos':
      return cloneDemoValue(store.videos || []);
    case '/api/materials':
      return cloneDemoValue(store.materials || {});
    case '/api/mat-assign':
      return cloneDemoValue(store.matAssign || {});
    case '/api/updates':
      return cloneDemoValue(filterDateSidMap(store.updates || {}, params));
    case '/api/logs':
      return cloneDemoValue(filterDateSidMap(store.logs || {}, params));
    case '/api/homework-books':
      return cloneDemoValue(homeworkBooksBySid(store.logs || {}));
    case '/api/logs/entry':
      return {
        ok: true,
        entry: cloneDemoValue(entryForDateSid(store.logs || {}, params)),
      };
    case '/api/logs/unarchived-summary':
      return { total: 0, byDate: [] };
    case '/api/student-logs':
      return { ok: true, logs: cloneDemoValue(store.studentOperationLogs || []) };
    case '/api/progress':
      return cloneDemoValue(filterDateSidMap(store.progress || {}, params));
    case '/api/extra-attend':
      return cloneDemoValue(store.extraAttend || {});
    case '/api/weekend-slots':
      return cloneDemoValue(store.weekendSlots || {});
    case '/api/today_order':
      return cloneDemoValue(store.todayOrder || {});
    case '/api/makeup-carryover':
      return cloneDemoValue(store.makeupCarryover || {});
    case '/api/absent':
      return cloneDemoValue(store.absent || { by_date: {}, by_student: {}, by_slot: {} });
    case '/api/school-calendar':
      return cloneDemoValue(store.schoolCalendar || {});
    case '/api/tests-config':
      return cloneDemoValue(store.testsConfig || { categories: {} });
    case '/api/tests':
      return cloneDemoValue(store.tests || {});
    case '/api/attendance':
    case '/api/attend':
      return dateMapPayload(store.attendance || {}, params);
    case '/api/contact':
      return dateMapPayload(store.contact || {}, params);
    case '/arrive-time':
    case '/api/arrive-time':
      return dateMapPayload(store.arriveTime || {}, params);
    case '/api/announce-status':
      return { ok: true, demo: true };
    case '/api/announcements':
      return cloneDemoValue(store.announcements || []);
    default:
      return {
        ok: true,
        demo: true,
        disabled: true,
        message: '데모 모드에서 안전하게 차단된 API입니다.',
      };
  }
}

function homeworkBooksBySid(logs) {
  const out = {};
  Object.keys(logs || {}).sort().reverse().forEach(date => {
    Object.entries(logs?.[date] || {}).forEach(([sid, entry]) => {
      if (out[sid]) return;
      const seen = new Set();
      const books = (Array.isArray(entry?.homeworkTable) ? entry.homeworkTable : [])
        .filter(row => row && typeof row === 'object' && !row._deleted)
        .map(row => String(row.book || '').trim())
        .filter(book => {
          const key = book.replace(/\s+/g, '').toLowerCase();
          if (!key || seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      if (books.length) out[String(sid)] = books;
    });
  });
  return out;
}

async function handleFallbackMutation(path, input, init) {
  const body = await readJsonBody(input, init);

  const store = loadDemoStore();
  const studentLogsResult = applyStudentLogsRequest({
    method: String(init?.method || input?.method || 'POST').toUpperCase(),
    path,
    body,
    store,
    createdAt: () => new Date().toISOString(),
    today: store.demoDate,
  });
  if (studentLogsResult) {
    if (studentLogsResult.changed) saveDemoStore(store);
    return { demo: true, ...studentLogsResult.payload };
  }
  if (path === '/api/today_order/patch') {
    const date = String(body?.date || '').trim();
    const parsed = /^\d{4}-\d{2}-\d{2}$/.test(date) ? new Date(`${date}T00:00:00Z`) : null;
    if (!parsed || Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) {
      return { ok: false, demo: true, error: 'invalid date' };
    }
    const remove = body?.remove === true;
    if (!remove && !Array.isArray(body?.order)) {
      return { ok: false, demo: true, error: 'order must be a list' };
    }
    const todayOrder = store.todayOrder && typeof store.todayOrder === 'object' ? store.todayOrder : {};
    const order = remove
      ? []
      : Array.from(new Set(body.order.map(value => String(value).trim()).filter(Boolean)));
    if (remove) delete todayOrder[date];
    else todayOrder[date] = order;
    saveDemoStore({ ...store, todayOrder });
    return { ok: true, demo: true, date, order, removed: remove };
  }


  if (path === '/api/today_order') {
    saveDemoStore({ ...loadDemoStore(), todayOrder: body && typeof body === 'object' ? body : {} });
    return { ok: true, demo: true };
  }

  if (path === '/api/announcements/image') {
    return {
      ok: false,
      demo: true,
      error: '데모 모드에서는 이미지 업로드를 사용할 수 없습니다.',
    };
  }

  if (path === '/api/announcements' || path.startsWith('/api/announcements/')) {
    return {
      ok: true,
      demo: true,
      item: {
        id: `demo-ann-${Date.now()}`,
        ...(body && typeof body === 'object' ? body : {}),
      },
    };
  }

  return {
    ok: true,
    demo: true,
    disabled: true,
    message: '데모 모드에서 실제 저장 없이 처리했습니다.',
  };
}

function filterDateSidMap(map, params) {
  const date = String(params.get('date') || '').trim();
  const sid = String(params.get('sid') || '').trim();
  const sids = String(params.get('sids') || '').split(',').map(item => item.trim()).filter(Boolean);

  if (date && sid) {
    return { [date]: { [sid]: map?.[date]?.[sid] || {} } };
  }
  if (date) {
    return { [date]: map?.[date] || {} };
  }
  if (sid || sids.length) {
    const wanted = new Set(sid ? [sid] : sids);
    const out = {};
    Object.entries(map || {}).forEach(([day, rows]) => {
      Object.entries(rows || {}).forEach(([rowSid, value]) => {
        if (!wanted.has(String(rowSid))) return;
        out[day] = out[day] || {};
        out[day][rowSid] = value;
      });
    });
    return out;
  }
  return map || {};
}

function entryForDateSid(map, params) {
  const date = String(params.get('date') || '').trim();
  const sid = String(params.get('sid') || '').trim();
  return map?.[date]?.[sid] || {};
}

function dateMapPayload(map, params) {
  const date = String(params.get('date') || '').trim();
  if (!date) return cloneDemoValue(map || {});
  return cloneDemoValue(map?.[date] || {});
}

function installNavigationGuard(demo) {
  if (demo.navigationGuardInstalled) return;
  document.addEventListener('click', (event) => {
    const target = event.target?.closest?.('a[href]');
    if (!target) return;

    const href = target.getAttribute('href') || '';
    const demoHref = demoUrlForNavigation(href);
    if (demoHref) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation?.();
      window.location.assign(demoHref);
      return;
    }

    if (!shouldBlockNavigation(href)) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
    recordBlockedNavigation(demo, href, 'click', target);
  }, true);
  demo.navigationGuardInstalled = true;
}

function installWindowOpenGuard(demo) {
  if (demo.windowOpenGuardInstalled) return;
  const originalOpen = typeof window.open === 'function' ? window.open.bind(window) : null;
  demo.originalWindowOpen = originalOpen;

  window.open = (url = '', target = '', features = '') => {
    const demoHref = demoUrlForNavigation(url);
    if (demoHref) {
      window.location.assign(demoHref);
      return null;
    }
    if (shouldBlockNavigation(url)) {
      recordBlockedNavigation(demo, url, 'window.open');
      return null;
    }
    return originalOpen ? originalOpen(url, target, features) : null;
  };

  demo.windowOpenGuardInstalled = true;
}

function demoUrlForNavigation(rawUrl) {
  const raw = String(rawUrl || '').trim();
  if (!raw || raw === '#' || raw.startsWith('#') || raw.toLowerCase().startsWith('javascript:')) return '';

  let url;
  try {
    url = new URL(raw, window.location.href);
  } catch {
    return '';
  }

  if (url.origin !== window.location.origin) return '';
  const path = normalizePath(url.pathname);
  if (DEMO_PATHS.has(path)) return `${url.pathname}${url.search}${url.hash}`;
  const mapped = DEMO_ROUTE_MAP.get(path);
  if (!mapped) return '';
  return `${mapped}${url.search}${url.hash}`;
}

function shouldBlockNavigation(rawUrl) {
  const raw = String(rawUrl || '').trim();
  if (!raw || raw === '#' || raw.startsWith('#') || raw.toLowerCase().startsWith('javascript:')) return false;

  let url;
  try {
    url = new URL(raw, window.location.href);
  } catch {
    return true;
  }

  if (!['http:', 'https:'].includes(url.protocol)) return true;
  if (url.origin !== window.location.origin) return true;

  const path = normalizePath(url.pathname);
  if (isDemoPath(path)) return false;
  return true;
}

function recordBlockedNavigation(demo, rawUrl, source, element = null) {
  const normalized = normalizeBlockedUrl(rawUrl);
  demo.blockedNavigations.push({
    at: new Date().toISOString(),
    source,
    url: normalized,
    selector: element ? describeElement(element) : '',
  });
  showDemoMessage(BLOCK_MESSAGE);
}

function normalizeBlockedUrl(rawUrl) {
  try {
    return new URL(rawUrl, window.location.href).href;
  } catch {
    return String(rawUrl || '');
  }
}

function describeElement(element) {
  if (!element) return '';
  if (element.id) return `#${element.id}`;
  if (element.className && typeof element.className === 'string') {
    return `${element.tagName.toLowerCase()}.${element.className.trim().split(/\s+/).join('.')}`;
  }
  return element.tagName ? element.tagName.toLowerCase() : '';
}

function injectDemoControls() {
  if (document.getElementById('adminDemoIndicator')) return;
  const host = document.querySelector('.global-links') || document.body;
  if (!host) return;

  const wrap = document.createElement('span');
  wrap.id = 'adminDemoIndicator';
  wrap.setAttribute('role', 'group');
  wrap.setAttribute('aria-label', '데모 모드 제어');
  wrap.style.cssText = [
    'display:inline-flex',
    'align-items:center',
    'gap:6px',
    'min-height:32px',
    'padding:0 10px',
    'border:1px solid #f4b63f',
    'border-radius:999px',
    'background:#fff7df',
    'color:#613b00',
    'font-size:12px',
    'font-weight:700',
    'white-space:nowrap',
    'vertical-align:middle',
  ].join(';');

  const label = document.createElement('span');
  label.textContent = '데모 모드';
  wrap.appendChild(label);

  const resetButton = document.createElement('button');
  resetButton.type = 'button';
  resetButton.textContent = '초기화';
  resetButton.style.cssText = [
    'border:0',
    'border-left:1px solid rgba(97,59,0,.25)',
    'background:transparent',
    'color:#613b00',
    'font:inherit',
    'font-weight:800',
    'padding:0 0 0 7px',
    'cursor:pointer',
  ].join(';');
  resetButton.addEventListener('click', () => resetDemoSession());
  wrap.appendChild(resetButton);

  const guideButton = document.createElement('button');
  guideButton.type = 'button';
  guideButton.dataset.adminDemoAction = 'help';
  guideButton.textContent = '도움말';
  guideButton.style.cssText = resetButton.style.cssText;
  guideButton.addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('admin-demo:tutorial-open'));
  });
  wrap.appendChild(guideButton);

  if (host === document.body) {
    wrap.style.position = 'fixed';
    wrap.style.top = '12px';
    wrap.style.right = '12px';
    wrap.style.zIndex = '10000';
    if (window.matchMedia('(max-width: 520px)').matches) {
      wrap.style.top = 'auto';
      wrap.style.bottom = '12px';
    }
    document.body.appendChild(wrap);
  } else {
    host.insertBefore(wrap, host.firstChild);
  }
}

function resetDemoSession() {
  try {
    const keys = [];
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = sessionStorage.key(i);
      if (key && (key === DEMO_STORAGE_KEY || key.startsWith(`${DEMO_STORAGE_KEY}.`) || key.startsWith('academy.adminDemo.'))) {
        keys.push(key);
      }
    }
    keys.forEach(key => sessionStorage.removeItem(key));
  } catch {
  }
  resetDemoStore();
  window.location.assign(DEMO_RESET_PATH);
}

function showDemoMessage(message, options = {}) {
  const text = String(message || BLOCK_MESSAGE);
  const toast = ensureToast();
  toast.textContent = text;
  toast.hidden = false;
  toast.style.opacity = options.quiet ? '0.92' : '1';
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, options.quiet ? 1600 : 3200);
}

function ensureToast() {
  let toast = document.getElementById('adminDemoToast');
  if (toast) return toast;

  toast = document.createElement('div');
  toast.id = 'adminDemoToast';
  toast.setAttribute('role', 'status');
  toast.setAttribute('aria-live', 'polite');
  toast.style.cssText = [
    'position:fixed',
    'right:18px',
    'bottom:18px',
    'max-width:min(360px, calc(100vw - 36px))',
    'padding:10px 12px',
    'border:1px solid rgba(97,59,0,.22)',
    'border-radius:8px',
    'background:#1f2937',
    'color:white',
    'box-shadow:0 10px 24px rgba(0,0,0,.22)',
    'font-size:13px',
    'line-height:1.45',
    'z-index:10000',
  ].join(';');
  document.body.appendChild(toast);
  return toast;
}
