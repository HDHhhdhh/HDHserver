import fs from 'node:fs';
import vm from 'node:vm';
import A from 'node:assert/strict';


const plain = x => JSON.parse(JSON.stringify(x));
function part(s, a, b) {
  const i = s.indexOf(a), j = s.indexOf(b, i);
  A.ok(i >= 0 && j > i);
  return s.slice(i, j);
}
const fixtureSource = fs.readFileSync(
  'scripts/verify_student_material_access_scope.js', 'utf8'
);
const dom = part(fixtureSource, 'class ClassList {', 'function makeResponse(');
const shared = fs.readFileSync('static/js/shared/search.js', 'utf8')
  .replace(/^export /gm, '');

function run(src, url, useShared = false) {
  const metrics = { render: 0, key: 0, walk: 0, sort: 0, history: [] };
  const location = new URL('https://fixture.invalid/student/s' + url);
  const mats = {
    f: { id: 11, title: '함수 문제.pdf', url: '/files/math/native-id.pdf' },
    a: { title: '가.pdf', url: '/files/math/a.pdf' },
    b: { title: '가.pdf', url: '/files/math/b.pdf' },
    c: { url: '/files/math/12345678-1234-1234-1234-123456789abc_수학.pdf' },
    hidden: { title: 'private.pdf', url: '/files/private.pdf' }
  };
  const ctx = vm.createContext({
    URL, URLSearchParams, metrics, mats, sid: 's',
    assigns: { s: [11, 'a', 'b', 'c', '/files/archive/1699999999999_국어.pdf'] },
    location: {
      origin: location.origin, pathname: location.pathname,
      search: location.search, hash: location.hash
    },
    fetch() { throw Error('unexpected request'); }
  });
  ctx.window = ctx;
  ctx.history = {
    replaceState(state, _, target) {
      metrics.history.push({ state: plain(state), target });
      const next = new URL(target, location);
      Object.assign(ctx.location, { search: next.search, hash: next.hash });
    }
  };
  vm.runInContext(dom + `
    globalThis.document = new DocumentStub();
    const list = document.createElement("ul");
    list.id = "matList"; document.body.appendChild(list);
    globalThis.$ = id => document.getElementById(id);
  `, ctx);
  if (useShared) vm.runInContext(shared, ctx);

  const helpers =
    part(src, 'const STUDENT_SEARCH_HELP_TEXT =', '// VG Controller') +
    part(src, '  function cleanDisplayName(name) {', '  // 전역 캐시');
  let body = part(src, '    function getAssignedRaw(assignsObj, sid) {',
    '    /* ───────────── 건의사항 제출');
  body = body
    .replace('    function renderMat() {',
      '    function renderMat() { metrics.render++;')
    .replace(/\(function walk\(nd, acc = \[\]\) \{/g,
      '(function walk(nd, acc = []) { metrics.walk++;')
    .replace(/\.sort\(/g, '.countedSort(');
  vm.runInContext(`
    Array.prototype.countedSort = function(c) {
      metrics.sort++; return this.sort(c);
    };
  ` + helpers + `
    const actualKey = studentSearchKeyForText;
    studentSearchKeyForText = x => { metrics.key++; return actualKey(x); };
    (function(){${body}})();
  `, ctx);

  function view() {
    return plain({
      rows: ctx.document.getElementById('matList').children.map(li => ({
        text: li.textContent, type: li.dataset.type,
        links: li.querySelectorAll('a').map(a => [a.textContent, a.href, a.download])
      })),
      crumb: ctx.document.getElementById('matCrumb').textContent,
      mode: ctx.document.getElementById('matMode').textContent,
      aria: ctx.document.getElementById('matMode').getAttribute('aria-pressed'),
      location: ctx.location
    });
  }
  return {
    ctx, metrics, view,
    query(q) {
      const input = ctx.document.getElementById('matSearch');
      input.value = q;
      input.dispatchEvent({ type: 'input', target: input });
      return view();
    }
  };
}


const titles = v => v.rows.flatMap(r => r.links.map(a => a[0]));
const sourceIndex = process.argv.indexOf('--source');
const after = fs.readFileSync(sourceIndex < 0 ? 'static/js/student.js' : process.argv[sourceIndex + 1], 'utf8');
const initialCases = [
['', [], 'tree', [], ['files']],
['?mpath=files&mmode=tree&x=1#keep', ['files'], 'tree', [], ['archive', 'math']],
['?mpath=files/math&mmode=tree#keep', ['files', 'math'], 'tree', ['가.pdf', '가.pdf', '수학.pdf', '함수 문제.pdf'], []],
['?mpath=files/math&mmode=flat#keep', ['files', 'math'], 'flat', ['가.pdf', '가.pdf', '국어.pdf', '수학.pdf', '함수 문제.pdf'], []],
['?mpath=missing&mmode=tree#keep', ['missing'], 'tree', [], ['files']],
['?mpath=files&mmode=bad&sid=a&sid=b#keep', ['files'], 'tree', [], ['archive', 'math']],
];
for (const [url, path, mode, files, folders] of initialCases) {
const h = run(after, url);
const view = h.view();
A.deepEqual(titles(view), files);
A.deepEqual(view.rows.filter(row => row.type === 'dir').map(row => row.text.replace('📁', '').replace(/\(\d+\)$/, '')), folders);
A.equal(view.mode, mode === 'tree' ? '폴더 보기' : '전체 보기');
A.equal(view.aria, String(mode !== 'tree'));
A.equal(h.metrics.render, 1);
A.equal(h.metrics.history.length, 1);
A.deepEqual(h.metrics.history[0].state, { mpath: path, mmode: mode });
const expectedParams = new URLSearchParams(url.split('#')[0].replace(/^\?/, ''));
expectedParams.set('mpath', path.join('/'));
expectedParams.set('mmode', mode);
A.equal(view.location.search, '?' + expectedParams);
A.equal(view.location.hash, url.includes('#') ? '#keep' : '');
}
for (const useShared of [false, true]) {
const h = run(after, '?mpath=files/math&mmode=flat#keep', useShared);
for (const [q, want] of [
  ['', ['가.pdf', '가.pdf', '국어.pdf', '수학.pdf', '함수 문제.pdf']],
  ['함수', ['함수 문제.pdf']], ['ㅎㅅ', ['함수 문제.pdf']],
  ['gkatn', ['함수 문제.pdf']], ['함수 math', ['함수 문제.pdf']],
  ['native-id', []], ['12345678', []], ['archive', ['국어.pdf']], ['nope', []],
]) A.deepEqual(titles(h.query(q)), want);
A.deepEqual([h.metrics.render, h.metrics.key, h.metrics.walk, h.metrics.sort], [10, 5, 4, 1]);
const tree = run(after, '?mpath=files/math&mmode=tree#keep', useShared);
for (const [q, want] of [
  ['native-id', ['함수 문제.pdf']], ['12345678', ['수학.pdf']],
  ['함수 math', []], ['함수 native-id', ['함수 문제.pdf']], ['private', []],
]) A.deepEqual(titles(tree.query(q)), want);
const links = tree.query('함수').rows.flatMap(row => row.links);
A.deepEqual(links, [['함수 문제.pdf', '/files/math/native-id.pdf', '']]);
}
const late = run(after, '?mpath=files/math&mmode=tree#keep');
A.deepEqual(titles(late.query('pdfnative')), ['함수 문제.pdf']);
vm.runInContext(shared, late.ctx);
A.deepEqual(titles(late.query('pdfnative')), []);
vm.runInContext('window.SearchUtils = undefined;', late.ctx);
A.deepEqual(titles(late.query('pdfnative')), ['함수 문제.pdf']);
console.log(JSON.stringify({ ok: true, initialUrlCases: 6, searchModes: 4, lateHelperChanges: 2, realFetch: 0, persistentWrites: 0 }));
