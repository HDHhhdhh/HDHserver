import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const draft = repo;
const day = '2026-10-14';
const shared = fs.readFileSync(path.join(repo, 'static/js/shared/api.js'), 'utf8');
const coreApi = fs.readFileSync(path.join(repo, 'static/js/admin/core/api.js'), 'utf8');
const transport = fs.readFileSync(path.join(draft, 'static/js/admin/core/bootstrapTransport.js'), 'utf8');
const stateSource = fs.readFileSync(path.join(repo, 'static/js/admin/core/state.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const strip = source => source.replace(/^import[^\n]*;\s*$/gm, '').replace(/\bexport\s+/g, '');
const base = () => ({ date: day, students: [{ id: 'literal-student', unknown: { keep: false } }],
  videos: [{ id: 'literal-video', mid: 'literal-mid', unknown: { keep: 0 } }],
  updates: { [day]: { 'literal-student': { source: 'manual', videos: [], version: 'GET-latest' } } },
  logs: { [day]: { 'literal-student': { done: false, score: 0, unknown: { keep: true } } } },
  absent: { by_date: {}, by_student: {}, by_slot: { [day]: { 'literal-student': [1] } } },
  progress: { [day]: { 'literal-student': { tests: { literal: { state: 'none', explicitBlank: true } } } } },
  schoolCal: { unknown: { keep: true } }, revisions: { updates: 'GET-latest-token' } });
const ensured = () => ({ [day]: { 'literal-student': { source: 'manual', videos: [], version: 'POST-earlier' } } });
const response = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

function runtime(handler) {
  const calls = [];
  const root = { sentinel: 'unchanged' };
  const context = vm.createContext({ window: root, todayLocalKey: () => day, Headers, Response,
    console: { warn() {}, error() {}, log() {} },
    fetch: async (url, init = {}) => {
      const call = { url: String(url), method: init.method || 'GET', init };
      calls.push(call);
      return handler(call, calls);
    },
  });
  new vm.Script([shared, strip(coreApi), strip(transport), strip(stateSource),
    'globalThis.stateRef = state; globalThis.bootstrapRef = bootstrap;'].map(strip).join('\n')).runInContext(context);
  return { calls, root, context, bootstrap: context.bootstrapRef, state: context.stateRef };
}

function oldResponses(call, payload = base()) {
  if (call.url === '/api/students') return response(payload.students);
  if (call.url === '/api/videos') return response(payload.videos);
  if (call.url.startsWith('/api/logs?')) return response(payload.logs);
  if (call.url === '/api/absent') return response(payload.absent);
  if (call.url.startsWith('/api/progress?')) return response(payload.progress);
  if (call.url === '/api/school-calendar') return response(payload.schoolCal);
  throw new Error('unexpected legacy request ' + call.url);
}

let groups = 0;
async function test(name, action) {
  await action();
  groups++;
  process.stdout.write('PASS ' + name + '\n');
}

await test('new backend makes exactly ensure POST then one GET; GET data and revision publish together', async () => {
  const payload = base();
  const run = runtime(call => call.method === 'POST' ? response(ensured()) : response(payload));
  await run.bootstrap();
  assert.deepEqual(run.calls.map(({ url, method }) => [method, url]), [
    ['POST', '/api/updates/ensure-today'], ['GET', `/api/admin/bootstrap?date=${day}`],
  ]);
  assert.deepEqual(plain(run.state.updates), payload.updates);
  assert.deepEqual(plain(run.state.revisions), payload.revisions);
  assert.deepEqual(plain(run.root.logs), payload.logs);
  assert.deepEqual(plain(run.root.progressData), payload.progress);
  assert.deepEqual(plain(run.root.absentSlotsByDate), payload.absent.by_slot);
});

await test('404 uses only existing six GETs and already completed ensure response', async () => {
  const run = runtime(call => call.method === 'POST' ? response(ensured())
    : call.url.startsWith('/api/admin/bootstrap?') ? response({ error: 'missing' }, 404) : oldResponses(call));
  await run.bootstrap();
  assert.equal(run.calls.length, 8);
  assert.equal(run.calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(run.calls.filter(call => call.url.startsWith('/api/updates?') || call.url === '/api/updates').length, 0);
  assert.deepEqual(plain(run.state.updates), ensured());
  assert.deepEqual(plain(run.state.revisions), {});
});

await test('auth/conflict/server failures do not fallback or publish partial state', async () => {
  for (const status of [400, 401, 403, 409, 428, 500, 503]) {
    const run = runtime(call => call.method === 'POST' ? response(ensured()) : response({ error: 'literal' }, status));
    const before = plain(run.state);
    await assert.rejects(run.bootstrap());
    assert.equal(run.calls.length, 2);
    assert.deepEqual(plain(run.state), before);
    assert.deepEqual(run.root, { sentinel: 'unchanged' });
  }
});

await test('network failure and HTTP200 invalid JSON do not fallback', async () => {
  for (const kind of ['network', 'json']) {
    const run = runtime(call => {
      if (call.method === 'POST') return response(ensured());
      if (kind === 'network') throw new TypeError('literal network failure');
      return new Response('{', { status: 200 });
    });
    await assert.rejects(run.bootstrap());
    assert.equal(run.calls.length, 2);
    assert.deepEqual(run.root, { sentinel: 'unchanged' });
  }
});

await test('missing keys critical roots and wrong dates fail before compatibility globals publish', async () => {
  for (const change of [value => delete value.logs, value => value.students = [null], value => value.videos = {},
    value => value.updates = [], value => value.logs = [], value => value.progress = null, value => value.date = '2026-10-13']) {
    const payload = base();
    change(payload);
    const run = runtime(call => call.method === 'POST' ? response(ensured()) : response(payload));
    const before = plain(run.state);
    await assert.rejects(run.bootstrap());
    assert.deepEqual(plain(run.state), before);
    assert.deepEqual(run.root, { sentinel: 'unchanged' });
  }
});

await test('failed or malformed ensure prevents GET and never repeats POST', async () => {
  for (const makeResponse of [() => response({ error: 'literal' }, 503), () => response({}, 404),
    () => response([])]) {
    const run = runtime(() => makeResponse());
    await assert.rejects(run.bootstrap());
    assert.equal(run.calls.length, 1);
    assert.equal(run.calls[0].method, 'POST');
    assert.deepEqual(run.root, { sentinel: 'unchanged' });
  }
});

await test('legacy optional absent/calendar failures retain empty fallbacks', async () => {
  const run = runtime(call => call.method === 'POST' ? response(ensured())
    : call.url.startsWith('/api/admin/bootstrap?') ? response({}, 404)
      : ['/api/absent', '/api/school-calendar'].includes(call.url) ? response({}, 503) : oldResponses(call));
  await run.bootstrap();
  assert.deepEqual(plain(run.state.absences), {});
  assert.deepEqual(plain(run.state.schoolCal), {});
});

await test('unknowns false zero explicit blank and unified absence slots remain intact', async () => {
  const payload = base();
  const run = runtime(call => call.method === 'POST' ? response(ensured()) : response(payload));
  await run.bootstrap();
  assert.equal(run.state.logs[day]['literal-student'].done, false);
  assert.equal(typeof run.state.logs[day]['literal-student'].score, 'number');
  assert.equal(run.state.progress[day]['literal-student'].tests.literal.explicitBlank, true);
  assert.deepEqual(plain(run.state.students), payload.students);
  assert.deepEqual(plain(run.state.videos), payload.videos);
  assert.deepEqual(plain(run.state.absentSlotsByDate), payload.absent.by_slot);
});

await test('popup-only catalogs and watch remain outside first render transport', async () => {
  const run = runtime(call => call.method === 'POST' ? response(ensured()) : response(base()));
  await run.bootstrap();
  assert.equal(run.calls.some(call => /materials|mat-assign|tests-config|watch/.test(call.url)), false);
  assert.deepEqual(plain(run.state.materials), {});
  assert.deepEqual(plain(run.state.testsConfig), { categories: {} });
});
process.stdout.write(JSON.stringify({ bootstrapTransportGroups: groups, actualSharedHelpers: true,
  actualStateShapeAndPublicationRetained: true, backendGate: "verify_admin_bootstrap_contract.py" }) + '\n');
