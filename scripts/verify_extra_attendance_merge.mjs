import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const helperPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'extraAttendanceMerge.js');
const modalPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'extraModal.js');
const videoModalPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'videoModal.js');
const helper = await import(`${pathToFileURL(helperPath).href}?verify=${Date.now()}`);
const modalSource = fs.readFileSync(modalPath, 'utf8');
const videoModalSource = fs.readFileSync(videoModalPath, 'utf8');

const merged = helper.mergeExtraAttendanceSelection(
  ['baseline', 'concurrent'],
  ['baseline'],
  ['baseline', 'new'],
);
assert.deepEqual(merged.selectedIds, ['baseline', 'concurrent', 'new']);
assert.deepEqual(merged.addedIds, ['new']);
assert.deepEqual(merged.removedIds, []);

const removed = helper.mergeExtraAttendanceSelection(
  ['baseline', 'concurrent'],
  ['baseline'],
  [],
);
assert.deepEqual(removed.selectedIds, ['concurrent']);
assert.deepEqual(removed.removedIds, ['baseline']);

assert.deepEqual(
  helper.legacyExtraAttendanceIds([{ id: 'live-1' }], ['live-1', 'legacy-2']),
  ['legacy-2'],
);
assert.equal(helper.legacyStudentName('student123'), 'student');

assert.ok(modalSource.includes("fetch('/api/extra-attend', { cache: 'no-store' })"));
assert.ok(videoModalSource.includes("getJSON('/api/extra-attend')"));
for (const retiredPath of ['/api/extra', '/api/extra_attend', '/api/extra-attend/all']) {
  assert.ok(!videoModalSource.includes(`'${retiredPath}'`), `video modal still retries ${retiredPath}`);
}
assert.ok(modalSource.includes('mergeExtraAttendanceSelection('));
assert.ok(modalSource.includes('baselineSelectedIds'));
assert.ok(modalSource.includes('for (const sid of removedIds)'));
assert.ok(!modalSource.includes('for (const sid of previousSelectedIds)'));

console.log('extra attendance merge regression checks passed');
