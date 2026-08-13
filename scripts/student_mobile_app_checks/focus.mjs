import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..', '..');
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8');

class FakeNode {
  constructor(id = '') {
    this.id = id;
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
    this.isConnected = true;
    this.listeners = new Map();
    this.classList = { add() {}, remove() {} };
  }

  addEventListener(type, handler) { this.listeners.set(type, handler); }
  querySelector(selector) { return selector === '.student-focus-sheet' ? this.sheet : null; }
  querySelectorAll() { return []; }
  setAttribute() {}
  focus() { this.owner.activeElement = this; }
  click() { this.listeners.get('click')?.({ target: this, preventDefault() {} }); }
}

function fakeDom() {
  const ids = [
    'studentFocusLauncher', 'studentFocusStart', 'studentFocusLauncherStatus', 'studentFocusModal',
    'studentFocusLiveStatus', 'studentFocusTime', 'studentFocusHiddenCount', 'studentFocusHiddenTime',
    'studentFocusLongestHidden', 'studentFocusRemaining', 'studentFocusEndConfirm', 'studentFocusMinimize',
    'studentFocusEnd', 'studentFocusEndCancel', 'studentFocusEndConfirmButton',
  ];
  const nodes = Object.fromEntries(ids.map(id => [id, new FakeNode(id)]));
  const documentListeners = new Map();
  const body = new FakeNode('body');
  const doc = {
    visibilityState: 'visible', activeElement: null, body,
    getElementById: id => nodes[id] || null,
    addEventListener: (type, handler) => documentListeners.set(type, handler),
  };
  const sheet = new FakeNode('sheet');
  nodes.studentFocusModal.sheet = sheet;
  Object.values(nodes).forEach(node => { node.owner = doc; });
  body.owner = doc;
  sheet.owner = doc;
  const windowListeners = new Map();
  const win = {
    HTMLElement: FakeNode,
    setInterval: () => 1,
    clearInterval() {},
    addEventListener: (type, handler) => windowListeners.set(type, handler),
  };
  return { doc, win, nodes, documentListeners, windowListeners };
}

function studentFocusApi() {
  const source = read('static/js/student-focus.js');
  const window = {};
  vm.runInNewContext(source, { window, console, Date, URLSearchParams, setTimeout, clearTimeout }, { filename: 'student-focus.js' });
  return window.StudentFocus;
}

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

async function settle() {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
}

async function lifecycleCheck() {
  const api = studentFocusApi();
  const { doc, win, nodes, documentListeners, windowListeners } = fakeDom();
  const schedule = {
    kind: 'regular', date: '2026-08-10', startAt: '2026-08-10T18:00:00+09:00',
    endAt: '2026-08-10T20:00:00+09:00', timeLabel: '18:00', slots: [2],
  };
  let now = Date.parse(schedule.startAt);
  let session = null;
  let lastAt = now;
  const calls = [];
  const snapshot = () => session ? { ...session, schedule: { ...schedule } } : null;
  const currentBody = () => ({
    ok: true, serverNow: new Date(now).toISOString(),
    eligibility: { state: session ? 'eligible' : 'eligible', opensAt: '2026-08-10T17:30:00+09:00', closesAt: schedule.endAt, schedule },
    session: snapshot(),
  });
  const mutation = extra => ({ ok: true, serverNow: new Date(now).toISOString(), session: snapshot(), ...extra });

  async function request(url, init = {}) {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, body, keepalive: init.keepalive === true });
    if (url.endsWith('/current')) return response(currentBody());
    if (url.endsWith('/start')) {
      session = {
        id: 'fcs_abcdefghijklmnopqrstuvwxyz012345', state: 'active', startedAt: new Date(now).toISOString(), endedAt: null,
        lastSeq: 0, visibility: 'visible', focusMs: 0, hiddenCount: 0, hiddenMs: 0,
        longestHiddenMs: 0, unknownMs: 0, schedule,
      };
      lastAt = now;
      return response(mutation({ resumed: false }), 201);
    }
    if (url.endsWith('/events')) {
      body.events.forEach(event => {
        const delta = now - lastAt;
        if (event.type === 'unknown' || session.visibility === 'unknown') session.unknownMs += delta;
        else if (session.visibility === 'visible' && event.type === 'hidden') {
          session.focusMs += delta;
          session.hiddenCount += 1;
        } else if (session.visibility === 'hidden' && event.type === 'visible') {
          session.hiddenMs += delta;
          session.longestHiddenMs = Math.max(session.longestHiddenMs, delta);
        }
        session.visibility = event.type;
        session.lastSeq = event.seq;
        lastAt = now;
      });
      return response(mutation({}));
    }
    if (url.endsWith('/end')) {
      const delta = now - lastAt;
      if (session.visibility === 'visible') session.focusMs += delta;
      else if (session.visibility === 'hidden') {
        session.hiddenMs += delta;
        session.longestHiddenMs = Math.max(session.longestHiddenMs, delta);
      } else session.unknownMs += delta;
      session.state = 'finished';
      session.visibility = 'unknown';
      session.lastSeq = body.seq;
      session.endedAt = new Date(now).toISOString();
      return response(mutation({}));
    }
    return response({ ok: false, code: 'not_found' }, 404);
  }

  const controller = api.createController({ documentRef: doc, windowRef: win, request, clock: () => now });
  await controller.load();
  nodes.studentFocusStart.click();
  await settle();
  assert.equal(controller.state().session.state, 'active');

  now += 10 * 60_000;
  doc.visibilityState = 'hidden';
  documentListeners.get('visibilitychange')();
  windowListeners.get('pagehide')();
  await settle();
  assert.equal(calls.filter(call => call.url.endsWith('/events')).length, 1, 'hidden+pagehide was not coalesced');
  assert.equal(calls.find(call => call.url.endsWith('/events')).keepalive, true, 'hidden transition did not use keepalive');

  now += 2 * 60_000;
  doc.visibilityState = 'visible';
  documentListeners.get('visibilitychange')();
  windowListeners.get('pageshow')();
  await settle();
  now += 8 * 60_000;
  nodes.studentFocusEnd.click();
  nodes.studentFocusEndConfirmButton.click();
  await settle();
  const final = controller.state().session;
  assert.deepEqual(
    [final.focusMs, final.hiddenCount, final.hiddenMs, final.longestHiddenMs],
    [1_080_000, 1, 120_000, 120_000],
  );
  assert.equal(nodes.studentFocusTime.textContent, '18분');
  const eventBodies = calls.filter(call => call.url.endsWith('/events')).map(call => call.body);
  assert.equal(JSON.stringify(eventBodies).match(/url|appName|notification|clientAt|duration/gi), null, 'client sent a forbidden focus field');
  return { api, final };
}

async function inFlightOrderingCheck() {
  const api = studentFocusApi();
  const { doc, win, nodes, documentListeners } = fakeDom();
  const schedule = {
    kind: 'regular', date: '2026-08-10', startAt: '2026-08-10T18:00:00+09:00',
    endAt: '2026-08-10T20:00:00+09:00', timeLabel: '18:00', slots: [2],
  };
  const now = Date.parse(schedule.startAt);
  let session = null;
  const releases = [];
  const eventBodies = [];
  const snapshot = () => session ? { ...session, schedule: { ...schedule } } : null;
  const mutation = extra => ({ ok: true, serverNow: new Date(now).toISOString(), session: snapshot(), ...extra });
  const applyEvents = events => {
    for (const event of events) {
      session.visibility = event.type;
      session.lastSeq = event.seq;
    }
  };

  async function request(url, init = {}) {
    const body = init.body ? JSON.parse(init.body) : null;
    if (url.endsWith('/current')) {
      return response({
        ok: true, serverNow: new Date(now).toISOString(),
        eligibility: { state: 'eligible', opensAt: '2026-08-10T17:30:00+09:00', closesAt: schedule.endAt, schedule },
        session: snapshot(),
      });
    }
    if (url.endsWith('/start')) {
      session = {
        id: 'fcs_abcdefghijklmnopqrstuvwxyz012345', state: 'active', startedAt: new Date(now).toISOString(), endedAt: null,
        lastSeq: 0, visibility: 'visible', focusMs: 0, hiddenCount: 0, hiddenMs: 0,
        longestHiddenMs: 0, unknownMs: 0, schedule,
      };
      return response(mutation({ resumed: false }), 201);
    }
    if (url.endsWith('/events')) {
      eventBodies.push(body);
      if (eventBodies.length <= 2) {
        return new Promise(resolve => releases.push(() => {
          applyEvents(body.events);
          resolve(response(mutation({})));
        }));
      }
      applyEvents(body.events);
      return response(mutation({}));
    }
    return response({ ok: false, code: 'not_found' }, 404);
  }

  const controller = api.createController({ documentRef: doc, windowRef: win, request, clock: () => now });
  await controller.load();
  nodes.studentFocusStart.click();
  await settle();
  doc.visibilityState = 'hidden';
  documentListeners.get('visibilitychange')();
  await settle();
  doc.visibilityState = 'visible';
  documentListeners.get('visibilitychange')();
  await settle();
  releases.shift()();
  await settle();
  assert.equal(eventBodies.length, 2, 'queued visible transition did not start after hidden acknowledgement');
  doc.visibilityState = 'hidden';
  documentListeners.get('visibilitychange')();
  await settle();
  releases.shift()();
  await settle();
  assert.deepEqual(
    eventBodies.map(item => item.events[0]),
    [{ seq: 1, type: 'hidden' }, { seq: 2, type: 'visible' }, { seq: 3, type: 'hidden' }],
    'in-flight acknowledgement rewound the predicted visibility state',
  );
}

async function endRaceCheck() {
  const api = studentFocusApi();
  const { doc, win, nodes, documentListeners } = fakeDom();
  const schedule = {
    kind: 'regular', date: '2026-08-10', startAt: '2026-08-10T18:00:00+09:00',
    endAt: '2026-08-10T20:00:00+09:00', timeLabel: '18:00', slots: [2],
  };
  const now = Date.parse(schedule.startAt);
  let session = null;
  let releaseEnd = null;
  const eventBodies = [];
  const snapshot = () => session ? { ...session, schedule: { ...schedule } } : null;
  const mutation = extra => ({ ok: true, serverNow: new Date(now).toISOString(), session: snapshot(), ...extra });
  async function request(url, init = {}) {
    const body = init.body ? JSON.parse(init.body) : null;
    if (url.endsWith('/current')) {
      return response({
        ok: true, serverNow: new Date(now).toISOString(),
        eligibility: { state: 'eligible', opensAt: '2026-08-10T17:30:00+09:00', closesAt: schedule.endAt, schedule },
        session: snapshot(),
      });
    }
    if (url.endsWith('/start')) {
      session = {
        id: 'fcs_abcdefghijklmnopqrstuvwxyz012345', state: 'active', startedAt: new Date(now).toISOString(), endedAt: null,
        lastSeq: 0, visibility: 'visible', focusMs: 0, hiddenCount: 0, hiddenMs: 0,
        longestHiddenMs: 0, unknownMs: 0, schedule,
      };
      return response(mutation({ resumed: false }), 201);
    }
    if (url.endsWith('/events')) {
      eventBodies.push(body);
      return response({ ok: false, code: 'focus_sequence_conflict' }, 409);
    }
    if (url.endsWith('/end')) {
      return new Promise(resolve => { releaseEnd = () => {
        session = { ...session, state: 'finished', visibility: 'unknown', endedAt: new Date(now).toISOString(), lastSeq: body.seq };
        resolve(response(mutation({})));
      }; });
    }
    return response({ ok: false, code: 'not_found' }, 404);
  }

  const controller = api.createController({ documentRef: doc, windowRef: win, request, clock: () => now });
  await controller.load();
  nodes.studentFocusStart.click();
  await settle();
  nodes.studentFocusEnd.click();
  nodes.studentFocusEndConfirmButton.click();
  await settle();
  assert.equal(typeof releaseEnd, 'function', 'explicit end request did not start');
  doc.visibilityState = 'hidden';
  documentListeners.get('visibilitychange')();
  await settle();
  assert.equal(eventBodies.length, 0, 'visibility transition raced an in-flight explicit end');
  releaseEnd();
  await settle();
  assert.equal(controller.state().session.state, 'finished');
}

export async function runChecks() {
  let checks = 0;
  const html = read('static/student.html');
  const css = read('static/css/student.css');
  const source = read('static/js/student-focus.js');
  const student = read('static/js/student.js');
  const adminHtml = read('static/admin.html');
  const adminFeature = read('static/js/admin/features/studentFocus.js');
  const adminMain = read('static/js/admin/main.js');
  const demoData = read('static/js/admin/demo/data.js');
  const demoStore = read('static/js/admin/demo/store.js');
  const demoFetch = read('static/js/admin/demo/fetch.js');
  const demoBootstrap = read('static/js/admin/demo/bootstrap.js');

  for (const id of ['studentFocusLauncher', 'studentFocusStart', 'studentFocusModal', 'studentFocusRemaining', 'studentFocusEnd', 'studentFocusEndConfirmButton']) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(html, /전화·잠금·권한창과 앱 전환을 구분할 수 없어/);
  assert.match(html, /다른 앱 이름이나 방문 URL은 수집하지 않습니다/);
  checks += 1;

  assert.match(css, /body\.student-page\.student-app-mobile-surface \.student-focus-modal/);
  assert.match(css, /min-height:\s*100dvh/);
  assert.match(css, /env\(safe-area-inset-(?:top|right|bottom|left)\)/);
  assert.match(css, /#studentFocusMinimize[\s\S]*min-height:\s*44px/);
  checks += 1;

  assert.match(source, /visibilitychange/);
  assert.match(source, /pagehide/);
  assert.match(source, /pageshow/);
  assert.match(source, /keepalive/);
  assert.doesNotMatch(source, /\b(?:localStorage|sessionStorage|indexedDB|sendBeacon|document\.title|document\.referrer|location\.href)\b/);
  assert.match(source, /JSON\.stringify\(\{\s*sessionId:\s*session\.id,\s*events\s*\}\)/);
  checks += 1;

  assert.match(student, /initStudentFocusController\(\)/);
  assert.match(student, /request:\s*studentAppRequest/);
  assert.match(student, /makeSessionError:/);
  checks += 1;

  const { final } = await lifecycleCheck();
  await inFlightOrderingCheck();
  await endRaceCheck();
  assert.equal(final.state, 'finished');
  checks += 1;

  const adminModule = await import(`${pathToFileURL(path.join(root, 'static/js/admin/features/studentFocus.js')).href}?focus=${Date.now()}`);
  assert.equal(adminModule.__test.duration(final.focusMs), '18분');
  assert.ok(adminModule.__test.normalizePayload({
    ok: true, date: '2026-08-10', serverNow: '2026-08-10T18:20:00+09:00',
    classes: [{
      classId: 'fcl_ABCDEFGHIJKLMNOPQRSTUVWX', kind: 'regular',
      startAt: '2026-08-10T18:00:00+09:00', endAt: '2026-08-10T20:00:00+09:00',
      sessions: [{
        sid: 'sid-a', name: '학생A', school: '테스트고', grade: '1', state: 'finished',
        startedAt: '2026-08-10T18:00:00+09:00', endedAt: '2026-08-10T18:20:00+09:00',
        focusMs: 1_080_000, hiddenCount: 1, hiddenMs: 120_000, longestHiddenMs: 120_000, unknownMs: 0,
      }],
    }],
  }), 'admin rejected the SID-independent class identifier');
  assert.match(adminFeature, /원시 전환 기록은 표시하지 않습니다/);
  assert.doesNotMatch(adminFeature, /focus\/events|student_focus_events/);
  checks += 1;

  for (const id of ['studentFocusOpen', 'studentFocusAdminModal', 'studentFocusAdminClose', 'studentFocusAdminDate', 'studentFocusAdminList']) {
    assert.match(adminHtml, new RegExp(`id=["']${id}["']`));
  }
  assert.match(adminMain, /import\s+\{\s*initStudentFocus\s*\}.*studentFocus\.js/);
  assert.match(adminMain, /initStudentFocus\(\)/);
  assert.match(adminFeature, /modal\.style\.display\s*=\s*['"]flex['"]/,
    'focus modal open must override the shared display:none backdrop rule');
  assert.match(adminFeature, /modal\.style\.display\s*=\s*['"]none['"]/,
    'focus modal close must restore the hidden backdrop display');
  checks += 1;

  assert.match(demoData, /focusSummaries:/);
  assert.match(demoStore, /DEMO_SCHEMA_VERSION\s*=\s*3/);
  assert.match(demoStore, /store\.focusSummaries/);
  assert.match(demoFetch, /\/api\/admin\/student-focus\/summary/);
  assert.match(demoBootstrap, /\/api\/admin\/student-focus\/summary/);
  checks += 1;

  const normalized = studentFocusApi().normalizeCurrent({
    ok: true,
    serverNow: '2026-08-10T18:00:00+09:00',
    eligibility: {
      state: 'eligible', opensAt: '2026-08-10T17:30:00+09:00', closesAt: '2026-08-10T20:00:00+09:00',
      schedule: { kind: 'regular', date: '2026-08-10', startAt: '2026-08-10T18:00:00+09:00', endAt: '2026-08-10T20:00:00+09:00', timeLabel: '18:00', slots: [2] },
    },
    session: null,
  });
  assert.ok(normalized);
  assert.equal(studentFocusApi().normalizeCurrent({ ...normalized, sid: 'forbidden' }), null);
  checks += 1;

  return { checks };
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const result = await runChecks();
  console.log(`focus: ${result.checks} assertions passed`);
}

export default runChecks;
