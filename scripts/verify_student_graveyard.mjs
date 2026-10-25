import assert from 'node:assert/strict';
import fs from 'node:fs';

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {}; this.value = ''; this.text = ''; this.disabled = false; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(' '); }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key]; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async fire(name, event = {}) { for (const fn of this.listeners[name] || []) await fn(event); }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes) { this.text = ''; this.children = []; this.append(...nodes); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
  querySelectorAll(tag) { return this.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
  focus() { document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; void this.fire('close'); }
}
const body = new Element('body');
globalThis.document = { body, createElement: tag => new Element(tag), activeElement: null };
globalThis.confirm = () => true;
const values = new Map();
globalThis.sessionStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
const { createDemoFetch } = await import('../static/js/admin/demo/fetch.js');
const { loadDemoStore, saveDemoStore } = await import('../static/js/admin/demo/store.js');
const { state } = await import('../static/js/all/core/state.js');
const root = { location: { origin: 'http://localhost' }, Response };
let forwarded = 0;
const demoFetch = createDemoFetch({ root, originalFetch: () => { forwarded++; throw new Error('live request forbidden'); } });
const initial = loadDemoStore();
const one = initial.students[0], two = initial.students[1];
const sid = one.id;
initial.logs['2026-06-16'] = { [sid]: { notes: '<script>안전한 텍스트</script>', homeworkTable: [{ book: '보존 교재', range: '10~20' }], done: true } };
initial.progress['2026-06-16'] = { [sid]: { 'demo-v-test': 'done', tests: { 'test-a': { status: 'assigned', title: '보존 시험' } } } };
saveDemoStore(initial);
state.videos = [{ mid: 'demo-v-test', title: '보존 영상' }];
const ops = store => JSON.stringify([store.logs, store.progress, store.updates, store.watch, store.attendance, store.matAssign]);
const originalOps = ops(loadDemoStore());
const deletion = await demoFetch(`/api/students/${sid}`, { method: 'DELETE' });
assert.equal(deletion.headers.get('X-Student-Graveyard'), '1');
assert.equal(ops(loadDemoStore()), originalOps);
await demoFetch(`/api/students/${two.id}`, { method: 'DELETE' });
const current = loadDemoStore();
current.graveyard.find(row => row.student.id === sid).snapshotComplete = false;
saveDemoStore(current);

let delayFirst = false, release, failList = false, failHistory = false;
const writes = [];
globalThis.fetch = async (url, init = {}) => {
  if (init.method && init.method !== 'GET') writes.push([url, init]);
  if (failList && url === '/api/students/graveyard') return new Response('{}', { status: 503 });
  if (failHistory && String(url).startsWith('/api/logs?')) return new Response('{}', { status: 503 });
  if (delayFirst && String(url).startsWith('/api/logs?') && String(url).includes(two.id)) {
    delayFirst = false;
    await new Promise(resolve => { release = resolve; });
  }
  return demoFetch(url, init);
};
const { openGraveyard } = await import('../static/js/all/features/graveyard.js');
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)); };
const find = (tag, text) => body.querySelectorAll(tag).find(node => node.textContent === text);
const classNode = name => {
  const walk = node => node.className === name ? node : node.children.map(walk).find(Boolean);
  return walk(body);
};
let restored = [];
await openGraveyard({ onRestored: row => restored.push(row) });
await settle();
assert.equal(document.activeElement.tagName, 'input');
assert.equal(classNode('graveyard-list').querySelectorAll('button').length, 2);
const archivedButton = classNode('graveyard-list').querySelectorAll('button').find(node => node.textContent.includes(one.name));
await archivedButton.fire('click');
await settle();
assert.match(classNode('graveyard-detail').textContent, /전체 설정이 없습니다/);
assert.match(classNode('graveyard-detail').textContent, /보존 교재/);
assert.match(classNode('graveyard-detail').textContent, /보존 영상 · 완료/);
assert.match(classNode('graveyard-detail').textContent, /보존 시험 · 배정/);
assert.match(classNode('graveyard-detail').textContent, /<script>안전한 텍스트<\/script>/);
assert.equal(body.querySelectorAll('script').length, 0);

// Reversed history responses and closed sessions cannot repaint another selection.
delayFirst = true;
const otherButton = classNode('graveyard-list').querySelectorAll('button').find(node => node.textContent.includes(two.name));
const pending = otherButton.fire('click');
await settle();
await classNode('graveyard-list').querySelectorAll('button').find(node => node.textContent.includes(one.name)).fire('click');
release(); await pending; await settle();
assert.match(classNode('graveyard-detail').textContent, /보존 교재/);
failHistory = true;
await classNode('graveyard-list').querySelectorAll('button').find(node => node.textContent.includes(one.name)).fire('click');
await settle();
assert.ok(find('button', '기록 다시 불러오기'));
failHistory = false;
await find('button', '기록 다시 불러오기').fire('click'); await settle();
const restoreButton = find('button', '전체 학생 명단으로 복원');
await Promise.all([restoreButton.fire('click'), restoreButton.fire('click')]);
await settle();
assert.equal(writes.length, 1, 'double click must send only one restore');
assert.equal(restored[0].id, sid);
assert.ok(loadDemoStore().students.some(row => row.id === sid));
assert.equal(ops(loadDemoStore()), originalOps);
assert.equal(loadDemoStore().graveyard.length, 1);
failList = true;
await find('button', '새로고침').fire('click');
assert.equal(classNode('graveyard-message').dataset.error, 'true');
assert.equal(classNode('graveyard-detail').querySelectorAll('button').length, 0);
failList = false;
await find('button', '새로고침').fire('click'); await settle();
assert.equal(classNode('graveyard-list').querySelectorAll('button').length, 1);
assert.equal(forwarded, 0);
assert.ok(fs.readFileSync('static/js/admin/demo/bootstrap.js', 'utf8').includes('applyDemoGraveyardRequest({ method, path, body: homeworkBody, store: homeworkStore })'));
console.log('student graveyard UI/demo verification: OK (restore, preservation, races, errors, no live forwarding)');
