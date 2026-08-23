import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/js/student.js', 'utf8');
const start = source.indexOf('const WATCH_UPDATED_AT_MIN_MS');
const end = source.indexOf('\n\n  function getProgress', start);
if (start < 0 || end < 0) throw new Error('watch timestamp normalizer was not found');

const context = {};
vm.runInNewContext(`${source.slice(start, end)}\nglobalThis.normalize = normalizeWatchUpdatedAt;`, context);
const valid = 1_787_390_000_123;
const fallback = 1_787_390_100_456;
if (context.normalize(valid, fallback) !== valid) throw new Error('valid epoch milliseconds changed');
if (context.normalize(667_934_656, fallback) !== fallback) throw new Error('Int32 timestamp was not rejected');
if (context.normalize(1_787_390_000, fallback) !== fallback) throw new Error('seconds timestamp was not rejected');
if (context.normalize('bad', fallback) !== fallback) throw new Error('invalid timestamp was not rejected');

if (/updatedAt\s*:[^\n,]*\|\s*0/.test(source)) {
  throw new Error('watch snapshot still applies bitwise timestamp coercion');
}
if (!/updatedAt:\s*normalizeWatchUpdatedAt\(next\.updatedAt\)/.test(source)) {
  throw new Error('server watch snapshot does not preserve full epoch milliseconds');
}
if (!/updatedAt:\s*normalizeWatchUpdatedAt\(prog\.updatedAt,\s*now\)/.test(source)) {
  throw new Error('outgoing watch payload does not repair stale timestamps');
}

console.log('student watch timestamp checks passed');
