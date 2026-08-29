import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const playbackSource = fs.readFileSync('static/js/student/playback.js', 'utf8');
const studentSource = fs.readFileSync('static/js/student.js', 'utf8');
const htmlSource = fs.readFileSync('static/student.html', 'utf8');
const listeners = new Map();
const posted = [];
const browserWindow = {
  URL,
  location: { origin: 'https://academy.example.test', protocol: 'https:' },
  addEventListener(type, callback) { listeners.set(type, callback); },
  postMessage(message, targetOrigin) { posted.push({ message, targetOrigin }); },
};
vm.runInNewContext(playbackSource, {
  URL,
  console,
  Math,
  Number,
  Object,
  Promise,
  String,
  window: browserWindow,
});

const api = browserWindow.StudentPlayback;
assert.ok(api && typeof api.createController === 'function', 'playback module contract was not published');
assert.equal(typeof api.withStartParam, 'function');

assert.equal(
  api.withStartParam('https://video.example.test/embed', 4, { URLImpl: URL, origin: browserWindow.location.origin }),
  'https://video.example.test/embed',
  'resume under five seconds must not change the playback URL',
);
const resumed = new URL(api.withStartParam(
  'https://video.example.test/embed?token=keep',
  12.9,
  { URLImpl: URL, origin: browserWindow.location.origin },
));
assert.equal(resumed.searchParams.get('token'), 'keep');
assert.equal(resumed.searchParams.get('start'), '12');
assert.equal(resumed.searchParams.get('t'), '12');
const existingStart = new URL(api.withStartParam(
  'https://video.example.test/embed?start=7',
  12,
  { URLImpl: URL, origin: browserWindow.location.origin },
));
assert.equal(existingStart.searchParams.get('start'), '7', 'existing start parameter must win');
assert.equal(existingStart.searchParams.get('t'), '12', 'missing t parameter must be added');
assert.equal(
  api.withStartParam('http://[invalid', 12, { URLImpl: URL, origin: browserWindow.location.origin }),
  'http://[invalid#t=12',
  'malformed URL fallback changed',
);

const requests = [];
const responses = [];
const lastMids = [];
const progressPatches = [];
const progressByMid = {
  'mid-a': { last: 12, dur: 100, completed: false, updatedAt: 1_787_390_000_123 },
  'mid-b': { last: 0, dur: 100, completed: false, updatedAt: 1_787_390_000_123 },
};
const progressHash = crypto.createHash('sha256').update(JSON.stringify(progressByMid)).digest('hex');
const intervals = new Map();
const timeouts = new Map();
const clients = [];
const logs = [];
const warnings = [];
const reportedErrors = [];
let intervalId = 0;
let timeoutId = 0;
let academyAllowed = false;
let restrictedNotices = 0;
let loadFailures = 0;
let flushes = 0;

class FakeKollusClient {
  constructor(options) {
    this.options = options;
    this.handlers = new Map();
    this.position = 25;
    this.duration = 100;
    this.seekCalls = [];
    clients.push(this);
  }

  on(type, callback) { this.handlers.set(type, callback); }
  seek(seconds) { this.seekCalls.push(seconds); }
  async getPosition() { return this.position; }
  async getDuration() { return this.duration; }
}
browserWindow.VgControllerClient = FakeKollusClient;

const frame = { src: 'about:blank', contentWindow: { fixture: true }, onload: null };
const controller = api.createController({
  globalRef: browserWindow,
  locationRef: browserWindow.location,
  getFrame: () => frame,
  getSid: () => 'sid 7',
  canPlay: () => academyAllowed,
  showRestrictedNotice: () => { restrictedNotices += 1; },
  showLoadFailure: () => { loadFailures += 1; },
  flushWatch: () => { flushes += 1; },
  setLastMid: mid => { lastMids.push(mid); },
  getProgress: mid => progressByMid[mid] || null,
  setProgress: (mid, patch) => { progressPatches.push({ mid, patch }); },
  request: async url => {
    requests.push(url);
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next;
  },
  doneRatio: 0.90,
  setIntervalImpl(callback, delay) {
    const id = ++intervalId;
    intervals.set(id, { callback, delay });
    return id;
  },
  clearIntervalImpl(id) { intervals.delete(id); },
  setTimeoutImpl(callback, delay) {
    const id = ++timeoutId;
    timeouts.set(id, { callback, delay });
    return id;
  },
  encodeURIComponentImpl: encodeURIComponent,
  URLImpl: URL,
  log: (...args) => logs.push(args.map(String).join(' ')),
  warn: (...args) => warnings.push(args.map(String).join(' ')),
  reportError: error => reportedErrors.push(String(error?.message || error)),
});

await controller.play('mid-a');
assert.equal(restrictedNotices, 1, 'outside-academy playback must show the restriction notice');
assert.equal(requests.length, 0, 'outside-academy playback must not request a URL');
assert.equal(controller.currentMid(), null, 'blocked playback must not change the active MID');

academyAllowed = true;
responses.push({ ok: true, status: 200, async text() { return 'http://video.example.test/embed?token=keep'; } });
await controller.play('mid-a');
assert.equal(controller.currentMid(), 'mid-a');
assert.equal(lastMids.at(-1), 'mid-a');
assert.equal(requests.at(-1), '/api/get-url?mid=mid-a&sid=sid%207');
const frameUrl = new URL(frame.src);
assert.equal(frameUrl.protocol, 'https:', 'HTTPS student page must upgrade an HTTP playback URL');
assert.equal(frameUrl.searchParams.get('token'), 'keep');
assert.equal(frameUrl.searchParams.get('start'), '12');
assert.equal(frameUrl.searchParams.get('t'), '12');
assert.equal(flushes, 0, 'first playback must not flush an unrelated watch record');
assert.equal(
  crypto.createHash('sha256').update(JSON.stringify(progressByMid)).digest('hex'),
  progressHash,
  'playback mutated the injected progress snapshot',
);

assert.equal(typeof frame.onload, 'function', 'successful playback must attach the iframe bridge on load');
frame.onload();
assert.equal(intervals.size, 1, 'iframe load must schedule one controller attach loop');
assert.equal([...intervals.values()][0].delay, 100, 'controller attach interval changed');
await [...intervals.values()][0].callback();
assert.equal(clients.length, 1, 'available Kollus controller must attach once');
assert.equal(frame.__vgAttached, 'mid-a');
assert.equal(clients[0].options.target_window, frame.contentWindow);
frame.onload();
assert.equal(intervalId, 1, 'same-MID iframe load must not schedule a duplicate bridge');

clients[0].handlers.get('ready')();
await Promise.resolve();
await Promise.resolve();
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(clients[0].seekCalls, [12], 'resume position must seek after Kollus ready');
assert.ok(posted.some(entry => entry.message.type === 'kollus.ready' && entry.message.mid === 'mid-a'));
assert.ok(posted.some(entry => entry.message.type === 'kollus.progress'
  && entry.message.currentTime === 25 && entry.message.duration === 100));
assert.ok([...timeouts.values()].some(entry => entry.delay === 3000), 'Kollus polling interval changed');

clients[0].handlers.get('progress')(25, 30, 100);
clients[0].handlers.get('done')();
await clients[0].handlers.get('play')();
await clients[0].handlers.get('pause')();
assert.ok(posted.some(entry => entry.message.currentTime === 30 && entry.message.ended === false));
assert.ok(posted.some(entry => entry.message.ended === true));

delete browserWindow.VgControllerClient;
const unavailableFrame = { contentWindow: { fixture: 'unavailable' } };
controller.attachKollusBridgeToIframe(unavailableFrame, 'mid-timeout', 0);
const unavailableIntervalId = Math.max(...intervals.keys());
for (let attempt = 0; attempt < 200; attempt += 1) {
  intervals.get(unavailableIntervalId)?.callback();
}
assert.equal(intervals.has(unavailableIntervalId), false, 'unavailable controller loop must stop after 200 tries');
assert.equal(
  warnings.filter(message => message.includes('not available (timeout)')).length,
  1,
  'unavailable controller must emit exactly one timeout warning',
);
browserWindow.VgControllerClient = FakeKollusClient;

const onMessage = listeners.get('message');
assert.equal(typeof onMessage, 'function', 'playback controller must install one message listener');
onMessage({ source: browserWindow, data: { type: 'kollus.ready', mid: 'mid-a', duration: 100 } });
onMessage({ source: browserWindow, data: { type: 'kollus.progress', mid: 'mid-a', currentTime: 5, duration: 100 } });
onMessage({ source: browserWindow, data: { type: 'kollus.progress', mid: 'mid-a', currentTime: 90, duration: 100 } });
onMessage({ source: {}, data: { type: 'kollus.progress', mid: 'mid-a', currentTime: 99, duration: 100 } });
onMessage({ source: browserWindow, data: { type: 'kollus.progress', mid: 'other', currentTime: 99, duration: 100 } });
assert.equal(progressPatches.length, 3, 'only same-window active-MID events may update progress');
assert.equal(progressPatches[0].patch.dur, 100);
assert.equal(progressPatches[1].patch.completed, undefined, 'five percent must remain incomplete in the browser');
assert.equal(progressPatches[2].patch.completed, true, '90 percent must become complete in the browser');

responses.push({ ok: true, status: 200, async text() { return 'https://video.example.test/next'; } });
await controller.play('mid-b');
assert.equal(flushes, 1, 'switching active MID must flush the preceding watch record once');
assert.equal(controller.currentMid(), 'mid-b');
assert.equal(lastMids.at(-1), 'mid-b');

responses.push({ ok: false, status: 403, async text() { return ''; } });
await controller.play('mid-c');
assert.equal(restrictedNotices, 2, '403 playback must reuse the academy restriction notice');
assert.equal(loadFailures, 0, '403 playback must not show the generic load failure');
assert.equal(reportedErrors.at(-1), 'academy-network-required');

responses.push({ ok: false, status: 500, async text() { return ''; } });
await controller.play('mid-d');
assert.equal(loadFailures, 1, 'non-403 playback failure must show the generic load failure');
assert.equal(reportedErrors.at(-1), 'get-url 500');

responses.push(new Error('network-down'));
await controller.play('mid-e');
assert.equal(loadFailures, 2, 'network failure must remain visible');
assert.equal(reportedErrors.at(-1), 'network-down');
assert.ok(logs.some(message => message.includes('[play] forced https url')));
assert.equal(warnings.length, 1, 'playback fixture emitted an unexpected warning');

for (const forbidden of ['document.', 'localStorage', 'studentAppRequest', 'alert(']) {
  assert.equal(playbackSource.includes(forbidden), false, `playback module leaked an ambient dependency: ${forbidden}`);
}
for (const retired of ['function withStartParam(', 'function attachKollusBridgeToIframe(', 'async function play(mid)']) {
  assert.equal(studentSource.includes(retired), false, `student entrypoint still owns playback primitive: ${retired}`);
}
assert.equal(studentSource.includes('/api/get-url?'), false, 'student entrypoint duplicated playback transport');
assert.ok(studentSource.includes('studentPlayback.createController({'), 'student entrypoint must compose the playback controller');

const bootstrapScript = '/js/student/bootstrapState.js?v=20260828-bootstrap-state-r1';
const watchScript = '/js/student/watchState.js?v=20260828-watch-state-r1';
const playbackScript = '/js/student/playback.js?v=20260828-playback-r1';
const reviewPlaylistScript = '/js/student/reviewPlaylist.js?v=20260828-review-playlist-r1';
const announcementStateScript = '/js/student/announcementState.js?v=20260828-announcement-state-r1';
const testPresentationScript = '/js/student/testPresentation.js?v=20260828-test-presentation-r1';
const studentScript = '/js/student.js?v=20260828-test-presentation-r1';
assert.equal((htmlSource.match(/\/js\/student\/playback\.js/g) || []).length, 1);
assert.ok(htmlSource.indexOf(bootstrapScript) < htmlSource.indexOf(watchScript));
assert.ok(htmlSource.indexOf(watchScript) < htmlSource.indexOf(playbackScript));
assert.ok(htmlSource.indexOf(playbackScript) < htmlSource.indexOf(reviewPlaylistScript));
assert.ok(htmlSource.indexOf(reviewPlaylistScript) < htmlSource.indexOf(announcementStateScript));
assert.ok(htmlSource.indexOf(announcementStateScript) < htmlSource.indexOf(testPresentationScript));
assert.ok(htmlSource.indexOf(testPresentationScript) < htmlSource.indexOf(studentScript));

console.log('student playback checks passed: resume URL, access gate, active-MID bridge, switch flush, failures, and shell order');
