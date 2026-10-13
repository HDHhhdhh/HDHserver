import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('static/js/admin/features/today.render.js', 'utf8');
const routeSource = fs.readFileSync('routes/api_students.py', 'utf8');

const renderStart = source.indexOf('export function renderToday(');
const renderEnd = source.indexOf('export function renderDone(', renderStart);
assert.ok(renderStart >= 0 && renderEnd > renderStart, 'today renderer must remain independently addressable');
const renderSource = source.slice(renderStart, renderEnd);

const colgroupMatch = renderSource.match(/<colgroup>([\s\S]*?)<\/colgroup>/);
assert.ok(colgroupMatch, 'today renderer must expose a fixed colgroup');
const widths = Array.from(colgroupMatch[1].matchAll(/width:(\d+)px/g), match => Number(match[1]));
assert.deepEqual(
  widths,
  [32, 72, 120, 84, 168, 44, 84, 84, 112, 36, 36, 232, 64, 56],
  'only the new 36px white-review column and the 36px action reduction may change the table widths',
);
assert.equal(widths.reduce((sum, width) => sum + width, 0), 1224, 'today colgroup total must stay unchanged');
assert.match(renderSource, /<th>진도<\/th>\s*<th>백지<\/th>\s*<th>작업<\/th>\s*<th>보강<\/th>\s*<th>문서<\/th>/);
assert.match(renderSource, /renderWhiteReviewPendingCell\(s.id, s.name, whiteReviewPending\)/);
assert.match(source, /class="whiteReviewPendingChk"/);
assert.match(source, /class="c" data-kind="check"/);
const doneEnd = source.indexOf('// --- todayWrap event delegation ---', renderEnd);
assert.ok(doneEnd > renderEnd, 'live done renderer must remain independently addressable');
const doneSource = source.slice(renderEnd, doneEnd);
function assertDoneTableLayout(markup) {
  const group = markup.match(/<colgroup>([\s\S]*?)<\/colgroup>/);
  assert.ok(group, 'live done table must expose a fixed colgroup');
  const widths = Array.from(group[1].matchAll(/width:(\d+)px/g), match => Number(match[1]));
  assert.deepEqual(widths, [104, 72, 64, 120, 84, 112, 36, 232, 56],
    'done table stays 880px; only action space funds the checkbox');
  assert.equal(widths.reduce((sum, width) => sum + width, 0), 880);
  assert.match(markup, /<th>커리큘럼<\/th>\s*<th class="done-white-review-head">백지<\/th>\s*<th>작업<\/th>/);
}
assertDoneTableLayout(doneSource);

const cleanupStart = source.indexOf('const leaveBtn = e.target.closest(\'.markLeave\')');
const cleanupEnd = source.indexOf('const undoBtn = e.target.closest(\'.undoDone\')', cleanupStart);
const recordCleanupEnd = source.indexOf('\n    });', cleanupEnd);
assert.ok(cleanupStart >= 0 && cleanupEnd > cleanupStart && recordCleanupEnd > cleanupEnd);
assert.ok(!source.slice(cleanupStart, recordCleanupEnd).includes('whiteReviewPending'), 'leave and record cleanup must not mutate the SID flag');
assert.match(routeSource, /field in \{WHITE_REVIEW_PENDING_FIELD, GICHUL_OVERLAY_FIELD\} and type\(value\) is not bool/);

class StubElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.textContent = '';
    this.disabled = false;
    this._html = '';
    this._listeners = {};
  }

  set innerHTML(value) { this._html = String(value); }
  get innerHTML() { return this._html; }

  addEventListener(type, handler) {
    (this._listeners[type] ||= []).push(handler);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  querySelector() { return null; }
  querySelectorAll() { return []; }
  contains() { return false; }
  remove() {}
  setAttribute(name, value) { this[name] = String(value); }
  removeAttribute(name) { delete this[name]; }
}

const todayHost = new StubElement('div');
const doneHost = new StubElement('div');
const todayCount = new StubElement('span');
const documentListeners = {};
const alerts = [];
const requests = [];
let refreshCount = 0;
let failNextSave = false;
let holdNextSave = null;
const visibleCheckboxes = [];
const dispatchedEvents = [];

const leaveRequests = [];
const leaveReloadOptions = [];
let holdNextLeave = null;
let leaveReload = null;

globalThis.window = {
  addEventListener() {},
  removeEventListener() {},
  Sortable: null,
  weekendSlots: {},
  open() {},
};
globalThis.document = {
  activeElement: null,
  body: new StubElement('body'),
  head: new StubElement('head'),
  defaultView: null,
  addEventListener(type, handler) {
    (documentListeners[type] ||= []).push(handler);
  },
  dispatchEvent(event) { dispatchedEvents.push(event.type); },
  createElement(tagName) { return new StubElement(tagName); },
  getElementById(id) {
    if (id === 'todayWrap') return todayHost;
    if (id === 'doneWrap') return doneHost;
    if (id === 'todayCount') return todayCount;
    return null;
  },
  querySelector() { return null; },
  querySelectorAll(selector) { return selector === '.whiteReviewPendingChk' ? visibleCheckboxes : []; },
};
globalThis.document.defaultView = globalThis.window;
globalThis.localStorage = {
  getItem() { return null; },
  setItem() {},
  removeItem() {},
};
globalThis.sessionStorage = {
  getItem() { return '2026-08-29'; },
  setItem() {},
};
globalThis.CustomEvent = function CustomEvent(type, init = {}) { return { type, ...init }; };
globalThis.requestAnimationFrame = callback => { callback(); return 1; };
globalThis.cancelAnimationFrame = () => {};
globalThis.alert = message => alerts.push(String(message));
globalThis.fetch = async (url, init = {}) => {
  const path = String(url);
  if (path === '/api/logs/patch-batch') {
    const body = JSON.parse(String(init.body || '{}'));
    leaveRequests.push({ path, method: init.method, body });
    if (holdNextLeave) await holdNextLeave;
    return { ok: true, status: 200, json: async () => ({ ok: true, count: body.patches.length }) };
  }
  if (path !== '/api/update') throw new Error(`unexpected request: ${path}`);
  const body = JSON.parse(String(init.body || '{}'));
  requests.push({ path, method: init.method, body });
  if (holdNextSave) await holdNextSave;
  if (failNextSave) {
    failNextSave = false;
    return { ok: false, status: 503, text: async () => 'injected failure' };
  }
  return { ok: true, status: 200, text: async () => 'OK' };
};

const { state } = await import('../static/js/admin/core/state.js');
const { renderToday, renderDone, bindTodayTableEvents } = await import('../static/js/admin/features/today.render.js?v=white-review-done');

const student = {
  id: 'student-white-review',
  name: '이민용',
  school: '예시고',
  curriculum: '미적분1',
  subCurriculum: 'APEX',
  day1: '토1',
  whiteReviewPending: true,
};
state.students = [student];
state.videos = [];
state.logs = {};
state.progress = {};

renderToday([student], '2026-08-29', false, {});
assert.match(todayHost.innerHTML, /<th>진도<\/th>\s*<th>백지<\/th>\s*<th>작업<\/th>/);
assert.match(todayHost.innerHTML, /class="whiteReviewPendingChk"[^>]*checked/);
assert.match(todayHost.innerHTML, /aria-label="이민용 백지리뷰 검사 대기"/);

bindTodayTableEvents(async (options = {}) => {
  refreshCount += 1;
  if (leaveReload) {
    leaveReloadOptions.push(options);
    await leaveReload();
  }
});
const changeHandler = todayHost._listeners.change?.[0];
assert.equal(typeof changeHandler, 'function', 'today table must bind one delegated change handler');

const row = {
  dataset: { sid: student.id, date: '2026-08-29', whiteReviewPending: '1' },
  querySelector() { return null; },
};
const pill = { dataset: { on: '1' } };
function checkbox(checked) {
  const input = {
    checked,
    disabled: false,
    isConnected: true,
    closest(selector) {
      if (selector === '.whiteReviewPendingChk') return input;
      if (selector === '.c') return pill;
      if (selector === 'tr[data-sid]') return row;
      return null;
    },
  };
  return input;
}

const clearInput = checkbox(false);
await changeHandler({ target: clearInput });
assert.deepEqual(requests.at(-1), {
  path: '/api/update',
  method: 'POST',
  body: { id: student.id, field: 'whiteReviewPending', value: false },
});
assert.equal(student.whiteReviewPending, false);
assert.equal(row.dataset.whiteReviewPending, '');
assert.equal(pill.dataset.on, '0');
assert.equal(clearInput.disabled, false);

const checkInput = checkbox(true);
await changeHandler({ target: checkInput });
assert.equal(requests.at(-1).body.value, true);
assert.equal(student.whiteReviewPending, true);
renderToday([student], '2026-08-30', false, {});
assert.match(todayHost.innerHTML, /class="whiteReviewPendingChk"[^>]*checked/, 'a later selected date must render the same SID flag');

failNextSave = true;
const failedClearInput = checkbox(false);
const originalConsoleError = console.error;
const capturedConsoleErrors = [];
console.error = (...args) => capturedConsoleErrors.push(args);
try {
  await changeHandler({ target: failedClearInput });
} finally {
  console.error = originalConsoleError;
}
assert.equal(student.whiteReviewPending, true, 'a failed save must restore the roster state');
assert.equal(failedClearInput.checked, true, 'a failed save must restore the checkbox');
assert.equal(row.dataset.whiteReviewPending, '1');
assert.equal(pill.dataset.on, '1');
assert.equal(refreshCount, 1, 'a failed save must request one authoritative rerender');
assert.deepEqual(alerts, ['백지리뷰 검사 대기 저장 실패']);
assert.equal(capturedConsoleErrors.length, 1, 'the failed request must remain diagnosable in the console');

renderDone([[student.id, { done: true }, '2026-08-29'], [student.id, { done: true }, '2026-08-28']]);
assertDoneTableLayout(doneHost.innerHTML);
assert.equal((doneHost.innerHTML.match(/class="whiteReviewPendingChk"[^>]*checked/g) || []).length, 2,
  'all historical done rows read the current SID flag, not the log date');
assert.match(doneHost.innerHTML, /aria-label="이민용 백지리뷰 검사 대기"/);
const doneChange = doneHost._listeners.change?.[0];
assert.equal(typeof doneChange, 'function');
renderDone([[student.id, { done: true }, '2026-08-29']]);
assert.equal(doneHost._listeners.change.length, 1, 'rerenders must not duplicate save listeners');

const duplicate = checkbox(true);
const otherRow = { dataset: { sid: 'other-student', date: '2026-08-28' } };
const otherInput = { checked: true, closest: selector => selector === 'tr[data-sid]' ? otherRow : null };
visibleCheckboxes.push(duplicate, otherInput);
const doneClear = checkbox(false);
await doneChange({ target: doneClear });
assert.deepEqual(requests.at(-1).body, { id: student.id, field: 'whiteReviewPending', value: false });
assert.equal(student.whiteReviewPending, false);
assert.equal(duplicate.checked, false, 'one done row updates every visible copy of the same SID');
assert.equal(otherInput.checked, true, 'other SIDs must remain untouched');

let releaseSave;
holdNextSave = new Promise(resolve => { releaseSave = resolve; });
const doneCheck = checkbox(true);
const saving = doneChange({ target: doneCheck });
assert.equal(doneCheck.disabled, true);
assert.equal(duplicate.disabled, true, 'all copies are locked while one SID saves');
const requestCount = requests.length;
await changeHandler({ target: checkbox(false) });
assert.equal(requests.length, requestCount, 'same SID cannot race through a different row or table');
renderDone([[student.id, { done: true }, '2026-08-28']]);
assert.match(doneHost.innerHTML, /class="whiteReviewPendingChk"[^>]*checked[^>]*disabled/,
  'a rerender during save must remain locked');
releaseSave();
await saving;
holdNextSave = null;
assert.equal(duplicate.disabled, false);
assert.equal(duplicate.checked, true);
renderToday([student], '2026-09-01', false, {});
assert.match(todayHost.innerHTML, /class="whiteReviewPendingChk"[^>]*checked/,
  'a flag set after leaving remains checked on the next attendance date');

failNextSave = true;
console.error = (...args) => capturedConsoleErrors.push(args);
try { await doneChange({ target: checkbox(false) }); }
finally { console.error = originalConsoleError; }
assert.equal(student.whiteReviewPending, true);
assert.equal(duplicate.checked, true, 'failed done save rolls back every copy');
assert.equal(duplicate.disabled, false);
assert.equal(dispatchedEvents.filter(type => type === 'admin:refresh').length, 1);
await doneChange({ target: checkbox(false) });
renderToday([student], '2026-09-02', false, {});
assert.doesNotMatch(todayHost.innerHTML, /class="whiteReviewPendingChk"[^>]*checked/,
  'explicit uncheck in done list persists on subsequent dates');
renderDone([['removed-student', { done: true }, '2026-08-28']]);
assert.match(doneHost.innerHTML, /class="whiteReviewPendingChk"[^>]*disabled/,
  'a historical row with no current student cannot issue a student update');

// Execute the real delegated leave path; this never calls a dead mover or a source marker.
student.whiteReviewPending = true;
state.logs = { '2026-08-29': { [student.id]: { done: false, archived: true, notes: '보존 메모', unknown: { keep: 7 } } } };
renderToday([student], '2026-08-29', false, {});
renderDone([[student.id, { done: true }, '2026-08-28']]);
assertDoneTableLayout(doneHost.innerHTML);
const doneBeforeLeave = doneHost.innerHTML;
const leaveLabel = { textContent: '', dataset: {} };
const leaveRow = {
  dataset: { sid: student.id, date: '2026-08-29', slotGroup: '1', whiteReviewPending: '1' },
  querySelector(selector) { return selector === '.leaveLabel' ? leaveLabel : null; },
  remove() { assert.fail('leave must not manually move/remove the today row before authoritative reload'); },
};
const leaveButton = {
  closest(selector) {
    if (selector === '.markLeave') return leaveButton;
    if (selector === 'tr[data-sid]') return leaveRow;
    return null;
  },
};
leaveReload = async () => {
  const entry = state.logs['2026-08-29'][student.id];
  assert.equal(entry.done, true);
  assert.equal(entry.archived, undefined, 'leave clears archived but preserves unrelated fields');
  assert.equal(entry.notes, '보존 메모');
  assert.deepEqual(entry.unknown, { keep: 7 });
  renderToday([], '2026-08-29', false, {});
  renderDone([[student.id, entry, '2026-08-29']]);
};
let releaseLeave;
holdNextLeave = new Promise(resolve => { releaseLeave = resolve; });
const clickHandler = documentListeners.click?.[0];
assert.equal(typeof clickHandler, 'function', 'real delegated leave click must remain wired');
const leaveSave = clickHandler({ target: leaveButton });
assert.equal(leaveRequests.length, 1);
assert.equal(leaveReloadOptions.length, 0, 'reload waits for the batch save to finish');
assert.equal(doneHost.innerHTML, doneBeforeLeave, 'pending leave cannot preemptively build a done row');
assert.equal(student.whiteReviewPending, true);
releaseLeave();
await leaveSave;
holdNextLeave = null;
leaveReload = null;
assert.deepEqual(leaveReloadOptions, [{ force: true }], 'one persisted leave produces one authoritative reload');
assert.equal(leaveRequests[0].path, '/api/logs/patch-batch');
assert.equal(leaveRequests[0].method, 'POST');
assert.equal(leaveRequests[0].body.patches.length, 1);
const leavePatch = leaveRequests[0].body.patches[0];
assert.deepEqual({ date: leavePatch.date, sid: leavePatch.sid, __clear: leavePatch.__clear },
  { date: '2026-08-29', sid: 'student-white-review', __clear: ['archived'] });
assert.deepEqual(Object.keys(leavePatch.entry).sort(), ['done', 'leaveAt', 'leaveTime']);
assert.equal(leavePatch.entry.done, true);
assert.match(leavePatch.entry.leaveTime, /^\d{2}:\d{2}$/);
assert.match(leavePatch.entry.leaveAt, /^\d{4}-\d{2}-\d{2}T/);
assert.equal(student.whiteReviewPending, true, 'leave never clears the current SID flag');
assertDoneTableLayout(doneHost.innerHTML);
assert.match(doneHost.innerHTML, /data-sid="student-white-review" data-date="2026-08-29"/);
assert.equal((doneHost.innerHTML.match(/class="whiteReviewPendingChk"[^>]*checked/g) || []).length, 1);
assert.match(doneHost.innerHTML, /aria-label="이민용 백지리뷰 검사 대기"/);
assert.match(todayHost.innerHTML, /오늘 학생 없음/);
renderToday([student], '2026-09-03', false, {});
assert.match(todayHost.innerHTML, /class="whiteReviewPendingChk"[^>]*checked/,
  'leave followed by reload preserves the same SID flag on a later attendance date');

console.log('admin white-review pending checks passed: today/done transport, rollback, SID synchronization, in-flight deduplication, next-attendance persistence, width invariants and real leave/save/reload');
