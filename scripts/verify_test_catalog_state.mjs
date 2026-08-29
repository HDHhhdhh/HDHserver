import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const moduleSource = fs.readFileSync('static/js/tests/catalogState.js', 'utf8');
const entrySource = fs.readFileSync('static/js/tests.js', 'utf8');
const htmlSource = fs.readFileSync('static/tests.html', 'utf8');
const exportNames = [
  'CATEGORY_BY_KEY', 'CATEGORY_DEFS', 'ILSAN_GRAPH_DIFFICULTY', 'STUDENT_LEVELS', 'SUBJECTS', 'TERM_OPTIONS',
  'canonText', 'captureCatalogMutationSnapshot', 'catalogGroupKey', 'catalogSearchText', 'categoryKeyFrom',
  'categoryLabel', 'compareCatalogTests', 'ensureConfig', 'isPastCategory', 'isUnitCategory',
  'normalizeCatalogTest', 'normalizeDifficulty', 'normalizeRevision', 'normalizeRound', 'normalizeSubject',
  'normalizeTerm', 'projectCatalogOrderBlock', 'roundLabel', 'roundSortValue', 'termSortValue',
  'testDefinitionWriteRequest', 'visibleCatalogTests', 'wholeConfigWriteRequest',
];
const executableSource = `${moduleSource.replace(/^export\s+/gm, '')}\nthis.__catalogState = { ${exportNames.join(', ')} };`;
const context = {};
vm.runInNewContext(executableSource, context, { filename: 'static/js/tests/catalogState.js' });
const api = context.__catalogState;

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function sha256(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

const legacyConfig = {
  futureRoot: { preserve: true },
  categories: {
    ILSAN_PAST: { label: '', tests: [{ id: 'keep', futureField: { nested: true } }] },
  },
  autoAssignRules: {
    REVIEW: { '공수1': { '상': ['상'] } },
    ILSAN_PAST: {
      '대수': {
        '상': ['상'],
        '삼각함수 그래프 포함': ['중'],
      },
    },
  },
};
const ensured = api.ensureConfig(legacyConfig);
assert.equal(ensured, legacyConfig, 'config normalization must preserve the existing object identity');
assert.equal(ensured.futureRoot.preserve, true);
assert.equal(ensured.categories.ILSAN_PAST.tests[0].futureField.nested, true);
assert.deepEqual(Object.keys(plain(ensured.categories)).sort(), ['ILSAN_PAST', 'REVIEW', 'SCHOOL_PAST', 'TRAINING_PACK', 'UNIT']);
assert.equal(ensured.categories.ILSAN_PAST.label, '일산 기출');
assert.equal(Object.hasOwn(ensured.autoAssignRules.ILSAN_PAST.대수, '상'), false);
assert.equal(Object.hasOwn(ensured.autoAssignRules.ILSAN_PAST.대수, '삼각함수 그래프 포함'), false);
assert.deepEqual(plain(ensured.autoAssignRules.ILSAN_PAST.대수['중상']), ['하', '중', '중상', '상']);
assert.deepEqual(plain(ensured.autoAssignRules.ILSAN_PAST.대수['그래프 포함']), ['하', '중', '중상', '상']);
assert.deepEqual(plain(ensured.autoAssignRules.REVIEW['공수1']['상']), ['상'], 'non-Ilsan custom arrays must survive');

const rawTest = {
  title: '그래프 포함 일산 기출 기말 2회차',
  subject: '미적분Ⅰ',
  difficulty: '상',
  problems: 0,
  sourceFiles: { solutionFileId: 'solution-keep' },
  futureShape: { keep: true },
};
const rawHash = sha256(rawTest);
const normalized = plain(api.normalizeCatalogTest(rawTest, '일산', 4, { fallbackSubject: '공수1', now: 1234 }));
assert.equal(normalized.id, 't_ILSAN_PAST_1234_4');
assert.equal(normalized.name, rawTest.title);
assert.equal(normalized.categoryKey, 'ILSAN_PAST');
assert.equal(normalized.curriculum, '미적분1');
assert.equal(normalized.difficulty, '그래프 포함');
assert.equal(normalized.term, '기말고사');
assert.equal(normalized.round, '2');
assert.equal(normalized.problems, 1);
assert.equal(normalized.sourceFiles.solutionFileId, 'solution-keep');
assert.equal(normalized.futureShape.keep, true);
assert.equal(sha256(rawTest), rawHash, 'test normalization mutated the raw catalog row');

const searchKeyForText = value => String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/g, ' ');
const matchesSearchKey = (key, query) => {
  const terms = String(query || '').normalize('NFKC').toLowerCase().trim().split(/\s+/).filter(Boolean);
  return terms.every(term => String(key || '').includes(term));
};
const reviewRows = [
  { id: 'one', sourceId: 'drive-one', name: '첫 번째', categoryKey: 'REVIEW', curriculum: '공수1', difficulty: '상', round: '2', sortOrder: 2, problems: 20 },
  { id: 'two', sourceId: 'drive-two', name: '두 번째', categoryKey: 'REVIEW', curriculum: '공수1', difficulty: '상', round: '1', sortOrder: 0, problems: 20 },
  { id: 'other', sourceId: 'drive-other', name: '다른 난이도', categoryKey: 'REVIEW', curriculum: '공수1', difficulty: '중상', round: '1', sortOrder: 1, problems: 20 },
];
const reviewHash = sha256(reviewRows);
const visibleReview = plain(api.visibleCatalogTests(reviewRows, {
  category: 'REVIEW', subject: '공수1', difficulty: '상', term: '', round: '', catalogSearch: '',
}, { searchKeyForText, matchesSearchKey, displayNameFor: test => test.name }));
assert.deepEqual(visibleReview.map(test => test.id), ['two', 'one']);
const searchedReview = plain(api.visibleCatalogTests(reviewRows, {
  category: 'REVIEW', subject: '공수1', difficulty: '상', term: '', round: '', catalogSearch: 'drive one',
}, { searchKeyForText, matchesSearchKey, displayNameFor: test => test.name }));
assert.deepEqual(searchedReview.map(test => test.id), ['one']);
assert.equal(sha256(reviewRows), reviewHash, 'visible-list projection mutated catalog rows');

const pastRows = [
  { id: 'final', name: '기말', categoryKey: 'SCHOOL_PAST', curriculum: '대수', difficulty: '상', term: '기말고사', round: '1', sortOrder: 0 },
  { id: 'mid', name: '중간', categoryKey: 'SCHOOL_PAST', curriculum: '대수', difficulty: '상', term: '중간고사', round: '9', sortOrder: 9 },
];
assert.deepEqual([...pastRows].sort((a, b) => api.compareCatalogTests(a, b, 'SCHOOL_PAST')).map(test => test.id), ['mid', 'final']);
const unitRows = [
  { id: 'ten', name: '10회', difficulty: 'Lv.3', round: '10', sortOrder: 0 },
  { id: 'two', name: '2회', difficulty: 'Lv.3', round: '2', sortOrder: 9 },
];
assert.deepEqual([...unitRows].sort((a, b) => api.compareCatalogTests(a, b, 'UNIT')).map(test => test.id), ['two', 'ten']);
assert.equal(api.catalogGroupKey({ difficulty: '상', round: '2' }, 'UNIT'), '상|||2');
assert.equal(api.catalogGroupKey({ difficulty: '상', term: '중간고사' }, 'SCHOOL_PAST'), '중간고사|||상|||');

assert.equal(api.projectCatalogOrderBlock({ catalogSearch: 'x', category: 'REVIEW' }).kind, 'blocked');
assert.match(api.projectCatalogOrderBlock({ category: 'UNIT', round: '2' }).message, /회차/);
assert.match(api.projectCatalogOrderBlock({ category: 'SCHOOL_PAST', term: '중간고사' }).message, /고사/);
assert.equal(api.projectCatalogOrderBlock({ category: 'REVIEW' }), null);
assert.equal(api.projectCatalogOrderBlock({ catalogMutationSaveInFlight: true }).kind, 'saving');

const revision = 'A'.repeat(64);
assert.equal(api.normalizeRevision(revision), 'a'.repeat(64));
assert.equal(api.normalizeRevision('not-a-revision'), '');
const configPayload = { categories: { UNIT: { tests: [{ id: 'keep', unknown: { value: 7 } }] } }, futureRoot: true };
const configHash = sha256(configPayload);
const wholeRequest = api.wholeConfigWriteRequest(configPayload, revision, [9, 'ten']);
assert.equal(wholeRequest.method, 'POST');
assert.equal(wholeRequest.headers['Content-Type'], 'application/json');
assert.equal(wholeRequest.headers['X-Tests-Config-Revision'], 'a'.repeat(64));
assert.deepEqual(JSON.parse(wholeRequest.body).__removedTestIds, ['9', 'ten']);
assert.equal(JSON.parse(wholeRequest.body).categories.UNIT.tests[0].unknown.value, 7);
assert.equal(sha256(configPayload), configHash, 'whole-config request projection mutated the config');
assert.equal(Object.hasOwn(api.wholeConfigWriteRequest(configPayload, 'bad').headers, 'X-Tests-Config-Revision'), false);

const patchTest = { id: 'patch', sourceFiles: { solutionFileId: 'solution' }, unknown: { keep: true } };
const patchHash = sha256(patchTest);
const patchRequest = api.testDefinitionWriteRequest(patchTest, 'UNIT', '단원평가', ['term', 'examTerm'], revision);
assert.equal(patchRequest.method, 'PATCH');
assert.deepEqual(JSON.parse(patchRequest.body), {
  categoryKey: 'UNIT', categoryLabel: '단원평가', test: patchTest, clearFields: ['term', 'examTerm'],
});
assert.equal(sha256(patchTest), patchHash, 'single-test request projection mutated the test');

const snapshot = api.captureCatalogMutationSnapshot(configPayload, revision, 'keep');
snapshot.config.categories.UNIT.tests[0].id = 'changed';
assert.equal(configPayload.categories.UNIT.tests[0].id, 'keep');
assert.equal(snapshot.revision, 'a'.repeat(64));
assert.equal(snapshot.selectedId, 'keep');

for (const forbidden of ['document', 'window', 'fetch(', 'localStorage', 'sessionStorage', '/api/']) {
  assert.equal(moduleSource.includes(forbidden), false, `catalog state module leaked an ambient dependency: ${forbidden}`);
}
for (const retired of [
  'function ensureConfig(',
  'function normalizeDifficulty(',
  'function catalogSearchText(',
  'function compareTestsForList(',
  "const headers = { ...CT }",
]) {
  assert.equal(entrySource.includes(retired), false, `tests entrypoint still owns catalog state primitive: ${retired}`);
}
for (const delegated of [
  "from './tests/catalogState.js?v=20260829-catalog-state-r1'",
  'normalizeCatalogTest(rawTest, rawCategoryKey, idx, {',
  'visibleCatalogTests(getCategoryTests(ui.category), ui, {',
  'projectCatalogOrderBlock({',
  'wholeConfigWriteRequest(TEST_CFG, TEST_CFG_REVISION, removedTestIds)',
  'testDefinitionWriteRequest(',
]) {
  assert.ok(entrySource.includes(delegated), `tests entrypoint is missing catalog-state delegation: ${delegated}`);
}
assert.match(htmlSource, /<script src="\/js\/tests\.js\?v=20260829-catalog-statistics-state-r1" type="module"><\/script>/);

console.log('test catalog state checks passed: config/test normalization, search/sort/grouping, order gates, revisioned write projections, rollback snapshot, isolation, and entrypoint delegation');
