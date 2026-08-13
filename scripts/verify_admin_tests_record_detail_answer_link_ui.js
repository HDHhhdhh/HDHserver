const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const source = fs
  .readFileSync(path.join(ROOT, 'static', 'js', 'tests.js'), 'utf8')
  .replace(/import\s+\{[^}]+\}\s+from\s+['"]\.\/shared\/search\.js['"];\s*/, `
function applySearchPlaceholder() {}
function matchesSearchKey() { return true; }
function searchKeyForText(value) { return String(Array.isArray(value) ? value.join(' ') : value || ''); }
`)
  .replace(
    /import\s+\{\s*createUnitTestDisplayNameResolver\s*\}\s+from\s+['"]\.\/shared\/testCatalogDisplay\.js['"];\s*/,
    "const createUnitTestDisplayNameResolver = () => (test) => String(test?.name || '');\n",
  );

class ElementStub {
  constructor(id = '') {
    this.id = id;
    this.value = '';
    this.innerHTML = '';
    this.hidden = false;
    this.style = {};
    this.dataset = {};
    this.classList = { add() {}, remove() {} };
  }

  addEventListener() {}
  setAttribute(name, value) { this[name] = String(value); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

const elements = new Map();
const getElement = id => {
  if (!elements.has(id)) elements.set(id, new ElementStub(id));
  return elements.get(id);
};
getElement('statRecent').value = '3650';

const document = {
  body: new ElementStub('body'),
  addEventListener() {},
  createElement: () => new ElementStub(),
  getElementById: getElement,
  querySelector(selector) {
    if (String(selector).startsWith('#')) return getElement(String(selector).slice(1));
    return null;
  },
};

const context = {
  document,
  window: { addEventListener() {} },
  console,
  fetch: async () => ({ ok: true, json: async () => ({}), text: async () => '{}' }),
  alert: message => { throw new Error(`unexpected alert: ${message}`); },
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
TEST_CFG = { categories: { UNIT: { tests: [{
  id: 'admin-ui-detail-test',
  name: 'Admin UI Detail Test',
  categoryKey: 'UNIT',
  round: '1',
  problems: 4
}] } } };
TEST_STATS = { by_test_id: { 'admin-ui-detail-test': { count: 1, avg_pct: 100 } } };
window.TEST_ANSWER_LINK_MAP = {
  'admin-ui-detail-test': { '1': { answerUrl: 'https://map.example/should-not-render' } }
};
ui.statsCategory = 'UNIT';
ui.statsTestId = 'admin-ui-detail-test';
TEST_STATS_DETAIL = { answerUrl: '', records: [] };
renderStatsDetail(TEST_CFG.categories.UNIT.tests[0], false);
`;

vm.createContext(context);
vm.runInContext(`${source}\n${scenario}`, context, { filename: 'static/js/tests.js' });

const restrictedHtml = document.getElementById('statsDetailModalBody').innerHTML;
if (restrictedHtml.includes('https://map.example/should-not-render') || restrictedHtml.includes('detail-answer-link')) {
  throw new Error('admin detail answerUrl fallback rendered while API answerUrl was hidden');
}

vm.runInContext(`
TEST_STATS_DETAIL = { answerUrl: 'https://api.example/answer?from=detail&x=1', records: [] };
renderStatsDetail(TEST_CFG.categories.UNIT.tests[0], false);
`, context, { filename: 'static/js/tests.js' });

const allowedHtml = document.getElementById('statsDetailModalBody').innerHTML;
if (!allowedHtml.includes('href="https://api.example/answer?from=detail&amp;x=1"')) {
  throw new Error('admin detail API answerUrl was not rendered');
}
if (allowedHtml.includes('https://map.example/should-not-render')) {
  throw new Error('admin detail answerUrl fell back to static map instead of API payload');
}

console.log(JSON.stringify({
  ok: true,
  restrictedDetailAnswerUrlFallbackHidden: true,
  apiDetailAnswerUrlWins: true,
}, null, 2));
