import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Actual builder and student/date helpers, actual pure school-calendar module.
// No DOM, HTTP, app import, server, storage writes, or production runtime reads.
const root = path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), '..'));
const sourcePath = path.join(root, 'static/js/admin/features/calendar.js');
const sharedPath = path.join(root, 'static/js/shared/schoolCalendar.js');
const source = fs.readFileSync(sourcePath, 'utf8').replaceAll('\r\n', '\n');
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const shared = await import(pathToFileURL(sharedPath));
const { parseAdminDateLocal } = await import(pathToFileURL(path.join(root, 'static/js/admin/core/adminDate.js')));
const dateValidation = source.match(/^\s*const isSupportedCalendarDate = .+;$/m)?.[0];
assert.ok(dateValidation, 'calendar clicks must use the calendar date validator');
const copy = value => JSON.parse(JSON.stringify(value));
const section = (text, start, end) => {
  const a = text.indexOf(start), b = text.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, 'actual source section exists: ' + start);
  return text.slice(a, b);
};
const ymdStart = source.indexOf('  const ymd = ');
const ymdEnd = source.indexOf('\n', ymdStart);
assert.ok(ymdStart >= 0 && ymdEnd > ymdStart);
function makeBuilder(text = source) {
  const state = { students: [], schoolCal: null };
  const ctx = vm.createContext({ state, parseAdminDateLocal,
    flattenSchoolCalendarRows: shared.flattenSchoolCalendarRows,
    getActiveSchoolCalendarYear: shared.getActiveSchoolCalendarYear,
    normalizeExamSubject: shared.normalizeSchoolCalendarSubject,
  });
  vm.runInContext([
    source.slice(ymdStart, ymdEnd),
    section(text, '  function toSafeDate(', '  function startOfWeek('),
    section(text, '  function parseMonthDayTokens(', '\n  let countMap ='),
    section(text, '  function normalizeStudentIdentity(', '  function selectedMakeupStudentRecords('),
    'globalThis.build = buildSchoolExamEvents;',
  ].join('\n'), ctx, { filename: 'calendar.js actual school-exam builder' });
  return { state, build: payload => copy(ctx.build(payload)) };
}
const fixture = makeBuilder();
let cases = 0, assertions = 0;
const same = (actual, expected, label) => { assert.deepEqual(actual, expected, label); assertions++; };
const freeze = value => { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };
const documentFor = schools => ({ activeYear: '2026', activeSemester: '2', years: {
  '2025': { schools: { '퇴역고': { midtermMath: '10/1' } } },
  '2026': { activeSemester: '2', semesters: { '1': { schools: { '퇴역고': { midtermMath: '10/2' } } }, '2': { schools } } },
} });
const invoke = (payload, students, builder = fixture) => {
  const before = JSON.stringify({ payload, students });
  builder.state.students = freeze(students); builder.state.schoolCal = freeze(payload);
  const result = builder.build(payload);
  same(JSON.stringify({ payload, students }), before, 'input calendar and roster are unchanged');
  return result;
};
const project = events => events.map(event => ({ title: event.title, start: event.start, end: event.end, entries: event.extendedProps.examEntries }));

const basicPayload = documentFor({ '가온고': { grades: { '1학년::공통수학Ⅱ': {
  midtermMath: '10/6', midtermRange: '  함수 1~2단원  ', midtermNote: ' 계산기 금지 ',
  finalMath: '12.18', finalRange: ' 도형 3~4단원 ', finalNote: ' 증명 포함 ',
} } } });
const basicStudents = [
  { id: 'A1', name: '가학생', school: '가온고등학교', grade: '고1', curriculum: '공통수학2' },
  { id: 'A2', name: '다른학년', school: '가온고', grade: '고2', curriculum: '공수2' },
  { id: 'A3', name: '다른과목', school: '가온고', grade: '고1', curriculum: '대수' },
  { id: 'A4', name: '다른학교', school: '다른고', grade: '고1', curriculum: '공수2' },
];
const basicExpected = [
  { title: '가온1 공수2', start: '2026-10-06', end: '2026-10-07', entries: [{ title: '가온1 공수2', school: '가온고', grade: '1학년', subject: '공수2', sourceText: '10/6', range: '함수 1~2단원', note: '계산기 금지', studentNames: ['가학생'] }] },
  { title: '가온1 공수2', start: '2026-12-18', end: '2026-12-19', entries: [{ title: '가온1 공수2', school: '가온고', grade: '1학년', subject: '공수2', sourceText: '12.18', range: '도형 3~4단원', note: '증명 포함', studentNames: ['가학생'] }] },
];
{
  const events = invoke(basicPayload, basicStudents);
  same(project(events), basicExpected, 'literal midterm/final range and note, subject alias, grade/school filtering, exclusive end');
  same(events.map(e => e.extendedProps.tooltip), [
    '가온고 1학년 공수2 시험일\n범위: 함수 1~2단원\n비고: 계산기 금지\n일정: 10/6',
    '가온고 1학년 공수2 시험일\n범위: 도형 3~4단원\n비고: 증명 포함\n일정: 12.18',
  ], 'range and note reach visible tooltip');
  cases++;
}
{
  const events = invoke(documentFor({ '가온고': { grades: {
    '1학년::대수': { textbook: 'YBM <개정판>', midtermMath: '10/7' },
    '2학년::대수': { textbook: '천재', midtermMath: '10/7' },
  } } }), [
    { id: 'T1', name: '가학생', school: '가온고', grade: '고1', curriculum: '대수' },
    { id: 'T2', name: '나학생', school: '가온고', grade: '고2', curriculum: '대수' },
  ]);
  same(events[0].title, '가온1·2 대수', 'calendar date cell keeps the compact school-subject title');
  same(events[0].extendedProps.tooltip, '가온고 1학년, 2학년 대수 시험일\n일정: 10/7', 'calendar tooltip also stays unchanged');
  same(events[0].extendedProps.examEntries[0].textbook, 'YBM <개정판> / 천재', 'click detail receives both grade textbooks');
  assert.match(source, /entry\.textbook\s*\?[^\n]*escapeHtml\(entry\.textbook\)/, 'detail chip escapes textbook text'); assertions++;
  cases++;
}
{
  const events = invoke(documentFor({ '가온고': {
    common: { midtermMath: '10/9', midtermRange: '공통 옛 범위', midtermNote: '공통 비고' },
    grades: {
      '1학년::대수': { midtermMath: '10/7', midtermRange: '1단원', midtermNote: '공통 준비물' },
      '2학년::대수': { midtermMath: '10/7', midtermRange: '2단원', midtermNote: '공통 준비물' },
    },
  } }), [
    { id: 'M1', name: '가학생', school: '가온고', grade: '1학년', curriculum: '대수' },
    { id: 'M1', name: '중복 SID', school: '가온고', grade: '1학년', curriculum: '대수' },
    { id: 'M2', name: '나학생', school: '가온고', grade: '2학년', curriculum: '대수' },
    { id: 'M3', name: '타학년', school: '가온고', grade: '3학년', curriculum: '대수' },
    { id: 'M4', name: '타과목', school: '가온고', grade: '1학년', curriculum: '미적분2' },
  ]);
  same(project(events), [{ title: '가온1·2 대수', start: '2026-10-07', end: '2026-10-08', entries: [{ title: '가온1·2 대수', school: '가온고', grade: '1학년, 2학년', subject: '대수', sourceText: '10/7', range: '1단원 / 2단원', note: '공통 준비물', studentNames: ['가학생', '나학생'] }] }], 'same school/subject/date joins grades and ranges, deduplicates notes/source/SID, suppresses common duplicate');
  same(events[0].extendedProps.tooltip, '가온고 1학년, 2학년 대수 시험일\n범위: 학교별 상이 (2개)\n비고: 공통 준비물\n일정: 10/7', 'multiple ranges preserve existing display meaning');
  cases++;
}
{
  const events = invoke(documentFor({ '가온고': { grades: {
    '1학년::공수1': { midtermMath: '10/8', midtermRange: '공수 범위', midtermNote: '공수 비고' },
    '1학년::대수': { midtermMath: '10/8', midtermRange: '대수 범위', midtermNote: '대수 비고' },
    '2학년::대수': { midtermMath: '10/9', midtermRange: '2학년 범위', midtermNote: '' },
  } } }), [
    { id: 'S1', name: '공수학생', school: '가온고', grade: '고1', curriculum: '공수1' },
    { id: 'S2', name: '대수학생', school: '가온고', grade: '고1', curriculum: '대수' },
    { id: 'S3', name: '후일학생', school: '가온고', grade: '고2', curriculum: '대수' },
  ]);
  same(events.map(e => [e.title, e.start, e.end]), [
    ['가온1 공수1', '2026-10-08', '2026-10-09'], ['가온1 대수', '2026-10-08', '2026-10-09'], ['가온2 대수', '2026-10-09', '2026-10-10'],
  ], 'subject and date remain separate grouping dimensions');
  same(events[0].extendedProps.examEntries, [
    { title: '가온1 공수1', school: '가온고', grade: '1학년', subject: '공수1', sourceText: '10/8', range: '공수 범위', note: '공수 비고', studentNames: ['공수학생'] },
    { title: '가온1 대수', school: '가온고', grade: '1학년', subject: '대수', sourceText: '10/8', range: '대수 범위', note: '대수 비고', studentNames: ['대수학생'] },
  ], 'two same-day event entries preserve per-subject metadata');
  same(events[1].extendedProps.examEntries, events[0].extendedProps.examEntries, 'existing shared same-span popup entries remain');
  same(events[2].extendedProps.examEntries[0].note, '', 'blank note stays empty without earlier note leakage');
  cases++;
}
{
  const events = invoke(documentFor({ '가온고': { grades: { '1학년::대수': {
    midterm: '10/1 ~ 10/11', midtermMath: '10/8 ~ 10/10 / 10/8', midtermRange: ' 1~3단원 ', midtermNote: ' ',
    final: '12/1 ~ 12/5', finalMath: '', finalRange: '범위만 있고 시험일 없음', finalNote: '비고만 있음',
  } } } }), [{ id: 'D1', name: '기간학생', school: '가온고', grade: '고1', curriculum: '대수' }]);
  same(events.map(e => [e.start, e.end, e.extendedProps.examEntries[0].range, e.extendedProps.examEntries[0].note]), [
    ['2026-10-08', '2026-10-09', '1~3단원', ''], ['2026-10-10', '2026-10-11', '1~3단원', ''],
  ], 'math-date tokens remain individual dates, general exam period is ignored, duplicates removed, no date invented from range/note');
  cases++;
}
{
  const events = invoke(documentFor({
    '가온고': { grades: { '1학년::대수': { midtermMath: '2/30, 13/1', finalMath: '', midtermRange: '미표시', midtermNote: '미표시' }, '3학년::미적분2': { midtermMath: '10/8' } } },
    '재원없음고': { midtermMath: '10/9' }, '': { midtermMath: '10/10' },
  }), [{ id: 'I1', name: '관련학생', school: '가온고', grade: '고1', curriculum: '대수' }]);
  same(events, [], 'impossible dates, absent roster match, blank school and mismatched grade/subject stay excluded');
  same(invoke(documentFor({}), []), [], 'empty payload is still no events');
  cases++;
}
{
  const events = invoke(documentFor({ '국제고': { midtermMath: '10월 12일', midtermRange: '', midtermNote: '', finalMath: '12/31, 1/2' } }), [
    { id: 'L1', name: '가학생', school: '국제고', grade: '고1', curriculum: '대수' },
    { id: 'L2', name: '나학생', school: '국제고', grade: '고2', curriculum: '공수1' },
  ]);
  same(events.map(e => [e.title, e.start, e.end]), [
    ['국제고 수학', '2026-01-02', '2026-01-03'], ['국제고 수학', '2026-10-12', '2026-10-13'], ['국제고 수학', '2026-12-31', '2027-01-01'],
  ], 'ungraded legacy row keeps default math and existing active-year token semantics, year-end exclusive boundary');
  same(events[1].extendedProps.examEntries[0], { title: '국제고 수학', school: '국제고', grade: '', subject: '수학', sourceText: '10월 12일', range: '', note: '', studentNames: ['가학생', '나학생'] }, 'blank metadata/default math preserves legacy roster inclusion and special school title');
  cases++;
}
{
  const events = invoke(documentFor({
    '가온고': { grades: { '1학년::대수': { midtermMath: '10/13', midtermRange: '가 범위', midtermNote: '가 비고' } } },
    '나래고': { grades: { '1학년::대수': { midtermMath: '10/13', midtermRange: '나 범위', midtermNote: '나 비고' } } },
    '다온고': { grades: { '1학년::대수': { midtermMath: '10/13', midtermRange: '다 범위', midtermNote: '다 비고' } } },
  }), [
    { id: 'C1', name: '가학생', school: '가온고', grade: '고1', curriculum: '대수' },
    { id: 'C2', name: '나학생', school: '나래고', grade: '고1', curriculum: '대수' },
    { id: 'C3', name: '다학생', school: '다온고', grade: '고1', curriculum: '대수' },
  ]);
  same(events.map(e => [e.title, e.start, e.end, e.extendedProps.summaryCount]), [['가온1 대수 외 2개', '2026-10-13', '2026-10-14', 3]], 'three same-span groups still collapse to the existing summary');
  same(events[0].classNames, ['school-exam-event', 'school-exam-math', 'school-exam-summary'], 'summary class remains');
  same(events[0].extendedProps.examEntries.map(e => [e.school, e.range, e.note, e.studentNames]), [
    ['가온고', '가 범위', '가 비고', ['가학생']], ['나래고', '나 범위', '나 비고', ['나학생']], ['다온고', '다 범위', '다 비고', ['다학생']],
  ], 'collapsed summary retains each school range/note without cross-school mixing');
  cases++;
}
{
  const disconnected = source.replace(/^\s*(?:range: row\?\.(?:midtermRange|finalRange)|note: row\?\.(?:midtermNote|finalNote)),\n/gm, '');
  assert.notEqual(disconnected, source, 'four call-site wires present'); assertions++;
  const negative = invoke(basicPayload, basicStudents, makeBuilder(disconnected));
  assert.notDeepEqual(project(negative), basicExpected, 'old disconnected builder must fail literal range/note oracle'); assertions++;
  same(negative.map(e => [e.start, e.end]), [['2026-10-06', '2026-10-07'], ['2026-12-18', '2026-12-19']], 'negative control isolates metadata regression from dates');
  cases++;
}
const dateClickSource = section(source, '    dateClick: info => {', '    eventClick: (info) => {')
  .replace(/^    dateClick: /, '').replace(/,\s*$/, '');
function routeDateClick(text, fixture) {
  const calls = [];
  const handler = vm.runInNewContext(`${dateValidation}\n(${text})`, {
    parseAdminDateLocal, toast() {},
    manualAbsenceSelection: fixture.manual || null,
    makeupSelection: fixture.makeup || null,
    recentlyHandledManualAbsenceDate: () => false,
    toggleManualAbsenceDate: date => calls.push(['manual', date]),
    openMakeupSlotPicker: (date, day) => calls.push(['makeup', date, day]),
    openAttendModal: date => calls.push(['attend', date]),
  });
  const info = { dateStr: fixture.date ?? '2026-10-16', dayEl: 'fixture-day' };
  if (fixture.event !== false) {
    info.jsEvent = { target: { closest: selector => fixture.inside && selector === '.makeup-slot-popover' ? {} : null } };
  }
  handler(info);
  return calls;
}
for (const fixture of [
  { label: 'popover cancel must not open background attendance', inside: true, want: [] },
  { label: 'popover slot button must not recreate picker', inside: true, makeup: {}, want: [] },
  { label: 'calendar makeup date still opens picker', makeup: {}, want: [['makeup', '2026-10-16', 'fixture-day']] },
  { label: 'calendar manual absence date still toggles', manual: {}, want: [['manual', '2026-10-16']] },
  { label: 'normal calendar date still opens attendance', want: [['attend', '2026-10-16']] },
  { label: 'legacy caller without DOM event still works', event: false, want: [['attend', '2026-10-16']] },
  { label: 'impossible calendar date opens no action', date: '2026-02-29', want: [] },
  { label: 'unsupported calendar year opens no action', date: '9999-01-01', want: [] },
]) {
  same(routeDateClick(dateClickSource, fixture), fixture.want, fixture.label);
  cases++;
}
const unguardedDateClick = dateClickSource.replace("      if (info.jsEvent?.target?.closest?.('.makeup-slot-popover')) return;\n", '');
same(routeDateClick(unguardedDateClick, { inside: true }), [['attend', '2026-10-16']], 'negative control reproduces background popup after cancel');
cases++;
same(hash(fs.readFileSync(sourcePath, 'utf8').replaceAll('\r\n', '\n')), hash(source), 'source stayed fixed during this run');
console.log(JSON.stringify({ ok: true, suite: 'actual-calendar-school-exam-metadata', cases, assertions, sourcePath, sourceSha256: hash(source), evidence: 'actual builder/helpers + actual pure school-calendar module; literal fixtures; no HTTP, browser, app import, runtime data or writes' }, null, 2));
