import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..', '..');
const files = Object.freeze({
  logModal: path.join(root, 'static', 'js', 'admin', 'features', 'logModal.js'),
  css: path.join(root, 'static', 'css', 'admin.css'),
  lightCss: path.join(root, 'static', 'css', 'student-work-light.css'),
  contract: path.join(root, 'static', 'js', 'admin', 'demo', 'homeworkContract.js'),
  demoData: path.join(root, 'static', 'js', 'admin', 'demo', 'data.js'),
  demoStore: path.join(root, 'static', 'js', 'admin', 'demo', 'store.js'),
  demoFetch: path.join(root, 'static', 'js', 'admin', 'demo', 'fetch.js'),
  demoBootstrap: path.join(root, 'static', 'js', 'admin', 'demo', 'bootstrap.js'),
});

function runtimeScript() {
  return `
    import assert from 'node:assert/strict';
    import { pathToFileURL } from 'node:url';
    const [contractPath, storePath, fetchPath] = process.argv.slice(1);
    const contract = await import(pathToFileURL(contractPath).href);
    const storeModule = await import(pathToFileURL(storePath).href);
    const fetchModule = await import(pathToFileURL(fetchPath).href);

    assert.equal(contract.homeworkLocalDateTimeToKst('2026-08-11T18:05'), '2026-08-11T18:05:00+09:00');
    assert.equal(contract.homeworkLocalDateTimeToKst(''), null);
    assert.equal(contract.homeworkDueAtToLocalInput('2026-08-11T18:05:00+09:00'), '2026-08-11T18:05');
    assert.equal(contract.homeworkEffectiveStatus({ status: 'assigned', dueAt: '2026-08-11T18:05:00+09:00' }, new Date('2026-08-11T18:05:00+09:00')), 'overdue');
    assert.equal(contract.homeworkEffectiveStatus({ status: 'completed', dueAt: '2026-08-01T00:00:00+09:00' }, new Date('2026-08-11T18:05:00+09:00')), 'completed');

    const merged = contract.mergeHomeworkLogRow(
      { book: '기존 교재', vendorMeta: { keep: true }, _ph: { next: '복제 금지' } },
      { book: '수정 교재', this: '10쪽', pct: '', comment: '', next: '', _deleted: false },
      'opaque-a',
    );
    assert.deepEqual(merged.vendorMeta, { keep: true });
    assert.equal(merged.assignmentId, 'opaque-a');
    assert.equal(Object.hasOwn(merged, '_ph'), false);

    const malicious = '<img src=x onerror=globalThis.pwned=1>';
    const fakeValueControl = { value: '', textContent: '', innerHTML: 'sentinel' };
    contract.setHomeworkElementText(fakeValueControl, malicious, { asValue: true });
    assert.equal(fakeValueControl.value, malicious);
    assert.equal(fakeValueControl.innerHTML, 'sentinel');
    assert.equal(globalThis.pwned, undefined);
    const fakeTextNode = { value: '', textContent: '', innerHTML: 'sentinel' };
    contract.setHomeworkElementText(fakeTextNode, malicious);
    assert.equal(fakeTextNode.textContent, malicious);
    assert.equal(fakeTextNode.innerHTML, 'sentinel');

    const initial = storeModule.createInitialDemoStore('2026-06-17T00:00:00+09:00');
    assert.ok(Array.isArray(initial.homeworkAssignments) && initial.homeworkAssignments.length > 0);
    const assignment = initial.homeworkAssignments[0];
    const sid = assignment.sid;
    const date = assignment.sourceLogDate;
    const currentRows = structuredClone(initial.logs[date][sid].homeworkTable);
    assert.equal(currentRows[0].demoUnknownKey, 'unknown-field-preserved');

    const getResult = contract.applyDemoHomeworkRequest({
      method: 'GET', path: '/api/admin/student-homework',
      params: new URLSearchParams({ sid, date }), store: initial,
      now: new Date('2026-06-17T12:00:00+09:00'),
    });
    assert.equal(getResult.status, 200);
    assert.equal(getResult.payload.assignments[0].id, assignment.id);

    const operationId = 'checker-operation-1';
    const changedRows = structuredClone(currentRows);
    changedRows[0].this = '수정된 레거시 범위';
    const body = {
      operationId, date, sid,
      logPatch: {
        entry: { homeworkTable: changedRows, homework: '요약' },
        clearKeys: [], base: { homeworkTable: currentRows },
        baseHomeworkTableExact: currentRows,
      },
      homeworkRows: [{
        rowIndex: 0, sourceRowId: assignment.sourceRowId, assignmentId: assignment.id, expectedRevision: assignment.revision,
        title: malicious, book: changedRows[0].book, scope: '50~55쪽',
        dueAt: '2026-06-18T18:00:00+09:00', status: 'assigned',
      }],
      removedAssignmentIds: [],
    };
    const beforeCount = initial.homeworkAssignments.length;
    const committed = contract.applyDemoHomeworkRequest({
      method: 'POST', path: '/api/admin/student-homework/commit', body, store: initial,
      now: new Date('2026-06-17T12:00:00+09:00'),
    });
    assert.equal(committed.status, 200);
    assert.equal(committed.payload.ok, true);
    assert.equal(committed.payload.entry.homeworkTable[0].demoUnknownKey, 'unknown-field-preserved');
    assert.equal(committed.payload.entry.homeworkTable[0].assignmentId, assignment.id);
    assert.equal(Object.hasOwn(committed.payload.entry.homeworkTable[0], 'sourceRowId'), false);
    assert.equal(Object.hasOwn(committed.payload.entry.homeworkTable[0], 'title'), false);
    assert.equal(Object.hasOwn(committed.payload.entry.homeworkTable[0], 'dueAt'), false);
    assert.equal(initial.homeworkAssignments.length, beforeCount);
    const revision = initial.homeworkAssignments.find(item => item.id === assignment.id).revision;
    const retried = contract.applyDemoHomeworkRequest({
      method: 'POST', path: '/api/admin/student-homework/commit', body, store: initial,
      now: new Date('2026-06-17T12:00:00+09:00'),
    });
    assert.equal(retried.payload.operationId, operationId);
    assert.equal(initial.homeworkAssignments.length, beforeCount);
    assert.equal(initial.homeworkAssignments.find(item => item.id === assignment.id).revision, revision);

    const beforeCancelRows = structuredClone(initial.logs[date][sid].homeworkTable);
    const cancelled = contract.applyDemoHomeworkRequest({
      method: 'POST', path: '/api/admin/student-homework/commit', store: initial,
      now: new Date('2026-06-17T12:00:00+09:00'),
      body: {
        operationId: 'checker-operation-cancel', date, sid,
        logPatch: { entry: { homeworkTable: [] }, clearKeys: ['homework', 'homeworkTable'], base: { homeworkTable: beforeCancelRows }, baseHomeworkTableExact: beforeCancelRows },
        homeworkRows: [], removedAssignmentIds: [assignment.id],
      },
    });
    assert.equal(cancelled.status, 200);
    assert.equal(Array.isArray(cancelled.payload.entry.homeworkTable) ? cancelled.payload.entry.homeworkTable.length : 0, 0);
    assert.equal(initial.homeworkAssignments.find(item => item.id === assignment.id).status, 'cancelled');

    const values = new Map();
    globalThis.sessionStorage = {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: key => values.delete(key),
    };
    storeModule.saveDemoStore(storeModule.createInitialDemoStore('2026-06-17T00:00:00+09:00'));
    let liveFetches = 0;
    const root = {
      location: { origin: 'https://demo.test', pathname: '/demo/rh3123' },
      Response, Request, Headers,
    };
    const originalFetch = async () => { liveFetches += 1; return new Response('live'); };
    const demoFetch = fetchModule.createDemoFetch({ root, originalFetch, now: '2026-06-17T00:00:00+09:00' });
    const primaryGet = await demoFetch('/api/admin/student-homework?sid=' + encodeURIComponent(sid) + '&date=' + date);
    assert.equal(primaryGet.status, 200);
    assert.equal((await primaryGet.json()).ok, true);
    const primaryStore = storeModule.loadDemoStore('2026-06-17T00:00:00+09:00');
    const primaryRows = structuredClone(primaryStore.logs[date][sid].homeworkTable);
    const primaryAssignment = primaryStore.homeworkAssignments.find(item => item.sid === sid && item.sourceLogDate === date);
    const primaryBody = {
      operationId: 'primary-operation', date, sid,
      logPatch: { entry: { homeworkTable: primaryRows }, clearKeys: [], base: { homeworkTable: primaryRows }, baseHomeworkTableExact: primaryRows },
      homeworkRows: [{ rowIndex: 0, sourceRowId: primaryAssignment.sourceRowId, assignmentId: primaryAssignment.id, expectedRevision: primaryAssignment.revision, title: '데모 저장', book: primaryRows[0].book, scope: '1~3쪽', dueAt: null, status: 'assigned' }],
      removedAssignmentIds: [],
    };
    const primaryPost = await demoFetch('/api/admin/student-homework/commit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(primaryBody),
    });
    assert.equal(primaryPost.status, 200);
    assert.equal(liveFetches, 0);
    assert.ok([...values.keys()].every(key => key.startsWith('academy.adminDemo.')));
  `;
}

export async function runChecks() {
  const sources = Object.fromEntries(await Promise.all(
    Object.entries(files).map(async ([key, filename]) => [key, await fs.readFile(filename, 'utf8')]),
  ));
  const passed = [];
  const check = (name, callback) => { callback(); passed.push(name); };

  check('canonical modal probes GET and preserves a strict 404 legacy fallback', () => {
    assert.match(sources.logModal, /fetchCanonicalHomeworkForLog/);
    assert.match(sources.logModal, /\/api\/admin\/student-homework\?/);
    assert.match(sources.logModal, /res\.status\s*===\s*404[\s\S]*mode:\s*['"]legacy['"]/);
    assert.match(sources.logModal, /canonicalHomework\.mode\s*===\s*['"]error['"][\s\S]*throw new Error/);
  });

  check('composite body keeps canonical fields out of the legacy log row', () => {
    for (const field of ['operationId', 'baseHomeworkTableExact', 'homeworkRows', 'sourceRowId', 'removedAssignmentIds']) {
      assert.match(sources.logModal, new RegExp(field));
    }
    assert.match(sources.logModal, /mergeHomeworkLogRow\(item\.__homeworkOriginalRow/);
    assert.match(sources.logModal, /assignmentId:/);
    assert.doesNotMatch(sources.logModal.match(/const row = mergeHomeworkLogRow\([\s\S]*?\n\s*\}, assignmentId\);/)?.[0] || '', /title|scope|dueAt|status/);
  });

  check('canonical controls use safe DOM properties and explicit KST conversion', () => {
    const editorSource = sources.logModal.slice(
      sources.logModal.indexOf('function appendCanonicalHomeworkEditor'),
      sources.logModal.indexOf('function renderHwTable'),
    );
    assert.ok(editorSource.length > 200);
    assert.doesNotMatch(editorSource, /innerHTML|insertAdjacentHTML/);
    assert.match(editorSource, /setHomeworkElementText/);
    assert.match(sources.logModal, /homeworkLocalDateTimeToKst/);
    assert.match(sources.contract, /:00\+09:00/);
    for (const className of ['hwTitle', 'hwScope', 'hwDueAt', 'hwStatus', 'hwOverdueBadge']) {
      assert.match(editorSource, new RegExp(className));
    }
    assert.match(editorSource, /기한 없음 — 알림 제외/);
  });

  check('409 semantics retain partial retries and block continuation until success', () => {
    assert.match(sources.logModal, /data\?\.code\s*===\s*['"]partial_failure['"]/);
    assert.match(sources.logModal, /canonicalHomework\.pendingPayload\s*=\s*requestPayload/);
    assert.match(sources.logModal, /canonicalHomework\.pendingPayload\s*=\s*canonicalHomework\.pendingPayload \|\| payload/);
    assert.match(sources.logModal, /const requestPayload = canonicalHomework\.pendingPayload/);
    assert.match(sources.logModal, /canonicalHomework\.mode\s*=\s*['"]conflict['"]/);
    const saveHandler = sources.logModal.slice(sources.logModal.indexOf("logSave.addEventListener"));
    assert.ok(saveHandler.indexOf('await saveRecordPopupForCurrent()') >= 0);
    assert.ok(saveHandler.indexOf('await saveRecordPopupForCurrent()') < saveHandler.indexOf('toast('));
    assert.ok(saveHandler.indexOf('await saveRecordPopupForCurrent()') < saveHandler.indexOf('close()'));
  });

  check('save-and-close persists every unified student popup before closing', () => {
    const start = sources.logModal.indexOf('async function saveAllStudentPopupChangesAndClose()');
    const end = sources.logModal.indexOf("logSave.addEventListener", start);
    const saveAllHandler = sources.logModal.slice(start, end);
    assert.ok(start >= 0 && end > start);
    const videoSave = saveAllHandler.indexOf('await window.saveVideoAssignmentPopup');
    const testSave = saveAllHandler.indexOf('await window.saveTestAssignmentPopup');
    const recordSave = saveAllHandler.indexOf('await saveRecordPopupForCurrent()');
    const carriedTestReapply = saveAllHandler.indexOf('await reapplyCarriedTestAssignmentForCurrent()');
    const close = saveAllHandler.indexOf('close()');
    assert.ok(videoSave >= 0 && testSave >= 0 && recordSave >= 0 && carriedTestReapply >= 0 && close >= 0);
    assert.ok(videoSave < close);
    assert.ok(testSave < close);
    assert.ok(recordSave < close);
    assert.ok(recordSave < carriedTestReapply);
    assert.ok(carriedTestReapply < testSave);
    assert.match(saveAllHandler, /모든 팝업 변경사항 저장에 실패했습니다\. 팝업을 닫지 않았습니다\./);
  });

  check('record save preserves the dated video assignment snapshot', () => {
    const start = sources.logModal.indexOf('async function saveBase(doneFlag)');
    const end = sources.logModal.indexOf('async function saveRecordPopupForCurrent()', start);
    const saveBase = sources.logModal.slice(start, end);
    assert.ok(start >= 0 && end > start);
    assert.doesNotMatch(saveBase, /\/api\/updates\/patch/);
    assert.doesNotMatch(saveBase, /allProgressDone|clearVideoAssignmentForDateSid/);
  });

  check('all-students read-only mode disables canonical editing', () => {
    assert.match(sources.logModal, /#hwBody input, #hwBody select/);
    assert.match(sources.logModal, /input\.disabled = readOnly \|\| retryLocked/);
    assert.match(sources.logModal, /control\.disabled = readOnly/);
  });

  check('390px and 820px source layouts are single- and two-column without narrow controls', () => {
    assert.match(sources.css, /#logModal \.hwCanonicalGrid\s*\{[\s\S]*?repeat\(2, minmax\(0, 1fr\)\)/);
    assert.match(sources.css, /@media \(max-width: 520px\)[\s\S]*?#logModal \.hwCanonicalGrid\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/);
    assert.match(sources.css, /#logModal #hwBody input:not\(\[type="range"\]\)[\s\S]*?min-height:\s*44px/);
    assert.match(sources.css, /#logModal #hwBody \.hw-del-btn\s*\{[\s\S]*?min-width:\s*44px\s*!important[\s\S]*?height:\s*44px\s*!important/);
  });

  check('light homework labels align and the sleep control leaves section spacing', () => {
    assert.match(sources.lightCss, /\.hw-book::before\s*\{[\s\S]*?margin-left:\s*6px\s*!important/);
    assert.match(sources.lightCss, /\.hw-book\s*>\s*\.hw-book-sleep-toggle\s*\{[\s\S]*?margin:\s*4px 0 0\s*!important/);
  });

  check('light progress range has no outer shell and sleeping rows use one full-width surface', () => {
    assert.match(sources.lightCss, /\.hwPctRange\s*\{[\s\S]*?margin:\s*0\s*!important[\s\S]*?padding:\s*0\s*!important[\s\S]*?border:\s*0\s*!important[\s\S]*?background:\s*transparent\s*!important/);
    assert.match(sources.lightCss, /#hwBody \.hwItem\.is-sleeping\s*\{[\s\S]*?width:\s*100%\s*!important[\s\S]*?margin-inline:\s*0\s*!important[\s\S]*?background:\s*#f2f4f7\s*!important/);
    assert.match(sources.lightCss, /input:not\(\[type="range"\]\):disabled[\s\S]*?background-color:\s*transparent\s*!important[\s\S]*?background-image:\s*none\s*!important/);
  });

  check('demo primary and bootstrap fallback share one session-only contract', () => {
    assert.match(sources.demoFetch, /import \{ applyDemoHomeworkRequest \} from ['"]\.\/homeworkContract\.js['"]/);
    assert.match(sources.demoBootstrap, /import \{ applyDemoHomeworkRequest \} from ['"]\.\/homeworkContract\.js['"]/);
    assert.match(sources.demoFetch, /applyDemoHomeworkRequest\([\s\S]*?saveDemoStore/);
    assert.match(sources.demoBootstrap, /applyDemoHomeworkRequest\([\s\S]*?saveDemoStore/);
    assert.match(sources.demoStore, /globalThis\?\.sessionStorage/);
    assert.doesNotMatch(sources.contract, /fetch\s*\(|XMLHttpRequest|localStorage/);
  });

  check('demo fixtures validate canonical homework state', () => {
    assert.match(sources.demoData, /homeworkAssignments/);
    assert.match(sources.demoData, /homeworkOperations:\s*\{\}/);
    assert.match(sources.demoData, /assignmentId\s*=\s*id/);
    assert.match(sources.demoStore, /Array\.isArray\(store\.homeworkAssignments\)/);
    assert.match(sources.demoStore, /store\.homeworkOperations/);
  });

  check('pure contract, fake DOM, idempotency and primary demo flow pass', () => {
    const moduleMode = Number(process.versions.node.split('.')[0]) < 24
      ? ['--experimental-default-type=module']
      : [];
    const result = spawnSync(process.execPath, [
      ...moduleMode,
      '-e',
      runtimeScript(),
      files.contract,
      files.demoStore,
      files.demoFetch,
    ], { encoding: 'utf8', cwd: root });
    assert.equal(result.status, 0, result.stderr || result.stdout);
  });

  return { suite: 'student-mobile-app-homework-admin', checks: passed.length, checksPassed: passed };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  runChecks().then(
    result => console.log(`student-mobile-app homework-admin: ${result.checks} assertions passed`),
    error => { console.error(error); process.exitCode = 1; },
  );
}
