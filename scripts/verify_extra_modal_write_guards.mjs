import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createHash } from 'node:crypto';

const options = { sourceRoot: process.cwd(), source: null, expectAck: 'guarded' };
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  assert.ok(['--source-root', '--source', '--expect-ack'].includes(arg), 'unknown option ' + arg);
  const value = process.argv[++i];
  assert.ok(value && !value.startsWith('--'), 'missing value for ' + arg);
  options[{ '--source-root': 'sourceRoot', '--source': 'source', '--expect-ack': 'expectAck' }[arg]] = value;
}
assert.ok(['none', 'vulnerable', 'guarded'].includes(options.expectAck));
const root = path.resolve(options.sourceRoot);
const sourcePath = path.resolve(root, options.source || 'static/js/admin/features/extraModal.js');
const fixturePath = path.join(root, 'scripts/verify_admin_popup_async_scope.mjs');
const sourceBytes = fs.readFileSync(sourcePath);
const fixtureBytes = fs.readFileSync(fixturePath);
const fixtureText = fixtureBytes.toString('utf8').replaceAll('\r\n', '\n');
const hash = value => createHash('sha256').update(value).digest('hex');
const clone = value => JSON.parse(JSON.stringify(value));
const stripModule = text => text.replace(/^import\s[\s\S]*?;\r?\n/gm, '').replace(/\bexport\s+/g, '');
const read = file => stripModule(fs.readFileSync(path.join(root, file), 'utf8'));
const from = fixtureText.indexOf('function classList(');
const to = fixtureText.indexOf('const silentConsole', from);
const selectionFrom = fixtureText.indexOf('function selectionHarness(');
const selectionTo = fixtureText.indexOf('async function runSelectionOpen(', selectionFrom);
assert.ok(from >= 0 && to > from && selectionFrom > to && selectionTo > selectionFrom);
let domFixture = fixtureText.slice(from, to) + fixtureText.slice(selectionFrom, selectionTo);
function replaceOnce(before, after, purpose) {
  assert.equal(domFixture.split(before).length - 1, 1, 'fixture adaptation: ' + purpose);
  domFixture = domFixture.replace(before, after);
}
replaceOnce(
  'const checkbox = {checked: /class="chk-sid"[^>]*\\bchecked\\b/.test(match[0])};',
  'const checkbox = {checked: /class="chk-sid"[^>]*\\bchecked\\b/.test(match[0]), disabled: /class="chk-sid"[^>]*\\bdisabled\\b/.test(match[0])};',
  'preserve actual legacy checkbox disable state',
);
replaceOnce(
  "        dataset: {n: item[0].match(/data-n=\"(\\d+)\"/)?.[1]},",
  "        dataset: {n: item[0].match(/data-n=\"(\\d+)\"/)?.[1]},\n        disabled: /\\bdisabled\\b/.test(item[0]),",
  'preserve actual legacy slot disable state',
);
replaceOnce(
  '      zone.rows.push(item);',
  '      item.fixtureControls = [checkbox, ...slots];\n      zone.rows.push(item);',
  'expose rendered row controls for save lock assertions',
);
replaceOnce(
  '  modal.querySelectorAll = () => [save1, save2];',
  `  modal.querySelectorAll = selector => selector === 'button, input'
    ? [save1, save2, ...zone.rows.flatMap(row => row.fixtureControls)] : [save1, save2];`,
  'distinguish save buttons from all editable controls',
);
const { selectionHarness } = new Function(domFixture + '\nreturn { selectionHarness };')();
const apiSource = read('static/js/shared/api.js');
const helperSource = read('static/js/admin/features/extraAttendanceMerge.js');
const orderingSource = read('static/js/admin/features/scheduleOverrideSave.js');
const modalSource = stripModule(sourceBytes.toString('utf8'));
const DAY = '2026-10-01';
const OTHER = '2026-10-02';
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const response = (data, status = 200) => ({
  ok: status >= 200 && status < 300, status,
  headers: { get: () => null },
  json: async () => clone(data), text: async () => JSON.stringify(data),
});
const outcomes = [];
const pass = name => outcomes.push({ case: name, pass: true });

function harness() {
  const h = selectionHarness('extra');
  h.save1.textContent = h.save2.textContent = '저장';
  let date = DAY, failure = null, openHold = null, saveHold = null;
  let injectUnrelated = false, failSlots = false, ackFailure = null;
  const requests = [], writes = [], messages = [], alerts = [], events = [];
  let extras = { [DAY]: ['keep', 'remove', 'retired9'], [OTHER]: ['other'] };
  let slots = { [DAY]: { keep: 2, remove: 1, retired9: 2 }, [OTHER]: { other: 2 } };
  const students = ['keep', 'remove', 'add', 'late', 'later', 'other'].map(id => ({ id, name: id }));
  const state = { students, extra: {} };
  const window = {};
  const context = vm.createContext({
    $: h.$, state, window, document: h.document, console: { log() {}, warn() {}, error() {} },
    getAdminDate: () => date, toast: message => messages.push(message), alert: message => alerts.push(message),
    requestAnimationFrame: callback => callback(), CustomEvent: function(type, init) { this.type = type; this.detail = init?.detail; },
    applySearchPlaceholder() {}, matchesSearchKey: () => true,
    normalizeSearch: value => String(value || ''), studentSearchKey: student => student.id,
    clearTodayOrder: async frozenDate => writes.push({ step: 'order', date: frozenDate }),
    setArriveOverrides: (frozenDate, map) => writes.push({ step: 'arrival-cache', date: frozenDate, map: clone(map) }),
    saveWeekendSlotsPatch: async (frozenDate, map) => {
      writes.push({ step: 'slots', date: frozenDate, map: clone(map) });
      if (failSlots) throw new Error('fixture slot save failure');
      if (saveHold) { saveHold.entered.resolve(); await saveHold.promise; }
      for (const [sid, value] of Object.entries(map)) {
        if (Array.isArray(value) && !value.length) delete slots[frozenDate][sid];
        else (slots[frozenDate] ||= {})[sid] = clone(value);
      }
    },
    fetch: async (url, init = {}) => {
      const method = init.method || 'GET';
      requests.push({ method, url, body: init.body ? JSON.parse(init.body) : undefined });
      assert.ok(['/api/extra-attend', '/api/weekend-slots', '/api/arrive-time'].includes(url), 'no unrelated or real fetch');
      if (method === 'GET') {
        assert.equal(init.cache, 'no-store');
        assert.ok(url !== '/api/arrive-time');
        const payload = clone(url === '/api/extra-attend' ? extras : slots);
        if (openHold) await openHold.promise;
        if (failure?.url === url) {
          if (failure.malformed) return response(failure.payload);
          return response({ error: 'fixture read failure' }, 503);
        }
        return response(payload);
      }
      const body = JSON.parse(init.body);
      writes.push({ step: url, method, body: clone(body) });
      if (url === '/api/extra-attend') {
        assert.equal(method, 'PATCH');
        assert.deepEqual(Object.keys(body), ['deltas'], 'no unsafe legacy replacement fallback');
        if (failure?.deltaStatus) return response({ error: 'fixture legacy backend rejects delta' }, failure.deltaStatus);
        if (injectUnrelated) {
          extras[DAY].push('later');
          slots[DAY].later = 2;
          injectUnrelated = false;
        }
        const dates = {};
        for (const [key, mapping] of Object.entries(body.deltas)) {
          const membership = new Set(extras[key] || []);
          for (const [sid, active] of Object.entries(mapping)) {
            assert.equal(typeof active, 'boolean');
            if (active) membership.add(sid); else membership.delete(sid);
          }
          dates[key] = [...membership];
          if (dates[key].length) extras[key] = dates[key]; else delete extras[key];
        }
        if (ackFailure === 'missing') return response({ ok: true });
        if (ackFailure === 'malformed') return response({ ok: true, dates: { [DAY]: { invalid: true } } });
        if (ackFailure === 'json') return { ...response({ ok: true, dates }), json: async () => { throw new Error('fixture lost extra JSON reply after commit'); } };
        return response({ ok: true, dates, changedDates: Object.keys(dates) });
      }
      assert.equal(method, 'POST');
      assert.equal(url, '/api/arrive-time');
      return response({ ok: true });
    },
  });
  h.document.dispatchEvent = event => events.push(event.type);
  vm.runInContext(apiSource + '\n' + helperSource + '\n' + orderingSource + '\n' + modalSource + '\nensure=()=>{}; initExtraModal();', context,
    { filename: 'actual-extraModal-entrypoint.js' });
  const save = (button = h.save1) => Promise.all(h.document.body.listeners.click.map(listener => listener({
    target: { closest: selector => selector === '#extraModal .ex-save' ? button : null },
  })));
  const row = sid => {
    const result = h.zone.rows.find(item => item.dataset.sid === sid);
    assert.ok(result, 'rendered row ' + sid);
    return result;
  };
  return {
    ...h, state, window, context, requests, writes, messages, alerts, events,
    open: () => h.button.listeners.click[0](), save, row,
    choose: (sid, checked) => { row(sid).querySelector('.chk-sid').checked = checked; },
    setDate: value => { date = value; }, setFailure: value => { failure = value; },
    setOpenHold: value => { openHold = value; }, setSaveHold: value => { saveHold = value; },
    failSlots: () => { failSlots = true; },
    setAckFailure: value => { ackFailure = value; },
    concurrentBeforeRead: () => { extras[DAY].push('late'); slots[DAY].late = 2; },
    concurrentAfterRead: () => { injectUnrelated = true; },
    server: () => clone({ extras, slots }),
  };
}

for (const url of ['/api/extra-attend', '/api/weekend-slots']) {
  const h = harness();
  h.setFailure({ url });
  await h.open();
  assert.equal(h.save1.disabled, true);
  assert.equal(h.save2.disabled, true);
  await h.save();
  assert.equal(h.writes.length, 0, 'failed opening GET cannot enable any writer');
  assert.match(h.zone.innerHTML, /role="alert"/);
  h.setFailure(null);
  await h.open();
  assert.equal(h.save1.disabled, false, 'retry can recover readiness');
}
pass('both initial GET failures disable save and permit a fresh opening retry');

for (const failure of [
  { url: '/api/extra-attend' }, { url: '/api/weekend-slots' },
  { url: '/api/extra-attend', malformed: true, payload: [] },
  { url: '/api/weekend-slots', malformed: true, payload: null },
]) {
  const h = harness();
  await h.open();
  h.choose('add', true);
  h.setFailure(failure);
  await h.save();
  assert.equal(h.writes.length, 0, 'failed latest inputs prohibit slots/extra/arrival/order writes');
  assert.equal(h.row('add').querySelector('.chk-sid').checked, true, 'draft selection retained');
  assert.equal(h.modal.style.display, 'flex');
  assert.equal(h.save1.disabled, false, 'retry controls unlock');
  assert.equal(h.alerts.length, 1);
}
pass('latest extra/slots HTTP and invalid-root failures stop all mutation dependencies');

{
  const h = harness();
  await h.open();
  assert.equal(h.row('retired9').querySelector('.chk-sid').disabled, true, 'retired SID is display-only');
  h.choose('remove', false);
  h.choose('add', true);
  h.concurrentBeforeRead();
  h.concurrentAfterRead();
  h.setDate(OTHER); // Save owner must retain its opening date.
  await h.save();
  const delta = h.writes.find(write => write.step === '/api/extra-attend');
  assert.deepEqual(delta.body, { deltas: { [DAY]: { add: true, remove: false } } });
  assert.deepEqual(h.server().extras, { [DAY]: ['keep', 'retired9', 'late', 'later', 'add'], [OTHER]: ['other'] });
  assert.deepEqual(clone(h.state.extra), h.server().extras, 'actual final server dates hydrate client state');
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
  assert.equal(h.modal.style.display, 'none');
  assert.ok(h.writes.every(write => write.date === undefined || write.date === DAY));
  pass('opening baseline SID intent survives additions before/after final GET; final dates and untouched slots preserved');
}

{
  const h = harness(), gate = deferred(), entered = deferred();
  await h.open();
  h.choose('add', true);
  h.setSaveHold({ ...gate, entered });
  const saving = h.save();
  await entered.promise;
  assert.ok(h.save1.disabled && h.save2.disabled);
  assert.ok(h.zone.rows.flatMap(item => item.fixtureControls).every(control => control.disabled));
  const count = h.requests.length;
  await h.save(h.save2);
  await h.open();
  h.window.closeExtraAttendancePopup();
  assert.equal(h.requests.length, count, 'duplicate save and reopening are blocked during save');
  assert.equal(h.modal.style.display, 'flex', 'close cannot detach pending save owner');
  gate.resolve();
  await saving;
  assert.equal(h.writes.filter(write => write.step === '/api/extra-attend').length, 1);
  assert.equal(h.row('retired9').querySelector('.chk-sid').disabled, true);
  pass('pending actual save locks both buttons/all controls, duplicate/open/close suppression, legacy lock restoration');
}

{
  const h = harness(), gate = deferred();
  h.setOpenHold(gate);
  const older = h.open();
  h.window.closeExtraAttendancePopup();
  h.setOpenHold(null);
  gate.resolve();
  await older;
  assert.equal(h.modal.style.display, 'none');
  assert.equal(h.zone.rows.length, 0, 'late closed-session response cannot render editable rows');
  await h.save();
  assert.equal(h.writes.length, 0);
  pass('late opening response after explicit close cannot revive readiness or mutation');
}

{
  const h = harness();
  await h.open();
  h.choose('add', true);
  h.failSlots();
  await h.save();
  assert.deepEqual(h.writes.map(write => write.step), ['slots']);
  assert.equal(h.server().extras[DAY].includes('add'), false);
  assert.equal(h.modal.style.display, 'flex');
  pass('slot precommit failure prevents membership and all arrival/order followers');
}

{
  const h = harness();
  await h.open();
  h.choose('add', true);
  h.setFailure({ deltaStatus: 400 });
  await h.save();
  assert.equal(h.requests.filter(request => request.method === 'PATCH').length, 1);
  assert.ok(h.requests.every(request => request.method !== 'POST'));
  assert.equal(h.server().extras[DAY].includes('add'), false);
  assert.equal(h.modal.style.display, 'flex');
  assert.equal(h.alerts.length, 1);
  pass('old backend delta400 fails once without unsafe whole-date replacement or arrival/order writes');
}

if (options.expectAck !== 'none') {
  const guarded = options.expectAck === 'guarded';
  for (const failure of ['missing', 'malformed', 'json']) {
    const h = harness();
    await h.open();
    h.choose('add', true);
    h.concurrentBeforeRead();
    h.concurrentAfterRead();
    h.setAckFailure(failure);
    const openingState = clone(h.state.extra);
    await h.save();
    assert.equal(h.server().extras[DAY].includes('add'), true, 'primary 200 membership write committed');
    assert.equal(h.server().extras[DAY].includes('later'), true, 'unrelated late membership remains on server');
    assert.equal(h.writes.filter(write => write.step === '/api/extra-attend').length, 1);
    if (guarded) {
      assert.equal(h.writes.filter(write => write.step === '/api/arrive-time' || write.step === 'order' || write.step === 'arrival-cache').length, 0,
        'unknown acknowledgement prohibits every arrival/order follower');
      assert.deepEqual(clone(h.state.extra), openingState, 'unknown acknowledgement cannot install a guessed selectedIds list');
      assert.equal(h.modal.style.display, 'flex', 'partial failure keeps review/retry visible');
      assert.equal(h.alerts.length, 1);
      assert.match(h.alerts[0], /명단은 저장됐지만/, 'primary commit is reported separately from follow-up failure');
      assert.equal(h.save1.disabled, false);
      assert.equal(h.save2.disabled, false);
      assert.equal(h.row('add').querySelector('.chk-sid').checked, true);
      assert.ok(!h.messages.includes('보강 저장'), 'partial commit cannot announce full completion');
    } else {
      assert.ok(h.writes.some(write => write.step === '/api/arrive-time'));
      assert.ok(h.writes.some(write => write.step === 'order'));
      assert.equal(h.state.extra[DAY].includes('later'), false, 'reproduced guessed list omitting actual concurrent result');
      assert.equal(h.modal.style.display, 'none');
      assert.equal(h.alerts.length, 0);
      assert.ok(h.messages.includes('보강 저장'));
    }
    pass(guarded ? `extra200 ${failure} acknowledgement stops followers/guessed state and reports primary commit`
      : `reproduced extra200 ${failure} acknowledgement silent fallback and follower writes`);
  }
}

console.log(JSON.stringify({ source: sourcePath, sourceSha256: hash(sourceBytes),
  reusedHarness: fixturePath, reusedHarnessSha256: hash(fixtureBytes),
  groupCount: outcomes.length, outcomes, actualFullEntrypoint: true,
  actualSharedEnsureOkAndSendJson: true, persistentWrites: 0, realRequests: 0 }, null, 2));
