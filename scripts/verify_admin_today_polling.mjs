import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'static/js/admin/features/todayPolling.js'), 'utf8');
const { TodayRevisionPoller, TODAY_REVISION_KEYS } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const day = '2026-10-14';
const tokens = () => Object.fromEntries(TODAY_REVISION_KEYS.map(key => [key, `initial-${key}`]));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
let count = 0;
async function test(name, check) { await check(); count += 1; process.stdout.write(`PASS ${name}\n`); }

function fixture() {
  const poller = new TodayRevisionPoller();
  let values = tokens();
  let now = 1000;
  let current = true;
  const calls = [];
  const args = () => ({ date: day, realDate: day, now,
    isCurrent: () => current,
    getRevisions: async date => { calls.push(['revision', date]); return { date, revisions: { ...values } }; },
    refresh: async keys => { calls.push(['refresh', keys]); return new Set(keys || []); },
  });
  return { poller, calls, args, set values(next) { values = next; }, get values() { return values; },
    set now(value) { now = value; }, set current(value) { current = value; } };
}

await test('initial load covers all 17 independent scopes, idle poll performs no payload request', async () => {
  const f = fixture();
  assert.equal(TODAY_REVISION_KEYS.length, 17);
  await f.poller.poll(f.args());
  assert.deepEqual(f.calls[1], ['refresh', TODAY_REVISION_KEYS]);
  f.calls.length = 0;
  f.now = 31000;
  await f.poller.poll(f.args());
  assert.deepEqual(f.calls, [['revision', day]]);
});

await test('a contact change fetches only contact; old log/progress/arrival changes retain distinct scopes', async () => {
  const f = fixture(); await f.poller.poll(f.args()); f.calls.length = 0;
  f.values.contact = 'contact-next'; f.now = 31000;
  await f.poller.poll(f.args());
  assert.deepEqual(f.calls[1], ['refresh', ['contact']]);
  f.calls.length = 0;
  f.values.logHistory = 'past-log-delete'; f.values.progressHistory = 'past-white-change'; f.values.arriveHistory = 'past-arrival';
  await f.poller.poll(f.args());
  assert.deepEqual(new Set(f.calls[1][1]), new Set(['logHistory', 'progressHistory', 'arriveHistory']));
});

await test('failed/local-fallback source is retried; successful source is acknowledged', async () => {
  const f = fixture(); await f.poller.poll(f.args()); f.now = 31000;
  f.values.contact = 'new-contact'; f.values.attendance = 'new-attendance';
  await f.poller.poll({ ...f.args(), refresh: async () => new Set(['contact']) });
  f.calls.length = 0;
  await f.poller.poll(f.args());
  assert.deepEqual(f.calls[1], ['refresh', ['attendance']]);
});

await test('same-second edits, deletions, and restoration use content tokens rather than timestamps', async () => {
  const f = fixture(); await f.poller.poll(f.args()); f.now = 31000;
  const initial = f.values.logs;
  for (const value of ['same-second-one', 'same-second-two', 'deleted-row', initial]) {
    f.values.logs = value; f.calls.length = 0;
    await f.poller.poll(f.args());
    assert.deepEqual(f.calls[1], ['refresh', ['logs']]);
  }
});

await test('mutation epoch suppresses late acknowledgment without discarding unrelated prior tokens', async () => {
  const f = fixture(); await f.poller.poll(f.args()); f.now = 31000;
  f.values.contact = 'new-contact';
  const delayed = deferred();
  const pending = f.poller.poll({ ...f.args(), refresh: () => delayed.promise });
  await Promise.resolve(); await Promise.resolve();
  f.poller.invalidate(); delayed.resolve(new Set(['contact'])); await pending;
  f.calls.length = 0; await f.poller.poll(f.args());
  assert.deepEqual(f.calls[1], ['refresh', ['contact']]);
});

await test('closed/changed date or editing modal prevents delayed revision response from starting payload reads', async () => {
  const f = fixture(); const gate = deferred();
  const pending = f.poller.poll({ ...f.args(), getRevisions: () => gate.promise });
  f.current = false; gate.resolve({ date: day, revisions: tokens() }); await pending;
  assert.deepEqual(f.calls, []);
  assert.deepEqual(f.poller.acknowledged, {});
});

await test('10 minute full safety refresh survives unchanged tokens and resets only after complete success', async () => {
  const f = fixture(); await f.poller.poll(f.args()); f.calls.length = 0;
  f.now = 601000; await f.poller.poll(f.args());
  assert.deepEqual(f.calls[1], ['refresh', TODAY_REVISION_KEYS]);
  f.calls.length = 0; f.now = 631000; await f.poller.poll(f.args());
  assert.deepEqual(f.calls, [['revision', day]]);
});

await test('404/unavailable or invalid revision shape uses old full refresh without acknowledging data', async () => {
  for (const result of [{ date: day, revisions: {} }, { date: '2026-10-13', revisions: tokens() }]) {
    const f = fixture();
    await f.poller.poll({ ...f.args(), getRevisions: async () => result });
    assert.deepEqual(f.calls, [['refresh', null]]);
    assert.deepEqual(f.poller.acknowledged, {});
  }
  const f = fixture();
  await f.poller.poll({ ...f.args(), getRevisions: async () => { throw Object.assign(new Error('absent'), { status: 404 }); } });
  assert.deepEqual(f.calls, [['refresh', null]]);
});

await test('auth denial stops polling without unauthenticated full-request amplification', async () => {
  for (const status of [401, 403]) {
    const f = fixture();
    await f.poller.poll({ ...f.args(), getRevisions: async () => { throw Object.assign(new Error('auth'), { status }); } });
    assert.deepEqual(f.calls, []);
  }
});

await test('overlapping interval/visibility events share the same pending revision request', async () => {
  const f = fixture(); const gate = deferred(); let requests = 0;
  const args = { ...f.args(), getRevisions: () => { requests++; return gate.promise; } };
  const first = f.poller.poll(args); const second = f.poller.poll(args);
  gate.resolve({ date: day, revisions: tokens() }); await Promise.all([first, second]);
  assert.equal(requests, 1);
  assert.equal(f.calls.length, 1);
});
process.stdout.write(`admin revision polling: ${count} groups passed\n`);
