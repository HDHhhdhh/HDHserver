import assert from 'node:assert/strict';
import fs from 'node:fs';

class MemoryStorage {
  #values = new Map();
  get length() { return this.#values.size; }
  getItem(key) { return this.#values.has(key) ? this.#values.get(key) : null; }
  setItem(key, value) { this.#values.set(String(key), String(value)); }
  removeItem(key) { this.#values.delete(String(key)); }
  key(index) { return Array.from(this.#values.keys())[index] ?? null; }
}

globalThis.sessionStorage = new MemoryStorage();

const { createDemoFetch } = await import('../static/js/admin/demo/fetch.js');

let forwarded = 0;
const originalFetch = async () => {
  forwarded += 1;
  return new Response('{}', { status: 500 });
};
const root = {
  fetch: originalFetch,
  location: {
    href: 'http://localhost/demo/rh3123',
    origin: 'http://localhost',
    pathname: '/demo/rh3123',
  },
};
const demoFetch = createDemoFetch({ window: root, originalFetch });

await demoFetch('/api/today_order', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ '2026-06-16': ['keep'], '2026-06-17': ['old'] }),
});
const patched = await demoFetch('/api/today_order', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ date: '2026-06-17', order: [' a ', 'a', 'b'] }),
});
assert.equal(patched.status, 200);
assert.deepEqual((await patched.json()).order, ['a', 'b']);
let orderMap = await (await demoFetch('/api/today_order')).json();
assert.deepEqual(orderMap['2026-06-16'], ['keep'], 'demo PATCH overwrote another date');
assert.deepEqual(orderMap['2026-06-17'], ['a', 'b']);

const deleted = await demoFetch('/api/today_order?date=2026-06-17', { method: 'DELETE' });
assert.equal(deleted.status, 200);
assert.equal((await deleted.json()).cleared, true);
orderMap = await (await demoFetch('/api/today_order')).json();
assert.deepEqual(orderMap, { '2026-06-16': ['keep'] }, 'demo DELETE overwrote another date');
assert.equal(
  (await demoFetch('/api/today_order', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-02-31', order: [] }),
  })).status,
  400,
  'demo accepted an impossible order date',
);

await demoFetch('/api/absent', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    by_date: { '2026-06-16': ['sid-a'], '2026-06-17': ['sid-a', 'sid-b'] },
    by_student: { 'sid-a': '2026-06-17', 'sid-b': '2026-06-17' },
    by_slot: { '2026-06-16': { 'sid-a': [1] }, '2026-06-17': { 'sid-a': [2], 'sid-b': [1] } },
  }),
});
const recovered = await demoFetch('/api/absent/recover', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ date: '2026-06-17', sids: ['sid-a'] }),
});
assert.equal(recovered.status, 200);
const recoveredMap = await recovered.json();
assert.deepEqual(recoveredMap.by_date['2026-06-17'], ['sid-b']);
assert.deepEqual(recoveredMap.by_date['2026-06-16'], ['sid-a']);
assert.equal(recoveredMap.by_student['sid-a'], undefined);
assert.deepEqual(recoveredMap.by_slot['2026-06-16']['sid-a'], [1]);
assert.deepEqual(recoveredMap.by_slot['2026-06-17'], { 'sid-b': [1] });

await demoFetch('/api/absent', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    by_date: { '2026-06-18': ['sid-a', 'sid-b'] },
    by_student: { 'sid-a': '2026-06-18', 'sid-b': '2026-06-18' },
    by_slot: { '2026-06-18': { 'sid-a': [1], 'sid-b': [2] } },
  }),
});
await Promise.all([
  demoFetch('/api/absent/recover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-06-18', sids: ['sid-a'] }),
  }),
  demoFetch('/api/absent/recover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: '2026-06-18', sids: ['sid-b'] }),
  }),
]);
const concurrentRecovery = await (await demoFetch('/api/absent')).json();
assert.deepEqual(concurrentRecovery.by_date['2026-06-18'], [], 'concurrent demo recoveries lost a narrow update');
assert.equal(concurrentRecovery.by_student['sid-a'], undefined);
assert.equal(concurrentRecovery.by_student['sid-b'], undefined);

const summary = await (await demoFetch('/api/logs/unarchived-summary?exclude_date=2026-06-17')).json();
assert.equal(summary.rowsAvailable, true);
for (const row of summary.rows || []) {
  assert.deepEqual(
    Object.keys(row.entry || {}).sort().filter(key => !['archived', 'done', 'hwChecked', 'selfStudy'].includes(key)),
    [],
    'demo summary leaked full log metadata',
  );
}

const fallbackSource = fs.readFileSync('static/js/admin/demo/bootstrap.js', 'utf8');
assert.match(fallbackSource, /path === '\/api\/today_order' && method === 'PATCH'/);
assert.match(fallbackSource, /path === '\/api\/today_order' && method === 'DELETE'/);
assert.match(fallbackSource, /path === '\/api\/absent\/recover'/);
assert.match(fallbackSource, /status: mutation\?\.ok === false \? 400 : 200/, 'fallback mutations must preserve HTTP error status');
assert.equal(forwarded, 0, 'Phase16 demo API escaped to the live fetch implementation');

console.log('Phase16 demo contracts passed');
