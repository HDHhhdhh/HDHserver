import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const filename = 'static/js/admin/features/makeupPending.js';
const source = fs.readFileSync(filename, 'utf8')
  .replace(/\bexport function /g, 'function ');
const sandbox = { console };
vm.runInNewContext(`${source}
globalThis.__exports = {
  buildPendingMakeups,
  buildScheduledMakeupRows,
  buildScheduledMakeupCalendarSummary,
  formatMakeupDate,
  makeupOriginalAbsenceId,
};`, sandbox, { filename });

const {
  buildPendingMakeups,
  buildScheduledMakeupRows,
  buildScheduledMakeupCalendarSummary,
  formatMakeupDate,
  makeupOriginalAbsenceId,
} = sandbox.__exports;

const students = [{
  id: 'stu-1',
  name: '민주희',
  school: '운정고',
  curriculum: '미적분2',
  subCurriculum: 'A:Ble',
  day1: '금2',
}];

const demand = {
  source: 'absence',
  sid: 'stu-1',
  absenceDate: '2026-07-03',
  slot: 2,
};

assert.equal(makeupOriginalAbsenceId(demand), 'absence|2026-07-03|stu-1|2');
assert.equal(formatMakeupDate('2026-07-03'), '7/3(금)');

const carryover = {
  by_absence: {
    '2026-07-03': {
      'stu-1|2': {
        state: 'carried',
        scheduledMakeup: {
          originalAbsenceId: 'absence|2026-07-03|stu-1|2',
          studentId: 'stu-1',
          makeupDate: '2026-07-24',
          makeupTimes: [2],
          status: 'scheduled',
          createdBy: 'makeup-planner',
          ownedExtra: true,
          ownedSlots: [2],
        },
      },
    },
  },
};

const scheduledRows = buildScheduledMakeupRows({ students, carryover });
assert.equal(scheduledRows.length, 1);
assert.equal(scheduledRows[0].originalAbsenceId, 'absence|2026-07-03|stu-1|2');
assert.equal(scheduledRows[0].scheduledMakeup.makeupDate, '2026-07-24');

const pendingRows = buildPendingMakeups({
  students,
  absentByDate: { '2026-07-03': ['stu-1'] },
  absentSlotsByDate: { '2026-07-03': { 'stu-1': [2] } },
  carryover,
});
assert.equal(pendingRows.length, 0);

const cancelledCarryover = {
  by_absence: {
    '2026-07-03': {
      'stu-1|2': {
        state: 'open',
        scheduledMakeup: {
          originalAbsenceId: 'absence|2026-07-03|stu-1|2',
          studentId: 'stu-1',
          makeupDate: '2026-07-24',
          makeupTimes: [2],
          status: 'cancelled',
        },
      },
    },
  },
};
const cancelledPending = buildPendingMakeups({
  students,
  absentByDate: { '2026-07-03': ['stu-1'] },
  absentSlotsByDate: { '2026-07-03': { 'stu-1': [2] } },
  carryover: cancelledCarryover,
});
assert.equal(cancelledPending.length, 1);
assert.equal(buildScheduledMakeupRows({ students, carryover: cancelledCarryover }).length, 0);

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function scheduledFixture(count) {
  return Array.from({ length: count }, (_, index) => ({
    originalAbsenceId: `absence|2026-07-${String(index + 1).padStart(2, '0')}|stu-${index + 1}|1`,
    scheduledMakeup: {
      makeupDate: `2026-07-${String(index + 21).padStart(2, '0')}`,
      makeupTimes: [1],
      status: 'scheduled',
    },
    details: { index },
  }));
}

function assertCalendarSummary(rows, expected) {
  const before = deepClone(rows);
  const summary = buildScheduledMakeupCalendarSummary(rows);

  assert.equal(JSON.stringify(summary), JSON.stringify({
    previewRows: before.slice(0, 2),
    total: expected.total,
    remaining: expected.remaining,
  }));
  assert.equal(summary.total, expected.total);
  assert.equal(summary.remaining, expected.remaining);
  assert.equal(JSON.stringify(summary.previewRows), JSON.stringify(rows.slice(0, 2)));
  assert.equal(JSON.stringify(rows), JSON.stringify(before));
  assert.notStrictEqual(summary, rows);
  assert.notStrictEqual(summary.previewRows, rows);
}

assertCalendarSummary(scheduledFixture(0), { total: 0, remaining: 0 });
assertCalendarSummary(scheduledFixture(1), { total: 1, remaining: 0 });
assertCalendarSummary(scheduledFixture(2), { total: 2, remaining: 0 });
const fourScheduledRows = scheduledFixture(4);
assertCalendarSummary(fourScheduledRows, { total: 4, remaining: 2 });
const fourRowSummary = buildScheduledMakeupCalendarSummary(fourScheduledRows);
assert.equal(fourRowSummary.previewRows.length, 2);
console.log(`calendar summary observable: 4 rows -> previewRows=${fourRowSummary.previewRows.length} total=${fourRowSummary.total} remaining=${fourRowSummary.remaining}`);

console.log('makeup schedule frontend helpers ok');
