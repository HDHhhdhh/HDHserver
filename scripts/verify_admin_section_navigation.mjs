import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_PATH = path.join(ROOT, 'static', 'js', 'admin', 'features', 'uiEnhance.js');
const HTML_PATH = path.join(ROOT, 'static', 'admin.html');
const CSS_PATH = path.join(ROOT, 'static', 'css', 'admin.css');
const TARGETS = Object.freeze([
  ['scroll-today', 'todaySection'],
  ['scroll-done', 'doneSection'],
  ['scroll-calendar', 'calendarSection'],
]);

let assertionCount = 0;

function ok(value, message) {
  assertionCount += 1;
  assert.ok(value, message);
}

function equal(actual, expected, message) {
  assertionCount += 1;
  assert.equal(actual, expected, message);
}

function deepEqual(actual, expected, message) {
  assertionCount += 1;
  assert.deepEqual(actual, expected, message);
}

class MiniClassList {
  constructor(...tokens) {
    this.tokens = new Set(tokens.filter(Boolean));
  }

  add(...tokens) {
    tokens.forEach(token => this.tokens.add(token));
  }

  remove(...tokens) {
    tokens.forEach(token => this.tokens.delete(token));
  }

  toggle(token, force) {
    const enabled = force === undefined ? !this.tokens.has(token) : Boolean(force);
    if (enabled) this.tokens.add(token);
    else this.tokens.delete(token);
    return enabled;
  }

  contains(token) {
    return this.tokens.has(token);
  }
}

class MiniElement {
  constructor({ id = '', classes = [], attributes = {}, parent = null, rect = null } = {}) {
    this.id = id;
    this.parentElement = parent;
    this.attributes = new Map(Object.entries(attributes));
    this.classList = new MiniClassList(...classes);
    this.dataset = {};
    this.style = { setProperty() {} };
    this.scrollCalls = [];
    this.clicked = 0;
    this.textContent = '';
    this.rect = rect || { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 };
  }

  getAttribute(name) {
    if (name === 'id') return this.id || null;
    if (name === 'class') return [...this.classList.tokens].join(' ');
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  matches(selector) {
    if (selector === '[data-ui-action]') return this.attributes.has('data-ui-action');
    if (selector === '.admin-section-nav__button') return this.classList.contains('admin-section-nav__button');
    if (selector === '.kpi-card') return this.classList.contains('kpi-card');
    if (selector === '#todayWrap, #doneWrap') return this.id === 'todayWrap' || this.id === 'doneWrap';
    return false;
  }

  closest(selector) {
    let current = this;
    while (current) {
      if (current.matches(selector)) return current;
      current = current.parentElement;
    }
    return null;
  }

  querySelectorAll(selector) {
    if (selector === '.admin-section-nav__button') return this.buttons || [];
    return [];
  }

  querySelector() {
    return null;
  }

  scrollIntoView(options) {
    this.scrollCalls.push(options);
  }

  click() {
    this.clicked += 1;
  }

  getBoundingClientRect() {
    return { ...this.rect };
  }
}

class MiniDocument {
  constructor(elements) {
    this.elements = new Map(elements.map(element => [element.id, element]).filter(([id]) => id));
    this.listeners = new Map();
    this.body = new MiniElement();
  }

  getElementById(id) {
    return this.elements.get(id) || null;
  }

  querySelectorAll(selector) {
    if (selector === '#todayWrap tr[data-sid], #doneWrap tr[data-sid]') return [];
    if (selector === '.admin-section-nav__button' || selector === '#adminSectionNav .admin-section-nav__button') {
      return this.getElementById('adminSectionNav')?.buttons || [];
    }
    return [];
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatchEvent(event) {
    for (const listener of [...(this.listeners.get(event.type) || [])]) listener.call(this, event);
  }
}

function makeUi() {
  const nav = new MiniElement({
    id: 'adminSectionNav',
    classes: ['admin-section-nav'],
    rect: { top: 8, bottom: 66, left: 0, right: 600, width: 600, height: 58 },
  });
  const buttons = TARGETS.map(([action, target]) => new MiniElement({
    classes: ['admin-section-nav__button'],
    attributes: {
      'data-ui-action': action,
      'aria-controls': target,
    },
    parent: nav,
  }));
  nav.buttons = buttons;
  const sections = TARGETS.map(([, id], index) => new MiniElement({
    id,
    rect: {
      top: 100 + (index * 600),
      bottom: 650 + (index * 600),
      left: 0,
      right: 600,
      width: 600,
      height: 550,
    },
  }));
  const document = new MiniDocument([nav, ...sections]);
  return { document, nav, buttons, sections };
}

function transformModule(source) {
  const transformed = source
    .replace("import { $ } from '../core/utils.js';", 'const $ = id => document.getElementById(id);')
    .replace(
      "import { initAttendanceLedgerLink } from './attendanceLedgerLink.js';",
      'const initAttendanceLedgerLink = () => {};',
    )
    .replace('export function initAdminUiEnhance()', 'function initAdminUiEnhance()');
  ok(!/^\s*import\s/m.test(transformed), 'the VM fixture must replace every uiEnhance import');
  ok(!/\bexport\s+function\b/.test(transformed), 'the VM fixture must replace the exported initializer');
  return `${transformed}\nglobalThis.__uiEnhance = { initAdminUiEnhance };`;
}

function createStorageGuard(name, counters) {
  return new Proxy({}, {
    get() {
      counters[name] += 1;
      throw new Error(`${name} access is forbidden in section navigation`);
    },
  });
}

function activeButtons(buttons) {
  return buttons.filter(button => button.classList.contains('is-active'));
}

function currentButtons(buttons) {
  return buttons.filter(button => button.getAttribute('aria-current') === 'location');
}

function runScenario({ reducedMotion, intersectionObserver = true }) {
  const { document, nav, buttons, sections } = makeUi();
  const observerInstances = [];
  const counters = { fetch: 0, localStorage: 0, sessionStorage: 0 };

  class MiniIntersectionObserver {
    constructor(callback, options) {
      this.callback = callback;
      this.options = options;
      this.observed = [];
      observerInstances.push(this);
    }

    observe(element) {
      this.observed.push(element);
    }

    disconnect() {}

    emit(entries) {
      this.callback(entries, this);
    }
  }

  const window = {
    matchMedia(query) {
      equal(query, '(prefers-reduced-motion: reduce)', 'navigation must query the standard reduced-motion preference');
      return { matches: reducedMotion };
    },
  };
  if (intersectionObserver) window.IntersectionObserver = MiniIntersectionObserver;

  const context = {
    console,
    document,
    window,
    IntersectionObserver: intersectionObserver ? MiniIntersectionObserver : undefined,
    MutationObserver: class MutationObserver { observe() {} },
    Date,
    requestAnimationFrame(callback) { callback(); return 1; },
    setInterval() { return 1; },
    clearInterval() {},
    fetch() {
      counters.fetch += 1;
      throw new Error('fetch is forbidden in section navigation');
    },
    localStorage: createStorageGuard('localStorage', counters),
    sessionStorage: createStorageGuard('sessionStorage', counters),
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(transformModule(fs.readFileSync(SOURCE_PATH, 'utf8')), context, { filename: 'uiEnhance.js' });
  context.__uiEnhance.initAdminUiEnhance();

  return { context, counters, document, nav, buttons, sections, observerInstances };
}

function assertSingleton(buttons, expectedIndex, context) {
  deepEqual(activeButtons(buttons), [buttons[expectedIndex]], `${context}: exactly one button must have is-active`);
  deepEqual(currentButtons(buttons), [buttons[expectedIndex]], `${context}: exactly one button must have aria-current=location`);
  buttons.forEach((button, index) => {
    if (index !== expectedIndex) {
      equal(button.getAttribute('aria-current'), null, `${context}: inactive aria-current must be absent`);
    }
  });
}

const htmlSource = fs.readFileSync(HTML_PATH, 'utf8');
const cssSource = fs.readFileSync(CSS_PATH, 'utf8');
const uiSource = fs.readFileSync(SOURCE_PATH, 'utf8');
const navMatch = htmlSource.match(/<nav\b[^>]*\bid="adminSectionNav"[^>]*>([\s\S]*?)<\/nav>/i);

ok(navMatch, 'admin.html must contain the section navigation landmark');
equal((htmlSource.match(/\bid="adminSectionNav"/g) || []).length, 1, 'section navigation id must be unique');
ok(/class="[^"]*\badmin-section-nav\b[^"]*"/i.test(navMatch[0]), 'section navigation must expose its styling class');
ok(/aria-label="관리자 주요 섹션"/u.test(navMatch[0]), 'section navigation must have a Korean accessible name');
const sourceButtons = [...navMatch[1].matchAll(/<button\b([^>]*)>/gi)].map(match => match[1]);
equal(sourceButtons.length, 3, 'section navigation must expose exactly three buttons');
deepEqual(
  sourceButtons.map(attributes => [
    attributes.match(/data-ui-action="([^"]+)"/)?.[1],
    attributes.match(/aria-controls="([^"]+)"/)?.[1],
  ]),
  TARGETS,
  'section navigation buttons must map exactly to today, done, and calendar',
);
for (const [, target] of TARGETS) {
  equal((htmlSource.match(new RegExp(`\\bid="${target}"`, 'g')) || []).length, 1, `${target} must exist exactly once`);
}
ok(
  /body\.admin\.admin-simple\s+\.admin-section-nav\s*\{[^}]*display\s*:\s*none\s*!important/si.test(cssSource),
  'Simple mode must hide section navigation at the source CSS level',
);
ok(
  /body\.admin\s+#calendar\s+\.fc-header-toolbar\s*\{[^}]*top\s*:\s*calc\([^}]*58px\)/si.test(cssSource),
  'the calendar toolbar must stay below the sticky section navigation',
);
ok(
  /body\.admin\s+#calendar\s+\.fc-scrollgrid-section-header\s+th\s*\{[^}]*top\s*:\s*calc\([^}]*100px\)/si.test(cssSource),
  'the calendar weekday header must stay below both sticky navigation layers',
);
equal(/\bfetch\s*\(/.test(uiSource), false, 'uiEnhance section navigation must not issue fetch requests');
equal(/\blocalStorage\b/.test(uiSource), false, 'uiEnhance section navigation must not access localStorage');
equal(/\bsessionStorage\b/.test(uiSource), false, 'uiEnhance section navigation must not access sessionStorage');

const normal = runScenario({ reducedMotion: false });
equal(normal.observerInstances.length, 1, 'supported browsers must install one section IntersectionObserver');
deepEqual(normal.observerInstances[0].observed, normal.sections, 'the observer must watch exactly the three target sections');
equal(normal.observerInstances[0].options.rootMargin, '-64px 0px -55% 0px', 'observer margins must account for the sticky navigation');
deepEqual([...normal.observerInstances[0].options.threshold], [0, 0.15, 0.4, 0.7], 'observer thresholds must support stable visibility ranking');
assertSingleton(normal.buttons, 0, 'initial observer state');

TARGETS.forEach(([action], index) => {
  const nested = new MiniElement({ parent: normal.buttons[index] });
  normal.document.dispatchEvent({ type: 'click', target: nested });
  equal(normal.sections[index].scrollCalls.length, 1, `${action} delegated click must scroll its controlled section`);
  equal(normal.sections[index].scrollCalls[0].behavior, 'smooth', `${action} must use smooth motion by default`);
  equal(normal.sections[index].scrollCalls[0].block, 'start', `${action} must align the section start`);
  assertSingleton(normal.buttons, index, `${action} click`);
});

normal.observerInstances[0].emit([
  { target: normal.sections[0], isIntersecting: false, intersectionRatio: 0 },
  { target: normal.sections[1], isIntersecting: true, intersectionRatio: 0.72 },
]);
assertSingleton(normal.buttons, 1, 'done section intersection');
normal.observerInstances[0].emit([
  { target: normal.sections[2], isIntersecting: true, intersectionRatio: 0.8 },
]);
assertSingleton(normal.buttons, 2, 'calendar section intersection');
normal.sections[0].rect = { top: -700, bottom: -150 };
normal.sections[1].rect = { top: 0, bottom: 600 };
normal.sections[2].rect = { top: 620, bottom: 1200 };
normal.observerInstances[0].emit([
  { target: normal.sections[2], isIntersecting: false, intersectionRatio: 0 },
]);
assertSingleton(normal.buttons, 1, 'false-only upward intersection retains the visible done section');
normal.observerInstances[0].emit([
  { target: normal.sections[1], isIntersecting: false, intersectionRatio: 0 },
]);
assertSingleton(normal.buttons, 1, 'no-intersection fallback uses the section below the sticky navigation');

const reduced = runScenario({ reducedMotion: true });
reduced.document.dispatchEvent({ type: 'click', target: reduced.buttons[1] });
equal(reduced.sections[1].scrollCalls[0].behavior, 'auto', 'reduced-motion navigation must avoid smooth scrolling');
assertSingleton(reduced.buttons, 1, 'reduced-motion click');

const fallback = runScenario({ reducedMotion: false, intersectionObserver: false });
equal(fallback.observerInstances.length, 0, 'unsupported browsers must not try to construct IntersectionObserver');
assertSingleton(fallback.buttons, 0, 'IntersectionObserver fallback');
fallback.document.dispatchEvent({ type: 'click', target: fallback.buttons[2] });
equal(fallback.sections[2].scrollCalls.length, 1, 'fallback navigation must retain delegated clicking');
assertSingleton(fallback.buttons, 2, 'fallback click');

for (const [name, scenario] of Object.entries({ normal, reduced, fallback })) {
  deepEqual(scenario.counters, { fetch: 0, localStorage: 0, sessionStorage: 0 }, `${name} scenario must remain pure`);
}

console.log(`admin section navigation checks passed: ${assertionCount} assertions`);
