import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_PATH = path.join(ROOT, 'static', 'js', 'admin', 'features', 'hoverTooltip.js');
const originalSource = fs.readFileSync(SOURCE_PATH, 'utf8');
const source = originalSource
  .replace("import { state } from '../core/state.js';", 'const state = globalThis.__state;')
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => globalThis.__adminDate;")
  .replace(
    "import { resolveSchoolCalendarEntry, resolveSchoolCalendarEntries } from '../../shared/schoolCalendar.js';",
    'const resolveSchoolCalendarEntry = globalThis.__resolveOne; const resolveSchoolCalendarEntries = globalThis.__resolveMany;',
  )
  .replace(
    "import { regularAttendanceDaysForStudent } from '../../shared/selfStudy.js';",
    'const regularAttendanceDaysForStudent = globalThis.__attendanceDays;',
  )
  .replace('export function initHoverTooltip()', 'function initHoverTooltip()')
  .concat('\nglobalThis.__initHoverTooltip = initHoverTooltip;\n');

class ElementStub {
  constructor({ id = '', tagName = 'DIV', classes = [], host = null, anchor = null } = {}) {
    this.id = id;
    this.tagName = tagName;
    this.dataset = {};
    this.attributes = new Map();
    this.style = {};
    this.textContent = '';
    this._host = host;
    this._anchor = anchor;
    this._listeners = new Map();
    this._classes = new Set(classes);
    this._innerHTML = '';
    this.innerHTMLWrites = 0;
    this.rectReads = 0;
    this.classList = {
      add: value => this._classes.add(value),
      remove: value => this._classes.delete(value),
      contains: value => this._classes.has(value),
    };
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.innerHTMLWrites += 1;
  }

  get innerHTML() { return this._innerHTML; }

  addEventListener(type, listener) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(listener);
  }

  listeners(type) { return this._listeners.get(type) || []; }
  setAttribute(name, value) { this.attributes.set(String(name), String(value)); }
  getAttribute(name) { return this.attributes.get(String(name)) ?? null; }
  removeAttribute(name) { this.attributes.delete(String(name)); }
  setPointerCapture() {}
  releasePointerCapture() {}
  querySelector() { return null; }
  contains(other) { return other === this || other?._anchor === this; }

  closest(selector) {
    if (selector === 'a.stuName') {
      if (this.tagName === 'A' && this._classes.has('stuName')) return this;
      return this._anchor || null;
    }
    if (selector === '#todayWrap, #doneWrap, #allWrap') {
      if (['todayWrap', 'doneWrap', 'allWrap'].includes(this.id)) return this;
      return this._host || this._anchor?._host || null;
    }
    return null;
  }

  getBoundingClientRect() {
    this.rectReads += 1;
    return { left: 40, top: 60, right: 160, bottom: 100, width: 360, height: 240 };
  }
}

const hosts = Object.fromEntries(
  ['todayWrap', 'doneWrap', 'allWrap'].map(id => [id, new ElementStub({ id })]),
);
const documentListeners = new Map();
const windowListeners = new Map();
const appended = [];
const microtasks = [];
const queueMicrotask = callback => microtasks.push(callback);
const flushMicrotasks = () => {
  while (microtasks.length) microtasks.shift()();
};

const document = {
  activeElement: null,
  body: { appendChild(element) { appended.push(element); } },
  createElement() { return new ElementStub(); },
  getElementById(id) { return hosts[id] || null; },
  querySelector() { return null; },
  addEventListener(type, listener) {
    if (!documentListeners.has(type)) documentListeners.set(type, []);
    documentListeners.get(type).push(listener);
  },
};

let frameSequence = 0;
const frames = new Map();
const requestAnimationFrame = callback => {
  frameSequence += 1;
  frames.set(frameSequence, callback);
  return frameSequence;
};
const cancelAnimationFrame = id => frames.delete(id);
const flushFrames = () => {
  while (frames.size) {
    const batch = [...frames.values()];
    frames.clear();
    batch.forEach(callback => callback());
  }
};

let scheduleResolveCount = 0;
const students = Array.from({ length: 10_000 }, (_, index) => ({
  id: `sid-${index}`,
  name: `학생 ${index}`,
  school: '합성고등학교',
  grade: '1',
  level: index % 2 ? '중상' : '상',
  curriculum: '공수1',
  subCurriculum: '기초',
}));

const context = {
  __adminDate: '2026-08-13',
  __state: { students, schoolCal: {}, progress: {}, videos: [], homeworkBooksBySid: {} },
  __resolveMany() { scheduleResolveCount += 1; return []; },
  __resolveOne() { return {}; },
  __attendanceDays() { return ['월', '수']; },
  document,
  window: {
    innerWidth: 1440,
    innerHeight: 900,
    CSS: { escape: value => String(value) },
    addEventListener(type, listener) {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push(listener);
    },
  },
  localStorage: { getItem() { return null; }, setItem() {} },
  Element: ElementStub,
  CustomEvent: class CustomEvent { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } },
  requestAnimationFrame,
  cancelAnimationFrame,
  queueMicrotask,
  console,
  Date,
  Math,
  Number,
  String,
  Array,
  Object,
  Map,
  Set,
  RegExp,
  JSON,
};
context.window.window = context.window;
context.window.document = document;

vm.createContext(context);
vm.runInContext(source, context, { filename: 'hoverTooltip.js' });
context.__initHoverTooltip();
context.__initHoverTooltip();

for (const host of Object.values(hosts)) {
  for (const type of ['pointerover', 'pointermove', 'pointerout', 'focusin', 'focusout', 'keydown']) {
    assert.equal(host.listeners(type).length, 1, `${host.id} ${type} listener duplicated`);
  }
}
assert.equal(documentListeners.get('today:rendered')?.length, 1, 'today:rendered listener duplicated');
assert.equal(documentListeners.get('all:rendered')?.length, 1, 'all:rendered listener duplicated');
assert.equal(appended.length, 0, 'tooltip mounted before first interaction');

const host = hosts.todayWrap;
const anchor = new ElementStub({ tagName: 'A', classes: ['stuName'], host });
anchor.dataset.sid = 'sid-9999';
anchor.textContent = '학생 9999';
const firstChild = new ElementStub({ host, anchor });
const secondChild = new ElementStub({ host, anchor });
const over = host.listeners('pointerover')[0];
const move = host.listeners('pointermove')[0];
const out = host.listeners('pointerout')[0];
const focusIn = host.listeners('focusin')[0];
const focusOut = host.listeners('focusout')[0];
const keyDown = host.listeners('keydown')[0];

over({ target: firstChild, relatedTarget: null, clientX: 110, clientY: 120 });
assert.equal(appended.length, 1, 'tooltip was not mounted on first student hover');
const tip = appended[0];
assert.match(tip.innerHTML, /학생 9999/, 'large-roster SID lookup resolved the wrong student');
assert.equal(anchor.getAttribute('aria-describedby'), 'adminSchoolTip', 'pointer tooltip has no described trigger');
assert.equal(tip.innerHTMLWrites, 1, 'first hover rendered more than once');
assert.equal(tip.rectReads, 0, 'first hover forced layout before animation frame');

for (let index = 0; index < 500; index += 1) {
  over({ target: index % 2 ? firstChild : secondChild, relatedTarget: firstChild, clientX: 120 + index, clientY: 140 });
  move({ target: firstChild, clientX: 200 + index, clientY: 240 });
}
assert.equal(tip.innerHTMLWrites, 1, 'internal pointerover rebuilt the same tooltip');
assert.equal(frames.size, 1, 'pointer movement was not coalesced to one animation frame');
assert.equal(tip.rectReads, 0, 'pointer movement forced synchronous layout');
flushFrames();
assert.equal(tip.rectReads, 1, 'first visible placement did not measure exactly once');

for (let index = 0; index < 500; index += 1) {
  move({ target: firstChild, clientX: 500 + index, clientY: 300 });
}
assert.equal(frames.size, 1, 'second movement burst was not coalesced');
flushFrames();
assert.equal(tip.rectReads, 1, 'cached tooltip dimensions were not reused across movement frames');
assert.equal(scheduleResolveCount, 1, 'same-anchor hover rebuilt schedule content');

out({ target: firstChild, relatedTarget: new ElementStub(), clientX: 0, clientY: 0 });
assert.equal(tip.style.display, 'none', 'pointerout did not hide the hover tooltip');
assert.equal(anchor.getAttribute('aria-describedby'), null, 'pointerout left a stale tooltip description token');
over({ target: firstChild, relatedTarget: null, clientX: 140, clientY: 160 });
flushFrames();
assert.equal(tip.innerHTMLWrites, 2, 're-enter did not render the tooltip');
assert.equal(scheduleResolveCount, 2, 're-enter reused stale tooltip HTML');

out({ target: firstChild, relatedTarget: new ElementStub(), clientX: 0, clientY: 0 });
students[9999].school = '수정된 학교';
over({ target: firstChild, relatedTarget: null, clientX: 150, clientY: 170 });
flushFrames();
assert.match(tip.innerHTML, /수정된 학교/, 'in-place student edits left stale tooltip HTML');
assert.equal(scheduleResolveCount, 3, 'in-place student edit did not rebuild tooltip content');

for (const listener of documentListeners.get('today:rendered') || []) listener({ type: 'today:rendered' });
for (const hostElement of Object.values(hosts)) {
  assert.equal(hostElement.listeners('pointerover').length, 1, `${hostElement.id} rebound pointerover after render`);
}
assert.equal(tip.style.display, 'none', 'render refresh left a stale hover tooltip visible');
over({ target: firstChild, relatedTarget: null, clientX: 160, clientY: 180 });
flushFrames();
assert.equal(scheduleResolveCount, 4, 'render refresh did not rebuild tooltip HTML');

const replacementStudents = students.slice();
replacementStudents[9999] = { ...replacementStudents[9999], name: '교체된 학생' };
context.__state.students = replacementStudents;
for (const listener of documentListeners.get('today:rendered') || []) listener({ type: 'today:rendered' });
anchor.textContent = '교체된 학생';
over({ target: firstChild, relatedTarget: null, clientX: 180, clientY: 200 });
flushFrames();
assert.match(tip.innerHTML, /교체된 학생/, 'student index did not rebuild after roster replacement');
assert.equal(scheduleResolveCount, 5, 'roster replacement did not rebuild tooltip content');

let progressOwnKeys = 0;
context.__state.progress = new Proxy({}, {
  ownKeys() { progressOwnKeys += 1; return []; },
});
context.window.showStudentTooltipForElement(anchor, {
  fixed: true,
  variant: 'log',
  layout: 'student-work',
});
assert.equal(progressOwnKeys, 0, 'video-disabled fixed tooltip still enumerated progress dates');
context.window.hideStudentTooltip();

anchor.setAttribute('aria-describedby', 'existing-help');
document.activeElement = anchor;
focusIn({ target: anchor });
flushFrames();
assert.equal(tip.getAttribute('role'), 'tooltip', 'keyboard hover did not expose role=tooltip');
assert.equal(tip.getAttribute('aria-hidden'), 'false', 'keyboard hover remained hidden from accessibility APIs');
assert.equal(tip.getAttribute('aria-label'), null, 'generic tooltip label masked the tooltip content');
assert.equal(anchor.getAttribute('aria-describedby'), 'existing-help adminSchoolTip', 'tooltip description did not preserve existing tokens');

context.window.innerWidth = 390;
for (const listener of windowListeners.get('resize') || []) listener({ type: 'resize' });
flushFrames();
assert.ok(Number.parseFloat(tip.style.left) >= 12, 'mobile resize placed the tooltip past the left viewport edge');
assert.ok(Number.parseFloat(tip.style.left) <= 18, 'mobile resize left the tooltip past the right viewport edge');
context.window.innerWidth = 1440;
for (const listener of windowListeners.get('resize') || []) listener({ type: 'resize' });
flushFrames();

let enterPrevented = false;
keyDown({
  key: 'Enter',
  target: anchor,
  preventDefault() { enterPrevented = true; },
  stopPropagation() {},
});
assert.equal(enterPrevented, false, 'keyboard tooltip blocked the student link Enter action');

const otherAnchor = new ElementStub({ tagName: 'A', classes: ['stuName'], host });
otherAnchor.dataset.sid = 'sid-1';
otherAnchor.textContent = '학생 1';
const otherChild = new ElementStub({ host, anchor: otherAnchor });
move({ target: otherChild, clientX: 700, clientY: 300 });
assert.match(tip.innerHTML, /교체된 학생/, 'pointer movement replaced the focused student tooltip');

focusOut({ target: anchor });
document.activeElement = otherAnchor;
focusIn({ target: otherAnchor });
flushFrames();
flushMicrotasks();
assert.equal(anchor.getAttribute('aria-describedby'), 'existing-help', 'focus transition left a stale description token');
assert.equal(otherAnchor.getAttribute('aria-describedby'), 'adminSchoolTip', 'next focused student was not linked to the tooltip');
assert.match(tip.innerHTML, /학생 1/, 'stale focusout callback closed or replaced the next student tooltip');

over({ target: firstChild, relatedTarget: null, clientX: 180, clientY: 210 });
assert.match(tip.innerHTML, /학생 1/, 'pointer hover overrode keyboard focus ownership');
focusOut({ target: otherAnchor });
document.activeElement = null;
flushMicrotasks();
flushFrames();
assert.equal(otherAnchor.getAttribute('aria-describedby'), null, 'blur left a stale tooltip description token');
assert.match(tip.innerHTML, /교체된 학생/, 'blur did not restore the currently hovered student');

out({ target: firstChild, relatedTarget: new ElementStub(), clientX: 0, clientY: 0 });
assert.equal(tip.style.display, 'none', 'pointer exit after focus restoration did not hide the tooltip');

document.activeElement = anchor;
focusIn({ target: anchor });
flushFrames();
let escapePrevented = false;
let escapeStopped = false;
keyDown({
  key: 'Escape',
  target: anchor,
  preventDefault() { escapePrevented = true; },
  stopPropagation() { escapeStopped = true; },
});
assert.equal(escapePrevented, true, 'Escape did not dismiss the keyboard tooltip');
assert.equal(escapeStopped, true, 'Escape leaked to the global modal/search handler');
assert.equal(document.activeElement, anchor, 'Escape moved focus away from the student link');
assert.equal(anchor.getAttribute('aria-describedby'), 'existing-help', 'Escape removed an unrelated description token');
assert.equal(tip.style.display, 'none', 'Escape left the keyboard tooltip visible');
let secondEscapePrevented = false;
let secondEscapeStopped = false;
keyDown({
  key: 'Escape',
  target: anchor,
  preventDefault() { secondEscapePrevented = true; },
  stopPropagation() { secondEscapeStopped = true; },
});
assert.equal(secondEscapePrevented, false, 'hidden tooltip swallowed a second Escape key');
assert.equal(secondEscapeStopped, false, 'hidden tooltip blocked the global Escape handler');
over({ target: firstChild, relatedTarget: null, clientX: 190, clientY: 220 });
assert.equal(tip.style.display, 'none', 'pointer activity reopened an Escape-dismissed focused tooltip');
focusOut({ target: anchor });
document.activeElement = null;
flushMicrotasks();

context.window.showStudentTooltipForElement(anchor, { fixed: true, variant: 'log' });
flushFrames();
assert.equal(tip.getAttribute('role'), 'region', 'interactive fixed student panel retained tooltip semantics');
assert.equal(tip.getAttribute('aria-label'), '학생 정보 팝업', 'fixed student panel has no accessible label');
for (const listener of documentListeners.get('today:rendered') || []) listener({ type: 'today:rendered' });
assert.equal(tip.style.display, 'block', 'today refresh closed the fixed student panel');
context.window.hideStudentTooltip();

document.activeElement = anchor;
focusIn({ target: anchor });
flushFrames();
for (const listener of documentListeners.get('all:rendered') || []) listener({ type: 'all:rendered' });
assert.equal(tip.style.display, 'none', 'all-students rerender left a stale keyboard tooltip visible');
assert.equal(anchor.getAttribute('aria-describedby'), 'existing-help', 'all-students rerender left a stale description token');
flushFrames();
assert.equal(tip.style.display, 'none', 'fixed tooltip hide was reversed by a delayed placement frame');
assert.equal(tip.classList.contains('student-work-layout'), false, 'stale fixed placement restored a hidden student-work layout');

const duplicateStudents = context.__state.students.slice();
duplicateStudents[2] = { ...duplicateStudents[2], name: '동명이인', school: '첫 번째 학교' };
duplicateStudents[3] = { ...duplicateStudents[3], name: '동명이인', school: '두 번째 학교' };
context.__state.students = duplicateStudents;
for (const listener of documentListeners.get('all:rendered') || []) listener({ type: 'all:rendered' });
const allAnchor = new ElementStub({ tagName: 'A', classes: ['stuName'], host: hosts.allWrap });
allAnchor.dataset.id = 'sid-3';
allAnchor.textContent = '동명이인';
document.activeElement = allAnchor;
hosts.allWrap.listeners('focusin')[0]({ target: allAnchor });
flushFrames();
assert.match(tip.innerHTML, /두 번째 학교/, 'data-id-only duplicate-name link resolved the wrong student SID');
assert.doesNotMatch(tip.innerHTML, /첫 번째 학교/, 'duplicate-name fallback overrode the exact data-id student');
hosts.allWrap.listeners('focusout')[0]({ target: allAnchor });
document.activeElement = null;
flushMicrotasks();

context.window.showStudentTooltipForElement(anchor, { fixed: true, variant: 'log' });
flushFrames();
const rectReadsBeforeDrag = tip.rectReads;
const pointerDown = tip.listeners('pointerdown')[0];
pointerDown({
  button: 0,
  pointerId: 7,
  clientX: 200,
  clientY: 220,
  preventDefault() {},
});
assert.equal(tip.rectReads, rectReadsBeforeDrag + 1, 'drag start did not measure tooltip exactly once');
for (let index = 0; index < 500; index += 1) {
  for (const listener of documentListeners.get('pointermove') || []) {
    listener({ pointerId: 7, clientX: 210 + index, clientY: 230 + index });
  }
}
assert.equal(tip.rectReads, rectReadsBeforeDrag + 1, 'fixed tooltip drag forced layout on pointer movement');
for (const listener of documentListeners.get('pointerup') || []) listener({ pointerId: 7 });
assert.equal(tip.rectReads, rectReadsBeforeDrag + 1, 'fixed tooltip drag end forced an extra layout read');
context.window.hideStudentTooltip();

const findStudentBlock = originalSource.slice(
  originalSource.indexOf('function findStudent'),
  originalSource.indexOf('// 위치 계산'),
);
assert.ok(findStudentBlock, 'findStudent source block was not found');
assert.doesNotMatch(findStudentBlock, /\.find\s*\(/, 'large-roster lookup still performs linear Array.find');
assert.match(originalSource, /scheduleHoverPlacement\(ev\.clientX, ev\.clientY\)/, 'pointer movement is not routed through the frame scheduler');
assert.match(originalSource, /if \(activeHoverAnchor === a/, 'same-anchor hover render guard is missing');
assert.doesNotMatch(originalSource, /todayTipHtmlBySid|cachedTodayNameTipHtml/, 'cross-entry tooltip HTML cache can retain stale student data');
assert.match(originalSource, /placementEpoch !== renderEpoch/, 'delayed fixed-tooltip placement lacks a stale-render guard');
assert.doesNotMatch(originalSource, /min-width:\s*420px/, 'compact tooltip still forces a clipped 420px mobile width');
assert.match(originalSource, /width:min\(420px, calc\(92vw - 36px\)\)/, 'compact tooltip lacks a viewport-bounded inner width');
assert.match(originalSource, /anchorEl\?\.dataset\?\.id/, 'all-students data-id is not used for exact SID lookup');
assert.match(originalSource, /resizePlacementFrame = requestAnimationFrame/, 'visible hover is not repositioned after viewport resize');
assert.match(originalSource, /el\.setAttribute\('role', 'tooltip'\)/, 'hover tooltip semantics are missing');
assert.match(originalSource, /el\.setAttribute\('role', 'region'\)/, 'fixed interactive panel is not separated from tooltip semantics');
const allMainSource = fs.readFileSync(path.join(ROOT, 'static', 'js', 'all', 'main.js'), 'utf8');
assert.match(allMainSource, /initHoverTooltip as initAdminHoverTooltip/, 'all-students startup lacks the lightweight tooltip bridge');
assert.match(allMainSource, /document\.dispatchEvent\(new CustomEvent\('all:rendered'\)\)/, 'all-students rerenders do not invalidate stale tooltip state');
assert.doesNotMatch(allMainSource, /import .*studentRecordPopup/, 'all-students startup eagerly imported the full popup graph');
const renderProgressBlock = originalSource.slice(
  originalSource.indexOf('function renderProgressTables'),
  originalSource.indexOf('// 학생 찾기'),
);
assert.match(renderProgressBlock, /if \(!includeVideo\) return '';/, 'fixed tooltip still scans progress when video rows are disabled');
assert.ok(
  renderProgressBlock.indexOf("if (!includeVideo) return '';") < renderProgressBlock.indexOf('Object.keys(state.progress'),
  'fixed-tooltip progress guard runs after the full progress scan',
);

console.log(JSON.stringify({
  ok: true,
  rosterSize: replacementStudents.length,
  pointerEvents: 1003,
  tooltipHtmlWrites: tip.innerHTMLWrites,
  layoutReads: tip.rectReads,
  delegatedHostListenerCount: Object.values(hosts).reduce(
    (total, item) => total + ['pointerover', 'pointermove', 'pointerout', 'focusin', 'focusout', 'keydown'].reduce((sum, type) => sum + item.listeners(type).length, 0),
    0,
  ),
  accessibility: 'focus/blur/Escape/ARIA/fixed-role/mobile-width',
}, null, 2));
