import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
const args = process.argv.slice(2), rootArg = args.indexOf('--source-root');
const root = path.resolve(rootArg < 0 ? path.join(path.dirname(fileURLToPath(import.meta.url)), '..') : args[rootArg + 1]);
const strip = text => text.replace(/^import[\s\S]*?;\r?\n/gm, '').replace(/\bexport\s+/g, '');
const read = file => fs.readFileSync(path.join(root, 'static/js', file), 'utf8');
const same = (actual, expected) => assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected);
const flush = async () => { for (let i = 0; i < 32; i++) await Promise.resolve(); };
class Element {
  constructor(id = '', owner = null) {
    Object.assign(this, { id, owner, dataset: {}, handlers: {}, children: [], style: { setProperty() {} }, attrs: {},
      value: '', textContent: '', innerHTML: '', hidden: true, disabled: false, isConnected: true });
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); this.owner?.registrations.push([this.id, type]); }
  fire(type, detail) { return (this.handlers[type] || []).map(fn => fn({ target: this, currentTarget: this, detail, preventDefault() {}, stopPropagation() {}, stopImmediatePropagation() {} })); }
  querySelector(q) { return q.startsWith('#') ? this.owner?.ids.get(q.slice(1)) || null : null; }
  querySelectorAll() { return []; } closest() { return null; } getClientRects() { return []; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k] ?? null; } removeAttribute(k) { delete this.attrs[k]; }
  append(...xs) { this.children.push(...xs); } appendChild(x) { this.children.push(x); return x; } replaceChildren(...xs) { this.children = xs; }
  contains(x) { return this.children.includes(x); } insertAdjacentHTML() {} remove() {} focus() {} scrollIntoView() {}
}
const specs = [
  { file: 'calendar', init: 'initCalendar', ids: 'calendar makeupPlanner', required: 'calendar',
    bindings: [['calendar','pointerdown'],['calendar','click'],['calendar','wheel'],['document','keydown'],['body','click'],['document','admin:refresh'],['document','attendance:updated'],['document','admin:date-change']],
    urls: ['/api/extra-attend','/api/weekend-slots','/api/makeup-carryover','/api/absent','/api/school-calendar'] },
  { file: 'studentAccounts', init: 'initStudentAccounts',
    ids: 'studentAccountsOpen studentAccountsModal studentAccountsClose studentAccountsSearch studentAccountsFilter studentAccountsRefresh studentAccountsStatus studentAccountsList studentActivationCodePanel studentActivationCodeValue studentActivationCodeCopy studentActivationCodeDismiss',
    required: 'studentAccountsOpen studentAccountsModal studentAccountsClose studentAccountsSearch studentAccountsFilter studentAccountsRefresh studentAccountsStatus studentAccountsList studentActivationCodePanel studentActivationCodeValue studentActivationCodeCopy studentActivationCodeDismiss',
    bindings: [['studentAccountsOpen','click'],['studentAccountsClose','click'],['studentActivationCodeDismiss','click'],['studentAccountsRefresh','click'],['studentAccountsSearch','input'],['studentAccountsFilter','change'],['studentAccountsModal','click'],['studentAccountsModal','keydown'],['studentActivationCodeCopy','click']], urls: [],
    open: 'studentAccountsOpen', close: 'studentAccountsClose', modal: 'studentAccountsModal', openUrl: '/api/student-accounts' },
  { file: 'studentFocus', init: 'initStudentFocus',
    ids: 'studentFocusOpen studentFocusAdminModal studentFocusAdminClose studentFocusAdminRefresh studentFocusAdminDate studentFocusAdminStatus studentFocusAdminList',
    required: 'studentFocusOpen studentFocusAdminModal studentFocusAdminClose studentFocusAdminRefresh studentFocusAdminDate studentFocusAdminStatus studentFocusAdminList',
    bindings: [['studentFocusOpen','click'],['studentFocusAdminClose','click'],['studentFocusAdminRefresh','click'],['studentFocusAdminModal','keydown']], urls: [],
    open: 'studentFocusOpen', close: 'studentFocusAdminClose', modal: 'studentFocusAdminModal', openUrl: '/api/admin/student-focus/summary?date=2026-10-01' },
  { file: 'studentTestOcrReview', init: 'initStudentTestOcrReview',
    ids: 'studentTestOcrReviewOpen studentTestOcrReviewModal studentTestOcrReviewClose studentTestOcrReviewRefresh studentTestOcrReviewDate studentTestOcrReviewStatus studentTestOcrReviewList studentTestOcrReviewDetail',
    required: 'studentTestOcrReviewOpen studentTestOcrReviewModal studentTestOcrReviewClose studentTestOcrReviewRefresh studentTestOcrReviewDate studentTestOcrReviewStatus studentTestOcrReviewList studentTestOcrReviewDetail',
    bindings: [['studentTestOcrReviewOpen','click'],['studentTestOcrReviewClose','click'],['studentTestOcrReviewRefresh','click'],['studentTestOcrReviewModal','keydown'],['document','admin:date-change']],
    urls: ['/api/student-test-ocr/admin/capabilities','/api/student-test-ocr/admin/pending?date=2026-10-01'],
    open: 'studentTestOcrReviewOpen', close: 'studentTestOcrReviewClose', modal: 'studentTestOcrReviewModal', openUrl: '/api/student-test-ocr/admin/pending?date=2026-10-01' },
  { file: 'adminOperationNotes', init: 'initAdminOperationNotes',
    ids: 'adminOperationNotes adminOperationNoteForm adminOperationNoteInput adminOperationNoteList adminOperationNoteStatus adminOperationNoteSubmit',
    required: 'adminOperationNotes adminOperationNoteForm adminOperationNoteInput adminOperationNoteList',
    bindings: [['adminOperationNoteForm','submit'],['adminOperationNoteInput','input'],['adminOperationNoteList','click']], urls: ['/api/admin-operation-notes'] },
  { file: 'studentLogs', init: 'initStudentLogs', ids: 'studentLogPanel studentLogList studentLogClear studentLogStatus',
    required: 'studentLogPanel studentLogList studentLogClear',
    bindings: [['studentLogClear','click'],['studentLogPanel','click'],['window','student-log:created']], urls: ['/api/student-logs'] },
];
const bodies = {
  '/api/student-accounts': { groups: [] },
  '/api/admin/student-focus/summary?date=2026-10-01': { ok: true, date: '2026-10-01', serverNow: '2026-10-01T00:00:00Z', classes: [] },
  '/api/student-test-ocr/admin/capabilities': { enabled: true, review: true },
  '/api/student-test-ocr/admin/pending?date=2026-10-01': { submissions: [] },
  '/api/admin-operation-notes': { notes: [] }, '/api/student-logs': { logs: [] },
  '/api/extra-attend': {}, '/api/weekend-slots': {}, '/api/school-calendar': {},
  '/api/makeup-carryover': { by_absence: {}, manual: {} }, '/api/absent': { by_date: {}, by_student: {}, by_slot: {} },
};
function fixture(spec, bodyOverrides = {}) {
  const f = { ids: new Map(), registrations: [], calls: [], constructors: 0, renders: 0 };
  const document = new Element('document', f); document.body = new Element('body', f);
  document.getElementById = id => f.ids.get(id) || null; document.createElement = tag => new Element(tag, f);
  const ctx = { document, Element, HTMLElement: Element, console: { error() {}, warn() {} },
    $: id => f.ids.get(id) || null, state: { students: [], schoolCal: {}, absences: {}, absentByDate: {}, absentSlotsByDate: {} },
    getAdminDate: () => '2026-10-01', toast() {}, applySearchPlaceholder() {}, matchesSearchKey: () => true,
    normalizeSearch: String, studentSearchKey: () => '', requestAnimationFrame: fn => fn(), setTimeout: () => 0,
    localStorage: { getItem: () => null, setItem() {} }, navigator: { clipboard: { writeText: async () => {} } },
    CustomEvent: class { constructor(type, options = {}) { this.type = type; Object.assign(this, options); } },
    fetch: async (url, opt = {}) => {
      assert.equal(opt.method || 'GET', 'GET', 'initializer made a write');
      assert.ok(Object.hasOwn(bodies, url), 'unexpected URL ' + url); f.calls.push(url);
      return { ok: true, status: 200, headers: { get: () => 'test-revision' }, json: async () => JSON.parse(JSON.stringify(bodyOverrides[url] ?? bodies[url])) };
    } };
  ctx.window = ctx; ctx.addEventListener = (type, fn) => { (ctx.handlers[type] ||= []).push(fn); f.registrations.push(['window',type]); }; ctx.handlers = {};
  vm.createContext(ctx);
  const expose = (file, names) => vm.runInContext('(function(){' + strip(read(file)) + '\nObject.assign(globalThis,{' + names + '});})();', ctx);
  expose('shared/api.js', 'ensureOk,fetchJson,fetchJsonChecked,fetchJsonOr,sendJson');
  expose('admin/core/api.js', 'api');
  if (spec.file === 'calendar') {
    expose('shared/schoolCalendar.js', 'flattenSchoolCalendarRows,getActiveSchoolCalendarYear,normalizeSchoolCalendarSubject');
    ctx.normalizeExamSubject = ctx.normalizeSchoolCalendarSubject;
    expose('admin/features/makeupPending.js', 'buildPendingMakeups,buildActiveScheduledMakeupRows,buildScheduledMakeupRows,formatMakeupDate,formatMakeupCopyText,makeupOriginalAbsenceId');
  }
  f.library = { Calendar: class {
    constructor() { f.constructors++; this.view = { activeStart: new Date('2026-09-21'), activeEnd: new Date('2026-10-26') }; }
    render() { f.renders++; } removeAllEvents() {} addEventSource() {} changeView() {}
  } };
  ctx.FullCalendar = f.library;
  expose('admin/features/' + spec.file + '.js', spec.init); f.init = ctx[spec.init]; f.ctx = ctx;
  f.mount = (missing = null) => { for (const id of spec.ids.split(' ')) if (id !== missing && !f.ids.has(id)) f.ids.set(id, new Element(id, f)); };
  return f;
}
async function checkInitialized(spec, f, calendarCounts = [1,1]) {
  f.init(); f.init(); await flush();
  same(f.registrations.slice().sort(), spec.bindings.slice().sort()); same(f.calls.slice().sort(), spec.urls.slice().sort());
  same([f.constructors,f.renders], spec.file === 'calendar' ? calendarCounts : [0,0]);
  if (spec.open) {
    const before = f.calls.length; f.ids.get(spec.open).fire('click'); await flush();
    same(f.calls.slice(before), [spec.openUrl]); same(f.ids.get(spec.modal).hidden, false);
    f.ids.get(spec.close).fire('click'); await flush(); same(f.ids.get(spec.modal).hidden, true);
  }
}
let cases = 0;
for (const spec of specs) {
  const complete = fixture(spec); complete.mount(); await checkInitialized(spec, complete); cases++;
  const late = fixture(spec); late.init(); same([late.registrations,late.calls,late.constructors], [[],[],0]);
  late.mount(); await checkInitialized(spec, late); cases++;
  for (const missing of spec.required.split(' ')) {
    const partial = fixture(spec); partial.mount(missing); partial.init(); await flush();
    same([partial.registrations,partial.calls,partial.constructors], [[],[],0]);
    partial.mount(); await checkInitialized(spec, partial); cases++;
  }
}
for (const badLibrary of [undefined, {}]) {
  const spec = specs[0], f = fixture(spec); f.mount();
  if (badLibrary === undefined) delete f.ctx.FullCalendar; else f.ctx.FullCalendar = badLibrary;
  assert.throws(f.init, /FullCalendar.*not available/); same([f.registrations,f.calls,f.constructors], [[],[],0]);
  f.ctx.FullCalendar = f.library; await checkInitialized(spec, f); cases++;
}
for (const phase of ['constructor', 'render']) {
  const spec = specs[0], f = fixture(spec); f.mount();
  f.ctx.FullCalendar = { Calendar: class extends f.library.Calendar {
    constructor(...args) { super(...args); if (phase === 'constructor') throw new Error('transient constructor failure'); }
    render() { super.render(); throw new Error('transient render failure'); }
  } };
  assert.throws(f.init, /transient/); same([f.registrations,f.calls], [[],[]]);
  f.ctx.FullCalendar = f.library; await checkInitialized(spec, f, phase === 'constructor' ? [2,1] : [2,2]); cases++;
}
for (const payload of [{}, {enabled:false,review:true}, {enabled:true,review:false}]) {
  const spec=specs.find(item=>item.file==='studentTestOcrReview');
  const f=fixture(spec, {'/api/student-test-ocr/admin/capabilities':payload});f.mount();f.init();await flush();
  f.ctx.document.fire('admin:date-change');f.ctx.document.fire('admin:date-change');await flush();
  same(f.calls,['/api/student-test-ocr/admin/capabilities']);
  same(f.ids.get(spec.open).hidden,true);cases++;
}
for (const feature of ['studentFocus','studentTestOcrReview']) {
  const spec=specs.find(item=>item.file===feature),f=fixture(spec);f.mount();f.init();await flush();
  const opener=f.ids.get(spec.open);let focused=0;opener.focus=()=>{focused++;};f.ctx.document.activeElement=opener;
  opener.fire('click');await flush();let prevented=0,stopped=0;
  f.ids.get(spec.modal).handlers.keydown[0]({key:'Escape',preventDefault(){prevented++;},stopPropagation(){stopped++;}});
  same([prevented,stopped,focused,f.ids.get(spec.modal).hidden],[1,1,1,true]);cases++;
}
console.log('PASS admin initializer idempotence: ' + cases + ' full-module/export/recovery/OFF-capability/Escape-focus cases');
