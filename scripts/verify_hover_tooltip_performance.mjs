import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { buildExamAttendance } from '../static/js/admin/features/examAttendance.js';
import './verify_exam_attendance.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const calendarSource = fs.readFileSync(path.join(ROOT, 'static', 'js', 'shared', 'schoolCalendar.js'), 'utf8');
const calendarModule = await import(`data:text/javascript;base64,${Buffer.from(calendarSource).toString('base64')}`);
const semesterTwoSchools = {
  저동고: {
    common: { semesterStart: '8/18(화)' },
    grades: { '2학년::미적분1': { __grade: '2학년', __phase: '미적분1' } },
  },
};
const semesterPayload = {
  activeYear: '2026',
  activeSemester: '2',
  years: {
    2026: {
      activeSemester: '2',
      schools: { 저동고: { common: { final: '06/24~06/30', textbook: '천재(홍)' }, grades: {} } },
      semesters: { 2: { schools: semesterTwoSchools } },
    },
  },
};
assert.equal(calendarModule.getActiveSchoolCalendarSemester(semesterPayload), '2', 'active semester was not resolved');
assert.equal(calendarModule.getSchoolCalendarSchoolMap(semesterPayload), semesterTwoSchools, 'semester 2 school map did not override legacy semester 1 data');
assert.deepEqual(
  calendarModule.resolveSchoolCalendarEntries(semesterPayload, '저동고', '고2').map(entry => ({ phase: entry.phase, semesterStart: entry.semesterStart, final: entry.final || '', textbook: entry.textbook || '' })),
  [{ phase: '미적분1', semesterStart: '8/18(화)', final: '', textbook: '' }],
  'semester 2 entries leaked legacy semester 1 exam or textbook data',
);
const legacyPayload = { activeYear: '2026', activeSemester: '1', years: { 2026: { activeSemester: '1', schools: { 레거시고: { final: '06/30' } } } } };
assert.ok(calendarModule.getSchoolCalendarSchoolMap(legacyPayload).레거시고, 'semester 1 legacy school map fallback broke');

const SOURCE_PATH = path.join(ROOT, 'static', 'js', 'admin', 'features', 'hoverTooltip.js');
const originalSource = fs.readFileSync(SOURCE_PATH, 'utf8');
const source = originalSource
  .replace("import { fetchJsonChecked } from '../../shared/api.js';", 'const fetchJsonChecked = async () => ({});')
  .replace("import { buildExamAttendance, createExamAttendanceLoader } from './examAttendance.js';", 'const buildExamAttendance = globalThis.__buildExamAttendance; const createExamAttendanceLoader = () => ({ peek: () => null, load: () => new Promise(() => {}), invalidate() {} });')
  .replace("import { state } from '../core/state.js';", 'const state = globalThis.__state;')
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => globalThis.__adminDate;")
  .replace(
    "import { resolveSchoolCalendarEntry, resolveSchoolCalendarEntries } from '../../shared/schoolCalendar.js?v=20260814-active-semester1';",
    'const resolveSchoolCalendarEntry = globalThis.__resolveOne; const resolveSchoolCalendarEntries = globalThis.__resolveMany;',
  )
  .replace(
    "import { regularAttendanceDaysForStudent } from '../../shared/selfStudy.js';",
    'const regularAttendanceDaysForStudent = globalThis.__attendanceDays;',
  )
  .replace('export function initHoverTooltip()', 'function initHoverTooltip()')
  .replace('  function attendanceHtml(entry, stu, referenceDate) {', '  globalThis.__attendanceMarkup = attendanceMarkup;\n  globalThis.__pickExam = pickExam;\n  function attendanceHtml(entry, stu, referenceDate) {')
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

const NativeDate = Date;
class FixedDate extends NativeDate {
  constructor(...args) {
    if (args.length) super(...args);
    else super(2026, 8, 4, 12, 0, 0, 0);
  }

  static now() {
    return new FixedDate().getTime();
  }
}

let scheduleResolveCount = 0;
let resolvedScheduleEntries = [];
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
  __buildExamAttendance: buildExamAttendance,
  __adminDate: '2026-09-04',
  __state: { students, schoolCal: {}, progress: {}, videos: [], homeworkBooksBySid: {} },
  __resolveMany() { scheduleResolveCount += 1; return resolvedScheduleEntries; },
  __resolveOne() { return {}; },
  __attendanceDays(student) {
    const selfStudyDays = student?.selfStudyDays || {};
    const days = ['day1', 'day2', 'day3', 'day4', 'day5']
      .filter(field => selfStudyDays[field] !== true)
      .map(field => String(student?.[field] || '').trim())
      .filter(Boolean)
      .slice(0, 4);
    return days.length ? days : ['월', '수'];
  },
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
  Date: FixedDate,
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
assert.equal(context.__attendanceMarkup({total:5, regular:4, pending:1}, {}), '5회 <span class="student-tooltip-exam-pending" style="color:var(--exam-attendance-pending-color, #fda4af)">(+1회 : 보강 잡자!)</span>', 'only the unreserved reminder gets the color span');
assert.equal(context.__attendanceMarkup({total:5, regular:4, pending:0}, {}), '5회', 'no reminder when nothing is pending');
assert.equal(context.__attendanceMarkup({regular:4}, null), '정규 4회 · 보강 확인 중…');
assert.equal(context.__attendanceMarkup({regular:4}, null, true), '정규 4회 · 보강 확인 실패');
assert.equal(context.__attendanceMarkup(null, {}), '-');
assert.ok(!context.__attendanceMarkup({total:'<img>', pending:1}, {}).includes('<img>'), 'numeric projection output remains escaped');

const rolloverCases = [
  ['period start', '2026-10-07', { midterm: '10/7~10/9', final: '12/1' }, '중간'],
  ['period ongoing', '2026-10-08', { midterm: '10/7~10/9', final: '12/1' }, '중간'],
  ['period end', '2026-10-09', { midterm: '10/7~10/9', final: '12/1' }, '중간'],
  ['period passed', '2026-10-10', { midterm: '10/7~10/9', final: '12/1' }, '기말'],
  ['subject exam today', '2026-10-05', { midterm: '10/1~10/9', midtermMath: '10/5(월)', final: '12/1' }, '중간'],
  ['subject exam passed', '2026-10-06', { midterm: '10/1~10/9', midtermMath: '10/5(월)', final: '12/1' }, '기말'],
  ['subject range is not a fixed day', '2026-10-08', { midterm: '10/1~10/9', midtermMath: '10/5~10/7', final: '12/1' }, '중간'],
  ['invalid subject date falls back', '2026-10-08', { midterm: '10/1~10/9', midtermMath: '10/32', final: '12/1' }, '중간'],
  ['final scope only', '2026-10-10', { midterm: '10/7~10/9', finalRange: '적분', finalNote: '기말 안내' }, '기말'],
  ['empty final', '2026-10-10', { midterm: '10/7~10/9' }, '기말'],
  ['past operating date', '2026-09-30', { midterm: '10/1~10/9', final: '12/1' }, '중간'],
  ['old midterm must not shift to next year', '2026-10-10', { midterm: '3/1~3/3' }, '기말'],
  ['hyphen period', '2026-07-03', { midterm: '6/30-7/2', final: '12/1' }, '기말'],
  ['Korean dates', '2026-10-10', { midterm: '10월 7일~10월 9일' }, '기말'],
  ['explicit years', '2026-10-10', { midterm: '2026-10-07~2026-10-09' }, '기말'],
  ['unordered multiple days', '2026-10-08', { midterm: '10/9, 10/7', final: '12/1' }, '중간'],
  ['year crossing ongoing', '2027-01-01', { midterm: '12/31~1/2' }, '중간'],
  ['year crossing passed', '2027-01-03', { midterm: '12/31~1/2' }, '기말'],
  ['future January', '2026-12-20', { midterm: '1/2' }, '중간'],
  ['final-only calendar', '2026-10-07', { final: '12/1' }, '기말'],
];
for (const [label, key, entry, expected] of rolloverCases) {
  const [year, month, day] = key.split('-').map(Number);
  const before = JSON.stringify(entry);
  assert.equal(context.__pickExam(entry, 'auto', new FixedDate(year, month - 1, day)).label, expected, label);
  assert.equal(JSON.stringify(entry), before, `${label}: calendar input was mutated`);
}
assert.equal(context.__pickExam({ midterm: '10/1~10/32' }, 'auto', new FixedDate(2026, 9, 10)).label, '중간', 'invalid end date must not confirm rollover');

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
assert.equal(tip.classList.contains('student-work-layout'), true,
  'unified tooltip must have its final layout before the first animation frame');
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

resolvedScheduleEntries = [{
  phase: '미적분1',
  midterm: '10/7(수)~10/8(목)',
}];
const selfStudyStudent = {
  id: 'sid-self-study',
  name: '자습 제외 학생',
  school: '고국고',
  grade: '고2',
  curriculum: '미적분1',
  day1: '금2',
  day2: '일1',
  day3: '토1',
  selfStudyDays: { day3: true },
};
context.__state.students = [...context.__state.students, selfStudyStudent];
const selfStudyAnchor = new ElementStub({ tagName: 'A', classes: ['stuName'], host });
selfStudyAnchor.dataset.sid = selfStudyStudent.id;
selfStudyAnchor.textContent = selfStudyStudent.name;
context.window.showStudentTooltipForElement(selfStudyAnchor, {
  fixed: true,
  variant: 'today',
  subject: '미적분1',
});
flushFrames();
assert.match(tip.innerHTML, /금2 · 일1/, 'regular attendance days were not rendered');
assert.doesNotMatch(tip.innerHTML, /토1/, 'self-study day leaked into regular attendance days');
assert.match(
  tip.innerHTML,
  /남은출석횟수[\s\S]*9회/,
  'selected-date attendance or a self-study day was counted before the exam',
);
assert.doesNotMatch(tip.innerHTML, /남은출석횟수[\s\S]*10회/, 'selected operating date was counted again');
context.window.hideStudentTooltip();

context.__adminDate = '2026-09-11';
context.window.showStudentTooltipForElement(selfStudyAnchor, {
  fixed: true,
  variant: 'today',
  subject: '미적분1',
});
flushFrames();
assert.match(
  tip.innerHTML,
  /남은출석횟수[\s\S]*7회/,
  'remaining sessions ignored the selected admin date',
);
context.window.hideStudentTooltip();

context.__adminDate = '2026-09-04';
resolvedScheduleEntries = [{
  phase: '미적분1',
  midterm: '10/1(목)~10/7(수)',
  midtermMath: '10/5(월)',
}];
context.window.showStudentTooltipForElement(selfStudyAnchor, {
  fixed: true,
  variant: 'today',
  subject: '미적분1',
});
flushFrames();
assert.match(
  tip.innerHTML,
  /남은출석횟수[\s\S]*9회/,
  'an exact subject exam date did not override the school exam-period start',
);
context.window.hideStudentTooltip();

resolvedScheduleEntries = [
  { phase: '대수', midterm: '9/29(화)~10/2(금)' },
  { phase: '미적분1', midterm: '9/29(화)~10/2(금)' },
];
const sharedPeriodStudent = {
  id: 'sid-shared-period',
  name: '공통 기간 학생',
  school: '공통고',
  grade: '고2',
  curriculum: '확통',
  day1: '토1',
};
context.__state.students = [...context.__state.students, sharedPeriodStudent];
const sharedPeriodAnchor = new ElementStub({ tagName: 'A', classes: ['stuName'], host });
sharedPeriodAnchor.dataset.sid = sharedPeriodStudent.id;
sharedPeriodAnchor.textContent = sharedPeriodStudent.name;
context.window.showStudentTooltipForElement(sharedPeriodAnchor, {
  fixed: true,
  variant: 'today',
  subject: '확통',
});
flushFrames();
assert.match(
  tip.innerHTML,
  /남은출석횟수[\s\S]*4회/,
  'shared school exam period was not used when the academy subject had no exact calendar row',
);
context.window.hideStudentTooltip();
resolvedScheduleEntries = [];

resolvedScheduleEntries = [{ phase: '미적분1', midterm: '10/1~10/5', final: '12/1~12/4', finalMath: '12/3', finalRange: '기말 범위 검증', finalNote: '기말 안내 검증' }];
context.__adminDate = '2026-10-06';
context.window.showStudentTooltipForElement(selfStudyAnchor, { fixed: true, variant: 'log', subject: '미적분1' });
flushFrames();
assert.match(tip.innerHTML, /기말/);
assert.match(tip.innerHTML, /12\/1~12\/4/);
assert.match(tip.innerHTML, /12\/3/);
assert.match(tip.innerHTML, /기말 범위 검증/);
assert.match(tip.innerHTML, /기말 안내 검증/);
assert.doesNotMatch(tip.innerHTML, /10\/1~10\/5/, 'passed midterm leaked into the final tooltip');
context.window.hideStudentTooltip();
resolvedScheduleEntries = [{ phase: '미적분1', midterm: '10/1~10/5' }];
context.window.showStudentTooltipForElement(selfStudyAnchor, { fixed: true, variant: 'log', subject: '미적분1' });
flushFrames();
assert.match(tip.innerHTML, /기말/);
assert.doesNotMatch(tip.innerHTML, /10\/1~10\/5|시험 전 출석 횟수/, 'empty final must not reuse passed midterm dates or attendance');
context.window.hideStudentTooltip();
resolvedScheduleEntries = [
  { phase: '대수', midterm: '10/1~10/5', final: '12/1~12/4' },
  { phase: '미적분1', midterm: '10/1~10/5', final: '12/1~12/4' },
];
context.window.showStudentTooltipForElement(sharedPeriodAnchor, { fixed: true, variant: 'log', subject: '확통' });
flushFrames();
assert.match(tip.innerHTML, /기말/);
assert.match(tip.innerHTML, /12\/1~12\/4/, 'shared school period did not roll over to final');
context.window.hideStudentTooltip();

context.__adminDate = '2026-09-13';
resolvedScheduleEntries = [{ phase: '미적분1', midterm: '10/5(월)' }];
const doubleClassStudent = {
  id: 'sid-double-class', name: '연강 검증 학생', school: '합성고', grade: '고2',
  curriculum: '미적분1', day1: '일1', day2: '일2',
};
context.__state.students = [...context.__state.students, doubleClassStudent];
const doubleClassAnchor = new ElementStub({ tagName: 'A', classes: ['stuName'], host });
doubleClassAnchor.dataset.sid = doubleClassStudent.id;
doubleClassAnchor.textContent = doubleClassStudent.name;
for (const variant of ['today', 'log']) {
  context.window.showStudentTooltipForElement(doubleClassAnchor, {
    fixed: true, variant, subject: '미적분1',
  });
  flushFrames();
  assert.match(tip.innerHTML, /일1\s*[·]\s*일2/, 'both regular slots remain visible');
  assert.match(tip.innerHTML, /data-exam-attendance="0">정규 6회/, `${variant} popup must show six sessions across three double-class Sundays`);
  context.window.hideStudentTooltip();
}
resolvedScheduleEntries = [];

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
assert.match(originalSource, /visibleExamEntries = examEntries\.filter\(hasExamSchedule\)/, 'empty active-semester exam rows are still rendered');
assert.doesNotMatch(originalSource, /levelBadgeHtml|student-tooltip-level-badge/, 'student tooltip still renders the student difficulty badge');
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
