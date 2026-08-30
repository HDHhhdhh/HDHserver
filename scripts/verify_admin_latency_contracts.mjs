import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function read(relativePath) {
  return fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
}

function extractFunction(source, name) {
  const patterns = [
    `async function ${name}(`,
    `function ${name}(`,
  ];
  const start = patterns
    .map(pattern => source.indexOf(pattern))
    .filter(index => index >= 0)
    .sort((a, b) => a - b)[0];
  assert.notEqual(start, undefined, `${name} must exist`);

  const signatureEnd = source.indexOf(') {', start);
  const braceStart = signatureEnd >= 0 ? signatureEnd + 2 : -1;
  assert.ok(braceStart >= 0, `${name} must have a body`);
  let depth = 0;
  let quote = '';
  let escaped = false;
  for (let index = braceStart; index < source.length; index += 1) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === '"' || char === "'" || char === '`') {
      quote = char;
      continue;
    }
    if (char === '{') depth += 1;
    if (char === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  assert.fail(`${name} body is incomplete`);
}

function delayResult(starts, label, startedAt, value, delayMs = 80, reject = false) {
  starts[label] = performance.now() - startedAt;
  return new Promise((resolve, rejectPromise) => {
    setTimeout(() => {
      if (reject) rejectPromise(new Error(`${label} failed`));
      else resolve(value);
    }, delayMs);
  });
}

async function verifyCalendarParallelPreload() {
  const source = read('static/js/admin/features/calendar.js');
  const functionSource = extractFunction(source, 'preloadExtraWeekend');
  const buildRunner = new Function(
    'fetch',
    'fetchMakeupCarryoverSnapshot',
    'fetchAbsentSnapshot',
    'applyAbsentPayload',
    `${functionSource}
     let EXTRA = { old: 'extra' };
     let WEEKEND = { old: 'weekend' };
     let CARRYOVER = { old: 'carryover' };
     let preloadExtraWeekendPromise = null;
     const state = {};
     const window = {};
     const normalizeCarryoverPayload = value => value;
     return async () => {
       await Promise.all([
         preloadExtraWeekend(),
         preloadExtraWeekend(),
         preloadExtraWeekend(),
       ]);
       return { EXTRA, WEEKEND, CARRYOVER, state, window };
     };`,
  );

  const starts = {};
  const calls = {};
  const startedAt = performance.now();
  const run = buildRunner(
    url => {
      calls[url] = (calls[url] || 0) + 1;
      return delayResult(starts, url, startedAt, { [url]: true }).then(payload => ({ json: () => payload }));
    },
    () => {
      calls.carryover = (calls.carryover || 0) + 1;
      return delayResult(starts, 'carryover', startedAt, { payload: { carryover: true } });
    },
    () => {
      calls.absent = (calls.absent || 0) + 1;
      return delayResult(starts, 'absent', startedAt, { absent: true });
    },
    payload => { starts.appliedAbsence = payload; },
  );
  const result = await run();
  const elapsed = performance.now() - startedAt;

  const requestStarts = [
    starts['/api/extra-attend'],
    starts['/api/weekend-slots'],
    starts.carryover,
    starts.absent,
  ];
  assert.ok(requestStarts.every(Number.isFinite), 'all calendar inputs must start');
  assert.ok(Math.max(...requestStarts) < 30, `calendar inputs must start together: ${requestStarts}`);
  assert.ok(elapsed < 180, `calendar preload must take about one delayed request: ${elapsed.toFixed(1)}ms`);
  assert.deepEqual(calls, {
    '/api/extra-attend': 1,
    '/api/weekend-slots': 1,
    carryover: 1,
    absent: 1,
  }, 'concurrent calendar initializers must share one request bundle');
  assert.deepEqual(result.CARRYOVER, { carryover: true });
  assert.deepEqual(starts.appliedAbsence, { absent: true });

  const failedRun = buildRunner(
    () => Promise.reject(new Error('extra/weekend failed')),
    () => Promise.reject(new Error('carryover failed')),
    () => Promise.reject(new Error('absent failed')),
    () => assert.fail('failed absence read must not overwrite the current absence state'),
  );
  const failed = await failedRun();
  assert.deepEqual(failed.EXTRA, {});
  assert.deepEqual(failed.WEEKEND, {});
  assert.deepEqual(failed.CARRYOVER, {});

  return elapsed;
}

async function verifyRosterInputsParallelLoad() {
  const source = read('static/js/admin/features/exportLogs.js');
  const functionSource = extractFunction(source, 'loadRosterExportInputs');
  const buildRunner = new Function(
    'refreshRosterExportCoreData',
    'loadWeekendSlots',
    'ensureAbsentForRosterDate',
    'ensureLogsForRosterDate',
    'loadExtraAttendMap',
    `${functionSource}
     return loadRosterExportInputs;`,
  );
  const starts = {};
  const startedAt = performance.now();
  const delayed = (label, value) => () => delayResult(starts, label, startedAt, value);
  const run = buildRunner(
    delayed('core'),
    delayed('weekend'),
    delayed('absent'),
    delayed('logs'),
    delayed('extra', { '2026-08-29': ['demo-s001'] }),
  );
  const extraMap = await run('2026-08-29');
  const elapsed = performance.now() - startedAt;
  const requestStarts = ['core', 'weekend', 'absent', 'logs', 'extra'].map(key => starts[key]);

  assert.ok(requestStarts.every(Number.isFinite), 'all roster inputs must start');
  assert.ok(Math.max(...requestStarts) < 30, `roster inputs must start together: ${requestStarts}`);
  assert.ok(elapsed < 180, `roster inputs must take about one delayed request: ${elapsed.toFixed(1)}ms`);
  assert.deepEqual(extraMap, { '2026-08-29': ['demo-s001'] });
  return elapsed;
}

function verifyTodayCriticalPathSource() {
  const source = read('static/js/admin/features/today.js');
  const computeSource = extractFunction(source, 'computeTodayList');
  const loadSource = extractFunction(source, 'loadTodayAndRender');

  assert.match(computeSource, /^function computeTodayList\(dateKey, extraMap/);
  assert.doesNotMatch(computeSource, /loadExtraAttendMap\s*\(/);
  assert.match(loadSource, /const extraAttendPromise = loadExtraAttendMap\(\);/);
  assert.match(loadSource, /loadMakeupCarryoverMap\(\{ force \}\),\s*extraAttendPromise,/s);
  assert.match(loadSource, /computeTodayList\(dateKey, extraMap\)/);
}

function verifyBootstrapAndFeaturePrioritySource() {
  const stateSource = read('static/js/admin/core/state.js');
  for (const retiredInitialUrl of [
    '/api/tests-config',
    '/api/materials',
    '/api/mat-assign',
    '/api/extra-attend',
  ]) {
    assert.doesNotMatch(
      extractFunction(stateSource, 'bootstrap'),
      new RegExp(retiredInitialUrl.replaceAll('/', '\\/')),
      `${retiredInitialUrl} must not block admin bootstrap`,
    );
  }

  const mainSource = read('static/js/admin/main.js');
  const deferredSource = extractFunction(mainSource, 'initDeferredAdminFeatures');
  assert.match(deferredSource, /initCalendar\(\)/);
  assert.match(deferredSource, /initAdminOperationNotes\(\)/);
  assert.match(deferredSource, /initStudentLogs\(\)/);
  assert.match(deferredSource, /initAnnouncements\(\)/);
  assert.match(mainSource, /loadTodayAndRender\(\)[\s\S]*\.then\(initDeferredAdminFeatures\)/);

  const adminShell = read('static/admin.html');
  assert.match(adminShell, /admin\/demo\/bootstrap\.js/);
  assert.match(adminShell, /admin\/main\.js\?[^"']*latency=4/);
  assert.ok(
    adminShell.indexOf('admin/demo/bootstrap.js') < adminShell.indexOf('admin/main.js'),
    'the existing server process must install the demo guard before admin main',
  );
  assert.match(mainSource, /videoModal\.js\?v=20260830-popup-load3/);
  assert.match(mainSource, /logModal\.js\?v=20260830-popup-load3/);

  const doneSource = read('static/js/admin/features/done.js');
  const todaySource = read('static/js/admin/features/today.js');
  assert.match(doneSource, /today\.render\.js\?v=20260824-linked-leave1/);
  assert.match(todaySource, /today\.render\.js\?v=20260824-linked-leave1/);
}

async function verifyPopupCacheFailureEviction() {
  const logSource = read('static/js/admin/features/logModal.js');
  const cacheSource = extractFunction(logSource, 'fetchJSONCached');
  const buildCache = new Function(
    'window',
    'fetch',
    `${cacheSource}; return fetchJSONCached;`,
  );
  const cacheWindow = { __studentWorkFetchCache: new Map() };
  let requestCount = 0;
  let shouldFail = true;
  const cachedFetch = buildCache(cacheWindow, async () => {
    requestCount += 1;
    if (shouldFail) throw new Error('synthetic network failure');
    return {
      ok: true,
      status: 200,
      json: async () => ({ requestCount }),
    };
  });

  const failed = await Promise.allSettled([
    cachedFetch('/api/logs?sid=s1'),
    cachedFetch('/api/logs?sid=s1'),
  ]);
  assert.equal(requestCount, 1, 'concurrent popup reads must share one request');
  assert.ok(failed.every(result => result.status === 'rejected'));
  assert.equal(cacheWindow.__studentWorkFetchCache.has('/api/logs?sid=s1'), false);

  shouldFail = false;
  const recovered = await Promise.all([
    cachedFetch('/api/logs?sid=s1'),
    cachedFetch('/api/logs?sid=s1'),
  ]);
  assert.equal(requestCount, 2, 'a failed popup read must be retried on the next request');
  assert.deepEqual(recovered, [{ requestCount: 2 }, { requestCount: 2 }]);

  for (const relativePath of [
    'static/js/admin/features/logModal.js',
    'static/js/admin/features/testModal.js',
    'static/js/admin/features/videoModal.js',
  ]) {
    const source = read(relativePath);
    const helper = extractFunction(source, 'fetchJSONCached');
    assert.match(helper, /promise\.catch\(\(\) =>/);
    assert.match(helper, /cache\.delete\(url\)/);
  }
  assert.match(logSource, /invalidateLogModalHydrationCaches\(today, sid\)/);
  assert.match(read('static/js/admin/features/testModal.js'), /invalidateStudentWorkFetchCache\(`\/api\/progress\?sid=/);
  assert.match(read('static/js/admin/features/videoModal.js'), /invalidateVideoModalHydrationCaches\(today, sid\)/);
}

async function verifySaveConflictHandling() {
  const helperUrl = pathToFileURL(path.join(ROOT, 'static/js/admin/core/saveConflict.js')).href;
  const { classifySaveConflict } = await import(helperUrl);
  const rawLock = classifySaveConflict(
    { error: 'lock timeout: C:\\server\\progress.json.lock' },
    '진도',
  );
  assert.equal(rawLock.retryable, true);
  assert.doesNotMatch(rawLock.message, /C:\\server|다른 사용자/);
  const mislabeledRevision = classifySaveConflict(
    { code: 'revision_conflict', retryable: true, error: 'revision changed' },
    '진도',
  );
  assert.equal(
    mislabeledRevision.retryable,
    false,
    'only a transient lock timeout may be retried automatically',
  );

  const logSource = read('static/js/admin/features/logModal.js');
  const patchSource = extractFunction(logSource, 'patchProgressEntry');
  const buildPatch = new Function(
    'fetch',
    'toast',
    'setTimeout',
    'classifySaveConflict',
    `${patchSource}; return patchProgressEntry;`,
  );
  const response = (status, payload) => ({
    status,
    ok: status >= 200 && status < 300,
    json: async () => payload,
  });
  const retryResponses = [
    response(409, { code: 'progress_lock_timeout', retryable: true }),
    response(200, { ok: true, progress: { mid: 'done' } }),
  ];
  const retryToasts = [];
  const retryPatch = buildPatch(
    async () => retryResponses.shift(),
    message => retryToasts.push(message),
    callback => { callback(); return 1; },
    classifySaveConflict,
  );
  assert.deepEqual(await retryPatch('2026-08-30', 'sid', { mid: 'done' }), { mid: 'done' });
  assert.equal(retryResponses.length, 0);
  assert.equal(retryToasts.length, 1);

  let conflictCalls = 0;
  const conflictPatch = buildPatch(
    async () => {
      conflictCalls += 1;
      return response(409, { retryable: false, error: '다른 화면에서 진도가 변경되었습니다.' });
    },
    () => {},
    callback => { callback(); return 1; },
    classifySaveConflict,
  );
  await assert.rejects(
    () => conflictPatch('2026-08-30', 'sid', { mid: 'done' }),
    /다른 화면/,
  );
  assert.equal(conflictCalls, 1, 'a real revision conflict must not be retried blindly');
}

const calendarElapsed = await verifyCalendarParallelPreload();
const rosterElapsed = await verifyRosterInputsParallelLoad();
verifyTodayCriticalPathSource();
verifyBootstrapAndFeaturePrioritySource();
await verifyPopupCacheFailureEviction();
await verifySaveConflictHandling();

console.log(`admin latency contracts: OK (calendar ${calendarElapsed.toFixed(1)}ms, roster inputs ${rosterElapsed.toFixed(1)}ms)`);
