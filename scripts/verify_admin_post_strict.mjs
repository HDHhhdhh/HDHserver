import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const draft = path.dirname(fileURLToPath(import.meta.url));
const strip = text => text.replace(/^import .*;\r?\n/gm, '').replace(/\bexport\s+/g, '');
const calls = [];
let status = 200, parsed = 0;
const context = vm.createContext({
  Headers,
  console: { warn() {} },
  fetch: async (url, init) => {
    calls.push({ url, init });
    return {
      ok: status < 400, status,
      json: async () => { parsed++; return { preserved: '한글' }; },
      text: async () => '{"message":"fixture denied"}',
    };
  },
});
vm.runInContext(strip(fs.readFileSync(path.join(root, 'static/js/shared/api.js'), 'utf8')), context);
vm.runInContext(strip(fs.readFileSync(path.join(root, 'static/js/admin/core/api.js'), 'utf8')) + '\nglobalResult = api;', context);
const actual = await context.globalResult.postStrict('/api/updates/ensure-today', {}, 'fixture ensure', { cache: 'no-store' });
assert.equal(actual.preserved, '한글');
assert.equal(calls[0].url, '/api/updates/ensure-today');
assert.equal(calls[0].init.method, 'POST');
assert.equal(calls[0].init.body, '{}');
assert.equal(calls[0].init.cache, 'no-store');
assert.equal(calls[0].init.headers['Content-Type'], 'application/json');
assert.equal(parsed, 1);
status = 401;
await assert.rejects(context.globalResult.postStrict('/api/updates/ensure-today', {}), /fixture denied/);
assert.equal(parsed, 1, 'HTTP failure must not become a successful JSON snapshot');
console.log('Draft postStrict: actual shared error handling, POST/body/cache headers, and no snapshot parsing after 401');
