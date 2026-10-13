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
     let calendarPreloadError = null;
     const fetchJsonChecked = async (url) => { const response = await fetch(url); if (!response.ok) throw new Error('fixture HTTP failure'); return response.json(); };
     let calendarMutationGeneration = 0;
     let calendarReadGeneration = 0;
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
      return delayResult(starts, url, startedAt, { [url]: true }).then(payload => ({ ok: true, status: 200, json: () => payload }));
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

async function verifyCalendarRecalculation() {
  const source = read('static/js/admin/features/calendar.js');
  const projectionState = source.match(/\blet calendarProjectionGeneration = 0;/)?.[0];
  assert.ok(projectionState, 'calendar projection generation must be initialized');
  const recalcStart = source.indexOf('window.recalcCalendarCounts = function () {');
  const recalcEnd = source.indexOf('\n  };', recalcStart) + '\n  };'.length;
  assert.ok(recalcStart >= 0 && recalcEnd > recalcStart);
  const calls = [];
  let generation = 1;
  let fail = false;
  let release;
  let block = null;
  const day = '2026-10-02';
  const load = async label => {
    const snapshotGeneration = generation;
    const rejectSnapshot = fail;
    calls.push(label);
    if (block) await block;
    if (rejectSnapshot) throw new Error('synthetic failed read');
    if (label === '/api/extra-attend') return { [day]: [snapshotGeneration === 1 ? 'extra' : 'new'] };
    if (label === '/api/weekend-slots') return { [day]: { extra: [2], new: [1, 2] } };
    if (label === 'carryover') return { payload: { generation: snapshotGeneration } };
    return { [day]: snapshotGeneration === 1 ? ['regular'] : [] };
  };
  const listenerStart = source.indexOf('  let calendarMutationRefreshPromise = null;');
  const listenerEnd = source.indexOf("  document.addEventListener('admin:date-change'", listenerStart);
  assert.ok(listenerStart >= 0 && listenerEnd > listenerStart);
  const runner = new Function('load', 'day', `
    let EXTRA, WEEKEND, CARRYOVER, countMap;
    let preloadExtraWeekendPromise = null;
     let calendarPreloadError = null;
     const fetchJsonChecked = async (url) => { const response = await fetch(url); if (!response.ok) throw new Error('fixture HTTP failure'); return response.json(); };
    let calendarMutationGeneration = 0;
    let calendarReadGeneration = 0;
    ${projectionState}
    const state = { students: [{ id: 'regular' }], absentByDate: {} };
    const window = {};
    const listeners = {};
    const document = {
      addEventListener: (name, callback) => { listeners[name] = callback; },
      dispatchEvent: event => listeners[event.type]?.(event),
    };
    function CustomEvent(type) { this.type = type; }
    const rendered = [];
    const calendar = { view: { activeStart: new Date(day), activeEnd: new Date('2026-10-03') } };
    const fetch = url => { const payload = load(url); return Promise.resolve({ ok: true, status: 200, json: () => payload }); };
    const fetchMakeupCarryoverSnapshot = () => load('carryover');
    const fetchAbsentSnapshot = () => load('absent');
    const applyAbsentPayload = value => { state.absentByDate = value; };
    const normalizeCarryoverPayload = value => value;
    const MAKEUP_SLOTS = [1, 2];
    const ymd = date => date.toISOString().slice(0, 10);
    const yoil = () => '금';
    const hasWeekday = () => true;
    const getCountSlots = () => [1];
    const getMakeupSlots = (date, sid) => WEEKEND?.[date]?.[sid] || [1];
    const parseSlotNumbers = value => value;
    function refreshCountBadges() { rendered.push({ kind: 'counts', counts: structuredClone(countMap) }); }
    function renderMakeupPlanner() { rendered.push({ kind: 'planner', counts: structuredClone(countMap), extra: structuredClone(EXTRA), carryover: structuredClone(CARRYOVER) }); }
    function refreshMakeupConflictHints() {}
    ${extractFunction(source, 'addSlotCounts')}
    ${extractFunction(source, 'invalidateCalendarPreload')}
    ${extractFunction(source, 'preloadExtraWeekend')}
    ${extractFunction(source, 'fetchCountsForRange')}
    ${extractFunction(source, 'refreshMakeupPlanner')}
    ${extractFunction(source, 'refreshCalendarAfterMutation')}
    ${source.slice(recalcStart, recalcEnd)}
    ${source.slice(listenerStart, listenerEnd)}
    return { recalc: window.recalcCalendarCounts, rendered, changed: () => listeners['attendance:updated'](),
      committed: () => refreshCalendarAfterMutation({ attendance: true }) };
  `)(load, day);
  const bundle = ['/api/extra-attend', '/api/weekend-slots', 'carryover', 'absent'];
  await runner.recalc();
  assert.deepEqual(calls, bundle, 'one recalculation must read each input once');
  assert.deepEqual(runner.rendered.slice(-2), [
    { kind: 'counts', counts: { [day]: { 1: 0, 2: 1 } } },
    { kind: 'planner', counts: { [day]: { 1: 0, 2: 1 } }, extra: { [day]: ['extra'] }, carryover: { generation: 1 } },
  ]);
  generation = 2;
  calls.length = 0;
  await runner.recalc();
  assert.deepEqual(calls, bundle, 'a later recalculation must reload after mutation');
  assert.deepEqual(runner.rendered.at(-1), {
    kind: 'planner', counts: { [day]: { 1: 2, 2: 1 } }, extra: { [day]: ['new'] }, carryover: { generation: 2 },
  });
  fail = true;
  calls.length = 0;
  await runner.recalc();
  assert.deepEqual(calls, bundle);
  fail = false;
  calls.length = 0;
  block = new Promise(resolve => { release = resolve; });
  const pending = [runner.recalc(), runner.recalc()];
  assert.deepEqual(calls, bundle, 'overlapping recalculations must share only the pending read');
  release();
  await Promise.all(pending);
  assert.deepEqual(calls, bundle, 'failed preload must remain retryable without a second serial bundle');
  assert.equal(runner.rendered.at(-1).carryover.generation, 2);
  generation = 1;
  calls.length = 0;
  block = new Promise(resolve => { release = resolve; });
  const older = runner.recalc();
  generation = 2;
  const afterCommit = runner.changed();
  const latest = runner.recalc();
  block = null;
  release();
  await Promise.all([older, afterCommit, latest]);
  assert.deepEqual(calls, [...bundle, ...bundle], 'a committed mutation must discard the old flight and share one fresh bundle');
  assert.equal(runner.rendered.at(-1).carryover.generation, 2);
  assert.deepEqual(runner.rendered.at(-1).counts, { [day]: { 1: 2, 2: 1 } });
  calls.length = 0;
  await runner.committed();
  assert.deepEqual(calls, bundle, 'one committed absence action shares planner, counts and both events');
  generation = 3;
  calls.length = 0;
  await runner.committed();
  assert.deepEqual(calls, bundle, 'the next committed action must read a new authoritative snapshot');
  assert.equal(runner.rendered.at(-1).carryover.generation, 3);
  for (let depth = 0; depth <= 12; depth += 1) {
    generation = 1;
    calls.length = 0;
    const previous = runner.recalc();
    let turn = Promise.resolve();
    for (let index = 0; index < depth; index += 1) turn = turn.then(() => {});
    const committed = turn.then(() => {
      generation = 2;
      return Promise.all([runner.changed(), runner.recalc()]);
    });
    await Promise.all([previous, committed]);
    assert.deepEqual(calls, [...bundle, ...bundle], `mutation at microtask depth ${depth} must share exactly one fresh read`);
    assert.equal(runner.rendered.at(-1).carryover.generation, 2);
    assert.deepEqual(runner.rendered.at(-1).counts, { [day]: { 1: 2, 2: 1 } });
  }
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
  const allPopupSource = read('static/js/all/features/studentRecordPopup.js');
  for (const module of ['logModal', 'videoModal']) {
    const version = new RegExp(`${module}\\.js\\?v=([^"']+)`);
    const adminVersion = mainSource.match(version)?.[1];
    assert.ok(adminVersion, `${module} must carry a version`);
    assert.equal(allPopupSource.match(version)?.[1], adminVersion, `${module} must use one version on both pages`);
  }

  const doneSource = read('static/js/admin/features/done.js');
  const todaySource = read('static/js/admin/features/today.js');
  const doneRendererUrl = doneSource.match(/from ['"]([^'"]*today\.render\.js\?v=[^'"]+)['"]/)?.[1];
  const todayRendererUrl = todaySource.match(/from ['"]([^'"]*today\.render\.js\?v=[^'"]+)['"]/)?.[1];
  assert.ok(doneRendererUrl, 'done must load a versioned renderer');
  assert.equal(doneRendererUrl, todayRendererUrl, 'today/done must share one renderer and its per-SID save locks');
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
await verifyCalendarRecalculation();
const rosterElapsed = await verifyRosterInputsParallelLoad();
verifyTodayCriticalPathSource();
verifyBootstrapAndFeaturePrioritySource();
await verifyPopupCacheFailureEviction();
await verifySaveConflictHandling();

console.log(`admin latency contracts: OK (calendar ${calendarElapsed.toFixed(1)}ms, roster inputs ${rosterElapsed.toFixed(1)}ms)`);
