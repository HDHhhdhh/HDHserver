import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';

// Actual video init/open/close/load/save functions with the existing VM harness,
// synthetic DOM and deferred transport. No app import, HTTP or persistent writes.
const args = process.argv.slice(2);
const option = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const root = path.resolve(option('--repo-root', process.cwd()));
const sourceDir = path.resolve(option('--source-dir', path.join(root, 'static/js/admin/features')));
const videoSource = path.resolve(option('--source', path.join(sourceDir, 'videoModal.js')));
const clone = value => JSON.parse(JSON.stringify(value));
const equal = (actual, expected, message) => assert.deepEqual(clone(actual), expected, message);
const flush = async () => { for (let i = 0; i < 50; i++) await Promise.resolve(); };
const DATE = '2026-10-01', PRIOR = '2026-09-20', STALE = '2026-09-01', FUTURE = '2026-10-15';
const A = '1001', B = '2002';
const urls = (sid, date = DATE) => [
  '/api/updates?readOnly=1',
  '/api/logs/entry?date=' + date + '&sid=' + sid,
  '/api/extra-attend',
  '/api/progress?sid=' + sid,
  '/api/watch/latest?sid=' + sid,
];
const cacheSource = fs.readFileSync(path.join(root, 'scripts/verify_popup_pending_cache.mjs'), 'utf8');
const helperSource = cacheSource.slice(cacheSource.indexOf('const clone ='), cacheSource.indexOf('async function run(proposed)'));
assert.ok(helperSource.includes('function harness(proposed)'), 'existing actual-source fixture must be present');
const fixtureFs = {
  readFileSync(file, ...rest) {
    const resolved = path.resolve(file);
    return fs.readFileSync(resolved === path.join(sourceDir, 'videoModal.js') ? videoSource : resolved, ...rest);
  },
};
const makeHarness = new Function('fs', 'path', 'vm', 'assert', 'sourceDir', helperSource + '\nreturn harness;')(
  fixtureFs, path, vm, assert, sourceDir,
);

function initialState() {
  return {
    students: [{ id: A, name: 'QA A', curriculum: '대수', autoVideoAssignCount: 2 }, { id: B, name: 'QA B', curriculum: '공수1', autoVideoAssignCount: 4 }],
    videos: [],
    updates: { [DATE]: { [A]: { videos: ['MID_OLD'], source: 'manual', unknown: 'old assignment' }, [B]: { videos: ['MID_B'], source: 'manual' } } },
    logs: { [DATE]: { [A]: { notes: 'OLD' }, [B]: { notes: '다른 학생', unknown: 'other log' } } },
    progress: {
      [DATE]: { [A]: { MID: 'done' }, [B]: { OTHER: 'skip', unknown: 'other current' } },
      [PRIOR]: { [A]: { OLD_PRIOR: 'done' }, [B]: { OTHER: 'none', unknown: 'other prior' } },
      [STALE]: { [A]: { DROP: 'done' }, [B]: { OTHER: 'interrupted', unknown: 'other stale' } },
    },
    extra: { [DATE]: [A], unknown: { keep: 'extra metadata' } },
  };
}

function payloads(sid = A, marker = 'NEW', date = DATE) {
  const progress = marker === 'NEW'
    ? { MID: 'none', __manualProgressMids: { MID: true }, __videoWatchCycles: { MID: { token: 'qa-cycle' } }, unknown: { nested: '한글 보존' } }
    : { MID: 'done', unknown: 'old response' };
  return {
    '/api/updates?readOnly=1': {
      [date]: { [sid]: { videos: [marker === 'NEW' ? 'MID_NEW' : 'MID_OLD'], source: 'manual', unknown: { keep: 'assignment metadata' } }, [sid === A ? B : A]: { videos: ['MID_OTHER'], source: 'manual' } },
      unknown: { keep: 'root update metadata' },
    },
    ['/api/logs/entry?date=' + date + '&sid=' + sid]: { ok: true, source: 'synthetic', entry: { notes: marker, unknown: { keep: 'log metadata' } } },
    '/api/extra-attend': { [date]: [sid], unknown: { keep: 'extra metadata' } },
    ['/api/progress?sid=' + sid]: {
      [date]: { [sid]: progress },
      [PRIOR]: { [sid]: { HIST: 'skip', unknown: 'history' } },
      [FUTURE]: { [sid]: { FUTURE_MID: 'done', unknown: 'future history' } },
    },
    ['/api/watch/latest?sid=' + sid]: { ok: true, sid, date: '', watch: { MID: { done: true, percent: 100, updatedAt: 1790812800000 } } },
  };
}

function fixture() {
  const h = makeHarness(true), ctx = h.contexts.videoModal;
  const ids = new Map(), feedback = [];
  class Element {
    constructor(id) {
      Object.assign(this, { id, dataset: {}, style: { display: 'none' }, disabled: false, textContent: '', hidden: false, isConnected: true, handlers: {} });
      const classes = new Set();
      this.classList = { add: (...xs) => xs.forEach(x => classes.add(x)), remove: (...xs) => xs.forEach(x => classes.delete(x)), contains: x => classes.has(x), toggle: (x, value) => value ? classes.add(x) : classes.delete(x) };
    }
    set innerHTML(value) {
      this.markup = String(value);
      if (this.id === 'chkZone' && this.markup.includes('id="videoLoadRetry"')) ids.set('videoLoadRetry', new Element('videoLoadRetry'));
    }
    get innerHTML() { return this.markup || ''; }
    addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
    fire(type, target = this) { return (this.handlers[type] || []).map(fn => fn({ target, currentTarget: this, preventDefault() {}, stopPropagation() {} })); }
    querySelector() { return null; } querySelectorAll() { return []; }
    getBoundingClientRect() { return { height: 100, top: 0 }; }
  }
  for (const id of ['vidModal', 'mTitle', 'chkZone', 'mSave', 'excludeHighDifficultyVideos', 'vidSavePopup', 'autoAssignCountToggle']) ids.set(id, new Element(id));
  Object.assign(ctx, { $: id => ids.get(id) || null, CT: { 'Content-Type': 'application/json' }, toast: x => feedback.push(x), alert: x => feedback.push(x), requestAnimationFrame() {} });
  ctx.document.getElementById = ctx.$;
  ctx.document.documentElement = new Element('html');
  ctx.document.body = new Element('body');
  ctx.window.clearTimeout = () => {};
  ctx.window.setTimeout = () => 1;
  Object.assign(ctx.state, initialState());
  // Rendering and course eligibility are outside this loader/readiness seam.
  // Keep the real data hydrators, authority cache, opener/close owner and saves.
  vm.runInContext([
    'ensureModal=()=>{};',
    'renderAutoAssignControl=()=>{};',
    'currentCurriculumVideosForStudent=()=>[];',
    'ensureExtraVideoFilters=()=>{};',
    'isTodayStudent=()=>false;',
    'resetVideoMultiSelectionState=()=>{};',
    'buildVideoAssignmentHtml=(videos,assigned)=>{window.qaAssigned=JSON.parse(JSON.stringify(assigned));return "rendered "+assigned.join(",");};',
    'window.qaActiveProgress=()=>JSON.parse(JSON.stringify(activeVideoProgress));',
  ].join('\n'), ctx);
  ctx.initVideoModal();
  const row = (sid = A, date = DATE) => ({ dataset: { sid, date }, closest() { return this; } });
  const finish = (request, body, status = 200, badJson = false) => request.gate.resolve({
    ok: status >= 200 && status < 300, status,
    json: async () => { if (badJson) throw new Error('synthetic bad JSON'); return clone(body); },
    text: async () => JSON.stringify(body),
  });
  const settle = (requests, map = payloads(), faulty = null) => requests.forEach(request => {
    if (faulty && request.url === faulty.url) {
      if (faulty.network) request.gate.reject(new Error('synthetic offline'));
      else finish(request, faulty.body, faulty.status || 200, faulty.badJson || false);
    } else finish(request, map[request.url]);
  });
  return { h, ctx, ids, feedback, row, finish, settle, open: (sid = A, date = DATE) => ctx.window.openVideoAssignmentPopupForRow(row(sid, date)), close: () => ctx.window.closeVideoAssignmentPopup() };
}

async function assertNoSaveOrCountCommand(f) {
  const beforeReads = f.h.reads.length, beforeStudents = clone(f.ctx.state.students);
  const originalFetch = f.ctx.fetch;
  let attempts = 0;
  f.ctx.fetch = async () => { attempts += 1; throw new Error('unexpected transport before authority'); };
  try {
    // External/unified code changing the button cannot substitute for authority.
    f.ids.get('mSave').disabled = false;
    await assert.rejects(f.ctx.window.saveVideoAssignmentPopup({ showPopup: false, refresh: false }), /불러|먼저/);
    await assert.rejects(f.ctx.saveAutoAssignCountForCurrent(6), /불러|먼저/);
    assert.equal(attempts, 0, 'programmatic save/count must not begin a read or write');
    assert.equal(f.h.reads.length, beforeReads);
    equal(f.ctx.state.students, beforeStudents, 'blocked count must not change student settings');
  } finally { f.ctx.fetch = originalFetch; }
}

const passed = [], failed = [];
async function check(name, fn) {
  try { await fn(); passed.push(name); }
  catch (error) { failed.push({ name, message: error.message }); }
}

await check('loading locks independent programmatic assignment and count commands', async () => {
  const f = fixture(), opening = f.open();
  equal(f.h.reads.map(r => r.url), urls(A));
  assert.equal(f.ids.get('mSave').disabled, true);
  await assertNoSaveOrCountCommand(f);
  f.settle(f.h.reads); await opening;
  assert.equal(f.ids.get('mSave').disabled, false);
});

for (const url of urls(A)) {
  for (const failure of ['http503', 'network']) {
    await check(failure + ' retains authority lock: ' + url, async () => {
      const f = fixture(), opening = f.open();
      equal(f.h.reads.map(r => r.url), urls(A));
      f.settle(f.h.reads, payloads(), { url, status: 503, body: { ok: false, error: 'unavailable' }, network: failure === 'network' });
      await opening;
      assert.equal(f.ids.get('mSave').disabled, true);
      assert.equal(f.ids.get('excludeHighDifficultyVideos').disabled, true);
      assert.match(f.ids.get('chkZone').innerHTML, /불러오지 못|실패/);
      await assertNoSaveOrCountCommand(f);
    });
  }
  for (const shape of [
    { name: 'null', body: null }, { name: 'primitive', body: 'not a map' },
    { name: 'array', body: [] }, { name: 'okFalse', body: { ok: false } },
    { name: 'badJson', body: {}, badJson: true },
  ]) {
    await check('malformed ' + shape.name + ': ' + url, async () => {
      const f = fixture(), opening = f.open();
      f.settle(f.h.reads, payloads(), { url, ...shape }); await opening;
      assert.equal(f.ids.get('mSave').disabled, true);
      await assertNoSaveOrCountCommand(f);
    });
  }
}

const nestedMalformed = [
  { url: urls(A)[0], name: 'wrapped update primitive', body: { ok: true, updates: 'bad' } },
  { url: urls(A)[0], name: 'wrapped update null', body: { ok: true, updates: null } },
  { url: urls(A)[0], name: 'wrapped update array', body: { ok: true, updates: [] } },
  { url: urls(A)[1], name: 'array log entry', body: { ok: true, entry: [] } },
  { url: urls(A)[1], name: 'primitive log entry', body: { ok: true, entry: 'bad entry' } },
  { url: urls(A)[2], name: 'wrapped extra array', body: { ok: true, extra: [] } },
  { url: urls(A)[2], name: 'wrapped extra primitive', body: { ok: true, extra: 'bad' } },
  { url: urls(A)[2], name: 'wrapped extra data array', body: { ok: true, data: [] } },
  { url: urls(A)[2], name: 'wrapped extra data null', body: { ok: true, data: null } },
  { url: urls(A)[2], name: 'invalid primary extra with valid alias', body: { ok: true, extra: 'bad', data: {} } },
  { url: urls(A)[3], name: 'wrapped progress array', body: { ok: true, progress: [] } },
  { url: urls(A)[3], name: 'wrapped progress data primitive', body: { ok: true, data: 'bad' } },
  { url: urls(A)[3], name: 'array progress day', body: { [DATE]: [] } },
  { url: urls(A)[3], name: 'array target progress entry', body: { [DATE]: { [A]: [] } } },
  { url: urls(A)[4], name: 'missing watch', body: { ok: true } },
  { url: urls(A)[4], name: 'array watch', body: { ok: true, watch: [] } },
];
for (const malformed of nestedMalformed) await check('malformed ' + malformed.name, async () => {
  const f = fixture(), opening = f.open();
  f.settle(f.h.reads, payloads(), malformed); await opening;
  assert.equal(f.ids.get('mSave').disabled, true);
  await assertNoSaveOrCountCommand(f);
});

for (const [url,key] of [[urls(A)[0],'updates'],[urls(A)[2],'data'],[urls(A)[3],'data']]) {
  await check('valid wrapped map ' + url, async () => {
    const f=fixture(),opening=f.open(),body=payloads();
    body[url]={ok:true,[key]:body[url]};
    f.settle(f.h.reads,body);await opening;
    assert.equal(f.ids.get('mSave').disabled,false,'supported map envelope remains writable');
  });
}
await check('actual retry click begins five fresh reads and recovers', async () => {
  const f = fixture(), opening = f.open();
  f.settle(f.h.reads, payloads(), { url: urls(A)[3], status: 503, body: { ok: false } });
  await opening; assert.equal(f.ids.get('mSave').disabled, true);
  const retry = f.ids.get('videoLoadRetry');
  assert.ok(retry && retry.handlers.click?.length === 1, 'failure shell owns one retry listener');
  retry.fire('click'); await flush();
  equal(f.h.reads.slice(5).map(r => r.url), urls(A));
  f.settle(f.h.reads.slice(5)); await flush();
  assert.equal(f.ids.get('mSave').disabled, false);
  equal(f.ctx.window.qaAssigned, ['MID_NEW']);
});

for (const oldOutcome of ['success', 'failure']) {
  await check('close suppresses old ' + oldOutcome + ' before state writes', async () => {
    const f = fixture(), before = clone(f.ctx.state), opening = f.open();
    f.close();
    f.settle(f.h.reads, payloads(A, 'OLD'), oldOutcome === 'failure' ? { url: urls(A)[3], status: 503, body: { ok: false } } : null);
    await opening;
    equal(f.ctx.state, before);
    assert.equal(f.ids.get('vidModal').style.display, 'none');
    await assertNoSaveOrCountCommand(f);
  });
  for (const target of [A, B]) {
    await check('A to ' + (target === A ? 'A reopen' : 'B switch') + ' ignores old ' + oldOutcome, async () => {
      const f = fixture(), old = f.open(); await flush();
      if (target === A) f.close();
      const fresh = f.open(target);
      equal(f.h.reads.slice(5).map(r => r.url), urls(target));
      f.settle(f.h.reads.slice(5), payloads(target)); await fresh;
      const accepted = clone(f.ctx.state), markup = f.ids.get('chkZone').innerHTML;
      f.settle(f.h.reads.slice(0, 5), payloads(A, 'OLD'), oldOutcome === 'failure' ? { url: urls(A)[3], status: 503, body: { ok: false } } : null);
      await old;
      equal(f.ctx.state, accepted);
      assert.equal(f.ids.get('chkZone').innerHTML, markup);
      assert.equal(f.ids.get('mSave').disabled, false);
      equal(f.ctx.window.qaAssigned, ['MID_NEW']);
    });
  }
}

await check('authority keeps literal history, unknown fields, manual white and other SID', async () => {
  const f = fixture(), opening = f.open(), map = payloads();
  f.settle(f.h.reads, map); await opening;
  equal(f.ctx.state.updates, map[urls(A)[0]]);
  equal(f.ctx.state.logs[DATE], { [A]: { notes: 'NEW', unknown: { keep: 'log metadata' } }, [B]: { notes: '다른 학생', unknown: 'other log' } });
  equal(f.ctx.state.progress, {
    [DATE]: { [A]: { MID: 'none', __manualProgressMids: { MID: true }, __videoWatchCycles: { MID: { token: 'qa-cycle' } }, unknown: { nested: '한글 보존' } }, [B]: { OTHER: 'skip', unknown: 'other current' } },
    [PRIOR]: { [A]: { HIST: 'skip', unknown: 'history' }, [B]: { OTHER: 'none', unknown: 'other prior' } },
    [STALE]: { [B]: { OTHER: 'interrupted', unknown: 'other stale' } },
    [FUTURE]: { [A]: { FUTURE_MID: 'done', unknown: 'future history' } },
  });
  assert.equal(f.ctx.window.qaActiveProgress().MID, 'none', 'completed watch cannot override manual white');
  assert.equal(f.ctx.window.qaActiveProgress().HIST, 'skip');
  assert.equal(f.ctx.window.qaActiveProgress().FUTURE_MID, undefined, 'future history is not current progress');
});

await check('authoritative empty maps remain successful and prune only requested SID', async () => {
  const f = fixture(), opening = f.open();
  const map = { [urls(A)[0]]: {}, [urls(A)[1]]: { ok: true, entry: {} }, [urls(A)[2]]: {}, [urls(A)[3]]: {}, [urls(A)[4]]: { ok: true, watch: {} } };
  f.settle(f.h.reads, map); await opening;
  assert.equal(f.ids.get('mSave').disabled, false);
  equal(f.ctx.state.progress, {
    [DATE]: { [A]: {}, [B]: { OTHER: 'skip', unknown: 'other current' } },
    [PRIOR]: { [B]: { OTHER: 'none', unknown: 'other prior' } },
    [STALE]: { [B]: { OTHER: 'interrupted', unknown: 'other stale' } },
  });
});

await check('open shares existing slow prefetch while settled open reads are fresh', async () => {
  const f = fixture();
  const prefetch = f.ctx.prefetchVideoModalDataForRow(f.row());
  f.h.advance(3000);
  const opening = f.open();
  equal(f.h.reads.map(r => r.url), urls(A));
  f.settle(f.h.reads); await Promise.all([prefetch, opening]);
  assert.equal(f.ids.get('mSave').disabled, false);
  f.close(); const reopened = f.open();
  equal(f.h.reads.slice(5).map(r => r.url), urls(A));
  f.settle(f.h.reads.slice(5)); await reopened;
  assert.equal(f.ids.get('mSave').disabled, false);
});

function countTransport(f) {
  const pending=[];
  f.ctx.fetch=(url,init={})=>{
    assert.equal(url,'/api/update');assert.equal(init.method,'POST');
    const body=JSON.parse(init.body);assert.equal(body.field,'autoVideoAssignCount');
    let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});pending.push({body,resolve,reject});return promise;
  };
  const source=fs.readFileSync(videoSource,'utf8');
  const start=source.indexOf('function renderAutoAssignControl('),end=source.indexOf('async function saveAutoAssignCountForCurrent(',start);
  assert.ok(start>=0&&end>start);
  vm.runInContext(source.slice(start,end)+'\neffectiveAutoAssignCountForStudent=stu=>autoAssignCountForStudent(stu);',f.ctx);
  return pending;
}
await check('count saves lock duplicates, restore failed field and allow retry',async()=>{
  const f=fixture(),opening=f.open();f.settle(f.h.reads);await opening;const pending=countTransport(f);
  const first=f.ctx.saveAutoAssignCountForCurrent(5),duplicate=f.ctx.saveAutoAssignCountForCurrent(6);
  const settled=Promise.allSettled([first,duplicate]);
  equal(pending.map(p=>p.body),[{id:A,field:'autoVideoAssignCount',value:5}]);
  assert.equal(f.ctx.state.students[0].autoVideoAssignCount,5);
  assert.equal((f.ids.get('autoAssignCountToggle').innerHTML.match(/disabled/g)||[]).length,6);
  pending[0].resolve({ok:false,status:503});assert.ok((await settled).every(item=>item.status==='rejected'));
  assert.equal(f.ctx.state.students[0].autoVideoAssignCount,2);assert.equal(f.ctx.state.students[1].autoVideoAssignCount,4);
  assert.equal((f.ids.get('autoAssignCountToggle').innerHTML.match(/disabled/g)||[]).length,0);
  const retry=f.ctx.saveAutoAssignCountForCurrent(3);pending[1].resolve({ok:true,status:200});await retry;
  assert.equal(f.ctx.state.students[0].autoVideoAssignCount,3);
});
await check('failed count keeps originally missing field absent',async()=>{
  const f=fixture();delete f.ctx.state.students[0].autoVideoAssignCount;f.ctx.state.students[0].unknown={keep:'한글'};
  const opening=f.open();f.settle(f.h.reads);await opening;const pending=countTransport(f);
  const saved=Promise.allSettled([f.ctx.saveAutoAssignCountForCurrent(6)]);pending[0].reject(new Error('injected count transport'));
  await saved;assert.equal(Object.hasOwn(f.ctx.state.students[0],'autoVideoAssignCount'),false);
  equal(f.ctx.state.students[0].unknown,{keep:'한글'});
});
for(const target of [A,B]) await check('pending count settlement after reopen '+target,async()=>{
  const f=fixture(),opening=f.open();f.settle(f.h.reads);await opening;
  const normalFetch=f.ctx.fetch,pending=countTransport(f),saved=Promise.allSettled([f.ctx.saveAutoAssignCountForCurrent(5)]);
  f.ctx.fetch=normalFetch;f.close();const reopened=f.open(target);f.settle(f.h.reads.slice(5),payloads(target));await reopened;
  const before=f.ids.get('autoAssignCountToggle').innerHTML;
  pending[0].resolve({ok:false,status:503});await saved;
  assert.equal(f.ctx.state.students[0].autoVideoAssignCount,2);
  if(target===A){
    assert.equal((f.ids.get('autoAssignCountToggle').innerHTML.match(/disabled/g)||[]).length,0);
    assert.match(f.ids.get('autoAssignCountToggle').innerHTML,/data-count="2" aria-pressed="true"/);
  } else { assert.equal(f.ids.get('autoAssignCountToggle').innerHTML,before);assert.equal(f.ctx.state.students[1].autoVideoAssignCount,4); }
});
// Restore real course rules and expose only checkbox DOM state. The witness is
// captured by the actual opener; no private readiness/witness setter is used.
function noopFixture() {
  const f = fixture(), zone = f.ids.get('chkZone'), boxes = [];
  const base = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(zone), 'innerHTML');
  Object.defineProperty(zone, 'innerHTML', {
    get() { return base.get.call(this); },
    set(value) {
      base.set.call(this, value);
      boxes.splice(0);
      if (String(value).startsWith('rendered ')) {
        for (const mid of f.ctx.window.qaAssigned) boxes.push({ value: String(mid), checked: true, closest: () => null });
      }
    },
  });
  const queryAll = f.ctx.document.querySelectorAll;
  f.ctx.document.querySelectorAll = selector => selector === '#chkZone input[type="checkbox"]'
    ? boxes : selector === '#chkZone input[type="checkbox"]:checked'
      ? boxes.filter(box => box.checked) : queryAll(selector);
  f.ctx.state.videos = [
    { mid: 'MID_NEW', title: '대수 영상', curriculum: '대수', chapter: 1 },
    { mid: 'MID_SECOND', title: '대수 다음 영상', curriculum: '대수', chapter: 2 },
    { mid: 'MID_OTHER', title: '다른 과목', curriculum: '공수1', chapter: 1 },
  ];
  f.ctx.todayLocalKey = () => DATE;
  vm.runInContext(fs.readFileSync(path.join(root, 'static/js/shared/videoSources.js'), 'utf8').replace(/\bexport\s+/g, ''), f.ctx);
  const source = fs.readFileSync(videoSource, 'utf8');
  vm.runInContext(source.slice(source.indexOf('function currentCurriculumVideosForStudent('), source.indexOf('function videoByMid(')), f.ctx);
  f.boxes = boxes;
  f.transport = [];
  f.ctx.getJSON = async url => {
    const res = await f.ctx.fetch(url, { cache: 'no-store' });
    return { res, data: await res.json() };
  };
  return f;
}
function noopPayload({ sid = A, date = DATE, source = 'manual', mids = ['MID_NEW'], entry = {} } = {}) {
  const map = payloads(sid, 'NEW', date);
  map[urls(sid, date)[0]][date][sid] = { videos: mids, source, unknown: { keep: '한글' } };
  map[urls(sid, date)[1]].entry = { notes: '그대로 보존', ...entry };
  return map;
}
async function openNoop(f, options = {}, transform = () => {}) {
  const map = noopPayload(options); transform(map);
  const before = f.h.reads.length, opening = f.open(options.sid || A, options.date || DATE);
  f.settle(f.h.reads.slice(before), map); await opening;
  assert.equal(f.ids.get('mSave').disabled, false);
  return map;
}
const noopOptions = { showPopup: false, refresh: false, skipUnchanged: true };
function failAtFirstTransport(f) {
  f.ctx.fetch = async (url, init = {}) => {
    f.transport.push({ url: String(url), method: init.method || 'GET' });
    throw new Error('synthetic save transport reached');
  };
}
for (const source of ['manual', 'auto']) await check('unified unchanged canonical ' + source + ' skips all transport and preserves state', async () => {
  const f = noopFixture(); await openNoop(f, { source });
  const before = clone(f.ctx.state); failAtFirstTransport(f);
  equal(await f.ctx.window.saveVideoAssignmentPopup(noopOptions), ['MID_NEW']);
  equal(f.transport, []); equal(f.ctx.state, before);
});
await check('explicit empty manual selection remains a valid unchanged snapshot', async () => {
  const f = noopFixture(); await openNoop(f, { mids: [] }); failAtFirstTransport(f);
  equal(await f.ctx.window.saveVideoAssignmentPopup(noopOptions), []); equal(f.transport, []);
});
const fallbackCases = [
  { name: 'empty auto must retain assignment-removal command', setup: { source: 'auto', mids: [] } },
  { name: 'future auto keeps existing server validation', setup: { source: 'auto', date: FUTURE } },
  { name: 'cross-course extras require generated-log handling', setup: { mids: ['MID_OTHER'] } },
  { name: 'extra generated note requires cleanup', setup: { entry: { extraVideoAssignmentNote: '[커리 외 영상]' } } },
  { name: 'empty extra array still requires explicit cleanup', setup: { entry: { assignedExtraVideos: [] } } },
  { name: 'unknown source needs normalization', setup: { source: 'legacy' } },
  { name: 'self-study source follows explicit save semantics', setup: { source: 'selfStudy' } },
  { name: 'legacy array needs normalization', transform: map => { map[urls(A)[0]][DATE][A] = ['MID_NEW']; } },
  { name: 'numeric MID needs normalization', setup: { mids: [123] } },
  { name: 'duplicate stored MIDs do not match real checkbox selection', setup: { mids: ['MID_NEW', 'MID_NEW'] }, mutate: f => { f.boxes.splice(1); } },
  { name: 'filtered auto snapshot must keep correction command', setup: { source: 'auto', mids: ['MID_NEW', 'MID_OTHER'] } },
  { name: 'selection clear is detected without a dirty flag', mutate: f => f.ctx.window.clearVideoAssignmentPopupForCurrent() },
  { name: 'selection order change cannot be skipped', setup: { mids: ['MID_NEW', 'MID_SECOND'] }, mutate: f => f.boxes.reverse() },
  { name: 'selection dirty even after restore keeps manual authority', mutate: f => f.ctx.markVideoSelectionDirty() },
  { name: 'log changes after open still need cleanup', mutate: f => { f.ctx.state.logs[DATE][A].assignedExtraVideos = []; } },
  { name: 'explicit manual option is a real command', options: { manual: true } },
  { name: 'explicit empty option is a real command', options: { forceEmpty: true } },
  { name: 'direct save without opt-in keeps original transport', options: { skipUnchanged: false } },
  { name: 'visible result request keeps original transport', options: { showPopup: true } },
  { name: 'refresh request keeps original transport', options: { refresh: true } },
];
for (const item of fallbackCases) await check('no-op conservative fallback: ' + item.name, async () => {
  const f = noopFixture(); await openNoop(f, item.setup, item.transform);
  item.mutate?.(f); failAtFirstTransport(f);
  await assert.rejects(f.ctx.window.saveVideoAssignmentPopup({ ...noopOptions, ...item.options }), /synthetic save transport/);
  assert.equal(f.transport.length, 1, 'first real preflight proves the command was not dropped');
});
await check('ambiguous write failure prevents an unchanged retry from being skipped', async () => {
  const f = noopFixture(), map = await openNoop(f);
  let failWrite = true;
  f.ctx.fetch = async (url, init = {}) => {
    f.transport.push({ url: String(url), method: init.method || 'GET' });
    if (url === '/api/updates/patch' && failWrite) throw new Error('ambiguous write response');
    const body = url === '/api/updates?readOnly=1' ? map[url]
      : url.startsWith('/api/logs/entry?') ? { ok: true, entry: map[urls(A)[1]].entry } : { ok: true };
    return { ok: true, status: 200, json: async () => clone(body) };
  };
  await assert.rejects(f.ctx.window.saveVideoAssignmentPopup({ ...noopOptions, skipUnchanged: false }), /ambiguous write response/);
  failWrite = false; f.transport.splice(0);
  await f.ctx.window.saveVideoAssignmentPopup(noopOptions);
  equal(f.transport, [
    { url: urls(A)[1], method: 'GET' }, { url: '/api/updates/patch', method: 'POST' },
    { url: '/api/updates?readOnly=1', method: 'GET' },
  ]);
  equal(f.ctx.state.updates, map[urls(A)[0]], 'unknown assignment metadata remains intact');
});
for (const sid of [A, B]) await check('close/reopen gets a fresh witness for ' + sid, async () => {
  const f = noopFixture(); await openNoop(f); failAtFirstTransport(f);
  await assert.rejects(f.ctx.window.saveVideoAssignmentPopup({ ...noopOptions, skipUnchanged: false }), /synthetic save transport/);
  f.ctx.fetch = f.h.contexts.logModal.fetch;
  f.close(); await openNoop(f, { sid, mids: sid === A ? ['MID_NEW'] : ['MID_OTHER'] });
  failAtFirstTransport(f); f.transport.splice(0);
  equal(await f.ctx.window.saveVideoAssignmentPopup(noopOptions), sid === A ? ['MID_NEW'] : ['MID_OTHER']);
  equal(f.transport, []);
});
function transitionRow(f, next) {
  const box = f.boxes[0];
  const row = { dataset: { mid: 'MID_NEW', state: 'done' },
    classList: { toggle() {} }, setAttribute() {},
    querySelector: selector => selector === 'input[type="checkbox"]' ? box : null };
  f.ctx.applyVideoRowState(row, next);
  return row;
}
for (const next of ['none', 'skip', 'assigned']) await check('unified opt-in keeps real video transition ' + next, async () => {
  const f = noopFixture();
  f.ctx.crypto = { randomUUID: () => 'qa_watch_cycle_001' };
  const map = await openNoop(f, {}, data => {
    data[urls(A)[3]][DATE][A] = { MID_NEW: 'done', __videoWatchCycles: { MID_NEW: { token: 'qa_previous_cycle_001' } } };
  });
  transitionRow(f, next);
  f.ctx.fetch = async (url, init = {}) => {
    f.transport.push({ url: String(url), method: init.method || 'GET', ...(init.body ? { body: JSON.parse(init.body) } : {}) });
    const body = url === '/api/progress/patch'
      ? { ok: true, progress: { MID_NEW: next === 'assigned' ? 'none' : next,
        __manualProgressMids: { MID_NEW: next !== 'assigned' },
        ...(next === 'assigned' ? { __videoWatchCycles: { MID_NEW: { token: 'qa_watch_cycle_001' } } } : {}) } }
      : url === '/api/updates?readOnly=1' ? map[url]
        : url.startsWith('/api/logs/entry?') ? { ok: true, entry: map[urls(A)[1]].entry } : { ok: true };
    return { ok: true, status: 200, headers: { get: key => key === 'X-Video-Watch-Cycles' ? '1' : null }, json: async () => clone(body) };
  };
  await f.ctx.window.saveVideoAssignmentPopup(noopOptions);
  const progressWrites = f.transport.filter(x => x.url === '/api/progress/patch');
  const expected = { date: DATE, sid: A, progress: { MID_NEW: next === 'assigned' ? 'none' : next } };
  if (next === 'assigned') expected.resumeAutoWatch = { MID_NEW: { token: 'qa_watch_cycle_001', baseToken: 'qa_previous_cycle_001' } };
  equal(progressWrites.map(x => x.body), [expected]);
  equal(f.transport.map(x => x.url), [
    ...(next === 'assigned' ? ['/api/progress?date=' + DATE + '&sid=' + A] : []),
    urls(A)[1], '/api/updates/patch', '/api/progress/patch', '/api/updates?readOnly=1',
  ]);
  assert.equal(f.ctx.state.progress[DATE][A].MID_NEW, next === 'assigned' ? 'none' : next);
  assert.equal(f.ctx.state.progress[DATE][A].__manualProgressMids.MID_NEW, next !== 'assigned');
});
await check('unified rearm retry keeps its generation after a post-progress failure', async () => {
  const f = noopFixture(); f.ctx.crypto = { randomUUID: () => 'qa_watch_cycle_002' };
  const map = await openNoop(f, { entry: { assignedExtraVideos: [] } }, data => {
    data[urls(A)[3]][DATE][A].__videoWatchCycles = { MID_NEW: { token: 'qa_previous_cycle_002' } };
  });
  transitionRow(f, 'assigned');
  let failLog = true;
  f.ctx.fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    f.transport.push({ url: String(url), method: init.method || 'GET', body });
    if (url === '/api/logs/patch' && failLog) throw new Error('post-progress log failure');
    const result = url === '/api/progress/patch'
      ? { ok: true, progress: { MID_NEW: 'none', __videoWatchCycles: { MID_NEW: { token: 'qa_watch_cycle_002' } } } }
      : url === '/api/updates?readOnly=1' ? map[url]
        : url.startsWith('/api/logs/entry?') ? { ok: true, entry: map[urls(A)[1]].entry } : { ok: true };
    return { ok: true, status: 200, headers: { get: () => '1' }, json: async () => clone(result) };
  };
  await assert.rejects(f.ctx.window.saveVideoAssignmentPopup(noopOptions), /post-progress log failure/);
  failLog = false; await f.ctx.window.saveVideoAssignmentPopup(noopOptions);
  const writes = f.transport.filter(x => x.url === '/api/progress/patch');
  assert.equal(writes.length, 2);
  for (const write of writes) equal(write.body.resumeAutoWatch, { MID_NEW: { token: 'qa_watch_cycle_002', baseToken: 'qa_previous_cycle_002' } });
  assert.equal(f.transport.filter(x => x.url === '/api/logs/patch').length, 2);
});
console.log(JSON.stringify({ verifier: 'video popup actual-source hydration', source: videoSource, sourceSha256: crypto.createHash('sha256').update(fs.readFileSync(videoSource)).digest('hex'), passed: passed.length, failed: failed.length, failures: failed, evidence: 'VM only; synthetic rendering/checkbox DOM/transport and real course rules; no HTTP, browser, runtime data or provider calls' }, null, 2));
if (failed.length) process.exitCode = 1;
