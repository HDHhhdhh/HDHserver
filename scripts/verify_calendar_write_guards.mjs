import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createHash } from 'node:crypto';

const options = { sourceRoot: process.cwd(), source: null, escSource: null, expectOwner: 'guarded' };
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  assert.ok(['--source-root', '--source', '--esc-source', '--expect-owner'].includes(arg), 'unknown option ' + arg);
  const value = process.argv[++i];
  assert.ok(value && !value.startsWith('--'), 'missing value for ' + arg);
  options[{ '--source-root': 'sourceRoot', '--source': 'source', '--esc-source': 'escSource', '--expect-owner': 'expectOwner' }[arg]] = value;
}
assert.ok(['none', 'vulnerable', 'guarded'].includes(options.expectOwner));
const root = path.resolve(options.sourceRoot);
const sourcePath = path.resolve(root, options.source || 'static/js/admin/features/calendar.js');
const fixturePath = path.join(root, 'scripts/verify_admin_popup_async_scope.mjs');
const sourceBytes = fs.readFileSync(sourcePath);
const fixtureBytes = fs.readFileSync(fixturePath);
const source = sourceBytes.toString('utf8').replaceAll('\r\n', '\n');
const datePattern = source.match(/  const DATE_RE = (.*);/)?.[1];
assert.ok(datePattern, 'actual calendar date pattern');
const fixture = fixtureBytes.toString('utf8').replaceAll('\r\n', '\n');
const hash = value => createHash('sha256').update(value).digest('hex');
const clone = value => JSON.parse(JSON.stringify(value));
const stripModule = text => text.replace(/^import\s[\s\S]*?;\r?\n/gm, '').replace(/\bexport\s+/g, '');
const read = file => stripModule(fs.readFileSync(path.join(root, file), 'utf8'));
const domStart = fixture.indexOf('function classList(');
const domEnd = fixture.indexOf('const silentConsole', domStart);
assert.ok(domStart >= 0 && domEnd > domStart);
const { element, classList, documentFor } = new Function(
  fixture.slice(domStart, domEnd) + '\nreturn { element, classList, documentFor };',
)();

// Same explicit two-space function boundary used by verify_makeup_schedule_links.
// Execute real save/open/listener/helper bodies; avoid unrelated FullCalendar UI.
function calendarFunction(name) {
  const match = new RegExp(`  (?:async )?function ${name}\\(`).exec(source);
  assert.ok(match, 'calendar function ' + name);
  const end = source.indexOf('\n  }\n', match.index);
  assert.ok(end > match.index, 'explicit calendar function boundary ' + name);
  return source.slice(match.index, end + 5);
}
const listenerStart = source.indexOf("  selectionSaveBtn?.addEventListener('click', async () => {");
const listenerEnd = source.indexOf('  let calendarMutationRefreshPromise = null;', listenerStart);
assert.ok(listenerStart >= 0 && listenerEnd > listenerStart, 'actual selection save/close listeners');
const listeners = source.slice(listenerStart, listenerEnd);
const functionNames = [
  'hasWeekday', 'parseSlotNumbers', 'slotGroupLabel', 'slotSortValue', 'getRegularSlots',
  'getCountSlots', 'getMakeupSlots', 'serializeSlots', 'combinedSlotsForStudent',
  'slotsForAttendStudent', 'getAbsentSlots', 'subtractAbsentSlots', 'availableSlotsForAttendStudent',
  'addSlotCounts', 'invalidateCalendarPreload', 'preloadExtraWeekend', 'fetchCountsForRange',
  'escapeHtml', 'escapeAttr', 'normalizeCarryoverPayload', 'clonePlainMap', 'postJson',
  'fetchAbsentSnapshot', 'postAbsentSnapshot', 'fetchMakeupCarryoverSnapshot', 'postMakeupCarryoverSnapshot',
  'patchExtraAttendDates', 'normalizeAbsentSlotMap', 'applyAbsentPayload', 'postWeekendPatch',
  'makeupSlotLabel', 'slotLegend', 'studentRow', 'setSelectionRowSelected', 'openSelectionUI', 'onSlotClick',
  'saveManualAbsenceSelection', 'carryoverScheduledMakeup', 'scheduleSelectedMakeup',
];
for (const name of ['closeCalendarSelectionPopup', 'saveCalendarSelectionSnapshot']) {
  if (source.includes(`function ${name}(`) && !listeners.includes(`function ${name}(`)) functionNames.push(name);
}
const functions = functionNames.map(calendarFunction).join('\n');
const dependencySource = [
  read('static/js/shared/api.js'),
  read('static/js/admin/features/extraAttendanceMerge.js'),
  read('static/js/admin/features/scheduleOverrideSave.js'),
].join('\n');
const DAY = '2026-10-01';
const OTHER = '2026-10-02';
const settle = async () => { for (let i = 0; i < 36; i++) await Promise.resolve(); };
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300, status,
  headers: { get: () => 'fixture-existing-revision' },
  json: async () => clone(payload), text: async () => JSON.stringify(payload),
});
const outcomes = [];
const pass = name => outcomes.push({ case: name, pass: true });

function harness({ actualResolution = false } = {}) {
  const ids = new Map(['selectionModal', 'selectionList', 'selectionSave', 'selectionClose',
    'selectionTitle', 'attendDateTitle', 'attendModal'].map(id => [id, element(id)]));
  const modal = ids.get('selectionModal'), list = ids.get('selectionList'), saveButton = ids.get('selectionSave');
  modal.querySelectorAll = () => [saveButton, ids.get('selectionClose'), ...list.rows.flatMap(item => item.fixtureControls)];
  modal.dataset = { mode: 'extra', date: DAY };
  ids.get('attendDateTitle').textContent = DAY + ' (목)';
  let html = '';
  list.rows = [];
  Object.defineProperty(list, 'innerHTML', { get: () => html, set(value) {
    html = value;
    list.rows = [];
    for (const match of value.matchAll(/<li\b([^>]*)>([\s\S]*?)<\/li>/g)) {
      const sid = match[1].match(/data-id="([^"]*)"/)?.[1];
      if (!sid) continue;
      const item = element(sid), checkbox = element();
      checkbox.checked = /class="chk-sid"[^>]*\bchecked\b/.test(match[0]);
      const slots = Array.from(match[2].matchAll(/<button\b[\s\S]*?<\/button>/g), value => {
        const slot = element();
        slot.dataset.slot = value[0].match(/data-slot="(\d+)"/)?.[1];
        slot.classList = classList(value[0].match(/class="([^"]*)"/)?.[1]);
        slot.disabled = /\bdisabled\b/.test(value[0]);
        return slot;
      });
      item.dataset = { id: sid, allSlots: match[1].match(/data-all-slots="([^"]*)"/)?.[1] || '' };
      item.querySelector = selector => selector === '.chk-sid' ? checkbox
        : selector === '.slot-btn.on' ? slots.find(slot => slot.classList.contains('on'))
        : selector === '.slot-btn[data-slot="1"]:not([disabled])' ? slots.find(slot => slot.dataset.slot === '1' && !slot.disabled)
        : selector === '.slot-btn:not([disabled])' ? slots.find(slot => !slot.disabled)
        : selector === '.student-name' ? { textContent: sid } : null;
      item.querySelectorAll = selector => selector.startsWith('.slot-btn.on')
        ? slots.filter(slot => slot.classList.contains('on') && (!selector.includes('[disabled]') || !slot.disabled)) : [];
      item.fixtureControls = [checkbox, ...slots];
      list.rows.push(item);
    }
  } });
  list.querySelectorAll = selector => selector === 'li[data-id]' ? list.rows : [];
  const document = documentFor(ids), requests = [], writes = [], alerts = [], events = [];
  document.dispatchEvent = event => events.push(event.type);
  const originalQueryAll = document.querySelectorAll;
  document.querySelectorAll = selector => selector.includes('[id$=') ? [modal] : originalQueryAll(selector);
  let failure = null, openHold = null, injectLater = false, missingDates = false, failCarryoverAck = false;
  let extras = { [DAY]: ['keep', 'remove', 'retired9'], [OTHER]: ['other'] };
  let slots = { [DAY]: { keep: 2, remove: 1, retired9: 2 }, [OTHER]: { other: 2 } };
  let carryover = { by_absence: { '2026-09-01': { 'add|1': { state: 'open', note: 'first' } },
    '2026-09-02': { 'add|1': { state: 'open', note: 'second' } } }, manual: {} };
  const students = ['keep', 'remove', 'add', 'late', 'later', 'other'].map(id => ({ id, name: id }));
  students.push({ id: 'regular', name: 'regular', day1: '목1' });
  const state = { students, extra: {}, absentByDate: {}, absences: {}, absentSlotsByDate: {} };
  const window = {};
  const context = vm.createContext({
    $: id => ids.get(id) || null, state, window, document,
    console: { log() {}, warn() {}, error() {} }, alert: message => alerts.push(message), toast() {},
    CustomEvent: function(type, init) { this.type = type; this.detail = init?.detail; },
    getComputedStyle: el => ({ display: el.style.display, visibility: 'visible', opacity: '1', position: 'fixed' }),
    requestAnimationFrame: callback => callback(),
    studentSearchKey: student => student.id, ensureSelectionSearchUI: () => null, applySelectionSearchFilter() {},
    getAdminDate: () => DAY, parseAdminDateLocal: value => new Date(value + 'T12:00:00'),
    openAttendModal() {}, refreshMakeupPlanner: async () => {},
    resolveFirstOpenMakeupDemandsForSids: async sids => writes.push({ step: 'resolve-carryover', sids: clone(sids) }),
    markAbsenceMakeupOpen: async () => writes.push({ step: 'open-carryover' }),
    manualMakeupSelectedDateList: () => [DAY],
    saveWeekendSlotsPatch: async (date, map) => {
      writes.push({ step: 'slots', date, map: clone(map) });
      for (const [sid, value] of Object.entries(map)) {
        if (Array.isArray(value) && !value.length) delete slots[date][sid];
        else (slots[date] ||= {})[sid] = clone(value);
      }
    },
    fetch: async (url, init = {}) => {
      const method = init.method || 'GET';
      requests.push({ url, method, body: init.body ? JSON.parse(init.body) : undefined });
      const endpoint = url.split('?')[0];
      assert.ok(['/api/attend', '/api/extra-attend', '/api/weekend-slots', '/api/absent',
        '/api/makeup-carryover', '/api/arrive-time', '/api/arrive-time/patch'].includes(endpoint), 'only synthetic scoped endpoints');
      if (method === 'GET') {
        assert.equal(init.cache, 'no-store');
        const payload = clone(endpoint === '/api/attend' ? students : endpoint === '/api/extra-attend' ? extras
          : endpoint === '/api/weekend-slots' ? slots : endpoint === '/api/makeup-carryover'
            ? carryover : { by_date: {}, by_student: {}, by_slot: {} });
        if (openHold) await openHold.promise;
        if (failure?.url === endpoint) return failure.malformed
          ? response(failure.payload) : response({ error: 'fixture failed input' }, 503);
        return response(payload);
      }
      const body = JSON.parse(init.body);
      writes.push({ step: endpoint, method, body: clone(body) });
      if (endpoint === '/api/makeup-carryover') {
        carryover = clone(body);
        if (failCarryoverAck) {
          failCarryoverAck = false;
          return { ...response(body), json: async () => { throw new Error('fixture lost carryover reply after commit'); } };
        }
        return response(body);
      }
      if (endpoint === '/api/extra-attend') {
        assert.equal(method, 'PATCH');
        assert.deepEqual(Object.keys(body), ['deltas'], 'actual calendar delta helper must not replace full dates');
        if (injectLater) { extras[DAY].push('later'); slots[DAY].later = 2; injectLater = false; }
        const dates = {};
        for (const [date, mapping] of Object.entries(body.deltas)) {
          const membership = new Set(extras[date] || []);
          for (const [sid, selected] of Object.entries(mapping)) {
            assert.equal(typeof selected, 'boolean');
            if (selected) membership.add(sid); else membership.delete(sid);
          }
          dates[date] = [...membership];
          if (dates[date].length) extras[date] = dates[date]; else delete extras[date];
        }
        return response(missingDates ? { ok: true } : { ok: true, dates, changedDates: Object.keys(dates) });
      }
      assert.equal(method, 'POST');
      return response(body);
    },
  });
  vm.runInContext(dependencySource + `
    const CT = { 'Content-Type': 'application/json' }, WCHR = '일월화수목금토';
    const DATE_RE = ${datePattern};
    const MAKEUP_SLOTS = [1, 2], MAKEUP_ARRIVE_BY_SLOT = { 1: '13:00', 2: '18:00' };
    const yoil = date => WCHR[new Date(date).getDay()];
    const ymd = d => [d.getFullYear(), String(d.getMonth()+1).padStart(2,'0'), String(d.getDate()).padStart(2,'0')].join('-');
    const selectionModal = $('selectionModal'), selectionListEl = $('selectionList');
    const selectionSaveBtn = $('selectionSave'), selectionClose = $('selectionClose');
    let EXTRA = {}, WEEKEND = {}, CARRYOVER = {}, absenceRevision = '', countMap = {};
    let preloadExtraWeekendPromise = null, calendarPreloadError = null;
    let calendarMutationGeneration = 0, calendarReadGeneration = 0, calendarProjectionGeneration = 0;
    let selectionBaselineExtraIds = [], selectionBaselineExtraDate = '', selectionOpenSequence = 0, slotClickBound = false;
    let selectionSaving = false;
    let makeupSelection = { sid: 'add', absenceDate: '${DAY}', source: 'absence' };
    let manualAbsenceSelection = { sid: 'add' };
    ${functions}
    ${actualResolution ? calendarFunction('resolveFirstOpenMakeupDemandsForSids') : ''}
    ${listeners}
    globalThis.probe = {
      open: openSelectionUI, load: preloadExtraWeekend,
      counts: () => fetchCountsForRange('${DAY}', '${OTHER}'),
      manual: () => saveManualAbsenceSelection({ currentTarget: selectionSaveBtn }),
      cancel: () => carryoverScheduledMakeup({ sid:'add',absenceDate:'${DAY}',source:'absence' }),
      schedule: () => scheduleSelectedMakeup('${DAY}', 1),
      snapshot: () => JSON.parse(JSON.stringify({ EXTRA, WEEKEND, countMap })),
    };
  `, context, { filename: 'actual-calendar-registered-selection-listeners.js' });
  return {
    ids, modal, list, saveButton, state, context, window, requests, writes, alerts, events, probe: context.probe,
    open: async () => { context.probe.open('extra'); await settle(); },
    save: () => saveButton.listeners.click[0](),
    choose: (sid, selected) => {
      const row = list.rows.find(item => item.dataset.id === sid);
      assert.ok(row, 'rendered actual calendar row ' + sid);
      row.querySelector('.chk-sid').checked = selected;
    },
    chooseSlots: (sid, selected) => {
      const row = list.rows.find(item => item.dataset.id === sid);
      assert.ok(row, 'rendered actual slot row ' + sid);
      row.fixtureControls.slice(1).forEach(slot => slot.classList.toggle('on', selected.includes(+slot.dataset.slot)));
    },
    openAbsence: async () => { context.probe.open('absent'); await settle(); },
    setRegularDay: (sid, day) => { state.students.find(student => student.id === sid).day1 = day; },
    close: () => ids.get('selectionClose').listeners.click[0](),
    setDate: date => { ids.get('attendDateTitle').textContent = date + ' (요일)'; },
    setFailure: value => { failure = value; }, setOpenHold: value => { openHold = value; },
    concurrentBeforeRead: () => { extras[DAY].push('late'); slots[DAY].late = 2; },
    concurrentAfterRead: () => { injectLater = true; },
    failCarryoverAck: () => { failCarryoverAck = true; },
    missingDates: () => { missingDates = true; }, server: () => clone({ extras, slots, carryover }),
  };
}

for (const url of ['/api/attend', '/api/extra-attend', '/api/weekend-slots']) {
  const h = harness();
  h.setFailure({ url });
  await h.open();
  assert.equal(h.saveButton.disabled, true);
  await h.save();
  assert.equal(h.writes.length, 0, 'failed opening invalidates baseline before a forced save callback');
  assert.equal(h.alerts.length, 1);
  h.setFailure(null);
  await h.open();
  assert.equal(h.saveButton.disabled, false);
}
pass('actual selection opening GET failures disable save, invalidate baseline, recover on fresh open');

for (const url of ['/api/extra-attend', '/api/weekend-slots', '/api/makeup-carryover', '/api/absent']) {
  const h = harness();
  await h.open();
  h.choose('add', true);
  h.setFailure({ url });
  const before = h.server();
  await h.save();
  assert.equal(h.writes.length, 0, 'selection guard stops slot/extra/arrival/carryover writers for ' + url);
  assert.deepEqual(h.server(), before);
  const start = h.requests.length;
  await h.probe.manual();
  assert.equal(h.requests.length - start, 4, 'manual guard makes only one four-input read bundle');
  await assert.rejects(h.probe.cancel(), /보강 정보를 불러오지 못했습니다/);
  await assert.rejects(h.probe.schedule(), /보강 정보를 불러오지 못했습니다/);
  assert.equal(h.writes.length, 0, 'all four actual writer entrypoints stop before mutation');
  assert.ok(h.requests.every(request => request.method === 'GET'));
  assert.equal(h.saveButton.disabled, false, 'manual failure releases button');
  assert.equal(await h.probe.load(), false, 'read-only loader fallback still resolves');
  assert.equal(await h.probe.counts(), true, 'actual count projection remains available');
  assert.ok(h.probe.snapshot().countMap[DAY][1] >= 1, 'regular student remains countable after failed input');
}
pass('each of four failed inputs stops all four actual writers before any POST/PATCH/slot save while read projection works');

{
  const h = harness();
  await h.open();
  h.choose('remove', false);
  h.choose('add', true);
  h.concurrentBeforeRead();
  h.concurrentAfterRead();
  await h.save();
  const delta = h.writes.find(write => write.step === '/api/extra-attend');
  assert.ok(delta, JSON.stringify({ writes: h.writes, alerts: h.alerts }));
  assert.deepEqual(delta.body, { deltas: { [DAY]: { add: true, remove: false } } });
  assert.deepEqual(h.server().extras, { [DAY]: ['keep', 'retired9', 'late', 'later', 'add'], [OTHER]: ['other'] });
  assert.deepEqual(clone(h.state.extra), h.server().extras);
  assert.equal(h.server().slots[DAY].late, 2);
  assert.equal(h.server().slots[DAY].later, 2);
  assert.equal(h.server().slots[DAY].retired9, 2);
  assert.equal(Object.hasOwn(h.server().slots[DAY], 'remove'), false);
  const slotWrites = h.writes.filter(write => write.step === 'slots');
  assert.deepEqual(slotWrites.map(write => write.map), [{ add: 1, keep: 2 }, { remove: [] }]);
  assert.ok(h.writes.indexOf(slotWrites[0]) < h.writes.indexOf(delta));
  assert.ok(h.writes.indexOf(slotWrites[1]) > h.writes.indexOf(delta));
  const arrival = h.writes.find(write => write.step === '/api/arrive-time');
  assert.deepEqual(arrival.body, { [DAY]: { add: '13:00', keep: '18:00' } });
  assert.deepEqual(h.writes.find(write => write.step === 'resolve-carryover').sids, ['add']);
  pass('actual opening baseline/listener/delta helper preserve concurrent SID additions, retired/untouched slots and acknowledged dates');
}

{
  const h = harness(), gate = deferred();
  h.setOpenHold(gate);
  await h.open();
  h.close();
  h.setOpenHold(null);
  h.setDate(OTHER);
  await h.open();
  const rows = h.list.rows.filter(item => item.querySelector('.chk-sid').checked).map(item => item.dataset.id);
  assert.deepEqual(rows, ['other']);
  gate.resolve();
  await settle();
  assert.equal(h.modal.dataset.date, OTHER, 'late older open cannot replace frozen current date');
  assert.deepEqual(h.list.rows.filter(item => item.querySelector('.chk-sid').checked).map(item => item.dataset.id), ['other']);
  h.close();
  await h.save();
  assert.equal(h.writes.length, 0, 'closed baseline cannot be saved by queued callback');
  pass('close/new-open sequence rejects old reply and closed-session save callback');
}

{
  const h = harness();
  await h.open();
  h.choose('add', true);
  h.missingDates();
  await h.save();
  assert.equal(h.server().extras[DAY].includes('add'), true, 'primary membership save did commit');
  assert.equal(h.writes.filter(write => write.step === '/api/arrive-time' || write.step === 'resolve-carryover').length, 0,
    'missing actual dates acknowledgement stops downstream arrival/carryover work');
  assert.equal(h.modal.style.display, 'flex');
  assert.ok(h.alerts.some(message => /저장 결과/.test(message)));
  pass('missing dates acknowledgement after primary commit stops downstream work and retains visible failure');
}

if (options.expectOwner !== 'none') {
  const guarded = options.expectOwner === 'guarded';
  const h = harness(), gate = deferred();
  await h.open();
  h.choose('add', true);
  h.setOpenHold(gate);
  const first = h.save(), second = h.save();
  await settle();
  assert.equal(h.saveButton.disabled, guarded, 'pending save control state');
  h.close();
  h.setDate(OTHER);
  h.setOpenHold(null);
  await h.open();
  assert.equal(h.modal.dataset.date, guarded ? DAY : OTHER, 'pending save permits or blocks new opening');
  gate.resolve();
  await Promise.all([first, second]);
  assert.equal(h.writes.filter(write => write.step === '/api/extra-attend').length, guarded ? 1 : 2);
  assert.equal(h.writes.filter(write => write.step === 'resolve-carryover').length, guarded ? 1 : 2);
  assert.equal(h.modal.style.display, 'none', 'old unlocked save also closes the newly opened modal');
  pass(guarded ? 'pending save owner blocks duplicate/close/open' : 'reproduced duplicate saves and older save closing newer date session');

  const replay = harness({ actualResolution: true });
  await replay.open();
  replay.choose('add', true);
  replay.failCarryoverAck();
  await replay.save();
  assert.equal(replay.server().carryover.by_absence['2026-09-01']['add|1'].state, 'carried');
  assert.equal(replay.server().carryover.by_absence['2026-09-02']['add|1'].state, 'open');
  assert.equal(replay.modal.style.display, 'flex', 'lost acknowledgement permits visible retry');
  assert.ok(replay.alerts.some(message => /lost carryover reply/.test(message)));
  await replay.save();
  assert.equal(replay.server().carryover.by_absence['2026-09-02']['add|1'].state, guarded ? 'open' : 'carried');
  assert.equal(replay.writes.filter(write => write.step === '/api/makeup-carryover').length, guarded ? 1 : 2);
  pass(guarded ? 'post-commit lost carryover reply retry consumes no second demand' : 'reproduced second-demand consumption after post-commit lost carryover reply');

  const esc = harness(), escGate = deferred();
  await esc.open();
  esc.choose('add', true);
  esc.setOpenHold(escGate);
  const escSaving = esc.save();
  const escSource = stripModule(fs.readFileSync(path.resolve(root, options.escSource || 'static/js/admin/features/escClose.js'), 'utf8'));
  vm.runInContext(escSource + '\ninitEscClose();', esc.context);
  esc.context.document.events.listeners.keydown.forEach(listener => listener({ key: 'Escape' }));
  assert.equal(esc.modal.style.display, guarded ? 'flex' : 'none', 'ESC must route through active selection owner');
  esc.setOpenHold(null);
  escGate.resolve();
  await escSaving;
  pass(guarded ? 'actual ESC close owner denies pending save close' : 'reproduced actual ESC hiding pending save owner');

  if (guarded) {
    const absent = harness();
    absent.setRegularDay('keep', '목1');
    await absent.openAbsence();
    absent.choose('keep', true);
    absent.chooseSlots('keep', [2]);
    await absent.save();
    const posted = absent.writes.find(write => write.step === '/api/absent');
    assert.ok(posted, JSON.stringify(absent.alerts));
    assert.deepEqual(posted.body.by_slot[DAY].keep, [2]);
    assert.equal(posted.body.by_date[DAY]?.includes('keep') || false, false,
      'locking controls cannot turn selected slot 2 into full-day absence');
    pass('enabled slot snapshot preserves actual partial absence while all controls lock');
  }
}

console.log(JSON.stringify({ source: sourcePath, sourceSha256: hash(sourceBytes),
  reusedDomFixture: fixturePath, reusedDomFixtureSha256: hash(fixtureBytes),
  groupCount: outcomes.length, outcomes, actualRegisteredSelectionListener: true,
  actualFourWriterEntryPoints: true, actualSharedEnsureOkAndSendJson: true,
  fullCalendarEntrypoint: false, persistentWrites: 0, realRequests: 0,
  limits: ['FullCalendar rendering/init excluded', 'planner refresh and carryover resolution dependencies are synthetic',
    'successful carryover cancel/schedule bodies remain covered by the existing schedule-links fixture, not these failed-input cases'] }, null, 2));
