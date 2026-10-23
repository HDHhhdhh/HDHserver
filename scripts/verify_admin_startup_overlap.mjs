import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/js/admin/main.js', 'utf8')
  .replace(/^import\s[^\n]+\n/gm, '')
  .replace(/\bimport\(/g, 'importFeature(');
const initialOrder = [
  'initSaveOperations',
  'initHoverTooltip', 'initAssistantStudentNotes', 'initVideoModal', 'initLogModal',
  'initExtraModal', 'initAbsentRegister', 'initExport', 'initQuickPrinterExport',
  'initClearAll', 'initAbsentRecovery', 'initTimeGraph', 'initAdminDateBar',
  'initAdminUiEnhance', 'initStudentTestRecordDetails',
];
const exportsByFile = {
  saveOperations: 'initSaveOperations',
  hoverTooltip: 'initHoverTooltip', assistantStudentNotes: 'initAssistantStudentNotes',
  videoModal: 'initVideoModal', logModal: 'initLogModal', extraModal: 'initExtraModal',
  absentRegister: 'initAbsentRegister', exportLogs: 'initExport',
  quickPrinterExport: 'initQuickPrinterExport', done: 'initClearAll',
  absentRecovery: 'initAbsentRecovery', timeGraph: 'initTimeGraph',
  uiEnhance: 'initAdminUiEnhance', testRecordDetails: 'initStudentTestRecordDetails',
};
const tick = () => new Promise(resolve => setImmediate(resolve));

async function run(fail = '') {
  const calls = [], pending = [], document = {};
  let resolveData;
  const context = vm.createContext({
    state: {}, window: {}, document,
    console: { error() {} }, alert: () => calls.push('failure-feedback'),
    initDarkmode: () => calls.push('theme'),
    initAdminViewMode: () => calls.push('view'),
    initEscClose: () => calls.push('escape'),
    initAdminDateBar: options => {
      assert.equal(options.mountId, 'adminDateMount'); calls.push('initAdminDateBar');
    },
    bootstrap: () => {
      calls.push('data-start');
      return new Promise((resolve, reject) => {
        resolveData = () => {
          calls.push('data-ready');
          if (fail === 'data') reject(new Error('injected bootstrap failure'));
          else resolve();
        };
      });
    },
    loadTodayAndRender: async () => calls.push('first-table'),
    importFeature: url => {
      const name = url.match(/\/([^/]+)\.js/)[1];
      calls.push(`import:${name}`);
      if (!exportsByFile[name]) return Promise.resolve(new Proxy({}, {get: () => () => calls.push('deferred')}));
      return new Promise((resolve, reject) => pending.push(() => {
        if (fail === name) { reject(new Error('injected module failure')); return; }
        const exported = exportsByFile[name];
        resolve({ [exported]: arg => {
          if (name === 'testRecordDetails') assert.equal(arg, document);
          calls.push(exported);
        }});
      }));
    },
  });
  const completion = vm.runInContext(`(async () => {${source}\n})()`, context);
  const outcome = completion.then(() => true, () => false);
  assert.deepEqual(calls.slice(0, 4), ['theme', 'view', 'escape', 'data-start']);
  assert.equal(pending.length, 14, 'all required imports start while data is pending');
  assert.ok(!calls.includes('first-table'));
  // Finish imports out of order; the literal previous initialization order must remain intact.
  pending.reverse().forEach(resolve => resolve());
  await tick();
  assert.ok(!calls.includes('first-table'), 'imports alone cannot expose an unhydrated table');
  resolveData();
  assert.equal(await outcome, !fail);
  await tick();
  const initialized = calls.filter(name => name.startsWith('init'));
  if (fail) {
    assert.deepEqual(initialized, []);
    assert.ok(!calls.includes('first-table'));
    assert.ok(calls.includes('failure-feedback'));
  } else {
    assert.deepEqual(initialized, initialOrder);
    assert.ok(calls.indexOf('data-ready') < calls.indexOf('first-table'));
    assert.ok(calls.indexOf('first-table') < calls.indexOf('deferred'));
  }
}

await run();
await run('videoModal');
await run('logModal');
await run('saveOperations');
await run('data');
const shell = fs.readFileSync('static/admin.html', 'utf8');
assert.ok(shell.indexOf('admin/demo/bootstrap.js') < shell.indexOf('admin/main.js'));
for (const library of ['fullcalendar@6.1.8', 'sortablejs@1.15.0']) {
  const script = shell.split('\n').find(line => line.includes(library));
  assert.match(script, /<script defer /);
  assert.doesNotMatch(script, /\basync\b/);
}
console.log('PASS admin startup: overlapped reads/imports, fixed initialization order, fail-closed readiness and deferred libraries');
