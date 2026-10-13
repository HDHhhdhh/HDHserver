import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const helperPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'extraAttendanceMerge.js');
const saveHelperPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'scheduleOverrideSave.js');
const modalPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'extraModal.js');
const calendarPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'calendar.js');
const mainPath = path.join(ROOT, 'static', 'js', 'admin', 'main.js');
const shellPath = path.join(ROOT, 'static', 'admin.html');
const videoModalPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'videoModal.js');
const helper = await import(`${pathToFileURL(helperPath).href}?verify=${Date.now()}`);
const saveHelper = await import(`${pathToFileURL(saveHelperPath).href}?verify=${Date.now()}`);
const modalSource = fs.readFileSync(modalPath, 'utf8');
const calendarSource = fs.readFileSync(calendarPath, 'utf8');
const mainSource = fs.readFileSync(mainPath, 'utf8');
const shellSource = fs.readFileSync(shellPath, 'utf8');
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

const retiredIds = helper.legacyExtraAttendanceIds(
  [{ id: 'active' }],
  ['retired', 'active'],
);
assert.deepEqual(retiredIds, ['retired']);
const retainedSelection = helper.mergeExtraAttendanceSelection(
  ['retired', 'active'],
  ['retired', 'active'],
  ['active', ...retiredIds],
);
assert.deepEqual(retainedSelection.selectedIds, ['retired', 'active']);
assert.deepEqual(retainedSelection.removedIds, []);

assert.ok(modalSource.includes("fetch('/api/extra-attend', { cache: 'no-store' })"));
assert.ok(videoModalSource.includes("fetchJSONForVideoOpen('/api/extra-attend')"));
for (const retiredPath of ['/api/extra', '/api/extra_attend', '/api/extra-attend/all']) {
  assert.ok(!videoModalSource.includes(`'${retiredPath}'`), `video modal still retries ${retiredPath}`);
}
assert.ok(modalSource.includes('mergeExtraAttendanceSelection('));
assert.ok(modalSource.includes('baselineSelectedIds'));
assert.ok(modalSource.includes('for (const sid of removedIds)'));
assert.ok(!modalSource.includes('for (const sid of previousSelectedIds)'));
assert.ok(modalSource.includes("const activeSelectedRows = selectedRows.filter(r => !r.classList.contains('legacy'))"));
assert.equal((modalSource.match(/for \(const row of activeSelectedRows\)/g) || []).length, 2);
assert.ok(modalSource.includes('if (!currentStudentIds.has(sid)) continue'));
assert.ok(modalSource.includes("isLegacy ? 'disabled title="));
assert.ok(calendarSource.includes('...legacyExtraAttendanceIds(state.students, openingExtraIds)'));
assert.ok(modalSource.includes('saveScheduleOverridesFailClosed({'));
assert.equal((calendarSource.match(/saveScheduleOverridesFailClosed\(\{/g) || []).length, 2);
assert.equal((mainSource.match(/20260929-retired-extra1/g) || []).length, 2);
assert.ok(shellSource.includes('scheduleOverride=20260927'));
assert.ok(shellSource.includes('retiredExtra=20260929'));

const split = saveHelper.splitWeekendPatchByFinalExtra(
  { '2026-09-27': ['added', 'kept'] },
  { '2026-09-27': { added: [1], kept: [2], removed: [] } },
);
assert.deepEqual(split.beforeExtra, { '2026-09-27': { added: [1], kept: [2] } });
assert.deepEqual(split.afterExtra, { '2026-09-27': { removed: [] } });

const calls = [];
await saveHelper.saveScheduleOverridesFailClosed({
  extraMap: { '2026-09-27': ['added'] },
  weekendPatch: { '2026-09-27': { added: [1], removed: [] } },
  saveWeekend: async patch => calls.push(['weekend', patch]),
  saveExtra: async () => calls.push(['extra']),
});
assert.deepEqual(calls.map(row => row[0]), ['weekend', 'extra', 'weekend']);

const failedCalls = [];
await assert.rejects(() => saveHelper.saveScheduleOverridesFailClosed({
  extraMap: { '2026-09-27': ['added'] },
  weekendPatch: { '2026-09-27': { added: [1] } },
  saveWeekend: async patch => {
    failedCalls.push(['weekend', patch]);
    throw new Error('slot save failed');
  },
  saveExtra: async () => failedCalls.push(['extra']),
}));
assert.deepEqual(failedCalls.map(row => row[0]), ['weekend']);

const extraFailureCalls = [];
await assert.rejects(() => saveHelper.saveScheduleOverridesFailClosed({
  extraMap: { '2026-09-27': ['added'] },
  weekendPatch: { '2026-09-27': { added: [1], removed: [] } },
  saveWeekend: async patch => extraFailureCalls.push(['weekend', patch]),
  saveExtra: async () => {
    extraFailureCalls.push(['extra']);
    throw new Error('extra save failed');
  },
}));
assert.deepEqual(extraFailureCalls.map(row => row[0]), ['weekend', 'extra']);

console.log('extra attendance merge regression checks passed');
