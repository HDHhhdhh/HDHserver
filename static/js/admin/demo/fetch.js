import { cloneDemoValue, loadDemoStore, saveDemoStore } from './store.js';
import { applyDemoHomeworkRequest } from './homeworkContract.js';
import { applyOperationNotesRequest } from './operationNotesContract.js';

const DEFAULT_DEMO_NOW = '2026-06-17T00:00:00+09:00';
const JSON_HEADERS = Object.freeze({ 'Content-Type': 'application/json; charset=utf-8' });
const PATCH_METHODS = new Set(['POST', 'PATCH']);
const WRITE_METHODS = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);
const DEMO_UPLOAD_URL = '/demo-assets/images/uploaded-demo-image.png';

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
      const tests = next.tests && typeof next.tests === 'object' ? { ...next.tests } : {};
      Object.entries(rawValue).forEach(([testKey, testStatus]) => {
        const normalizedKey = String(testKey || '').trim();
        if (!normalizedKey) return;
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
  const date = dateParam(url, store);
  const rows = [];
  const bySid = store.logs?.[date] || {};
  Object.entries(bySid).forEach(([sid, entry]) => {
    if (!entry || typeof entry !== 'object') return;
    if (entry.done === true && entry.archived !== true) {
      const student = (store.students || []).find(row => String(row?.id) === String(sid)) || {};
      rows.push({
        date,
        sid,
        name: student.name || sid,
        leaveTime: entry.leaveTime || entry.doneTime || '',
        notes: entry.notes || '',
      });
    }
  });
  return responseJson(root, { ok: true, date, rows, count: rows.length });
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

function materialUploadResponse(root) {
  return responseJson(root, {
    ok: false,
    demo: true,
    error: 'demo upload disabled',
    materials: {},
  }, 200);
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
  if (path === '/api/extra-attend' || path === '/api/extra' || path === '/api/extra_attend' || path === '/api/extra-attend/all') return extraAttendResponse(root, store, url);
  if (path === '/api/absent') return responseJson(root, clone(store.absent || { by_date: {}, by_student: {}, by_slot: {} }));
  if (path === '/api/attendance') return dayMapResponse(root, store, 'attendance', url);
  if (path === '/api/contact') return dayMapResponse(root, store, 'contact', url);
  if (path === '/api/arrive-time' || path === '/arrive-time') return dayMapResponse(root, store, 'arriveTime', url);
  if (path === '/api/attend') return attendResponse(root, store, url);
  if (path === '/api/weekend-slots') return responseJson(root, clone(store.weekendSlots || {}));
  if (path === '/api/today_order') return responseJson(root, clone(store.todayOrder || {}));
  if (path === '/api/makeup-carryover') return responseJson(root, clone(store.makeupCarryover || {}));
  if (path === '/api/school-calendar') return responseJson(root, clone(store.schoolCalendar || {}));
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
  if (path !== '/api/announcements/image' && path !== '/api/material-upload') {
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

  if (method === 'POST' && path === '/api/delete-student') {
    const result = deleteStudent(store, body?.id || body?.sid);
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
    const calendar = setSchoolCalendar(store, body);
    saveDemoStore(store);
    return ok(root, calendar);
  }

  if (method === 'POST' && path === '/api/tests-config') {
    const config = setTestsConfig(store, body);
    saveDemoStore(store);
    return ok(root, config);
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

  if (PATCH_METHODS.has(method) && (path === '/api/arrive-time/patch' || path === '/arrive-time/patch')) {
    const result = upsertArriveTime(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, arriveTime: result.map, date: result.date, sid: result.sid, value: result.value });
  }

  if (PATCH_METHODS.has(method) && (path === '/api/arrive-time' || path === '/arrive-time')) {
    const result = body?.sid ? upsertArriveTime(store, body) : { map: mergeWholeMap(store, 'arriveTime', body) };
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, { ok: true, arriveTime: clone(store.arriveTime || {}) });
  }

  if (method === 'POST' && (path === '/api/extra-attend' || path === '/api/extra' || path === '/api/extra_attend' || path === '/api/extra-attend/all')) {
    if (body?.date && body?.sid) {
      const date = String(body.date);
      const sid = String(body.sid);
      const rows = ensureArrayDateMap(store, 'extraAttend', date);
      const set = new Set(rows.map(String));
      if (body.value === false || body.remove === true) set.delete(sid);
      else set.add(sid);
      store.extraAttend[date] = Array.from(set);
    } else {
      store.extraAttend = body && typeof body === 'object' ? clone(body) : {};
    }
    saveDemoStore(store);
    return ok(root, { ok: true, extraAttend: clone(store.extraAttend || {}) });
  }

  if (method === 'POST' && path === '/api/weekend-slots') {
    const next = mergeWholeMap(store, 'weekendSlots', body);
    saveDemoStore(store);
    return ok(root, next);
  }

  if (method === 'POST' && path === '/api/today_order') {
    const next = setWholeMap(store, 'todayOrder', body);
    saveDemoStore(store);
    return ok(root, next);
  }

  if (method === 'POST' && path === '/api/makeup-carryover') {
    const next = setWholeMap(store, 'makeupCarryover', body);
    saveDemoStore(store);
    return ok(root, next);
  }

  if (method === 'POST' && path === '/api/absent') {
    const result = mergeAbsent(store, body);
    if (result.error) return badRequest(root, result.error);
    saveDemoStore(store);
    return ok(root, result);
  }

  if (method === 'POST' && path === '/api/mat-assign') {
    store.matAssign = body && typeof body === 'object' ? clone(body) : {};
    saveDemoStore(store);
    return ok(root, store.matAssign);
  }

  if (method === 'POST' && path === '/api/materials') {
    store.materials = body && typeof body === 'object' ? clone(body) : {};
    saveDemoStore(store);
    return ok(root, store.materials);
  }

  if (method === 'POST' && path === '/api/material-upload') return materialUploadResponse(root);

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
