import assert from 'node:assert/strict';

const clickListeners = [];
const date = '2026-06-28';
const sid = 'student-cleanup-1';
const testLabel = '단원평가 / 공수1 / Lv.3 / 1회차 / 테스트 A';

class StubElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.textContent = '';
    this._listeners = {};
  }

  addEventListener(type, handler) {
    this._listeners[type] = handler;
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  remove() {}

  querySelector() {
    return null;
  }

  querySelectorAll() {
    return [];
  }

  closest() {
    return null;
  }
}

const todayHost = new StubElement('div');
const clearAllButton = new StubElement('button');

globalThis.window = {
  addEventListener() {},
  Sortable: null,
  weekendSlots: {},
  recalcCalendarCounts: null,
  open() {},
};
globalThis.document = {
  _todayDocClickBound: false,
  activeElement: null,
  body: new StubElement('body'),
  head: new StubElement('head'),
  addEventListener(type, handler) {
    if (type === 'click') clickListeners.push(handler);
  },
  dispatchEvent() {},
  createElement(tagName) {
    return new StubElement(tagName);
  },
  getElementById(id) {
    if (id === 'todayWrap') return todayHost;
    if (id === 'clearAllBtn') return clearAllButton;
    return null;
  },
  querySelector() {
    return null;
  },
  querySelectorAll() {
    return [];
  },
};
globalThis.CustomEvent = function CustomEvent(type, init = {}) {
  return { type, ...init };
};
globalThis.sessionStorage = {
  getItem() { return date; },
  setItem() {},
};
globalThis.alert = (message) => {
  throw new Error(`unexpected alert: ${message}`);
};

const { state } = await import('../static/js/admin/core/state.js');
const { bindTodayTableEvents } = await import('../static/js/admin/features/today.render.js');

state.logs = {
  [date]: {
    [sid]: {},
  },
};
state.progress = {
  [date]: {
    [sid]: {
      video_1: 'done',
    },
  },
};
state.absentByDate = {};
state.absences = {};
state.absentSlotsByDate = {};
window.state = state;
window.progressData = state.progress;
window.logs = state.logs;

const progressPatchBodies = [];
const logPatchBodies = [];
let fetchedAuthoritativeProgress = false;

function okJson(body) {
  const text = JSON.stringify(body);
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => text,
  };
}

globalThis.fetch = async (url, init = {}) => {
  const path = String(url);
  if (path.startsWith('/api/logs/entry?')) {
    return okJson({ ok: true, entry: {} });
  }

  if (path.startsWith('/api/progress?')) {
    fetchedAuthoritativeProgress = true;
    return okJson({
      [date]: {
        [sid]: {
          video_1: 'done',
          tests: {
            [testLabel]: 'assigned',
          },
        },
      },
    });
  }

  if (path === '/api/progress/patch') {
    const body = JSON.parse(String(init.body || '{}'));
    progressPatchBodies.push(body);
    assert.equal(body.date, date);
    assert.equal(body.sid, sid);
    assert.deepEqual(body.progress, {
      tests: {
        [testLabel]: 'done',
      },
    });
    return okJson({
      ok: true,
      progress: {
        video_1: 'done',
        tests: {
          [testLabel]: 'done',
        },
      },
    });
  }

  if (path === '/api/logs/patch') {
    const body = JSON.parse(String(init.body || '{}'));
    logPatchBodies.push(body);
    return okJson({ ok: true, entry: body.entry || {} });
  }

  throw new Error(`unexpected fetch: ${path}`);
};

const row = new StubElement('tr');
row.dataset.sid = sid;
row.dataset.date = date;
row.closest = (selector) => (selector === 'tr[data-sid]' ? row : null);

const clearButton = new StubElement('button');
clearButton.closest = (selector) => {
  if (selector === '.clearDone') return clearButton;
  if (selector === 'tr[data-sid]') return row;
  return null;
};

let reloads = 0;
bindTodayTableEvents(async () => {
  reloads += 1;
});

assert.equal(clickListeners.length, 1, 'today document click handler must bind once');
await clickListeners[0]({ target: clearButton });

assert.equal(fetchedAuthoritativeProgress, true, 'cleanup must fetch progress when local entry has no tests');
assert.equal(progressPatchBodies.length, 1, 'cleanup must patch assigned tests to done');
assert.equal(logPatchBodies.length, 1, 'cleanup must still archive the log row');
assert.equal(logPatchBodies[0].entry.archived, true, 'cleanup log patch must archive row');
assert.equal(state.progress[date][sid].tests[testLabel], 'done', 'local progress cache must become done');
assert.equal(reloads, 1, 'cleanup must reload today table once');

console.log('record cleanup assigned-test status verifier passed');

state.logs = {
  [date]: {
    [sid]: {
      done: true,
      archived: false,
    },
  },
};
state.progress = {
  [date]: {
    [sid]: {
      video_1: 'done',
    },
  },
};
window.progressData = state.progress;
window.logs = state.logs;
fetchedAuthoritativeProgress = false;
progressPatchBodies.length = 0;
logPatchBodies.length = 0;

const { initClearAll } = await import('../static/js/admin/features/done.js');
initClearAll();

assert.equal(typeof clearAllButton._listeners.click, 'function', 'bulk cleanup click handler must bind');
await clearAllButton._listeners.click();

assert.equal(fetchedAuthoritativeProgress, true, 'bulk cleanup must fetch progress when local entry has no tests');
assert.equal(progressPatchBodies.length, 1, 'bulk cleanup must patch assigned tests to done');
assert.equal(logPatchBodies.length, 1, 'bulk cleanup must still archive the log row');
assert.equal(logPatchBodies[0].entry.archived, true, 'bulk cleanup log patch must archive row');
assert.equal(state.progress[date][sid].tests[testLabel], 'done', 'bulk cleanup local progress cache must become done');

console.log('bulk record cleanup assigned-test status verifier passed');
