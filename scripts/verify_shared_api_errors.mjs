import assert from 'node:assert/strict';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { fetchJson, fetchJsonOr, ApiError } = await import(pathToFileURL(path.join(root, 'static/js/shared/api.js')));
const originalFetch = globalThis.fetch;
const originalWarn = console.warn;
const warnings = [];
let jsonReads = 0;
try {
  globalThis.fetch = async () => ({ ok: false, status: 401, text: async () => '{"ok":false}', json: async () => { jsonReads++; return { ok: false }; } });
  await assert.rejects(fetchJson('/api/protected'), error => error instanceof ApiError && error.status === 401 && error.body === '{"ok":false}');
  assert.equal(jsonReads, 0, 'an HTTP error must not be used as store data');
  console.warn = (...args) => warnings.push(args);
  const fallback = { fixture: true };
  assert.equal(await fetchJsonOr('/api/protected', fallback), fallback);
  assert.equal(warnings.length, 1);
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ rows: [] }) });
  assert.deepEqual(await fetchJson('/api/success'), { rows: [] });
  assert.deepEqual(await fetchJsonOr('/api/success', fallback), { rows: [] });
  assert.equal(warnings.length, 1);
  console.log('shared API errors: reject HTTP failures before JSON projection, observable fallback, success preserved');
} finally {
  globalThis.fetch = originalFetch;
  console.warn = originalWarn;
}
