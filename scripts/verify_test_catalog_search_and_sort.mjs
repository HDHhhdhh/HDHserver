import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TESTS_JS_PATH = path.join(ROOT, 'static', 'js', 'tests.js');
const CATALOG_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogState.js');
const CATALOG_EDITOR_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogEditorState.js');
const CATALOG_STATISTICS_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogStatisticsState.js');
const TESTS_HTML_PATH = path.join(ROOT, 'static', 'tests.html');

const testsHtml = fs.readFileSync(TESTS_HTML_PATH, 'utf8');
const catalogStateSource = fs.readFileSync(CATALOG_STATE_PATH, 'utf8').replace(/^export\s+/gm, '');
const catalogEditorStateSource = fs.readFileSync(CATALOG_EDITOR_STATE_PATH, 'utf8').replace(/^export\s+/gm, '');
const catalogStatisticsStateSource = fs.readFileSync(CATALOG_STATISTICS_STATE_PATH, 'utf8')
  .replace(/import\s+\{[\s\S]*?\}\s+from\s+['"]\.\/catalogState\.js(?:\?[^'"]*)?['"];\s*/, '')
  .replace(/^export\s+/gm, '');
const source = fs
  .readFileSync(TESTS_JS_PATH, 'utf8')
  .replace(/import\s+\{[^}]+\}\s+from\s+['"]\.\/shared\/search\.js['"];\s*/, `
function applySearchPlaceholder(input, label) {
  if (input) input.placeholder = String(label || '');
}
function searchKeyForText(value) {
  return String(value || '').normalize('NFKC').toLowerCase().replace(/\\s+/g, ' ');
}
function matchesSearchKey(key, query) {
  const terms = String(query || '').normalize('NFKC').toLowerCase().trim().split(/\\s+/).filter(Boolean);
  return terms.every(term => String(key || '').includes(term));
}
`)
  .replace(
    /import\s+\{\s*createUnitTestDisplayNameResolver\s*\}\s+from\s+['"]\.\/shared\/testCatalogDisplay\.js['"];\s*/,
    "const createUnitTestDisplayNameResolver = () => (test) => String(test?.name || '');\n",
  )
  .replace(
    /import\s+\{[\s\S]*?\}\s+from\s+['"]\.\/tests\/catalogState\.js(?:\?[^'"]*)?['"];\s*/,
    `${catalogStateSource}\n`,
  )
  .replace(
    /import\s+\{[\s\S]*?\}\s+from\s+['"]\.\/tests\/catalogEditorState\.js(?:\?[^'"]*)?['"];\s*/,
    `${catalogEditorStateSource}\n`,
  )
  .replace(
    /import\s+\{[\s\S]*?\}\s+from\s+['"]\.\/tests\/catalogStatisticsState\.js(?:\?[^'"]*)?['"];\s*/,
    `${catalogStatisticsStateSource}\n`,
  );

class ElementStub {
  constructor(id = '') {
    this.id = id;
    this.value = '';
    this.innerHTML = '';
    this.textContent = '';
    this.hidden = false;
    this.disabled = false;
    this.dataset = {};
    this.style = {};
    this.handlers = {};
    this.classList = {
      add() {},
      remove() {},
      contains() { return false; },
    };
  }

  addEventListener(type, handler) { this.handlers[type] = handler; }
  setAttribute(name, value) { this[name] = String(value); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() {}
}

const elements = new Map();
const getElement = id => {
  if (!elements.has(id)) elements.set(id, new ElementStub(id));
  return elements.get(id);
};
getElement('statRecent').value = '30';

const document = {
  body: new ElementStub('body'),
  addEventListener() {},
  createElement: () => new ElementStub(),
  querySelector(selector) {
    const idMatch = String(selector).match(/^#([A-Za-z0-9_-]+)$/);
    return idMatch ? getElement(idMatch[1]) : null;
  },
  querySelectorAll() { return []; },
};

const fetchCalls = [];
let fetchMode = 'success';
const quietConsole = {
  ...console,
  error() {},
};
const context = {
  document,
  window: { addEventListener() {} },
  console: quietConsole,
  fetch: async (url, init = {}) => {
    fetchCalls.push({
      url: String(url || ''),
      method: String(init.method || 'GET'),
      headers: { ...(init.headers || {}) },
      body: init.body ? JSON.parse(init.body) : null,
    });
    if (fetchMode === 'conflict') {
      if (String(init.method || 'GET') === 'POST') {
        return { ok: false, status: 409, headers: { get: () => '' }, text: async () => 'conflict' };
      }
      const body = String(url || '').includes('/api/tests-config')
        ? JSON.stringify({
          serverRevision: 'latest-after-conflict',
          categories: {
            REVIEW: {
              label: '복습 테스트',
              tests: [{
                id: 'server-latest', name: '서버 최신 목록', curriculum: '공수1',
                difficulty: '상', round: '1', sortOrder: 44, serverOnly: true,
              }],
            },
          },
        })
        : '{}';
      return {
        ok: true,
        status: 200,
        headers: { get: name => String(name).toLowerCase() === 'x-tests-config-revision' ? 'c'.repeat(64) : '' },
        text: async () => body,
      };
    }
    return fetchMode === 'success'
      ? {
        ok: true,
        status: 200,
        headers: { get: name => String(name).toLowerCase() === 'x-tests-config-revision' ? 'b'.repeat(64) : '' },
        text: async () => '{}',
        json: async () => ({ test: init.body ? JSON.parse(init.body).test : { id: 'patch-check', saved: true } }),
      }
      : { ok: false, status: 500, headers: { get: () => '' }, text: async () => 'failure' };
  },
  alert: message => { throw new Error(`unexpected alert: ${message}`); },
  confirm: () => true,
  Date,
  Math,
  Number,
  String,
  Array,
  Object,
  Set,
  Map,
  RegExp,
  JSON,
  URL,
  URLSearchParams,
  Blob,
  setTimeout,
  clearTimeout,
};
context.window.window = context.window;
context.window.document = document;

vm.createContext(context);
vm.runInContext(source, context, { filename: 'static/js/tests.js' });

context.fetchCalls = fetchCalls;
context.setFetchMode = value => { fetchMode = value; };

vm.runInContext(`
window.__catalogSortScenario = (async () => {
  const check = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const sameArrayIdentity = (actual, expected, message) => {
    check(actual.length === expected.length, message + ' (length)');
    actual.forEach((value, index) => check(value === expected[index], message + ' (index ' + index + ')'));
  };

  const oneSourceFiles = { solutionFileId: 'solution-one', nested: { keep: true } };
  const oneAnswerKeys = { '1': ['1', '2'], bonus: ['A'] };
  const oneUnknown = { future: { enabled: true }, labels: ['keep', 'all'] };
  const one = {
    id: 'one', sourceId: 'drive-one', name: '첫 번째', category: 'REVIEW',
    curriculum: '공수1', difficulty: '상', round: '1', problems: 2,
    sortOrder: 0, sourceOrder: 501, sourceFiles: oneSourceFiles,
    answerKeys: oneAnswerKeys, unknownMetadata: oneUnknown,
  };
  const two = {
    id: 'two', sourceId: 'drive-two', name: '두 번째', category: 'REVIEW',
    curriculum: '공수1', difficulty: '상', round: '2', problems: 2,
    sortOrder: 1, sourceOrder: 502, sourceFiles: { solutionFileId: 'solution-two' },
    answerKeys: { '2': ['3', '4'] }, futureFlag: 'preserve-me',
  };
  const three = {
    id: 'three', sourceId: 'drive-three', name: '세 번째', category: 'REVIEW',
    curriculum: '공수1', difficulty: '상', round: '3', problems: 2,
    sortOrder: 2, sourceOrder: 503, sourceFiles: { solutionFileId: 'solution-three' },
    answerKeys: { '3': ['2', '1'] },
  };
  const otherGroup = {
    id: 'other', sourceId: 'drive-other', name: '다른 그룹', category: 'REVIEW',
    curriculum: '공수1', difficulty: '중상', round: '1', sortOrder: 77, sourceOrder: 900,
    sourceFiles: { solutionFileId: 'do-not-touch' },
  };

  TEST_CFG = { categories: { REVIEW: { label: '복습 테스트', tests: [two, otherGroup, one, three] } } };
  ui.category = 'REVIEW';
  ui.subject = '공수1';
  ui.difficulty = '상';
  ui.term = '';
  ui.round = '';
  ui.catalogSearch = '';
  catalogOrderSaveInFlight = false;
  catalogOrderFeedback = null;
  TEST_CFG_REVISION = 'a'.repeat(64);

  const success = await persistCatalogReorder(2, 3, 'after', 'drag');
  check(success, 'same-group drag reorder did not save');
  sameArrayIdentity(TEST_CFG.categories.REVIEW.tests, [two, otherGroup, three, one], 'raw category array was rebuilt or reordered outside its group slots');
  check(two.sortOrder === 0 && three.sortOrder === 1 && one.sortOrder === 2, 'sortOrder was not stably reassigned inside the group');
  check(otherGroup.sortOrder === 77, 'another group sortOrder was changed');
  check(one.sourceOrder === 501 && two.sourceOrder === 502 && three.sourceOrder === 503, 'sourceOrder provenance changed');
  check(one.sourceFiles === oneSourceFiles, 'sourceFiles object identity was lost');
  check(one.answerKeys === oneAnswerKeys, 'answerKeys object identity was lost');
  check(one.unknownMetadata === oneUnknown, 'unknown metadata object identity was lost');

  const successPayload = fetchCalls.at(-1)?.body?.categories?.REVIEW?.tests || [];
  check(fetchCalls.at(-1)?.headers?.['X-Tests-Config-Revision'] === 'a'.repeat(64), 'catalog save omitted its base revision');
  check(TEST_CFG_REVISION === 'b'.repeat(64), 'catalog save did not retain the server revision');
  const savedOne = successPayload.find(test => test.id === 'one');
  check(savedOne?.sourceId === 'drive-one', 'sourceId was omitted from the saved payload');
  check(savedOne?.sourceFiles?.solutionFileId === 'solution-one', 'sourceFiles were omitted from the saved payload');
  check(savedOne?.answerKeys?.bonus?.[0] === 'A', 'answerKeys were narrowed in the saved payload');
  check(savedOne?.unknownMetadata?.future?.enabled === true, 'unknown keys were omitted from the saved payload');

  const fetchCountBeforeBoundary = fetchCalls.length;
  const firstGroupTestIndex = TEST_CFG.categories.REVIEW.tests.indexOf(two);
  const boundaryMove = await moveCatalogTestByKeyboard(firstGroupTestIndex, -1);
  check(boundaryMove === false, 'keyboard move crossed the top group boundary');
  check(fetchCalls.length === fetchCountBeforeBoundary, 'group-boundary keyboard move attempted a save');

  const oneIndexBeforeKeyboard = TEST_CFG.categories.REVIEW.tests.indexOf(one);
  const keyboardMove = await moveCatalogTestByKeyboard(oneIndexBeforeKeyboard, -1);
  check(keyboardMove, 'keyboard up control did not use the reorder save path');
  sameArrayIdentity(TEST_CFG.categories.REVIEW.tests, [two, otherGroup, one, three], 'keyboard reorder did not stay in group slots');

  ui.catalogSearch = 'drive one';
  const searchResults = getVisibleTests();
  check(searchResults.length === 1 && searchResults[0].id === 'one', 'catalog search did not filter independently by source ID terms');
  check(!canReorderCatalog(), 'catalog search did not disable ordering');
  const fetchCountBeforeSearchMove = fetchCalls.length;
  const blockedSearchMove = await persistCatalogReorder(
    TEST_CFG.categories.REVIEW.tests.indexOf(one),
    TEST_CFG.categories.REVIEW.tests.indexOf(two),
    'before'
  );
  check(blockedSearchMove === false && fetchCalls.length === fetchCountBeforeSearchMove, 'search-narrowed reorder attempted a save');

  const unitOne = { id: 'unit-one', name: '단원 1회', curriculum: '공수1', difficulty: 'Lv.3', round: '1', sourceOrder: 1 };
  const unitTwo = { id: 'unit-two', name: '단원 2회', curriculum: '공수1', difficulty: 'Lv.3', round: '2', sourceOrder: 2 };
  TEST_CFG = { categories: { UNIT: { label: '단원평가', tests: [unitOne, unitTwo] } } };
  ui.category = 'UNIT';
  ui.difficulty = 'Lv.3';
  ui.catalogSearch = '';
  ui.round = '';
  const fetchCountBeforeCrossGroup = fetchCalls.length;
  const crossGroupMove = await persistCatalogReorder(0, 1, 'after');
  check(crossGroupMove === false, 'UNIT reorder crossed the difficulty+round group boundary');
  check(fetchCalls.length === fetchCountBeforeCrossGroup, 'cross-group drag attempted a save');
  ui.round = '1';
  check(!canReorderCatalog() && /회차/.test(catalogOrderBlock().message), 'round narrowing did not disable ordering with a clear reason');

  ui.category = 'SCHOOL_PAST';
  ui.round = '';
  ui.term = '중간고사';
  check(!canReorderCatalog() && /고사/.test(catalogOrderBlock().message), 'term narrowing did not disable ordering with a clear reason');

  const failSourceFiles = { solutionFileId: 'rollback-solution', opaque: { value: 7 } };
  const failA = {
    id: 'fail-a', name: '롤백 A', curriculum: '공수1', difficulty: '상', round: '1',
    sortOrder: 7, sourceOrder: 701, sourceFiles: failSourceFiles, answerKeys: { '1': ['1'] },
  };
  const failB = {
    id: 'fail-b', name: '롤백 B', curriculum: '공수1', difficulty: '상', round: '2',
    sourceOrder: 8, futureShape: { preserve: true },
  };
  const failC = {
    id: 'fail-c', name: '롤백 C', curriculum: '공수1', difficulty: '상', round: '3',
    sortOrder: undefined, sourceOrder: 9,
  };
  TEST_CFG = { categories: { REVIEW: { label: '복습 테스트', tests: [failC, failA, failB] } } };
  ui.category = 'REVIEW';
  ui.difficulty = '상';
  ui.term = '';
  ui.round = '';
  ui.catalogSearch = '';
  const beforeFailure = TEST_CFG.categories.REVIEW.tests.slice();
  const beforeSortState = beforeFailure.map(test => ({
    test,
    had: Object.prototype.hasOwnProperty.call(test, 'sortOrder'),
    value: test.sortOrder,
  }));
  setFetchMode('failure');
  const failed = await persistCatalogReorder(1, 2, 'after', 'down');
  check(failed === false, 'failed save was reported as successful');
  sameArrayIdentity(TEST_CFG.categories.REVIEW.tests, beforeFailure, 'failed save did not restore the exact raw array order');
  beforeSortState.forEach(state => {
    check(Object.prototype.hasOwnProperty.call(state.test, 'sortOrder') === state.had, 'failed save changed sortOrder property presence');
    check(state.test.sortOrder === state.value, 'failed save changed the prior sortOrder value');
  });
  check(failA.sourceOrder === 701, 'rollback changed sourceOrder provenance');
  check(failA.sourceFiles === failSourceFiles, 'rollback changed sourceFiles identity');
  check(failB.futureShape.preserve === true, 'rollback dropped an unknown key');
  check(catalogOrderFeedback?.kind === 'error', 'failed save did not expose rollback feedback');

  const conflictA = { id: 'conflict-a', name: '충돌 A', curriculum: '공수1', difficulty: '상', round: '1', sortOrder: 0 };
  const conflictB = { id: 'conflict-b', name: '충돌 B', curriculum: '공수1', difficulty: '상', round: '2', sortOrder: 1 };
  TEST_CFG = { categories: { REVIEW: { label: '복습 테스트', tests: [conflictA, conflictB] } } };
  ui.category = 'REVIEW';
  ui.difficulty = '상';
  setFetchMode('conflict');
  const conflicted = await persistCatalogReorder(0, 1, 'after');
  check(conflicted === false, '409 conflict was reported as a successful reorder');
  check(TEST_CFG.serverRevision === 'latest-after-conflict', '409 did not retain the reloaded server config');
  check(TEST_CFG.categories.REVIEW.tests[0].id === 'server-latest', 'stale rollback overwrote the 409 server config');
  check(TEST_CFG_REVISION === 'c'.repeat(64), '409 reload did not retain the latest server revision');
  check(/최신 목록/.test(catalogOrderFeedback?.message || ''), '409 did not expose conflict-specific feedback');

  const configBeforeStatsOnly = TEST_CFG;
  setFetchMode('success');
  await loadStatsOnly();
  check(TEST_CFG === configBeforeStatsOnly, 'stats-only refresh replaced the catalog config');

  setFetchMode('success');
  TEST_CFG = { categories: { REVIEW: { label: '복습 테스트', tests: [one, two, three] } } };
  ui.category = 'REVIEW';
  ui.difficulty = '상';
  const fetchCountBeforeRuleGuard = fetchCalls.length;
  ruleSaveTimer = 123;
  const blockedByRuleTimer = await persistCatalogReorder(0, 1, 'after');
  check(blockedByRuleTimer === false && fetchCalls.length === fetchCountBeforeRuleGuard, 'pending rule save did not block reorder');
  ruleSaveTimer = null;
  catalogOrderSaveInFlight = true;
  scheduleRulesAutosave();
  check(ruleSavePending === true && ruleSaveTimer === null, 'rule autosave was not deferred during reorder');
  syncCatalogMutationControls();
  check(document.querySelector('#btnNewTest').disabled === true, 'catalog mutation buttons were not locked during reorder');
  catalogOrderSaveInFlight = false;
  ruleSavePending = false;
  syncCatalogMutationControls();
  check(document.querySelector('#btnNewTest').disabled === false, 'catalog mutation buttons were not restored after reorder');

  ruleSaveTimer = 456;
  const mutationBlockedByRuleTimer = beginCatalogMutationSave();
  check(mutationBlockedByRuleTimer === false, 'pending rule timer did not block a catalog mutation save');
  ruleSaveTimer = null;
  const mutationStarted = beginCatalogMutationSave();
  check(mutationStarted === true, 'catalog mutation save did not start after rule save cleared');
  check(catalogMutationSaveInFlight === true, 'catalog mutation in-flight state was not recorded');
  check(document.querySelector('#btnNewTest').disabled === true, 'catalog mutation did not immediately lock New');
  check(document.querySelector('#btnSaveTest').disabled === true, 'catalog mutation did not immediately lock Save');
  check(document.querySelector('#cfgName').disabled === true, 'catalog mutation did not immediately lock editor inputs');
  check(beginCatalogMutationSave() === false, 'overlapping catalog mutation save was allowed');
  scheduleRulesAutosave();
  check(ruleSavePending === true && ruleSaveTimer === null, 'rule autosave was not deferred during catalog mutation');
  ruleSavePending = false;
  endCatalogMutationSave();
  check(catalogMutationSaveInFlight === false, 'catalog mutation in-flight state was not cleared');
  check(document.querySelector('#btnNewTest').disabled === false, 'catalog controls were not restored after mutation save');

  TEST_CFG = {
    categories: {
      UNIT: {
        label: '단원평가',
        tests: [{ id: 'rollback-test', name: '서버 값', unknownMetadata: { preserve: true } }],
      },
    },
  };
  TEST_CFG_REVISION = 'd'.repeat(64);
  ui.category = 'UNIT';
  ui.subject = '공수1';
  ui.difficulty = 'Lv.3';
  ui.selectedId = 'rollback-test';
  const mutationSnapshot = captureTestCatalogMutationSnapshot();
  TEST_CFG.categories.UNIT.tests[0].name = '저장 실패 초안';
  TEST_CFG.categories.UNIT.tests.push({ id: 'unsaved-new', name: '미저장 신규' });
  TEST_CFG_REVISION = 'e'.repeat(64);
  ui.selectedId = 'unsaved-new';
  restoreTestCatalogMutationSnapshot(mutationSnapshot);
  check(TEST_CFG.categories.UNIT.tests.length === 1, 'single-test failure snapshot kept an unsaved record');
  check(TEST_CFG.categories.UNIT.tests[0].name === '서버 값', 'single-test failure snapshot kept an unsaved edit');
  check(TEST_CFG.categories.UNIT.tests[0].unknownMetadata.preserve === true, 'single-test rollback dropped unknown metadata');
  check(TEST_CFG_REVISION === 'd'.repeat(64), 'single-test rollback did not restore the base revision');
  check(ui.selectedId === 'rollback-test', 'single-test rollback did not restore the prior selection');

  setFetchMode('success');
  await saveTestDefinition(
    { id: 'patch-check', name: '분류 이동' },
    'UNIT',
    '단원평가',
    ['term', 'examTerm'],
  );
  const definitionPatch = fetchCalls.at(-1);
  check(definitionPatch.method === 'PATCH', 'single-test save did not use PATCH');
  check(
    definitionPatch.body?.clearFields?.join('|') === 'term|examTerm',
    'single-test save omitted explicit term clears',
  );

  const compoundAnswers = ['1', '-1/7', 'M = 44, m = 3', '(9/7, 50/7)'];
  const compoundModes = ['choice_number', 'answer_value', 'answer_value', 'answer_value'];
  const compound = {
    id: 'ilsan-compound', name: '서술형 보존', curriculum: '공수2', difficulty: '상',
    term: '중간고사', round: '1', problems: 4, answerKey: compoundAnswers.slice(),
    answerKeys: { '1': compoundAnswers.slice() }, answerModes: { '1': compoundModes.slice() },
    sourceFiles: { solutionFileId: 'synthetic-solution', futureMetadata: 'preserve' },
  };
  TEST_CFG = ensureConfig({ categories: { ILSAN_PAST: { label: '일산 기출', tests: [compound] } } });
  ui.category = 'ILSAN_PAST'; ui.subject = '공수2'; ui.difficulty = '상';
  ui.term = '중간고사'; ui.selectedId = compound.id;
  document.querySelectorAll = selector => selector === '#cfgAnswerModes select[data-question-no]'
    ? compoundModes.map(value => ({ value })) : [];
  bindUI();
  fillEditor();
  check(JSON.stringify(JSON.parse($('#cfgAnswers').value)) === JSON.stringify(compoundAnswers), 'editor split a compound answer on load');
  $('#cfgName').value = '이름만 변경';
  await $('#btnSaveTest').handlers.click();
  const compoundPatch = fetchCalls.at(-1);
  check(compoundPatch.method === 'PATCH' && compoundPatch.body.test.id === compound.id, 'editor did not save the selected synthetic test');
  check(compoundPatch.body.test.difficulty === '상', 'editor collapsed high difficulty');
  check(JSON.stringify(compoundPatch.body.test.answerKey) === JSON.stringify(compoundAnswers), 'rename/save changed compound answers');
  check(compoundPatch.body.test.sourceFiles.futureMetadata === 'preserve', 'rename/save dropped source metadata');
  const writesBeforeInvalid = fetchCalls.length;
  $('#cfgAnswers').value = '["1",';
  await $('#btnSaveTest').handlers.click();
  check(fetchCalls.length === writesBeforeInvalid, 'invalid answer JSON reached transport');
  check($('#testSaveStatus').textContent.includes('JSON 배열'), 'invalid answer JSON did not show editor feedback');

  return {
    successfulPosts: fetchCalls.filter(call => call.method === 'POST').length - 1,
    rollbackVerified: true,
    searchAndScopeGuardsVerified: true,
    rawMetadataVerified: true,
    compoundAnswerEditorRoundTripVerified: true,
  };
})();
`, context, { filename: 'verify_test_catalog_search_and_sort.scenario.js' });

const result = await context.window.__catalogSortScenario;

assert.match(testsHtml, /<label class="toolbar-label" for="cfgCatalogSearch">목록 검색<\/label>/);
assert.match(testsHtml, /id="cfgCatalogSearch"[^>]*type="search"/);
assert.match(testsHtml, /id="catalogOrderHint"[^>]*role="status"[^>]*aria-live="polite"/);
assert.match(testsHtml, /id="testSaveStatus"[^>]*role="status"[^>]*aria-live="polite"/);
assert.match(testsHtml, /id="statSearch"[^>]*type="search"/);
assert.match(testsHtml, /<script src="\/js\/tests\.js\?v=20260907-ilsan-level-r1&hub=20261001-detail1" type="module"><\/script>/);
assert.doesNotMatch(testsHtml, /sortable(?:\.min)?\.js|jquery-ui/i);
assert.match(source, /\.test-drag-handle\[draggable="true"\]/);
assert.match(source, /data-move="up"/);
assert.match(source, /data-move="down"/);
assert.match(source, /await saveConfig\(\);/);
assert.match(source, /const clearFields = term \? \[\] : \['term', 'examTerm'\];/);
assert.match(source, /await saveTestDefinition\([\s\S]*clearFields,[\s\S]*\);/);
assert.match(source, /restoreTestCatalogMutationSnapshot\(catalogSnapshot\);/);
assert.match(source, /await loadConfigAndStats\(\);[\s\S]*목록 변경 감지/);
assert.match(source, /setTestSaveStatus\('success', `저장 완료 · \$\{testSaveClock\(\)\}`\)/);
assert.match(source, /wholeConfigWriteRequest\(TEST_CFG, TEST_CFG_REVISION, removedTestIds\)/);
assert.match(source, /testDefinitionWriteRequest\([\s\S]*TEST_CFG_REVISION,[\s\S]*\)/);
assert.match(source, /if \(res\.status === 409 \|\| res\.status === 428\) await loadConfigAndStats\(\);/);
assert.match(source, /if \(catalogOrderSaveInFlight \|\| catalogMutationSaveInFlight\) \{\s*ruleSavePending = true;/);
assert.match(source, /const locked = catalogOrderSaveInFlight \|\| catalogMutationSaveInFlight;/);
assert.match(source, /'#btnReloadStats', '#statRecent',/);
assert.match(source, /#btnReloadStats'[\s\S]*catalogMutationControlsLocked\(\)/);
assert.match(source, /#btnReloadStats'[\s\S]*loadStatsOnly\(\)/);
assert.doesNotMatch(source, /#btnReloadStats'[\s\S]{0,220}loadConfigAndStats\(\)/);
assert.match(source, /if \(ruleSaveTimer \|\| ruleSaveInFlight \|\| ruleSavePending\)/);
assert.match(source, /'#btnImportCsv', '#csvFile', '#btnNewTest', '#btnSaveTest', '#btnDeleteTest'/);
assert.match(source, /restoreCatalogOrder\(cat, snapshot\)/);
const newTestStart = source.indexOf("$('#btnNewTest')?.addEventListener");
const saveTestStart = source.indexOf("$('#btnSaveTest')?.addEventListener", newTestStart);
const newTestHandler = newTestStart >= 0 && saveTestStart > newTestStart
  ? source.slice(newTestStart, saveTestStart)
  : '';
assert.ok(newTestHandler, 'new-test handler was not found');
assert.doesNotMatch(newTestHandler, /cat\.tests\.push\(/);
const editorSubjectStart = source.indexOf("$('#cfgSubject')?.addEventListener");
assert.equal(editorSubjectStart, -1, 'editor subject changes mutate the catalog before Save');

console.log(JSON.stringify({ ok: true, ...result }, null, 2));
