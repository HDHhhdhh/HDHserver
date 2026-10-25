import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const sourceRoot = args.includes('--source-root') ? args[args.indexOf('--source-root') + 1] : root;
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : '';
const read = relative => fs.readFileSync(path.join(sourceRoot, relative), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const gate = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const response = (data = {}, status = 200) => ({ ok: status < 400, status, json: async () => data });
function element(id = '') {
  const classes = new Set();
  return {
    id, dataset: {}, value: '', textContent: '', innerHTML: '', disabled: false, readOnly: false,
    style: {}, listeners: {}, isContentEditable: false,
    classList: { add() {}, remove() {}, toggle() {}, contains: key => classes.has(key) },
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); },
    setAttribute() {}, removeAttribute() {}, focus() {}, blur() {},
    querySelector: () => null, querySelectorAll: () => [],
  };
}
function storage() {
  const values = new Map();
  return { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) };
}

async function authChecks() {
  function harness(fetch) {
    const ids = new Map(['spin', 'msg', 'modalMsg', 'loginBtn', 'pw', 'sid', 'goBtn', 'changeBtn',
      'saveChangeBtn', 'curPw', 'newId', 'newPw', 'loggedBox', 'loginBox'].map(id => [id, element(id)]));
    const document = { ...element('document'), getElementById: id => ids.get(id) || null };
    const sandbox = vm.createContext({ document, window: element('window'), fetch, localStorage: storage(),
      sessionStorage: storage(), location: { href: 'before' }, console, setTimeout: () => 1 });
    vm.runInContext(read('static/js/auth.js'), sandbox);
    ids.get('sid').value = 'QA'; ids.get('pw').value = 'QA password';
    ids.get('curPw').value = 'QA password'; ids.get('newId').value = 'QA new';
    return { ids, sandbox, document };
  }
  for (const name of ['login', 'switchAndGo', 'saveChange', 'autoLogin']) {
    const { ids, sandbox } = harness(async () => { throw new TypeError('synthetic offline'); });
    sandbox.localStorage.setItem('studentToken', 'existing-token');
    sandbox.localStorage.setItem('studentSid', 'old-SID');
    await vm.runInContext(name === 'switchAndGo' ? "switchAndGo('new-SID')" : `${name}()`, sandbox);
    assert.equal(ids.get('spin').style.display, 'none', `${name} leaves spinner running`);
    assert.equal(sandbox.localStorage.getItem('studentToken'), 'existing-token');
    assert.equal(sandbox.localStorage.getItem('studentSid'), 'old-SID');
    assert.equal(sandbox.location.href, 'before');
    assert.ok((name === 'saveChange' ? ids.get('modalMsg') : ids.get('msg')).textContent);
  }
  for (const status of [503, 401]) {
    const { ids, sandbox } = harness(async () => response({ ok: false }, status));
    sandbox.localStorage.setItem('studentToken', 'existing-token');
    sandbox.localStorage.setItem('studentSid', 'old-SID');
    await vm.runInContext('autoLogin()', sandbox);
    assert.equal(ids.get('spin').style.display, 'none');
    assert.equal(sandbox.localStorage.getItem('studentToken'), status === 401 ? null : 'existing-token');
  }
  const pending = gate(); let requests = 0;
  const { ids } = harness(() => { requests++; return pending.promise; });
  const click = ids.get('loginBtn').listeners.click[0];
  const first = click(); await click();
  assert.equal(requests, 1); assert.equal(ids.get('spin').style.display, 'block');
  pending.reject(new TypeError('offline')); await first;
  assert.equal(ids.get('spin').style.display, 'none');
}

async function attendanceChecks() {
  const source = read('static/js/admin/features/calendar.js');
  const start = source.indexOf('  let attendOpenSequence');
  const end = source.indexOf('  // ───────────── 보강/결석 선택 모달', start);
  assert.ok(start >= 0 && end > start);
  const ids = new Map(['attendModal', 'attendDateTitle', 'attendList', 'attendClose', 'timeGraphWrapForDate',
    'addExtraBtn', 'markAbsentBtn'].map(id => [id, element(id)]));
  const reads = [], graphs = [];
  const sandbox = vm.createContext({ $: id => ids.get(id), document: { body: element('body') }, window: {}, console,
    fetchJsonChecked: url => { const task = gate(); reads.push({ url, ...task }); return task.promise; },
    yoil: () => '목', EXTRA: {}, WEEKEND: {}, availableSlotsForAttendStudent: () => [1],
    slotSortValue: () => 1, slotGroupLabel: () => '1타임', escapeAttr: String, escapeHtml: String,
    parseSlotNumbers: () => [], renderTimeGraphForDate: date => graphs.push(date) });
  vm.runInContext(source.slice(start, end), sandbox);
  const first = vm.runInContext("openAttendModal('2026-10-01')", sandbox);
  assert.equal(ids.get('attendModal').style.display, 'flex');
  assert.equal(ids.get('addExtraBtn').disabled, true);
  const second = vm.runInContext("openAttendModal('2026-10-02')", sandbox);
  const finish = (offset, name) => {
    reads[offset].resolve([{ id: name, name, curriculum: '대수' }]);
    reads[offset + 1].resolve({}); reads[offset + 2].resolve({});
  };
  finish(3, 'B'); await second; finish(0, 'A'); await first;
  assert.match(ids.get('attendList').innerHTML, /B/);
  assert.doesNotMatch(ids.get('attendList').innerHTML, />A/);
  assert.deepEqual(graphs, ['2026-10-02']);
  assert.equal(ids.get('addExtraBtn').disabled, false);
  const closed = vm.runInContext("openAttendModal('2026-10-03')", sandbox);
  ids.get('attendClose').listeners.click[0](); finish(6, 'C'); await closed;
  assert.equal(ids.get('attendModal').style.display, 'none');
  assert.deepEqual(graphs, ['2026-10-02']);
  const failure = vm.runInContext("openAttendModal('2026-10-04')", sandbox);
  reads[9].reject(new Error('503')); reads[10].resolve({}); reads[11].resolve({}); await failure;
  assert.match(ids.get('attendList').textContent, /불러오지 못/);
  assert.equal(ids.get('markAbsentBtn').disabled, true);
}

async function rosterChecks() {
  const students = [
    { id: 'A', personId: 'person-1', school: 'Before', grade: '2', curriculum: '대수', day1: '목1', visitTime1: '13:00', level: 'L1' },
    { id: 'B', personId: 'person-1', school: 'Before', grade: '2', curriculum: '기하' },
    { id: 'C', personId: 'person-2', school: 'Other', grade: '3' },
  ];
  const server = plain(students), events = element('document'), alerts = [], writes = [], controls = [], rows = [];
  for (const student of students) {
    const row = element(); row.dataset.id = student.id;
    const cells = new Map(['.cell-school', '.cell-grade', '.curSelect', '.subCurrSelect', '.levelSelect', '.docUrlInput'].map(key => [key, element()]));
    cells.forEach(input => { input.dataset.id = student.id; });
    row.querySelector = selector => cells.get(selector) || null;
    row.querySelectorAll = selector => controls.filter(input => input.dataset.id === student.id
      && (selector === '.dayInput' ? !!input.dataset.day : !!input.dataset.field));
    rows.push(row); controls.push(...['.curSelect', '.subCurrSelect', '.levelSelect', '.docUrlInput'].map(key => cells.get(key)));
    for (const [key, value] of [['day', 'day1'], ['day', 'day2'], ['field', 'visitTime1'], ['field', 'visitTime2']]) {
      const input = element(); input.dataset = { id: student.id, [key]: value };
      input.classList.contains = name => name === (key === 'day' ? 'dayInput' : 'timeInput');
      controls.push(input);
    }
  }
  events.querySelectorAll = selector => selector === '#allWrap tr[data-id]' ? rows : selector.includes('input[data-id]') ? controls : [];
  events.getElementById = () => null;
  let failField = '', pending = null;
  const refreshes = { cur: 0, yoil: 0, search: 0 };
  const sandbox = vm.createContext({ document: events, window: { students }, state: { students }, console,
    refreshes,
    $: () => null, toast: () => {}, alert: message => alerts.push(message),
    patchField: async (sid, field, value) => {
      writes.push({ sid, field, value });
      if (pending) await pending.promise;
      if (field === failField) throw new Error('503');
      const owner = server.find(item => item.id === sid);
      const targets = ['school', 'grade', 'docUrl'].includes(field) ? server.filter(item => item.personId === owner.personId) : [owner];
      targets.forEach(item => { item[field] = plain(value); });
      return { ok: true };
    },
    getJSON: async () => plain(server), searchKeyForText: String, matchesSearchKey: () => true,
    SELF_STUDY_DAYS_FIELD: 'selfStudyDays', isSelfStudyDayField: (student, field) => student?.selfStudyDays?.[field] === true,
    nextSelfStudyDays: (student, field, enabled) => ({ ...student.selfStudyDays, [field]: enabled }),
  });
  const source = read('static/js/all/features/table.js').replace(/^import\s[\s\S]*?;\r?\n/gm, '').replace(/\bexport\s+/g, '');
  vm.runInContext(source + '\nrenderCurStats = () => { refreshes.cur++; }; renderYoilStatsSafe = async () => { refreshes.yoil++; }; applyAllStudentSearch = () => { refreshes.search++; };', sandbox);
  const input = controls.find(item => item.dataset.id === 'A' && item.dataset.field === 'visitTime1');
  sandbox.input = input;
  failField = 'visitTime1'; input.value = '18:00';
  await vm.runInContext('saveTimeInput(input)', sandbox); await tick();
  assert.equal(students[0].visitTime1, '13:00', 'failed time save must restore authoritative state');
  assert.equal(input.value, '13:00');
  alerts.length = 0;
  failField = 'level';
  await vm.runInContext("saveRosterFields(input, { level: 'L2' }, 'saved')", sandbox);
  assert.equal(students[0].level, 'L1'); assert.equal(rows[0].querySelector('.levelSelect').value, 'L1');
  assert.equal(alerts.length, 1); assert.equal(input.disabled, false);
  failField = 'visitTime1';
  await vm.runInContext("saveRosterFields(input, { day1: '금2', visitTime1: '18:00' }, 'saved')", sandbox);
  assert.equal(students[0].day1, '금2'); assert.equal(students[0].visitTime1, '13:00');
  assert.equal(controls.find(item => item.dataset.id === 'A' && item.dataset.day).value, '금2');
  failField = ''; pending = gate();
  const success = vm.runInContext("saveRosterFields(input, { school: 'After' }, 'saved')", sandbox);
  await tick(); const count = writes.length;
  await vm.runInContext("saveRosterFields(input, { school: 'Duplicate' }, 'saved')", sandbox);
  assert.equal(writes.length, count); assert.equal(students[0].school, 'Before');
  assert.equal(controls.find(item => item.dataset.id === 'B').disabled, true);
  pending.resolve(); await success; pending = null;
  assert.deepEqual(students.map(item => item.school), ['After', 'After', 'Other']);
  assert.deepEqual(rows.map(row => row.querySelector('.cell-school').textContent), ['After', 'After', '']);
  assert.equal(sandbox.window.students, students);
  rows[1].querySelector('.docUrlInput').value = 'unsaved draft';
  await vm.runInContext("saveRosterFields(input, { grade: '1' }, 'saved')", sandbox);
  assert.equal(students[1].grade, '1'); assert.equal(rows[1].querySelector('.cell-grade').textContent, '1');
  assert.equal(rows[1].querySelector('.docUrlInput').value, 'unsaved draft');
  await vm.runInContext("saveRosterFields(input, { school: '' }, 'saved')", sandbox);
  assert.equal(rows[1].querySelector('.cell-school').textContent, '학교 입력');
  const resetRefreshes = () => {
    refreshes.cur = 0; refreshes.yoil = 0; refreshes.search = 0;
  };
  const docA = rows[0].querySelector('.docUrlInput');
  sandbox.docA = docA;
  rows[1].querySelector('.levelSelect').value = 'unrelated level draft';
  rows[2].querySelector('.docUrlInput').value = 'unrelated person doc draft';
  students[0].unknown = { keep: 'value' };
  server[0].unknown = { keep: 'value' };
  docA.value = 'https://example.invalid/new';
  writes.length = 0; resetRefreshes();
  await vm.runInContext('saveDocUrl(docA)', sandbox);
  assert.deepEqual(writes, [{ sid: 'A', field: 'docUrl', value: 'https://example.invalid/new' }]);
  assert.deepEqual(students.map(row => row.docUrl), ['https://example.invalid/new', 'https://example.invalid/new', undefined]);
  assert.deepEqual(refreshes, { cur: 0, yoil: 0, search: 1 });
  assert.deepEqual(students[0].unknown, { keep: 'value' });
  assert.equal(rows[1].querySelector('.levelSelect').value, 'unrelated level draft');
  assert.equal(rows[2].querySelector('.docUrlInput').value, 'unrelated person doc draft');
  assert.equal(sandbox.window.students, students);
  assert.ok(controls.every(control => !control.disabled));
  failField = 'docUrl';
  server[0].school = server[1].school = 'Authoritative';
  server[0].grade = server[1].grade = '3';
  docA.value = 'https://example.invalid/failed';
  resetRefreshes();
  await vm.runInContext('saveDocUrl(docA)', sandbox);
  assert.deepEqual(refreshes, { cur: 1, yoil: 1, search: 1 });
  assert.deepEqual(students.map(row => row.school), ['Authoritative', 'Authoritative', 'Other']);
  assert.deepEqual(students.map(row => row.grade), ['3', '3', '3']);
  assert.equal(docA.value, 'https://example.invalid/new');
  assert.equal(rows[1].querySelector('.levelSelect').value, 'unrelated level draft');
  assert.equal(rows[2].querySelector('.docUrlInput').value, 'unrelated person doc draft');
  failField = '';
  for (const changes of [
    { school: 'Next' }, { grade: '1' }, { level: 'L3' },
    { curriculum: '대수' }, { subCurriculum: 'A:Ble' },
    { day1: '월1' }, { visitTime1: '13:00' },
    { selfStudyDays: { day1: true } }, { unknownFlag: { keep: true } },
    { docUrl: 'https://example.invalid/multi', grade: '2' },
  ]) {
    sandbox.changes = changes; resetRefreshes();
    await vm.runInContext("saveRosterFields(docA, changes, 'saved')", sandbox);
    assert.deepEqual(refreshes, { cur: 1, yoil: 1, search: 1 });
  }
  failField = 'visitTime1'; resetRefreshes();
  await vm.runInContext("saveRosterFields(docA, { day1: '금2', visitTime1: '18:00' }, 'saved')", sandbox);
  assert.deepEqual(refreshes, { cur: 1, yoil: 1, search: 1 });
  assert.equal(students[0].day1, '금2');
  assert.equal(students[0].visitTime1, '13:00');
  assert.deepEqual(students[0].unknown, { keep: 'value' });

  // A pending weekday save must retain native Tab targets without permitting
  // concurrent edits. Original locks and adjacent drafts survive both outcomes.
  const dayA = controls.find(item => item.dataset.id === 'A' && item.dataset.day === 'day1');
  const nextDayA = controls.find(item => item.dataset.id === 'A' && item.dataset.day === 'day2');
  const dayB = controls.find(item => item.dataset.id === 'B' && item.dataset.day === 'day1');
  const timeB = controls.find(item => item.dataset.id === 'B' && item.dataset.field === 'visitTime1');
  dayB.readOnly = true; timeB.disabled = true; nextDayA.value = 'adjacent draft';
  sandbox.dayA = dayA;
  for (const failing of [false, true]) {
    failField = failing ? 'visitTime1' : ''; pending = gate(); writes.length = 0;
    dayA.value = failing ? '화1' : '월2';
    const savingDay = vm.runInContext('saveDayInput(dayA)', sandbox); await tick();
    for (const control of controls.filter(item => ['A', 'B'].includes(item.dataset.id)
      && (item.dataset.day || item.dataset.field))) {
      assert.equal(control.disabled, control === timeB, 'weekday/time controls stay in native Tab order');
      assert.equal(control.readOnly, true, 'pending schedule inputs remain protected against edits');
    }
    assert.equal(rows[1].querySelector('.levelSelect').disabled, true, 'other linked controls stay locked');
    assert.equal(controls.find(item => item.dataset.id === 'C' && item.dataset.day).readOnly, false);
    assert.equal(nextDayA.value, 'adjacent draft');
    let prevented = 0;
    for (const shiftKey of [false, true]) {
      for (const listener of events.listeners.keydown || []) {
        listener({target: dayA, key: 'Tab', shiftKey, preventDefault() { prevented++; }});
      }
    }
    assert.equal(prevented, 0, 'Tab and Shift+Tab must keep browser defaults');
    const count = writes.length;
    await vm.runInContext('saveTimeInput(input)', sandbox);
    assert.equal(writes.length, count, 'pending linked saves still deduplicate');
    pending.resolve(); await savingDay; pending = null;
    assert.equal(dayA.disabled, false); assert.equal(nextDayA.disabled, false);
    assert.equal(dayA.readOnly, false); assert.equal(nextDayA.readOnly, false);
    assert.equal(dayB.readOnly, true, 'pre-existing readonly state is restored');
    assert.equal(timeB.disabled, true, 'pre-existing disabled state is preserved');
    assert.equal(timeB.readOnly, false);
    assert.equal(rows[1].querySelector('.levelSelect').disabled, false);
    assert.equal(nextDayA.value, 'adjacent draft', 'saved fields cannot erase the adjacent draft');
    assert.deepEqual(writes.map(write => write.field), ['day1', 'visitTime1']);
    assert.equal(students[0].day1, failing ? '화1' : '월2');
    assert.equal(students[0].visitTime1, '18:00', 'failed second field reloads the committed server value');
  }
}

async function addStudentChecks() {
  const ids = new Map(['newStuMount', 'ns_add', 'ns_name', 'ns_cur', 'ns_sub', 'ns_firstAttendanceDate',
    'ns_day1', 'ns_day2', 'ns_day3', 'ns_day4', 'ns_day5', 'ns_grade', 'ns_level', 'ns_school', 'ns_doc']
    .map(id => [id, element(id)]));
  let valid = true, reloads = 0, pending;
  const writes = [], alerts = [];
  const firstDate = ids.get('ns_firstAttendanceDate');
  firstDate.reportValidity = () => valid;
  const context = vm.createContext({
    document: { getElementById: id => ids.get(id) || null },
    location: { reload: () => { reloads++; } },
    alert: message => alerts.push(message),
    fetch: async (url, options) => {
      writes.push({ url, method: options.method, body: JSON.parse(options.body) });
      return pending ? pending.promise : response({ id: 'new-student' });
    },
  });
  vm.runInContext(read('static/js/all/features/addStudent.js').replace(/\bexport\s+/g, ''), context);
  context.mountNewStudentBar();
  const markup = ids.get('newStuMount').innerHTML;
  assert.match(markup, /for="ns_firstAttendanceDate"/);
  assert.match(markup, /id="ns_firstAttendanceDate" type="date" required/);
  const initial = markup.match(/min="(\d{4}-\d{2}-\d{2})" value="(\d{4}-\d{2}-\d{2})"/);
  assert.ok(initial); assert.equal(initial[1], initial[2], 'calendar defaults to its earliest allowed date');
  firstDate.value = '2099-01-05';
  ids.get('ns_name').value = '첫등원검증'; ids.get('ns_day1').value = '월1';
  const click = ids.get('ns_add').listeners.click[0];
  valid = false; await click(); assert.equal(writes.length, 0, 'invalid native calendar value cannot submit');
  valid = true; pending = gate();
  const saving = click(); await tick(); await click();
  assert.equal(writes.length, 1, 'a pending add cannot create duplicate students');
  assert.equal(writes[0].url, '/api/add-student'); assert.equal(writes[0].method, 'POST');
  assert.equal(writes[0].body.firstAttendanceDate, '2099-01-05');
  assert.equal(writes[0].body.day1, '월1', 'first attendance leaves weekly schedule independent');
  pending.resolve(response({ error: '첫 등원일 오류' }, 400)); await saving;
  assert.equal(reloads, 0); assert.equal(firstDate.value, '2099-01-05');
  assert.equal(ids.get('ns_add').disabled, false); assert.match(alerts[0], /첫 등원일 오류/);
  pending = null; await click(); assert.equal(reloads, 1, 'successful add refreshes the authoritative roster');
  assert.equal(writes.length, 2);
}

if (!only || only === 'add') await addStudentChecks();
if (!only || only === 'auth') await authChecks();
if (!only || only === 'attendance') await attendanceChecks();
if (!only || only === 'roster') await rosterChecks();
console.log('roster/auth/attendance async checks passed: offline retry, token retention/401, dedup, reversed/closed reads, partial commit and linked profile DOM/state');
