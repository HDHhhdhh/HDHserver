import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({ window: {}, Date, Math, Number, String, Object, Promise });
vm.runInContext(fs.readFileSync('static/js/student/watchState.js', 'utf8'), context);
const api = context.window.StudentWatchState;
const storage = new Map();
const requests = [];
let response = { ok: true };
let changed = 0;
const now = 1789200000000;
const controller = api.createController({
  storage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
  getSid: () => 'qa', getCanonicalSid: () => 'qa', getDate: () => '2026-09-12', getCurrentMid: () => 'mid',
  canSync: () => true, now: () => now, setTimer: () => 1, clearTimer() {},
  request: async (url, options) => { requests.push(JSON.parse(options.body)); return response; },
  onCycleChanged: () => changed++,
});
controller.setProgress('mid', { last: 100, dur: 100, completed: true });
controller.setProgress('other', { last: 100, dur: 100, completed: true });
controller.mergeServerWatchIntoLocal({ mid: { last: 0, dur: 0, completed: false, updatedAt: now, cycleToken: 'generation_00001' } });
assert.equal(controller.getProgress('mid').last, 0);
assert.equal(controller.getProgress('mid').completed, false);
assert.equal(controller.getProgress('other').completed, true);
assert.equal(controller.acceptPlaybackWatch('other', {last:0,dur:0,completed:false,cycleToken:'next_other_generation'}), false);
controller.setProgress('other', {last:100,dur:100,completed:true});
assert.equal(controller.getProgress('other').completed, false, 'retired iframe must not write into the new cycle');
changed = 0;
controller.setProgress('mid', { last: 5, dur: 100 });
await controller.syncNow('mid');
assert.equal(requests.at(-1).cycleToken, 'generation_00001');
assert.equal(requests.at(-1).last, 5);
assert.equal(requests.at(-1).completed, false);
response = { ok: false, status: 409, json: async () => ({ code: 'watch_cycle_changed', watch: {
  last: 0, dur: 0, completed: false, updatedAt: now, cycleToken: 'generation_00002',
} }) };
controller.setProgress('mid', { last: 100, dur: 100, completed: true });
await controller.syncNow('mid');
assert.equal(changed, 1);
const count = requests.length;
controller.setProgress('mid', { last: 100, dur: 100, completed: true });
await controller.syncNow('mid');
assert.equal(requests.length, count, 'old player must stay frozen until fresh bootstrap');
assert.equal(controller.getProgress('mid').completed, false);

// Execute the real admin transition and transport, with literal white/green oracles.
const source = fs.readFileSync('static/js/admin/features/videoModal.js', 'utf8');
const videoSources = await import(`data:text/javascript;base64,${Buffer.from(fs.readFileSync('static/js/shared/videoSources.js', 'utf8')).toString('base64')}`);
const functionSource = (name, next) => source.slice(source.indexOf(`function ${name}(`), source.indexOf(`function ${next}(`));
const sandbox = vm.createContext({ Date, Math, crypto: { randomUUID: () => 'admin_operation_001' },
  isYouTubeMid: videoSources.isYouTubeMid,
  activeVideoProgress: { mid: 'none' }, activeVideoProgressInitial: { mid: 'none', __videoWatchCycles: { mid: { token: 'previous_cycle_001' } } },
  activeVideoProgressPatch: {}, activeVideoWatchRearms: {}, activeVideoAccessMode: 'full',
  normalizeVideoProgressState: value => ['done', 'interrupted', 'skip'].includes(value) ? value : 'none',
  updateVideoRowPresentation: (row, state) => { row.dataset.state = state; }, markVideoSelectionDirty() {},
});
vm.runInContext(functionSource('setActiveVideoProgressState', 'videoRowState'), sandbox);
const row = { dataset: { mid: 'mid', state: 'none' } };
sandbox.applyVideoRowState(row, 'assigned');
assert.equal(row.dataset.state, 'assigned');
assert.equal(sandbox.activeVideoProgressPatch.mid, 'none');
assert.equal(sandbox.activeVideoWatchRearms.mid.baseToken, 'previous_cycle_001');
assert.equal(sandbox.activeVideoWatchRearms.mid.token, 'admin_operation_001');
sandbox.applyVideoRowState(row, 'none');
assert.equal(Object.keys(sandbox.activeVideoWatchRearms).length, 0);
assert.equal(sandbox.activeVideoProgressPatch.mid, 'none');
sandbox.activeVideoAccessMode = 'all-students-readonly';
sandbox.applyVideoRowState(row, 'skip');
assert.equal(Object.keys(sandbox.activeVideoWatchRearms).length, 0);
assert.equal(sandbox.activeVideoProgressPatch.mid, 'skip');
assert.ok(source.includes('state.progress?.[today]?.[editingSid]?.__videoWatchCycles'), 'reopen must hydrate generation base');
assert.ok(source.indexOf("support.headers.get('X-Video-Watch-Cycles')") < source.indexOf('const latestLogEntry = await fetchLatestExtraVideoLogEntry(today, sid)'));
console.log('fresh-watch browser contracts passed: local reset, generation transport, stale-player freeze, explicit green/white, read-only mode');

// A page that was already open must refresh resume state from the get-url response before replaying.
vm.runInContext(fs.readFileSync('static/js/student/playback.js', 'utf8'), context);
let cachedWatch = { last: 100, dur: 100, completed: true };
const frame = { src: '' };
const playback = context.window.StudentPlayback.createController({
  globalRef: { addEventListener() {}, postMessage() {} }, locationRef: { origin: 'http://localhost', protocol: 'http:' },
  getFrame: () => frame, getSid: () => 'qa', canPlay: () => true, showRestrictedNotice() {},
  showLoadFailure() { throw Error('unexpected playback failure'); }, flushWatch() {}, setLastMid() {},
  getProgress: () => cachedWatch, setProgress() {},
  request: async () => ({ ok: true, text: async () => 'https://video.example.test/fresh', headers: { get: () => JSON.stringify({last:0,dur:0,completed:false,cycleToken:'generation_00003'}) } }),
  onWatchCycle: (_mid, record) => { cachedWatch = record; },
  setIntervalImpl() {}, clearIntervalImpl() {}, setTimeoutImpl() {}, encodeURIComponentImpl: encodeURIComponent, URLImpl: URL,
});
await playback.play('mid');
assert.equal(frame.src, 'https://video.example.test/fresh', 'old completed resume position leaked into fresh playback');
assert.equal(cachedWatch.completed, false);
