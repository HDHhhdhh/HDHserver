import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const filename = path.join(root, 'static/js/admin/features/makeupPending.js');
const source = fs.readFileSync(filename, 'utf8').replace(/\r\n/g, '\n');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
let checks = 0;
function same(actual, expected, label) {
  assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected, label);
  checks += 1;
}
// The additive daily-mode projection has its own behavior checks; freeze the existing helpers.
const preExtractionSource = source.replace(/^export function scheduledMakeupSlotsByDate\([\s\S]*?^\}\n\n/m, '')
  .replace('    const seenDetails = new Set();',
  "    const duplicateCounts = new Map();\n    entries.forEach(item => {\n      const course = courseForExport(item.course);\n      const key = `${item.absenceDate || ''}|${course}`;\n      duplicateCounts.set(key, (duplicateCounts.get(key) || 0) + 1);\n    });\n\n" + '    const seenDetails = new Set();');
same(hash(preExtractionSource), '984e1624c21158a9ac2f317aaf2210419f8c4253de7fac51e1a5e07734c1c4ba',
  'existing projection baseline permits only the retired counter and additive daily-mode helper');
const sandbox = { console };
vm.runInNewContext(source.replace(/\bexport function /g, 'function ') +
  '\nglobalThis.rules = { buildPendingMakeups, countPendingMakeupsBySid, makeupOriginalAbsenceId,' +
  ' buildScheduledMakeupRows, buildActiveScheduledMakeupRows, scheduledMakeupStudentIdsForDate,' +
  ' buildMakeupExportRows, makeupExportRowsToCsv, parseSlotNumbers };', sandbox, { filename });
const r = sandbox.rules;
const input = {
  students: [
    { id: 's1', personId: 'person-shared', name: '가람', school: '운정고', grade: '2', curriculum: '교재', day1: '목1', day2: '목2', unknown: { keep: true } },
    { id: 's2', personId: 'person-shared', name: '가람', school: '운정고', grade: '2', curriculum: '교재실', day1: '목1' },
  ],
  absentByDate: { '2026-10-01': ['s1', 's2'], '2026-10-08': ['s1', 's2'], '2026-10-15': ['s1'] },
  absentSlotsByDate: { '2026-10-01': { s1: [2, 1], s2: [3] } },
  carryover: { by_absence: {
    '2026-10-01': { s1: { state: 'self-study', unknown: 7 }, 's2|3': { state: 'open' } },
    '2026-10-08': { 's1|1': { state: 'carried' }, 's1|2': { state: 'open' }, 's2|1': { state: 'carried' } },
  }, manual: {} },
  manualMakeups: { '2026-10-01': {
    m: { sid: 's1', dateOnly: true, course: '교재실', unknown: 'retain-input' },
    c: { sid: 's2', slots: [1], state: 'carried' },
  } },
  extra: { '2026-10-04': ['s1'] },
  weekendSlots: { '2026-10-04': { s1: [1] } },
};
const fingerprint = hash(JSON.stringify(input));
const project = row => ({
  source: row.source, sid: row.sid, absenceDate: row.absenceDate,
  slot: row.slot, dateOnly: row.dateOnly, course: row.course,
  originalAbsenceId: r.makeupOriginalAbsenceId(row),
});
const expected = [
  { source: 'manual', sid: 's1', absenceDate: '2026-10-01', slot: '', dateOnly: true, course: '교재실', originalAbsenceId: 'manual|2026-10-01|m' },
  { source: 'absence', sid: 's2', absenceDate: '2026-10-01', slot: 3, dateOnly: false, course: '교재실', originalAbsenceId: 'absence|2026-10-01|s2|3' },
  { source: 'absence', sid: 's1', absenceDate: '2026-10-08', slot: 2, dateOnly: false, course: '교재', originalAbsenceId: 'absence|2026-10-08|s1|2' },
  { source: 'absence', sid: 's1', absenceDate: '2026-10-15', slot: 2, dateOnly: false, course: '교재', originalAbsenceId: 'absence|2026-10-15|s1|2' },
];
same(r.buildPendingMakeups(input).map(project), expected, 'literal pending order/slots/self-study/manual/open/supply precedence');
same(r.countPendingMakeupsBySid(input), { s1: 3, s2: 1 }, 'shared person does not collapse SID pending counts');
same(r.buildPendingMakeups({ ...input, minAbsenceDate: '2026-10-08' }).map(project), expected.slice(2),
  'minimum date filters only pending demand');
same(r.countPendingMakeupsBySid({ ...input, minAbsenceDate: '2026-10-08' }), { s1: 3, s2: 1 },
  'count ignores activation threshold');
same(hash(JSON.stringify(input)), fingerprint, 'input hash including unknown fields unchanged');
same(r.parseSlotNumbers(['토3', '2,1', '3', 7]), [1, 2, 3], 'browser label parser retains third slot');
const scheduleInput = {
  students: input.students,
  carryover: { by_absence: {
    '2026-10-01': {
      's1|2': { state: 'carried', scheduledMakeup: {
        originalAbsenceId: 'absence|2026-10-01|s1|2', studentId: 's1',
        makeupDate: '2026-10-04', makeupTimes: [3, 1], ownedExtra: false, ownedSlots: [],
      } },
      's2|1': { state: 'carried', scheduledMakeup: {
        originalAbsenceId: 'absence|2026-10-01|s2|1', studentId: 's2',
        makeupDate: '2026-10-04', status: 'cancelled',
      } },
    },
  }, manual: { '2026-10-02': {
    m: { sid: 's2', dateOnly: true, course: '교재', scheduledMakeup: {
      originalAbsenceId: 'manual|2026-10-02|m', studentId: 's2',
      makeupDate: '2026-10-05', makeupTimes: [2], ownedExtra: true, ownedSlots: [2],
    } },
  } } },
};
const scheduleBefore = hash(JSON.stringify(scheduleInput));
const scheduleProjection = row => ({
  sid: row.sid, source: row.source, originalAbsenceId: row.originalAbsenceId,
  absenceDate: row.absenceDate, dateOnly: row.dateOnly, course: row.course,
  makeupDate: row.scheduledMakeup.makeupDate, times: row.scheduledMakeup.makeupTimes,
  ownedExtra: row.scheduledMakeup.ownedExtra, ownedSlots: row.scheduledMakeup.ownedSlots,
});
same(r.buildScheduledMakeupRows(scheduleInput).map(scheduleProjection), [
  { sid: 's1', source: 'absence', originalAbsenceId: 'absence|2026-10-01|s1|2', absenceDate: '2026-10-01', dateOnly: false,
    course: '교재', makeupDate: '2026-10-04', times: [1, 3], ownedExtra: false, ownedSlots: [] },
  { sid: 's2', source: 'manual', originalAbsenceId: 'manual|2026-10-02|m', absenceDate: '2026-10-02', dateOnly: true,
    course: '교재', makeupDate: '2026-10-05', times: [2], ownedExtra: true, ownedSlots: [2] },
], 'literal active reservation/manual/provenance/ownership projection');
same(r.buildActiveScheduledMakeupRows({ ...scheduleInput, operatingDate: '2026-10-05' }).map(row => row.sid), ['s2'],
  'elapsed reservation excluded at operating date');
same(r.scheduledMakeupStudentIdsForDate({ ...scheduleInput, date: '2026-10-04' }), ['s1'], 'cancelled reservation absent from date SIDs');
same(hash(JSON.stringify(scheduleInput)), scheduleBefore, 'reservation projection input hash unchanged');
const note = { by_absence: { '2026-09-25': { 's1|2': {
  state: 'carried',
  note: '예정 정규수업 결석: 2026-09-25 2타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 교재실 (s2). 실제 이행 완료 표시는 아님. [approved-fixture-20260923]',
} } }, manual: {} };
const noteRows = r.buildScheduledMakeupRows({ students: input.students, carryover: note });
same(noteRows.map(row => ({
  sid: row.sid, originalAbsenceId: row.originalAbsenceId, ownedExtra: row.scheduledMakeup.ownedExtra,
  ownedSlots: row.scheduledMakeup.ownedSlots, creditedStudentId: row.scheduledMakeup.creditedStudentId,
})), [{ sid: 's1', originalAbsenceId: 'absence|2026-09-25|s1|2', ownedExtra: false, ownedSlots: [], creditedStudentId: 's2' }],
  'approved peer-SID credit retains original absence and does not own peer attendance');
note.by_absence['2026-09-25']['s1|2'].scheduledMakeup = null;
same(r.buildScheduledMakeupRows({ students: input.students, carryover: note }), [], 'explicit tombstone suppresses note reservation');
const exports = r.buildMakeupExportRows([
  { sid: 's1', student: input.students[0], name: '가람', absenceDate: '2026-10-01', course: '교재', slot: 1 },
  { sid: 's2', student: input.students[1], name: '가람', absenceDate: '2026-10-01', course: '교재실', dateOnly: true },
]);
const text = '📢 보강 잡아주세요!\n\n10/1(목) 교재 1타임, 10/1(목) 교재실 결석분에 대한 보강 날짜 알려주세요~';
same(exports, [{ time: '', chatName: 'A 운정2 가람', text }], 'literal export grouping keeps 교재 and 교재실 distinct');
same(r.makeupExportRowsToCsv(exports), '\uFEFF타임,대화명,텍스트\r\n,A 운정2 가람,"' + text + '"\r\n', 'literal BOM/CSV/newline/escaping output');
if (process.argv[2] === '--roundtrip') {
  const carryover = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
  const students = ['s', 'alias', 'legacy', 's-peer'].map(id => ({ id, name: id, curriculum: '교재실' }));
  const before = hash(JSON.stringify(carryover));
  same(carryover.by_absence['2026-09-25']['s|2'].scheduledMakeup, null, 'HTTP preserves explicit null');
  same(carryover.by_absence['2026-09-25']['alias|2'].scheduledMakeup, null, 'HTTP preserves alias null');
  same(carryover.manual['2026-10-02'].m.scheduledMakeup, null, 'HTTP preserves manual null');
  const rows = r.buildScheduledMakeupRows({ students, carryover });
  same(rows.map(row => ({ sid: row.sid, date: row.scheduledMakeup.makeupDate, times: row.scheduledMakeup.makeupTimes })),
    [{ sid: 'legacy', date: '2026-09-27', times: [2] }], 'HTTP roundtrip never resurrects deleted note reservation; missing key remains legacy-compatible');
  same(r.scheduledMakeupStudentIdsForDate({ students, carryover, date: '2026-09-27' }), ['legacy'], 'deleted reservations absent from date roster');
  same(hash(JSON.stringify(carryover)), before, 'HTTP projection input unchanged');
}
console.log('makeup projection oracle: ' + checks + ' assertions passed; actual source VM, no DOM/network/storage');
