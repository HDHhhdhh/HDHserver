const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const CATALOG_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogState.js');
const CATALOG_EDITOR_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogEditorState.js');
const CATALOG_STATISTICS_STATE_PATH = path.join(ROOT, 'static', 'js', 'tests', 'catalogStatisticsState.js');
const catalogStateSource = fs.readFileSync(CATALOG_STATE_PATH, 'utf8').replace(/^export\s+/gm, '');
const catalogEditorStateSource = fs.readFileSync(CATALOG_EDITOR_STATE_PATH, 'utf8').replace(/^export\s+/gm, '');
const catalogStatisticsStateSource = fs.readFileSync(CATALOG_STATISTICS_STATE_PATH, 'utf8')
  .replace(/import\s+\{[\s\S]*?\}\s+from\s+['"]\.\/catalogState\.js(?:\?[^'"]*)?['"];\s*/, '')
  .replace(/^export\s+/gm, '');
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

async function verifyDetailRequestRaces() {
  const deferred = [];
  context.fetch = url => new Promise((resolve, reject) => deferred.push({ url, resolve, reject }));
  context.console = { ...console, error() {} };
  const select = id => vm.runInContext(`
    TEST_CFG = { categories: { UNIT: { tests: [
      {id:'race-a', name:'Detail A', categoryKey:'UNIT'},
      {id:'race-b', name:'Detail B', categoryKey:'UNIT'}
    ]}}};
    ui.statsCategory='UNIT'; ui.statsTestId='${id}';
    renderStatsDetail(TEST_CFG.categories.UNIT.tests.find(t=>t.id===ui.statsTestId), true);
  `, context);
  const settle = async () => { await new Promise(resolve => setImmediate(resolve)); };
  const resolve = (index, studentName) => deferred[index].resolve({
    ok:true, text:async()=>JSON.stringify({records:[{studentName,correct:1,total:1,pct:100}]}),
  });
  const html = () => getElement('statsDetailModalBody').innerHTML;
  select('race-a');
  if (!html().includes('role="status"')) throw new Error('Loading feedback is missing');
  select('race-b');
  if (deferred.length !== 2 || !deferred[0].url.includes('race-a') || !deferred[1].url.includes('race-b')) {
    throw new Error('Actual selected test requests were not observed');
  }
  resolve(1,'Current B record'); await settle();
  const current = html();
  if (!current.includes('Current B record') || !current.includes('Detail B')) throw new Error('Current detail did not render');
  resolve(0,'Stale A record'); await settle();
  if (html() !== current) throw new Error('Stale request overwrote the current detail');
  select('race-a');
  vm.runInContext('closeStatsDetailModal()',context);
  const closed = html();
  resolve(2,'Closed response'); await settle();
  if (html() !== closed) throw new Error('A response updated a closed modal');
  select('race-b');
  deferred[3].reject(new Error('injected read failure')); await settle();
  if (!html().includes('role="alert"') || !html().includes('불러오지 못했습니다')) throw new Error('Current failure feedback is missing');
  console.log('statistics detail async checks passed: out-of-order requests, close invalidation, loading and failure feedback');
}
verifyDetailRequestRaces().catch(err => { console.error(err); process.exitCode = 1; });
