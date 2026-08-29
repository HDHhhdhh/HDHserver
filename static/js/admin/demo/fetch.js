import { cloneDemoValue, loadDemoStore, saveDemoStore } from './store.js';
import { applyAssistantStudentNotesRequest } from './assistantStudentNotesContract.js';
import { applyDemoHomeworkRequest } from './homeworkContract.js';
import { applyOperationNotesRequest } from './operationNotesContract.js';
import { applyStudentLogsRequest } from './studentLogsContract.js';
import { patchDemoTestConfig } from './testConfigContract.js?v=20260827-test-patch1';

const DEFAULT_DEMO_NOW = '2026-06-17T00:00:00+09:00';
const JSON_HEADERS = Object.freeze({ 'Content-Type': 'application/json; charset=utf-8' });
const PATCH_METHODS = new Set(['POST', 'PATCH']);
const WRITE_METHODS = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);
const DEMO_UPLOAD_URL = '/demo-assets/images/uploaded-demo-image.png';
const TEST_ASSIGN_CHANGE_ORDER_KEY = '__testAssignmentChangeOrder';
const TEST_ASSIGN_TOUCHED_KEYS_KEY = '__testAssignmentTouchedKeys';

function getLocationOrigin(root) {
  const loc = root?.location || globalThis.location;
  return loc?.origin || 'http://localhost';
}

function getResponseCtor(root) {
  return root?.Response || globalThis.Response;
}

function clone(value) {
  return cloneDemoValue(value);
}

function nowIso() {
  return new Date().toISOString();
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

function stripTrailingSlash(pathname) {
  const value = String(pathname || '/');
  return value.length > 1 ? value.replace(/\/+$/, '') : value;
}

function isApiLikePath(pathname) {
  const path = stripTrailingSlash(pathname);
  return path === '/api' || path.startsWith('/api/') || path === '/arrive-time' || path.startsWith('/arrive-time/');
}

function normalizeMethod(input, init) {
  return String(init?.method || input?.method || 'GET').toUpperCase();
}

function normalizeHeaders(input, init) {
  if (init?.headers) return init.headers;
  return input?.headers || undefined;
}

function normalizeFetchRequest(input, init = {}, root = globalThis) {
  const locOrigin = getLocationOrigin(root);
  const rawUrl = typeof input === 'string' || input instanceof URL
    ? String(input)
    : String(input?.url || '');
  const url = new URL(rawUrl || '/', locOrigin);
  return {
    input,
    init,
    url,
    path: stripTrailingSlash(url.pathname),
    method: normalizeMethod(input, init),
    headers: normalizeHeaders(input, init),
    body: Object.prototype.hasOwnProperty.call(init, 'body') ? init.body : undefined,
    request: (typeof Request !== 'undefined' && input instanceof Request) ? input : null,
  };
}

function responseJson(root, body, status = 200, extraHeaders = {}) {
  const ResponseCtor = getResponseCtor(root);
  return new ResponseCtor(JSON.stringify(body), {
    status,
    headers: {
      ...JSON_HEADERS,
      'Cache-Control': 'no-store',
      ...extraHeaders,
    },
  });
}

function responseText(root, text, status = 200, extraHeaders = {}) {
  const ResponseCtor = getResponseCtor(root);
  return new ResponseCtor(String(text ?? ''), {
    status,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'no-store',
      ...extraHeaders,
    },
  });
}

function ok(root, body = { ok: true }) {
  return responseJson(root, body, 200);
}

function badRequest(root, error, details = {}) {
  return responseJson(root, { ok: false, error, ...details }, 400);
}

function notFound(root, error, details = {}) {
  return responseJson(root, { ok: false, error, ...details }, 404);
}

function unsupported(root, url, method) {
  return responseJson(root, {
    ok: false,
    error: 'demo unsupported endpoint',
    demo: true,
    method,
    path: url.pathname,
  }, 404);
}

async function readTextBody(ctx) {
  if (ctx.request) {
    try {
      return await ctx.request.clone().text();
    } catch {
      return '';
    }
  }
  if (typeof ctx.body === 'string') return ctx.body;
  if (ctx.body == null) return '';
  if (ctx.body instanceof URLSearchParams) return ctx.body.toString();
  if (typeof Blob !== 'undefined' && ctx.body instanceof Blob) {
    try { return await ctx.body.text(); } catch { return ''; }
  }
  if (ctx.body instanceof ArrayBuffer) {
    return new TextDecoder().decode(ctx.body);
  }
  if (ArrayBuffer.isView(ctx.body)) {
    return new TextDecoder().decode(ctx.body);
  }
  return '';
}

function looksLikeFormData(value) {
  return typeof FormData !== 'undefined' && value instanceof FormData;
}

async function readFormDataBody(ctx) {
  if (looksLikeFormData(ctx.body)) return ctx.body;
  if (ctx.request && typeof ctx.request.clone().formData === 'function') {
    try { return await ctx.request.clone().formData(); } catch { return null; }
  }
  return null;
}

async function readJsonBody(ctx) {
  if (ctx.body && typeof ctx.body === 'object' && !looksLikeFormData(ctx.body) && !(ctx.body instanceof URLSearchParams) && !(typeof Blob !== 'undefined' && ctx.body instanceof Blob) && !(ctx.body instanceof ArrayBuffer) && !ArrayBuffer.isView(ctx.body)) {
    return clone(ctx.body);
  }
  const text = await readTextBody(ctx);
  if (!String(text || '').trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('bad json');
  }
}

function dateParam(url, store) {
  return String(url.searchParams.get('date') || store.demoDate || store.dates?.current || '').trim();
}

function sidParam(url) {
  return String(url.searchParams.get('sid') || '').trim();
}

function ensureDateMap(store, key, date) {
  store[key] = store[key] && typeof store[key] === 'object' ? store[key] : {};
  store[key][date] = store[key][date] && typeof store[key][date] === 'object' && !Array.isArray(store[key][date])
    ? store[key][date]
    : {};
  return store[key][date];
}

function ensureArrayDateMap(store, key, date) {
  store[key] = store[key] && typeof store[key] === 'object' ? store[key] : {};
  store[key][date] = Array.isArray(store[key][date]) ? store[key][date] : [];
  return store[key][date];
}

function removeEmptyDateMap(store, key, date) {
  if (store[key]?.[date] && typeof store[key][date] === 'object' && !Array.isArray(store[key][date]) && Object.keys(store[key][date]).length === 0) {
    delete store[key][date];
  }
}

function filterDateSidMap(source, url) {
  const map = source && typeof source === 'object' ? source : {};
  const date = String(url.searchParams.get('date') || '').trim();
  const sid = String(url.searchParams.get('sid') || '').trim();
  const sids = String(url.searchParams.get('sids') || '')
    .split(',')
    .map(value => value.trim())
    .filter(Boolean);

  let out = clone(map);
  if (date) out = { [date]: clone(map[date] || {}) };
  if (sid || sids.length) {
    const wanted = new Set([sid, ...sids].filter(Boolean).map(String));
    const next = {};
    Object.entries(out).forEach(([dateKey, bySid]) => {
      const rows = {};
      if (bySid && typeof bySid === 'object') {
        Object.entries(bySid).forEach(([rowSid, entry]) => {
          if (wanted.has(String(rowSid))) rows[String(rowSid)] = clone(entry);
        });
      }
      if (Object.keys(rows).length || date) next[dateKey] = rows;
    });
    out = next;
  }
  return out;
}

function getLogEntry(store, url) {
  const date = dateParam(url, store);
  const sid = sidParam(url);
  if (!date || !sid) return {};
  return clone(store.logs?.[date]?.[sid] || {});
}

function applyClearKeys(entry, clearKeys) {
  if (!Array.isArray(clearKeys)) return entry;
  clearKeys.forEach(key => {
    if (key != null) delete entry[String(key)];
  });
  return entry;
}

function mergeLogPatch(store, body) {
  const date = String(body?.date || '').trim();
  const sid = String(body?.sid || '').trim();
  if (!date || !sid) return { error: 'missing date or sid' };
  const bySid = ensureDateMap(store, 'logs', date);
  const previous = bySid[sid] && typeof bySid[sid] === 'object' ? bySid[sid] : {};
  const entryPatch = body.entry && typeof body.entry === 'object' ? body.entry : {};
  const next = applyClearKeys({ ...previous, ...clone(entryPatch) }, body.__clear);
  bySid[sid] = next;
  return { entry: clone(next) };
}

function mergeLogPatchBatch(store, body) {
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
    normalized.push({
      date,
      sid,
      entry: clone(entry),
      ...(Array.isArray(clear) ? { __clear: clone(clear) } : {}),
    });
  }

  const draft = { ...store, logs: clone(store.logs || {}) };
  normalized.forEach(patch => mergeLogPatch(draft, patch));
  store.logs = draft.logs;
  return { count: normalized.length };
}

function mergeProgressPatch(store, body) {
  const date = String(body?.date || '').trim();
  const sid = String(body?.sid || '').trim();
  if (!date || !sid) return { error: 'missing date or sid' };
  const bySid = ensureDateMap(store, 'progress', date);
  const previous = bySid[sid] && typeof bySid[sid] === 'object' ? bySid[sid] : {};
  const patch = body.progress && typeof body.progress === 'object' ? body.progress : {};
  const next = { ...previous };
  const manualMeta = next.__manualProgressMids && typeof next.__manualProgressMids === 'object'
    ? { ...next.__manualProgressMids }
    : {};
  const touchedTestKeys = new Set(
    Array.isArray(patch[TEST_ASSIGN_TOUCHED_KEYS_KEY])
      ? patch[TEST_ASSIGN_TOUCHED_KEYS_KEY].map(key => String(key || '').trim()).filter(Boolean)
      : [],
  );
  const patchedTestKeys = new Set();
  const changedTestKeys = new Set();
  let sawTestsPatch = false;
  const testStatusName = (value) => {
    if (value && typeof value === 'object') {
      if (value.remove === true) return '';
      value = value.status;
    }
    const status = String(value ?? '').trim();
    return status === 'none' ? '' : status;
  };

  Object.entries(patch).forEach(([key, rawValue]) => {
    const mid = String(key || '').trim();
    if (!mid) return;

    if (mid === '__testsClearedAt') {
      const marker = String(rawValue || '').trim();
      if (marker) next.__testsClearedAt = marker;
      else delete next.__testsClearedAt;
      return;
    }

    if (mid === 'tests') {
      if (!rawValue || typeof rawValue !== 'object') return;
      sawTestsPatch = true;
      const tests = next.tests && typeof next.tests === 'object' ? { ...next.tests } : {};
      Object.entries(rawValue).forEach(([testKey, testStatus]) => {
        const normalizedKey = String(testKey || '').trim();
        if (!normalizedKey) return;
        patchedTestKeys.add(normalizedKey);
        const beforeStatus = testStatusName(tests[normalizedKey]);
        if (testStatus == null || testStatus === false) {
          delete tests[normalizedKey];
        } else if (typeof testStatus === 'string') {
          const normalizedStatus = testStatus.trim();
          if (!normalizedStatus || normalizedStatus === 'none') delete tests[normalizedKey];
          else tests[normalizedKey] = normalizedStatus;
        } else if (testStatus && typeof testStatus === 'object') {
          if (testStatus.remove === true) delete tests[normalizedKey];
          else tests[normalizedKey] = clone(testStatus);
        } else {
          tests[normalizedKey] = String(testStatus).trim();
        }
        if (beforeStatus !== testStatusName(tests[normalizedKey])) changedTestKeys.add(normalizedKey);
      });
      if (Object.keys(tests).length) {
        next.tests = tests;
        delete next.__testsClearedAt;
      } else {
        delete next.tests;
      }
      return;
    }

    if (mid.startsWith('__')) return;

    const status = String(rawValue ?? '').trim();
    if (status === '') {
      delete next[mid];
      delete manualMeta[mid];
    } else {
      next[mid] = status;
      manualMeta[mid] = true;
    }
  });

  if (Object.keys(manualMeta).length) next.__manualProgressMids = manualMeta;
  else delete next.__manualProgressMids;
  if (sawTestsPatch) {
    const tests = next.tests && typeof next.tests === 'object' ? next.tests : {};
    const rawOrder = next[TEST_ASSIGN_CHANGE_ORDER_KEY];
    const orderByKey = {};
    if (rawOrder && typeof rawOrder === 'object' && !Array.isArray(rawOrder)) {
      Object.entries(rawOrder).forEach(([key, value]) => {
        const order = Number(value);
        if (String(key || '').trim() && Number.isInteger(order) && order > 0 && testStatusName(tests[key])) {
          orderByKey[key] = order;
        }
      });
    }
    const orderedKeys = Array.from(touchedTestKeys.size ? touchedTestKeys : changedTestKeys)
      .filter(key => patchedTestKeys.has(key) && testStatusName(tests[key]));
    if (orderedKeys.length) {
      const nextOrder = Math.max(0, ...Object.values(orderByKey)) + 1;
      orderedKeys.forEach(key => { orderByKey[key] = nextOrder; });
    }
    if (Object.keys(orderByKey).length) next[TEST_ASSIGN_CHANGE_ORDER_KEY] = orderByKey;
    else delete next[TEST_ASSIGN_CHANGE_ORDER_KEY];
  }
  delete next[TEST_ASSIGN_TOUCHED_KEYS_KEY];
  bySid[sid] = next;
  return { progress: clone(next) };
}

function mergeUpdatesPatch(store, body) {
  const date = String(body?.date || '').trim();
  const sid = String(body?.sid || '').trim();
  if (!date || !sid) return { error: 'missing date or sid' };
  const bySid = ensureDateMap(store, 'updates', date);
  if (body.remove === true) {
    delete bySid[sid];
    removeEmptyDateMap(store, 'updates', date);
    return { updates: clone(store.updates || {}) };
  }
  const previous = bySid[sid] && typeof bySid[sid] === 'object' ? bySid[sid] : {};
  const entry = body.entry && typeof body.entry === 'object'
    ? body.entry
    : (body.update && typeof body.update === 'object' ? body.update : {});
  bySid[sid] = { ...previous, ...clone(entry) };
  return { entry: clone(bySid[sid]), updates: clone(store.updates || {}) };
}

function setStudentField(store, body) {
  const sid = String(body?.id || body?.sid || '').trim();
  const field = String(body?.field || '').trim();
  if (!sid || !field) return { error: 'missing id or field' };
  const student = (store.students || []).find(row => String(row?.id) === sid);
  if (!student) return { error: 'student not found', status: 404 };
  student[field] = body?.value;
  return { student: clone(student) };
}

function nextDemoStudentId(store) {
  const used = new Set((store.students || []).map(row => String(row?.id || '')));
  for (let index = 1; index < 10000; index += 1) {
    const id = `demo-s${String(index).padStart(3, '0')}`;
    if (!used.has(id)) return id;
  }
  return `demo-s-${Date.now()}`;
}

function addStudent(store, body) {
  const payload = body && typeof body === 'object' ? clone(body) : {};
  const name = String(payload.name || '').trim() || '데모학생';
  const id = String(payload.id || '').trim().startsWith('demo-')
    ? String(payload.id).trim()
    : nextDemoStudentId(store);
  const student = {
    ...payload,
    id,
    name,
    school: String(payload.school || '데모고').trim(),
    grade: String(payload.grade || '고1').trim(),
    curriculum: String(payload.curriculum || '공통수학1').trim(),
    subCurriculum: String(payload.subCurriculum || payload.sub || '기본').trim(),
    level: String(payload.level || '중').trim(),
    docUrl: String(payload.docUrl || `/demo/rh3123/demo-student-card/${id}`).trim(),
    memo: String(payload.memo || '데모용 안전 학생 데이터').trim(),
  };
  store.students = Array.isArray(store.students) ? store.students : [];
  store.students.push(student);
  return { id, student: clone(student) };
}

function removeSidFromDateSidMap(store, key, sid) {
  const source = store[key];
  if (!source || typeof source !== 'object') return;
  Object.keys(source).forEach(date => {
    if (source[date] && typeof source[date] === 'object' && !Array.isArray(source[date])) {
      delete source[date][sid];
      if (!Object.keys(source[date]).length) delete source[date];
    }
  });
}

function removeSidFromDateArrayMap(store, key, sid) {
  const source = store[key];
  if (!source || typeof source !== 'object') return;
  Object.keys(source).forEach(date => {
    if (Array.isArray(source[date])) {
      source[date] = source[date].filter(item => String(item) !== sid);
      if (!source[date].length) delete source[date];
    }
  });
}

function deleteStudent(store, sid) {
  const key = String(sid || '').trim();
  if (!key) return { error: 'missing sid' };
  store.students = Array.isArray(store.students) ? store.students : [];
  const before = store.students.length;
  store.students = store.students.filter(row => String(row?.id) !== key);
  ['updates', 'logs', 'progress', 'attendance', 'contact', 'arriveTime', 'weekendSlots'].forEach(mapKey => {
    removeSidFromDateSidMap(store, mapKey, key);
  });
  removeSidFromDateArrayMap(store, 'extraAttend', key);
  if (store.matAssign && typeof store.matAssign === 'object') delete store.matAssign[key];
  if (store.absent?.by_student) delete store.absent.by_student[key];
  if (store.absent?.by_date) removeSidFromDateArrayMap(store.absent, 'by_date', key);
  return { deleted: before !== store.students.length, id: key };
}

function sanitizeVideoRow(row, index = 0) {
  const source = row && typeof row === 'object' ? clone(row) : {};
  const rawId = String(source.id || source.mid || `demo-v${String(index + 1).padStart(3, '0')}`).trim();
  const safeId = rawId.startsWith('demo-') ? rawId : `demo-v-${rawId.replace(/[^A-Za-z0-9_-]/g, '') || index + 1}`;
  const rawMid = String(source.mid || safeId).trim();
  const safeMid = rawMid.startsWith('demo-') ? rawMid : `demo-mid-${rawMid.replace(/[^A-Za-z0-9_-]/g, '') || index + 1}`;
  const rawUrl = String(source.url || '').trim();
  const safeUrl = rawUrl.startsWith('/demo-assets/') || rawUrl.startsWith('https://demo.invalid/')
    ? rawUrl
    : `/demo-assets/videos/${safeMid}.mp4`;
  return {
    ...source,
    id: safeId,
    mid: safeMid,
    title: String(source.title || `데모 영상 ${index + 1}`).trim(),
    curriculum: String(source.curriculum || '공통수학1').trim(),
    subCurriculum: String(source.subCurriculum || '기본').trim(),
    chapter: Number(source.chapter || index + 1) || 1,
    url: safeUrl,
  };
}

function setVideos(store, body) {
  const rows = Array.isArray(body) ? body : [];
  store.videos = rows.map((row, index) => sanitizeVideoRow(row, index));
  return clone(store.videos);
}

function setTestsConfig(store, body) {
  store.testsConfig = body && typeof body === 'object' ? clone(body) : { categories: {} };
  return clone(store.testsConfig);
}

function setSchoolCalendar(store, body) {
  store.schoolCalendar = body && typeof body === 'object' ? clone(body) : {};
  return clone(store.schoolCalendar);
}

function flatDemoTests(store) {
  const config = store.testsConfig && typeof store.testsConfig === 'object'
    ? store.testsConfig
    : { categories: {} };
  const rows = [];
  Object.entries(config.categories || {}).forEach(([categoryKey, category]) => {
    const label = category?.label || categoryKey;
    (Array.isArray(category?.tests) ? category.tests : []).forEach(test => {
      rows.push({
        ...clone(test),
        categoryKey,
        categoryLabel: label,
      });
    });
  });
  return rows;
}

function statSeedForTest(test, index) {
  const count = 3 + (index % 5);
  const avg = 72 + ((index * 7) % 19);
  return {
    count,
    avg_pct: avg,
    stddev_pct: 6 + (index % 4),
    median_pct: Math.min(98, avg + 1),
    max_pct: Math.min(100, avg + 10),
    min_pct: Math.max(45, avg - 16),
  };
}

function testsSignature(test) {
  return [
    test?.categoryKey || '',
    test?.curriculum || '',
    String(test?.name || '').trim().replace(/\s+/g, ' '),
    test?.term || test?.examTerm || '',
    String(test?.round || '').trim(),
  ].join('\u241f');
}

function testsStatsResponse(root, store) {
  const rows = flatDemoTests(store);
  const byTestId = {};
  const byTestSignature = {};
  const byTest = {};
  const summaryBuckets = {};
  rows.forEach((test, index) => {
    const stat = statSeedForTest(test, index);
    if (test.id) byTestId[test.id] = stat;
    byTestSignature[testsSignature(test)] = stat;
    if (test.name) byTest[String(test.name).trim()] = stat;
    const bucket = summaryBuckets[test.categoryKey] || { count: 0, total: 0 };
    bucket.count += stat.count;
    bucket.total += stat.avg_pct * stat.count;
    summaryBuckets[test.categoryKey] = bucket;
  });
  const summary = {};
  Object.entries(summaryBuckets).forEach(([categoryKey, bucket]) => {
    summary[categoryKey] = {
      count: bucket.count,
      avg_pct: bucket.count ? bucket.total / bucket.count : 0,
    };
  });
  return responseJson(root, {
    ok: true,
    demo: true,
    summary,
    by_test_id: byTestId,
    by_test_signature: byTestSignature,
    by_test: byTest,
  });
}

function testsRecordsResponse(root, store, url) {
  const testId = String(url.searchParams.get('test_id') || '').trim();
  const tests = flatDemoTests(store);
  const index = Math.max(0, tests.findIndex(test => String(test.id || '') === testId));
  const stat = statSeedForTest(tests[index] || {}, index);
  const students = Array.isArray(store.students) ? store.students.slice(0, Math.min(6, store.students.length)) : [];
  const records = students.map((student, rowIndex) => {
    const pct = Math.max(45, Math.min(100, stat.avg_pct + (rowIndex - 2) * 4));
    const total = Number(tests[index]?.problems || 20) || 20;
    const correct = Math.round((pct / 100) * total);
    return {
      sid: student.id,
      studentName: student.name,
      level: student.level || '-',
      pct,
      correct,
      total,
      createdAt: `${store.demoDate || store.dates?.current || '2026-06-17'}T18:0${rowIndex}:00+09:00`,
    };
  });
  return responseJson(root, { ok: true, demo: true, records });
}

function mergeWatchProgress(store, body, explicitStatus = '') {
  const date = String(body?.date || store.demoDate || '').trim();
  const sid = String(body?.sid || '').trim();
  const mid = String(body?.mid || body?.videoId || body?.id || '').trim();
  if (!date || !sid || !mid) return { error: 'missing date, sid, or mid' };
  const status = explicitStatus
    || String(body?.status || '').trim()
    || (body?.completed === true ? 'done' : 'interrupted');
  const day = ensureDateMap(store, 'progress', date);
  const entry = day[sid] && typeof day[sid] === 'object' ? day[sid] : {};
  entry[mid] = status;
  day[sid] = entry;
  return { date, sid, mid, status, progress: clone(entry) };
}

function upsertBooleanDayValue(store, key, body) {
  const date = String(body?.date || store.demoDate || '').trim();
  const sid = String(body?.sid || '').trim();
  if (!date || !sid) return { error: 'missing date or sid' };
  const day = ensureDateMap(store, key, date);
  if (body.value === false || body.value === 0 || body.value === '0' || body.value === '') delete day[sid];
  else day[sid] = 1;
  return { date, sid, value: !!day[sid], map: clone(day) };
}

function upsertArriveTime(store, body) {
  const date = String(body?.date || store.demoDate || '').trim();
  const sid = String(body?.sid || '').trim();
  if (!date || !sid) return { error: 'missing date or sid' };
  const day = ensureDateMap(store, 'arriveTime', date);
  const value = String(body?.value ?? body?.time ?? '').trim();
  if (value) day[sid] = value;
  else delete day[sid];
  return { date, sid, value: day[sid] || '', map: clone(day) };
}

function setWholeMap(store, key, body) {
  store[key] = body && typeof body === 'object' ? clone(body) : {};
  return clone(store[key]);
}

function mergeWholeMap(store, key, body) {
  store[key] = store[key] && typeof store[key] === 'object' ? store[key] : {};
  if (body && typeof body === 'object') {
    Object.entries(body).forEach(([date, value]) => {
      store[key][date] = clone(value);
    });
  }
  return clone(store[key]);
}

function mergeWeekendSlotsPatch(store, body) {
  store.weekendSlots = store.weekendSlots && typeof store.weekendSlots === 'object'
    ? store.weekendSlots
    : {};
  Object.entries(body && typeof body === 'object' ? body : {}).forEach(([date, mapping]) => {
    if (!mapping || typeof mapping !== 'object' || Array.isArray(mapping)) return;
    const day = { ...(store.weekendSlots[date] || {}) };
    Object.entries(mapping).forEach(([sid, value]) => {
      if (value == null || value === false || (Array.isArray(value) && value.length === 0)) delete day[String(sid)];
      else day[String(sid)] = clone(value);
    });
    if (Object.keys(day).length) store.weekendSlots[date] = day;
    else delete store.weekendSlots[date];
  });
  return clone(store.weekendSlots);
}

function mergeAbsent(store, body) {
  store.absent = store.absent && typeof store.absent === 'object'
    ? store.absent
    : { by_date: {}, by_student: {}, by_slot: {} };

  if (body?.by_date || body?.by_student || body?.by_slot) {
    store.absent.by_date = body.by_date ? clone(body.by_date) : (store.absent.by_date || {});
    store.absent.by_student = body.by_student ? clone(body.by_student) : (store.absent.by_student || {});
    store.absent.by_slot = body.by_slot ? clone(body.by_slot) : (store.absent.by_slot || {});
    return clone(store.absent);
  }

  const date = String(body?.date || '').trim();
  const sid = String(body?.sid || '').trim();
  const slots = Array.isArray(body?.slots) ? body.slots : (body?.slot != null ? [body.slot] : []);
  const value = body?.value !== false && body?.absent !== false && body?.remove !== true;
  if (!date || !sid) return { error: 'missing date or sid' };

  store.absent.by_date = store.absent.by_date && typeof store.absent.by_date === 'object' ? store.absent.by_date : {};
  store.absent.by_student = store.absent.by_student && typeof store.absent.by_student === 'object' ? store.absent.by_student : {};
  store.absent.by_slot = store.absent.by_slot && typeof store.absent.by_slot === 'object' ? store.absent.by_slot : {};

  const day = new Set((store.absent.by_date[date] || []).map(String));
  if (value) day.add(sid);
  else day.delete(sid);
  if (day.size) store.absent.by_date[date] = Array.from(day);
  else delete store.absent.by_date[date];

  if (value) store.absent.by_student[sid] = Array.from(new Set([...(Array.isArray(store.absent.by_student[sid]) ? store.absent.by_student[sid] : []), date]));
  else if (Array.isArray(store.absent.by_student[sid])) {
    store.absent.by_student[sid] = store.absent.by_student[sid].filter(row => String(row) !== date);
    if (!store.absent.by_student[sid].length) delete store.absent.by_student[sid];
  } else {
    delete store.absent.by_student[sid];
  }

  store.absent.by_slot[date] = store.absent.by_slot[date] && typeof store.absent.by_slot[date] === 'object' ? store.absent.by_slot[date] : {};
  if (value && slots.length) {
    store.absent.by_slot[date][sid] = Array.from(new Set(slots.map(Number).filter(n => n === 1 || n === 2)));
  } else {
    delete store.absent.by_slot[date][sid];
  }
  if (!Object.keys(store.absent.by_slot[date]).length) delete store.absent.by_slot[date];

  return clone(store.absent);
}

function recoverAbsent(store, body) {
  const date = canonicalDate(body?.date);
  const sids = Array.from(new Set((Array.isArray(body?.sids) ? body.sids : [])
    .map(value => String(value || '').trim())
    .filter(Boolean)));
  if (!date || !sids.length) {
    return { error: 'missing date or sids' };
  }

  const absent = clone(store.absent && typeof store.absent === 'object'
    ? store.absent
    : { by_date: {}, by_student: {}, by_slot: {} });
  absent.by_date = absent.by_date && typeof absent.by_date === 'object' ? absent.by_date : {};
  absent.by_student = absent.by_student && typeof absent.by_student === 'object' ? absent.by_student : {};
  absent.by_slot = absent.by_slot && typeof absent.by_slot === 'object' ? absent.by_slot : {};
  const selected = new Set(sids);
  absent.by_date[date] = (absent.by_date?.[date] || [])
    .filter(sid => !selected.has(String(sid)));
  sids.forEach(sid => {
    if (String(absent.by_student?.[sid] || '') === date) delete absent.by_student[sid];
    if (absent.by_slot?.[date]) delete absent.by_slot[date][sid];
  });
  if (absent.by_slot?.[date] && !Object.keys(absent.by_slot[date]).length) delete absent.by_slot[date];
  store.absent = absent;
  return clone(absent);
}

function dayMapResponse(root, store, key, url) {
  const date = String(url.searchParams.get('date') || '').trim();
  const source = store[key] && typeof store[key] === 'object' ? store[key] : {};
  if (date) return responseJson(root, clone(source[date] || {}));
  return responseJson(root, clone(source));
}

function extraAttendResponse(root, store, url) {
  const date = String(url.searchParams.get('date') || '').trim();
  if (date) return responseJson(root, clone(store.extraAttend?.[date] || []));
  return responseJson(root, clone(store.extraAttend || {}));
}

function attendResponse(root, store, url) {
  const date = String(url.searchParams.get('date') || '').trim();
  if (date) {
    return responseJson(root, {
      attendance: clone(store.attendance?.[date] || {}),
      contact: clone(store.contact?.[date] || {}),
      arriveTime: clone(store.arriveTime?.[date] || {}),
    });
  }
  return responseJson(root, {
    attendance: clone(store.attendance || {}),
    contact: clone(store.contact || {}),
    arriveTime: clone(store.arriveTime || {}),
  });
}

function watchLatestResponse(root, store, url) {
  const sid = sidParam(url);
  const latest = {};
  const progress = store.progress && typeof store.progress === 'object' ? store.progress : {};
  Object.keys(progress).sort().forEach(date => {
    const entry = progress[date]?.[sid];
    if (!entry || typeof entry !== 'object') return;
    Object.entries(entry).forEach(([mid, status]) => {
      if (mid.startsWith('__') || mid === 'tests') return;
      latest[mid] = {
        mid,
        sid,
        status,
        ratio: status === 'done' ? 1 : status === 'interrupted' ? 0.45 : 0,
        updatedAt: `${date}T18:00:00+09:00`,
      };
    });
  });
  return responseJson(root, { ok: true, latest, byMid: latest });
}

function unarchivedSummaryResponse(root, store, url) {
  const excludeDate = String(
    url.searchParams.get('exclude_date') || url.searchParams.get('excludeDate') || '',
  ).trim();
  const today = String(store.demoDate || store.dates?.current || '').trim();
  const latestBySid = new Map();
  const byDate = new Map();
  const staleStudents = new Set();
  let total = 0;

  Object.keys(store.logs || {}).sort().forEach((date) => {
    const dateKey = canonicalDate(date);
    if (!dateKey) return;
    Object.entries(store.logs?.[date] || {}).forEach(([sid, entry]) => {
      const sidKey = String(sid || '').trim();
      if (!sidKey) return;
      if (!entry || typeof entry !== 'object') return;
      const done = entry.done === true || entry.done === 1 || entry.done === '1' || entry.done === 'true';
      const archived = entry.archived === true || entry.archived === 1 || entry.archived === '1' || entry.archived === 'true';
      if (!done || archived) return;

      latestBySid.set(sidKey, { date: dateKey, sid: sidKey, entry: projectedDoneEntry(entry) });
      if ((excludeDate && dateKey === excludeDate) || (today && dateKey >= today)) return;
      byDate.set(dateKey, (byDate.get(dateKey) || 0) + 1);
      staleStudents.add(sidKey);
      total += 1;
    });
  });

  const rows = Array.from(latestBySid.values())
    .sort((a, b) => String(b.date).localeCompare(String(a.date)) || String(a.sid).localeCompare(String(b.sid)));
  return responseJson(root, {
    ok: true,
    excludeDate,
    total,
    students: staleStudents.size,
    rowsAvailable: true,
    byDate: Array.from(byDate.entries())
      .sort(([a], [b]) => String(b).localeCompare(String(a)))
      .map(([date, count]) => ({ date, count })),
    rows,
  });
}

function normalizeAnnouncementPayload(payload, previous = {}) {
  const id = String(previous.id || payload.id || `demo-ann-${Date.now()}`).trim();
  const createdAt = previous.createdAt || nowIso();
  const next = {
    ...clone(previous),
    ...clone(payload),
    id,
    createdAt,
    updatedAt: nowIso(),
  };
  if (!Array.isArray(next.targetSids)) next.targetSids = [];
  if (!Array.isArray(next.targetSnapshot)) next.targetSnapshot = [];
  if (!Array.isArray(next.images)) next.images = next.image ? [next.image] : [];
  return next;
}

function announcementStatusRows(store) {
  return clone(store.announcements || []).map(row => ({
    ...row,
    replyCount: Array.isArray(row.replies) ? row.replies.length : 0,
    responseCount: row.surveyResults?.responseCount || 0,
  }));
}

function findAnnouncement(store, id) {
  const key = String(id || '').trim();
  return (store.announcements || []).find(row => String(row?.id) === key);
}

function announcementIdFromPath(path) {
  const prefix = '/api/announcements/';
  if (!path.startsWith(prefix)) return '';
  return decodeURIComponent(path.slice(prefix.length));
}

async function imageUploadResponse(root, ctx) {
  await readFormDataBody(ctx);
  return responseJson(root, {
    ok: true,
    demo: true,
    image: {
      id: `demo-upload-${Date.now()}`,
      url: DEMO_UPLOAD_URL,
      name: 'demo-upload.png',
      alt: 'Demo upload placeholder',
    },
  });
}

function testsFlatConfig(store) {
  return clone(store.testsConfig || { categories: {} });
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

function findStudentAccountGroup(store, aid) {
  return (Array.isArray(store.studentAccounts) ? store.studentAccounts : [])
    .find(group => String(group?.account?.aid || group?.identity?.name || '') === String(aid || ''));
}

function sameExactSids(expected, received) {
  if (!Array.isArray(expected) || !Array.isArray(received)) return false;
  const normalize = rows => [...new Set(rows.map(value => String(value).trim()).filter(Boolean))].sort();
  const left = normalize(expected);
  const right = normalize(received);
  return left.length === right.length && left.every((sid, index) => sid === right[index]);
}

function studentAccountAction(path) {
  const match = path.match(/^\/api\/student-accounts\/([^/]+)\/(reset|disable|enable|revoke-sessions|activation-code)$/);
  if (!match) return null;
  try {
    return { aid: decodeURIComponent(match[1]), action: match[2] };
  } catch {
    return null;
  }
}

async function handleGet(root, ctx, store) {
  const { path, url } = ctx;
  const homeworkResult = applyDemoHomeworkRequest({
    method: 'GET',
    path,
    params: url.searchParams,
    store,
    now: new Date(DEFAULT_DEMO_NOW),
  });
  if (homeworkResult) {
    if (homeworkResult.changed) saveDemoStore(store);
    return responseJson(root, clone(homeworkResult.payload), homeworkResult.status);
  }
  const studentLogsResult = applyStudentLogsRequest({
    method: 'GET',
    path,
    store,
    createdAt: nowIso,
    today: store.demoDate,
  });
  if (studentLogsResult) {
    return responseJson(root, clone(studentLogsResult.payload), studentLogsResult.status);
  }
  const assistantStudentNotesResult = applyAssistantStudentNotesRequest({
    method: 'GET',
    path,
    params: url.searchParams,
    store,
    createdAt: nowIso,
  });
  if (assistantStudentNotesResult) {
    return responseJson(root, clone(assistantStudentNotesResult.payload), assistantStudentNotesResult.status);
  }
  if (path === '/api/student-accounts') return responseJson(root, { ok: true, groups: clone(store.studentAccounts || []) });
  if (path === '/api/admin/student-focus/summary') {
    const date = String(url.searchParams.get('date') || '').trim();
    return responseJson(root, clone(store.focusSummaries?.[date] || {
      ok: true, date, serverNow: nowIso(), classes: [],
    }));
  }
  if (path === '/api/students') return responseJson(root, clone(store.students || []));
  if (path === '/api/videos') return responseJson(root, clone(store.videos || []));
  if (path === '/api/materials') return responseJson(root, clone(store.materials || {}));
  if (path === '/api/mat-assign') return responseJson(root, clone(store.matAssign || {}));
  if (path === '/api/updates') return responseJson(root, clone(store.updates || {}));
  if (path === '/api/logs') return responseJson(root, filterDateSidMap(store.logs, url));
  if (path === '/api/homework-books') return responseJson(root, homeworkBooksBySid(store.logs));
  if (path === '/api/logs/entry') return responseJson(root, { ok: true, entry: getLogEntry(store, url) });
  if (path === '/api/progress') return responseJson(root, filterDateSidMap(store.progress, url));
  if (path === '/api/extra-attend') return extraAttendResponse(root, store, url);
  if (path === '/api/absent') return responseJson(root, clone(store.absent || { by_date: {}, by_student: {}, by_slot: {} }));
  if (path === '/api/attendance') return dayMapResponse(root, store, 'attendance', url);
  if (path === '/api/contact') return dayMapResponse(root, store, 'contact', url);
  if (path === '/api/arrive-time') return dayMapResponse(root, store, 'arriveTime', url);
  if (path === '/api/attend') return attendResponse(root, store, url);
  if (path === '/api/weekend-slots') return responseJson(root, clone(store.weekendSlots || {}));
  if (path === '/api/today_order') return responseJson(root, clone(store.todayOrder || {}));
  if (path === '/api/makeup-sheet-sync/config') {
    return responseJson(root, {
      ok: true,
      sheetUrl: String(store.makeupSheetSyncConfig?.sheetUrl || ''),
    });
  }
  if (path === '/api/makeup-carryover') {
    const payload = clone(store.makeupCarryover || {});
    return responseJson(root, payload, 200, {
      'X-Makeup-Carryover-Revision': demoRevision(payload),
    });
  }
  if (path === '/api/school-calendar') {
    const payload = clone(store.schoolCalendar || {});
    const revision = schoolCalendarDemoRevision(payload);
    return responseJson(root, payload, 200, {
      'X-School-Calendar-Revision': revision,
      ETag: `"${revision}"`,
    });
  }
  if (path === '/api/tests-config') return responseJson(root, testsFlatConfig(store));
  if (path === '/api/tests') return responseJson(root, clone(store.tests || {}));
  if (path === '/api/tests-stats') return testsStatsResponse(root, store, url);
  if (path === '/api/tests-records') return testsRecordsResponse(root, store, url);
  const operationNotesResult = applyOperationNotesRequest({
    method: 'GET',
    path,
    store,
    createdAt: nowIso,
  });
  if (operationNotesResult) {
    return responseJson(root, clone(operationNotesResult.payload), operationNotesResult.status);
  }
  if (path === '/api/announcements' || path === '/api/announce-status') return responseJson(root, announcementStatusRows(store));
  if (path.startsWith('/api/announcements/')) {
    const found = findAnnouncement(store, announcementIdFromPath(path));
    return found ? responseJson(root, clone(found)) : notFound(root, 'announcement not found');
  }
  if (path === '/api/watch/latest') return watchLatestResponse(root, store, url);
  if (path === '/api/logs/unarchived-summary') return unarchivedSummaryResponse(root, store, url);
  return null;
}

async function handleWrite(root, ctx, store) {
  const { path, method } = ctx;
  let body = {};
  if (path !== '/api/announcements/image') {
    try {
      body = await readJsonBody(ctx);
    } catch {
      return badRequest(root, 'invalid json body');
    }
  }

  const homeworkResult = applyDemoHomeworkRequest({
    method,
    path,
    body,
    store,
    now: new Date(DEFAULT_DEMO_NOW),
  });
  if (homeworkResult) {
    if (homeworkResult.changed) saveDemoStore(store);
    return responseJson(root, clone(homeworkResult.payload), homeworkResult.status);
  }

  const assistantStudentNotesResult = applyAssistantStudentNotesRequest({
    method,
    path,
    body,
    store,
    createdAt: nowIso,
  });
  if (assistantStudentNotesResult) {
    if (assistantStudentNotesResult.changed) saveDemoStore(store);
    return responseJson(root, clone(assistantStudentNotesResult.payload), assistantStudentNotesResult.status);
  }

  const studentLogsResult = applyStudentLogsRequest({
    method,
    path,
    body,
    store,
    createdAt: nowIso,
    today: store.demoDate,
  });
  if (studentLogsResult) {
    if (studentLogsResult.changed) saveDemoStore(store);
    return responseJson(root, clone(studentLogsResult.payload), studentLogsResult.status);
  }

  const accountRequest = method === 'POST' ? studentAccountAction(path) : null;
  if (accountRequest) {
    const group = findStudentAccountGroup(store, accountRequest.aid);
    if (!group) return notFound(root, 'student account not found');
    const account = group.account || null;
    if (accountRequest.action === 'activation-code') {
      if (account?.status === 'disabled') return responseJson(root, { ok: false, error: 'student account disabled' }, 409);
      if (!group.activationCodeRequired) return responseJson(root, { ok: false, error: 'activation code not required' }, 409);
      if (!sameExactSids(group.identity?.sids, body?.sids)) return badRequest(root, 'exact SID group required');
      return ok(root, { ok: true, activationCode: '482731', expiresAt: Math.floor(Date.now() / 1000) + (24 * 60 * 60) });
    }
    if (!account) return notFound(root, 'student account not found');
    if (accountRequest.action === 'reset') {
      account.mustChangeCredentials = true;
      account.activeSessionCount = 0;
    } else if (accountRequest.action === 'disable') {
      account.status = 'disabled';
      account.activeSessionCount = 0;
      account.activePushSubscriptionCount = 0;
    } else if (accountRequest.action === 'enable') {
      account.status = 'active';
    } else if (accountRequest.action === 'revoke-sessions') {
      account.activeSessionCount = 0;
    }
    saveDemoStore(store);
    return ok(root, { ok: true, group: clone(group) });
  }

  if (PATCH_METHODS.has(method) && path === '/api/update') {
    const result = setStudentField(store, body);
    if (result.error) return responseJson(root, { ok: false, error: result.error }, result.status || 400);
    saveDemoStore(store);
    return ok(root, { ok: true, student: result.student });
  }

  if (method === 'POST' && path === '/api/add-student') {
    const result = addStudent(store, body);
    saveDemoStore(store);
    return ok(root, { ok: true, id: result.id, student: result.student });
  }

  if (method === 'DELETE' && path.startsWith('/api/students/')) {
    const sid = decodeURIComponent(path.slice('/api/students/'.length));
    const result = deleteStudent(store, sid);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, ...result });
  }

  if (method === 'POST' && path === '/api/videos') {
    const videos = setVideos(store, body);
    saveDemoStore(store);
    return ok(root, videos);
  }

  if (method === 'POST' && path === '/api/school-calendar') {
    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      return badRequest(root, 'invalid school calendar');
    }
    const current = clone(store.schoolCalendar || {});
    const currentRevision = schoolCalendarDemoRevision(current);
    const expectedRevision = requestHeader(ctx.headers, 'If-Match')
      .trim()
      .replace(/^W\//, '')
      .replace(/^"|"$/g, '')
      .toLowerCase();
    if (!expectedRevision) {
      return responseJson(root, { ok: false, code: 'school_calendar_revision_required' }, 428, {
        'X-School-Calendar-Revision': currentRevision,
      });
    }
    if (expectedRevision !== currentRevision) {
      return responseJson(root, { ok: false, code: 'school_calendar_conflict' }, 409, {
        'X-School-Calendar-Revision': currentRevision,
      });
    }
    const calendar = setSchoolCalendar(store, body);
    saveDemoStore(store);
    const revision = schoolCalendarDemoRevision(calendar);
    return responseJson(root, calendar, 200, {
      'X-School-Calendar-Revision': revision,
      ETag: `"${revision}"`,
    });
  }

  if (method === 'POST' && path === '/api/tests-config') {
    const config = setTestsConfig(store, body);
    saveDemoStore(store);
    return ok(root, config);
  }

  if (method === 'PATCH' && path === '/api/tests-config/test') {
    const result = patchDemoTestConfig(store.testsConfig || { categories: {} }, body);
    if (!result.ok) return responseJson(root, { ok: false, error: result.error }, result.status);
    store.testsConfig = result.config;
    saveDemoStore(store);
    return ok(root, { ok: true, test: result.test });
  }

  if (method === 'POST' && path === '/api/watch') {
    const result = mergeWatchProgress(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, watch: result, progress: result.progress });
  }

  if (method === 'POST' && path === '/api/watch-status') {
    const result = mergeWatchProgress(store, body, String(body?.status || '').trim());
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, watch: result, progress: result.progress });
  }

  if (PATCH_METHODS.has(method) && path === '/api/updates/patch') {
    const result = mergeUpdatesPatch(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, ...result });
  }

  if (PATCH_METHODS.has(method) && path === '/api/logs/patch') {
    const result = mergeLogPatch(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, entry: result.entry });
  }

  if (method === 'POST' && path === '/api/logs/patch-batch') {
    const result = mergeLogPatchBatch(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, count: result.count });
  }

  if (PATCH_METHODS.has(method) && path === '/api/progress/patch') {
    const result = mergeProgressPatch(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, progress: result.progress });
  }

  if (PATCH_METHODS.has(method) && path === '/api/attendance/patch') {
    const result = upsertBooleanDayValue(store, 'attendance', body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, attendance: result.map, date: result.date, sid: result.sid, value: result.value });
  }

  if (PATCH_METHODS.has(method) && path === '/api/contact/patch') {
    const result = upsertBooleanDayValue(store, 'contact', body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, contact: result.map, date: result.date, sid: result.sid, value: result.value });
  }

  if (PATCH_METHODS.has(method) && path === '/api/arrive-time/patch') {
    const result = upsertArriveTime(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, arriveTime: result.map, date: result.date, sid: result.sid, value: result.value });
  }

  if (PATCH_METHODS.has(method) && path === '/api/arrive-time') {
    const result = body?.sid ? upsertArriveTime(store, body) : { map: mergeWholeMap(store, 'arriveTime', body) };
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, arriveTime: clone(store.arriveTime || {}) });
  }

  if (method === 'PATCH' && path === '/api/extra-attend') {
    const rawDates = body?.dates && typeof body.dates === 'object'
      ? body.dates
      : { [body?.date]: body?.sids };
    const dates = {};
    for (const [rawDate, rawSids] of Object.entries(rawDates)) {
      const date = canonicalDate(rawDate);
      if (!date || !Array.isArray(rawSids)) return badRequest(root, 'invalid date or sids');
      dates[date] = Array.from(new Set(rawSids.map(sid => String(sid || '').trim()).filter(Boolean)));
    }
    if (!Object.keys(dates).length) return badRequest(root, 'date patch is required');

    const latest = loadDemoStore();
    latest.extraAttend = latest.extraAttend && typeof latest.extraAttend === 'object' ? latest.extraAttend : {};
    Object.entries(dates).forEach(([date, sids]) => {
      if (sids.length) latest.extraAttend[date] = sids;
      else delete latest.extraAttend[date];
    });
    saveDemoStore(latest);
    return ok(root, { ok: true, dates: clone(dates), changedDates: Object.keys(dates) });
  }

  if (method === 'POST' && path === '/api/weekend-slots') {
    const next = mergeWeekendSlotsPatch(store, body);
    saveDemoStore(store);
    return ok(root, next);
  }

  if (method === 'POST' && path === '/api/makeup-sheet-sync/config') {
    const sheetUrl = String(body?.sheetUrl || '').trim();
    if (!sheetUrl.includes('docs.google.com/spreadsheets/d/')) {
      return badRequest(root, 'Google Sheets link required');
    }
    const latest = loadDemoStore();
    latest.makeupSheetSyncConfig = {
      ...(latest.makeupSheetSyncConfig && typeof latest.makeupSheetSyncConfig === 'object'
        ? latest.makeupSheetSyncConfig
        : {}),
      sheetUrl,
    };
    saveDemoStore(latest);
    return ok(root, { ok: true, sheetUrl });
  }

  if (method === 'POST' && path === '/api/makeup-sheet-sync') {
    return ok(root, {
      ok: true,
      mode: 'additive-only',
      opened: 0,
      added: 0,
      skippedExisting: 0,
      unmatchedStarredRows: 0,
      months: [],
      demo: true,
    });
  }

  if (method === 'PATCH' && path === '/api/today_order') {
    const date = canonicalDate(body?.date);
    if (!date || !Array.isArray(body?.order)) return badRequest(root, 'invalid date or order');
    const order = Array.from(new Set(body.order.map(value => String(value || '').trim()).filter(Boolean)));
    const latest = loadDemoStore();
    latest.todayOrder = latest.todayOrder && typeof latest.todayOrder === 'object' ? latest.todayOrder : {};
    latest.todayOrder[date] = order;
    saveDemoStore(latest);
    return ok(root, { ok: true, date, order: clone(order) });
  }

  if (method === 'DELETE' && path === '/api/today_order') {
    const date = canonicalDate(ctx.url.searchParams.get('date'));
    if (!date) return badRequest(root, 'invalid date');
    const latest = loadDemoStore();
    latest.todayOrder = latest.todayOrder && typeof latest.todayOrder === 'object' ? latest.todayOrder : {};
    const cleared = Object.prototype.hasOwnProperty.call(latest.todayOrder, date);
    delete latest.todayOrder[date];
    saveDemoStore(latest);
    return ok(root, { ok: true, date, cleared });
  }

  if (method === 'POST' && path === '/api/makeup-carryover') {
    const latest = loadDemoStore();
    const current = clone(latest.makeupCarryover || {});
    const currentRevision = demoRevision(current);
    const expectedRevision = requestHeader(ctx.headers, 'If-Match').trim().replace(/^"|"$/g, '');
    if (!expectedRevision) {
      return responseJson(root, { ok: false, error: 'makeup_revision_required' }, 428, {
        'X-Makeup-Carryover-Revision': currentRevision,
      });
    }
    if (expectedRevision !== currentRevision) {
      return responseJson(root, { ok: false, error: 'makeup_revision_conflict' }, 409, {
        'X-Makeup-Carryover-Revision': currentRevision,
      });
    }

    const next = setWholeMap(latest, 'makeupCarryover', body);
    saveDemoStore(latest);
    return responseJson(root, next, 200, {
      'X-Makeup-Carryover-Revision': demoRevision(next),
    });
  }

  if (method === 'POST' && path === '/api/absent') {
    const result = mergeAbsent(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, result);
  }

  if (method === 'POST' && path === '/api/absent/recover') {
    // The request body is read asynchronously. Reload immediately before the
    // narrow mutation so concurrent demo recoveries cannot publish a stale map.
    const latest = loadDemoStore();
    const result = recoverAbsent(latest, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(latest);
    return ok(root, result);
  }

  if (method === 'POST' && path === '/api/mat-assign') {
    store.matAssign = body && typeof body === 'object' ? clone(body) : {};
    saveDemoStore(store);
    return ok(root, store.matAssign);
  }


  if (method === 'POST' && path === '/api/announcements/image') return imageUploadResponse(root, ctx);

  const operationNotesResult = applyOperationNotesRequest({ method, path, body, store, createdAt: nowIso });
  if (operationNotesResult) {
    if (operationNotesResult.changed) saveDemoStore(store);
    return responseJson(root, clone(operationNotesResult.payload), operationNotesResult.status);
  }

  if (method === 'POST' && path === '/api/announcements') {
    const created = normalizeAnnouncementPayload(body);
    store.announcements = Array.isArray(store.announcements) ? store.announcements : [];
    store.announcements.unshift(created);
    saveDemoStore(store);
    return responseJson(root, clone(created), 201);
  }

  if (method === 'PUT' && path.startsWith('/api/announcements/')) {
    const id = announcementIdFromPath(path);
    store.announcements = Array.isArray(store.announcements) ? store.announcements : [];
    const index = store.announcements.findIndex(row => String(row?.id) === id);
    if (index < 0) return notFound(root, 'announcement not found');
    store.announcements[index] = normalizeAnnouncementPayload({ ...body, id }, store.announcements[index]);
    saveDemoStore(store);
    return responseJson(root, clone(store.announcements[index]));
  }

  if (method === 'DELETE' && path.startsWith('/api/announcements/')) {
    const id = announcementIdFromPath(path);
    store.announcements = Array.isArray(store.announcements) ? store.announcements : [];
    const before = store.announcements.length;
    store.announcements = store.announcements.filter(row => String(row?.id) !== id);
    saveDemoStore(store);
    return ok(root, { ok: true, deleted: before !== store.announcements.length, id });
  }

  return null;
}

function ensureDemoState(root, originalFetch) {
  const demo = root.__adminDemo || {};
  demo.enabled = true;
  demo.originalFetch = demo.originalFetch || originalFetch;
  demo.fetchLog = Array.isArray(demo.fetchLog) ? demo.fetchLog : [];
  demo.unsupportedApiCalls = Array.isArray(demo.unsupportedApiCalls) ? demo.unsupportedApiCalls : [];
  demo.forwardedApiCalls = Array.isArray(demo.forwardedApiCalls) ? demo.forwardedApiCalls : [];
  root.__adminDemo = demo;
  return demo;
}

function logIntercept(demo, ctx, status, extra = {}) {
  demo.fetchLog.push({
    at: nowIso(),
    method: ctx.method,
    url: `${ctx.url.pathname}${ctx.url.search}`,
    status,
    forwarded: false,
    ...extra,
  });
}

async function handleDemoFetch(root, demo, ctx) {
  const store = loadDemoStore(demo.now || DEFAULT_DEMO_NOW);
  let response = null;
  if (ctx.method === 'GET' || ctx.method === 'HEAD') {
    response = await handleGet(root, ctx, store);
    if (ctx.method === 'HEAD' && response) {
      response = responseText(root, '', response.status, { 'Content-Type': response.headers.get('Content-Type') || JSON_HEADERS['Content-Type'] });
    }
  } else if (WRITE_METHODS.has(ctx.method)) {
    response = await handleWrite(root, ctx, store);
  }

  if (!response) {
    demo.unsupportedApiCalls.push({
      at: nowIso(),
      method: ctx.method,
      url: `${ctx.url.pathname}${ctx.url.search}`,
    });
    response = unsupported(root, ctx.url, ctx.method);
  }

  logIntercept(demo, ctx, response.status, { unsupported: response.status === 404 && !response.ok });
  return response;
}

export function createDemoFetch(options = {}) {
  const root = options.window || options.root || globalThis.window || globalThis;
  const originalFetch = options.originalFetch || root.fetch?.bind(root) || globalThis.fetch?.bind(globalThis);
  const demo = ensureDemoState(root, originalFetch);
  demo.now = options.now || demo.now || DEFAULT_DEMO_NOW;

  const demoFetch = async (input, init = {}) => {
    const ctx = normalizeFetchRequest(input, init, root);
    if (!isApiLikePath(ctx.path)) {
      if (typeof originalFetch !== 'function') {
        throw new TypeError('original fetch is unavailable for non-demo assets');
      }
      return originalFetch(input, init);
    }
    return handleDemoFetch(root, demo, ctx);
  };
  demoFetch.__adminDemoFetch = true;
  demoFetch.__adminDemoOriginalFetch = originalFetch;
  return demoFetch;
}

export function installDemoFetch(options = {}) {
  const root = options.window || options.root || globalThis.window || globalThis;
  const currentFetch = root.fetch || globalThis.fetch;
  if (currentFetch?.__adminDemoFetch && options.force !== true) {
    const demo = ensureDemoState(root, currentFetch.__adminDemoOriginalFetch);
    demo.fetchInstalled = true;
    return { fetch: currentFetch, uninstall: () => {} };
  }

  const originalFetch = options.originalFetch || currentFetch?.bind(root);
  const demoFetch = createDemoFetch({ ...options, window: root, originalFetch });
  root.fetch = demoFetch;
  const demo = ensureDemoState(root, originalFetch);
  demo.fetchInstalled = true;
  demo.fetchInstalledAt = nowIso();
  return {
    fetch: demoFetch,
    uninstall() {
      if (root.fetch === demoFetch && typeof originalFetch === 'function') {
        root.fetch = originalFetch;
      }
    },
  };
}

export default installDemoFetch;
