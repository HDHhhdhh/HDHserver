import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/js/admin/features/today.state.js', 'utf8');
const begin = source.indexOf('let studentLookup = null;');
const end = source.indexOf('export function dayValues(', begin);
assert.ok(begin >= 0 && end > begin);
const first = {id: '7', name: '첫 학생'}, duplicate = {id: 7, name: '중복 학생'};
const state = {students: [first, duplicate, {id: '0007', name: '별도 SID'}]};
const context = vm.createContext({state});
vm.runInContext(source.slice(begin, end).replace(/\bexport\s+/g, ''), context);
assert.equal(context.getStudent(7), first);
assert.equal(context.getStudent('0007').name, '별도 SID');
context.withStudentLookup(() => {
  assert.equal(context.getStudent(7), first, 'first matching duplicate SID wins');
  assert.equal(context.getStudent('missing'), undefined);
  first.name = '이름 변경';
  assert.equal(context.getStudent('7').name, '이름 변경', 'objects remain current');
  context.withStudentLookup(() => assert.equal(context.getStudent(7), first));
  assert.throws(() => context.withStudentLookup(() => { throw new Error('nested failure'); }));
  assert.equal(context.getStudent(7), first);
});
assert.throws(() => context.withStudentLookup(() => { throw new Error('outer failure'); }));
state.students[0] = {id: '7', name: '동일 배열에서 교체'};
assert.equal(context.getStudent(7).name, '동일 배열에서 교체', 'scope is gone after error');
context.withStudentLookup(() => assert.equal(context.getStudent(7).name, '동일 배열에서 교체'));
state.students = [{id: 7, name: '다음 조회'}];
context.withStudentLookup(() => assert.equal(context.getStudent('7').name, '다음 조회'));

const arrivalBegin = source.indexOf("const ARRIVE_URL = '/api/arrive-time';");
const arrivalEnd = source.indexOf('export function plannedTimeFor(', arrivalBegin);
assert.ok(arrivalBegin >= 0 && arrivalEnd > arrivalBegin);
const day = '2026-10-03', otherDay = '2026-10-04', writes = [], storage = new Map([
  [`arrive_time:${day}`, JSON.stringify({A: '13:00', B: '18:00', unknown: {keep: [1, 2]}})],
  [`arrive_time:${otherDay}`, JSON.stringify({A: '14:00'})],
]);
const arrival = vm.createContext({
  safeJSONParse: (raw, fallback) => raw ? JSON.parse(raw) : fallback,
  localStorage: {getItem: key => storage.get(key), setItem: (key, value) => {writes.push(key); storage.set(key, value);}},
});
vm.runInContext(source.slice(arrivalBegin, arrivalEnd).replace(/\bexport\s+/g, ''), arrival);
arrival.setArriveOverrides(day, {A: ' 14:10 ', B: '', C: '18:30'});
assert.deepEqual(JSON.parse(storage.get(`arrive_time:${day}`)), {A:'14:10',C:'18:30',unknown:{keep:[1,2]}});
assert.deepEqual(writes, [`arrive_time:${day}`]);
assert.equal(arrival.getArriveOverride(day, 'B'), '');
assert.equal(arrival.getArriveOverride(otherDay, 'A'), '14:00');
arrival.setArriveOverride(day, 'A', '');
assert.equal(arrival.getArriveOverride(day, 'A'), '');
assert.deepEqual(JSON.parse(storage.get(`arrive_time:${day}`)), {C:'18:30',unknown:{keep:[1,2]}});
console.log('PASS today lookup/bulk: duplicate IDs, nested/throw scope, fresh roster, one backup write, clear/unknown/date isolation');
