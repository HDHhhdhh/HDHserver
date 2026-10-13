import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const read = relative => fs.readFileSync(path.join(process.cwd(), relative), 'utf8');
const list = { innerHTML: '', querySelectorAll: () => [] };
const selection = { textContent: '' };
const context = vm.createContext({
  document: {
    querySelector: selector => selector === '#testList' ? list
      : selector === '#editorSelectionLabel' ? selection : null,
    querySelectorAll: () => [],
  },
  window: { addEventListener() {} }, console,
  fetch() { throw new Error('Unexpected transport'); },
  setTimeout, clearTimeout,
});
function load(relative, dependencies = {}) {
  let source = read(relative);
  const names = [...source.matchAll(/^export (?:const|function|class) (\w+)/gm)]
    .map(x => x[1]);
  source = source.replace(
    /import\s+\{([\s\S]*?)\}\s+from\s+['"]([^'"]+)['"];\s*/g,
    (_, fields, ref) => 'const {' + fields + '}=dependencies['
      + JSON.stringify(ref.split('?')[0]) + '];\n',
  );
  context.dependencies = dependencies;
  return vm.runInContext(
    '(function(dependencies){' + source.replace(/^export\s+/gm, '')
      + '\nreturn {' + names.join(',') + '};})(dependencies)',
    context,
  );
}
const state = load('static/js/tests/catalogState.js');
context.modules = {
  './shared/search.js': load('static/js/shared/search.js'),
  './shared/testCatalogDisplay.js': load('static/js/shared/testCatalogDisplay.js'),
  './tests/catalogState.js': state,
  './tests/catalogEditorState.js': load('static/js/tests/catalogEditorState.js'),
  './tests/catalogStatisticsState.js': load(
    'static/js/tests/catalogStatisticsState.js', { './catalogState.js': state },
  ),
};
const entry = read('static/js/tests.js').replace(
  /import\s+\{([\s\S]*?)\}\s+from\s+['"]([^'"]+)['"];\s*/g,
  (_, fields, ref) => 'const {' + fields + '}=modules['
    + JSON.stringify(ref.split('?')[0]) + '];\n',
);
vm.runInContext(entry, context);
vm.runInContext(`
TEST_CFG = ensureConfig({unknownRoot:{keep:true},categories:{
  UNIT:{tests:[
    {id:'b',sourceId:'B',name:'다항식',curriculum:'공수1',difficulty:'Lv.3',round:'1',sortOrder:2,unknown:{keep:true}},
    {id:'a',sourceId:'A',name:'함수',curriculum:'공수1',difficulty:'Lv.3',round:'1',sortOrder:1},
    {id:'b2',sourceId:'B',name:'다항식',curriculum:'공수1',difficulty:'Lv.3',round:'2',sortOrder:3},
    {id:'c',sourceId:'C',name:'기하',curriculum:'공수1',difficulty:'Lv.4',round:'1',sortOrder:0}
  ]},REVIEW:{tests:[{id:'r',name:'복습',curriculum:'공수1',difficulty:'상',round:'1'}]}
}});
ui.category='UNIT';ui.subject='공수1';ui.difficulty='';ui.selectedId='b';
let normalizations=0;
const originalNormalizeTest=normalizeTest;
normalizeTest=(...args)=>{normalizations++;return originalNormalizeTest(...args)};
globalThis.oracle={
  get calls(){return normalizations},
  get cfg(){return JSON.stringify(TEST_CFG)},
  reset(){normalizations=0},
  get candidate(){return typeof createCatalogRenderProjection==='function'},
  renderAndFill(){fillEditor(renderTestList())},
  search(query){ui.catalogSearch=query;renderTestList()},
};
`, context);
assert.equal(context.oracle.candidate, true, 'render projection must be installed');
const initial = context.oracle.cfg;
const ids = () => [...list.innerHTML.matchAll(
  /<button type="button" data-id="([^"]+)"/g,
)].map(x => x[1]);
context.oracle.reset();context.oracle.renderAndFill();
assert.deepEqual(ids(), ['a','b','b2','c']);
assert.equal(selection.textContent, '2. 다항식');
assert.equal(context.oracle.calls, 5);
const renderAndFillCalls = context.oracle.calls;
context.oracle.reset();context.oracle.search('ㄷㅎㅅ');
assert.deepEqual(ids(), ['b','b2']);
assert.equal(context.oracle.calls, 4);
assert.equal(context.oracle.cfg, initial);
console.log(JSON.stringify({
  ok:true, candidate:context.oracle.candidate,
  renderAndFillCalls, searchCalls:context.oracle.calls, transportCalls:0,
}));
