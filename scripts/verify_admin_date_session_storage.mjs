import assert from 'node:assert/strict';
import fs from 'node:fs';

const STORAGE_KEY = 'adminSelectedDate';
const RealDate = Date;
let assertionCount = 0;

function equal(actual, expected, message) {
  assertionCount += 1;
  assert.equal(actual, expected, message);
}

function deepEqual(actual, expected, message) {
  assertionCount += 1;
  assert.deepEqual(actual, expected, message);
}

class FixedDate extends RealDate {
  constructor(...args) {
    if (args.length === 0) {
      super(2026, 2, 15, 12, 0, 0, 0);
      return;
    }
    super(...args);
  }

  static now() {
    return new RealDate(2026, 2, 15, 12, 0, 0, 0).getTime();
  }
}

class SessionStorageStub {
  constructor(initial = {}) {
    this.values = new Map(Object.entries(initial));
    this.throwOnGet = false;
    this.throwOnSet = false;
    this.getCalls = 0;
    this.setCalls = 0;
  }

  getItem(key) {
    this.getCalls += 1;
    if (this.throwOnGet) throw new Error('get blocked');
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.setCalls += 1;
    if (this.throwOnSet) throw new Error('set blocked');
    this.values.set(key, String(value));
  }
}

class MiniEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    this.listeners.set(type, listeners.filter((candidate) => candidate !== listener));
  }

  dispatchEvent(event) {
    for (const listener of [...(this.listeners.get(event.type) || [])]) {
      listener.call(this, event);
    }
    return true;
  }
}

class MiniCustomEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.detail = options.detail;
  }
}

class MiniClassList {
  constructor() {
    this.values = new Set();
  }

  add(...tokens) {
    tokens.forEach((token) => this.values.add(token));
  }

  remove(...tokens) {
    tokens.forEach((token) => this.values.delete(token));
  }
}

function isNativeDateInputValue(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) return false;
  const [year, month, day] = match.slice(1).map(Number);
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1) return false;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return day <= [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

class MiniElement extends MiniEventTarget {
  constructor(tagName, ownerDocument) {
    super();
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.classList = new MiniClassList();
    this.style = {
      setProperty() {},
      removeProperty() {},
    };
    this.textContent = '';
    this.title = '';
    this.type = '';
    this.min = '';
    this.max = '';
    this._value = '';
    this.id = '';
    this._innerHTML = '';
  }

  appendChild(child) {
    this.children.push(child);
    this.ownerDocument.register(child);
    return child;
  }

  insertAdjacentElement(_position, child) {
    return this.appendChild(child);
  }

  closest() {
    return null;
  }

  querySelector() {
    return null;
  }

  click() {
    this.dispatchEvent({ type: 'click' });
  }

  set value(value) {
    const next = String(value ?? '');
    this._value = this.type === 'date' && next && !isNativeDateInputValue(next) ? '' : next;
  }

  get value() {
    return this._value;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    for (const match of this._innerHTML.matchAll(/<(button|div|input)[^>]*\sid="([^"]+)"[^>]*>/g)) {
      const child = new MiniElement(match[1], this.ownerDocument);
      for (const attribute of match[0].matchAll(/\s([A-Za-z][\w:-]*)="([^"]*)"/g)) {
        const [, name, attributeValue] = attribute;
        if (name === 'id' || name === 'type' || name === 'min' || name === 'max' || name === 'title') {
          child[name] = attributeValue;
        }
      }
      child.id ||= match[2];
      this.appendChild(child);
    }
  }

  get innerHTML() {
    return this._innerHTML;
  }
}

class MiniDocument extends MiniEventTarget {
  constructor() {
    super();
    this.elements = new Map();
    this.head = new MiniElement('head', this);
    this.body = new MiniElement('body', this);
  }

  register(element) {
    if (element.id) this.elements.set(element.id, element);
  }

  createElement(tagName) {
    return new MiniElement(tagName, this);
  }

  getElementById(id) {
    return this.elements.get(id) || null;
  }

  querySelector() {
    return null;
  }
}

globalThis.Date = FixedDate;
globalThis.CustomEvent = MiniCustomEvent;

const moduleUrl = new URL('../static/js/admin/core/adminDate.js', import.meta.url);
const { getAdminDate, getRealToday, initAdminDateBar, parseAdminDateLocal, setAdminDate } = await import(moduleUrl.href);
const coordinatorModuleUrl = new URL('../static/js/admin/features/calendarSnapshotCoordinator.js', import.meta.url);
const { createSnapshotCoordinator } = await import(coordinatorModuleUrl.href);

equal(getRealToday(), '2026-03-15', 'real-today helper must use the local calendar date');
equal(parseAdminDateLocal('0001-01-01'), null, 'local date parsing must reject the unsupported FullCalendar low boundary');
equal(parseAdminDateLocal('1000-01-01')?.getFullYear(), 1000, 'local date parsing must preserve the supported minimum year');
equal(parseAdminDateLocal('9998-12-31')?.getFullYear(), 9998, 'local date parsing must preserve the supported maximum year');
equal(parseAdminDateLocal('9999-01-01'), null, 'local date parsing must reject the unsupported FullCalendar high boundary');
equal(parseAdminDateLocal('2026-02-31'), null, 'local date parsing must reject impossible dates');

for (const storedValue of [
  undefined,
  'not-a-date',
  '2026-2-03',
  '2026-99-01',
  '2026-00-10',
  '2026-02-29',
  '2026-02-31',
  '2026-04-31',
  '0000-01-01',
  '0001-01-01',
  '0999-12-31',
  '9999-01-01',
]) {
  const initial = storedValue === undefined ? {} : { [STORAGE_KEY]: storedValue };
  globalThis.sessionStorage = new SessionStorageStub(initial);
  equal(
    getAdminDate(),
    '2026-03-15',
    `missing, malformed, or impossible stored date must fall back: ${storedValue}`,
  );
}

globalThis.sessionStorage = new SessionStorageStub({ [STORAGE_KEY]: '2028-02-29' });
equal(getAdminDate(), '2028-02-29', 'a real leap-day value must be retained');

const throwingGetStorage = new SessionStorageStub({ [STORAGE_KEY]: '2028-02-29' });
throwingGetStorage.throwOnGet = true;
globalThis.sessionStorage = throwingGetStorage;
equal(getAdminDate(), '2026-03-15', 'a sessionStorage read failure must fall back to today');

const eventDocument = new MiniDocument();
globalThis.document = eventDocument;
const emittedDates = [];
eventDocument.addEventListener('admin:date-change', (event) => emittedDates.push(event.detail));

const writableStorage = new SessionStorageStub();
globalThis.sessionStorage = writableStorage;
setAdminDate(' 2028-02-29 ');
equal(writableStorage.values.get(STORAGE_KEY), '2028-02-29', 'valid dates must be trimmed and persisted');
deepEqual(emittedDates, [{ dateStr: '2028-02-29' }], 'valid writes must emit the canonical event detail');

setAdminDate('2028-03-01', { silent: true });
equal(writableStorage.values.get(STORAGE_KEY), '2028-03-01', 'silent writes must still persist');
equal(emittedDates.length, 1, 'silent writes must not emit an admin date event');

const callsBeforeInvalidWrites = writableStorage.setCalls;
for (const invalidValue of ['0001-01-01', '0999-12-31', '2026-02-29', '2026-02-31', '2026-04-31', '2026-99-01', '9999-01-01', '', null]) {
  setAdminDate(invalidValue);
}
equal(writableStorage.setCalls, callsBeforeInvalidWrites, 'invalid dates must not attempt a storage write');
equal(writableStorage.values.get(STORAGE_KEY), '2028-03-01', 'invalid dates must not replace the selected date');
equal(emittedDates.length, 1, 'invalid dates must not emit an admin date event');

const throwingSetStorage = new SessionStorageStub({ [STORAGE_KEY]: '2029-01-01' });
throwingSetStorage.throwOnSet = true;
globalThis.sessionStorage = throwingSetStorage;
setAdminDate('2029-01-02');
equal(throwingSetStorage.setCalls, 1, 'a valid date must attempt exactly one storage write');
deepEqual(
  emittedDates.at(-1),
  { dateStr: '2029-01-02' },
  'a storage write failure must not suppress the in-page date-change event',
);
equal(
  getAdminDate(),
  '2029-01-02',
  'a storage write failure must keep the emitted date authoritative in memory',
);

const restoredStorage = new SessionStorageStub();
globalThis.sessionStorage = restoredStorage;
setAdminDate('2030-01-03');
equal(getAdminDate(), '2030-01-03', 'a later successful write must replace the memory fallback');

const uiDocument = new MiniDocument();
globalThis.document = uiDocument;
globalThis.window = Object.assign(new MiniEventTarget(), {
  matchMedia: () => ({ matches: false }),
});
const mount = uiDocument.createElement('div');
mount.id = 'adminDateMount';
uiDocument.body.appendChild(mount);
const uiStorage = new SessionStorageStub({ [STORAGE_KEY]: '2026-03-01' });
globalThis.sessionStorage = uiStorage;
const uiEvents = [];
uiDocument.addEventListener('admin:date-change', (event) => uiEvents.push(event.detail.dateStr));

initAdminDateBar();
const display = uiDocument.getElementById('adb_date_display');
const previous = uiDocument.getElementById('adb_prev');
const next = uiDocument.getElementById('adb_next');
const today = uiDocument.getElementById('adb_today');
equal(display.tagName, 'INPUT', 'the selected date must be directly editable');
equal(display.type, 'date', 'the selected date must retain native date input semantics');
equal(display.min, '1000-01-01', 'the direct date input must expose the supported minimum');
equal(display.max, '9998-12-31', 'the direct date input must expose the supported maximum');
equal(display.value, '2026-03-01', 'the date bar must render the stored selected date');
equal(display.title, '2026-03-01', 'the date bar title must expose the full selected date');

previous.click();
equal(uiStorage.values.get(STORAGE_KEY), '2026-02-28', 'previous must persist the preceding calendar day');
equal(display.value, '2026-02-28', 'previous must update the visible date');
equal(uiEvents.at(-1), '2026-02-28', 'previous must emit the selected date');

next.click();
equal(uiStorage.values.get(STORAGE_KEY), '2026-03-01', 'next must persist the following calendar day');
equal(display.value, '2026-03-01', 'next must update the visible date');
equal(uiEvents.at(-1), '2026-03-01', 'next must emit the selected date');

today.click();
equal(uiStorage.values.get(STORAGE_KEY), '2026-03-15', 'today must persist the real local date');
equal(display.value, '2026-03-15', 'today must update the visible date');
equal(uiEvents.at(-1), '2026-03-15', 'today must emit the real local date');

const eventsBeforeDirectSelection = uiEvents.length;
display.value = '2025-12-24';
display.dispatchEvent({ type: 'change' });
equal(uiStorage.values.get(STORAGE_KEY), '2025-12-24', 'direct selection must persist the chosen date');
equal(display.value, '2025-12-24', 'direct selection must remain visible');
equal(uiEvents.length, eventsBeforeDirectSelection + 1, 'direct selection must emit exactly one event');
equal(uiEvents.at(-1), '2025-12-24', 'direct selection must emit the chosen date');

const callsBeforeSameSelection = uiStorage.setCalls;
const eventsBeforeSameSelection = uiEvents.length;
display.dispatchEvent({ type: 'change' });
equal(uiStorage.setCalls, callsBeforeSameSelection, 'selecting the current date must not write again');
equal(uiEvents.length, eventsBeforeSameSelection, 'selecting the current date must not emit again');

display.value = '';
display.dispatchEvent({ type: 'change' });
equal(display.value, '2025-12-24', 'clearing the date input must restore the authoritative date');
equal(uiEvents.length, eventsBeforeSameSelection, 'clearing the date input must not emit an event');

display.value = '2026-02-31';
equal(display.value, '', 'the test DOM must model native impossible-date normalization');
display.dispatchEvent({ type: 'change' });
equal(display.value, '2025-12-24', 'an impossible direct date must restore the authoritative date');
equal(uiEvents.length, eventsBeforeSameSelection, 'an impossible direct date must not emit an event');

uiDocument.dispatchEvent(new MiniCustomEvent('admin:date-change', {
  detail: { dateStr: '2026-02-31' },
}));
equal(display.value, '2025-12-24', 'the date bar listener must ignore impossible event dates');

uiDocument.dispatchEvent(new MiniCustomEvent('admin:date-change', {
  detail: { dateStr: '2026-12-31' },
}));
equal(display.value, '2026-12-31', 'the date bar listener must accept valid external date events');
equal(display.title, '2026-12-31', 'a valid external event must update the full-date title');
equal(
  uiStorage.values.get(STORAGE_KEY),
  '2025-12-24',
  'an external event must update only the display rather than writing storage again',
);

const boundaryDocument = new MiniDocument();
globalThis.document = boundaryDocument;
const boundaryMount = boundaryDocument.createElement('div');
boundaryMount.id = 'adminDateMount';
boundaryDocument.body.appendChild(boundaryMount);
const boundaryStorage = new SessionStorageStub({ [STORAGE_KEY]: '1000-01-01' });
globalThis.sessionStorage = boundaryStorage;
initAdminDateBar();
boundaryDocument.getElementById('adb_prev').click();
equal(
  boundaryDocument.getElementById('adb_date_display').value,
  '1000-01-01',
  'previous at the minimum supported date must remain on a valid date',
);
equal(boundaryStorage.values.get(STORAGE_KEY), '1000-01-01', 'minimum-date navigation must not underflow');

boundaryStorage.values.set(STORAGE_KEY, '9998-12-31');
boundaryDocument.dispatchEvent(new MiniCustomEvent('admin:date-change', {
  detail: { dateStr: '9998-12-31' },
}));
boundaryDocument.getElementById('adb_next').click();
equal(
  boundaryDocument.getElementById('adb_date_display').value,
  '9998-12-31',
  'next at the maximum supported date must remain on a valid date',
);
equal(boundaryStorage.values.get(STORAGE_KEY), '9998-12-31', 'maximum-date navigation must not overflow');

const pendingRefreshes = new Map();
const committedRefreshes = [];
const refreshCoordinator = createSnapshotCoordinator(
  key => new Promise(resolve => pendingRefreshes.set(key, resolve)),
  (snapshot, key) => committedRefreshes.push([key, snapshot]),
);
const refreshA = refreshCoordinator.load('A');
const refreshB = refreshCoordinator.load('B');
pendingRefreshes.get('B')('snapshot-B');
deepEqual(await refreshB, { committed: true, snapshot: 'snapshot-B' }, 'the latest calendar refresh must commit');
pendingRefreshes.get('A')('snapshot-A');
deepEqual(await refreshA, { committed: false, snapshot: 'snapshot-A' }, 'a late stale calendar refresh must not commit');
deepEqual(committedRefreshes, [['B', 'snapshot-B']], 'reverse completion must preserve only the latest calendar state');
const pendingActionRefreshes = new Map();
const actionCommits = [];
const sharedCoordinator = createSnapshotCoordinator(
  key => new Promise(resolve => pendingActionRefreshes.set(key, resolve)),
  (snapshot, key) => actionCommits.push([key, snapshot]),
);
const visibleLoad = sharedCoordinator.load('visible-A');
const actionLoad = sharedCoordinator.load('action');
pendingActionRefreshes.get('action')('action-state');
deepEqual(await actionLoad, { committed: true, snapshot: 'action-state' }, 'a newer action preload must commit');
pendingActionRefreshes.get('visible-A')('stale-visible-state');
deepEqual(await visibleLoad, { committed: false, snapshot: 'stale-visible-state' }, 'an older visible refresh must not overwrite action state');
deepEqual(actionCommits, [['action', 'action-state']], 'visible/action interleaving must preserve the newest shared snapshot');
const pendingActionFirstRefreshes = new Map();
const actionFirstCommits = [];
const actionFirstCoordinator = createSnapshotCoordinator(
  key => new Promise(resolve => pendingActionFirstRefreshes.set(key, resolve)),
  (snapshot, key) => actionFirstCommits.push([key, snapshot]),
);
const actionFirstLoad = actionFirstCoordinator.load('action-first');
const visibleSecondLoad = actionFirstCoordinator.load('visible-second');
pendingActionFirstRefreshes.get('action-first')('stale-action-state');
deepEqual(await actionFirstLoad, { committed: false, snapshot: 'stale-action-state' }, 'an action preload superseded by a visible refresh must report stale');
pendingActionFirstRefreshes.get('visible-second')('visible-state');
deepEqual(await visibleSecondLoad, { committed: true, snapshot: 'visible-state' }, 'the newer visible preload must own shared state');
deepEqual(actionFirstCommits, [['visible-second', 'visible-state']], 'action-first interleaving must not publish its stale snapshot');
const pendingCoalescedRefreshes = new Map();
const coalescedCommits = [];
let coalescedLoadCount = 0;
const coalescedCoordinator = createSnapshotCoordinator(
  key => {
    coalescedLoadCount += 1;
    return new Promise(resolve => pendingCoalescedRefreshes.set(key, resolve));
  },
  (snapshot, key) => coalescedCommits.push([key, snapshot]),
);
const coalescedAction = (async () => {
  const result = await coalescedCoordinator.load('action');
  return result.committed ? result : coalescedCoordinator.settled();
})();
const coalescedVisible = (async () => {
  const result = await coalescedCoordinator.load('visible');
  return result.committed ? result : coalescedCoordinator.settled();
})();
pendingCoalescedRefreshes.get('action')('stale-action');
pendingCoalescedRefreshes.get('visible')('latest-visible');
deepEqual(await coalescedAction, { committed: true, snapshot: 'latest-visible' }, 'a stale action must coalesce behind the latest visible refresh');
deepEqual(await coalescedVisible, { committed: true, snapshot: 'latest-visible' }, 'the latest visible refresh must settle normally');
equal(coalescedLoadCount, 2, 'coalescing must not create a retry request loop');
deepEqual(coalescedCommits, [['visible', 'latest-visible']], 'coalescing must publish one newest snapshot');
const invalidatedCommits = [];
let resolveInvalidated;
const invalidationCoordinator = createSnapshotCoordinator(
  () => new Promise(resolve => { resolveInvalidated = resolve; }),
  snapshot => invalidatedCommits.push(snapshot),
);
const invalidatedLoad = invalidationCoordinator.load('old-read');
invalidationCoordinator.invalidate();
resolveInvalidated('old-state');
deepEqual(await invalidatedLoad, { committed: false, snapshot: 'old-state' }, 'a direct write invalidation must reject an older shared read');
deepEqual(invalidatedCommits, [], 'an invalidated read must not overwrite direct write state');
deepEqual(await invalidationCoordinator.settled(), { committed: true, snapshot: null }, 'settled after direct invalidation must not expose the rejected snapshot');
const pendingProjectionRefreshes = new Map();
const projectionCoordinator = createSnapshotCoordinator(
  key => new Promise(resolve => pendingProjectionRefreshes.set(key, resolve)),
  () => {},
);
let activeProjectionRange = 'A';
const projectedRanges = [];
const projectLatestRange = async requestedRange => {
  const result = await projectionCoordinator.load(requestedRange);
  let projectionRange = requestedRange;
  if (!result.committed) {
    const settled = await projectionCoordinator.settled();
    if (!settled.snapshot) return false;
    projectionRange = activeProjectionRange;
  }
  projectedRanges.push(projectionRange);
  return true;
};
const projectionA = projectLatestRange('A');
activeProjectionRange = 'B';
const projectionB = projectLatestRange('B');
pendingProjectionRefreshes.get('B')('snapshot-B');
pendingProjectionRefreshes.get('A')('snapshot-A');
equal(await projectionB, true, 'the latest visible range must project');
equal(await projectionA, true, 'a stale visible call must settle without dropping the current projection');
equal(projectedRanges.includes('A'), false, 'a stale visible call must never project its old range after the current range');
deepEqual(projectedRanges, ['B', 'B'], 'all settled projections must target the current visible range');
const invalidatedProjectionLoads = new Map();
const invalidatedProjectionCoordinator = createSnapshotCoordinator(
  key => new Promise(resolve => invalidatedProjectionLoads.set(key, resolve)),
  () => {},
);
let invalidatedCurrentRange = 'A';
const invalidatedProjectedRanges = [];
const projectAfterInvalidation = async requestedRange => {
  const result = await invalidatedProjectionCoordinator.load(requestedRange);
  if (!result.committed) {
    const settled = await invalidatedProjectionCoordinator.settled();
    if (!settled.snapshot) return projectAfterInvalidation(invalidatedCurrentRange);
  }
  invalidatedProjectedRanges.push(invalidatedCurrentRange);
  return true;
};
const invalidatedProjectionA = projectAfterInvalidation('A');
invalidatedCurrentRange = 'B';
invalidatedProjectionCoordinator.invalidate();
invalidatedProjectionLoads.get('A')('stale-A');
while (!invalidatedProjectionLoads.has('B')) await Promise.resolve();
invalidatedProjectionLoads.get('B')('fresh-B');
equal(await invalidatedProjectionA, true, 'invalidate recovery must eventually project');
deepEqual(invalidatedProjectedRanges, ['B'], 'invalidate recovery must reload and project only the current range');

const calendarSource = fs.readFileSync('static/js/admin/features/calendar.js', 'utf8');
const adminMainSource = fs.readFileSync('static/js/admin/main.js', 'utf8');

function calendarBlock(startMarker, endMarker) {
  const start = calendarSource.indexOf(startMarker);
  const end = calendarSource.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0 && end > start, `missing executable calendar block: ${startMarker}`);
  return calendarSource.slice(start, end);
}

function createCalendarLoaderFixture() {
  const requests = [];
  const state = { students: [], absentByDate: {}, absentSlotsByDate: {} };
  const published = {};
  const request = url => new Promise(resolve => requests.push({ url, resolve }));
  const factory = new Function(
    'fetch', 'fetchMakeupCarryoverSnapshot', 'fetchAbsentSnapshot', 'normalizeCarryoverPayload',
    'applyAbsentPayload', 'state', 'window', 'ymd', 'yoil', 'MAKEUP_SLOTS', 'hasWeekday',
    'addSlotCounts', 'getCountSlots', 'getMakeupSlots', 'parseSlotNumbers',
    `let countMap = {}, EXTRA = {}, WEEKEND = {}, CARRYOVER = {};
     ${calendarBlock('  let preloadExtraWeekendPromise = null;', '  // 슬롯 버튼')}
     ${calendarBlock('  function invalidateCalendarPreload()', '  function syncCalendarCellRatio()')}
     ${calendarBlock('  async function fetchCountsForRange(start, end)', '  function refreshCountBadges()')}
     return {
       load: preloadExtraWeekend,
       counts: fetchCountsForRange,
       invalidate: invalidateCalendarPreload,
       direct(extra) { invalidateCalendarPreload(); EXTRA = extra; state.extra = extra; window.extra = extra; },
       inspect() { return structuredClone({ extra: window.extra, carryover: CARRYOVER, counts: countMap }); }
     };`,
  );
  const loader = factory(
    url => request(url).then(payload => ({ json: async () => payload })),
    () => request('/api/makeup-carryover').then(payload => ({ payload, revision: 'fixture-revision' })),
    () => request('/api/absent'),
    payload => payload,
    payload => { state.absentByDate = payload.by_date || {}; state.absentSlotsByDate = payload.by_slot || {}; },
    state, published,
    value => `${String(value.getFullYear()).padStart(4, '0')}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`,
    () => '월', [1, 2], () => false,
    (slots, sid) => slots[1].add(String(sid)), () => [1], () => [1], value => Array.isArray(value) ? value : [value],
  );
  const settle = (batch, sid) => {
    const pending = requests.slice(batch * 4, batch * 4 + 4);
    equal(pending.length, 4, 'one actual calendar preload starts exactly four independent store reads');
    pending.slice().reverse().forEach(({ url, resolve }) => resolve(
      url === '/api/extra-attend' ? { '2026-06-02': [sid] }
        : url === '/api/makeup-carryover' ? { by_absence: { [sid]: {} } }
          : {},
    ));
  };
  return { loader, requests, settle };
}

const actualVisible = createCalendarLoaderFixture();
const actualRangeA = actualVisible.loader.counts('2026-06-01', '2026-06-02');
const actualRangeB = actualVisible.loader.counts('2026-06-02', '2026-06-03');
equal(actualVisible.requests.length, 4, 'concurrent visible ranges must share one actual preload');
actualVisible.settle(0, 'newest');
equal(await actualRangeA, false, 'a stale visible range must not publish its count projection');
equal(await actualRangeB, true, 'the newest visible range must publish its count projection');
deepEqual(actualVisible.loader.inspect().counts, { '2026-06-02': { 1: 1, 2: 0 } }, 'visible projection must contain only the newest range');

for (const actionFirst of [false, true]) {
  const actualShared = createCalendarLoaderFixture();
  const first = actionFirst ? actualShared.loader.load() : actualShared.loader.counts('2026-06-02', '2026-06-03');
  const second = actionFirst ? actualShared.loader.counts('2026-06-02', '2026-06-03') : actualShared.loader.load();
  equal(actualShared.requests.length, 4, 'action and visible calls must share one actual preload in either start order');
  actualShared.settle(0, 'shared');
  await Promise.all([first, second]);
  deepEqual(actualShared.loader.inspect().extra, { '2026-06-02': ['shared'] }, 'shared action/visible reads must publish the same fresh state');
  equal(actualShared.requests.length, 4, 'coalesced action/visible reads must not create a retry loop');
}

const actualInvalidation = createCalendarLoaderFixture();
const invalidatedActualLoad = actualInvalidation.loader.load();
actualInvalidation.loader.direct({ '2026-06-02': ['direct-write'] });
actualInvalidation.loader.invalidate();
const coalescedActualLoad = actualInvalidation.loader.load();
actualInvalidation.settle(0, 'stale-read');
for (let turn = 0; actualInvalidation.requests.length < 8 && turn < 20; turn += 1) await Promise.resolve();
equal(actualInvalidation.requests.length, 8, 'invalidated waiters must coalesce behind one fresh actual preload');
deepEqual(actualInvalidation.loader.inspect().extra, { '2026-06-02': ['direct-write'] }, 'an invalidated actual read must not overwrite direct mutation state');
actualInvalidation.settle(1, 'fresh-read');
await Promise.all([invalidatedActualLoad, coalescedActualLoad]);
deepEqual(actualInvalidation.loader.inspect().extra, { '2026-06-02': ['fresh-read'] }, 'invalidated waiters must eventually receive the fresh actual state');
equal(actualInvalidation.requests.length, 8, 'repeated invalidation must not create an unbounded reload loop');

const actualInvalidatedRange = createCalendarLoaderFixture();
const oldActualProjection = actualInvalidatedRange.loader.counts('2026-06-01', '2026-06-02');
actualInvalidatedRange.loader.invalidate();
const freshActualProjection = actualInvalidatedRange.loader.counts('2026-06-02', '2026-06-03');
actualInvalidatedRange.settle(0, 'old-range');
for (let turn = 0; actualInvalidatedRange.requests.length < 8 && turn < 20; turn += 1) await Promise.resolve();
actualInvalidatedRange.settle(1, 'new-range');
equal(await oldActualProjection, false, 'invalidated recovery must never project the old visible range');
equal(await freshActualProjection, true, 'invalidated recovery must project the current visible range');
deepEqual(actualInvalidatedRange.loader.inspect().counts, { '2026-06-02': { 1: 1, 2: 0 } }, 'recovered actual projections must remain on the current range');
equal(
  adminMainSource.includes("import { initAdminDateBar } from './core/adminDate.js';"),
  true,
  'admin bootstrap must share the canonical admin-date module instance with feature consumers',
);
equal(
  /let calendarFocusDate = toSafeDate\(\.\.\.String\(getAdminDate\(\)/.test(calendarSource),
  true,
  'calendar initialization must use the selected admin date',
);
equal(
  /y < 1000 \|\| y > 9998/.test(calendarSource),
  true,
  'calendar dates must enforce the same year range as the direct date input',
);
equal(
  /String\(d\.getFullYear\(\)\)\.padStart\(4, '0'\)/.test(calendarSource),
  true,
  'calendar ISO dates must retain four-digit boundary years',
);
equal(
  /return \{ start: ymd\(start\), end: ymd\(addDays\(start, 35\)\) \}/.test(calendarSource),
  true,
  'calendar visible ranges must use four-digit ISO strings at boundary years',
);
equal(
  /String\(titleDate\.getFullYear\(\)\)\.padStart\(4, '0'\)\.slice\(2\)/.test(calendarSource),
  true,
  'calendar week titles must retain a two-digit display for boundary years',
);
equal(
  (calendarSource.match(/new Date\(date\.getTime\(\)\)/g) || []).length,
  2,
  'calendar date copies must avoid constructor-based year offsets in every navigation path',
);
equal(
  /new Date\(date\.getFullYear\(\), date\.getMonth\(\), date\.getDate\(\)\)/.test(calendarSource),
  false,
  'calendar navigation must not use the Date constructor year-1900 offset',
);
equal(
  /return parseAdminDateLocal\(`\$\{String\(y\)\.padStart\(4, '0'\)\}-\$\{String\(m\)\.padStart\(2, '0'\)\}-\$\{String\(d\)\.padStart\(2, '0'\)\}`\)/.test(calendarSource),
  true,
  'calendar dates must use the executable admin date parser for boundary-year behavior',
);
equal(
  /const isSupportedCalendarDate = value => !!parseAdminDateLocal\(String\(value \|\| ''\)\.trim\(\)\)/.test(calendarSource),
  true,
  'calendar interactions must share the executable supported-date validator',
);
equal(
  /const next = date instanceof Date\s*\? parseAdminDateLocal\(ymd\(date\)\)\s*: toSafeDate/.test(calendarSource),
  true,
  'Date-based wheel navigation must revalidate the supported calendar range',
);
equal(
  /dateClick: info => \{\s*if \(!isSupportedCalendarDate\(info\.dateStr\)\)/.test(calendarSource),
  true,
  'calendar side cells outside the supported range must be inert before any action mode',
);
equal(
  /function openAttendModal\(dateStr\) \{\s*if \(!isSupportedCalendarDate\(dateStr\)\) return;/.test(calendarSource),
  true,
  'attendance reads must reject unsupported calendar dates',
);
equal(
  /function openMakeupSlotPicker\(dateStr, dayEl\) \{\s*if \(!makeupSelection \|\| !dayEl \|\| !isSupportedCalendarDate\(dateStr\)\) return;/.test(calendarSource),
  true,
  'makeup scheduling must reject unsupported calendar dates',
);
equal(
  /const generation = calendarMutationGeneration;[\s\S]*?Promise\.allSettled\(\[[\s\S]*?generation !== calendarMutationGeneration/.test(calendarSource),
  true,
  'calendar snapshot loads must retain their single-flight mutation-generation owner',
);
equal(
  /const projectionGeneration = \+\+calendarProjectionGeneration;\s*await preloadExtraWeekend\(\);\s*if \(projectionGeneration !== calendarProjectionGeneration\) return false;/.test(calendarSource),
  true,
  'visible projections must reject a superseded range after the shared actual preload',
);
equal(
  /async function preloadExtraWeekend\(\) \{\s*while \(true\) \{\s*if \(!preloadExtraWeekendPromise\)/.test(calendarSource),
  true,
  'action preloads must retain one shared pending read and retry only after a mutation invalidates it',
);
equal(/Promise\.all\(\[[\s\S]*?\/api\/extra-attend[\s\S]*?\]\)\.then\(\(\[att, extraMap, weekendMap\]\) => \{\s*EXTRA\s*=/.test(calendarSource), false, 'attendance display loads must not overwrite the shared extra-attendance snapshot');
equal(/Promise\.all\(\[[\s\S]*?\/api\/weekend-slots[\s\S]*?\]\)\.then\(\(\[todayAtt, extraMap, weekendMap\]\) => \{\s*EXTRA\s*=/.test(calendarSource), false, 'selection display loads must not overwrite the shared weekend snapshot');
equal(/await saveScheduleOverridesFailClosed\([\s\S]*?invalidateCalendarPreload\(\);/.test(calendarSource), true, 'revisioned selection saves must invalidate pending shared reads after committing');
const datesSetBlock = calendarSource.match(/datesSet: range => \{([\s\S]*?)\r?\n\s{4}\}\r?\n\s{2}\}\);/)?.[1] || '';
equal(datesSetBlock.includes('fetchCountsForRange(range.start, range.end)'), true, 'datesSet must project counts through the shared actual preload');
equal(datesSetBlock.includes('loadExtraWeekendSnapshot('), false, 'datesSet must not start a duplicate data preload');
equal(datesSetBlock.includes('preloadExtraWeekend('), false, 'datesSet must not start a second direct data preload');
equal(datesSetBlock.includes('refreshMakeupPlanner('), true, 'datesSet must retain planner refresh through the same single-flight loader');
equal(
  /document\.addEventListener\('admin:date-change', \(event\) => \{\s*setCalendarFocusDate\(event\?\.detail\?\.dateStr\)/.test(calendarSource),
  true,
  'calendar focus must follow valid admin date changes',
);
equal(
  /document\.addEventListener\('admin:date-change', \(event\) => \{\s*setCalendarFocusDate\(event\?\.detail\?\.dateStr\);\s*\}\);/.test(calendarSource),
  true,
  'calendar date changes must rely on datesSet rather than issuing a second planner refresh',
);

console.log(`admin date sessionStorage checks passed: ${assertionCount} assertions`);
