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
assert.match(renderSource, /class="whiteReviewPendingChk"/);
assert.match(renderSource, /class="c" data-kind="check"/);

const cleanupStart = source.indexOf('const leaveBtn = e.target.closest(\'.markLeave\')');
const cleanupEnd = source.indexOf('const undoBtn = e.target.closest(\'.undoDone\')', cleanupStart);
const recordCleanupEnd = source.indexOf('\n    });', cleanupEnd);
assert.ok(cleanupStart >= 0 && cleanupEnd > cleanupStart && recordCleanupEnd > cleanupEnd);
assert.ok(!source.slice(cleanupStart, recordCleanupEnd).includes('whiteReviewPending'), 'leave and record cleanup must not mutate the SID flag');
assert.match(routeSource, /field == WHITE_REVIEW_PENDING_FIELD and type\(value\) is not bool/);

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
  dispatchEvent() {},
  createElement(tagName) { return new StubElement(tagName); },
  getElementById(id) {
    if (id === 'todayWrap') return todayHost;
    if (id === 'doneWrap') return doneHost;
    if (id === 'todayCount') return todayCount;
    return null;
  },
  querySelector() { return null; },
  querySelectorAll() { return []; },
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
  if (path !== '/api/update') throw new Error(`unexpected request: ${path}`);
  const body = JSON.parse(String(init.body || '{}'));
  requests.push({ path, method: init.method, body });
  if (failNextSave) {
    failNextSave = false;
    return { ok: false, status: 503, text: async () => 'injected failure' };
  }
  return { ok: true, status: 200, text: async () => 'OK' };
};

const { state } = await import('../static/js/admin/core/state.js');
const { renderToday, bindTodayTableEvents } = await import('../static/js/admin/features/today.render.js?v=white-review-pending1');

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

bindTodayTableEvents(async () => { refreshCount += 1; });
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

console.log('admin white-review pending checks passed: exact transport, rollback, date persistence, DOM order, and width invariants');
