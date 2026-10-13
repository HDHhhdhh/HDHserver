import assert from 'node:assert/strict';
import fs from 'node:fs';

class MemoryStorage {
  #values = new Map();
  get length() { return this.#values.size; }
  getItem(key) { return this.#values.has(key) ? this.#values.get(key) : null; }
  setItem(key, value) { this.#values.set(String(key), String(value)); }
  removeItem(key) { this.#values.delete(String(key)); }
  key(index) { return Array.from(this.#values.keys())[index] ?? null; }
}

globalThis.sessionStorage = new MemoryStorage();

const { createDemoFetch } = await import('../static/js/admin/demo/fetch.js');
const { loadDemoStore } = await import('../static/js/admin/demo/store.js');

let forwarded = 0;
const originalFetch = async () => {
  forwarded += 1;
  return new Response('{}', { status: 500 });
};
const root = {
  fetch: originalFetch,
  location: {
    href: 'http://localhost/demo/rh3123',
    origin: 'http://localhost',
    pathname: '/demo/rh3123',
  },
};
const demoFetch = createDemoFetch({ window: root, originalFetch });
const initialOrderMap = await (await demoFetch('/api/today_order')).json();

const initialCalendarResponse = await demoFetch('/api/school-calendar');
const initialCalendar = await initialCalendarResponse.json();
const initialCalendarRevision = initialCalendarResponse.headers.get('X-School-Calendar-Revision') || '';
assert.match(initialCalendarRevision, /^[0-9a-f]{64}$/, 'demo calendar GET lacks a revision');
const missingCalendarRevision = await demoFetch('/api/school-calendar', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ version: 2, activeYear: 'missing-revision' }),
});
assert.equal(missingCalendarRevision.status, 428, 'demo calendar accepted a missing revision');
assert.deepEqual(
  await (await demoFetch('/api/school-calendar')).json(),
  initialCalendar,
  'missing demo calendar revision changed the store',
);
const demoCalendarDocument = {
  version: 2,
  activeYear: '2026',
  years: { 2026: { activeSemester: '2', schools: { '데모고': {} } } },
};
const savedCalendar = await demoFetch('/api/school-calendar', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'If-Match': initialCalendarRevision,
  },
  body: JSON.stringify(demoCalendarDocument),
});
assert.equal(savedCalendar.status, 200, 'demo revisioned calendar save failed');
const savedCalendarRevision = savedCalendar.headers.get('X-School-Calendar-Revision') || '';
assert.match(savedCalendarRevision, /^[0-9a-f]{64}$/);
const staleCalendar = await demoFetch('/api/school-calendar', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'If-Match': initialCalendarRevision,
  },
  body: JSON.stringify({ version: 2, activeYear: 'stale-writer' }),
});
assert.equal(staleCalendar.status, 409, 'demo calendar accepted a stale revision');
assert.equal(staleCalendar.headers.get('X-School-Calendar-Revision'), savedCalendarRevision);
assert.deepEqual(
  await (await demoFetch('/api/school-calendar')).json(),
  demoCalendarDocument,
  'stale demo calendar writer overwrote the winner',
);

const demoTestsConfig = {
  categories: {
    SCHOOL_PAST: {
      label: '학군지 기출',
      unknownCategory: { preserve: true },
      tests: [{
        id: 'demo-partial-patch',
        name: '이동 전',
        term: '기말고사',
        examTerm: '기말고사',
        sourceFiles: { solutionFileId: 'keep-solution', name: 'before.pdf' },
        unknownTest: { preserve: true },
      }],
    },
    UNIT: { label: '단원평가', tests: [] },
  },
  unknownConfig: { preserve: true },
};
assert.equal((await demoFetch('/api/tests-config', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(demoTestsConfig),
})).status, 200, 'demo tests-config seed failed');
const demoTestPatch = await demoFetch('/api/tests-config/test', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    categoryKey: 'UNIT',
    categoryLabel: '단원평가',
    test: {
      id: 'demo-partial-patch',
      name: '이동 후',
      sourceFiles: { name: 'after.pdf' },
    },
    clearFields: ['term', 'examTerm'],
  }),
});
assert.equal(demoTestPatch.status, 200, 'demo single-test PATCH failed');
const demoPatchedConfig = await (await demoFetch('/api/tests-config')).json();
assert.equal(demoPatchedConfig.categories.SCHOOL_PAST.tests.length, 0, 'demo PATCH kept the old category record');
const demoPatchedTest = demoPatchedConfig.categories.UNIT.tests[0];
assert.equal(demoPatchedTest.name, '이동 후');
assert.equal(demoPatchedTest.term, undefined, 'demo PATCH retained cleared term');
assert.equal(demoPatchedTest.examTerm, undefined, 'demo PATCH retained cleared examTerm');
assert.equal(demoPatchedTest.sourceFiles.solutionFileId, 'keep-solution', 'demo PATCH dropped solution metadata');
assert.equal(demoPatchedTest.sourceFiles.name, 'after.pdf', 'demo PATCH did not merge source metadata');
assert.equal(demoPatchedTest.unknownTest.preserve, true, 'demo PATCH dropped unknown test metadata');
assert.equal(demoPatchedConfig.unknownConfig.preserve, true, 'demo PATCH dropped unknown config metadata');
const demoConfigBeforeRejectedClear = JSON.stringify(demoPatchedConfig);
assert.equal((await demoFetch('/api/tests-config/test', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    categoryKey: 'UNIT',
    test: { id: 'demo-partial-patch', name: '거부 대상' },
    clearFields: ['sourceFiles'],
  }),
})).status, 400, 'demo PATCH accepted an unsafe clear field');
assert.equal(
  JSON.stringify(await (await demoFetch('/api/tests-config')).json()),
  demoConfigBeforeRejectedClear,
  'rejected demo PATCH changed the catalog',
);

const initialSheetConfig = await demoFetch('/api/makeup-sheet-sync/config');
assert.equal(initialSheetConfig.status, 200, 'demo sheet config GET failed');
assert.equal((await initialSheetConfig.json()).sheetUrl, '');
const demoSheetUrl = 'https://docs.google.com/spreadsheets/d/demo-sheet/edit?gid=7';
const savedSheetConfig = await demoFetch('/api/makeup-sheet-sync/config', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ sheetUrl: demoSheetUrl }),
});
assert.equal(savedSheetConfig.status, 200, 'demo sheet config POST failed');
assert.equal((await savedSheetConfig.json()).sheetUrl, demoSheetUrl);
assert.equal(
  (await (await demoFetch('/api/makeup-sheet-sync/config')).json()).sheetUrl,
  demoSheetUrl,
  'demo sheet config was not persisted in demo storage',
);
assert.equal((await demoFetch('/api/makeup-sheet-sync/config', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ sheetUrl: 'https://example.com/not-a-sheet' }),
})).status, 400, 'demo accepted a non-Google sheet config');
const demoSheetSync = await demoFetch('/api/makeup-sheet-sync', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ date: '2026-06-17' }),
});
assert.equal(demoSheetSync.status, 200, 'demo sheet sync was not safely emulated');
assert.equal((await demoSheetSync.json()).added, 0, 'demo sheet sync created live-like absence data');

for (const [date, order] of Object.entries({ '2026-06-16': ['keep'], '2026-06-17': ['old'] })) {
  const seeded = await demoFetch('/api/today_order', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date, order }),
  });
  assert.equal(seeded.status, 200);
}
assert.equal(
  (await demoFetch('/api/today_order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ '2026-06-16': ['overwrite'] }),
  })).status,
  404,
  'demo accepted the retired whole-map today-order POST',
);
const patched = await demoFetch('/api/today_order', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ date: '2026-06-17', order: [' a ', 'a', 'b'] }),
});
assert.equal(patched.status, 200);
assert.deepEqual((await patched.json()).order, ['a', 'b']);
let orderMap = await (await demoFetch('/api/today_order')).json();
assert.deepEqual(orderMap['2026-06-16'], ['keep'], 'demo PATCH overwrote another date');
assert.deepEqual(orderMap['2026-06-17'], ['a', 'b']);

const deleted = await demoFetch('/api/today_order?date=2026-06-17', { method: 'DELETE' });
assert.equal(deleted.status, 200);
assert.equal((await deleted.json()).cleared, true);
orderMap = await (await demoFetch('/api/today_order')).json();
const expectedAfterDelete = { ...initialOrderMap, '2026-06-16': ['keep'] };
delete expectedAfterDelete['2026-06-17'];
assert.deepEqual(orderMap, expectedAfterDelete, 'demo DELETE overwrote another date');
assert.equal(
  (await demoFetch('/api/today_order', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-02-31', order: [] }),
  })).status,
  400,
  'demo accepted an impossible order date',
);

const updatesBeforeRetiredPost = await (await demoFetch('/api/updates')).json();
const retiredUpdatesPost = await demoFetch('/api/updates', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ '2026-06-16': { 'demo-s001': { videos: ['overwrite'], source: 'manual' } } }),
});
assert.equal(retiredUpdatesPost.status, 404, 'demo accepted retired base POST /api/updates');
const updatesAfterRetiredPost = await (await demoFetch('/api/updates')).json();
assert.deepEqual(updatesAfterRetiredPost, updatesBeforeRetiredPost, 'retired updates POST changed demo data');

const extraDate = '2026-06-16';
const extraSaved = await demoFetch('/api/extra-attend', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ date: extraDate, sids: ['demo-extra-sid'] }),
});
assert.equal(extraSaved.status, 200);
const extraBeforeRetiredAliases = await (await demoFetch('/api/extra-attend')).json();
for (const retiredPath of ['/api/extra', '/api/extra_attend', '/api/extra-attend/all']) {
  assert.equal((await demoFetch(retiredPath)).status, 404, `demo accepted retired extra-attend GET: ${retiredPath}`);
  assert.equal((await demoFetch(retiredPath, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: extraDate, sids: ['overwrite'] }),
  })).status, 404, `demo accepted retired extra-attend PATCH: ${retiredPath}`);
}
const extraAfterRetiredAliases = await (await demoFetch('/api/extra-attend')).json();
assert.deepEqual(extraAfterRetiredAliases, extraBeforeRetiredAliases, 'retired extra-attend alias changed demo data');

for (const { basePath, patchPath, key } of [
  { basePath: '/api/attendance', patchPath: '/api/attendance/patch', key: 'attendance' },
  { basePath: '/api/contact', patchPath: '/api/contact/patch', key: 'contact' },
]) {
  const patchedFlag = await demoFetch(patchPath, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-06-16', sid: `demo-${key}-sid`, value: true }),
  });
  assert.equal(patchedFlag.status, 200);
  const beforeRetiredBulk = await (await demoFetch(`${basePath}?date=2026-06-16`)).json();
  const retiredBulk = await demoFetch(basePath, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-06-16', map: { overwrite: 1 }, replace: true }),
  });
  assert.equal(retiredBulk.status, 404, `demo accepted retired bulk POST: ${basePath}`);
  const afterRetiredBulk = await (await demoFetch(`${basePath}?date=2026-06-16`)).json();
  assert.deepEqual(afterRetiredBulk, beforeRetiredBulk, `retired bulk POST changed ${key} data`);
}

const arriveDate = '2026-06-16';
const arriveSaved = await demoFetch('/api/arrive-time', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ [arriveDate]: { 'demo-s002': '15:00', 'demo-s003': '17:50' } }),
});
assert.equal(arriveSaved.status, 200);
const arrivePatched = await demoFetch('/api/arrive-time/patch', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ date: arriveDate, sid: 'demo-s002', value: '16:30' }),
});
assert.equal(arrivePatched.status, 200);
const arriveBeforeRetiredRequests = await (await demoFetch(`/api/arrive-time?date=${arriveDate}`)).json();
assert.deepEqual(arriveBeforeRetiredRequests, { 'demo-s002': '16:30', 'demo-s003': '17:50' });
for (const [retiredUrl, init] of [
  [`/arrive-time?date=${arriveDate}`, undefined],
  ['/arrive-time', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [arriveDate]: { 'demo-arrive-sid': 'overwrite' } }),
  }],
  ['/arrive-time/patch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: arriveDate, sid: 'demo-arrive-sid', value: 'overwrite' }),
  }],
]) {
  const retiredResponse = await demoFetch(retiredUrl, init);
  assert.equal(retiredResponse.status, 404, `demo accepted retired arrive-time route: ${retiredUrl}`);
}
const arriveAfterRetiredRequests = await (await demoFetch(`/api/arrive-time?date=${arriveDate}`)).json();
assert.deepEqual(arriveAfterRetiredRequests, arriveBeforeRetiredRequests, 'retired demo arrive-time route changed data');

const demoUnitLabel = '단원평가 / 대수 / Lv.5 / 1회차 / 단원';
const demoSchoolLabel = '학군지 기출 / 대수 / 중상 / 기말고사 / 학군지';
const firstTestAssignment = await (await demoFetch('/api/progress/patch', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    date: '2026-06-19',
    sid: 'test-order-sid',
    progress: {
      tests: { [demoUnitLabel]: 'assigned', [demoSchoolLabel]: 'assigned' },
      __testAssignmentTouchedKeys: [demoUnitLabel, demoSchoolLabel],
    },
  }),
})).json();
assert.equal(firstTestAssignment.progress.__testAssignmentChangeOrder[demoUnitLabel], 1);
assert.equal(firstTestAssignment.progress.__testAssignmentChangeOrder[demoSchoolLabel], 1);
assert.equal(firstTestAssignment.progress.__testAssignmentTouchedKeys, undefined, 'touch hints must not persist');

const schoolReassignment = await (await demoFetch('/api/progress/patch', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    date: '2026-06-19',
    sid: 'test-order-sid',
    progress: {
      tests: { [demoUnitLabel]: 'assigned', [demoSchoolLabel]: 'assigned' },
      __testAssignmentTouchedKeys: [demoSchoolLabel],
    },
  }),
})).json();
assert.equal(schoolReassignment.progress.__testAssignmentChangeOrder[demoUnitLabel], 1);
assert.equal(schoolReassignment.progress.__testAssignmentChangeOrder[demoSchoolLabel], 2);

const laterCompletion = await (await demoFetch('/api/progress/patch', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    date: '2026-06-19',
    sid: 'test-order-sid',
    progress: { tests: { [demoUnitLabel]: 'done', [demoSchoolLabel]: 'assigned' } },
  }),
})).json();
assert.equal(laterCompletion.progress.__testAssignmentChangeOrder[demoUnitLabel], 3);
assert.equal(laterCompletion.progress.__testAssignmentChangeOrder[demoSchoolLabel], 2);

await demoFetch('/api/absent', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    by_date: { '2026-06-16': ['sid-a'], '2026-06-17': ['sid-a', 'sid-b'] },
    by_student: { 'sid-a': '2026-06-17', 'sid-b': '2026-06-17' },
    by_slot: { '2026-06-16': { 'sid-a': [1] }, '2026-06-17': { 'sid-a': [2], 'sid-b': [1] } },
  }),
});
const recovered = await demoFetch('/api/absent/recover', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ date: '2026-06-17', sids: ['sid-a'] }),
});
assert.equal(recovered.status, 200);
const recoveredMap = await recovered.json();
assert.deepEqual(recoveredMap.by_date['2026-06-17'], ['sid-b']);
assert.deepEqual(recoveredMap.by_date['2026-06-16'], ['sid-a']);
assert.equal(recoveredMap.by_student['sid-a'], undefined);
assert.deepEqual(recoveredMap.by_slot['2026-06-16']['sid-a'], [1]);
assert.deepEqual(recoveredMap.by_slot['2026-06-17'], { 'sid-b': [1] });

await demoFetch('/api/absent', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    by_date: { '2026-06-18': ['sid-a', 'sid-b'] },
    by_student: { 'sid-a': '2026-06-18', 'sid-b': '2026-06-18' },
    by_slot: { '2026-06-18': { 'sid-a': [1], 'sid-b': [2] } },
  }),
});
await Promise.all([
  demoFetch('/api/absent/recover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-06-18', sids: ['sid-a'] }),
  }),
  demoFetch('/api/absent/recover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-06-18', sids: ['sid-b'] }),
  }),
]);
const concurrentRecovery = await (await demoFetch('/api/absent')).json();
assert.deepEqual(concurrentRecovery.by_date['2026-06-18'], [], 'concurrent demo recoveries lost a narrow update');
assert.equal(concurrentRecovery.by_student['sid-a'], undefined);
assert.equal(concurrentRecovery.by_student['sid-b'], undefined);

const batchLogDate = '2026-06-20';
for (const sid of ['demo-s001', 'demo-s002']) {
  const seededLog = await demoFetch('/api/logs/patch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      date: batchLogDate,
      sid,
      entry: { archived: true, preserved: sid },
    }),
  });
  assert.equal(seededLog.status, 200);
}
const batchLogResponse = await demoFetch('/api/logs/patch-batch', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    patches: [
      {
        date: batchLogDate,
        sid: 'demo-s001',
        entry: { done: true, leaveTime: '20:15' },
        __clear: ['archived'],
      },
      {
        date: batchLogDate,
        sid: 'demo-s002',
        entry: { done: true, leaveTime: '20:15' },
        __clear: ['archived'],
      },
    ],
  }),
});
assert.equal(batchLogResponse.status, 200);
assert.equal((await batchLogResponse.json()).count, 2);
const batchLogs = await (await demoFetch(`/api/logs?date=${batchLogDate}`)).json();
assert.equal(batchLogs[batchLogDate]['demo-s001'].done, true);
assert.equal(batchLogs[batchLogDate]['demo-s001'].archived, undefined);
assert.equal(batchLogs[batchLogDate]['demo-s001'].preserved, 'demo-s001');
assert.equal(batchLogs[batchLogDate]['demo-s002'].done, true);
assert.equal(batchLogs[batchLogDate]['demo-s002'].archived, undefined);
assert.equal(batchLogs[batchLogDate]['demo-s002'].preserved, 'demo-s002');

const duplicateBatchBefore = structuredClone(batchLogs[batchLogDate]);
const duplicateBatchResponse = await demoFetch('/api/logs/patch-batch', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    patches: [
      { date: batchLogDate, sid: 'demo-s001', entry: { overwritten: true } },
      { date: batchLogDate, sid: 'demo-s001', entry: { overwrittenAgain: true } },
    ],
  }),
});
assert.equal(duplicateBatchResponse.status, 400);
const logsAfterDuplicate = await (await demoFetch(`/api/logs?date=${batchLogDate}`)).json();
assert.deepEqual(logsAfterDuplicate[batchLogDate], duplicateBatchBefore, 'invalid batch partially changed demo logs');

const summary = await (await demoFetch('/api/logs/unarchived-summary?exclude_date=2026-06-17')).json();
assert.equal(summary.rowsAvailable, true);
for (const row of summary.rows || []) {
  assert.deepEqual(
    Object.keys(row.entry || {}).sort().filter(key => !['archived', 'done', 'hwChecked', 'selfStudy'].includes(key)),
    [],
    'demo summary leaked full log metadata',
  );
}
const missingLeaveSummary = await (
  await demoFetch('/api/arrive-time/missing-leave-summary?exclude_date=2026-06-17')
).json();
assert.equal(missingLeaveSummary.rowsAvailable, true);
assert.equal(missingLeaveSummary.total, 1);
assert.deepEqual(missingLeaveSummary.rows, [
  { date: '2026-06-16', sid: 'demo-s002', arriveTime: '16:30' },
]);
assert.equal(
  missingLeaveSummary.rows.some(row => row.sid === 'demo-s003' || row.sid === 'demo-arrive-sid'),
  false,
  'moved-makeup or unknown roster residue triggered a leave warning',
);

const quickPrinterBefore = loadDemoStore().quickPrinterExports.length;
const quickPrinterPreview = await demoFetch('/api/tests/quick-printer-export/preview', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    date: '2026-06-17',
    studentIds: ['demo-s001', 'demo-s002', 'demo-s005'],
    includePreviouslyExportedCarryovers: false,
  }),
});
assert.equal(quickPrinterPreview.status, 200);
const quickPrinterPreviewPayload = await quickPrinterPreview.json();
assert.equal(quickPrinterPreviewPayload.automaticExclusionStudentCount, 2);
assert.equal(quickPrinterPreviewPayload.automaticExclusionCount, 3);
assert.equal(quickPrinterPreviewPayload.rowCount, 1);
assert.equal(quickPrinterPreviewPayload.csv, undefined);
assert.equal(loadDemoStore().quickPrinterExports.length, quickPrinterBefore, 'preview wrote demo export history');

const zeroQuickPrinterExport = await demoFetch('/api/tests/quick-printer-export', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    date: '2026-06-17',
    studentIds: ['demo-s001'],
    includePreviouslyExportedCarryovers: false,
  }),
});
assert.equal(zeroQuickPrinterExport.status, 422);
const zeroQuickPrinterPayload = await zeroQuickPrinterExport.json();
assert.equal(zeroQuickPrinterPayload.code, 'no_new_assignments_after_carryover_exclusion');
assert.equal(zeroQuickPrinterPayload.csv, undefined);
assert.equal(loadDemoStore().quickPrinterExports.length, quickPrinterBefore, 'zero-row export wrote demo history');

const reprintQuickPrinterExport = await demoFetch('/api/tests/quick-printer-export', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    date: '2026-06-17',
    studentIds: ['demo-s001'],
    includePreviouslyExportedCarryovers: true,
  }),
});
assert.equal(reprintQuickPrinterExport.status, 200);
const reprintQuickPrinterPayload = await reprintQuickPrinterExport.json();
assert.equal(reprintQuickPrinterPayload.rowCount, 2);
assert.ok(reprintQuickPrinterPayload.csv.startsWith('\uFEFF'));
assert.equal(loadDemoStore().quickPrinterExports.length, quickPrinterBefore + 1);

const fallbackSource = fs.readFileSync('static/js/admin/demo/bootstrap.js', 'utf8');
const threadPreviewSource = fs.readFileSync('static/js/admin/demo/threadPreview.js', 'utf8');
const threadPreviewCss = fs.readFileSync('static/css/demo-thread-preview.css', 'utf8');
assert.match(fallbackSource, /\.\/fetch\.js\?v=20260912-watch-rearm1/);
assert.match(fallbackSource, /import\('\.\/threadPreview\.js\?v=20260914-threads1'\)/);
assert.match(threadPreviewSource, /MutationObserver/);
assert.match(threadPreviewSource, /demo-thread-avatar/);
assert.match(threadPreviewCss, /body\.admin\.demo-thread-preview\.student-popup-open/);
assert.match(threadPreviewCss, /\.assistant-note-item::after/);
assert.match(fallbackSource, /applyDemoQuickPrinterRequest/);
assert.match(fallbackSource, /path === '\/api\/tests-config\/test' && method === 'PATCH'/);
assert.match(fallbackSource, /patchDemoTestConfig\(store\.testsConfig/);
assert.match(fallbackSource, /path === '\/api\/today_order' && method === 'PATCH'/);
assert.doesNotMatch(fallbackSource, /path === '\/api\/today_order' && method === 'POST'/);
assert.doesNotMatch(fallbackSource, /path === '\/api\/updates' && method === 'POST'/);
assert.match(fallbackSource, /path === '\/api\/today_order' && method === 'DELETE'/);
assert.match(fallbackSource, /case '\/api\/arrive-time':/);
assert.match(fallbackSource, /case '\/api\/arrive-time\/missing-leave-summary':/);
assert.doesNotMatch(fallbackSource, /case '\/arrive-time':/);
assert.match(fallbackSource, /path === '\/arrive-time'/, 'retired arrive-time requests must remain demo-blocked');
assert.match(fallbackSource, /path === '\/api\/absent\/recover'/);
assert.match(fallbackSource, /path === '\/api\/logs\/patch-batch' && method === 'POST'/);
assert.match(fallbackSource, /case '\/api\/makeup-sheet-sync\/config':/);
assert.match(fallbackSource, /path === '\/api\/makeup-sheet-sync\/config' && method === 'POST'/);
assert.match(fallbackSource, /path === '\/api\/makeup-sheet-sync' && method === 'POST'/);
assert.match(fallbackSource, /method === 'POST' && path === '\/api\/school-calendar'/);
assert.match(fallbackSource, /X-School-Calendar-Revision/);
assert.match(fallbackSource, /school_calendar_conflict/);
assert.match(fallbackSource, /function applyFallbackLogPatchBatch\(store, body\)/);
assert.match(fallbackSource, /Number\(mutation\?\.__demoStatus\)/, 'fallback mutations must preserve endpoint-specific HTTP error status');
for (const shell of ['admin.html', 'all.html', 'school-cal.html', 'video-manage.html', 'tests.html']) {
  const shellSource = fs.readFileSync(`static/${shell}`, 'utf8');
  const expectedBootstrapVersion = shell === 'admin.html'
    ? '/js/admin/demo/bootstrap.js?v=20260830-missing-leave-roster1&amp;quickPrinter=1'
    : '/js/admin/demo/bootstrap.js?v=20260828-calendar-revision1';
  assert.ok(shellSource.includes(expectedBootstrapVersion), `${shell} has the wrong demo bootstrap cache key`);
}
assert.equal(forwarded, 0, 'Phase16 demo API escaped to the live fetch implementation');

console.log('Phase16 demo contracts passed');
