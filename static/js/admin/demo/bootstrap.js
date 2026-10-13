import {
  DEMO_STORAGE_KEY,
  cloneDemoValue,
  loadDemoStore,
  resetDemoStore,
  saveDemoStore,
} from './store.js';
import { createDemoFetch, mergeProgressPatch } from './fetch.js?v=20260912-watch-rearm1&storeSafety=20261013';
import {
  applyAssistantStudentNotesRequest,
  isAssistantStudentNotesPath,
} from './assistantStudentNotesContract.js';
import { applyDemoHomeworkRequest } from './homeworkContract.js';
import { applyOperationNotesRequest, isOperationNotesPath } from './operationNotesContract.js';
import { applyStudentLogsRequest } from './studentLogsContract.js';
import { patchDemoTestConfig } from './testConfigContract.js?v=20260827-test-patch1';
import { applyDemoQuickPrinterRequest } from './quickPrinterContract.js?v=20260830-carryover-history1';
import { effectiveDemoRosterStudentIds } from './attendanceRosterContract.js?v=20260830-missing-leave-roster1';
import { patchDemoExtraAttendance } from './extraAttendContract.js';
import { demoVideoRevision, validateDemoVideoWrite } from './videoCatalogContract.js';
import { demoAdminState, demoAdminRevisions } from './adminStateContract.js';
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
    if (currentPath === DEMO_ROOT_PATH) {
      void import('./threadPreview.js?v=20260914-threads1')
        .then(({ initDemoThreadPreview }) => initDemoThreadPreview())
        .catch((error) => {
          demo.errors = Array.isArray(demo.errors) ? demo.errors : [];
          demo.errors.push({
            at: new Date().toISOString(),
            type: 'thread-preview-load-failed',
            message: error?.message || String(error),
          });
        });
    }
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

function canonicalDate(value) {
  const date = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return '';
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date ? date : '';
}

function demoRevision(value) {
  const text = JSON.stringify(value || {});
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `demo-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

function schoolCalendarDemoRevision(value) {
  return demoRevision(value).replace(/^demo-/, '').repeat(8);
}

function requestHeader(headers, name) {
  if (headers?.get) return String(headers.get(name) || '');
  const target = String(name || '').toLowerCase();
  const found = Object.entries(headers || {}).find(([key]) => String(key).toLowerCase() === target);
  return String(found?.[1] || '');
}

function projectedDoneEntry(entry) {
  const out = { done: true, archived: false };
  if (entry?.hwChecked === true || entry?.hwChecked === 1 || entry?.hwChecked === '1' || entry?.hwChecked === 'true') out.hwChecked = true;
  if (entry?.selfStudy === true || entry?.selfStudy === 1 || entry?.selfStudy === '1' || entry?.selfStudy === 'true') out.selfStudy = true;
  return out;
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
    return { method, url, headers: init.headers || requestLike?.headers };
  } catch {
    return null;
  }
}

async function handleDemoApiRequest(request, input, init, demo) {
  const { method, url } = request;
  const path = normalizePath(url.pathname);
  if (method === 'POST' && path === '/api/updates/ensure-today') {
    return demoJson(cloneDemoValue(loadDemoStore().updates || {}), {
      handler: 'bootstrap-fallback',
    });
  }

  const homeworkBody = method === 'GET' ? {} : await readJsonBody(input, init);
  const homeworkStore = loadDemoStore();
  const homeworkResult = applyDemoHomeworkRequest({
    method,
    path,
    params: url.searchParams,
    body: homeworkBody,
    store: homeworkStore,
    now: new Date(homeworkStore.generatedAt || '2026-06-17T00:00:00+09:00'),
  });
  if (homeworkResult) {
    if (homeworkResult.changed) saveDemoStore(homeworkStore);
    return demoJson(homeworkResult.payload, {
      status: homeworkResult.status,
      handler: 'bootstrap-fallback',
    });
  }

  const studentLogsResult = applyStudentLogsRequest({
    method,
    path,
    body: homeworkBody,
    store: homeworkStore,
    createdAt: () => new Date().toISOString(),
    today: homeworkStore.demoDate,
  });
  if (studentLogsResult) {
    if (studentLogsResult.changed) saveDemoStore(homeworkStore);
    return demoJson(studentLogsResult.payload, {
      status: studentLogsResult.status,
      handler: 'bootstrap-fallback',
    });
  }

  if (isAssistantStudentNotesPath(path)) {
    const result = applyAssistantStudentNotesRequest({
      method,
      path,
      params: url.searchParams,
      body: homeworkBody,
      store: homeworkStore,
      createdAt: () => new Date().toISOString(),
    });
    if (result.changed) saveDemoStore(homeworkStore);
    return demoJson(result.payload, {
      status: result.status,
      handler: 'bootstrap-fallback',
    });
  }

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

  if (method === 'PATCH' && path === '/api/extra-attend') {
    const latest = loadDemoStore();
    const result = patchDemoExtraAttendance(latest, homeworkBody);
    if (result.error) return demoJson({ ok: false, error: result.error }, { status: 400, handler: 'bootstrap-fallback' });
    if (result.changed) saveDemoStore(latest);
    return demoJson({ ok: true, dates: cloneDemoValue(result.dates), changedDates: result.changedDates }, { handler: 'bootstrap-fallback' });
  }

  if (method === 'POST' && path === '/api/makeup-carryover') {
    const store = loadDemoStore();
    const current = cloneDemoValue(store.makeupCarryover || {});
    const currentRevision = demoRevision(current);
    const expectedRevision = requestHeader(request.headers, 'If-Match').trim().replace(/^"|"$/g, '');
    if (!expectedRevision || expectedRevision !== currentRevision) {
      return demoJson({
        ok: false,
        error: expectedRevision ? 'makeup_revision_conflict' : 'makeup_revision_required',
      }, {
        status: expectedRevision ? 409 : 428,
        handler: 'bootstrap-fallback',
        headers: { 'X-Makeup-Carryover-Revision': currentRevision },
      });
    }
    store.makeupCarryover = homeworkBody && typeof homeworkBody === 'object'
      ? cloneDemoValue(homeworkBody)
      : {};
    saveDemoStore(store);
    return demoJson(cloneDemoValue(store.makeupCarryover), {
      handler: 'bootstrap-fallback',
      headers: {
        'X-Makeup-Carryover-Revision': demoRevision(store.makeupCarryover),
      },
    });
  }

  if (method === 'POST' && path === '/api/school-calendar') {
    const store = loadDemoStore();
    const current = cloneDemoValue(store.schoolCalendar || {});
    const currentRevision = schoolCalendarDemoRevision(current);
    const expectedRevision = requestHeader(request.headers, 'If-Match')
      .trim()
      .replace(/^W\//, '')
      .replace(/^"|"$/g, '')
      .toLowerCase();
    if (!expectedRevision || expectedRevision !== currentRevision) {
      return demoJson({
        ok: false,
        code: expectedRevision
          ? 'school_calendar_conflict'
          : 'school_calendar_revision_required',
      }, {
        status: expectedRevision ? 409 : 428,
        handler: 'bootstrap-fallback',
        headers: { 'X-School-Calendar-Revision': currentRevision },
      });
    }
    if (!homeworkBody || typeof homeworkBody !== 'object' || Array.isArray(homeworkBody)) {
      return demoJson({ ok: false, code: 'invalid_school_calendar' }, {
        status: 400,
        handler: 'bootstrap-fallback',
      });
    }
    store.schoolCalendar = cloneDemoValue(homeworkBody);
    saveDemoStore(store);
    const revision = schoolCalendarDemoRevision(store.schoolCalendar);
    return demoJson(cloneDemoValue(store.schoolCalendar), {
      handler: 'bootstrap-fallback',
      headers: {
        'X-School-Calendar-Revision': revision,
        ETag: `"${revision}"`,
      },
    });
  }

  if (method === 'POST' && path === '/api/videos') {
    const store = loadDemoStore();
    const error = validateDemoVideoWrite(store.videos || [], homeworkBody, requestHeader(request.headers, 'If-Match') || requestHeader(request.headers, 'X-Store-Revision'));
    if (error) return demoJson({ ok: false, error: error.error }, { status: error.status, handler: 'bootstrap-fallback', headers: { 'X-Store-Revision': demoVideoRevision(store.videos || []) } });
    store.videos = cloneDemoValue(homeworkBody);
    saveDemoStore(store);
    return new Response(null, { status: 204, headers: { 'X-Store-Revision': demoVideoRevision(store.videos), 'X-Admin-Demo-Handler': 'bootstrap-fallback' } });
  }

  if (method !== 'GET') {
    const mutation = await handleFallbackMutation(path, input, init);
    const responseStatus = Number(mutation?.__demoStatus) || (mutation?.ok === false ? 400 : 200);
    const responsePayload = { ...(mutation || {}) };
    delete responsePayload.__demoStatus;
    return demoJson(responsePayload, {
      status: responseStatus,
      handler: 'bootstrap-fallback',
    });
  }

  const store = loadDemoStore();
  if (path === '/api/admin/bootstrap' || path === '/api/admin/revisions') {
    const date = String(url.searchParams.get('date') || '').trim();
    const parsed = new Date(`${date}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) {
      return demoJson({ ok: false, error: 'bad date' }, { status: 400, handler: 'bootstrap-fallback' });
    }
    const project = path.endsWith('/bootstrap') ? demoAdminState : demoAdminRevisions;
    return demoJson(project(store, date, demoRevision), { handler: 'bootstrap-fallback' });
  }
  if (path === '/api/progress') {
    if (!['date', 'sid', 'sids'].some(key => String(url.searchParams.get(key) || '').trim())) {
      return demoJson({ ok: false, error: 'filter_required' }, { status: 400, handler: 'bootstrap-fallback' });
    }
    const since = String(url.searchParams.get('since') || '').trim();
    const parsed = since && new Date(`${since}T00:00:00Z`);
    if (since && (!/^\d{4}-\d{2}-\d{2}$/.test(since) || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== since)) {
      return demoJson({ ok: false, error: 'bad date' }, { status: 400, handler: 'bootstrap-fallback' });
    }
  }
  const payload = fallbackPayloadForGet(path, url.searchParams, store);
  const responseHeaders = {};
  if (path === '/api/progress') {
    responseHeaders['X-Video-Watch-Cycles'] = '1';
  } else if (path === '/api/extra-attend') {
    responseHeaders['X-Extra-Attend-Patch-Modes'] = 'replace,delta';
  } else if (path === '/api/videos') {
    responseHeaders['X-Store-Revision'] = demoVideoRevision(payload);
    responseHeaders['X-Video-Providers'] = 'kollus,youtube';
  } else if (path === '/api/makeup-carryover') {
    responseHeaders['X-Makeup-Carryover-Revision'] = demoRevision(payload);
  } else if (path === '/api/school-calendar') {
    responseHeaders['X-School-Calendar-Revision'] = schoolCalendarDemoRevision(payload);
  }
  return demoJson(payload, {
    handler: 'bootstrap-fallback',
    headers: responseHeaders,
  });
}

function demoJson(payload, { status = 200, handler = 'bootstrap', headers = {} } = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Admin-Demo': '1',
      'X-Admin-Demo-Handler': handler,
      ...headers,
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
      return unarchivedDoneSummary(store, params);
    case '/api/arrive-time/missing-leave-summary':
      return missingLeaveSummary(store, params);
    case '/api/progress':
      return cloneDemoValue(Object.fromEntries(Object.entries(filterDateSidMap(store.progress || {}, params))
        .filter(([date]) => !params.get('since') || date >= params.get('since'))));
    case '/api/extra-attend':
      return cloneDemoValue(store.extraAttend || {});
    case '/api/weekend-slots':
      return cloneDemoValue(store.weekendSlots || {});
    case '/api/today_order':
      return cloneDemoValue(store.todayOrder || {});
    case '/api/makeup-sheet-sync/config':
      return {
        ok: true,
        sheetUrl: String(store.makeupSheetSyncConfig?.sheetUrl || ''),
      };
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
    case '/api/arrive-time':
      return dateMapPayload(store.arriveTime || {}, params);
    case '/api/announce-status':
      return { ok: true, demo: true };
    case '/api/announcements':
      return cloneDemoValue(store.announcements || []);
    case '/api/admin/student-focus/summary': {
      const date = String(params.get('date') || '').trim();
      return cloneDemoValue(store.focusSummaries?.[date] || {
        ok: true, date, serverNow: new Date().toISOString(), classes: [],
      });
    }
    default:
      return {
        ok: true,
        demo: true,
        disabled: true,
        message: '데모 모드에서 안전하게 차단된 API입니다.',
      };
  }
}

function unarchivedDoneSummary(store, params) {
  const excludeDate = String(params.get('exclude_date') || params.get('excludeDate') || '').trim();
  const today = String(store.demoDate || store.dates?.current || '').trim();
  const latestBySid = new Map();
  const byDate = new Map();
  const staleStudents = new Set();
  let total = 0;

  Object.keys(store.logs || {}).sort().forEach(date => {
    const dateKey = canonicalDate(date);
    if (!dateKey) return;
    Object.entries(store.logs?.[date] || {}).forEach(([sid, entry]) => {
      const sidKey = String(sid || '').trim();
      if (!sidKey) return;
      if (!entry || typeof entry !== 'object') return;
      const done = entry.done === true || entry.done === 1 || entry.done === '1' || entry.done === 'true';
      const archived = entry.archived === true || entry.archived === 1 || entry.archived === '1' || entry.archived === 'true';
      if (!done || archived) return;

      latestBySid.set(sidKey, {
        date: dateKey,
        sid: sidKey,
        entry: projectedDoneEntry(entry),
      });
      if ((excludeDate && dateKey === excludeDate) || (today && dateKey >= today)) return;
      byDate.set(dateKey, (byDate.get(dateKey) || 0) + 1);
      staleStudents.add(sidKey);
      total += 1;
    });
  });

  return {
    ok: true,
    excludeDate,
    total,
    students: staleStudents.size,
    rowsAvailable: true,
    byDate: Array.from(byDate.entries())
      .sort(([a], [b]) => String(b).localeCompare(String(a)))
      .map(([date, count]) => ({ date, count })),
    rows: Array.from(latestBySid.values())
      .sort((a, b) => String(b.date).localeCompare(String(a.date)) || String(a.sid).localeCompare(String(b.sid))),
  };
}

function missingLeaveSummary(store, params) {
  const excludeDate = String(params.get('exclude_date') || params.get('excludeDate') || '').trim();
  const today = String(store.demoDate || store.dates?.current || '').trim();
  const absentByDate = store.absent?.by_date || {};
  const rows = [];

  Object.entries(store.arriveTime || {}).forEach(([date, bySid]) => {
    const dateKey = canonicalDate(date);
    if (!dateKey || (today && dateKey >= today) || (excludeDate && dateKey === excludeDate)) return;
    const absent = new Set(Array.isArray(absentByDate?.[dateKey]) ? absentByDate[dateKey].map(String) : []);
    const rosterIds = effectiveDemoRosterStudentIds(store, dateKey);
    Object.entries(bySid && typeof bySid === 'object' ? bySid : {}).forEach(([sid, arriveTime]) => {
      const sidKey = String(sid || '').trim();
      const arrive = String(arriveTime || '').trim();
      if (!sidKey || !arrive || absent.has(sidKey) || !rosterIds.has(sidKey)) return;
      const entry = store.logs?.[dateKey]?.[sidKey];
      const done = entry?.done === true || entry?.done === 1 || entry?.done === '1' || entry?.done === 'true';
      if (!done) rows.push({ date: dateKey, sid: sidKey, arriveTime: arrive });
    });
  });

  rows.sort((a, b) => String(b.date).localeCompare(String(a.date)) || String(a.sid).localeCompare(String(b.sid)));
  const byDate = new Map();
  rows.forEach(row => byDate.set(row.date, (byDate.get(row.date) || 0) + 1));
  return {
    ok: true,
    sinceDate: store.dates?.previous || '',
    excludeDate,
    total: rows.length,
    students: new Set(rows.map(row => row.sid)).size,
    rowsAvailable: true,
    byDate: Array.from(byDate.entries())
      .sort(([a], [b]) => String(b).localeCompare(String(a)))
      .map(([date, count]) => ({ date, count })),
    rows,
  };
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

function applyFallbackLogPatchBatch(store, body) {
  const patches = body?.patches;
  if (!Array.isArray(patches) || patches.length < 1 || patches.length > 100) {
    return { error: 'patches must contain 1 to 100 items' };
  }

  const normalized = [];
  const seen = new Set();
  for (const raw of patches) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { error: 'bad patch item' };
    const date = canonicalDate(raw.date);
    const sid = String(raw.sid || '').trim();
    const entry = raw.entry == null ? {} : raw.entry;
    const clear = raw.__clear;
    if (!date || !sid || !entry || typeof entry !== 'object' || Array.isArray(entry)) {
      return { error: 'bad patch item' };
    }
    if (clear != null && !Array.isArray(clear)) return { error: 'bad clear list' };

    const targetKey = `${date}\u0000${sid}`;
    if (seen.has(targetKey)) return { error: 'duplicate patch target' };
    seen.add(targetKey);
    normalized.push({ date, sid, entry: cloneDemoValue(entry), clear: cloneDemoValue(clear || []) });
  }

  const logs = cloneDemoValue(store.logs || {});
  normalized.forEach(({ date, sid, entry, clear }) => {
    logs[date] = logs[date] && typeof logs[date] === 'object' ? logs[date] : {};
    const previous = logs[date][sid] && typeof logs[date][sid] === 'object' ? logs[date][sid] : {};
    const next = { ...previous, ...entry };
    clear.forEach(key => { if (key != null) delete next[String(key)]; });
    logs[date][sid] = next;
  });
  store.logs = logs;
  return { count: normalized.length };
}

async function handleFallbackMutation(path, input, init) {
  const body = await readJsonBody(input, init);
  const request = normalizeFetchRequest(input, init);
  const method = request?.method || String(init?.method || 'POST').toUpperCase();
  if (path === '/api/progress/patch' && (method === 'POST' || method === 'PATCH')) {
    const store = loadDemoStore();
    const result = mergeProgressPatch(store, body);
    if (result.error) return { ok: false, error: result.error, __demoStatus: result.status || 400 };
    saveDemoStore(store);
    return { ok: true, progress: result.progress };
  }

  const quickPrinterStore = loadDemoStore();
  const quickPrinterResult = applyDemoQuickPrinterRequest({
    method,
    path,
    body,
    store: quickPrinterStore,
    createdAt: () => new Date().toISOString(),
  });
  if (quickPrinterResult) {
    if (quickPrinterResult.changed) saveDemoStore(quickPrinterStore);
    return {
      ...cloneDemoValue(quickPrinterResult.payload),
      __demoStatus: quickPrinterResult.status,
    };
  }

  if (path === '/api/tests-config/test' && method === 'PATCH') {
    const store = loadDemoStore();
    const result = patchDemoTestConfig(store.testsConfig || { categories: {} }, body);
    if (!result.ok) return { ok: false, demo: true, error: result.error };
    store.testsConfig = result.config;
    saveDemoStore(store);
    return { ok: true, demo: true, test: result.test };
  }

  if (path === '/api/logs/patch-batch' && method === 'POST') {
    const store = loadDemoStore();
    const result = applyFallbackLogPatchBatch(store, body);
    if (result.error) return { ok: false, demo: true, error: result.error };
    saveDemoStore(store);
    return { ok: true, demo: true, count: result.count };
  }

  if (path === '/api/makeup-sheet-sync/config' && method === 'POST') {
    const sheetUrl = String(body?.sheetUrl || '').trim();
    if (!sheetUrl.includes('docs.google.com/spreadsheets/d/')) {
      return { ok: false, demo: true, error: 'Google Sheets link required' };
    }
    const store = loadDemoStore();
    store.makeupSheetSyncConfig = {
      ...(store.makeupSheetSyncConfig && typeof store.makeupSheetSyncConfig === 'object'
        ? store.makeupSheetSyncConfig
        : {}),
      sheetUrl,
    };
    saveDemoStore(store);
    return { ok: true, demo: true, sheetUrl };
  }

  if (path === '/api/makeup-sheet-sync' && method === 'POST') {
    return {
      ok: true,
      demo: true,
      mode: 'additive-only',
      opened: 0,
      added: 0,
      skippedExisting: 0,
      unmatchedStarredRows: 0,
      months: [],
    };
  }

  if (path === '/api/absent/recover') {
    const date = canonicalDate(body?.date);
    const selected = new Set((Array.isArray(body?.sids) ? body.sids : [])
      .map(value => String(value || '').trim())
      .filter(Boolean));
    if (!date || !selected.size) {
      return { ok: false, demo: true, error: 'missing date or sids' };
    }
    const store = loadDemoStore();
    const absent = cloneDemoValue(store.absent || { by_date: {}, by_student: {}, by_slot: {} });
    absent.by_date ||= {};
    absent.by_student ||= {};
    absent.by_slot ||= {};
    absent.by_date[date] = (absent.by_date[date] || []).filter(sid => !selected.has(String(sid)));
    selected.forEach(sid => {
      if (String(absent.by_student[sid] || '') === date) delete absent.by_student[sid];
      if (absent.by_slot[date]) delete absent.by_slot[date][sid];
    });
    if (absent.by_slot[date] && !Object.keys(absent.by_slot[date]).length) delete absent.by_slot[date];
    saveDemoStore({ ...store, absent });
    return cloneDemoValue(absent);
  }

  if (path === '/api/today_order' && method === 'PATCH') {
    const date = canonicalDate(body?.date);
    if (!date || !Array.isArray(body?.order)) return { ok: false, demo: true, error: 'invalid date or order' };
    const order = Array.from(new Set(body.order.map(value => String(value || '').trim()).filter(Boolean)));
    const store = loadDemoStore();
    store.todayOrder = store.todayOrder && typeof store.todayOrder === 'object' ? store.todayOrder : {};
    store.todayOrder[date] = order;
    saveDemoStore(store);
    return { ok: true, demo: true, date, order };
  }

  if (path === '/api/today_order' && method === 'DELETE') {
    const date = canonicalDate(request?.url?.searchParams?.get('date'));
    if (!date) return { ok: false, demo: true, error: 'invalid date' };
    const store = loadDemoStore();
    store.todayOrder = store.todayOrder && typeof store.todayOrder === 'object' ? store.todayOrder : {};
    const cleared = Object.prototype.hasOwnProperty.call(store.todayOrder, date);
    delete store.todayOrder[date];
    saveDemoStore(store);
    return { ok: true, demo: true, date, cleared };
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
    'min-width:44px',
    'min-height:44px',
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
