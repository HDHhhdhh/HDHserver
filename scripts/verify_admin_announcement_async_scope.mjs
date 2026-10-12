import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
const args = process.argv.slice(2), rootArg = args.indexOf('--source-root');
const root = path.resolve(rootArg < 0 ? path.join(path.dirname(fileURLToPath(import.meta.url)), '..') : args[rootArg + 1]);
const sourceArg = args.indexOf('--source');
const source = fs.readFileSync(sourceArg < 0 ? path.join(root, 'static/js/admin/features/announcements.js') : path.resolve(args[sourceArg + 1]), 'utf8')
  .replace(/^import[\s\S]*?;\r?\n/gm, '').replace('export function initAnnouncements', 'function initAnnouncements');
const apiSource = fs.readFileSync(path.join(root, 'static/js/shared/api.js'), 'utf8').replace(/\bexport\s+/g, '');
const copy = value => JSON.parse(JSON.stringify(value));
const same = (actual, expected) => assert.deepEqual(copy(actual), expected);
const flush = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
const defer = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const response = (body, status = 200) => ({ ok: status === 200, status, json: async () => copy(body), text: async () => typeof body === 'string' ? body : JSON.stringify(body) });
class ClockDate extends Date { constructor(...args) { super(...(args.length ? args : [Date.UTC(2026, 9, 1)])); } static now() { return Date.UTC(2026, 9, 1); } }
class Element {
  constructor(id = '') {
    Object.assign(this, { id, value: '', textContent: '', innerHTML: '', hidden: true, disabled: false, files: [], style: {}, dataset: {}, attrs: {}, handlers: {}, children: [] });
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  fire(type, target = this) { return (this.handlers[type] || []).map(fn => fn({ target, currentTarget: this, preventDefault() {}, stopPropagation() {}, stopImmediatePropagation() {} })); }
  querySelector() { return null; } querySelectorAll() { return []; } closest() { return null; } matches() { return false; }
  getAttribute(k) { return this.attrs[k]; } setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'hidden') this.hidden = true; if (k === 'open') this.open = true; }
  removeAttribute(k) { delete this.attrs[k]; } contains(child) { return this.children.includes(child); }
  appendChild(child) { this.children.push(child); child.parentNode = this; } append(...xs) { xs.forEach(x => this.appendChild(x)); }
  replaceChildren(...xs) { this.children = []; this.append(...xs); } insertBefore(x) { this.appendChild(x); }
  insertAdjacentHTML() {} focus() {} remove() {} getBoundingClientRect() { return { width: 0, height: 0 }; }
}
const image = name => ({ url: '/files/announcements/' + name + '.png', path: 'announcements/' + name + '.png', name: name + '.png', originalName: name + '.png', mime: '', size: 0 });
const record = (id, extra = {}) => ({ id, kind: 'announcement', title: id + ' title', content: id + ' body', targetSids: ['sid-a'], expiresAt: '2026-10-01T04:00:00.000Z', images: [], ...extra });
const B = record('B', { images: [image('b-existing')] });
const S = record('S', { kind: 'survey', survey: { status: 'public', anonymous: false, allowMultiple: false, questions: [{ id: 'q1', type: 'short', text: '질문', required: true, options: [] }] } });
function fixture({ records = [B], manualGets = false, failedRefresh = false } = {}) {
  const ids = new Map(('announcementSection annTitle annContent annPublish annModeToggle annComposeModeToggle annTargetMenu annTargetBtn annBoardShell annComposeExpand annComposeExpandClose annComposeExpandModal annComposeExpandMount annReplyDock annList annImageFile annImagePick annImageRemove').split(' ').map(id => [id, new Element(id)]));
  const compose = new Element(), expanded = new Element(), builder = new Element(), today = new Element();
  today.dataset = { sid: 'sid-a', slotGroup: '1' };
  const document = new Element(); document.hidden = false; document.body = new Element();
  document.getElementById = id => ids.get(id) || null;
  document.querySelector = q => q === '.announcement-compose' ? compose : q === '#annBoardShell' ? ids.get('annBoardShell') : q === '[data-expanded-survey-builder]' ? builder : null;
  document.querySelectorAll = q => q === '#todayWrap tr[data-sid]' ? [today] : q === '[data-expanded-publish]' ? [expanded] : [];
  document.createElement = tag => new Element(tag); document.createComment = text => new Element(text);
  const writes = [], deletes = [], uploads = [], gets = [], intervals = [], alerts = [], toasts = [];
  const ctx = { document, Date: ClockDate, state: { students: [{ id: 'sid-a', name: '학생A', curriculum: '대수' }], videos: [] },
    getAdminDate: () => '2026-10-01', applySearchPlaceholder() {}, matchesSearchKey: () => true, searchKeyForText: String,
    console: { error() {}, warn() {}, log() {} }, alert: m => alerts.push(String(m)), confirm: () => true,
    addEventListener() {}, setTimeout: () => 0, clearTimeout() {}, requestAnimationFrame: fn => fn(),
    setInterval: fn => { intervals.push(fn); return intervals.length; }, FormData: class { append() {} }, __toasts: toasts,
    fetch: (url, opt = {}) => {
      const gate = defer(), method = opt.method || 'GET';
      if (url === '/api/announce-status' && method === 'GET') {
        gets.push({ gate }); if (!manualGets) gate.resolve(response(records, failedRefresh && gets.length > 1 ? 503 : 200));
      } else if (url === '/api/announcements/image' && method === 'POST') uploads.push({ gate });
      else if (url.startsWith('/api/announcements/') && method === 'DELETE') deletes.push({ url, gate });
      else if (url.startsWith('/api/announcements') && ['POST', 'PUT'].includes(method)) writes.push({ url, method, payload: JSON.parse(opt.body), gate });
      else throw new Error('Unexpected request: ' + method + ' ' + url);
      return gate.promise;
    } };
  ctx.window = ctx; vm.createContext(ctx);
  vm.runInContext(apiSource + '\nglobalThis.sendJson=sendJson;', ctx);
  // Layout-only stubs leave transport, ownership and registered listeners intact.
  vm.runInContext(source + '\nrenderComposeExpandBody=()=>{}; renderReplyDock=()=>{}; renderExpandedAnnouncementList=()=>{}; toast=m=>__toasts.push(String(m)); globalThis.entry={initAnnouncements};', ctx);
  ctx.entry.initAnnouncements();
  const click = id => ids.get(id).fire('click'), wait = tasks => Promise.all(tasks);
  const edit = id => { const target = new Element(); target.dataset.annEdit = id; target.closest = q => q === '[data-ann-edit]' ? target : null; return ids.get('annReplyDock').fire('click', target); };
  const remove = id => { const target = new Element(); target.dataset.annDelete = id; target.closest = q => q === '[data-ann-delete]' ? target : null; return ids.get('annReplyDock').fire('click', target); };
  expanded.closest = q => q === '[data-expanded-survey-builder]' ? builder : q === '[data-expanded-publish]' ? expanded : null;
  const input = (title, body) => { ids.get('annTitle').value = title; ids.get('annContent').value = body; ids.get('annTitle').fire('input'); ids.get('annContent').fire('input'); };
  return { ids, expanded, writes, deletes, uploads, gets, intervals, alerts, toasts, ctx, click, edit, remove, input, wait,
    main: () => click('annPublish'), expandedSave: () => ids.get('annComposeExpandMount').fire('click', expanded),
    file: name => { ids.get('annImageFile').files = [{ name: name + '.png', type: 'image/png', size: 20 }]; return ids.get('annImageFile').fire('change'); },
    draft: () => { input('A title', 'A body'); click('annComposeExpand'); },
    busy: () => [ids.get('annPublish').disabled, expanded.disabled, ids.get('annImagePick').disabled],
    finish: async (tasks, status = 200) => { writes.forEach(w => w.gate.resolve(response(status === 200 ? { id: 'A' } : 'save failed', status))); await wait(tasks); await flush(); } };
}
let cases = 0;
{
  const f = fixture(); await flush(); f.ctx.entry.initAnnouncements(); await flush(); f.click('annModeToggle');
  const task = f.file('one'); same([f.ids.get('annModeToggle').textContent, f.uploads.length, f.intervals.length], ['영상', 1, 1]);
  f.uploads[0].gate.resolve(response({ image: image('one') })); await f.wait(task); cases++;
}
for (const survey of [false, true]) {
  const f = fixture({ records: survey ? [S] : [B] }); await flush(); survey ? await f.wait(f.edit('S')) : f.draft();
  const task = survey ? f.expandedSave() : f.main(); const duplicate = [...f.main(), ...(survey ? f.expandedSave() : [])];
  same(f.writes.length, 1); same(f.busy(), [true, true, true]);
  if (survey) same([f.writes[0].url, f.writes[0].payload.kind], ['/api/announcements/S', 'survey']);
  await f.finish([...task, ...duplicate]); same([f.ids.get('annTitle').value, f.ids.get('annComposeExpandModal').hidden], ['', true]);
  same(f.busy(), [false, false, false]); same(f.alerts, []); cases++;
}
{
  const f = fixture(); await flush(); f.draft(); const first = f.main(), payload = copy(f.writes[0].payload);
  await f.finish(first, 503); same([f.ids.get('annTitle').value, f.ids.get('annContent').value, f.alerts], ['A title', 'A body', ['save failed']]);
  same(f.busy(), [false, false, false]); const retry = f.main(); same(f.writes.length, 2); same(f.writes[1].payload, payload);
  await f.finish(retry); same(f.busy(), [false, false, false]); cases++;
}
for (const change of ['draft', 'edit', 'reopen']) {
  const f = fixture(); await flush(); f.draft(); const task = f.main();
  if (change === 'draft') f.input('B draft', 'B new body');
  if (change === 'edit') await f.wait(f.edit('B'));
  if (change === 'reopen') { f.click('annComposeExpandClose'); f.click('annComposeExpand'); }
  await f.finish(task); same([f.writes[0].payload.title, f.writes[0].payload.content], ['A title', 'A body']);
  same([f.ids.get('annTitle').value, f.ids.get('annContent').value, f.ids.get('annComposeExpandModal').hidden],
    change === 'draft' ? ['B draft', 'B new body', false] : change === 'edit' ? ['B title', 'B body', false] : ['A title', 'A body', false]);
  same(f.alerts, []); cases++;
}
{
  const f = fixture({ manualGets: true }); f.gets[0].gate.resolve(response([B])); await flush(); f.draft(); const task = f.main();
  f.writes[0].gate.resolve(response({ id: 'A' })); await flush();
  same([f.ids.get('annTitle').value, f.ids.get('annComposeExpandModal').hidden, f.gets.length], ['', true, 2]);
  await f.wait(f.edit('B')); f.gets[1].gate.resolve(response([B])); await f.wait(task); await flush();
  same([f.ids.get('annTitle').value, f.ids.get('annComposeExpandModal').hidden], ['B title', false]); cases++;
}
{
  const f = fixture({ failedRefresh: true }); await flush(); f.draft(); await f.finish(f.main());
  same(f.alerts, []); same(f.toasts, ['공지 등록 완료', '등록은 완료됐지만 목록을 새로고침하지 못했습니다.']);
  same([f.ids.get('annTitle').value, f.ids.get('annComposeExpandModal').hidden], ['', true]); same(f.busy(), [false, false, false]); cases++;
}
for (const change of ['edit', 'remove']) {
  const f = fixture(); await flush(); f.draft(); const task = f.file('old');
  change === 'edit' ? await f.wait(f.edit('B')) : f.click('annImageRemove'); f.main();
  same(f.writes.length, 0); same(f.busy(), [true, true, true]);
  f.uploads[0].gate.resolve(response({ image: image('old') })); await f.wait(task); await flush(); const saved = f.main();
  same(f.writes[0].payload.images, change === 'edit' ? [image('b-existing')] : []);
  same(f.toasts.includes('이미지 첨부 완료'), false); if (change === 'edit') same(f.writes[0].url, '/api/announcements/B');
  await f.finish(saved); cases++;
}
{
  const f = fixture(); await flush(); f.draft(); const a = f.file('first'), b = f.file('second');
  f.uploads[1].gate.resolve(response({ image: image('second') })); await f.wait(b); same(f.busy(), [true, true, true]);
  f.uploads[0].gate.resolve(response({ image: image('first') })); await f.wait(a); await flush(); const saved = f.main();
  same(f.writes[0].payload.images, [image('second')]); same(f.toasts.filter(t => t === '이미지 첨부 완료').length, 1);
  await f.finish(saved); cases++;
}
for (const stale of [false, true]) {
  const f = fixture(); await flush(); await f.wait(f.edit('B')); const failed = f.file('failed');
  if (stale) { f.click('annComposeExpandClose'); f.click('annComposeExpand'); }
  f.uploads[0].gate.resolve(response({ error: 'upload failed' }, 503)); await f.wait(failed); await flush();
  same(f.alerts, stale ? [] : ['upload failed']); same(f.busy(), [false, false, false]);
  const retry = f.file('retry'); f.uploads[1].gate.resolve(response({ image: image('retry') })); await f.wait(retry); await flush();
  const saved = f.main(); same(f.writes[0].payload.images, [image('retry')]); await f.finish(saved); cases++;
}
for (const status of [200, 503]) {
  const f = fixture({ manualGets: true }); f.draft(); const saved = f.main();
  f.intervals[0](); f.intervals[0](); same(f.gets.length, 1, 'unchanged polls share the pending read');
  f.writes[0].gate.resolve(response({ id: 'NEW-B' })); await flush();
  same(f.gets.length, 2, 'a committed mutation must start a fresh authoritative read');
  f.gets[1].gate.resolve(response([record('NEW-B')])); await flush(); assert.ok(f.ids.get('annList').innerHTML.includes('data-ann-id="NEW-B"'));
  f.gets[0].gate.resolve(response([record('OLD-A')], status)); await flush(); const html = f.ids.get('annList').innerHTML;
  await f.wait(saved);
  assert.ok(html.includes('data-ann-id="NEW-B"')); assert.ok(!html.includes('data-ann-id="OLD-A"')); assert.ok(!html.includes('불러오지 못했습니다')); same(f.alerts, []); cases++;
}
{
  const f = fixture({ manualGets: true }); f.intervals[0](); f.intervals[0](); same(f.gets.length, 1);
  f.gets[0].gate.resolve(response({}, 503)); await flush();
  assert.ok(f.ids.get('annList').innerHTML.includes('불러오지 못했습니다'));
  f.intervals[0](); same(f.gets.length, 2, 'failed reads must be evicted');
  f.gets[1].gate.resolve(response([B])); await flush();
  assert.ok(f.ids.get('annList').innerHTML.includes('data-ann-id="B"'));
  f.intervals[0](); same(f.gets.length, 3, 'settled reads are never cached');
  f.gets[2].gate.resolve(response([B])); await flush(); cases++;
}
{
  const f=fixture({failedRefresh:true});await flush();const task=f.remove('B');
  same(f.deletes.length,1);f.deletes[0].gate.resolve(response({ok:true}));await f.wait(task);await flush();
  same(f.alerts,[],'committed delete is not reported as a failed command');
  same(f.toasts,['공지 삭제 완료','삭제는 완료됐지만 목록을 새로고침하지 못했습니다.']);cases++;
}
for(const status of [403,503]){
  const f=fixture();await flush();await f.wait(f.edit('B'));const task=f.remove('B');
  f.deletes[0].gate.resolve(response({error:'simulated delete failure'},status));await f.wait(task);await flush();
  same(f.alerts,['공지 삭제 실패']);same(f.gets.length,1,'failed delete never refreshes as committed');
  same(f.ids.get('annTitle').value,'B title');cases++;
}
{
  const C=record('C',{targetSids:['sid-b'],targetSnapshot:[{sid:'sid-b',name:'학생B',curriculum:'대수'}]});
  const f=fixture({records:[B,C]});await flush();await f.wait(f.edit('B'));const task=f.remove('B');
  await f.wait(f.edit('C'));f.deletes[0].gate.resolve(response({ok:true}));await f.wait(task);await flush();
  same([f.ids.get('annTitle').value,f.ids.get('annContent').value],['C title','C body']);
  const saved=f.main();same(f.writes.length,1);same(f.writes[0].url,'/api/announcements/C');
  same(f.writes[0].payload.targetSids,['sid-b'],'old delete must retain newer fallback target snapshot');
  await f.finish(saved);cases++;
}
{
  const f=fixture();await flush();await f.wait(f.edit('B'));const task=f.remove('B');
  f.click('annComposeExpandClose');f.click('annComposeExpand');f.input('new B draft','new B body');
  f.deletes[0].gate.resolve(response({ok:true}));await f.wait(task);await flush();
  same([f.ids.get('annTitle').value,f.ids.get('annContent').value],['new B draft','new B body']);
  const saved=f.main();same(f.writes[0].url,'/api/announcements/B','new same-ID edit session survives old delete');await f.finish(saved);cases++;
}
{
  const f=fixture();await flush();f.ctx.confirm=()=>false;await f.wait(f.remove('B'));
  same(f.deletes.length,0);same(f.gets.length,1);same(f.toasts,[]);cases++;
}
console.log('PASS administrator announcement async safety: ' + cases + ' actual initializer/listener cases');
