import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createDemoFetch } from '../static/js/admin/demo/fetch.js';
import { loadDemoStore, saveDemoStore } from '../static/js/admin/demo/store.js';
import { patchDemoExtraAttendance } from '../static/js/admin/demo/extraAttendContract.js';
import { demoVideoRevision, validateDemoVideoWrite } from '../static/js/admin/demo/videoCatalogContract.js';

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
  removeItem(key) { this.values.delete(key); }
}
globalThis.sessionStorage = new MemoryStorage();
const clone = value => JSON.parse(JSON.stringify(value));
let forwards = 0;
const fetch = createDemoFetch({ window: { Response, location: { origin: 'http://fixture.invalid', pathname: '/demo/rh3123' } }, originalFetch: () => { forwards++; throw Error('live fetch forbidden'); } });
const seed = loadDemoStore();
const date = '2026-06-19';
const [sidA, sidB] = seed.students.map(row => row.id);
const bootstrap = fs.readFileSync('static/js/admin/demo/bootstrap.js', 'utf8');
const functionSlice = (start, end) => bootstrap.slice(bootstrap.indexOf(start), bootstrap.indexOf(end, bootstrap.indexOf(start)));
const context = vm.createContext({
  URL, Response, Date, console, cloneDemoValue: clone, loadDemoStore, saveDemoStore,
  patchDemoExtraAttendance, demoVideoRevision, validateDemoVideoWrite,
  normalizePath: path => path.replace(/\/+$/, ''),
  readJsonBody: async (_input, init) => JSON.parse(init.body || '{}'),
  applyDemoHomeworkRequest: () => null, applyStudentLogsRequest: () => null,
  isAssistantStudentNotesPath: () => false, isOperationNotesPath: () => false,
  requestHeader: (headers, name) => Object.entries(headers || {}).find(([key]) => key.toLowerCase() === name.toLowerCase())?.[1] || '',
  demoJson: (body, { status = 200, headers = {} } = {}) => new Response(JSON.stringify(body), { status, headers }),
});
vm.runInContext(functionSlice('async function handleDemoApiRequest(', '\nfunction demoJson('), context);
vm.runInContext(functionSlice('function fallbackPayloadForGet(', '\nfunction filterDateSidMap('), context);
const fallback = (path, init = {}) => context.handleDemoApiRequest({ method: init.method || 'GET', headers: init.headers, url: new URL(path, 'http://fixture.invalid') }, null, init, {});
const send = (transport, path, body, headers = {}, method = 'POST') => transport(path, { method, headers, body: JSON.stringify(body) });

for (const [name, transport] of [['primary', fetch], ['fallback', fallback]]) {
  saveDemoStore(clone(seed));
  const first = await send(transport, '/api/extra-attend', { deltas: { [date]: { [sidA]: true } } }, {}, 'PATCH');
  assert.equal(first.status, 200, name);
  const second = await send(transport, '/api/extra-attend', { deltas: { [date]: { [sidB]: true } } }, {}, 'PATCH');
  assert.deepEqual((await second.json()).dates[date], [sidA, sidB], name);
  const beforeBad = clone(loadDemoStore());
  for (const bad of [{ deltas: { [date]: { [sidA]: 1 } } }, { deltas: {}, dates: {} }, { deltas: { '2026-02-30': {} } }]) {
    assert.equal((await send(transport, '/api/extra-attend', bad, {}, 'PATCH')).status, 400, name);
    assert.deepEqual(loadDemoStore(), beforeBad);
  }
  const removed = await send(transport, '/api/extra-attend', { deltas: { [date]: { [sidA]: false } } }, {}, 'PATCH');
  assert.deepEqual((await removed.json()).dates[date], [sidB]);
  const videoGet = await transport('/api/videos');
  const revision = videoGet.headers.get('X-Store-Revision');
  assert.match(revision, /^[0-9a-f]{64}$/);
  const videos = await videoGet.json();
  videos[0].title += ' 새 제목';
  const saved = await send(transport, '/api/videos', videos, { 'If-Match': revision });
  assert.equal(saved.status, 204, name);
  assert.notEqual(saved.headers.get('X-Store-Revision'), revision);
  const committed = clone(loadDemoStore());
  videos[0].title += ' 오래된 화면';
  assert.equal((await send(transport, '/api/videos', videos, { 'If-Match': revision })).status, 409);
  assert.deepEqual(loadDemoStore(), committed);
  assert.equal((await send(transport, '/api/videos', videos, { 'If-Match': '*' })).status, 428);
  assert.deepEqual(loadDemoStore(), committed);
  const ensureBefore = clone(loadDemoStore());
  const ensure = await send(transport, '/api/updates/ensure-today', {});
  assert.deepEqual(await ensure.json(), ensureBefore.updates);
  assert.deepEqual(loadDemoStore(), ensureBefore);
}
assert.equal(forwards, 0);
console.log('P3 demo primary/fallback: SID deltas, invalid no-write, video revision/204/conflict, synthetic ensure and zero live forwards passed');
