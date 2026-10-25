import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/js/admin/features/makeupPending.js', 'utf8');
const sandbox = {};
vm.runInNewContext(source.replace(/export function /g, 'function ') +
  '\nglobalThis.r = { buildPendingMakeups, buildScheduledMakeupRows, buildActiveScheduledMakeupRows, formatMakeupPlannerLabel, makeupChangeCount };', sandbox);
const r = sandbox.r;
const plain = value => JSON.parse(JSON.stringify(value));
const students = [{ id: 's', name: '강민욱', school: '저동고등학교', grade: '고2', curriculum: '미적분1', subCurriculum: 'A:Ble', day1: '목1' }];
const key = 'absence|2026-10-01|s|1';
const schedule = { originalAbsenceId: key, studentId: 's', makeupDate: '2026-10-04', makeupTimes: [1], status: 'scheduled' };
const carryover = { by_absence: { '2026-10-01': { 's|1': { state: 'carried', scheduledMakeup: schedule } } }, manual: {} };
const input = { students, carryover, absentByDate: { '2026-10-01': ['s'], '2026-10-04': ['s'] }, absentSlotsByDate: { '2026-10-04': { s: [1] } } };
const before = JSON.stringify(input);
const pending = r.buildPendingMakeups(input);
assert.equal(pending.length, 1, 'one missed makeup is the original absence, not a new independent demand');
assert.equal(pending[0].absenceDate, '2026-10-01');
assert.equal(pending[0].rebooking, true);
assert.equal(pending[0].missedMakeupDate, '2026-10-04');
assert.equal(r.buildActiveScheduledMakeupRows({ ...input, operatingDate: '2026-10-04' }).length, 0);
assert.equal(r.formatMakeupPlannerLabel({ ...pending[0], absenceDate: '2026-10-16', scheduleHistory: [{ action: 'rescheduled' }] }),
  '강민욱(저동2) | 미적1 | 10/16(금) 결석 | 변경 1회');
assert.equal(JSON.stringify(input), before);
const secondSlot = structuredClone(carryover);
secondSlot.by_absence['2026-10-01']['s|1'].scheduledMakeup.makeupTimes = [2];
const wholeDay = { ...input, carryover: secondSlot, absentSlotsByDate: {} };
assert.equal(r.buildPendingMakeups(wholeDay).length, 1, 'whole-day absence on a non-regular day uses actual second-slot booking');
assert.equal(r.buildPendingMakeups(wholeDay)[0].absenceDate, '2026-10-01');
const noMiss = { ...input, absentByDate: { '2026-10-01': ['s'] }, absentSlotsByDate: { '2026-10-04': { s: [2] } } };
assert.equal(r.buildPendingMakeups(noMiss)[0].absenceDate, '2026-10-04', 'different slot remains independent');
assert.equal(r.buildActiveScheduledMakeupRows({ ...noMiss, operatingDate: '2026-10-04' }).length, 1);
const duplicate = structuredClone(carryover);
duplicate.by_absence['2026-10-02'] = { 's|1': { state: 'carried', scheduledMakeup: { ...schedule, originalAbsenceId: 'absence|2026-10-02|s|1' } } };
assert.equal(r.buildPendingMakeups({ ...input, carryover: duplicate })[0].absenceDate, '2026-10-04', 'ambiguous overlap is not guessed');
const ambiguousStatus = r.buildActiveScheduledMakeupRows({ ...input, carryover: duplicate, operatingDate: '2026-10-25' });
assert.equal(ambiguousStatus.length, 2, 'ambiguous missed reservations remain accessible even after their dates');
assert.ok(ambiguousStatus.every(row => row.needsAbsenceReview));
const manual = { by_absence: {}, manual: { '2026-10-01': { m: { sid: 's', dateOnly: true, state: 'carried', scheduledMakeup: { ...schedule, originalAbsenceId: 'manual|2026-10-01|m' } } } } };
assert.equal(r.buildPendingMakeups({ ...input, carryover: manual, absentByDate: { '2026-10-04': ['s'] } })[0].source, 'manual');
if (process.argv[2]) {
  const saved = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const next = { ...input, carryover: saved };
  assert.equal(r.buildPendingMakeups(next).length, 0, 'persisted missed link suppresses duplicate after rebooking');
  const row = r.buildScheduledMakeupRows(next)[0];
  assert.equal(row.absenceDate, '2026-10-01');
  assert.equal(r.makeupChangeCount(row), 1);
  assert.deepEqual(plain(row.scheduleHistory.map(e => e.makeupDate)), ['2026-10-04', '2026-10-11']);
  const missedAgain = { ...next, absentByDate: { ...input.absentByDate, '2026-10-11': ['s'] } };
  assert.equal(r.buildPendingMakeups(missedAgain).length, 1);
  assert.equal(r.buildPendingMakeups(missedAgain)[0].absenceDate, '2026-10-01');
  const movedEarly = structuredClone(saved);
  delete movedEarly.scheduleHistory[key][0].missedSlots;
  assert.equal(r.buildPendingMakeups({ ...input, carryover: movedEarly })[0].absenceDate, '2026-10-04', 'earlier move cannot swallow later independent absence');
}
const calendar = fs.readFileSync('static/js/admin/features/calendar.js', 'utf8');
const boundary = calendar.slice(calendar.indexOf('  async function fetchMakeupCarryoverSnapshot()'), calendar.indexOf('  async function patchExtraAttendDates('));
let version = '', writes = 0;
const io = { state: {}, normalizeCarryoverPayload: value => value, invalidateCalendarPreload() {}, ensureOk: async () => {},
  fetch: async () => ({ json: async () => carryover, headers: { get: name => name === 'X-Makeup-History-Version' ? version : 'fixture-revision' } }),
  sendJson: async () => { writes++; return { status: 200, json: async () => carryover }; },
};
vm.runInNewContext(boundary + '\nglobalThis.read = fetchMakeupCarryoverSnapshot; globalThis.save = postMakeupCarryoverSnapshot;', io);
const oldSnapshot = await io.read();
await assert.rejects(io.save(oldSnapshot.payload, oldSnapshot.revision, oldSnapshot.historyVersion), /서버 재시작/);
assert.equal(writes, 0, 'old backend must not silently discard new history');
version = '1';
const supported = await io.read();
await io.save(supported.payload, supported.revision, supported.historyVersion);
assert.equal(writes, 1);
console.log('makeup history browser projection, literal label, repeated absence and server capability checks: OK');
