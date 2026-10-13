import assert from 'node:assert/strict';
import fs from 'node:fs';
import { matchesSearchKey } from '../static/js/shared/search.js';
import { todayStudentSearchKey } from '../static/js/admin/features/todaySearch.js';

const students = [
  { id: 's1', name: '노윤우', school: '정발고', curriculum: '미적분1', subCurriculum: 'APEX' },
  { id: 's2', name: '이주빈', school: '백석고', curriculum: '대수', subCurriculum: 'A:Ble' },
];
const found = (query, field = 'all') => students
  .filter(student => matchesSearchKey(todayStudentSearchKey(student, field), query))
  .map(student => student.name);

for (const query of ['ㅈㅂㄱ', 'wqr']) {
  assert.deepEqual(found(query), ['노윤우'], `${query} must find 정발고 in all-fields mode`);
  assert.deepEqual(found(query, 'school'), ['노윤우'], `${query} must find 정발고 in school mode`);
  assert.deepEqual(found(query, 'name'), [], `${query} must not match a different field in name mode`);
}
for (const query of ['ㅁㅈㅂ', 'alwjrqns']) {
  assert.deepEqual(found(query), ['노윤우'], `${query} must find 미적분1 in all-fields mode`);
  assert.deepEqual(found(query, 'curriculum'), ['노윤우'], `${query} must find 미적분1 in subject mode`);
}
assert.deepEqual(found('ㅇㅈㅂ'), ['이주빈'], 'name-school initials must never join across field boundaries');
assert.deepEqual(found('ㅇㅈㅂ', 'name'), ['이주빈'], 'name initials still work in name mode');
assert.deepEqual(found('ㅇㅈㅂ', 'school'), [], 'school-only mode must not match a student name');
assert.deepEqual(found('ㄴㅇㅇ ㅈㅂㄱ'), ['노윤우'], 'separate name and school terms retain AND matching');
assert.deepEqual(found('정발고 미적분1'), ['노윤우'], 'separate school and subject terms retain AND matching');
assert.deepEqual(found('ㅈㅂㄱ 대수'), [], 'different students cannot satisfy separate search terms');

const todaySource = fs.readFileSync(new URL('../static/js/admin/features/today.js', import.meta.url), 'utf8');
assert.match(todaySource, /todayStudentSearchKey\(stu, mode\)/, 'today roster must use the field-scoped search key');
assert.match(todaySource, /matchesSearchKey\(key, queryText\)/, 'today roster must use shared query variants');
console.log('today student field-scoped initial/keyboard search passed');
