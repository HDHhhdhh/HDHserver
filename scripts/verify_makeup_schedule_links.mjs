import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const filename = 'static/js/admin/features/makeupPending.js';
const calendarFilename = 'static/js/admin/features/calendar.js';
const adminCssFilename = 'static/css/admin.css';
const source = fs.readFileSync(filename, 'utf8')
  .replace(/\bexport function /g, 'function ');
const calendarSource = fs.readFileSync(calendarFilename, 'utf8');
const adminCssSource = fs.readFileSync(adminCssFilename, 'utf8');
const sandbox = { console };
vm.runInNewContext(`${source}
globalThis.__exports = {
  buildPendingMakeups,
  buildActiveScheduledMakeupRows,
  buildScheduledMakeupRows,
  buildScheduledMakeupCalendarSummary,
  formatMakeupDate,
  formatMakeupCopyText,
  makeupOriginalAbsenceId,
};`, sandbox, { filename });

const {
  buildPendingMakeups,
  buildActiveScheduledMakeupRows,
  buildScheduledMakeupRows,
  buildScheduledMakeupCalendarSummary,
  formatMakeupDate,
  formatMakeupCopyText,
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
assert.equal(formatMakeupCopyText({ name: '강규현', absenceDate: '2026-07-11', slot: 1 }), '강규현 7/11 토1 결석 >>');
assert.equal(formatMakeupCopyText({ name: '김상우', absenceDate: '2026-06-27', slot: 2 }), '김상우 6/27 토2 결석 >>');
assert.equal(formatMakeupCopyText({ name: '조승연', absenceDate: '2026-07-10', dateOnly: true }), '조승연 7/10 결석 >>');
assert.match(calendarSource, /data-copy-text="\$\{escapeAttr\(copyText\)\}"/);
assert.match(calendarSource, /addEventListener\('copy', handleMakeupListCopy\)/);
assert.match(calendarSource, /clipboardData\.setData\('text\/plain', text\)/);
assert.match(calendarSource, /const scheduledTimeLabel = slotGroupLabel\(parseSlotNumbers\(item\.scheduledMakeup\?\.makeupTimes\)\)/);
assert.match(calendarSource, /const scheduledLabel = \[scheduledDate, scheduledTimeLabel\]\.filter\(Boolean\)\.join\(' · '\)/);
assert.match(calendarSource, /보강 예정: \$\{escapeHtml\(scheduledLabel\)\}/);
assert.match(calendarSource, /function selectedStudentExistingMakeupLabels\(dateStr\)/);
assert.match(calendarSource, /getScheduledMakeups\(\)\.forEach\(row =>/);
assert.match(calendarSource, /row\.originalAbsenceId === selectedOriginalAbsenceId/);
assert.match(calendarSource, /기존 보강: \$\{\[absenceDate, slotLabel\]\.filter\(Boolean\)\.join\(' · '\)\}/);
assert.match(calendarSource, /className: 'makeup-existing-schedule'/);
assert.match(adminCssSource, /\.makeup-conflict-list \.makeup-existing-schedule/);
assert.match(calendarSource, /const label = `\$\{course\} - \$\{slot\}타임\$\{note\}`/);
assert.doesNotMatch(calendarSource, /kind === 'makeup' \? '보강' : '정규'/);

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

const activeScheduledRows = buildActiveScheduledMakeupRows({
  students,
  carryover,
  operatingDate: '2026-07-24',
});
assert.equal(activeScheduledRows.length, 1);

const elapsedScheduledRows = buildActiveScheduledMakeupRows({
  students,
  carryover,
  operatingDate: '2026-07-25',
});
assert.equal(elapsedScheduledRows.length, 0);
assert.equal(buildScheduledMakeupRows({ students, carryover }).length, 1);

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
