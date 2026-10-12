import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { canonText, isPastCategory, normalizeSubject, normalizeDifficulty, normalizeRound, normalizeTerm } from '../static/js/tests/catalogState.js';

const source = fs.readFileSync('static/js/tests.js', 'utf8');
const start = source.indexOf('function createCsvTestIndex(');
const end = source.indexOf('\nfunction reportCsvParseWarning', start);
assert.ok(start >= 0 && end > start);
const createIndex = vm.runInNewContext(source.slice(start, end) + '\ncreateCsvTestIndex;', {
  canonText, isPastCategory, normalizeSubject, normalizeDifficulty, normalizeRound, normalizeTerm,
});
const row = (id, name, fields = {}) => ({ id, name, curriculum: '공수1', difficulty: 'Lv.3', round: '1', ...fields });
const patch = (name, id = '', fields = {}) => ({ name, id, curriculum: '공수1', difficulty: 'Lv.3', round: '1', ...fields });
const tests = [row('dup', '기존'), row('dup', '기존'), row('third', '다른')];
const index = createIndex({ tests }, 'UNIT');
assert.equal(index.find(patch('없음', 'dup')).test, tests[0]);
assert.equal(index.find(patch('기존')).test, tests[0]);
assert.equal(index.find(patch('다른', '없는ID')).test, tests[2]);
assert.equal(index.find(patch('없음')), null);
const first = index.find(patch('기존', 'dup'));
Object.assign(first.test, { id: 'changed', name: '다른' });
index.refresh(first);
assert.equal(index.find(patch('기존', 'dup')).test, tests[1]);
assert.equal(index.find(patch('다른')).test, tests[0]);
assert.equal(index.find(patch('기존')).test, tests[1]);
const added = row('append', '신규', { unknown: { keep: true } });
tests.push(added); index.add(added);
assert.equal(index.find(patch('신규')).test, added);
assert.equal(index.find(patch('없음', 'append')).test, added);
assert.equal(tests.length, 4); assert.deepEqual(added.unknown, { keep: true });
const spaced = row(' padded ', '  공백  ', { subject: '공수1', curriculum: '', level: 'Lv.3', difficulty: '', session: '2', round: '' });
const aliases = createIndex({ tests: [spaced] }, 'UNIT');
assert.equal(aliases.find(patch('공백', 'padded', { round: '2' })).test, spaced);
for (const key of ['SCHOOL_PAST', 'REVIEW', 'UNIT']) {
  const categoryTests = [
    row('a', '공통', { term: '중간고사', difficulty: key === 'UNIT' ? 'Lv.3' : '상' }),
    row('b', '공통', { term: '기말고사', difficulty: key === 'UNIT' ? 'Lv.3' : '상' }),
  ];
  const categoryIndex = createIndex({ tests: categoryTests }, key);
  const match = categoryIndex.find(patch('공통', '', { difficulty: key === 'UNIT' ? 'Lv.3' : '상', term: '기말고사' }));
  assert.equal(match.test, key === 'SCHOOL_PAST' ? categoryTests[1] : categoryTests[0]);
}
const colliding = [row('left', '이름|공수1'), row('right', '이름')];
const collisionIndex = createIndex({ tests: colliding }, 'UNIT');
assert.equal(collisionIndex.find(patch('이름|공수1')).test, colliding[0]);
assert.equal(collisionIndex.find(patch('이름')).test, colliding[1]);
console.log(JSON.stringify({ ok: true, literalIndexAssertions: 17, sourceBoundaryChecks: 1, realFetch: 0, persistentWrites: 0 }));
