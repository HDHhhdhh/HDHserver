import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { isSelfStudyScheduledForDate } from '../static/js/shared/selfStudy.js';
import { scheduledMakeupSlotsByDate } from '../static/js/admin/features/makeupPending.js';

const date = '2026-10-25';
const student = { id: 'qa-study', day1: '일1', selfStudyDays: { day1: true } };
const plan = {
  originalAbsenceId: 'absence|2026-10-18|qa-study|1',
  studentId: student.id, makeupDate: date, makeupTimes: [1], status: 'scheduled',
};
const carryover = {
  by_absence: { '2026-10-18': { 'qa-study|1': { scheduledMakeup: plan } } }, manual: {},
};
const original = JSON.stringify({ student, carryover });
const state = { students: [student], logs: {}, scheduledMakeupSlotsByDate: {} };
const source = fs.readFileSync(new URL('../static/js/admin/features/today.state.js', import.meta.url), 'utf8')
  .replace(/^import\s[\s\S]*?;\s*$/gm, '').replace(/\bexport\s+/g, '');
const context = vm.createContext({ state, isSelfStudyScheduledForDate, getAdminDate: () => date });
vm.runInContext(source, context);
const update = value => {
  state.scheduledMakeupSlotsByDate = scheduledMakeupSlotsByDate({ students: [student], carryover: value });
};

assert.equal(context.isSelfStudy(date, student.id), true);
update(carryover);
assert.deepEqual(state.scheduledMakeupSlotsByDate, { [date]: { [student.id]: [1] } });
assert.equal(context.isSelfStudy(date, student.id), false, 'overlapping makeup must show a class');
assert.equal(context.isSelfStudy('2026-11-01', student.id), true, 'other dates retain the recurring schedule');
assert.equal(isSelfStudyScheduledForDate(student, date, [2]), true, 'another slot cannot clear self-study');
assert.equal(isSelfStudyScheduledForDate({ id: 'legacy', day1: '일1', day1SelfStudy: true }, date, [1]), false);

state.logs = { [date]: { [student.id]: { selfStudy: true } } };
assert.equal(context.isSelfStudy(date, student.id), true, 'explicit daily overrides retain priority');
state.logs[date][student.id].selfStudy = false;
assert.equal(context.isSelfStudy(date, student.id), false);
state.logs = {};

for (const status of ['cancelled', 'completed']) {
  const changed = structuredClone(carryover);
  changed.by_absence['2026-10-18']['qa-study|1'].scheduledMakeup.status = status;
  update(changed);
  assert.equal(context.isSelfStudy(date, student.id), true, `${status} restores the recurring fallback`);
}
for (const change of [{ makeupDate: '2026-11-01' }, { makeupTimes: [2] }, { studentId: 'other' }]) {
  const changed = structuredClone(carryover);
  Object.assign(changed.by_absence['2026-10-18']['qa-study|1'].scheduledMakeup, change);
  update(changed);
  assert.equal(context.isSelfStudy(date, student.id), true, 'moving a reservation restores the original slot');
}
update({ by_absence: { '2026-10-18': { 'qa-study|1': { scheduledMakeup: null, scheduled_makeup: plan } } } });
assert.deepEqual(state.scheduledMakeupSlotsByDate, {}, 'explicit deletion must not revive a legacy alias');
update({ by_absence: { '2026-10-18': { 'qa-study|1': {
  state: 'carried', note: '예정 정규수업 결석: 2026-10-18 1타임 / 직보 추가등원 예약으로 1회 차감: 2026-10-25 1타임 교재실 (qa-study). 실제 이행 완료 표시는 아님. [approved-fixture-20261025]',
} } } });
assert.deepEqual(state.scheduledMakeupSlotsByDate, {}, 'legacy display notes cannot change the server-authoritative class mode');
update({ manual: { '2026-10-18': { row: { sid: student.id, scheduledMakeup: plan } } } });
assert.equal(context.isSelfStudy(date, student.id), false, 'manual makeup reservations also override the schedule');
assert.equal(JSON.stringify({ student, carryover }), original, 'derived state cannot rewrite student or makeup records');
console.log('makeup self-study checks passed: matching date/slot, explicit overrides, cancel/move/complete, and input invariance');
