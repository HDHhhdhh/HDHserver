import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const draft = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = file => fs.readFileSync(path.join(draft, 'static/js/admin/demo', file), 'utf8');
const extract = (text, start, end) => {
  const from = text.indexOf(start), to = text.indexOf(end, from);
  assert.ok(from >= 0 && to > from);
  return text.slice(from, to);
};
const literal = { '2026-06-17': { DEMO1: { videos: ['demo-mid'], source: 'manual', unknown: { keep: true } } } };
const stored = { updates: structuredClone(literal) };
let writes = 0;
const context = vm.createContext({
  normalizePath: value => value,
  clone: structuredClone,
  cloneDemoValue: structuredClone,
  loadDemoStore: () => stored,
  saveDemoStore: () => { writes++; },
  responseJson: (_root, body) => ({ status: 200, body }),
  demoJson: body => ({ status: 200, body }),
  fetch: () => { throw new Error('live network is forbidden'); },
});
vm.runInContext(extract(source('fetch.js'), 'async function handleWrite(', '\nfunction ensureDemoState('), context);
vm.runInContext(extract(source('bootstrap.js'), 'async function handleDemoApiRequest(', '\nfunction demoJson('), context);
const primary = await context.handleWrite({}, { method: 'POST', path: '/api/updates/ensure-today' }, stored);
const fallback = await context.handleDemoApiRequest({ method: 'POST', url: new URL('http://fixture.invalid/api/updates/ensure-today') }, null, {}, {});
assert.equal(primary.status, 200);
assert.equal(fallback.status, 200);
assert.deepEqual(primary.body, literal);
assert.deepEqual(fallback.body, literal);
primary.body['2026-06-17'].DEMO1.unknown.keep = false;
assert.deepEqual(stored.updates, literal);
assert.equal(writes, 0);
console.log('Draft ensure demo: primary/fallback handlers return defensive synthetic assignments, with no storage write or live fetch');
