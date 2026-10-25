import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const filename = 'static/js/admin/features/makeupPending.js';
const calendarFilename = 'static/js/admin/features/calendar.js';
const todayFilename = 'static/js/admin/features/today.js';
const adminCssFilename = 'static/css/admin.css';
const source = fs.readFileSync(filename, 'utf8')
  .replace(/\bexport function /g, 'function ');
const calendarSource = fs.readFileSync(calendarFilename, 'utf8').replace(/\r\n/g, '\n');
const todaySource = fs.readFileSync(todayFilename, 'utf8');
const adminCssSource = fs.readFileSync(adminCssFilename, 'utf8');
const sharedApiSource = fs.readFileSync('static/js/shared/api.js', 'utf8').replace(/^export /gm, '');
const sandbox = { console };
vm.runInNewContext(`${source}
globalThis.__exports = {
  buildPendingMakeups,
  buildActiveScheduledMakeupRows,
  buildScheduledMakeupRows,
  buildScheduledMakeupCalendarSummary,
  scheduledMakeupStudentIdsForDate,
  formatMakeupDate,
  formatMakeupCopyText,
  makeupOriginalAbsenceId,
  formatMakeupPlannerLabel,
};`, sandbox, { filename });

const {
  buildPendingMakeups,
  buildActiveScheduledMakeupRows,
  buildScheduledMakeupRows,
  buildScheduledMakeupCalendarSummary,
  scheduledMakeupStudentIdsForDate,
  formatMakeupDate,
  formatMakeupCopyText,
  makeupOriginalAbsenceId,
  formatMakeupPlannerLabel,
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
assert.match(calendarSource, /'보강 예정'\}: \$\{escapeHtml\(scheduledLabel\)\}/);
assert.match(calendarSource, /function selectedStudentExistingMakeupLabels\(dateStr\)/);
assert.match(calendarSource, /getScheduledMakeups\(\)\.forEach\(row =>/);
assert.match(calendarSource, /row\.originalAbsenceId === selectedOriginalAbsenceId/);
assert.match(calendarSource, /기존 보강: \$\{\[absenceDate, slotLabel\]\.filter\(Boolean\)\.join\(' · '\)\}/);
assert.match(calendarSource, /className: 'makeup-existing-schedule'/);
assert.match(adminCssSource, /\.makeup-conflict-list \.makeup-existing-schedule/);
assert.match(calendarSource, /const label = `\$\{course\} - \$\{slot\}타임\$\{note\}`/);
assert.doesNotMatch(calendarSource, /kind === 'makeup' \? '보강' : '정규'/);
assert.match(todaySource, /scheduledMakeupStudentIdsForDate\(\{/);
assert.match(todaySource, /new Set\(\[\.\.\.extraIds, \.\.\.scheduledMakeupIds\]\)/);

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
assert.deepEqual(
  Array.from(scheduledMakeupStudentIdsForDate({ students, carryover, date: '2026-07-24' })),
  ['stu-1'],
);
assert.deepEqual(
  Array.from(scheduledMakeupStudentIdsForDate({ students, carryover, date: '2026-07-25' })),
  [],
);

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

const noteOnlyPrecreditCarryover = {
  by_absence: {
    '2026-09-25': {
      'stu-1|2': {
        state: 'carried',
        note: '예정 정규수업 결석: 2026-09-25 2타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 미적분2 (stu-1). 비중복 직보 크레딧. 실제 이행 완료 표시는 아님. [approved-fixture-20260923]',
      },
    },
  },
};
const noteOnlyRows = buildScheduledMakeupRows({ students, carryover: noteOnlyPrecreditCarryover });
assert.equal(noteOnlyRows.length, 1, 'legacy direct-credit notes must remain visible as scheduled makeups');
assert.equal(noteOnlyRows[0].originalAbsenceId, 'absence|2026-09-25|stu-1|2');
assert.equal(noteOnlyRows[0].scheduledMakeup.makeupDate, '2026-09-27');
assert.equal(JSON.stringify(noteOnlyRows[0].scheduledMakeup.makeupTimes), JSON.stringify([2]));
assert.equal(noteOnlyRows[0].scheduledMakeup.derivedFromPrecreditNote, true);
assert.equal(noteOnlyRows[0].scheduledMakeup.ownedExtra, true);
assert.equal(JSON.stringify(noteOnlyRows[0].scheduledMakeup.ownedSlots), JSON.stringify([2]));
assert.deepEqual(
  Array.from(scheduledMakeupStudentIdsForDate({ students, carryover: noteOnlyPrecreditCarryover, date: '2026-09-27' })),
  ['stu-1'],
);

const cancelledNoteOnlyCarryover = deepClone(noteOnlyPrecreditCarryover);
cancelledNoteOnlyCarryover.by_absence['2026-09-25']['stu-1|2'].scheduledMakeup = {
  originalAbsenceId: 'absence|2026-09-25|stu-1|2',
  studentId: 'stu-1',
  makeupDate: '2026-09-27',
  makeupTimes: [2],
  status: 'cancelled',
};
assert.equal(
  buildScheduledMakeupRows({ students, carryover: cancelledNoteOnlyCarryover }).length,
  0,
  'an explicit cancelled schedule must suppress the legacy note fallback',
);
const clearedNoteOnlyCarryover = deepClone(noteOnlyPrecreditCarryover);
clearedNoteOnlyCarryover.by_absence['2026-09-25']['stu-1|2'].scheduledMakeup = null;
assert.equal(
  buildScheduledMakeupRows({ students, carryover: clearedNoteOnlyCarryover }).length,
  0,
  'an explicitly cleared schedule field must suppress the legacy note fallback',
);
const conflictingAliasCarryover = deepClone(noteOnlyPrecreditCarryover);
conflictingAliasCarryover.by_absence['2026-09-25']['stu-1|2'].scheduledMakeup = null;
conflictingAliasCarryover.by_absence['2026-09-25']['stu-1|2'].scheduled_makeup = {
  original_absence_id: 'absence|2026-09-25|stu-1|2',
  student_id: 'stu-1',
  makeup_date: '2026-09-27',
  makeup_times: [2],
  status: 'scheduled',
};
assert.equal(
  buildScheduledMakeupRows({ students, carryover: conflictingAliasCarryover }).length,
  0,
  'the canonical camel-case tombstone must not be bypassed by a stale snake-case alias',
);
const snakeOnlyCarryover = deepClone(noteOnlyPrecreditCarryover);
delete snakeOnlyCarryover.by_absence['2026-09-25']['stu-1|2'].note;
snakeOnlyCarryover.by_absence['2026-09-25']['stu-1|2'].scheduled_makeup = {
  original_absence_id: 'absence|2026-09-25|stu-1|2',
  student_id: 'stu-1',
  makeup_date: '2026-09-27',
  makeup_times: [2],
  status: 'scheduled',
};
assert.equal(buildScheduledMakeupRows({ students, carryover: snakeOnlyCarryover }).length, 1);
const crossSubjectPrecreditCarryover = deepClone(noteOnlyPrecreditCarryover);
crossSubjectPrecreditCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  '예정 정규수업 결석: 2026-09-25 2타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 기하 (stu-2). 실제 이행 완료 표시는 아님. [approved-fixture-20260923]';
const crossSubjectRows = buildScheduledMakeupRows({ students, carryover: crossSubjectPrecreditCarryover });
assert.equal(crossSubjectRows.length, 1);
assert.equal(crossSubjectRows[0].scheduledMakeup.creditedStudentId, 'stu-2');
assert.equal(crossSubjectRows[0].scheduledMakeup.ownedExtra, false);
assert.equal(JSON.stringify(crossSubjectRows[0].scheduledMakeup.ownedSlots), JSON.stringify([]));
const unapprovedPrecreditCarryover = deepClone(noteOnlyPrecreditCarryover);
unapprovedPrecreditCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  '취소됨: 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 미적분2 (stu-1).';
assert.equal(
  buildScheduledMakeupRows({ students, carryover: unapprovedPrecreditCarryover }).length,
  0,
  'unapproved or stale prose must not become an active schedule',
);
const splitApprovalPrecreditCarryover = deepClone(noteOnlyPrecreditCarryover);
splitApprovalPrecreditCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  '[approved-unrelated] 실제 이행 완료 표시는 아님.\n직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 미적분2 (stu-1).';
assert.equal(
  buildScheduledMakeupRows({ students, carryover: splitApprovalPrecreditCarryover }).length,
  0,
  'approval and disclaimer from another line must not authorize a reservation sentence',
);
const nextLineApprovalPrecreditCarryover = deepClone(noteOnlyPrecreditCarryover);
nextLineApprovalPrecreditCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  '예정 정규수업 결석: 2026-09-25 2타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 미적분2 (stu-1). 실제 이행 완료 표시는 아님.\n[approved-fixture-20260923]';
assert.equal(
  buildScheduledMakeupRows({ students, carryover: nextLineApprovalPrecreditCarryover }).length,
  0,
  'the approval marker must stay on the same canonical record line',
);
const mismatchedAbsencePrecreditCarryover = deepClone(noteOnlyPrecreditCarryover);
mismatchedAbsencePrecreditCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  '예정 정규수업 결석: 2026-09-26 2타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 미적분2 (stu-1). 실제 이행 완료 표시는 아님. [approved-fixture-20260923]';
assert.equal(
  buildScheduledMakeupRows({ students, carryover: mismatchedAbsencePrecreditCarryover }).length,
  0,
  'an approval copied from a different absence date must not authorize the row',
);
const unrelatedEarlierAbsencePrecreditCarryover = deepClone(noteOnlyPrecreditCarryover);
unrelatedEarlierAbsencePrecreditCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  '과거 결석: 2026-09-25 2타임 / 다른 결석: 2026-09-26 1타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 미적분2 (stu-1). 실제 이행 완료 표시는 아님. [approved-fixture-20260923]';
assert.equal(
  buildScheduledMakeupRows({ students, carryover: unrelatedEarlierAbsencePrecreditCarryover }).length,
  0,
  'only the absence clause immediately before the credit marker may authorize the row',
);
const flexibleAbsenceSpacingCarryover = deepClone(noteOnlyPrecreditCarryover);
flexibleAbsenceSpacingCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  flexibleAbsenceSpacingCarryover.by_absence['2026-09-25']['stu-1|2'].note
    .replace('2026-09-25 2타임', '2026-09-25\t  2  타임');
assert.equal(buildScheduledMakeupRows({ students, carryover: flexibleAbsenceSpacingCarryover }).length, 1);
const emptyCreditedStudentPrecreditCarryover = deepClone(noteOnlyPrecreditCarryover);
emptyCreditedStudentPrecreditCarryover.by_absence['2026-09-25']['stu-1|2'].note =
  '예정 정규수업 결석: 2026-09-25 2타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 미적분2 (   ). 실제 이행 완료 표시는 아님. [approved-fixture-20260923]';
assert.equal(
  buildScheduledMakeupRows({ students, carryover: emptyCreditedStudentPrecreditCarryover }).length,
  0,
  'an empty credited student id must not produce a schedule',
);

// A displayed count is not a quota: render more than 40 active reservations,
// keep today's rows, and hide only reservations before the operating date.
const manyStudents = Array.from({ length: 76 }, (_, i) => ({
  id: `scroll-${i}`, name: `검증${String(i).padStart(3, '0')}`, school: '검증고', curriculum: '미적분1',
}));
const manyCarryover = { by_absence: { '2026-09-01': Object.fromEntries(manyStudents.map((student, i) => [
  `${student.id}|2`, { state: 'carried', scheduledMakeup: {
    originalAbsenceId: `absence|2026-09-01|${student.id}|2`, studentId: student.id,
    makeupDate: i === 75 ? '2026-09-04' : i % 2 ? '2026-09-06' : '2026-09-05',
    makeupTimes: [2], status: 'scheduled',
  } },
])) } };
const untouchedReservations = JSON.stringify(manyCarryover);
let scrollOperatingDate = '2026-09-05';
const activeScrollRows = () => buildActiveScheduledMakeupRows({
  students: manyStudents, carryover: manyCarryover, operatingDate: scrollOperatingDate,
});
assert.equal(activeScrollRows().length, 75);
const scrollElements = Object.fromEntries([
  'makeupPlannerList', 'makeupPlannerHint', 'makeupPlannerSearch',
  'makeupStatusList', 'makeupStatusSearch', 'makeupStatusHint', 'attendanceCheckToggle',
].map(id => [id, { innerHTML: '', textContent: '', value: '' }]));
const renderSource = calendarSource.slice(
  calendarSource.indexOf('  function renderMakeupHistory(item) {'),
  calendarSource.indexOf('  async function refreshMakeupPlanner() {'),
);
const renderSandbox = {
  state: {},
  $: id => scrollElements[id], ensureMakeupPlanner() {}, updateMakeupFocusUI() {},
  sortPlannerItems: rows => rows, studentSearchKey: (student, fields) => [student.name, ...fields].join(' '),
  matchesSearchKey: (key, query) => key.includes(query.trim()), applySearchPlaceholder() {},
  getPendingMakeups: () => [], getScheduledMakeupStatusRows: activeScrollRows,
  attendanceCheckMode: false, manualAbsenceSelection: null, makeupSelection: null,
  makeupItemKey: makeupOriginalAbsenceId, formatMakeupDate, formatMakeupCopyText,
  formatMakeupPlannerLabel,
  escapeHtml: value => String(value), escapeAttr: value => String(value),
  parseSlotNumbers: slots => slots, slotGroupLabel: slots => `${slots.join(',')}타임`,
};
vm.runInNewContext(`${renderSource}\nrenderMakeupPlanner();`, renderSandbox);
assert.equal((scrollElements.makeupStatusList.innerHTML.match(/class="makeup-row"/g) || []).length, 75);
assert.equal(scrollElements.makeupStatusHint.textContent, '전체 75건');
assert.match(scrollElements.makeupStatusList.innerHTML, /검증074/);
assert.doesNotMatch(scrollElements.makeupStatusList.innerHTML, /검증075/);
scrollElements.makeupStatusSearch.value = '검증074';
vm.runInNewContext(`${renderSource}\nrenderMakeupPlanner();`, renderSandbox);
assert.equal((scrollElements.makeupStatusList.innerHTML.match(/class="makeup-row"/g) || []).length, 1);
assert.equal(scrollElements.makeupStatusHint.textContent, '검색 1건 · 전체 75건');
scrollElements.makeupStatusSearch.value = '';
scrollOperatingDate = '2026-09-07';
vm.runInNewContext(`${renderSource}\nrenderMakeupPlanner();`, renderSandbox);
assert.equal(scrollElements.makeupStatusHint.textContent, '전체 0건');
assert.match(scrollElements.makeupStatusList.innerHTML, /보강 예정이 없습니다/);
assert.equal(JSON.stringify(manyCarryover), untouchedReservations, 'display filtering must not change reservations');
assert.match(calendarSource, /id="makeupStatusList"[^>]*tabindex="0"[^>]*aria-label="보강 예정 목록"/);
assert.match(adminCssSource, /#makeupStatusList\s*\{[^}]*overflow-y:\s*auto;[^}]*scrollbar-gutter:\s*stable;/);

// History stays outside both rows; opening it must not enter scheduling or save anything.
const historyItem = { ...buildScheduledMakeupRows({ students, carryover })[0],
  scheduleHistory: [
    { action: 'scheduled', makeupDate: '2026-10-04', makeupTimes: [2], missedSlots: [2] },
    { action: 'rescheduled', makeupDate: '2026-10-11', makeupTimes: [2] },
  ],
};
renderSandbox.getPendingMakeups = () => [historyItem];
renderSandbox.getScheduledMakeupStatusRows = () => [historyItem];
vm.runInNewContext('renderMakeupPlanner();', renderSandbox);
for (const id of ['makeupPlannerList', 'makeupStatusList']) {
  const html = scrollElements[id].innerHTML;
  assert.match(html, /class="makeup-history-btn"[^>]*data-makeup-action="history"[^>]*>이력<\/button>/);
  assert.ok(html.indexOf('data-makeup-action="history"') < html.indexOf('data-makeup-action="pick"'));
  assert.doesNotMatch(html, /<details|<ol>|최초 예약|10\/11/);
}
const historyElements = {};
const closeButton = { addEventListener(type, handler) { this[type] = handler; } };
let dialogCount = 0;
const historySandbox = {
  ...renderSandbox,
  $: id => historyElements[id],
  document: {
    createElement(tag) {
      assert.equal(tag, 'dialog');
      dialogCount++;
      return {
        open: false, setAttribute() {}, querySelector: () => closeButton,
        addEventListener(type, handler) { this[type] = handler; },
        showModal() { this.open = true; }, close() { this.open = false; },
      };
    },
    body: { append(dialog) { historyElements[dialog.id] = dialog; } },
  },
};
for (const id of ['makeupHistorySummary', 'makeupHistoryContent', 'makeupPlannerList', 'makeupStatusList']) {
  historyElements[id] = { addEventListener(type, handler) { this[type] = handler; } };
}
vm.runInNewContext(`${calendarFunction('renderMakeupHistory')}\n${calendarFunction('openMakeupHistory')}\n${calendarSource.slice(
  calendarSource.indexOf("    $('makeupPlannerList')?.addEventListener('click'"),
  calendarSource.indexOf('\n  }\n\n  function getPendingMakeups'),
)}`, historySandbox);
for (const id of ['makeupPlannerList', 'makeupStatusList']) {
  historyElements[id].click({ target: { closest: () => ({ dataset: { makeupAction: 'history', key: makeupOriginalAbsenceId(historyItem) } }) } });
  assert.equal(historyElements.makeupHistoryDialog.open, true);
  assert.match(historyElements.makeupHistoryContent.innerHTML, /10\/4.*최초 예약.*보강 결석/);
  assert.match(historyElements.makeupHistoryContent.innerHTML, /10\/11.*변경/);
  assert.match(historyElements.makeupHistorySummary.textContent, /원결석 2타임/);
  let stopped = false;
  historyElements.makeupHistoryDialog.keydown({ key: 'Escape', stopPropagation() { stopped = true; } });
  assert.equal(stopped, true, 'Escape must not cancel the underlying calendar selection');
  closeButton.click();
  assert.equal(historyElements.makeupHistoryDialog.open, false);
}
historySandbox.openMakeupHistory({ ...historyItem, scheduleHistory: [] });
assert.match(historyElements.makeupHistoryContent.innerHTML, /예약 이력이 없습니다/);
assert.equal(dialogCount, 1, 'reuse the history dialog without duplicate listeners');

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
assert.deepEqual(
  Array.from(scheduledMakeupStudentIdsForDate({ students, carryover: cancelledCarryover, date: '2026-07-24' })),
  [],
);

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

const selfStudyAbsenceInput = {
  students: [{ id: 'self', day1: '월1', day2: '월2' }, { id: 'regular', day1: '월1' }],
  absentByDate: { '2026-09-14': ['self', 'regular'], '2026-09-07': ['self'] },
  absentSlotsByDate: { '2026-09-14': { self: [1, 2] } },
  carryover: { by_absence: { '2026-09-14': { self: { state: 'self-study' } } } },
  manualMakeups: { '2026-09-14': { manual: { sid: 'self', slot: 1 } } },
};
const selfStudyBefore = JSON.stringify(selfStudyAbsenceInput);
const pendingKeys = buildPendingMakeups(selfStudyAbsenceInput).map(row => `${row.source}|${row.absenceDate}|${row.sid}|${row.slot}`);
assert.equal(JSON.stringify(pendingKeys), JSON.stringify([
  'absence|2026-09-07|self|1', 'absence|2026-09-07|self|2',
  'absence|2026-09-14|regular|1', 'manual|2026-09-14|self|1',
]));
assert.equal(JSON.stringify(selfStudyAbsenceInput), selfStudyBefore, 'exemption projection must not mutate inputs');
const withSupply = { ...selfStudyAbsenceInput, absentByDate: { '2026-09-14': ['self'], '2026-09-21': ['self'] }, extra: { '2026-09-15': ['self'] } };
const laterSelf = buildPendingMakeups(withSupply).filter(row => row.source === 'absence');
assert.equal(laterSelf.length, 1, 'self-study exemption must not consume a makeup supply for a later regular absence');
assert.equal(laterSelf[0].absenceDate, '2026-09-21');
const rendererSource = fs.readFileSync('static/js/admin/features/today.render.js', 'utf8');
const markStart = rendererSource.indexOf('async function markMakeupDemandOpen(');
const markEnd = rendererSource.indexOf('// Normalize absence maps', markStart);
const markSource = rendererSource.slice(markStart, markEnd);
for (const state of ['self-study', 'open']) {
  const calls = [];
  const driver = {
    parseSlotNumbers: sandbox.parseSlotNumbers,
    ensureOk: async () => {},
    fetch: async () => ({ headers: { get: () => 'fixture-revision' }, json: async () => ({ by_absence: { '2026-09-14': { self: { state } } } }) }),
    sendJson: async (_url, body) => { calls.push(body); return { status: 200 }; },
  };
  vm.runInNewContext(`${markSource}; globalThis.run = markMakeupDemandOpen;`, driver);
  await driver.run('2026-09-14', 'self', [1, 2]);
  assert.equal(calls.length, state === 'self-study' ? 0 : 1, 'the real row action must not reopen an exempt absence');
}
const calendarOpenStart = calendarSource.indexOf('  async function markAbsenceMakeupOpen(');
const calendarResolveStart = calendarSource.indexOf('  async function resolveFirstOpenMakeupDemandsForSids(', calendarOpenStart);
const calendarResolveEnd = calendarSource.indexOf('\n  async function ', calendarResolveStart + 1);
const calendarWrites = [];
const calendarExemptPayload = { by_absence: {
  '2026-09-14': { self: { state: 'self-study' }, 'self|1': { state: 'open' } },
  '2026-09-21': { 'self|1': { state: 'open' } },
}, manual: {} };
const calendarDriver = {
  parseSlotNumbers: sandbox.parseSlotNumbers,
  normalizeCarryoverPayload: value => value,
  fetchMakeupCarryoverSnapshot: async () => ({ payload: structuredClone(calendarExemptPayload), revision: 'test' }),
  postMakeupCarryoverSnapshot: async body => { calendarWrites.push(body); return body; },
};
assert.ok(calendarResolveEnd > calendarResolveStart, 'calendar helper boundaries must remain explicit');
vm.runInNewContext(`let CARRYOVER = {};
${calendarSource.slice(calendarOpenStart, calendarResolveEnd)}
globalThis.open = markAbsenceMakeupOpen;
globalThis.resolve = resolveFirstOpenMakeupDemandsForSids;`, calendarDriver);
await calendarDriver.open('2026-09-14', [{ sid: 'self', slots: [1, 2] }]);
assert.equal(calendarWrites.length, 0, 'calendar absence actions must not reopen a self-study demand');
await calendarDriver.resolve(['self']);
assert.equal(calendarWrites.length, 1);
assert.equal(calendarWrites[0].by_absence['2026-09-14'].self.state, 'self-study');
assert.equal(calendarWrites[0].by_absence['2026-09-14']['self|1'].state, 'open', 'masked old slot rows must not consume the next makeup');
assert.equal(calendarWrites[0].by_absence['2026-09-21']['self|1'].state, 'carried');
// Execute the real cancellation/reschedule entrypoints against literal API data.
// No production app import, stores, or network requests are used.
function calendarFunction(name) {
  const match = new RegExp(`  (?:async )?function ${name}\\(`).exec(calendarSource);
  assert.ok(match, `missing calendar function: ${name}`);
  const start = match.index;
  const end = calendarSource.indexOf('\n  }\n', start);
  assert.ok(end > start, `missing end boundary: ${name}`);
  return calendarSource.slice(start, end + 5);
}

function historyDriver({ recorded = {}, invalid = false, failure = false, httpFailure = false, conflict = false } = {}) {
  const oldDate = '2026-09-19';
  const newDate = '2026-10-03';
  const schedule = { makeupDate: oldDate, makeupTimes: [2], ownedExtra: true, ownedSlots: [2], createdBy: 'makeup-planner' };
  const item = { sid: 'stu-1', absenceDate: '2026-09-26', source: 'absence', student: students[0] };
  const initial = { by_absence: { '2026-09-26': { 'stu-1|2': { scheduledMakeup: schedule } } }, manual: {} };
  const calls = { reads: [], carryover: [], extra: [], weekend: [], arrive: [], ownership: [] };
  const driver = {
    console, URLSearchParams, Set, Date,
    state: { students }, window: {}, document: { dispatchEvent() {} }, CustomEvent: class {},
    MAKEUP_SLOTS: [1, 2], MAKEUP_ARRIVE_BY_SLOT: { 1: '13:00', 2: '18:00' },
    DATE_RE: /^\d{4}-\d{2}-\d{2}$/,
    makeupOriginalAbsenceId,
    parseSlotNumbers: sandbox.parseSlotNumbers, serializeSlots: rows => rows,
    combinedSlotsForStudent: (_student, _date, slots) => slots,
    clonePlainMap: deepClone, normalizeCarryoverPayload: value => value,
    getScheduledMakeupForItem: () => schedule, getScheduledMakeups: () => [],
    makeupCarryoverKey: () => 'stu-1|2', makeupItemKey: () => 'fixture',
    preloadExtraWeekend: async () => {},
    fetch: async (url, options) => {
      calls.reads.push(url);
      assert.equal(options.cache, 'no-store');
      if (failure) throw new Error('fixture read failure');
      const query = new URL(url, 'http://fixture').searchParams;
      assert.equal(query.get('sid'), 'stu-1');
      const kind = recorded[query.get('date')];
      const payload = invalid ? [] : url.startsWith('/api/attendance')
        ? (kind === 'attendance' ? { 'stu-1': 1 } : kind === 'boolean' ? { 'stu-1': true } : {})
        : { ok: true, entry: kind === 'log' ? { done: true, unknown: 'preserve' } : {} };
      return { ok: !httpFailure, status: httpFailure ? 503 : 200, json: async () => payload, text: async () => 'fixture HTTP failure' };
    },
    fetchMakeupCarryoverSnapshot: async () => ({ payload: deepClone(initial), revision: 'fixture' }),
    postMakeupCarryoverSnapshot: async (payload, revision) => {
      assert.equal(revision, 'fixture', 'history preflight must not discard the captured carryover revision');
      if (conflict) throw new Error('fixture 409');
      calls.carryover.push(deepClone(payload));
      const saved = payload.by_absence['2026-09-26']['stu-1|2'].scheduledMakeup;
      if (saved.status === 'scheduled') calls.ownership.push({ ownedExtra: saved.ownedExtra, ownedSlots: [...saved.ownedSlots] });
      return payload;
    },
    patchExtraAttendDates: async (_map, dates) => { calls.extra.push([...dates]); },
    postWeekendPatch: async patch => { if (Object.keys(patch).length) calls.weekend.push(deepClone(patch)); },
    saveScheduleOverridesFailClosed: async ({ saveExtra, saveWeekend, weekendPatch }) => {
      await saveExtra(); await saveWeekend(weekendPatch);
    },
    postJson: async (url, payload) => { assert.equal(url, '/api/arrive-time/patch'); calls.arrive.push(payload); },
    setMakeupSelection() {}, closeMakeupSlotPicker() {}, refreshMakeupPlanner: async () => {},
    toast() {}, formatMakeupDate: date => date,
  };
  const names = [
    'scheduledSlots', 'scheduledOwnedSlots', 'scheduledSlotsToRelease', 'loadRecordedMakeupDates',
    'applyScheduledAttendance', 'releaseScheduledAttendance', 'mergeWeekendPatches',
    'saveScheduledMakeupDemand', 'carryoverScheduledMakeup', 'scheduleSelectedMakeup', 'refreshCalendarAfterMutation',
  ];
  vm.runInNewContext(`let EXTRA = {'${oldDate}':['stu-1','other'], '${newDate}':['stu-1']};
    let WEEKEND = {'${oldDate}':{'stu-1':[1,2],other:[1]}, '${newDate}':{'stu-1':[1]}};
    let CARRYOVER = {}; let makeupSelection = ${JSON.stringify(item)};
    ${sharedApiSource}
    ${names.map(calendarFunction).join('\n')}
    globalThis.cancel = () => carryoverScheduledMakeup(${JSON.stringify(item)});
    globalThis.reschedule = () => scheduleSelectedMakeup('${newDate}', 2);
    globalThis.snapshot = () => JSON.stringify({EXTRA,WEEKEND});
    globalThis.releaseSlots = scheduledSlotsToRelease;
    globalThis.loadHistory = loadRecordedMakeupDates;`, driver);
  return { driver, calls, oldDate, newDate };
}

for (const kind of ['log', 'attendance', 'boolean']) {
  const { driver, calls, oldDate } = historyDriver({ recorded: { '2026-09-19': kind } });
  const before = driver.snapshot();
  await driver.cancel();
  assert.equal(driver.snapshot(), before, `${kind}: cancellation must preserve recorded attendance/slots`);
  assert.equal(calls.extra.length + calls.weekend.length + calls.arrive.length, 0);
  const saved = calls.carryover[0].by_absence['2026-09-26']['stu-1|2'];
  assert.equal(saved.scheduledMakeup.status, 'cancelled');
  assert.equal(saved.scheduledMakeup.ownedExtra, false);
  assert.deepEqual(saved.scheduledMakeup.ownedSlots, []);
  assert.equal(saved.scheduledMakeup.makeupDate, oldDate);
}
for (const options of [{ invalid: true }, { failure: true }, { httpFailure: true }, { conflict: true }]) {
  const { driver, calls } = historyDriver(options);
  const before = driver.snapshot();
  await assert.rejects(driver.cancel());
  await assert.rejects(driver.reschedule());
  assert.equal(driver.snapshot(), before);
  assert.equal(calls.carryover.length + calls.extra.length + calls.weekend.length + calls.arrive.length + calls.ownership.length, 0);
}
{
  const { driver, calls, oldDate } = historyDriver();
  await driver.cancel();
  assert.deepEqual(calls.extra, [[oldDate]], 'unrecorded owned reservations still release normally');
  assert.deepEqual(calls.weekend[0], { [oldDate]: { 'stu-1': [1] } });
  assert.deepEqual(Array.from(driver.releaseSlots({ createdBy: 'makeup-planner', makeupTimes: [2], ownedExtra: false })), [], 'normalized empty ownership must not become inferred ownership');
}
{
  const { driver, calls, oldDate, newDate } = historyDriver({ recorded: { '2026-09-19': 'log' } });
  await driver.reschedule();
  assert.deepEqual(calls.extra, [[newDate]]);
  assert.ok(calls.weekend.every(patch => !Object.hasOwn(patch, oldDate)));
  assert.equal(calls.arrive.length, 1);
  assert.deepEqual(JSON.parse(driver.snapshot()).WEEKEND[oldDate]['stu-1'], [1, 2]);
}
{
  const { driver, calls, oldDate, newDate } = historyDriver({ recorded: { '2026-10-03': 'attendance' } });
  await driver.reschedule();
  assert.deepEqual(calls.extra, [[oldDate]]);
  assert.equal(calls.arrive.length, 0, 'actual arrival time must not be replaced with a planned time');
  assert.deepEqual(calls.ownership, [{ ownedExtra: false, ownedSlots: [] }]);
  assert.deepEqual(JSON.parse(driver.snapshot()).WEEKEND[newDate]['stu-1'], [1]);
}
{
  const { driver, calls } = historyDriver({ recorded: { '2026-09-19': 'log', '2026-10-03': 'log' } });
  const before = driver.snapshot();
  await driver.reschedule();
  assert.equal(driver.snapshot(), before);
  assert.equal(calls.extra.length + calls.weekend.length + calls.arrive.length, 0);
  const readsBefore = calls.reads.length;
  await driver.loadHistory('stu-1', ['2026-09-19', '2026-09-19']);
  assert.equal(calls.reads.length - readsBefore, 2, 'same-date checks must be deduplicated');
}
console.log('makeup schedule frontend helpers ok (self-study, real actions, recorded-history preservation and read-failure no-write)');
