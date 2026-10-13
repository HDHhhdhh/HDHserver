import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { nextVideoId } from '../static/js/shared/videoIds.js';
import {
  buildVideoCorrectionDraft,
  protectedVideoIdentityChanges,
  VIDEO_CORRECTION_DRAFT_KIND,
  VIDEO_CORRECTION_DRAFT_SCHEMA_VERSION,
  videoCorrectionSummary,
} from '../static/js/shared/videoCatalogIdentity.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'static/js/video-manage.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'static/video-manage.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'static/css/style.css'), 'utf8');

assert.equal(nextVideoId([]), 1);
assert.equal(nextVideoId([{ id: 1 }, { id: '2' }, { id: 7 }]), 8);
assert.equal(nextVideoId([{ id: 'demo-v001' }, { id: 'demo-v021' }]), 1);
assert.equal(nextVideoId([{ id: 'demo-v001' }, { id: 3 }, { id: 'NaN' }]), 4);
assert.equal(nextVideoId(null), 1);

const current = [
  { id: 1, mid: 'mid-a', title: 'A' },
  { id: 2, mid: 'mid-b', title: 'B' },
];
assert.deepEqual(
  protectedVideoIdentityChanges(current, current.map(row => ({ ...row, title: `${row.title}!` }))),
  { removedIds: [], midChanges: [] },
);
assert.deepEqual(
  protectedVideoIdentityChanges(current, [{ ...current[0], mid: 'mid-new' }, current[1]]),
  { removedIds: [], midChanges: [{ id: '1', oldMid: 'mid-a', newMid: 'mid-new' }] },
);
assert.deepEqual(
  protectedVideoIdentityChanges(current, [current[1]]),
  { removedIds: ['1'], midChanges: [] },
);
assert.deepEqual(
  protectedVideoIdentityChanges(current, [...current, { id: 3, mid: 'mid-c' }]),
  { removedIds: [], midChanges: [] },
);

const correctionTarget = [
  { id: 1, mid: 'mid-new', title: 'A corrected' },
  { id: 3, mid: 'mid-c', title: 'C' },
];
assert.deepEqual(videoCorrectionSummary(current, correctionTarget), {
  removedIds: ['2'],
  midChanges: [{ id: '1', oldMid: 'mid-a', newMid: 'mid-new' }],
  newIds: ['3'],
  modifiedIds: ['1'],
});
const draft = buildVideoCorrectionDraft(current, correctionTarget, '2026-08-23T12:00:00.000Z');
assert.equal(draft.kind, VIDEO_CORRECTION_DRAFT_KIND);
assert.equal(draft.schemaVersion, VIDEO_CORRECTION_DRAFT_SCHEMA_VERSION);
assert.equal(draft.createdAt, '2026-08-23T12:00:00.000Z');
assert.deepEqual(draft.baseVideos, current);
assert.deepEqual(draft.nextVideos, correctionTarget);
current[0].title = 'mutated after draft';
correctionTarget[0].title = 'also mutated after draft';
assert.equal(draft.baseVideos[0].title, 'A');
assert.equal(draft.nextVideos[0].title, 'A corrected');

assert.match(source, /import\s+\{\s*nextVideoId\s*\}.*shared\/videoIds\.js/);
assert.match(source, /id:\s*nextVideoId\(videos\)/);
assert.doesNotMatch(source, /Math\.max\(\.\.\.videos\.map/);
assert.match(html, /id="videoSafetyNotice"/);
assert.match(html, /기존 영상의 MID 변경과 삭제는 저장되지 않습니다/);
for (const id of ['videoCorrectionMode', 'videoCorrectionDownload', 'videoCorrectionCancel', 'videoCorrectionStatus']) {
  assert.match(html, new RegExp(`id="${id}"`));
}
assert.match(css, /video-safety-notice\[data-state="correction"\]/);
assert.match(source, /VIDEO_IDENTITY_CHANGE_ERROR\s*=\s*'video_catalog_identity_change_blocked'/);
assert.match(source, /buildVideoCorrectionDraft, protectedVideoIdentityChanges, videoCorrectionSummary/);
assert.match(source, /function restoreLastSavedVideos\(/);
assert.match(source, /function enterCorrectionMode\(/);
assert.match(source, /function downloadCorrectionDraft\(/);
assert.match(source, /saveVidBtn\.disabled = correctionMode/);
assert.match(source, /if \(correctionMode\) \{\s*updateCorrectionStatus\(\);\s*return;\s*\}/);
assert.match(source, /const draft = buildVideoCorrectionDraft\(correctionBaseVideos, videos\)/);
assert.match(source, /err\?\.status === 409/);
const correctionSaveGuard = source.indexOf("toast('수정 모드에서는 서버 저장 안 됨')");
const liveVideoPost = source.indexOf("fetch('/api/videos',", correctionSaveGuard);
assert.ok(correctionSaveGuard >= 0 && liveVideoPost > correctionSaveGuard, 'correction guard must precede the live POST');
const downloadStart = source.indexOf('function downloadCorrectionDraft()');
const downloadEnd = source.indexOf('correctionModeBtn?.addEventListener', downloadStart);
assert.doesNotMatch(source.slice(downloadStart, downloadEnd), /fetch\s*\(/);
const correctionFlowStart = source.indexOf('function enterCorrectionMode()');
const correctionFlowEnd = source.indexOf('function showVideoIdentityBlocked', correctionFlowStart);
const correctionFlow = source.slice(correctionFlowStart, correctionFlowEnd);
assert.doesNotMatch(correctionFlow, /fetch\s*\(/);
assert.doesNotMatch(correctionFlow, /localStorage/);
assert.match(correctionFlow, /if \(autoSaveTimer\) clearTimeout\(autoSaveTimer\)/);

console.log('video-manage id, identity guard, and offline correction-mode checks passed');