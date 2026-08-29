import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const moduleSource = fs.readFileSync('static/js/tests/catalogEditorState.js', 'utf8');
const entrySource = fs.readFileSync('static/js/tests.js', 'utf8');
const htmlSource = fs.readFileSync('static/tests.html', 'utf8');
const exportNames = [
  'ANSWER_MODE_OPTIONS',
  'answerKeyForTest',
  'answerKeyFromCsvRow',
  'answerKeysToText',
  'answerModeConsistencyIssue',
  'answerModeSummary',
  'answerModesForTest',
  'answerModesFromCsvRow',
  'buildTestCatalogCsvTemplate',
  'csvAnswerRounds',
  'csvCell',
  'hasRoundAnswerColumns',
  'headerKey',
  'normalizeAnswerMode',
  'normalizeCsvAnswerMode',
  'parseAnswerSpec',
  'parseAnswerSpec3',
  'parseCsv',
  'parseCsvAnswerModes',
  'projectAnswerRound',
  'rowObject',
];
const executableSource = `${moduleSource.replace(/^export\s+/gm, '')}\nthis.__catalogEditorState = { ${exportNames.join(', ')} };`;
const context = {};
vm.runInNewContext(executableSource, context, { filename: 'static/js/tests/catalogEditorState.js' });
const api = context.__catalogEditorState;

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function sha256(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

assert.deepEqual(plain(api.parseAnswerSpec('1 3,5', 4)), ['1', '3', '5', '']);
assert.deepEqual(plain(api.parseAnswerSpec('', 3)), ['', '', '']);
assert.deepEqual(plain(api.parseAnswerSpec(['1', '2'], 4)), ['1', '2']);
assert.deepEqual(
  plain(api.parseAnswerSpec('1342', 4)),
  ['1342', '', '', ''],
  'approved parser contract keeps undelimited compact text as one answer plus padding',
);

const repeatedRounds = api.parseAnswerSpec3('1 2', 2);
assert.deepEqual(plain(repeatedRounds), { '1': ['1', '2'], '2': ['1', '2'], '3': ['1', '2'] });
assert.notEqual(repeatedRounds['1'], repeatedRounds['2']);
assert.deepEqual(
  plain(api.parseAnswerSpec3('1 2\n3 4', 2)),
  { '1': ['1', '2'], '2': ['3', '4'], '3': ['', ''] },
);

const answerTest = {
  problems: 3,
  round: '2',
  answerKeys: { '1': ['1', '2', '3'], '2': ['4', '5', '6'] },
  answerKey: ['legacy', 'legacy', 'legacy'],
};
assert.deepEqual(plain(api.answerKeyForTest(answerTest)), ['4', '5', '6']);
assert.equal(api.answerKeysToText(answerTest), '4 5 6');
assert.deepEqual(
  plain(api.answerKeyForTest({ problems: 2, round: '9', answerKeys: { '3': ['7'] } })),
  ['7'],
);
assert.deepEqual(plain(api.answerKeyForTest({ problems: 2, answerKey: '8 9' })), ['8', '9']);

assert.equal(api.normalizeAnswerMode('choice_number'), 'choice_number');
assert.equal(api.normalizeAnswerMode('choice-number'), '');
assert.deepEqual(
  plain(api.answerModesForTest({ answerModes: { '2': ['choice_number', 'answer_value'] } }, 3, '2')),
  ['choice_number', 'answer_value', ''],
);
assert.equal(
  api.answerModeConsistencyIssue(['6'], ['choice_number']),
  '1번 객관식 정답은 1~5여야 합니다',
);
assert.equal(
  api.answerModeConsistencyIssue([''], ['answer_value']),
  '1번 단답형 정답을 입력해주세요',
);
assert.equal(
  api.answerModeConsistencyIssue(['1'], ['']),
  '1번 문항 유형을 확인해주세요',
);
assert.equal(api.answerModeConsistencyIssue([''], ['manual_review']), '');
assert.deepEqual(
  plain(api.answerModeSummary(['choice_number', 'answer_value', 'manual_review', '', 'choice_number'])),
  {
    counts: { choice_number: 2, answer_value: 1, manual_review: 1, unverified: 1 },
    text: '객관식 2 · 단답형 1 · 수동 1 · 미확인 1',
  },
);

const projectionInput = {
  id: 'keep',
  answerKeys: { '1': ['1', '2'] },
  answerModes: { '1': ['choice_number', 'choice_number'] },
  futureField: { keep: true },
};
const projectionInputHash = sha256(projectionInput);
const projection = api.projectAnswerRound(projectionInput, {
  answers: '3 1/2',
  problems: 2,
  round: '2',
  modes: ['choice_number', 'answer_value'],
});
assert.deepEqual(plain(projection), {
  round: '2',
  answerKey: ['3', '1/2'],
  answerKeys: { '1': ['1', '2'], '2': ['3', '1/2'] },
  answerModes: {
    '1': ['choice_number', 'choice_number'],
    '2': ['choice_number', 'answer_value'],
  },
  issue: '',
});
assert.equal(sha256(projectionInput), projectionInputHash, 'answer projection mutated its test input');

assert.equal(api.csvCell('plain'), 'plain');
assert.equal(api.csvCell('a,b'), '"a,b"');
assert.equal(api.csvCell('a"b'), '"a""b"');
assert.equal(api.csvCell('a\nb'), '"a\nb"');

const template = api.buildTestCatalogCsvTemplate('그래프 포함');
assert.ok(template.startsWith('\uFEFF분류,과목,난이도'));
const templateRows = api.parseCsv(template);
assert.equal(templateRows.length, 7);
assert.equal(templateRows[0].length, 15);
assert.equal(templateRows.at(-1)[2], '그래프 포함');
assert.equal(templateRows[2][9].split(' ').length, 20);
assert.equal(templateRows[2][10].split(' ').length, 20);

const quotedRows = api.parseCsv('\uFEFF시험명,정답\r\n"가,나","1 ""2"""\r\n');
assert.deepEqual(plain(quotedRows), [
  ['\uFEFF시험명', '정답'],
  ['가,나', '1 "2"'],
]);
const headers = quotedRows[0].map(api.headerKey);
assert.deepEqual(plain(headers), ['name', 'answers']);
assert.equal(api.headerKey(' 시험 기간 '), 'term');
assert.equal(api.headerKey('answer_modes_json'), 'modesJson');
assert.deepEqual(plain(api.rowObject(headers, quotedRows[1])), { name: '가,나', answers: '1 "2"' });

const csvRow = {
  answers1: '1 2',
  answers3: '4 5',
  answers: 'fallback',
  modes1: '객관식 단답형',
  modesJson: JSON.stringify({ '3': ['choice_number', 'manual_review'] }),
};
const csvRowHash = sha256(csvRow);
assert.deepEqual(plain(api.csvAnswerRounds(csvRow)), ['1', '3']);
assert.equal(api.hasRoundAnswerColumns(csvRow), true);
assert.deepEqual(plain(api.answerKeyFromCsvRow(csvRow, '1', 2)), ['1', '2']);
assert.deepEqual(
  plain(api.answerModesFromCsvRow(csvRow, '1', 2)),
  ['choice_number', 'answer_value'],
);
assert.deepEqual(
  plain(api.answerModesFromCsvRow(csvRow, '3', 2)),
  ['choice_number', 'manual_review'],
);
assert.equal(sha256(csvRow), csvRowHash, 'CSV answer projection mutated its row input');

assert.equal(api.normalizeCsvAnswerMode('Choice-Number'), 'choice_number');
assert.equal(api.normalizeCsvAnswerMode('주관식'), 'answer_value');
assert.equal(api.normalizeCsvAnswerMode('수동 검토'), 'manual_review');
assert.deepEqual(
  plain(api.parseCsvAnswerModes('["choice","단답형"]', 2)),
  ['choice_number', 'answer_value'],
);
assert.deepEqual(plain(api.parseCsvAnswerModes('choice_number', 2)), []);

const warnings = [];
assert.deepEqual(
  plain(api.answerKeyFromCsvRow({ answersJson: '{', answers: '2 3' }, '1', 2, (...args) => warnings.push(args))),
  ['2', '3'],
);
assert.deepEqual(
  plain(api.answerModesFromCsvRow({ modesJson: '{', modes: 'choice manual' }, '1', 2, (...args) => warnings.push(args))),
  ['choice_number', 'manual_review'],
);
assert.equal(warnings.length, 2);
assert.equal(warnings[0][0], '[tests] answers_json parse failed');
assert.equal(warnings[1][0], '[tests] modes_json parse failed');

for (const forbidden of ['document', 'window', 'fetch(', 'localStorage', 'sessionStorage', '/api/']) {
  assert.equal(moduleSource.includes(forbidden), false, `catalog editor state leaked an ambient dependency: ${forbidden}`);
}
for (const retired of [
  'function parseAnswerSpec(',
  'function answerModeConsistencyIssue(',
  'function parseCsv(',
  'function headerKey(',
  'function answerModesFromCsvRow(',
]) {
  assert.equal(entrySource.includes(retired), false, `tests entrypoint still owns editor primitive: ${retired}`);
}
for (const delegated of [
  "from './tests/catalogEditorState.js?v=20260829-catalog-editor-state-r1'",
  'answerModeSummary(modes).text',
  'buildTestCatalogCsvTemplate(ILSAN_GRAPH_DIFFICULTY)',
  'answerKeyFromCsvRow(row, round, problems, reportCsvParseWarning)',
  'projectAnswerRound(selectedTestRef()?.test || null, {',
]) {
  assert.ok(entrySource.includes(delegated), `tests entrypoint is missing editor-state delegation: ${delegated}`);
}
assert.match(
  htmlSource,
  /<script src="\/js\/tests\.js\?v=20260829-catalog-statistics-state-r1" type="module"><\/script>/,
);
assert.match(
  htmlSource,
  /정답은 문항별로 구분해 <code>1 3 4 2<\/code> 또는 <code>1,3,4,2<\/code> 형식으로 입력합니다/,
  'answer help must describe only the two supported multi-answer delimiter forms',
);
assert.doesNotMatch(
  htmlSource,
  /<code>1342<\/code>/,
  'answer help must not claim compact text is split across questions',
);

console.log('test catalog editor state checks passed: answer parsing/modes, round projection, CSV template/parser/aliases, input hashes, isolation, approved compact-input contract/help, and entrypoint delegation');
