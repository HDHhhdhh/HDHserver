import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const plain = x => JSON.parse(JSON.stringify(x));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const unescape = s => String(s || '').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const existing = read('scripts/verify_test_catalog_search_and_sort.mjs');
const base = existing.slice(existing.indexOf('class ElementStub {'), existing.indexOf('const elements = new Map();'));
const ElementStub = vm.runInNewContext(base + '\nElementStub;');

class Element extends ElementStub {
  constructor(id = '') {
    super(id);
    this.attrs = {};
    this.children = [];
    this.writes = 0;
    this.classes = new Set();
    this.classList = {
      add: (...xs) => xs.forEach(x => this.classes.add(x)),
      remove: (...xs) => xs.forEach(x => this.classes.delete(x)),
      contains: x => this.classes.has(x),
      toggle: (x, on) => {
        const next = on === undefined ? !this.classes.has(x) : on;
        next ? this.classes.add(x) : this.classes.delete(x);
        return next;
      },
    };
    let html = '';
    Object.defineProperty(this, 'innerHTML', {
      get: () => html,
      set: value => {
        html = String(value);
        this.writes++;
        this.children = [];
        for (const m of html.matchAll(/<(button|select|tr)\b([^>]*)>([\s\S]*?)<\/\1>/g)) {
          const child = new Element();
          child.parent = this;
          child.textContent = unescape(m[3].replace(/<[^>]*>/g, ''));
          child.parseAttrs(m[2]);
          if (m[1] === 'select') child.innerHTML = m[3];
          this.children.push(child);
        }
        if (html.includes('<option')) {
          const options = [...html.matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)];
          this.value = unescape(options.find(m => /\bselected\b/.test(m[1]))?.[1].match(/value="([^"]*)"/)?.[1] || options[0]?.[1].match(/value="([^"]*)"/)?.[1] || '');
        }
      },
    });
  }
  parseAttrs(s) {
    for (const m of s.matchAll(/([a-zA-Z][\w-]*)(?:="([^"]*)")?/g)) {
      this.attrs[m[1]] = unescape(m[2] || '');
      if (m[1] === 'class') this.classes = new Set(this.attrs.class.split(/\s+/).filter(Boolean));
      if (m[1] === 'disabled') this.disabled = true;
      if (m[1].startsWith('data-')) this.dataset[m[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = unescape(m[2]);
      if (m[1] === 'id') this.id = m[2];
    }
  }
  matches(sel) {
    return String(sel).split(',').some(s => {
      s = s.trim();
      const id = /^#([\w-]+)$/.exec(s);
      if (id) return id[1] === this.id;
      const cls = /\.([\w-]+)/.exec(s);
      if (cls && !this.classes.has(cls[1])) return false;
      for (const m of s.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)) {
        if (!Object.hasOwn(this.attrs, m[1])) return false;
        if (m[2] !== undefined && this.attrs[m[1]] !== m[2]) return false;
      }
      return true;
    });
  }
  querySelectorAll(sel) { return this.children.filter(c => c.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  closest(sel) { return this.matches(sel) ? this : this.parent?.closest(sel) || null; }
  click() { if (!this.disabled) return this.handlers.click?.({ target: this, preventDefault() {}, stopPropagation() {} }); }
}

function harness() {
  const ids = new Map();
  const get = id => { if (!ids.has(id)) ids.set(id, new Element(id)); return ids.get(id); };
  for (const m of read('static/tests.html').matchAll(/\bid="([^"]+)"/g)) get(m[1]);
  get('statRecent').value = '30';
  const document = {
    body: new Element('body'), createElement: () => new Element(), addEventListener() {},
    querySelector: s => s === '#statsTable tbody' ? get('statsTbody') : s === '.editor-panel' ? get('editorPanel') : /^#[\w-]+$/.test(s) ? get(s.slice(1)) : s.startsWith('#testList ') ? get('testList').querySelector(s.slice(10)) : null,
    querySelectorAll: s => s === '#cfgAnswerModes select[data-question-no]' ? get('cfgAnswerModes').children : s.startsWith('#testList ') ? get('testList').querySelectorAll(s.slice(10)) : s === 'button.test-select-button[data-id]' ? get('testList').querySelectorAll(s) : [],
  };
  const window = new Element('window');
  const requests = [], writes = [], pendingReads = [];
  const config = { rootUnknown: { keep: true }, categories: { UNIT: { tests: [
    { id: 'a', name: '알파', curriculum: '공수1', difficulty: 'Lv.3', round: '1', problems: 1, sortOrder: 2, answerKey: ['1'], answerKeys: { '1': ['1'], '2': ['2'], '9': ['기존'] }, answerModes: { '1': ['choice_number'], '2': ['choice_number'], '9': ['answer_value'] }, sourceFiles: { solutionFileId: 'qa-a', unknown: 3 }, unknown: { keep: true } },
    { id: 7, name: '베타', curriculum: '공수1', difficulty: 'Lv.3', round: '1', problems: 1, sortOrder: 1, answerKey: ['2'], answerKeys: { '1': ['2'] }, answerModes: { '1': ['choice_number'] } },
  ] } } };
  const response = (data, status = 200) => ({ ok: status < 400, status, headers: { get: n => n.toLowerCase() === 'x-tests-config-revision' ? 'b'.repeat(64) : '' }, text: async () => JSON.stringify(data), json: async () => plain(data) });
  const context = vm.createContext({ document, window, console: { ...console, error() {} }, URLSearchParams, URL, Blob,
    alert() {}, confirm: () => true, requestAnimationFrame: fn => fn(), clearTimeout() {},
    setTimeout: (fn, delay) => { if (delay === 0) queueMicrotask(fn); return 1; },
    fetch: (url, init = {}) => {
      const request = { url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null };
      requests.push(request);
      if (request.method !== 'GET') { const d = deferred(); writes.push({ ...request, ...d }); return d.promise; }
      if (request.url === '/api/tests-config') return Promise.resolve(response(config));
      const d = deferred(); pendingReads.push(d); return d.promise;
    },
  });
  function load(file, deps = {}) {
    let source = read(file);
    const names = [...source.matchAll(/^export (?:const|function|class) (\w+)/gm)].map(m => m[1]);
    context.deps = deps;
    source = source.replace(/import\s+\{([\s\S]*?)\}\s+from\s+['"]([^'"]+)['"];\s*/g, (_, fields, ref) => 'const {' + fields + '}=deps[' + JSON.stringify(ref.split('?')[0]) + '];\n');
    return vm.runInContext('(function(deps){' + source.replace(/^export\s+/gm, '') + '\nreturn {' + names.join(',') + '};})(deps)', context);
  }
  const state = load('static/js/tests/catalogState.js');
  context.modules = {
    './tests/catalogState.js': state, './shared/search.js': load('static/js/shared/search.js'),
    './shared/testCatalogDisplay.js': load('static/js/shared/testCatalogDisplay.js'),
    './tests/catalogEditorState.js': load('static/js/tests/catalogEditorState.js'),
    './tests/catalogStatisticsState.js': load('static/js/tests/catalogStatisticsState.js', { './catalogState.js': state }),
  };
  const sourceIndex = process.argv.indexOf('--source');
  const actualSource = sourceIndex === -1 ? read('static/js/tests.js') : fs.readFileSync(process.argv[sourceIndex + 1], 'utf8');
  const source = actualSource.replace(/import\s+\{([\s\S]*?)\}\s+from\s+['"]([^'"]+)['"];\s*/g, (_, fields, ref) => 'const {' + fields + '}=modules[' + JSON.stringify(ref.split('?')[0]) + '];\n');
  vm.runInContext(source, context, { filename: 'actual-tests.js' });
  const buttons = () => get('testList').children.filter(b => b.classes.has('test-select-button'));
  return { get, requests, writes, pendingReads, response, buttons,
    start: async () => { window.handlers.DOMContentLoaded(); await tick(); },
    click: id => buttons().find(b => b.dataset.id === String(id)).click(),
    active: () => buttons().filter(b => b.classes.has('active')).map(b => b.dataset.id),
  };
}

if (!process.argv.includes('--only-save') && !process.argv.includes('--only-csv')) {
  const h = harness(); await h.start(); await h.click('a');
  const nodes = h.buttons(), htmlWrites = h.get('testList').writes;
  await h.click(7); assert.deepEqual(h.active(), ['7']); assert.equal(h.get('cfgName').value, '베타');
  assert.equal(h.get('testList').writes, htmlWrites); h.buttons().forEach((b, i) => assert.equal(b, nodes[i]));
  assert.equal(h.requests.length, 2);
}
if (!process.argv.includes('--only-csv')) {
  const h = harness(); await h.start(); await h.click('a'); h.get('cfgName').value = 'A 수정';
  const queuedB = h.buttons().find(b => b.dataset.id === '7');
  const saving = h.get('btnSaveTest').handlers.click(); await tick();
  assert.equal(h.writes.length, 1); assert.equal(h.writes[0].body.test.name, 'A 수정');
  await h.click(7); queuedB.handlers.click({ target: queuedB });
  assert.deepEqual(h.active(), ['a']); assert.equal(h.get('cfgName').value, 'A 수정'); assert.equal(queuedB.disabled, true);
  h.writes[0].resolve(h.response({}, 500)); await saving; await tick();
  assert.deepEqual(h.active(), ['a']); assert.equal(h.get('cfgName').value, 'A 수정');
  assert.equal(h.get('editorSelectionLabel').textContent, '2. 알파');
  const retry = h.get('btnSaveTest').handlers.click(); await tick();
  const payload = h.writes[1].body.test;
  assert.equal(payload.id, 'a'); assert.equal(payload.name, 'A 수정'); assert.deepEqual(payload.answerKey, ['1']);
  assert.deepEqual(payload.answerKeys, { '1': ['1'], '2': ['2'], '9': ['기존'] }); assert.deepEqual(payload.unknown, { keep: true });
  assert.deepEqual(payload.sourceFiles, { solutionFileId: 'qa-a', unknown: 3 });
  h.writes[1].resolve(h.response({ test: payload })); await retry; await tick();
  await h.click(7); assert.deepEqual(h.active(), ['7']); assert.equal(h.get('cfgName').value, '베타');
}
if (!process.argv.includes('--only-csv')) {
  const h = harness(); await h.start(); await h.click('a');
  const order = h.get('testList').children.find(b => b.classes.has('test-order-button') && b.dataset.move === 'down' && b.dataset.catalogIndex === '1');
  order.click(); await tick(); assert.equal(h.writes.length, 1); assert.equal(h.writes[0].method, 'POST');
  assert.deepEqual(h.writes[0].body.categories.UNIT.tests.map(t => t.id), ['a', 7]);
  await h.click(7); assert.deepEqual(h.active(), ['a']); assert.equal(h.get('btnSaveTest').disabled, true);
  h.writes[0].resolve(h.response({})); await tick();
  assert.equal(h.get('btnSaveTest').disabled, false); await h.click(7); assert.deepEqual(h.active(), ['7']);
}
if (!process.argv.includes('--only-save')) {
  const h = harness(); await h.start();
  h.get('csvFile').files = [{ text: async () => 'id,분류,과목,난이도,회차,시험명,문항수,정답,유형\na,UNIT,공수1,Lv.3,1,CSV 알파,1,3,choice_number' }];
  const importing = h.get('csvFile').handlers.change({ target: h.get('csvFile') }); await tick();
  assert.equal(h.writes.length, 1); assert.equal(h.writes[0].method, 'POST');
  const config = h.writes[0].body;
  const test = config.categories.UNIT.tests.find(t => t.id === 'a');
  assert.equal(test.name, 'CSV 알파'); assert.deepEqual(test.answerKey, ['3']);
  assert.deepEqual(test.answerKeys, { '1': ['3'], '2': ['2'], '9': ['기존'] });
  assert.deepEqual(test.answerModes, { '1': ['choice_number'], '2': ['choice_number'], '9': ['answer_value'] });
  assert.deepEqual(test.unknown, { keep: true }); assert.deepEqual(test.sourceFiles, { solutionFileId: 'qa-a', unknown: 3 });
  assert.deepEqual(config.rootUnknown, { keep: true }); assert.equal(config.categories.UNIT.tests.length, 2);
  h.writes[0].resolve(h.response({})); await tick();
  h.pendingReads.forEach(d => d.resolve(h.response({}))); await importing; await tick();
  assert.equal(h.writes.length, 1); assert.equal(h.get('csvFile').value, ''); assert.equal(h.get('btnSaveTest').disabled, false);
}
console.log(JSON.stringify({ ok: true, actualEntryPointLiteralGroups: process.argv.includes('--only-csv') ? 1 : process.argv.includes('--only-save') ? 2 : 4, realFetch: 0, persistentWrites: 0 }));
