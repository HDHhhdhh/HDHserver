import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('static/js/school-cal.js', 'utf8').replaceAll('\r\n', '\n');
const start = source.indexOf('  function renderBody() {');
const end = source.indexOf('\n  function render() {', start);
assert.ok(start >= 0 && end > start);
const schools = [
  { id: 'A', name: '첫학교', grades: [{ id: 'a1', subject: '수학' }, { id: 'a2', subject: '영어' }, { id: 'a3', subject: '수학' }] },
  { id: 'B', name: '다른학교', grades: [{ id: 'b1', subject: '물리' }, { id: 'b2', subject: '수학' }] },
];
function render(query, expanded = ['A']) {
  const before = JSON.stringify(schools);
  const run = new Function('schoolsData', 'searchQuery', 'expandedSchoolIds', `
    const tbody = {}, searchStatusEl = {};
    let predicates = 0;
    const ensureAtLeastOneSchool = () => {};
    const schoolMatchesQuery = school => !searchQuery || school.name.includes(searchQuery);
    const gradeMatchesQuery = (_school, grade) => { predicates++; return !searchQuery || grade.subject.includes(searchQuery); };
    const buildSchoolRow = (school, _index, options) => 'S:' + school.id + ':' + options.matched + ';';
    const buildGradeRow = (_school, grade, options) => 'G:' + grade.id + ':' + options.matched + ';';
    ${source.slice(start, end)}
    renderBody();
    return { html: tbody.innerHTML, status: searchStatusEl.textContent, predicates };
  `);
  const result = run(schools, query, new Set(expanded));
  assert.equal(JSON.stringify(schools), before, 'search rendering must not mutate caller data');
  return result;
}
assert.deepEqual(render('수학'), {
  html: 'S:A:false;G:a1:true;G:a3:true;S:B:false;G:b2:true;', status: '2개 학교 / 3행', predicates: 5,
});
assert.deepEqual(render('첫학교'), {
  html: 'S:A:true;G:a1:false;G:a2:false;G:a3:false;', status: '1개 학교 / 3행', predicates: 5,
});
assert.deepEqual(render(''), {
  html: 'S:A:false;G:a1:false;G:a2:false;G:a3:false;S:B:false;', status: '', predicates: 0,
});
assert.deepEqual(render('no-match'), { html: '', status: '0개 학교 / 0행', predicates: 5 });
schools[0].grades[0].subject = 'Changedneedle';
assert.deepEqual(render('수학'), {
  html: 'S:A:false;G:a3:true;S:B:false;G:b2:true;', status: '2개 학교 / 2행', predicates: 5,
});
assert.deepEqual(render('Changedneedle'), {
  html: 'S:A:false;G:a1:true;', status: '1개 학교 / 1행', predicates: 5,
});
console.log('school calendar actual render: 6 literal cases, per-render predicates, highlight/expanded/no-match/fresh-edit and caller invariance passed');
