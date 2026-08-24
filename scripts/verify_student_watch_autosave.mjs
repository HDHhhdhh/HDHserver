import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/js/student.js', 'utf8');
const syncStart = source.indexOf('  const LSKeys = {');
const syncEnd = source.indexOf('  /* ───────────── 설정 패널 & 다크모드 ───────────── */', syncStart);
if (syncStart < 0 || syncEnd < 0) throw new Error('student watch autosave block was not found');

const requests = [];
const listeners = { window: new Map(), document: new Map() };
const timers = new Map();
const storage = new Map();
let timerId = 0;
let nextResponseOk = true;

const context = {
  console,
  Map,
  Set,
  Promise,
  Date,
  JSON,
  Number,
  Math,
  String,
  Object,
  encodeURIComponent,
  localStorage: {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
    removeItem(key) { storage.delete(key); },
  },
  setTimeout(callback) {
    const id = ++timerId;
    timers.set(id, callback);
    return id;
  },
  clearTimeout(id) { timers.delete(id); },
  window: {
    addEventListener(type, callback) { listeners.window.set(type, callback); },
  },
  document: {
    visibilityState: 'visible',
    addEventListener(type, callback) { listeners.document.set(type, callback); },
  },
};
context.globalThis = context;
context.requests = requests;
Object.defineProperty(context, 'nextResponseOk', {
  get: () => nextResponseOk,
  set: value => { nextResponseOk = !!value; },
});

const prefix = [
  "let sid = 'sid-a';",
  "let currentMid = '';",
  "let academyAccessAllowed = true;",
  "let stuCache = { id: 'sid-a' };",
  "const CT = { 'Content-Type': 'application/json' };",
  "function todayLocalKey() { return '2026-08-24'; }",
  "function updateListCompletionBadges() {}",
  "function getAssignedVideos() { return []; }",
  "function studentDataDateKey() { return '2026-08-24'; }",
  "function $(id) { return null; }",
  "async function studentAppRequest(url, options) {",
  "  requests.push({ url, options, payload: JSON.parse(options.body) });",
  "  return { ok: nextResponseOk };",
  "}",
].join('\n');
const suffix = [
  'globalThis.__watchHarness = {',
  '  setProgress,',
  '  getProgress,',
  '  doSync,',
  '  flushSyncQueue,',
  '  setCurrentMid(value) { currentMid = value; },',
  '  setAcademyAllowed(value) { academyAccessAllowed = value; },',
  '};',
].join('\n');
vm.runInNewContext(prefix + '\n' + source.slice(syncStart, syncEnd) + '\n' + suffix, context);

const harness = context.__watchHarness;
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const runPendingTimers = async () => {
  const callbacks = [...timers.values()];
  timers.clear();
  await Promise.all(callbacks.map(callback => callback()));
};

harness.setProgress('mid-a', { last: 5, dur: 100, completed: false });
assert(timers.size === 1, 'watch progress must schedule one debounced sync');
harness.setProgress('mid-a', { last: 10, dur: 100, completed: false });
assert(timers.size === 1, 'new progress must replace the existing debounce timer');
await runPendingTimers();
assert(requests.length === 1, 'debounced progress must emit one request');
assert(requests[0].url === '/api/watch', 'autosave must use the canonical watch endpoint');
assert(requests[0].payload.date === '2026-08-24', 'autosave must use the current local date');
assert(requests[0].payload.sid === 'sid-a' && requests[0].payload.mid === 'mid-a', 'autosave identity changed');
assert(requests[0].payload.last === 10 && requests[0].payload.dur === 100, 'autosave did not send the merged furthest position');
assert(requests[0].payload.updatedAt >= 1_000_000_000_000, 'autosave timestamp is not epoch milliseconds');

await harness.doSync('mid-a');
assert(requests.length === 1, 'unchanged watch state must not be sent twice');

context.nextResponseOk = false;
harness.setProgress('mid-a', { last: 20, dur: 100 });
await runPendingTimers();
assert(requests.length === 2, 'a changed watch state must be sent');
context.nextResponseOk = true;
await harness.doSync('mid-a');
assert(requests.length === 3, 'a failed watch save must remain retryable');

harness.setProgress('mid-a', { last: 90, dur: 100, completed: true });
await runPendingTimers();
assert(requests.at(-1).payload.completed === true, '90 percent must be sent as completed');

harness.setCurrentMid('mid-a');
harness.setProgress('mid-a', { last: 95, dur: 100 });
listeners.window.get('pagehide')();
await new Promise(resolve => setTimeout(resolve, 0));
assert(requests.at(-1).options.keepalive === true, 'pagehide flush must use keepalive');

harness.setProgress('mid-a', { last: 96, dur: 100 });
context.document.visibilityState = 'hidden';
listeners.document.get('visibilitychange')();
await new Promise(resolve => setTimeout(resolve, 0));
assert(requests.at(-1).options.keepalive === true, 'hidden-page flush must use keepalive');

const beforeBlocked = requests.length;
harness.setAcademyAllowed(false);
harness.setProgress('mid-blocked', { last: 30, dur: 100 });
await runPendingTimers();
assert(requests.length === beforeBlocked, 'outside-academy progress must not reach the watch endpoint');

const messageStart = source.indexOf("  window.addEventListener('message', (e) => {");
const messageEnd = source.indexOf('\n  async function play(mid)', messageStart);
if (messageStart < 0 || messageEnd < 0) throw new Error('Kollus message bridge block was not found');
const bridgeCalls = [];
const bridgeListeners = new Map();
const bridgeWindow = {
  addEventListener(type, callback) { bridgeListeners.set(type, callback); },
};
const bridgeContext = {
  window: bridgeWindow,
  currentMid: 'mid-a',
  WATCH_DONE_RATIO: 0.90,
  Number,
  Math,
  String,
  setProgress(mid, patch) { bridgeCalls.push({ mid, patch }); },
};
vm.runInNewContext(source.slice(messageStart, messageEnd), bridgeContext);
const onMessage = bridgeListeners.get('message');
onMessage({ source: bridgeWindow, data: { type: 'kollus.ready', mid: 'mid-a', duration: 100 } });
onMessage({ source: bridgeWindow, data: { type: 'kollus.progress', mid: 'mid-a', currentTime: 5, duration: 100 } });
onMessage({ source: bridgeWindow, data: { type: 'kollus.progress', mid: 'mid-a', currentTime: 90, duration: 100 } });
onMessage({ source: {}, data: { type: 'kollus.progress', mid: 'mid-a', currentTime: 99, duration: 100 } });
onMessage({ source: bridgeWindow, data: { type: 'kollus.progress', mid: 'other', currentTime: 99, duration: 100 } });
assert(bridgeCalls.length === 3, 'Kollus bridge must accept only same-window active-MID events');
assert(bridgeCalls[0].patch.dur === 100, 'ready event must capture duration');
assert(!bridgeCalls[1].patch.completed, '5 percent progress must remain incomplete in the browser');
assert(bridgeCalls[2].patch.completed === true, '90 percent progress must become complete in the browser');

console.log('student watch autosave behavior checks passed (18 cases)');
