import assert from 'node:assert/strict';

const clickListeners = [];
const selectedDate = '2026-06-28';
const selectedSid = 'student-cleanup-selected';
const historicalDateA = '2026-06-27';
const historicalSidA = 'student-cleanup-history-a';
const historicalDateB = '2026-06-26';
const historicalSidB = 'student-cleanup-history-b';
const historicalSidNoProgress = 'student-cleanup-no-progress';
const testLabel = '단원평가 / 공수1 / Lv.3 / 1회차 / 테스트 A';
const explicitBlankLabel = '단원평가 / 공수1 / Lv.3 / 2회차 / 테스트 B';

class StubElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.textContent = '';
    this.disabled = false;
    this._listeners = {};
    this._queryRows = [];
    this._attributes = new Map();
  }

  addEventListener(type, handler) {
    this._listeners[type] = handler;
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  remove() {}

  setAttribute(name, value) {
    this._attributes.set(String(name), String(value));
  }

  removeAttribute(name) {
    this._attributes.delete(String(name));
  }

  getAttribute(name) {
    return this._attributes.get(String(name)) ?? null;
  }

  querySelector() {
    return null;
  }

  querySelectorAll(selector) {
    return selector === 'tr[data-sid][data-date]' ? this._queryRows : [];
  }

  closest() {
    return null;
  }
}

function cleanupRow(date, sid, extraDataset = {}) {
  const row = new StubElement('tr');
  row.dataset.date = date;
  row.dataset.sid = sid;
  Object.assign(row.dataset, extraDataset);
  row.closest = selector => (selector === 'tr[data-sid]' ? row : null);
  return row;
}

const todayHost = new StubElement('div');
const doneHost = new StubElement('div');
const clearAllButton = new StubElement('button');
clearAllButton.textContent = '기록 정리';
let todayRows = [];
let refreshEvents = 0;

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
  dispatchEvent(event) {
    if (event?.type === 'admin:refresh') refreshEvents += 1;
  },
  createElement(tagName) {
    return new StubElement(tagName);
  },
  getElementById(id) {
    if (id === 'todayWrap') return todayHost;
    if (id === 'doneWrap') return doneHost;
    if (id === 'clearAllBtn') return clearAllButton;
    return null;
  },
  querySelector() {
    return null;
  },
  querySelectorAll(selector) {
    return selector === '#todayWrap tr[data-sid]' ? todayRows : [];
  },
};
globalThis.CustomEvent = function CustomEvent(type, init = {}) {
  return { type, ...init };
};
globalThis.sessionStorage = {
  getItem() { return selectedDate; },
  setItem() {},
};
globalThis.alert = message => {
  throw new Error(`unexpected alert: ${message}`);
};

const { state } = await import('../static/js/admin/core/state.js');
const {
  bindTodayTableEvents,
  completeAssignedTestsForRecordCleanup,
} = await import('../static/js/admin/features/today.render.js?v=20260824-linked-leave1');

const requestKey = (date, sid) => `${date}\u0000${sid}`;
const authoritativeLogs = new Map();
const authoritativeProgress = new Map();
const logReadKeys = [];
const progressReadKeys = [];
const batchLogReadDates = [];
const batchProgressReadDates = [];
const progressPatchBodies = [];
const logPatchBodies = [];
const batchLogPatchBodies = [];

function okJson(body) {
  const text = JSON.stringify(body);
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => text,
  };
}

function requestParams(path) {
  const url = new URL(path, 'http://local.test');
  return {
    date: String(url.searchParams.get('date') || ''),
    sid: String(url.searchParams.get('sid') || ''),
    sids: String(url.searchParams.get('sids') || '')
      .split(',')
      .map(value => value.trim())
      .filter(Boolean),
  };
}

function mapEntriesForDate(source, date, sids = null) {
  const allowed = Array.isArray(sids) ? new Set(sids.map(String)) : null;
  const day = {};
  for (const [key, entry] of source.entries()) {
    const separator = key.indexOf('\u0000');
    const entryDate = key.slice(0, separator);
    const sid = key.slice(separator + 1);
    if (entryDate !== date || (allowed && !allowed.has(sid))) continue;
    day[sid] = entry;
  }
  return day;
}

globalThis.fetch = async (url, init = {}) => {
  const path = String(url);
  if (path.startsWith('/api/logs/entry?')) {
    const target = requestParams(path);
    const key = requestKey(target.date, target.sid);
    logReadKeys.push(key);
    return okJson({ ok: true, entry: authoritativeLogs.get(key) });
  }

  if (path.startsWith('/api/logs?')) {
    const target = requestParams(path);
    batchLogReadDates.push(target.date);
    return okJson({ [target.date]: mapEntriesForDate(authoritativeLogs, target.date) });
  }

  if (path.startsWith('/api/progress?')) {
    const target = requestParams(path);
    if (target.sids.length) {
      batchProgressReadDates.push(target.date);
      return okJson({
        [target.date]: mapEntriesForDate(authoritativeProgress, target.date, target.sids),
      });
    }

    const key = requestKey(target.date, target.sid);
    progressReadKeys.push(key);
    const day = authoritativeProgress.has(key)
      ? { [target.sid]: authoritativeProgress.get(key) }
      : {};
    return okJson({ [target.date]: day });
  }

  if (path === '/api/progress/patch') {
    const body = JSON.parse(String(init.body || '{}'));
    progressPatchBodies.push(body);
    const key = requestKey(body.date, body.sid);
    const current = authoritativeProgress.get(key) || {};
    const merged = {
      ...current,
      ...(body.progress || {}),
      tests: {
        ...(current.tests || {}),
        ...(body.progress?.tests || {}),
      },
    };
    authoritativeProgress.set(key, merged);
    return okJson({ ok: true, progress: merged });
  }

  if (path === '/api/logs/patch') {
    const body = JSON.parse(String(init.body || '{}'));
    logPatchBodies.push(body);
    return okJson({ ok: true, entry: body.entry || {} });
  }

  if (path === '/api/logs/patch-batch') {
    const body = JSON.parse(String(init.body || '{}'));
    batchLogPatchBodies.push(body);
    for (const patch of body.patches || []) {
      const key = requestKey(patch.date, patch.sid);
      const current = authoritativeLogs.get(key) || {};
      const merged = { ...current, ...(patch.entry || {}) };
      for (const clearKey of patch.__clear || []) delete merged[String(clearKey)];
      authoritativeLogs.set(key, merged);
    }
    return okJson({ ok: true, count: body.patches?.length || 0 });
  }

  throw new Error(`unexpected fetch: ${path}`);
};

function resetTracking() {
  logReadKeys.length = 0;
  progressReadKeys.length = 0;
  batchLogReadDates.length = 0;
  batchProgressReadDates.length = 0;
  progressPatchBodies.length = 0;
  logPatchBodies.length = 0;
  batchLogPatchBodies.length = 0;
}

state.logs = {
  [selectedDate]: {
    [selectedSid]: {
      done: true,
      archived: false,
      testAssignmentDailyTests: [{ label: explicitBlankLabel, status: 'assigned' }],
    },
  },
};
state.progress = {
  [selectedDate]: {
    [selectedSid]: {
      video_1: 'done',
      tests: {
        [testLabel]: 'done',
      },
    },
  },
};
state.absentByDate = {};
state.absences = {};
state.absentSlotsByDate = {};
window.state = state;
window.progressData = state.progress;
window.logs = state.logs;

authoritativeLogs.set(requestKey(selectedDate, selectedSid), {
  done: true,
  archived: false,
  testAssignmentDailyTests: [{ label: explicitBlankLabel, status: 'assigned' }],
});
authoritativeProgress.set(requestKey(selectedDate, selectedSid), {
  video_1: 'done',
  tests: {
    [testLabel]: 'assigned',
    [explicitBlankLabel]: '',
  },
});

const selectedRow = cleanupRow(selectedDate, selectedSid);
const clearButton = new StubElement('button');
clearButton.closest = selector => {
  if (selector === '.clearDone') return clearButton;
  if (selector === 'tr[data-sid]') return selectedRow;
  return null;
};

const reloadOptions = [];
bindTodayTableEvents(async options => {
  reloadOptions.push(options);
});

assert.equal(clickListeners.length, 1, 'today document click handler must bind once');
await clickListeners[0]({ target: clearButton });

assert.deepEqual(logReadKeys, [requestKey(selectedDate, selectedSid)], 'cleanup must always fetch the latest log');
assert.deepEqual(progressReadKeys, [requestKey(selectedDate, selectedSid)], 'cleanup must always fetch exact latest progress');
assert.equal(progressPatchBodies.length, 1, 'cleanup must patch assigned tests to done');
assert.deepEqual(progressPatchBodies[0].progress, {
  tests: {
    [testLabel]: 'done',
  },
}, 'cleanup must preserve an explicit blank progress key');
assert.equal(logPatchBodies.length, 1, 'individual cleanup must still archive with one log patch');
assert.equal(logPatchBodies[0].entry.archived, true, 'cleanup log patch must archive row');
assert.equal(
  logPatchBodies[0].entry.testAssignmentDailyTests[0].status,
  'done',
  'cleanup must complete assigned log metadata',
);
assert.equal(state.progress[selectedDate][selectedSid].tests[testLabel], 'done', 'local progress cache must become done');
assert.equal(state.progress[selectedDate][selectedSid].tests[explicitBlankLabel], '', 'explicit blank cache value must survive');
assert.equal(reloadOptions.length, 1, 'cleanup must reload today table once');

console.log('record cleanup assigned-test status verifier passed');

resetTracking();
authoritativeLogs.clear();
authoritativeProgress.clear();
state.logs = { [selectedDate]: {} };
state.progress = {};
window.progressData = state.progress;
window.logs = state.logs;

for (const [date, sid] of [
  [historicalDateA, historicalSidA],
  [historicalDateB, historicalSidB],
  [historicalDateA, historicalSidNoProgress],
]) {
  authoritativeLogs.set(requestKey(date, sid), { done: true, archived: false });
}
authoritativeProgress.set(requestKey(historicalDateA, historicalSidA), {
  tests: { [testLabel]: 'assigned' },
});
authoritativeProgress.set(requestKey(historicalDateB, historicalSidB), {
  tests: { [testLabel]: 'assigned' },
});

const historicalRowA = cleanupRow(historicalDateA, historicalSidA);
const historicalRowB = cleanupRow(historicalDateB, historicalSidB);
const historicalRowNoProgress = cleanupRow(historicalDateA, historicalSidNoProgress);
doneHost._queryRows = [historicalRowA, historicalRowA, historicalRowB, historicalRowNoProgress];

const { initClearAll } = await import('../static/js/admin/features/done.js?v=20260821-log-batch1');
initClearAll();

assert.equal(typeof clearAllButton._listeners.click, 'function', 'bulk cleanup click handler must bind');
await clearAllButton._listeners.click();

const historicalPairs = [
  [historicalDateA, historicalSidA],
  [historicalDateB, historicalSidB],
];
assert.deepEqual(
  [...batchLogReadDates].sort(),
  [historicalDateA, historicalDateB].sort(),
  'bulk cleanup must read logs once per rendered date',
);
assert.deepEqual(
  [...batchProgressReadDates].sort(),
  [historicalDateA, historicalDateB].sort(),
  'bulk cleanup must read progress once per rendered date',
);
assert.equal(logReadKeys.length, 0, 'bulk cleanup must avoid per-student full log reads');
assert.equal(progressReadKeys.length, 0, 'bulk cleanup must avoid per-student progress reads');
assert.equal(progressPatchBodies.length, 2, 'bulk cleanup must patch each unique rendered target once');
assert.deepEqual(
  progressPatchBodies.map(body => [body.date, body.sid]).sort(),
  [...historicalPairs].sort(),
  'bulk cleanup must preserve rendered date/sid pairs',
);
assert.equal(logPatchBodies.length, 0, 'bulk cleanup must avoid serial log patch requests');
assert.equal(batchLogPatchBodies.length, 1, 'bulk cleanup must archive all ready rows with one batch request');
assert.equal(batchLogPatchBodies[0].patches.length, 3, 'duplicate rendered rows must be archived once');
assert.ok(batchLogPatchBodies[0].patches.every(patch => patch.entry.archived === true));
assert.equal(state.progress[historicalDateA][historicalSidA].tests[testLabel], 'done');
assert.equal(state.progress[historicalDateB][historicalSidB].tests[testLabel], 'done');
assert.deepEqual(state.progress[historicalDateA][historicalSidNoProgress], {}, 'missing progress must remain an authoritative empty state');
assert.equal(clearAllButton.disabled, false, 'bulk button must be enabled again');
assert.equal(clearAllButton.textContent, '기록 정리', 'bulk button label must be restored');
assert.equal(clearAllButton.getAttribute('aria-busy'), null, 'bulk button busy state must be cleared');
assert.equal(refreshEvents, 1, 'bulk cleanup must refresh the rendered board once');

console.log('bulk rendered-date record cleanup batching verifier passed');

resetTracking();
const homeworkSidA = 'student-homework-leave-a';
const homeworkSidB = 'student-homework-leave-b';
state.logs = {
  [selectedDate]: {
    [homeworkSidA]: { hwChecked: true, archived: true },
    [homeworkSidB]: { hwChecked: false, archived: true },
  },
};
window.logs = state.logs;
const linkedLeaveIdentity = 'person:linked-student|school|grade';
todayRows = [
  cleanupRow(selectedDate, homeworkSidA, {
    hw: '1',
    slotGroup: '2',
    studentIdentity: linkedLeaveIdentity,
  }),
  cleanupRow(selectedDate, homeworkSidB, {
    slotGroup: '2',
    studentIdentity: linkedLeaveIdentity,
  }),
];
const homeworkLeaveButton = new StubElement('button');
homeworkLeaveButton.textContent = '숙검하원';
homeworkLeaveButton.closest = selector => (selector === '#homeworkLeaveBtn' ? homeworkLeaveButton : null);
const reloadCountBeforeHomeworkLeave = reloadOptions.length;
await clickListeners[0]({ target: homeworkLeaveButton });

assert.equal(batchLogPatchBodies.length, 1, '숙검하원 must use one batch log request');
assert.equal(batchLogPatchBodies[0].patches.length, 2, '숙검하원 must include every linked SID when one row is eligible');
assert.ok(batchLogPatchBodies[0].patches.every(patch => patch.entry.done === true));
assert.ok(batchLogPatchBodies[0].patches.every(patch => patch.__clear.includes('archived')));
assert.equal(logPatchBodies.length, 0, '숙검하원 must not write the 10MB log once per student');
assert.equal(state.logs[selectedDate][homeworkSidA].done, true);
assert.equal(state.logs[selectedDate][homeworkSidA].archived, undefined);
assert.equal(state.logs[selectedDate][homeworkSidB].done, true);
assert.equal(homeworkLeaveButton.disabled, false, '숙검하원 button must be enabled again');
assert.equal(homeworkLeaveButton.textContent, '숙검하원', '숙검하원 label must be restored');
assert.equal(homeworkLeaveButton.getAttribute('aria-busy'), null, '숙검하원 busy state must be cleared');
assert.equal(reloadOptions.length, reloadCountBeforeHomeworkLeave + 1, '숙검하원 must render once after batch save');
assert.equal(reloadOptions.at(-1), undefined, '숙검하원 success must avoid a force reload');

console.log('homework leave log batching verifier passed');

resetTracking();
state.logs = {
  [selectedDate]: {
    [homeworkSidA]: { archived: true },
    [homeworkSidB]: { archived: true },
  },
};
window.logs = state.logs;
todayRows = [
  cleanupRow(selectedDate, homeworkSidA, {
    slotGroup: '1',
    studentIdentity: linkedLeaveIdentity,
  }),
  cleanupRow(selectedDate, homeworkSidB, {
    slotGroup: '2',
    studentIdentity: linkedLeaveIdentity,
  }),
];
const linkedLeaveButton = new StubElement('button');
linkedLeaveButton.closest = selector => {
  if (selector === '.markLeave') return linkedLeaveButton;
  if (selector === 'tr[data-sid]') return todayRows[1];
  return null;
};
const reloadCountBeforeLinkedLeave = reloadOptions.length;
const NativeDate = globalThis.Date;
const fixedLeaveTime = new NativeDate(2026, 7, 3, 20, 15, 0, 0).getTime();
globalThis.Date = class FixedDate extends NativeDate {
  constructor(...args) {
    super(...(args.length ? args : [fixedLeaveTime]));
  }

  static now() {
    return fixedLeaveTime;
  }
};
try {
  await clickListeners[0]({ target: linkedLeaveButton });
} finally {
  globalThis.Date = NativeDate;
}

assert.equal(batchLogPatchBodies.length, 1, 'final-slot individual leave must use one batch request');
assert.deepEqual(
  batchLogPatchBodies[0].patches.map(patch => patch.sid).sort(),
  [homeworkSidA, homeworkSidB].sort(),
  'final-slot individual leave must include both linked course SIDs',
);
assert.ok(batchLogPatchBodies[0].patches.every(patch => patch.entry.done === true));
assert.ok(batchLogPatchBodies[0].patches.every(patch => patch.__clear.includes('archived')));
assert.equal(state.logs[selectedDate][homeworkSidA].done, true);
assert.equal(state.logs[selectedDate][homeworkSidB].done, true);
assert.equal(reloadOptions.length, reloadCountBeforeLinkedLeave + 1);
assert.deepEqual(reloadOptions.at(-1), { force: true });

console.log('linked individual leave batching verifier passed');

resetTracking();
const undoneDate = '2026-06-25';
const undoneSid = 'student-remotely-undone';
authoritativeLogs.set(requestKey(undoneDate, undoneSid), { done: false, archived: false });
authoritativeProgress.set(requestKey(undoneDate, undoneSid), { tests: { [testLabel]: 'assigned' } });
await assert.rejects(
  completeAssignedTestsForRecordCleanup(undoneDate, undoneSid),
  /하원이 취소/,
  'a remotely undone row must fail closed',
);
assert.equal(progressReadKeys.length, 0, 'remote undo must stop before progress read');
assert.equal(progressPatchBodies.length, 0, 'remote undo must not patch progress');

resetTracking();
const archivedDate = '2026-06-24';
const archivedSid = 'student-already-archived';
authoritativeLogs.set(requestKey(archivedDate, archivedSid), { done: true, archived: true });
await assert.rejects(
  completeAssignedTestsForRecordCleanup(archivedDate, archivedSid),
  /이미 정리/,
  'an already archived row must fail closed',
);
assert.equal(progressReadKeys.length, 0, 'archived row must stop before progress read');
assert.equal(progressPatchBodies.length, 0, 'archived row must not patch progress');

resetTracking();
const malformedProgressDate = '2026-06-23';
const malformedProgressSid = 'student-malformed-progress';
authoritativeLogs.set(requestKey(malformedProgressDate, malformedProgressSid), { done: true, archived: false });
authoritativeProgress.set(requestKey(malformedProgressDate, malformedProgressSid), null);
await assert.rejects(
  completeAssignedTestsForRecordCleanup(malformedProgressDate, malformedProgressSid),
  /진행 기록/,
  'a malformed exact progress entry must fail closed',
);
assert.equal(progressPatchBodies.length, 0, 'malformed progress must not patch progress');
assert.equal(logPatchBodies.length, 0, 'malformed progress must leave the row unarchived');
assert.equal(batchLogPatchBodies.length, 0, 'malformed progress must not batch archive the row');

console.log('record cleanup latest-read fail-closed verifier passed');
