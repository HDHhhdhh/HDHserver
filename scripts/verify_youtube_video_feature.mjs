import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const sourceText = fs.readFileSync('static/js/shared/videoSources.js', 'utf8');
const sources = await import(`data:text/javascript;base64,${Buffer.from(sourceText).toString('base64')}`);
const videoId = 'NSorUwxBPGg';
const listId = 'PL0dm9k63r76anfvN8b2EPD1r_dbu_dat8';
const expected = {
  provider: 'youtube', youtubeKind: 'video', youtubeId: videoId, youtubeStart: 90,
  mid: `ytv_${videoId}_r101`, url: `https://www.youtube.com/watch?v=${videoId}&t=90`,
};
for (const link of [
  `https://youtu.be/${videoId}?t=90`,
  `https://www.youtube.com/watch?v=${videoId}&list=${listId}&t=1m30s`,
  `https://m.youtube.com/shorts/${videoId}?start=90`,
  `https://www.youtube-nocookie.com/embed/${videoId}#t=90`,
]) assert.deepEqual(sources.parseYouTubeUrl(link, 101), expected);
assert.equal(sources.parseYouTubeUrl(`https://youtube.com/playlist?list=${listId}`, 102).mid, `ytp_${listId}_r102`);
assert.equal(sources.parseYouTubeUrl(`https://youtube.com.evil.test/watch?v=${videoId}`), null);
assert.throws(() => sources.parseYouTubeUrl(`https://youtube.com/live/${videoId}`));
assert.throws(() => sources.parseYouTubeUrl(`https://youtube.com/watch?v=${videoId}&v=${videoId}`));
assert.throws(() => sources.parseYouTubeUrl(`https://youtube.com/watch?v=${videoId}&t=oops`));
assert.equal(sources.automaticVideoCourse({ subCurriculum: 'APEX', gichulSelectionEnabled: true }), '기출엄선');
assert.equal(sources.automaticVideoCourse({ subCurriculum: 'APEX', gichulSelectionEnabled: 'true' }), 'APEX');
const student = { curriculum: '기하', subCurriculum: 'APEX', gichulSelectionEnabled: true };
for (const course of ['APEX', '기출엄선']) assert.equal(sources.videoInAssignmentScope(student, { curriculum: '기하', subCurriculum: course }), true);
assert.equal(sources.videoInAssignmentScope(student, { curriculum: '기하', subCurriculum: 'A:Ble' }), false);
assert.equal(sources.videoInAssignmentScope(student, { curriculum: '대수', subCurriculum: '기출엄선' }), false);

const playbackText = fs.readFileSync('static/js/student/playback.js', 'utf8');
const listeners = {};
const browser = { URL, location: { origin: 'https://academy.example.test', protocol: 'https:' },
  addEventListener(type, handler) { listeners[type] = handler; }, postMessage() {} };
vm.runInNewContext(playbackText, { window: browser, URL });
const frame = { src: '', onload: null, contentWindow: {} };
const calls = { watch: 0, resume: 0, last: 0, flush: 0, intervals: 0, failures: 0, requests: 0, notices: 0 };
let allowed = true;
let fallback = '';
const controller = browser.StudentPlayback.createController({
  globalRef: browser, getFrame: () => frame, getSid: () => 's1', canPlay: () => allowed,
  showRestrictedNotice: () => calls.notices++, showLoadFailure: () => calls.failures++,
  showYouTubeFallback: url => { fallback = url; },
  flushWatch: () => calls.flush++, setLastMid: () => calls.last++,
  getProgress: () => { calls.resume++; return { last: 500 }; }, setProgress: () => calls.watch++,
  request: async url => {
    calls.requests++;
    const mid = new URL(url, browser.location.origin).searchParams.get('mid');
    return { ok: true, text: async () => sources.isYouTubeMid(mid)
      ? `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=0&start=90`
      : 'https://v.kr.kollus.com/kollus-one',
    headers: { get: key => sources.isYouTubeMid(mid)
      ? ({ 'X-Video-Provider': 'youtube', 'X-Video-Open-Url': expected.url })[key] || null : null } };
  },
  setIntervalImpl: () => { calls.intervals++; return 1; }, clearIntervalImpl() {}, setTimeoutImpl() {},
  encodeURIComponentImpl: encodeURIComponent, URLImpl: URL,
});
await controller.play(expected.mid);
assert.equal(new URL(frame.src).searchParams.get('autoplay'), '0');
assert.equal(new URL(frame.src).searchParams.get('start'), '90');
assert.equal(frame.onload, null);
assert.equal(fallback, expected.url);
assert.deepEqual([calls.watch, calls.resume, calls.last, calls.intervals], [0, 0, 0, 0]);
listeners.message({ source: browser, data: { type: 'kollus.progress', mid: expected.mid, currentTime: 100, duration: 100, ended: true } });
assert.equal(calls.watch, 0, 'YouTube may never accept a forged Kollus completion event');
await controller.play('kollus-one');
assert.equal(calls.flush, 0, 'Leaving YouTube must not flush a synthetic watch record');
assert.equal(calls.resume, 1);
assert.equal(calls.last, 1);
assert.equal(fallback, '');
assert.equal(typeof frame.onload, 'function');
await controller.play(expected.mid);
assert.equal(calls.flush, 1, 'Leaving Kollus must still flush its real watch state');
allowed = false;
const requestCount = calls.requests;
await controller.play(expected.mid);
assert.equal(calls.requests, requestCount);
assert.equal(calls.notices, 1);
assert.equal(calls.failures, 0);

// Execute the actual admin state transition, with external observation of rearm commands.
const modal = fs.readFileSync('static/js/admin/features/videoModal.js', 'utf8');
function functionSource(name) {
  const start = modal.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  const end = modal.indexOf('\nfunction ', start + 1);
  return modal.slice(start, end < 0 ? undefined : end);
}
const context = {
  activeVideoProgress: {}, activeVideoProgressInitial: {}, activeVideoProgressPatch: {},
  activeVideoWatchRearms: {}, activeVideoAccessMode: 'full',
  normalizeVideoProgressState: value => ['done', 'interrupted', 'skip'].includes(value) ? value : 'none',
  isYouTubeMid: sources.isYouTubeMid, updateVideoRowPresentation() {}, markVideoSelectionDirty() {},
};
vm.createContext(context);
vm.runInContext(functionSource('setActiveVideoProgressState') + '\n' + functionSource('applyVideoRowState'), context);
context.applyVideoRowState({ dataset: { mid: expected.mid } }, 'assigned');
assert.equal(context.activeVideoProgressPatch[expected.mid], 'none');
assert.equal(Object.keys(context.activeVideoWatchRearms).length, 0);
context.applyVideoRowState({ dataset: { mid: 'kollus-one' } }, 'assigned');
assert.equal(typeof context.activeVideoWatchRearms['kollus-one'].token, 'string');

const html = fs.readFileSync('static/student.html', 'utf8');
assert.match(html, /<article class="player-card">[\s\S]*?<iframe id="player"[\s\S]*?id="youtubeOpenLink"[^>]*hidden[\s\S]*?<\/article>/);
assert.equal((html.match(/<iframe id="player"/g) || []).length, 1);
assert.match(fs.readFileSync('static/js/admin/features/today.render.js', 'utf8'), /completeAssignedYouTube: true/);
assert.match(fs.readFileSync('static/js/all/features/table.js', 'utf8'), /patchField\(sid, 'gichulSelectionEnabled', value\)/);
console.log('YouTube browser contracts passed: URL forms, overlay scope, autoplay=0 iframe, no watch/resume/rearm, academy gate, single player and cleanup command');
