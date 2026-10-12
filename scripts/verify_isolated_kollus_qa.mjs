import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { runStudentFixture } = require('./verify_student_previous_video_review.js');

const sid = 'QAHUBNATIVE1002';
const mid = '3FWqGfJP';
const qaLocation = { hostname: '127.0.0.1', port: '8004', origin: 'http://127.0.0.1:8004' };
const options = {
  sid, academyAccessAllowed: false, reviewVideos: [], assignment: [mid, 'denied-mid'],
  videos: [
    { mid, title: 'QA 영상', localPlaybackQaAllowed: true, playbackRestricted: false },
    { mid: 'denied-mid', title: '제한 영상', playbackRestricted: true },
  ],
};
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); };
const playable = await runStudentFixture({ ...options, location: qaLocation });
assert.equal(playable.window.__STUDENT_ACCESS__.academyAccessAllowed, false);
assert.equal(playable.requestLog.filter(r => r.url.startsWith('/api/get-url')).length, 1);
assert.ok(playable.requestLog.some(r => r.url.includes(`mid=${mid}&sid=${sid}`)));
playable.window.dispatchEvent({ type: 'message', source: playable.window, data: { type: 'kollus.progress', mid, currentTime: 10, duration: 100 } });
playable.window.dispatchEvent({ type: 'pagehide' });
await settle();
const writes = playable.requestLog.filter(r => r.url === '/api/watch' && r.method === 'POST');
assert.equal(writes.length, 1);
assert.equal(JSON.parse(writes[0].body).mid, mid);
assert.equal(JSON.parse(writes[0].body).sid, sid);
assert.ok(JSON.parse(writes[0].body).updatedAt > 1e12);
const deniedRow = playable.document.getElementById('vidList').querySelector('li[data-mid="denied-mid"]');
playable.document.getElementById('vidList').onclick({ target: deniedRow });
await settle();
assert.equal(playable.requestLog.filter(r => r.url.startsWith('/api/get-url')).length, 1);
assert.equal(playable.window.__STUDENT_ACCESS__.academyAccessAllowed, false);

for (const location of [
  { hostname: '127.0.0.1', port: '8003' },
  { hostname: 'academy.example', port: '' },
  { hostname: 'localhost', port: '8004' },
]) {
  const denied = await runStudentFixture({ ...options, location });
  assert.equal(denied.requestLog.filter(r => r.url.startsWith('/api/get-url')).length, 0);
  assert.equal(denied.requestLog.filter(r => r.url === '/api/watch').length, 0);
}
for (const value of [false, 1, 'true', null]) {
  const denied = await runStudentFixture({ ...options, location: qaLocation, videos: [{ mid, title: '제한', localPlaybackQaAllowed: value }] });
  assert.equal(denied.requestLog.filter(r => r.url.startsWith('/api/get-url')).length, 0);
}
console.log('isolated Kollus QA browser checks passed: actual entrypoint, per-MID native/writer scope, academy remains false, origin and strict boolean negatives');
