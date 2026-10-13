import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { pathToFileURL } from 'node:url';

// Reuse the repository's complete DOM/entrypoint fixture. Only its synthetic
// transport is extended; video-manage.js receives no test-only control flow.
const options = { sourceRoot: process.cwd(), source: null };
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  assert.ok(['--source-root', '--source'].includes(arg), 'unknown option ' + arg);
  const value = process.argv[++i];
  assert.ok(value && !value.startsWith('--'), 'missing value for ' + arg);
  options[arg === '--source-root' ? 'sourceRoot' : 'source'] = value;
}
const root = path.resolve(options.sourceRoot);
const sourcePath = path.resolve(root, options.source || 'static/js/video-manage.js');
const harnessPath = path.join(root, 'scripts/verify_video_catalog_interactions.mjs');
const hash = value => createHash('sha256').update(value).digest('hex');
const sourceBytes = fs.readFileSync(sourcePath);
const source = sourceBytes.toString('utf8').replaceAll('\r\n', '\n');
const fixtureBytes = fs.readFileSync(harnessPath);
const originalFixture = fixtureBytes.toString('utf8').replaceAll('\r\n', '\n');
const first = originalFixture.indexOf('function syntheticRows(');
const last = originalFixture.indexOf('async function cacheBoundaryTests(');
assert.ok(first >= 0 && last > first, 'expected complete repository DOM fixture');
let fixture = originalFixture.slice(first, last);
const replaceOnce = (before, after, purpose) => {
  assert.equal(fixture.split(before).length - 1, 1, 'fixture adaptation: ' + purpose);
  fixture = fixture.replace(before, after);
};
replaceOnce(
  'function makeHarness(source, fixture, { youtube = true } = {}) {',
  `function makeHarness(source, fixture, {
    youtube = true, initialRevision = null, getStatus = 200,
    getReject = false, getPayload = undefined,
  } = {}) {`,
  'synthetic GET controls',
);
replaceOnce('  const posts = [];', '  const posts = [];\n  const gets = [];', 'capture GET calls');
replaceOnce(
  '          posts.push({ body: options.body, resolve, reject, done: false });',
  '          posts.push({ body: options.body, headers: { ...options.headers }, resolve, reject, done: false });',
  'capture immutable outgoing headers',
);
replaceOnce(
  `      assert.equal(options.cache, 'no-store');
      return Promise.resolve({
        ok: true,
        headers: {
          get: name => name === 'X-Video-Providers'
            ? youtube ? 'kollus,youtube' : 'kollus'
            : null,
        },
        json: async () => clone(serverRows),
      });`,
  `      assert.equal(options.cache, 'no-store');
      gets.push({ url, cache: options.cache });
      if (getReject) return Promise.reject(new Error('fixture GET network failure'));
      return Promise.resolve({
        ok: getStatus >= 200 && getStatus < 300,
        status: getStatus,
        headers: {
          get: name => name.toLowerCase() === 'x-store-revision'
            ? initialRevision
            : name.toLowerCase() === 'x-video-providers'
              ? youtube ? 'kollus,youtube' : 'kollus'
              : null,
        },
        json: async () => clone(getPayload === undefined ? serverRows : getPayload),
      });`,
  'synthetic status/body/revision response',
);
replaceOnce(
  '    { status = 204, payload = {}, reject = false } = {},',
  '    { status = 204, payload = {}, reject = false, revision = null } = {},',
  'synthetic POST acknowledgement revision',
);
replaceOnce(
  `      post.resolve({
        ok: status >= 200 && status < 300,
        status,
        json: async () => payload,
      });`,
  `      post.resolve({
        ok: status >= 200 && status < 300,
        status,
        headers: { get: name => name.toLowerCase() === 'x-store-revision' ? revision : null },
        json: async () => payload,
      });`,
  '204 header support without JSON body requirement',
);
replaceOnce('    posts,\n    alerts,', '    posts,\n    gets,\n    alerts,', 'expose synthetic GET history');

const loadShared = file => import(pathToFileURL(path.join(root, 'static/js/shared', file)).href);
const [search, ids, providers, identity] = await Promise.all([
  loadShared('search.js'), loadShared('videoIds.js'),
  loadShared('videoSources.js'), loadShared('videoCatalogIdentity.js'),
]);
const sharedNames = [
  'assert', 'vm', 'performance', 'hash', 'searchKeyForText', 'matchesSearchKey',
  'applySearchPlaceholder', 'nextVideoId', 'parseYouTubeUrl', 'GICHUL_COURSE',
  'buildVideoCorrectionDraft', 'protectedVideoIdentityChanges', 'videoCorrectionSummary',
];
const sharedValues = [
  assert, vm, performance, hash, search.searchKeyForText, search.matchesSearchKey,
  search.applySearchPlaceholder, ids.nextVideoId, providers.parseYouTubeUrl, providers.GICHUL_COURSE,
  identity.buildVideoCorrectionDraft, identity.protectedVideoIdentityChanges, identity.videoCorrectionSummary,
];
const { makeHarness, loaded, syntheticRows, same, payloadAt, contractTests } = new Function(
  ...sharedNames,
  fixture + '\nreturn { makeHarness, loaded, syntheticRows, same, payloadAt, contractTests };',
)(...sharedValues);

const A = 'a'.repeat(64);
const B = 'b'.repeat(64);
const C = 'c'.repeat(64);
const outcomes = [];
const pass = name => outcomes.push({ case: name, pass: true });
const assertBlocked = h => {
  assert.equal(h.elements.get('saveVid').disabled, true, 'save disabled');
  assert.equal(h.elements.get('videoCorrectionMode').disabled, true, 'correction base unavailable');
  assert.equal(h.elements.get('videoSafetyNotice').dataset.state, 'blocked', 'persistent notice');
};

{
  const rows = syntheticRows(3);
  const h = await loaded(source, rows, { initialRevision: A });
  assert.equal(h.gets.length, 1);
  h.edit(0, 7, '첫 guarded 저장');
  await h.advance(800);
  assert.equal(h.posts.length, 1);
  assert.equal(h.posts[0].headers['If-Match'], A, 'first POST uses exact GET revision');
  assert.equal(h.posts[0].headers['Content-Type'], 'application/json');
  h.edit(1, 7, '둘째 대기 저장');
  await h.advance(800);
  h.click('saveVid');
  h.edit(2, 7, '대기 중 마지막 DOM', false);
  assert.equal(h.posts.length, 1, 'one POST in flight');
  await h.complete(0, { revision: B });
  assert.equal(h.posts.length, 2, 'queued manual follower begins after acknowledgement');
  assert.equal(h.posts[1].headers['If-Match'], B, 'queued follower uses acknowledged revision');
  const firstExpected = syntheticRows(3);
  firstExpected[0].title = '첫 guarded 저장';
  const secondExpected = syntheticRows(3);
  secondExpected[0].title = '첫 guarded 저장';
  secondExpected[1].title = '둘째 대기 저장';
  secondExpected[2].title = '대기 중 마지막 DOM';
  same(payloadAt(h, 0), firstExpected, 'immutable first body including unknown metadata');
  same(payloadAt(h, 1), secondExpected, 'queued body captures latest unblurred DOM');
  await h.complete(1, { revision: C });
  h.edit(0, 7, '셋째 수동 저장', false);
  h.click('saveVid');
  assert.equal(h.posts[2].headers['If-Match'], C, 'manual follow-up uses newest revision');
  await h.complete(2, { revision: A });
  const finalExpected = [...secondExpected];
  finalExpected[0] = { ...secondExpected[0], title: '셋째 수동 저장' };
  same(h.serverRows(), finalExpected, 'committed fake server preserves payload shape');
  h.click('saveVid');
  assert.equal(h.posts.length, 3, 'no-op does not issue POST');
  pass('GET -> first POST -> queued POST -> manual POST exact revision chaining');
}

for (const [status, error] of [
  [409, 'video_catalog_revision_conflict'],
  [428, 'video_catalog_revision_required'],
]) {
  const initial = syntheticRows(3);
  const h = await loaded(source, initial, { initialRevision: A });
  h.edit(0, 7, '충돌 첫 입력');
  await h.advance(800);
  h.edit(1, 7, '충돌 대기 입력');
  await h.advance(800);
  h.click('saveVid');
  h.edit(2, 7, '충돌 후 보존 DOM', false);
  await h.complete(0, {
    status, payload: { error, message: 'fixture revision reload required' }, revision: B,
  });
  assert.equal(h.posts.length, 1, `${status} stops already queued follower`);
  assertBlocked(h);
  same(h.titles(), ['충돌 첫 입력', '충돌 대기 입력', '충돌 후 보존 DOM'], 'failed save preserves all draft DOM');
  same(h.serverRows(), initial, 'revision failure cannot change fake server rows');
  h.forceSave();
  h.elements.get('videoCorrectionMode').dispatch('click');
  h.elements.get('videoCorrectionDownload').dispatch('click');
  h.edit(0, 7, '차단 뒤 새 입력');
  await h.advance(1600);
  assert.equal(h.posts.length, 1, `${status} stops forced/manual/auto followers`);
  assert.equal(h.downloads.length, 0, 'blocked baseline cannot produce correction draft');
  pass(`${status} queued/manual/auto/correction stop and draft preservation`);
}

{
  const failedCases = [
    { getStatus: 401 }, { getStatus: 503 }, { getReject: true },
    { getPayload: { invalid: 'catalog root is not an array' } },
  ];
  for (const response of failedCases) {
    const h = makeHarness(source, syntheticRows(2), { initialRevision: A, ...response });
    h.forceSave();
    assert.equal(h.posts.length, 0, 'pending initial GET cannot save default empty list');
    await h.settle();
    assertBlocked(h);
    h.forceSave();
    h.elements.get('videoCorrectionMode').dispatch('click');
    await h.advance(1600);
    assert.equal(h.posts.length, 0, 'failed initial GET cannot POST');
    assert.equal(h.downloads.length, 0);
    assert.equal(h.gets.length, 1, 'no hidden fallback GET chain');
  }
  pass('pending/401/503/network/malformed initial GET no POST or correction export');
}

{
  const h = await loaded(source, syntheticRows(3), { initialRevision: A });
  h.edit(0, 7, '서버에 저장된 첫 입력');
  await h.advance(800);
  h.edit(1, 7, '응답 전 대기 입력');
  await h.advance(800);
  h.click('saveVid');
  h.edit(2, 7, '최신 미저장 DOM', false);
  await h.complete(0); // Successful empty-body 204, but no next revision header.
  assert.equal(h.posts.length, 1, 'missing acknowledgement revision stops queued follower');
  const committed = syntheticRows(3);
  committed[0].title = '서버에 저장된 첫 입력';
  same(h.serverRows(), committed, 'successful first POST is acknowledged as committed');
  same(h.titles(), ['서버에 저장된 첫 입력', '응답 전 대기 입력', '최신 미저장 DOM'], 'unsaved newest DOM stays visible');
  assertBlocked(h);
  assert.match(h.elements.get('videoSafetyNotice').textContent, /저장됐지만/);
  assert.match(h.elements.get('videoSafetyNotice').textContent, /새로고침/);
  h.forceSave();
  h.elements.get('videoCorrectionMode').dispatch('click');
  h.edit(0, 7, '응답 누락 뒤 입력');
  await h.advance(1600);
  assert.equal(h.posts.length, 1, 'no soft unguarded follower after lost revision');
  pass('successful guarded 204 without next revision commits first body and blocks followers');
}

{
  for (const failure of [{ status: 503, payload: { message: 'fixture 503' } }, { reject: true }]) {
    const h = await loaded(source, syntheticRows(2), { initialRevision: A });
    h.edit(0, 7, '일반 실패 후 수동 재시도');
    await h.advance(800);
    await h.complete(0, failure);
    assert.equal(h.elements.get('saveVid').disabled, false, 'ordinary transport failure allows manual retry');
    h.click('saveVid');
    assert.equal(h.posts.length, 2);
    assert.equal(h.posts[1].headers['If-Match'], A, 'failed save does not advance revision');
    same(payloadAt(h, 1), payloadAt(h, 0), 'retry retains exact same draft');
    await h.complete(1, { revision: B });
    h.click('videoCorrectionMode');
    h.edit(0, 7, '수정안 전용 내용');
    h.forceSave();
    await h.advance(1600);
    assert.equal(h.posts.length, 2, 'correction mode forced/auto save prohibited');
    h.click('videoCorrectionDownload');
    assert.equal(h.downloads.length, 1, 'correction download remains available after guarded retry');
    h.click('videoCorrectionCancel');
    same(h.titles(), ['일반 실패 후 수동 재시도', '합성 기하 영상 2 대상마지막'], 'cancel restores successfully acknowledged base');
  }
  pass('503/network manual retry retains revision and correction no-POST/export/cancel contracts');
}

{
  const h = await loaded(source, syntheticRows(2), { initialRevision: A });
  h.edit(0, 7, '서버 MID 거절 입력');
  await h.advance(800);
  await h.complete(0, {
    status: 409,
    payload: {
      error: 'video_catalog_identity_change_blocked', removedIds: [],
      midChanges: [{ id: '1', oldMid: 'synthetic-1', newMid: 'blocked' }],
      message: 'fixture MID guarded failure',
    },
    revision: B,
  });
  same(h.titles(), ['합성 기하 영상 1', '합성 기하 영상 2 대상마지막'], 'MID409 retains saved-snapshot rollback');
  assert.equal(h.elements.get('saveVid').disabled, false, 'identity409 does not enter stale-revision permanent block');
  h.edit(0, 7, 'MID 거절 후 정상 제목');
  h.click('saveVid');
  assert.equal(h.posts.length, 2);
  assert.equal(h.posts[1].headers['If-Match'], A, 'MID rejection cannot advance revision');
  await h.complete(1, { revision: C });
  pass('MID409 priority/rollback/manual recovery preserved separately from revision409');
}

{
  const h = await loaded(source, syntheticRows(2));
  h.edit(0, 7, '이전 서버 호환 저장');
  await h.advance(800);
  assert.equal(Object.hasOwn(h.posts[0].headers, 'If-Match'), false, 'legacy GET has no revision');
  await h.complete(0);
  assert.equal(h.elements.get('saveVid').disabled, false, 'legacy headerless successful 204 remains usable');
  h.edit(1, 7, '이전 서버 둘째 저장', false);
  h.click('saveVid');
  assert.equal(h.posts.length, 2);
  await h.complete(1);
  pass('soft rollout preserves old headerless server while acknowledged revisions become required');
}

// These original groups include existing retry, queue, identity and correction
// negative cases. Keep them unchanged alongside the new revision scenarios.
const baseline = await contractTests(source, 'p3-draft legacy fixture contracts');
console.log(JSON.stringify({
  source: sourcePath, sourceSha256: hash(sourceBytes),
  reusedHarness: harnessPath, reusedHarnessSha256: hash(fixtureBytes),
  adaptedTransportSha256: hash(fixture),
  revisionGroupCount: outcomes.length, outcomes,
  preservedLegacyGroupCount: baseline.caseCount,
  preservedLegacyOutcomes: baseline.outcomes,
  actualFullEntrypoint: true, persistentWrites: 0, realRequests: 0,
}, null, 2));
