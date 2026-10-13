import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const watchSource = fs.readFileSync('static/js/student/watchState.js', 'utf8');
const studentSource = fs.readFileSync('static/js/student.js', 'utf8');
const htmlSource = fs.readFileSync('static/student.html', 'utf8');
const browserWindow = {};
vm.runInNewContext(watchSource, { Date, Math, Number, Object, Promise, String, window: browserWindow });

const api = browserWindow.StudentWatchState;
assert.ok(api && typeof api.createController === 'function', 'watch controller contract was not published');
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');

const requests = [];
const timers = new Map();
const storage = new Map();
let timerId = 0;
let currentMid = '';
let academyAccessAllowed = true;
let nextResponseOk = true;
let progressChangeCount = 0;
const nowMs = 1_787_390_000_123;

const controller = api.createController({
  storage: {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
    removeItem(key) { storage.delete(key); },
  },
  getSid: () => 'sid-a',
  getCanonicalSid: () => 'sid-a',
  getDate: () => '2026-08-24',
  getCurrentMid: () => currentMid,
  canSync: () => academyAccessAllowed,
  request: async (url, options) => {
    requests.push({ url, options, payload: JSON.parse(options.body) });
    return { ok: nextResponseOk };
  },
  headers: { 'Content-Type': 'application/json' },
  setTimer(callback, delay) {
    const id = ++timerId;
    timers.set(id, { callback, delay });
    return id;
  },
  clearTimer(id) { timers.delete(id); },
  now: () => nowMs,
  onProgressChange: () => { progressChangeCount += 1; },
});

const runPendingTimers = async () => {
  while (timers.size) {
    const [id, timer] = [...timers.entries()].sort((a, b) => a[1].delay - b[1].delay)[0];
    timers.delete(id);
    await timer.callback();
  }
};

const originalServerMap = {
  'mid-server': { last: 40, dur: 100, completed: false, updatedAt: nowMs - 100 },
};
const originalServerJson = JSON.stringify(originalServerMap);
const originalServerHash = sha256(originalServerJson);
controller.mergeServerWatchIntoLocal(originalServerMap);
assert.equal(JSON.stringify(originalServerMap), originalServerJson, 'server watch merge mutated its input');
assert.equal(sha256(JSON.stringify(originalServerMap)), originalServerHash, 'server watch input hash changed');
assert.equal(
  JSON.stringify(controller.getProgress('mid-server')),
  JSON.stringify({ last: 40, dur: 100, completed: false, updatedAt: nowMs }),
  'server watch merge changed the literal local projection',
);
await controller.syncNow('mid-server');
assert.equal(requests.length, 0, 'fresh server state must seed duplicate-send suppression');

controller.setProgress('mid-a', { last: 5, dur: 100, completed: false });
assert.equal(timers.size, 2, 'watch progress must schedule a trailing sync and bounded deadline');
controller.setProgress('mid-a', { last: 10, dur: 100, completed: false });
assert.equal(timers.size, 2, 'new progress must replace only the trailing timer');
await runPendingTimers();
assert.equal(requests.length, 1, 'debounced progress must emit one request');
assert.equal(requests[0].url, '/api/watch', 'autosave must use the canonical watch endpoint');
assert.deepEqual(requests[0].payload, {
  date: '2026-08-24',
  sid: 'sid-a',
  mid: 'mid-a',
  last: 10,
  dur: 100,
  completed: false,
  updatedAt: nowMs,
}, 'autosave payload changed');

await controller.syncNow('mid-a');
assert.equal(requests.length, 1, 'unchanged watch state must not be sent twice');

nextResponseOk = false;
controller.setProgress('mid-a', { last: 20, dur: 100 });
await runPendingTimers();
assert.equal(requests.length, 2, 'a changed watch state must be sent');
nextResponseOk = true;
await controller.syncNow('mid-a');
assert.equal(requests.length, 3, 'a failed watch save must remain retryable');

controller.setProgress('mid-a', { last: 90, dur: 100, completed: true });
await runPendingTimers();
assert.equal(requests.at(-1).payload.completed, true, '90 percent must be sent as completed');

currentMid = 'mid-a';
controller.setProgress('mid-a', { last: 95, dur: 100 });
await controller.flushSyncQueue({ keepalive: true });
assert.equal(requests.at(-1).options.keepalive, true, 'explicit flush must use keepalive');

const beforeBlocked = requests.length;
academyAccessAllowed = false;
controller.setProgress('mid-blocked', { last: 30, dur: 100 });
await runPendingTimers();
assert.equal(requests.length, beforeBlocked, 'outside-academy progress must not reach the watch endpoint');

controller.setLastMid('mid-a');
assert.equal(controller.getLastMid(), 'mid-a', 'last-video resume key changed');
controller.clearProgress('mid-a');
assert.equal(controller.getProgress('mid-a'), null, 'explicit stale-watch clearing must remove only the target MID');
assert.ok(controller.getProgress('mid-server'), 'targeted clearing removed an unrelated MID');
assert.ok(progressChangeCount >= 5, 'progress change callback did not observe local updates');

// Independent clock oracle: uninterrupted one-second events never reach quiet time.
const continuousStorage = new Map();
const clockTimers = new Map();
const continuousRequests = [];
let elapsed = 0;
let clockTimerId = 0;
const continuous = api.createController({
  storage: {
    getItem: key => continuousStorage.get(key) || null,
    setItem: (key, value) => continuousStorage.set(key, value),
    removeItem: key => continuousStorage.delete(key),
  },
  getSid: () => 'continuous-sid', getCanonicalSid: () => 'continuous-sid',
  getDate: () => '2026-10-02', getCurrentMid: () => 'continuous-mid',
  canSync: () => true, now: () => nowMs + elapsed,
  request: async (url, options) => {
    continuousRequests.push({ url, payload: JSON.parse(options.body), keepalive: options.keepalive });
    return { ok: true };
  },
  setTimer(callback, delay) {
    const id = ++clockTimerId;
    clockTimers.set(id, { callback, due: elapsed + delay });
    return id;
  },
  clearTimer: id => clockTimers.delete(id),
});
async function advanceClock(target) {
  while (true) {
    const next = [...clockTimers.entries()].filter(([, timer]) => timer.due <= target)
      .sort((a, b) => a[1].due - b[1].due)[0];
    if (!next) break;
    elapsed = next[1].due;
    clockTimers.delete(next[0]);
    await next[1].callback();
  }
  elapsed = target;
}
for (let second = 0; second < 10; second += 1) {
  await advanceClock(second * 1000);
  continuous.setProgress('continuous-mid', { last: second + 1, dur: 100 });
}
assert.equal(continuousRequests.length, 0, 'continuous events must retain trailing debounce');
await advanceClock(10000);
assert.equal(continuousRequests.length, 1, 'uninterrupted playback must save within ten seconds');
assert.equal(continuousRequests[0].payload.last, 10, 'bounded save must use the latest actual observation');
assert.equal(clockTimers.size, 0, 'bounded save must cancel the trailing callback');
continuous.setProgress('continuous-mid', { last: 11, dur: 100 });
await advanceClock(11499);
assert.equal(continuousRequests.length, 1, 'quiet trailing save must wait 1500ms');
await advanceClock(11500);
assert.equal(continuousRequests.length, 2, 'quiet trailing save remains available');
continuous.setProgress('continuous-mid', { last: 12, dur: 100 });
await continuous.flushSyncQueue({ keepalive: true });
assert.equal(continuousRequests.at(-1).keepalive, true);
assert.equal(clockTimers.size, 0, 'pagehide flush must cancel both schedules');
await advanceClock(30000);
assert.equal(continuousRequests.length, 3, 'cancelled timers must never duplicate a flush');
continuous.setProgress('continuous-mid', { last: 13, dur: 100 });
continuous.clearProgress('continuous-mid');
assert.equal(clockTimers.size, 0, 'target clearing must retire both pending schedules');

const lifecycleStart = studentSource.indexOf('  function flushCurrentWatch()');
const lifecycleEnd = studentSource.indexOf('  /* ───────────── 설정 패널 & 다크모드 ───────────── */', lifecycleStart);
if (lifecycleStart < 0 || lifecycleEnd < 0) throw new Error('watch lifecycle wiring was not found');
const lifecycleListeners = { window: new Map(), document: new Map() };
const flushCalls = [];
const lifecycleContext = {
  flushSyncQueue(options) { flushCalls.push(options); return Promise.resolve(); },
  window: {
    addEventListener(type, callback) { lifecycleListeners.window.set(type, callback); },
  },
  document: {
    visibilityState: 'visible',
    addEventListener(type, callback) { lifecycleListeners.document.set(type, callback); },
  },
};
vm.runInNewContext(studentSource.slice(lifecycleStart, lifecycleEnd), lifecycleContext);
lifecycleListeners.window.get('pagehide')();
lifecycleContext.document.visibilityState = 'hidden';
lifecycleListeners.document.get('visibilitychange')();
assert.equal(
  JSON.stringify(flushCalls),
  JSON.stringify([{ keepalive: true }, { keepalive: true }]),
  'page lifecycle flush contract changed',
);

for (const forbidden of ['document.', 'localStorage', 'addEventListener']) {
  assert.equal(watchSource.includes(forbidden), false, `watch module must stay DOM/ambient-storage free: ${forbidden}`);
}
assert.equal(studentSource.includes("studentAppRequest('/api/watch'"), false, 'student entrypoint duplicated watch transport');
assert.ok(watchSource.includes("request('/api/watch'"), 'watch module must own the canonical watch transport');
const bootstrapScript = '/js/student/bootstrapState.js?v=20260828-bootstrap-state-r1';
const watchScript = '/js/student/watchState.js?v=20261002-native-watch1';
const playbackScript = '/js/student/playback.js?v=20261002-native-watch1';
const reviewPlaylistScript = '/js/student/reviewPlaylist.js?v=20260828-review-playlist-r1';
const announcementStateScript = '/js/student/announcementState.js?v=20260828-announcement-state-r1';
const testPresentationScript = '/js/student/testPresentation.js?v=20260907-ilsan-level-r1';
const studentScript = '/js/student.js?v=20260907-ilsan-level-r1';
assert.ok(htmlSource.indexOf(bootstrapScript) < htmlSource.indexOf(watchScript), 'watch module must follow bootstrap state');
assert.ok(htmlSource.indexOf(watchScript) < htmlSource.indexOf(playbackScript), 'watch module must precede playback');
assert.ok(htmlSource.indexOf(playbackScript) < htmlSource.indexOf(reviewPlaylistScript), 'playback must precede review playlist');
assert.ok(htmlSource.indexOf(reviewPlaylistScript) < htmlSource.indexOf(announcementStateScript), 'review playlist must precede announcement state');
assert.ok(htmlSource.indexOf(announcementStateScript) < htmlSource.indexOf(testPresentationScript), 'announcement state must precede test presentation');
assert.ok(htmlSource.indexOf(testPresentationScript) < htmlSource.indexOf(studentScript), 'test presentation must precede the student entrypoint');

console.log('student watch state/autosave checks passed: literal merge, retry, flush, access gate, and shell order');
