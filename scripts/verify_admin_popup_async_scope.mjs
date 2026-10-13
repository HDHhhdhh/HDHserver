import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : fallback;
};
const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = option('--source-root', repositoryRoot);
const expectation = option('--expect', 'guarded'); // observe | vulnerable | guarded
assert.ok(['observe', 'vulnerable', 'guarded'].includes(expectation));
const A_DATE = '2026-10-01';
const B_DATE = '2026-10-02';
const read = relative => fs.readFileSync(path.join(sourceRoot, relative), 'utf8')
  .replace(/^import\s[\s\S]*?;\r?\n/gm, '')
  .replace(/\bexport\s+/g, '');
const clone = value => JSON.parse(JSON.stringify(value));
const deferred = () => {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
};
const response = data => ({
  ok: true, status: 200,
  json: async () => clone(data),
  text: async () => JSON.stringify(data),
  headers: { get: () => 'synthetic-revision' },
});
function classList(initial = '') {
  const classes = new Set(initial.split(/\s+/).filter(Boolean));
  return {
    contains: value => classes.has(value),
    add: (...values) => values.forEach(value => classes.add(value)),
    remove: (...values) => values.forEach(value => classes.delete(value)),
    toggle(value, on) {
      if (on === undefined) on = !classes.has(value);
      if (on) classes.add(value); else classes.delete(value);
      return on;
    },
  };
}
function element(id = '') {
  return {
    id, value: '', textContent: '', innerHTML: '', dataset: {}, style: { display: 'none' },
    disabled: false, hidden: false, isConnected: true, listeners: {},
    classList: classList(), previousElementSibling: null, scrollTop: 0,
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); },
    setAttribute() {}, removeAttribute() {}, focus() {}, prepend() {}, append() {},
    querySelector: () => null, querySelectorAll: () => [],
    contains: () => false,
    getBoundingClientRect: () => ({width:100,height:100}),
  };
}
function documentFor(ids) {
  const body = element('body'), events = element('document');
  return {
    body, events, activeElement: null,
    getElementById: id => ids.get(id) || null,
    querySelector: selector => ids.get(selector.replace(/^#/, '')) || null,
    querySelectorAll: selector => {
      const direct = ids.get(selector.replace(/^#/, ''));
      return direct ? [direct] : [];
    },
    addEventListener: events.addEventListener.bind(events),
    dispatchEvent() {}, createElement: () => element(),
  };
}
const silentConsole = { log() {}, warn() {}, error() {} };
const currentLogTarget = context => vm.runInContext(
  '({sid: editingLogSid, date: editingLogDate})', context,
);

function logHarness() {
  const ids = new Map(['logModal', 'logNotes', 'logSave', 'logCompleteBtn', 'logProgress',
    'hwBody', 'hwWrap', 'mSave', 'testSave'].map(id => [id, element(id)]));
  const document = documentFor(ids), writes = [], feedback = [], opening = [];
  const progressGate = deferred(), videoGate = deferred(), videoEntered = deferred();
  let holdProgress = false, holdVideo = false, homeworkRows = [], progressCells = [];
  let videoTarget = { sid: 'A', date: A_DATE }, testTarget = { sid: 'A', date: A_DATE };
  const state = {
    students: [{id: 'A', name: 'A', curriculum: '대수'}, {id: 'B', name: 'B', curriculum: '공수1'}],
    videos: [], progress: {},
    logs: { [A_DATE]: { A: { notes: '', homeworkTable: [] } }, [B_DATE]: { B: { notes: '', homeworkTable: [] } } },
  };
  const window = {
    setTimeout, clearTimeout,
    showStudentPopupBackdrop() {}, hideStudentPopupBackdrop() {},
    showStudentTooltipForSid() {}, hideStudentTooltip() {},
    showStudentPopupSaveResult: text => feedback.push(text),
    openVideoAssignmentPopupForRow: async row => {
      videoTarget = { sid: row.dataset.sid, date: row.dataset.date };
      opening.push({step: 'video-open', ...videoTarget});
    },
    openTestAssignmentPopupForRow: async row => {
      testTarget = { sid: row.dataset.sid, date: row.dataset.date };
      opening.push({step: 'test-open', ...testTarget});
    },
    closeVideoAssignmentPopup() {}, closeTestAssignmentPopup() {},
    saveVideoAssignmentPopup: async () => {
      const frozen = {...videoTarget};
      writes.push({step: 'video', ...frozen});
      videoEntered.resolve();
      if (holdVideo) await videoGate.promise;
    },
    saveTestAssignmentPopup: async () => writes.push({step: 'test', ...testTarget}),
  };
  const originalQueryAll = document.querySelectorAll;
  document.querySelectorAll = selector => selector === '#logProgress .progress-cell'
    ? progressCells : originalQueryAll(selector);
  const context = vm.createContext({
    $, state, window, document, console: silentConsole,
    getAdminDate: () => A_DATE, toast: text => feedback.push(text), postJSON() {},
    classifySaveConflict: () => ({}), initTestModal() {},
    placeSleepingHomeworkRowsLast: rows => rows, previousHomeworkText: () => '',
    projectBlankHomeworkCheckCarryover: () => ({}),
    alert: text => feedback.push('alert:' + text),
    requestAnimationFrame: callback => callback(), setTimeout, clearTimeout,
    CustomEvent: function(type, init) { this.type = type; this.detail = init?.detail; },
  });
  function $(id) { return ids.get(String(id).replace(/^#/, '')) || null; }
  vm.runInContext(read('static/js/admin/features/logModal.js'), context);
  // Keep the real entrypoint, open/close/save/session functions, patch builder and ordering.
  // Stub only dependencies that would fetch or require an actual browser renderer.
  Object.assign(context, {
    __readHomework: () => homeworkRows,
    __patchProgress: async (date, sid, progress) => {
      writes.push({step: 'progress', date, sid, progress: clone(progress)});
      if (holdProgress) await progressGate.promise;
      return clone(progress);
    },
    __patchLog: async (date, sid, entry, clearKeys, options) => {
      writes.push({step: 'log', date, sid, entry: clone(entry), base: clone(options?.base || {})});
      return clone(entry);
    },
  });
  vm.runInContext([
    'ensureModal=()=>{}; initTestModal=()=>{};',
    'parkHomeworkWorkspace=mountAssistantThread=mountHomeworkInTooltip=renderHwTable=syncHomeworkRemovalControls=()=>{};',
    'hydrateLogHistoryForSid=hydrateProgressHistoryForSid=async()=>true;',
    'fetchCanonicalHomeworkForLogCached=async()=>({mode:"legacy"});',
    'projectHomeworkRowsFromLogState=(date,sid)=>({logEntry:state.logs[date]?.[sid]||{},todayRows:[],sleepingHomeworkBooks:[],mergedRows:[]});',
    'configuredHomeworkBookRows=()=>[];',
    'collectHwTable=()=>__readHomework(); collectSleepingHomeworkBooks=()=>[];',
    'findAbsentTestCarryoverForLog=(date,sid)=>sid==="B"?({sourceDate:"2026-09-29",items:[{label:"B test",status:"assigned"}]}):null;',
    'patchProgressEntry=__patchProgress; patchLogEntry=__patchLog;',
    'fetchLatestCarriedTestLogEntry=async(date,sid)=>state.logs[date]?.[sid]||{};',
    'invalidateLogModalHydrationCaches=()=>{};',
    'initLogModal();',
  ].join('\n'), context);
  return {
    context, ids, writes, feedback, opening, window, progressGate, videoGate, videoEntered,
    setHoldProgress: () => { holdProgress = true; },
    setHoldVideo: () => { holdVideo = true; },
    edit(sid) {
      ids.get('logNotes').value = sid + ' note';
      homeworkRows = [{book: sid + ' book', this: sid + ' homework', pct: '', comment: '', next: ''}];
      progressCells = [{dataset: {mid: sid + '-mid', state: 'interrupted', initial: 'none'}}];
    },
  };
}
const row = (sid, date) => ({ dataset: {sid, date} });

async function runLogSave() {
  const h = logHarness();
  await h.window.openRecordPopupForRow(row('A', A_DATE));
  h.edit('A'); h.setHoldProgress();
  h.ids.get('logSave').listeners.click[0]();
  const saving = vm.runInContext('logRecordActionPromise', h.context);
  assert.ok(saving, 'actual save click must create the real action flight');
  h.window.closeStudentWorkPopups();
  await h.window.openRecordPopupForRow(row('B', B_DATE));
  const remounted = currentLogTarget(h.context).sid === 'B';
  if (remounted) h.edit('B');
  h.progressGate.resolve(); await saving;
  const logWrites = h.writes.filter(write => write.step === 'log');
  assert.equal(logWrites.length, 1, 'actual log save must emit one observed log command');
  const polluted = JSON.stringify(logWrites[0]).includes('B note')
    || JSON.stringify(logWrites[0]).includes('B homework')
    || JSON.stringify(logWrites[0]).includes('B test');
  if (expectation === 'guarded') {
    assert.equal(polluted, false, 'A command may not include B form or carryover data');
    assert.equal(remounted, false, 'save gate must reject changing log targets while pending');
  } else if (expectation === 'vulnerable') assert.equal(polluted, true);
  return {remounted, writes: h.writes};
}
async function runUnifiedSave() {
  const h = logHarness();
  await h.window.openStudentPopupsForRow(row('A', A_DATE));
  h.edit('A'); h.setHoldVideo();
  h.window.closeStudentWorkPopups({detail: {saveAll: true}});
  const saving = vm.runInContext('saveAllStudentPopupPromise', h.context);
  assert.ok(saving, 'actual unified close event must create the real flight');
  await h.videoEntered.promise;
  h.window.closeStudentWorkPopups();
  await h.window.openStudentPopupsForRow(row('B', B_DATE));
  const remounted = currentLogTarget(h.context).sid === 'B';
  if (remounted) h.edit('B');
  h.videoGate.resolve(); await saving;
  const targetWrites = h.writes.filter(write => ['video', 'log', 'test'].includes(write.step));
  assert.ok(targetWrites.some(write => write.step === 'video'), 'video stage must run');
  assert.ok(targetWrites.some(write => write.step === 'log'), 'log stage must run');
  assert.ok(targetWrites.some(write => write.step === 'test'), 'test stage must run');
  if (expectation === 'guarded') {
    assert.ok(targetWrites.every(write => write.sid === 'A' && write.date === A_DATE),
      'an A unified save must issue zero B commands');
    assert.equal(remounted, false);
    assert.equal(h.ids.get('logModal').style.display, 'none', 'internal completed close must be allowed');
  } else if (expectation === 'vulnerable') assert.ok(targetWrites.some(write => write.sid === 'B'));
  return {remounted, writes: h.writes, feedback: h.feedback};
}

// Connect the real test popup to the real unified save/close owner. The existing
// scope fixture keeps renderer dependencies synthetic, while all test reads,
// progress/log commands, readiness and button locks run through testModal.js.
function attachRealTestPopup(h, {failFirstLog = false} = {}) {
  const testIds = ['testAssignmentModalStyles', 'testModal', 'testTitle', 'testStudentMeta',
    'testVisibleCount', 'testCategoryTabs', 'testSubject', 'testDifficulty', 'testTerm',
    'testRound', 'testDifficultyOverride', 'testLevelSettingPanel', 'testLevelSettingCurrent',
    'testLevelSettingOptions', 'testSelectionMeta', 'testAssignList', 'testAppendNotes'];
  for (const id of testIds) h.ids.set(id, element(id));
  const requests = [], saveLocks = [];
  let logFailed = false;
  Object.assign(h.context, {
    CT: {'Content-Type': 'application/json'}, URLSearchParams,
    localStorage: {getItem: () => null, setItem() {}},
    createUnitTestDisplayNameResolver: () => test => test.name,
    fetch: async (url, init = {}) => {
      const method = init.method || 'GET';
      const body = init.body ? JSON.parse(init.body) : null;
      requests.push({url, method, body});
      if (method === 'GET') {
        if (url === '/api/tests-config') return response({categories: {UNIT: {tests: [{
          id: 'unified-test', name: '통합 저장 시험', curriculum: '대수', difficulty: 'Lv.3', round: '1',
        }]}}});
        if (url.startsWith('/api/logs/entry?')) {
          const q = new URLSearchParams(url.split('?')[1]);
          return response({entry: h.context.state.logs[q.get('date')]?.[q.get('sid')] || {}});
        }
        if (url.startsWith('/api/logs?')) return response(h.context.state.logs);
        if (url.startsWith('/api/progress?')) return response(h.context.state.progress);
        if (url === '/api/tests') return response({});
      }
      if (method === 'POST' && url === '/api/progress/patch') {
        h.writes.push({step: 'test-progress', ...clone(body)});
        return response({progress: body.progress});
      }
      if (method === 'POST' && url === '/api/logs/patch') {
        h.writes.push({step: 'test-log', ...clone(body)});
        if (failFirstLog && !logFailed) {
          logFailed = true;
          return {...response({error: 'synthetic log failure'}), ok: false, status: 503};
        }
        return response({entry: {...h.context.state.logs[body.date]?.[body.sid], ...body.entry}});
      }
      throw new Error('Unexpected synthetic test request: ' + method + ' ' + url);
    },
  });
  vm.runInContext('(function(){\n'
    + read('static/js/admin/features/testAssignmentRules.js') + '\n'
    + read('static/js/admin/features/testModal.js') + '\n'
    + 'initTestModal();\n'
    + 'window.qaSetTestStatus = status => {\n'
    + '  const test = activeCatalog.find(item => item.id === "unified-test");\n'
    + '  applyTestRowStatus({dataset:{testKey:test._key},classList:{toggle(){}},querySelector:()=>null}, status);\n'
    + '  testSelectionTouched = true;\n'
    + '  return test._key;\n'
    + '};\n})();', h.context);
  const save = h.window.saveTestAssignmentPopup;
  h.window.saveTestAssignmentPopup = options => {
    saveLocks.push(h.ids.get('testSave').disabled);
    return save(options);
  };
  return {requests, saveLocks};
}

async function runUnifiedRealTestSave({changed = true, failFirstLog = false} = {}) {
  const h = logHarness(), test = attachRealTestPopup(h, {failFirstLog});
  await h.window.openStudentPopupsForRow(row('A', A_DATE));
  assert.equal(h.ids.get('testSave').disabled, false, 'actual test hydration must be ready');
  h.edit('A');
  const key = changed ? h.window.qaSetTestStatus('assigned') : '';
  h.setHoldVideo();
  h.window.closeStudentWorkPopups({detail: {saveAll: true}});
  const saving = vm.runInContext('saveAllStudentPopupPromise', h.context);
  await h.videoEntered.promise;
  h.window.closeStudentWorkPopups({detail: {saveAll: true}});
  h.videoGate.resolve();
  await saving;
  assert.deepEqual(test.saveLocks, [true], 'unified save must retain the test button lock');
  const writes = () => h.writes.filter(write => write.step.startsWith('test-'));
  if (failFirstLog) {
    assert.equal(h.ids.get('logModal').style.display, 'flex', 'failed save keeps edits open');
    assert.ok(h.feedback.some(text => /테스트 상태는 저장됐지만/.test(text)));
    assert.ok(!h.feedback.includes('저장 완료'), 'partial failure cannot announce completion');
    assert.equal(h.ids.get('testSave').disabled, false, 'failure unlocks retry');
    h.window.closeStudentWorkPopups({detail: {saveAll: true}});
    await vm.runInContext('saveAllStudentPopupPromise', h.context);
    assert.deepEqual(test.saveLocks, [true, true]);
  }
  assert.equal(h.ids.get('logModal').style.display, 'none', 'successful unified save closes');
  assert.equal(h.ids.get('testModal').style.display, 'none', 'successful unified save closes tests');
  assert.equal(h.feedback.filter(text => text === '저장 완료').length, 1);
  if (changed) {
    assert.equal(writes().length, failFirstLog ? 4 : 2, 'one progress/log command per attempt');
    assert.ok(writes().every(write => write.sid === 'A' && write.date === A_DATE));
    assert.equal(writes()[0].progress.tests[key], 'assigned');
    assert.equal(writes().at(-1).entry.assignedTests[0].label, key);
    assert.ok(h.writes.findIndex(write => write.step === 'log')
      < h.writes.findIndex(write => write.step === 'test-progress'), 'test assignment saves after records');
    await h.window.openStudentPopupsForRow(row('A', A_DATE));
    assert.equal(h.context.state.progress[A_DATE].A.tests[key], 'assigned', 'saved tests survive reopen');
    h.window.closeStudentWorkPopups();
  } else {
    assert.equal(writes().length, 0, 'unchanged tests close without a test write');
  }
  return {changed, failFirstLog, testWrites: writes().map(write => write.step), saveLocks: test.saveLocks};
}

function selectionHarness(kind) {
  const modal = element(kind === 'extra' ? 'extraModal' : 'absentRegisterModal');
  const zone = element(), button = element(), save1 = element(), save2 = element();
  let html = '';
  zone.rows = [];
  Object.defineProperty(zone, 'innerHTML', {get: () => html, set(value) {
    html = value; zone.rows = [];
    for (const match of value.matchAll(/<div class="row([^"]*)" data-sid="([^"]*)"[\s\S]*?<\/div>/g)) {
      const checkbox = {checked: /class="chk-sid"[^>]*\bchecked\b/.test(match[0])};
      const slots = Array.from(match[0].matchAll(/<button\b[\s\S]*?<\/button>/g), item => ({
        dataset: {n: item[0].match(/data-n="(\d+)"/)?.[1]},
        classList: classList(item[0].match(/class="([^"]*)"/)?.[1] || ''),
      }));
      const item = element(match[2]);
      item.dataset = {sid: match[2], searchKey: match[2]};
      item.classList = classList('row ' + match[1]);
      item.querySelector = selector => selector === '.chk-sid' ? checkbox
        : selector === '.student-name' ? {textContent: match[2]}
        : selector === '.slot-btn.on' ? slots.find(slot => slot.classList.contains('on')) : null;
      item.querySelectorAll = selector => selector === '.slot-btn.on'
        ? slots.filter(slot => slot.classList.contains('on')) : [];
      zone.rows.push(item);
    }
  }});
  modal.querySelectorAll = () => [save1, save2];
  const ids = new Map(kind === 'extra'
    ? [['extraModal', modal], ['exZone', zone], ['extraBtn', button]]
    : [['absentRegisterModal', modal], ['absentZone', zone], ['absentRegisterBtn', button]]);
  const document = documentFor(ids);
  document.querySelectorAll = selector => selector === (kind === 'extra' ? '#exZone .row' : '#absentZone .row')
    ? zone.rows : selector.includes('[id$=') ? [modal] : [];
  return {modal, zone, button, save1, save2, document, $: id => ids.get(String(id).replace(/^#/, '')) || null};
}
async function runSelectionOpen(kind, {closeDuringLoad = false} = {}) {
  const h = selectionHarness(kind), gate = deferred(), saveGate = deferred(), writes = [];
  const holdSave = kind === 'absent' && expectation === 'guarded';
  let selectedDate = A_DATE, extraReads = 0, slotReads = 0, absentReads = 0;
  const students = [{id: 'A', name: 'A', day1: '목1'}, {id: 'B', name: 'B', day1: '금2'}];
  const extras = {[A_DATE]: ['A'], [B_DATE]: ['B']};
  const slots = {[A_DATE]: {A: 1}, [B_DATE]: {B: 2}};
  const emptyAbsence = {by_date: {}, by_student: {}, by_slot: {}};
  const context = vm.createContext({
    $: h.$, state: {students, absentByDate: {}, absences: {}, absentSlotsByDate: {}},
    getAdminDate: () => selectedDate, window: {}, document: h.document, CT: {},
    getComputedStyle: el => ({display:el.style.display,visibility:'visible',opacity:'1',position:'fixed'}),
    console: silentConsole, toast() {}, alert: text => writes.push({alert: text}),
    requestAnimationFrame: callback => callback(), CustomEvent: function() {},
    applySearchPlaceholder() {}, matchesSearchKey: () => true,
    normalizeSearch: value => String(value || ''), studentSearchKey: student => student.id,
    ensureOk: async res => { assert.ok(res.ok); },
    clearTodayOrder: async () => {}, setArriveOverrides() {}, setAttended() {}, setContacted() {},
    saveWeekendSlotsPatch: async (date, map) => writes.push({step: 'slots', date, map: clone(map)}),
    sendJson: async (url, body) => {
      writes.push({step: url, body: clone(body)});
      const dates = body.deltas
        ? Object.fromEntries(Object.entries(body.deltas).map(([date, mapping]) => [date, Object.entries(mapping).filter(([_sid, present]) => present).map(([sid]) => sid)]))
        : { [body.date]: body.sids };
      return response(url === '/api/extra-attend' ? { dates } : {});
    },
    fetch: async (url, init = {}) => {
      if (init.method === 'POST') {
        const body = JSON.parse(init.body);
        writes.push({step: url, body});
        if (holdSave && url === '/api/attendance/patch') await saveGate.promise;
        return response(url === '/api/absent' ? body : {});
      }
      if (url === '/api/extra-attend') {
        if (kind === 'extra' && ++extraReads === 1) await gate.promise;
        return response(kind === 'extra' ? extras : {});
      }
      if (url === '/api/weekend-slots') {
        if (++slotReads === 1) await gate.promise;
        return response(slots);
      }
      if (url === '/api/absent') {
        if (++absentReads === 1) await gate.promise;
        return response(emptyAbsence);
      }
      throw new Error('Unexpected synthetic request: ' + url);
    },
  });
  const source = kind === 'extra'
    ? read('static/js/admin/features/extraAttendanceMerge.js')
      + read('static/js/admin/features/scheduleOverrideSave.js')
      + read('static/js/admin/features/extraModal.js')
      + '\nensure=()=>{}; initExtraModal();'
    : read('static/js/admin/features/absentRegister.js') + '\nensure=()=>{}; initAbsentRegister();';
  const escSource = read('static/js/admin/features/escClose.js');
  vm.runInContext(escSource + '\ninitEscClose();\n' + source, context);
  const older = h.button.listeners.click[0]();
  const escape = () => h.document.events.listeners.keydown.forEach(listener => listener({key:'Escape'}));
  if (closeDuringLoad) {
    escape();
    assert.equal(h.modal.style.display, 'none', 'Escape must close a loading popup');
    gate.resolve(); await older;
    if (expectation === 'guarded') assert.equal(h.modal.style.display, 'none', 'late load must not reopen an Escape-closed popup');
    if (expectation === 'vulnerable') assert.equal(h.modal.style.display, 'flex');
    return {displayAfterLateResponse:h.modal.style.display,writes};
  }
  selectedDate = B_DATE; await h.button.listeners.click[0]();
  const snapshot = () => ({
    date: h.modal.dataset.date,
    ids: h.zone.rows.filter(item => kind === 'absent' || item.querySelector('.chk-sid').checked)
      .map(item => item.dataset.sid),
  });
  const afterB = snapshot();
  assert.deepEqual(afterB.ids, ['B'], 'second opening must have fully rendered B data');
  gate.resolve(); await older;
  const afterLateA = snapshot();
  if (kind === 'absent') h.zone.rows[0].querySelector('.chk-sid').checked = true;
  const selector = kind === 'extra' ? '#extraModal .ex-save' : '#absentRegisterModal .absent-save';
  const event = {target: {closest: candidate => candidate === selector ? h.save1 : null}};
  const save = Promise.all(h.document.body.listeners.click.map(listener => listener(event)));
  if (holdSave) {
    assert.ok(h.save1.disabled && h.save2.disabled, 'both absence save buttons must lock together');
    const beforeDuplicate = writes.length;
    const duplicateEvent = {target:{closest:candidate=>candidate === selector ? h.save2 : null}};
    await Promise.all(h.document.body.listeners.click.map(listener=>listener(duplicateEvent)));
    assert.equal(writes.length, beforeDuplicate, 'second save button must issue zero duplicate requests');
    escape();
    assert.equal(h.modal.style.display,'flex','Escape must respect the pending save owner');
    saveGate.resolve();
  }
  await save;
  if (expectation === 'guarded') {
    assert.deepEqual(afterLateA, afterB, 'late A open must not change the B UI or frozen date');
    if (kind === 'extra') {
      assert.ok(writes.every(write => !write.alert), 'successful extra save must not hide a missing dependency as partial success');
      assert.equal(h.modal.style.display, 'none', 'successful extra save closes its own popup');
      assert.ok(writes.every(write => !write.map?.A && !write.body?.[B_DATE]?.A),
        'saving B must not write A slots or arrival state');
    } else {
      const saved = writes.find(write => write.step === '/api/absent');
      assert.deepEqual(saved.body.by_date[B_DATE], ['B']);
      assert.ok(writes.filter(write => write.body?.sid).every(write => write.body.sid === 'B'));
    }
  } else if (expectation === 'vulnerable') assert.deepEqual(afterLateA.ids, ['A']);
  return {afterB, afterLateA, writes};
}

const report = {
  expectation, sourceRoot,
  logSave: await runLogSave(),
  unifiedSave: await runUnifiedSave(),
  unifiedRealTestSave: await runUnifiedRealTestSave(),
  unifiedUnchangedTests: await runUnifiedRealTestSave({changed: false}),
  unifiedTestRetry: await runUnifiedRealTestSave({failFirstLog: true}),
  extraOpen: await runSelectionOpen('extra'),
  absentOpen: await runSelectionOpen('absent'),
  extraEscape: await runSelectionOpen('extra', {closeDuringLoad:true}),
  absentEscape: await runSelectionOpen('absent', {closeDuringLoad:true}),
};
console.log(JSON.stringify(report, null, 2));
console.log('Read-only VM checks finished; source files were read, and all I/O/DOM was synthetic.');
