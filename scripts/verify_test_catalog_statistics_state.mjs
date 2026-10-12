import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const catalogSource = fs.readFileSync('static/js/tests/catalogState.js', 'utf8').replace(/^export\s+/gm, '');
const moduleSource = fs.readFileSync('static/js/tests/catalogStatisticsState.js', 'utf8');
const entrySource = fs.readFileSync('static/js/tests.js', 'utf8');
const htmlSource = fs.readFileSync('static/tests.html', 'utf8');
const exportNames = [
  'STATS_TYPE_LABELS', 'compareStatsRows', 'defaultStatsCompare', 'formatNumber', 'formatPercent',
  'projectStatsDetail', 'projectStatsRows', 'projectStatsSummary', 'projectWrongDetails',
  'statForTest', 'statsAverage', 'statsCount', 'statsSearchText', 'statsSignature',
  'statsTypeLabel', 'wrongListText',
];
const statisticsSource = moduleSource
  .replace(/import\s+\{[\s\S]*?\}\s+from\s+['"]\.\/catalogState\.js(?:\?[^'"]*)?['"];\s*/, '')
  .replace(/^export\s+/gm, '');
const executableSource = `${catalogSource}\n${statisticsSource}\nthis.__catalogStatisticsState = { ${exportNames.join(', ')} };`;
const context = {};
vm.runInNewContext(executableSource, context, { filename: 'static/js/tests/catalogStatisticsState.js' });
const api = context.__catalogStatisticsState;

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function sha256(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

const searchKeyForText = value => String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/g, ' ');
const matchesSearchKey = (key, query) => {
  const terms = String(query || '').normalize('NFKC').toLowerCase().trim().split(/\s+/).filter(Boolean);
  return terms.every(term => String(key || '').includes(term));
};

assert.deepEqual(plain(api.STATS_TYPE_LABELS), {
  REVIEW: '복테',
  TRAINING_PACK: '트팩',
  SCHOOL_PAST: '학군지',
  ILSAN_PAST: '일산',
});
assert.equal(api.statsTypeLabel({ key: 'REVIEW', label: '복습 테스트' }), '복테');
assert.equal(api.statsTypeLabel({ key: 'UNIT', label: '단원평가' }), '단원평가');
assert.equal(api.formatPercent(12.34), '12.3%');
assert.equal(api.formatPercent('12.34'), '-');
assert.equal(api.formatPercent(Number.NaN), '-');
assert.equal(api.formatNumber(7), '7.0');
assert.equal(api.formatNumber('7'), '-');

const pastSignatureTest = {
  categoryKey: 'SCHOOL_PAST', curriculum: '대수', name: '  기말   문제 ', term: 'final', round: ' 2 ',
};
assert.equal(
  api.statsSignature(pastSignatureTest),
  'SCHOOL_PAST\u241f대수\u241f기말 문제\u241f기말고사\u241f2',
);
assert.equal(
  api.statsSignature({ curriculum: '공수1', name: ' 단원 ', term: '기말고사', round: 1 }, 'UNIT'),
  'UNIT\u241f공수1\u241f단원\u241f\u241f1',
);

const idStat = { source: 'id', count: 3 };
const signatureStat = { source: 'signature', count: 2 };
const nameStat = { source: 'name', count: 1 };
const lookupTest = { id: 'lookup', categoryKey: 'UNIT', curriculum: '공수1', name: '찾기', round: '1' };
const lookupSignature = api.statsSignature(lookupTest);
assert.equal(api.statForTest(lookupTest, {
  by_test_id: { lookup: idStat },
  by_test_signature: { [lookupSignature]: signatureStat },
  by_test: { '찾기': nameStat },
}), idStat, 'id statistics must have first precedence');
assert.equal(api.statForTest({ ...lookupTest, id: 'missing' }, {
  by_test_signature: { [lookupSignature]: signatureStat },
  by_test: { '찾기': nameStat },
}), signatureStat, 'signature statistics must precede the legacy name map');
assert.equal(api.statForTest({ name: '  찾기  ' }, { by_test: { '찾기': nameStat } }, 'UNIT'), nameStat);

const summary = plain(api.projectStatsSummary({
  categoryDefinitions: [
    { key: 'UNIT', label: '단원평가' },
    { key: 'REVIEW', label: '복습 테스트' },
  ],
  summary: { UNIT: { count: 3, avg_pct: 72.34 } },
  categoryCounts: { UNIT: 9, REVIEW: 4 },
  activeCategory: 'REVIEW',
}));
assert.deepEqual(summary, [
  { key: 'UNIT', label: '단원평가', metric: '72.3%', meta: '응시 3건', active: false },
  { key: 'REVIEW', label: '복습 테스트', metric: '4개', meta: '등록 테스트', active: true },
]);

const tests = [
  { id: 'a', categoryKey: 'REVIEW', curriculum: 'A', name: 'Beta', difficulty: 'L', round: '2', problems: 20, nested: { keep: 1 } },
  { id: 'b', categoryKey: 'REVIEW', curriculum: 'A', name: 'Alpha', difficulty: 'L', round: '1', problems: 10 },
  { id: 'c', categoryKey: 'REVIEW', curriculum: 'A', name: 'Gamma', difficulty: 'L', round: '3', problems: 30 },
  { id: 'd', categoryKey: 'REVIEW', curriculum: 'A', name: 'Delta', difficulty: 'L', round: '4', problems: 40 },
];
const testsHash = sha256(tests);
const stats = {
  by_test_id: {
    a: { count: 3, avg_pct: 90 },
    b: { count: 1 },
    c: { count: 2, avg_pct: 70 },
    d: { count: 0, avg_pct: '88' },
  },
};
const project = (sort, queryText = '') => plain(api.projectStatsRows({
  tests,
  definition: { key: 'REVIEW', label: '복습 테스트' },
  stats,
  queryText,
  sort,
  displayNameFor: test => `Display ${test.name}`,
  searchKeyForText,
  matchesSearchKey,
}));
assert.deepEqual(project('default').map(row => row.id), ['b', 'a', 'c', 'd']);
assert.deepEqual(project('name').map(row => row.id), ['b', 'a', 'd', 'c']);
assert.deepEqual(project('taken_desc').map(row => row.id), ['a', 'c', 'b', 'd']);
assert.deepEqual(project('taken_asc').map(row => row.id), ['d', 'b', 'c', 'a']);
assert.deepEqual(project('avg_desc').map(row => row.id), ['a', 'd', 'c', 'b']);
assert.deepEqual(project('avg_asc').map(row => row.id), ['c', 'd', 'a', 'b']);
assert.deepEqual(project('round').map(row => row.id), ['b', 'a', 'c', 'd']);
assert.deepEqual(project('default', '복테 display gamma 30문항').map(row => row.id), ['c']);
assert.equal(project('default')[0].typeLabel, '복테');
assert.equal(sha256(tests), testsHash, 'statistics row projection mutated catalog rows');

assert.equal(api.wrongListText([]), '틀린 문항 없음');
assert.equal(api.wrongListText([1, ' 2 ', '']), '틀린 문항 1, 2');
assert.deepEqual(plain(api.projectWrongDetails([
  { questionNo: 1, myAnswer: ' 3 ', correctAnswer: 5 },
  { question_no: '2', my_answer: '', correct_answer: ' 4 ' },
  null,
], [1, 2])), {
  rows: [
    { questionLabel: '1번', myAnswer: '3', correctAnswer: '5' },
    { questionLabel: '2번', myAnswer: '-', correctAnswer: '4' },
  ],
  emptyMessage: '',
});
assert.deepEqual(plain(api.projectWrongDetails([], [9])), {
  rows: [],
  emptyMessage: '이전 제출 기록이라 내 답 비교가 없습니다.',
});

const detail = plain(api.projectStatsDetail({
  selected: {
    id: 'past', categoryKey: 'SCHOOL_PAST', curriculum: '대수', name: '원본 이름', displayName: '표시 이름',
    term: '기말고사', difficulty: '상', round: '2', sourceFiles: { solutionFileId: 'must-not-fallback' },
  },
  stat: { count: 2, avg_pct: 75, stddev_pct: 5, median_pct: 75, max_pct: 100, min_pct: 50 },
  detail: {
    answerUrl: ' https://answers.example/detail.pdf ',
    records: [{
      sid: 's1', level: '중', pct: 50, correct: 1, total: 2, wrong: [2],
      wrongDetails: [{ question_no: 2, my_answer: '<x>', correct_answer: '4' }],
      createdAt: '2026-08-29T12:34:56+09:00',
    }],
  },
  displayNameFor: test => test.name,
}));
assert.equal(detail.title, '표시 이름');
assert.equal(detail.subtitle, '대수 · 기말고사 · 상 · 2회차');
assert.deepEqual(detail.metrics, [
  { label: '응시', value: 2 },
  { label: '평균', value: '75.0%' },
  { label: '표준편차', value: '5.0' },
  { label: '중앙값', value: '75.0%' },
  { label: '최대', value: '100.0%' },
  { label: '최소', value: '50.0%' },
]);
assert.deepEqual(detail.answerLink, { url: 'https://answers.example/detail.pdf', label: '전체 답지 보기' });
assert.deepEqual(detail.records, [{
  studentName: 's1',
  level: '중',
  percent: '50.0%',
  score: '1 / 2',
  wrongText: '틀린 문항 2',
  wrongDetails: {
    rows: [{ questionLabel: '2번', myAnswer: '<x>', correctAnswer: '4' }],
    emptyMessage: '',
  },
  createdDate: '2026-08-29',
}]);
assert.equal(api.projectStatsDetail({ selected: { name: 'No API URL', sourceFiles: { answerUrl: 'hidden' } } }).answerLink, null);

for (const forbidden of ['document', 'window', 'fetch(', 'localStorage', 'sessionStorage', '/api/']) {
  assert.equal(moduleSource.includes(forbidden), false, `catalog statistics module leaked an ambient dependency: ${forbidden}`);
}
for (const retired of [
  'const STATS_TYPE_LABELS =',
  'function fmtPct(',
  'function statsSignature(',
  'function compareStatsRows(',
  'function wrongListText(',
]) {
  assert.equal(entrySource.includes(retired), false, `tests entrypoint still owns statistics primitive: ${retired}`);
}
for (const delegated of [
  "from './tests/catalogStatisticsState.js?v=20260907-ilsan-level-r1'",
  'projectStatsSummary({',
  'projectStatsRows({',
  'projectStatsDetail({',
  'statForTest(test, TEST_STATS, ui.category)',
]) {
  assert.ok(entrySource.includes(delegated), `tests entrypoint is missing statistics-state delegation: ${delegated}`);
}
assert.match(htmlSource, /<script src="\/js\/tests\.js\?v=20260907-ilsan-level-r1&hub=20261001-detail1" type="module"><\/script>/);

console.log('test catalog statistics checks passed: labels, lookup precedence, summary, search/sort, detail projection, answer-link restriction, isolation, and entrypoint delegation');
