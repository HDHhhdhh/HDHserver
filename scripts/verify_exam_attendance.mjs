import assert from 'node:assert/strict';
import { buildExamAttendance, createExamAttendanceLoader } from '../static/js/admin/features/examAttendance.js';

const student = { id: 's1', name: '동명이인', day1: '화1', day2: '금1', day3: '토1', selfStudyDays: { day3: true } };
const empty = () => ({ absentByDate: {}, absentSlotsByDate: {}, extra: {}, weekendSlots: {}, carryover: { by_absence: {}, manual: {} } });
const calculate = (snapshot = empty(), overrides = {}) => buildExamAttendance({
  students: [student], attendanceDays: ['화1', '금1'],
  referenceDate: new Date(2026, 8, 7), examDate: new Date(2026, 8, 14), snapshot, ...overrides,
});
const reserve = (snapshot, date, slots = [1], { sid = 's1', absenceDate = '2026-09-02', status = 'scheduled' } = {}) => {
  snapshot.carryover.by_absence[absenceDate] ??= {};
  snapshot.carryover.by_absence[absenceDate][sid + '|1'] = {
    state: 'carried', scheduledMakeup: {
      originalAbsenceId: ['absence', absenceDate, sid, '1'].join('|'),
      studentId: sid, makeupDate: date, makeupTimes: slots, status,
    },
  };
};
let checks = 0;
const same = (actual, expected, label) => { assert.deepEqual(actual, expected, label); checks += 1; };
same(calculate(), { total: 2, regular: 2, makeup: 0, pending: 0 }, 'Tue/Fri only; Saturday self-study excluded');
{
  const data = empty(); reserve(data, '2026-09-09');
  same(calculate(data), { total: 3, regular: 2, makeup: 1, pending: 0 }, 'reservation survives missing extra reflection');
  data.extra['2026-09-09'] = ['s1', 's1']; data.weekendSlots['2026-09-09'] = { s1: [1, 1] };
  same(calculate(data).total, 3, 'reservation/extra/duplicate slot counted once');
  reserve(data, '2026-09-09', [1], { absenceDate: '2026-09-03' });
  same(calculate(data).makeup, 1, 'two absence links cannot count one lesson twice');
}
{
  const data = empty(); reserve(data, '2026-09-11', [1]);
  same(calculate(data).total, 2, 'same regular date/slot not counted again');
  reserve(data, '2026-09-11', [2]);
  same(calculate(data).total, 3, 'additional slot on regular date included');
  reserve(data, '2026-09-09', [1, 2]);
  same(calculate(data).total, 4, 'two makeup slots included');
}
for (const date of ['2026-09-06', '2026-09-07', '2026-09-14', '2026-09-15']) {
  const data = empty(); reserve(data, date);
  same(calculate(data).makeup, 0, 'outside open interval: ' + date);
}
{
  const data = empty(); reserve(data, '2026-09-09', [1], { status: 'cancelled' });
  same(calculate(data).total, 2, 'cancelled reservation excluded');
  reserve(data, '2026-09-09'); reserve(data, '2026-09-15');
  same(calculate(data).total, 2, 'moved reservation uses new date only');
  reserve(data, '2026-09-09', [1], { sid: 's2' });
  same(calculate(data).total, 2, 'other SID excluded even if name matches');
}
{
  const data = empty(); data.absentByDate['2026-09-02'] = ['s1'];
  data.carryover.by_absence['2026-09-02'] = { 's1|1': { state: 'open' } };
  same(calculate(data).pending, 1, 'unreserved historical absence prompts scheduling');
  data.absentByDate['2026-09-11'] = ['s1'];
  data.carryover.by_absence['2026-09-11'] = { 's1|1': { state: 'open' } };
  same(calculate(data), { total: 1, regular: 1, makeup: 0, pending: 2 }, 'future known absence removed from regular count');
  reserve(data, '2026-09-15');
  same(calculate(data).pending, 1, 'already reserved after exam is not unreserved');
  data.absentByDate['2026-09-15'] = ['s1'];
  same(calculate(data).pending, 1, 'post-exam absence excluded from prompt');
  delete data.absentByDate['2026-09-11'];
  same(calculate(data).pending, 0, 'recovered absence leaves no prompt');
}
{
  const data = empty(); reserve(data, '2026-09-09', [1, 2]);
  data.absentSlotsByDate['2026-09-09'] = { s1: [2] };
  same(calculate(data).makeup, 1, 'slot absence excludes only its scheduled makeup slot');
  data.absentByDate['2026-09-09'] = ['s1'];
  same(calculate(data).makeup, 0, 'whole-date absence wins over reservation');
}
{
  const data = empty(); data.extra['2026-09-09'] = ['s1'];
  data.weekendSlots['2026-09-09'] = { s1: [1, 2] };
  same(calculate(data).total, 4, 'legacy extra attendance before exam included');
  const before = JSON.stringify(data); calculate(data);
  same(JSON.stringify(data), before, 'projection is mutation-free');
  same(calculate(data, { examDate: new Date(2026, 8, 7) }).total, 0, 'exam today has no remaining sessions');
  same(calculate(data, { examDate: null }), null, 'unknown exam not invented');
}

let clock = 0;
let calls = [];
let release;
const barrier = new Promise(resolve => { release = resolve; });
const loader = createExamAttendanceLoader(async url => { calls.push(url); await barrier; return {}; }, { now: () => clock });
const a = loader.load(); const b = loader.load();
same(a, b, 'concurrent readers share one request');
same(calls.length, 4, 'four independent reads start in parallel');
release(); await a;
await loader.load(); same(calls.length, 4, 'short cache prevents duplicate hover reads');
clock = 5001; await loader.load(); same(calls.length, 8, 'expired cache refreshes');
loader.invalidate(); await loader.load(); same(calls.length, 12, 'mutation event invalidates');
same([...new Set(calls)].sort(), ['/api/absent', '/api/extra-attend', '/api/makeup-carryover', '/api/weekend-slots'], 'canonical read endpoints only');

let fail = true; let retryCalls = 0;
const retryLoader = createExamAttendanceLoader(async () => { retryCalls += 1; if (fail) throw new Error('offline'); return {}; });
await assert.rejects(retryLoader.load(), /offline/);
same(retryLoader.peek(), null, 'failed read cannot appear as zero makeups');
fail = false; await retryLoader.load(); same(retryCalls, 8, 'failed promise evicted and retried');
const malformed = createExamAttendanceLoader(async () => []);
await assert.rejects(malformed.load(), /Invalid/); checks += 1;

let oldRelease; let requestRound = 0;
const oldBarrier = new Promise(resolve => { oldRelease = resolve; });
const raceLoader = createExamAttendanceLoader(async () => {
  const round = requestRound; if (round === 0) await oldBarrier;
  return { by_date: {}, round };
});
const oldRead = raceLoader.load(); raceLoader.invalidate(); requestRound = 1;
await raceLoader.load(); oldRelease(); await oldRead;
same(raceLoader.peek().extra.round, 1, 'invalidated late response cannot replace fresh snapshot');
console.log(JSON.stringify({ ok: true, suite: 'exam-attendance', checks }));
