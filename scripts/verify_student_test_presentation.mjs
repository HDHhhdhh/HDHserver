import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const moduleSource = fs.readFileSync('static/js/student/testPresentation.js', 'utf8');
const studentSource = fs.readFileSync('static/js/student.js', 'utf8');
const htmlSource = fs.readFileSync('static/student.html', 'utf8');
const context = { window: {} };
vm.runInNewContext(moduleSource, context, { filename: 'static/js/student/testPresentation.js' });

const api = context.window.StudentTestPresentation;
assert.ok(api && typeof api.viewModel === 'function', 'student test presentation contract was not published');

function sha256(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

const fixture = [
  {
    id: 'ilsan-upper',
    name: '일산 기출 2회',
    categoryKey: 'ILSAN_PAST',
    categoryLabel: '일산 기출',
    curriculum: '대수',
    difficulty: '상',
    round: '2',
    status: 'interrupted',
    answer_url: 'https://answers.example/ilsan-upper.pdf',
    untouched: { keep: true },
  },
  {
    id: 'ilsan-graph',
    label: '일산 그래프형',
    category: '일산',
    difficulty: '그래프 상',
    round: '3회차',
    status: 'done',
    solutionUrl: 'https://answers.example/ilsan-graph.pdf',
  },
  {
    testId: 'fallback-id',
    testName: '상태 폴백',
    category: 'UNIT',
    difficulty: 'Lv.3',
    status: 'unexpected-status',
  },
  {
    id: 'skip-id',
    name: '제외 시험',
    status: 'skip',
    answerRestricted: true,
    answerUrl: 'https://answers.example/skip.pdf',
  },
  { id: 'ilsan-upper', name: '중복은 제거' },
  null,
  {},
];
const fixtureHash = sha256(fixture);
const normalized = plain(api.normalizeAssignedTests(fixture));

assert.equal(normalized.length, 4, 'invalid and duplicate test rows must be removed');
assert.deepEqual(normalized.map(item => item.id), ['ilsan-upper', 'ilsan-graph', 'fallback-id', 'skip-id']);
assert.equal(normalized[0].difficulty, '중상');
assert.equal(normalized[0].statusLabel, '배부');
assert.equal(normalized[0].untouched.keep, true, 'unknown fields must survive normalization');
assert.equal(normalized[1].difficulty, '그래프 포함');
assert.equal(normalized[1].round, '3회차');
assert.equal(normalized[2].status, 'assigned');
assert.equal(normalized[2].statusLabel, '배정');
assert.equal(api.pendingCount(normalized), 2, 'done and skip must be excluded from the pending count');
assert.equal(sha256(fixture), fixtureHash, 'test normalization mutated the bootstrap fixture');

const insideView = plain(api.viewModel(normalized[0], { academyAccessAllowed: true }));
assert.deepEqual(insideView, {
  id: 'ilsan-upper',
  name: '일산 기출 2회',
  metaText: '일산 기출 · 대수 · 중상 · 2회차',
  status: 'interrupted',
  statusLabel: '배부',
  answerUrl: 'https://answers.example/ilsan-upper.pdf',
  answerRestricted: false,
  canOpenAnswerUrl: true,
});

const outsideView = plain(api.viewModel(normalized[0], { academyAccessAllowed: false }));
assert.equal(outsideView.answerRestricted, true);
assert.equal(outsideView.canOpenAnswerUrl, false);
const explicitRestrictedInside = plain(api.viewModel(normalized[3], { academyAccessAllowed: true }));
assert.equal(explicitRestrictedInside.answerRestricted, true);
assert.equal(explicitRestrictedInside.canOpenAnswerUrl, true, 'explicit restriction metadata must not change the existing inside-academy link rule');
const noAnswerView = plain(api.viewModel(normalized[2], { academyAccessAllowed: true }));
assert.equal(noAnswerView.answerRestricted, false);
assert.equal(noAnswerView.canOpenAnswerUrl, false);

assert.equal(api.answerUrl({ answerUrl: ' first ', answer_url: 'second', solutionUrl: 'third' }), 'first');
assert.equal(api.answerUrl({ answer_url: ' second ', solutionUrl: 'third' }), 'second');
assert.equal(api.answerUrl({ solution_url: ' fourth ' }), 'fourth');
assert.equal(api.statusLabel('done'), '완료');
assert.equal(api.statusLabel('interrupted'), '배부');
assert.equal(api.statusLabel('skip'), '제외');
assert.equal(api.statusLabel('unknown'), '배정');
assert.equal(api.roundLabel('4'), '4회차');
assert.equal(api.roundLabel('4회'), '4회');

assert.equal(api.shouldOpenAnswerInSameTab({ width: 1024 }), true);
assert.equal(api.shouldOpenAnswerInSameTab({ width: 1025 }), false);
assert.equal(api.shouldOpenAnswerInSameTab({ width: 1440, coarsePointer: true }), true);
assert.equal(api.shouldOpenAnswerInSameTab({ width: 1440, touchPoints: 1 }), true);

for (const forbidden of ['document', 'fetch(', 'localStorage', 'sessionStorage', '/api/']) {
  assert.equal(moduleSource.includes(forbidden), false, `test presentation module leaked an ambient dependency: ${forbidden}`);
}
for (const retired of [
  'function normalizeAssignedTestStatus(',
  'function assignedTestStatusLabel(',
  'function assignedTestDifficultyLabel(',
  'function normalizeAssignedTests(',
  'function assignedTestAnswerUrl(',
  'function isAssignedTestAnswerRestricted(',
  'function canOpenAssignedTestAnswer(',
]) {
  assert.equal(studentSource.includes(retired), false, `student entrypoint still owns a test presentation primitive: ${retired}`);
}
for (const delegated of [
  'window.StudentTestPresentation',
  'viewModel: assignedTestViewModel',
  'const view = assignedTestViewModel(test, { academyAccessAllowed })',
  'createAssignedTestActionElement(view.canOpenAnswerUrl, view.answerUrl)',
  'pendingAssignedTestCount(assignedTestsCache)',
]) {
  assert.ok(studentSource.includes(delegated), `student entrypoint is missing test-presentation delegation: ${delegated}`);
}

const announcementScript = '/js/student/announcementState.js?v=20260828-announcement-state-r1';
const presentationScript = '/js/student/testPresentation.js?v=20260828-test-presentation-r1';
const studentScript = '/js/student.js?v=20260828-test-presentation-r1';
assert.equal((htmlSource.match(/\/js\/student\/testPresentation\.js/g) || []).length, 1);
assert.ok(htmlSource.indexOf(announcementScript) < htmlSource.indexOf(presentationScript));
assert.ok(htmlSource.indexOf(presentationScript) < htmlSource.indexOf(studentScript));

console.log('student test presentation checks passed: normalization, labels, answer access, metadata, pending count, mobile navigation, isolation, and shell order');
