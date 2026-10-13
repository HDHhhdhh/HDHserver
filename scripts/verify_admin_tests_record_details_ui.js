const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const TESTS_JS_PATH = path.join(ROOT, 'static', 'js', 'tests.js');
const CATALOG_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogState.js');
const CATALOG_EDITOR_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogEditorState.js');
const CATALOG_STATISTICS_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogStatisticsState.js');
const TESTS_HTML_PATH = path.join(ROOT, 'static', 'tests.html');
const TESTS_CSS_PATH = path.join(ROOT, 'static', 'css', 'tests.css');
const catalogStateSource = fs.readFileSync(CATALOG_STATE_PATH, 'utf8').replace(/^export\s+/gm, '');
const catalogEditorStateSource = fs.readFileSync(CATALOG_EDITOR_STATE_PATH, 'utf8').replace(/^export\s+/gm, '');
const catalogStatisticsStateSource = fs.readFileSync(CATALOG_STATISTICS_STATE_PATH, 'utf8')
  .replace(/import\s+\{[\s\S]*?\}\s+from\s+['"]\.\/catalogState\.js(?:\?[^'"]*)?['"];\s*/, '')
  .replace(/^export\s+/gm, '');
const source = fs
  .readFileSync(TESTS_JS_PATH, 'utf8')
  .replace(/import\s+\{[^}]+\}\s+from\s+['"]\.\/shared\/search\.js['"];\s*/, `
function applySearchPlaceholder() {}
function matchesSearchKey() { return true; }
function searchKeyForText(value) { return String(Array.isArray(value) ? value.join(' ') : value || ''); }
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
const testsHtml = fs.readFileSync(TESTS_HTML_PATH, 'utf8');
const testsCss = fs.readFileSync(TESTS_CSS_PATH, 'utf8');

class ElementStub {
  constructor(id = '') {
    this.id = id;
    this.hidden = false;
    this.value = '';
    this.innerHTML = '';
    this.textContent = '';
    this.style = {};
    this.dataset = {};
    this.classList = { add() {}, remove() {} };
  }

  setAttribute(name, value) {
    this[name] = String(value);
  }

  addEventListener() {}

  querySelectorAll() {
    return [];
  }

  querySelector() {
    return null;
  }
}

function createDocument() {
  const elements = new Map();
  const getElement = id => {
    if (!elements.has(id)) elements.set(id, new ElementStub(id));
    return elements.get(id);
  };
  ['statsDetailModalBody', 'statsDetail', 'statRecent'].forEach(getElement);
  getElement('statRecent').value = '3650';
  return {
    body: new ElementStub('body'),
    querySelector(selector) {
      if (String(selector).startsWith('#')) return getElement(String(selector).slice(1));
      return null;
    },
    addEventListener() {},
    createElement: () => new ElementStub(),
    getElementById: getElement,
  };
}

function assertIncludes(haystack, needle) {
  if (!haystack.includes(needle)) {
    throw new Error(`missing rendered HTML: ${needle}`);
  }
}

function assertExcludes(haystack, needle) {
  if (haystack.includes(needle)) {
    throw new Error(`unsafe rendered HTML: ${needle}`);
  }
}

function assertCssIncludes(needle) {
  if (!testsCss.includes(needle)) {
    throw new Error(`missing CSS contract: ${needle}`);
  }
}

function countMatches(text, pattern) {
  return (text.match(pattern) || []).length;
}

const document = createDocument();
const fetchCalls = [];
const context = {
  document,
  window: { addEventListener() {} },
  console,
  fetch: async url => {
    fetchCalls.push(String(url || ''));
    return { ok: true, text: async () => '{}', json: async () => ({}) };
  },
  alert: message => {
    throw new Error(`unexpected alert: ${message}`);
  },
  Date,
  Math,
  Number,
  String,
  Array,
  Object,
  RegExp,
  JSON,
  URLSearchParams,
  setTimeout,
  clearTimeout,
};
context.window.window = context.window;
context.window.document = document;

const scenario = `
TEST_CFG = {
  categories: {
    UNIT: {
      tests: [{
        id: 'admin-ui-detail-test',
        name: 'Admin UI Detail Test',
        categoryKey: 'UNIT',
        curriculum: 'QA',
        difficulty: 'Lv.3',
        round: '1',
        problems: 4
      }]
    }
  }
};
TEST_STATS = {
  by_test_id: {
    'admin-ui-detail-test': {
      count: 2,
      avg_pct: 75,
      stddev_pct: 5,
      median_pct: 75,
      max_pct: 100,
      min_pct: 50
    }
  }
};
TEST_STATS_DETAIL = {
  answerUrl: 'https://example.test/answer?x=1&y=2',
  records: [
    {
      sid: 'qa001',
      studentName: 'QA Student',
      level: '중',
      pct: 50,
      correct: 2,
      total: 4,
      wrong: [1, 2],
      wrongDetails: [
        { questionNo: 1, myAnswer: '<script>alert(1)</script>', correctAnswer: '5&6' },
        { questionNo: 2, myAnswer: '2', correctAnswer: '4' }
      ],
      createdAt: '2026-07-03T00:00:00Z',
      testId: 'admin-ui-detail-test'
    },
    {
      sid: 'qa002',
      studentName: 'No Detail Student',
      level: '',
      pct: 100,
      correct: 4,
      total: 4,
      wrong: [],
      wrongDetails: [],
      createdAt: '2026-07-03T01:00:00Z',
      testId: 'admin-ui-detail-test'
    },
    {
      sid: 'qa003',
      studentName: 'Legacy Student',
      level: '상',
      pct: 75,
      correct: 3,
      total: 4,
      wrong: [3],
      createdAt: '2026-07-03T02:00:00Z',
      testId: 'admin-ui-detail-test'
    }
  ]
};
ui.statsCategory = 'UNIT';
ui.statsTestId = 'admin-ui-detail-test';
renderStatsDetail(TEST_CFG.categories.UNIT.tests[0], false);
`;

vm.createContext(context);
vm.runInContext(`${source}\n${scenario}`, context, { filename: 'static/js/tests.js' });

const html = document.getElementById('statsDetailModalBody').innerHTML;
assertIncludes(html, 'Admin UI Detail Test');
assertIncludes(html, 'QA Student');
assertIncludes(html, 'No Detail Student');
assertIncludes(html, 'Legacy Student');
assertIncludes(html, '2 / 4');
assertIncludes(html, '4 / 4');
assertIncludes(html, '3 / 4');
assertIncludes(html, '틀린 문항 1, 2');
assertIncludes(html, '틀린 문항 없음');
assertIncludes(html, '틀린 문항 3');
assertIncludes(html, '이전 제출 기록이라 내 답 비교가 없습니다.');
assertIncludes(html, '전체 답지 보기');
assertIncludes(html, '<th>채점 결과</th>');
assertIncludes(html, 'class="wrong-detail-list"');
assertIncludes(html, '<summary>틀린 문항 내 답/정답 비교</summary>');
assertIncludes(html, '<span class="wrong-detail-no">1번</span>');
assertIncludes(html, '<span class="wrong-detail-label">내 답</span>');
assertIncludes(html, '<strong>&lt;script&gt;alert(1)&lt;/script&gt;</strong>');
assertIncludes(html, '<span class="wrong-detail-label">정답</span>');
assertIncludes(html, '<strong>5&amp;6</strong>');
assertIncludes(html, '<span class="wrong-detail-no">2번</span>');
assertIncludes(html, '<strong>2</strong>');
assertIncludes(html, '<strong>4</strong>');
assertIncludes(html, 'href="https://example.test/answer?x=1&amp;y=2"');
assertIncludes(html, 'target="_blank"');
assertIncludes(html, 'rel="noopener noreferrer"');
assertExcludes(html, '<script>alert(1)</script>');

[
  'body.admin.tests-page .wrong-detail-list {',
  'min-width: 0;',
  'flex-wrap: wrap;',
  'word-break: keep-all;',
  'grid-template-columns: auto minmax(0, 1fr);',
  'white-space: nowrap;',
  '@media (max-width: 640px) {',
  'body.admin.tests-page .stats-detail-modal {',
  'width: calc(100vw - 24px);',
  'body.admin.tests-page .detail-metrics {',
  'grid-template-columns: 1fr 1fr;',
  'body.admin.tests-page .panel-table-wrap {',
  'overflow: hidden;',
  'body.admin.tests-page .detail-student-table td {',
  'grid-template-columns: 64px minmax(0, 1fr);',
  'content: "채점 결과";',
].forEach(assertCssIncludes);

if (countMatches(html, /class="wrong-detail-list"/g) !== 1) {
  throw new Error('wrong detail list should render only for records with details');
}
if (fetchCalls.some(url => url.includes('/api/submit-test'))) {
  throw new Error('/api/submit-test was called');
}

console.log(JSON.stringify({
  ok: true,
  wrongDetailLists: 1,
  submitTestCalls: 0,
  escapedStudentAnswer: true,
  answerLinkEscaped: true,
  mobileCssContract: true,
}, null, 2));
