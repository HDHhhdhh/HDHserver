import assert from 'node:assert/strict';

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

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    for (const match of this._innerHTML.matchAll(/<(button|div)[^>]*\sid="([^"]+)"[^>]*>/g)) {
      const child = new MiniElement(match[1], this.ownerDocument);
      child.id = match[2];
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
const { getAdminDate, getRealToday, initAdminDateBar, setAdminDate } = await import(moduleUrl.href);

equal(getRealToday(), '2026-03-15', 'real-today helper must use the local calendar date');

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
for (const invalidValue of ['2026-02-29', '2026-02-31', '2026-04-31', '2026-99-01', '', null]) {
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
equal(display.textContent, '26/03/01', 'the date bar must render the stored selected date');
equal(display.title, '2026-03-01', 'the date bar title must expose the full selected date');

previous.click();
equal(uiStorage.values.get(STORAGE_KEY), '2026-02-28', 'previous must persist the preceding calendar day');
equal(display.textContent, '26/02/28', 'previous must update the visible date');
equal(uiEvents.at(-1), '2026-02-28', 'previous must emit the selected date');

next.click();
equal(uiStorage.values.get(STORAGE_KEY), '2026-03-01', 'next must persist the following calendar day');
equal(display.textContent, '26/03/01', 'next must update the visible date');
equal(uiEvents.at(-1), '2026-03-01', 'next must emit the selected date');

today.click();
equal(uiStorage.values.get(STORAGE_KEY), '2026-03-15', 'today must persist the real local date');
equal(display.textContent, '26/03/15', 'today must update the visible date');
equal(uiEvents.at(-1), '2026-03-15', 'today must emit the real local date');

uiDocument.dispatchEvent(new MiniCustomEvent('admin:date-change', {
  detail: { dateStr: '2026-02-31' },
}));
equal(display.textContent, '26/03/15', 'the date bar listener must ignore impossible event dates');

uiDocument.dispatchEvent(new MiniCustomEvent('admin:date-change', {
  detail: { dateStr: '2026-12-31' },
}));
equal(display.textContent, '26/12/31', 'the date bar listener must accept valid external date events');
equal(display.title, '2026-12-31', 'a valid external event must update the full-date title');
equal(
  uiStorage.values.get(STORAGE_KEY),
  '2026-03-15',
  'an external event must update only the display rather than writing storage again',
);

const boundaryDocument = new MiniDocument();
globalThis.document = boundaryDocument;
const boundaryMount = boundaryDocument.createElement('div');
boundaryMount.id = 'adminDateMount';
boundaryDocument.body.appendChild(boundaryMount);
const boundaryStorage = new SessionStorageStub({ [STORAGE_KEY]: '0001-01-01' });
globalThis.sessionStorage = boundaryStorage;
initAdminDateBar();
boundaryDocument.getElementById('adb_prev').click();
equal(
  boundaryDocument.getElementById('adb_date_display').title,
  '0001-01-01',
  'previous at the minimum supported date must remain on a valid date',
);
equal(boundaryStorage.values.get(STORAGE_KEY), '0001-01-01', 'minimum-date navigation must not underflow');

boundaryStorage.values.set(STORAGE_KEY, '9999-12-31');
boundaryDocument.dispatchEvent(new MiniCustomEvent('admin:date-change', {
  detail: { dateStr: '9999-12-31' },
}));
boundaryDocument.getElementById('adb_next').click();
equal(
  boundaryDocument.getElementById('adb_date_display').title,
  '9999-12-31',
  'next at the maximum supported date must remain on a valid date',
);
equal(boundaryStorage.values.get(STORAGE_KEY), '9999-12-31', 'maximum-date navigation must not overflow');

console.log(`admin date sessionStorage checks passed: ${assertionCount} assertions`);
