import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const watchSource = fs.readFileSync('static/js/student/watchState.js', 'utf8');
const studentSource = fs.readFileSync('static/js/student.js', 'utf8');
const browserWindow = {};
vm.runInNewContext(watchSource, { Date, Math, Number, Object, Promise, String, window: browserWindow });

const api = browserWindow.StudentWatchState;
assert.ok(api && typeof api === 'object', 'watch state module must publish its browser contract');
assert.equal(api.WATCH_UPDATED_AT_MIN_MS, 1_000_000_000_000);

const valid = 1_787_390_000_123;
const fallback = 1_787_390_100_456;
assert.equal(api.normalizeUpdatedAt(valid, fallback), valid, 'valid epoch milliseconds changed');
assert.equal(api.normalizeUpdatedAt(667_934_656, fallback), fallback, 'Int32 timestamp was not rejected');
assert.equal(api.normalizeUpdatedAt(1_787_390_000, fallback), fallback, 'seconds timestamp was not rejected');
assert.equal(api.normalizeUpdatedAt('bad', fallback), fallback, 'invalid timestamp was not rejected');

const base = { last: 10, dur: 100, completed: false, updatedAt: valid };
const patchRecord = { last: 20, dur: 100, completed: false, updatedAt: valid + 50 };
const before = JSON.stringify({ base, patchRecord });
const merged = api.mergeRecords(base, patchRecord, valid + 100);
assert.equal(merged.updatedAt, valid + 100, 'merge must preserve full epoch milliseconds');
assert.equal(JSON.stringify({ base, patchRecord }), before, 'watch merge mutated its inputs');

if (/updatedAt\s*:[^\n,]*\|\s*0/.test(`${watchSource}\n${studentSource}`)) {
  throw new Error('watch snapshot still applies bitwise timestamp coercion');
}
assert.match(
  watchSource,
  /updatedAt:\s*normalizeUpdatedAt\(next\.updatedAt\)/,
  'server watch snapshot does not preserve full epoch milliseconds',
);
assert.match(
  watchSource,
  /updatedAt:\s*normalizeUpdatedAt\(progress\.updatedAt,\s*currentTime\)/,
  'outgoing watch payload does not repair stale timestamps',
);
assert.match(
  studentSource,
  /const studentWatchState = window\.StudentWatchState;/,
  'student entrypoint must delegate watch timestamp handling to the watch module',
);

console.log('student watch timestamp checks passed');
