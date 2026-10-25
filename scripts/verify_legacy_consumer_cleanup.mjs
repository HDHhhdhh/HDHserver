import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..');
const read = relativePath => fs.readFile(path.join(root, relativePath), 'utf8');

async function pathExists(relativePath) {
  try {
    await fs.access(path.join(root, relativePath));
    return true;
  } catch {
    return false;
  }
}

assert.equal(await pathExists('static/js/main.js'), false, 'retired main.js must stay deleted');
assert.equal(
  await pathExists('static/js/admin/features/materials.js'),
  false,
  'comment-only materials module must stay deleted',
);
for (const retiredPath of [
  'static/js/assign-panel.js',
  'static/js/file-assign.js',
  'static/js/admin/features/assignModal.js',
]) {
  assert.equal(await pathExists(retiredPath), false, retiredPath + ' must stay deleted');
}

const [adminMain, demoFetch, deleteSource, authSource] = await Promise.all([
  read('static/js/admin/main.js'),
  read('static/js/admin/demo/fetch.js'),
  read('static/js/all/features/deleteButtons.js'),
  read('static/js/auth.js'),
]);

assert.doesNotMatch(adminMain, /initMaterials|features\/materials\.js|initAssignModal|features\/assignModal\.js/);
assert.doesNotMatch(demoFetch, /materialUploadResponse|\/api\/material-upload|\/api\/delete-student/);
assert.doesNotMatch(demoFetch, /method === 'POST' && path === '\/api\/materials'/);
assert.match(demoFetch, /applyDemoGraveyardRequest\(\{ method, path, body, store \}\)/);
const { applyDemoGraveyardRequest } = await import('../static/js/admin/demo/graveyardContract.js');
const demoDeleteStore = { students: [{ id: 'demo-legacy-check', name: '합성학생' }], logs: { old: 'preserve' } };
assert.equal(applyDemoGraveyardRequest({ method: 'DELETE', path: '/api/students/demo-legacy-check', store: demoDeleteStore }).status, 200);
assert.deepEqual(demoDeleteStore.students, []);
assert.equal(demoDeleteStore.graveyard[0].student.id, 'demo-legacy-check');
assert.deepEqual(demoDeleteStore.logs, { old: 'preserve' });
assert.equal(applyDemoGraveyardRequest({ method: 'POST', path: '/api/delete-student', store: demoDeleteStore }), null);
assert.doesNotMatch(deleteSource, /\/api\/delete-student/);
assert.match(
  deleteSource,
  /fetch\(`\/api\/students\/\$\{encodeURIComponent\(sid\)\}`, \{ method:'DELETE' \}\)/,
);
assert.match(authSource, /apiWithSpinner\("\/api\/auth\/change"/);

const routeDir = path.join(root, 'routes');
const routeFiles = (await fs.readdir(routeDir, { withFileTypes: true }))
  .filter(entry => entry.isFile() && entry.name.endsWith('.py'))
  .map(entry => path.join(routeDir, entry.name));
const routeSource = (await Promise.all(routeFiles.map(file => fs.readFile(file, 'utf8')))).join('\n');
assert.doesNotMatch(routeSource, /["']\/api\/(?:delete-student|material-upload)["']/);
assert.doesNotMatch(routeSource, /["']\/api\/fs\/page-folders["']/);
assert.match(routeSource, /@bp_api_students\.get\("\/api\/students"\)/);
assert.match(routeSource, /@bp_api_materials\.get\("\/api\/materials"\)/);
assert.match(routeSource, /@bp_api_logs\.get\("\/api\/logs"\)/);
assert.match(routeSource, /@bp_api_schedule_overrides\.route\("\/api\/extra-attend", methods=\["GET", "PATCH"\]\)/);
assert.match(routeSource, /@bp_api_schedule_overrides\.route\("\/api\/weekend-slots", methods=\["GET", "POST"\]\)/);
assert.match(routeSource, /@bp_api_students\.delete\("\/api\/students\/<string:sid>"\)/);
assert.match(routeSource, /PAGE_FOLDERS_PATH/, 'internal page-folder store contract remains available');

let clickHandler = null;
const dispatched = [];
const alerts = [];
const toasts = [];
const fetchCalls = [];

globalThis.document = {
  body: {},
  getElementById: () => null,
  addEventListener(type, handler) {
    if (type === 'click') clickHandler = handler;
  },
  dispatchEvent(event) {
    dispatched.push(event);
    return true;
  },
};
globalThis.window = { students: [], toast: message => toasts.push(message) };
globalThis.toast = message => toasts.push(message);
globalThis.confirm = () => true;
globalThis.alert = message => alerts.push(message);
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};

const deleteModulePath = path.join(root, 'static/js/all/features/deleteButtons.js');
await import(`${pathToFileURL(deleteModulePath).href}?verify=${Date.now()}`);
assert.equal(typeof clickHandler, 'function', 'delete click handler must register');

function deleteFixture(sid, name) {
  const row = {
    dataset: { sid },
    cells: [{ textContent: name }],
    removed: false,
    querySelector: () => null,
    remove() {
      this.removed = true;
    },
  };
  const button = {
    closest(selector) {
      if (selector === 'tr') return row;
      if (selector === '.btn-del-stu') return button;
      return null;
    },
  };
  return {
    row,
    event: {
      target: {
        closest: selector => selector === '.btn-del-stu' ? button : null,
      },
    },
  };
}

const success = deleteFixture('sid/1', '성공 학생');
window.students = [{ id: 'sid/1' }, { id: 'keep' }];
globalThis.fetch = async (url, init = {}) => {
  fetchCalls.push({ url: String(url), method: init.method || 'GET' });
  return { ok: true, status: 204 };
};
await clickHandler(success.event);
assert.deepEqual(fetchCalls, [{ url: '/api/students/sid%2F1', method: 'DELETE' }]);
assert.equal(success.row.removed, true);
assert.deepEqual(window.students, [{ id: 'keep' }]);
assert.deepEqual(dispatched.map(event => [event.type, event.detail.sid]), [['all:student-deleted', 'sid/1']]);
assert.deepEqual(toasts, ['삭제 완료']);
assert.deepEqual(alerts, []);

fetchCalls.length = 0;
dispatched.length = 0;
toasts.length = 0;
alerts.length = 0;
const failure = deleteFixture('blocked', '실패 학생');
window.students = [{ id: 'blocked' }];
globalThis.fetch = async (url, init = {}) => {
  fetchCalls.push({ url: String(url), method: init.method || 'GET' });
  return { ok: false, status: 409 };
};
const originalConsoleError = console.error;
console.error = () => {};
try {
  await clickHandler(failure.event);
} finally {
  console.error = originalConsoleError;
}
assert.deepEqual(fetchCalls, [{ url: '/api/students/blocked', method: 'DELETE' }]);
assert.equal(failure.row.removed, false);
assert.deepEqual(window.students, [{ id: 'blocked' }]);
assert.deepEqual(dispatched, []);
assert.deepEqual(toasts, []);
assert.deepEqual(alerts, ['삭제 실패: 서버 응답 409']);

console.log('legacy consumer cleanup checks passed: retired full-map writes, static consumers, and canonical delete');
