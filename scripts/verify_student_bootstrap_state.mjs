import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const modulePath = path.join(root, 'static', 'js', 'student', 'bootstrapState.js');
const studentPath = path.join(root, 'static', 'js', 'student.js');
const htmlPath = path.join(root, 'static', 'student.html');
const moduleSource = fs.readFileSync(modulePath, 'utf8');
const studentSource = fs.readFileSync(studentPath, 'utf8');
const htmlSource = fs.readFileSync(htmlPath, 'utf8');

const browserWindow = {};
vm.runInNewContext(moduleSource, {
  URLSearchParams,
  console,
  window: browserWindow,
}, { filename: 'bootstrapState.js' });

const api = browserWindow.StudentBootstrapState;
assert.ok(api && typeof api === 'object', 'bootstrap state module must publish its browser contract');
assert.equal(typeof api.projectBootstrapInitialData, 'function');
assert.equal(typeof api.loadInitialData, 'function');

const plain = value => JSON.parse(JSON.stringify(value));
const hashJson = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');

const bootstrapFixture = {
  students: [{ id: 's-1', name: '학생 1', curriculum: 'A' }],
  student: { id: 'ignored-fallback' },
  videos: [{ mid: 'm-1', title: '첫 영상' }],
  updates: { '2026-08-28': { 's-1': { videos: ['m-1'], source: 'auto' } } },
  materials: { 교재: ['a.pdf'] },
  assigns: { 's-1': ['교재'] },
  absent: { by_date: { '2026-08-28': [] } },
  logs: { '2026-08-28': { 's-1': { note: '유지' } } },
  courseBlocked: true,
  selfStudy: true,
  blockMessage: '수업 없음',
  courseVideosCompleted: true,
  academyOnlyNotice: '학원 전용',
  assignedTests: [{ id: 't-1', label: '단원평가' }],
  homeworkBooks: ['개념서'],
  reviewVideos: [{ mid: 'm-0', reviewStatus: 'done' }],
  ghostStudent: true,
  redirectSid: 's-2',
  recoveredSid: 'ignored-recovery',
  recoveryReason: 'alias',
  dashboard: [],
  unknownField: { keep: true },
};
const watchFixture = { watch: { 'm-1': { last: 120, dur: 300 } } };
const fixtureHashBefore = hashJson({ bootstrapFixture, watchFixture });
const academyCalls = [];
const projected = api.projectBootstrapInitialData(bootstrapFixture, watchFixture, {
  publicMode: true,
  resolveAcademyAccess(publicMode, bootstrap) {
    academyCalls.push({ publicMode, sameBootstrap: bootstrap === bootstrapFixture });
    return false;
  },
});

assert.deepEqual(plain(projected), [
  [{ id: 's-1', name: '학생 1', curriculum: 'A' }],
  [{ mid: 'm-1', title: '첫 영상' }],
  { '2026-08-28': { 's-1': { videos: ['m-1'], source: 'auto' } } },
  { 교재: ['a.pdf'] },
  { 's-1': ['교재'] },
  { by_date: { '2026-08-28': [] } },
  { '2026-08-28': { 's-1': { note: '유지' } } },
  { watch: { 'm-1': { last: 120, dur: 300 } } },
  {
    courseBlocked: true,
    selfStudy: true,
    blockMessage: '수업 없음',
    courseVideosCompleted: true,
    academyAccessAllowed: false,
    academyOnlyMessage: '학원 전용',
    assignedTests: [{ id: 't-1', label: '단원평가' }],
    homeworkBooks: ['개념서'],
    reviewVideos: [{ mid: 'm-0', reviewStatus: 'done' }],
    reviewVideosMalformed: false,
    ghostStudent: true,
    redirectSid: 's-2',
    recoveryReason: 'alias',
    dashboard: [],
    videoProjectionAuthoritative: true,
  },
]);
assert.deepEqual(academyCalls, [{ publicMode: true, sameBootstrap: true }]);
assert.equal(hashJson({ bootstrapFixture, watchFixture }), fixtureHashBefore, 'projection must not mutate its inputs');

const malformedReviewProjection = plain(api.projectBootstrapInitialData({
  student: { id: 'fallback-student' },
  videos: 'bad-videos',
  updates: null,
  materials: null,
  assigns: null,
  absent: null,
  logs: null,
  assignedTests: {},
  homeworkBooks: 'bad-books',
  reviewVideos: { mid: 'not-an-array' },
  recoveredSid: 'recovered-sid',
  dashboard: 'bad-dashboard',
}, null, {
  publicMode: false,
  resolveAcademyAccess: () => true,
}));
assert.deepEqual(malformedReviewProjection, [
  [{ id: 'fallback-student' }],
  [],
  {},
  {},
  {},
  {},
  {},
  null,
  {
    courseBlocked: false,
    selfStudy: false,
    blockMessage: '',
    courseVideosCompleted: false,
    academyAccessAllowed: true,
    academyOnlyMessage: '',
    assignedTests: [],
    homeworkBooks: [],
    reviewVideos: { mid: 'not-an-array' },
    reviewVideosMalformed: true,
    ghostStudent: false,
    redirectSid: 'recovered-sid',
    recoveryReason: '',
    dashboard: null,
    videoProjectionAuthoritative: true,
  },
]);

let releaseWatchJson;
const watchJson = new Promise(resolve => { releaseWatchJson = resolve; });
const fetchCalls = [];
const loadTrace = [];
const fetchImpl = (url, init) => {
  fetchCalls.push({ url, init: init ? plain(init) : null });
  if (url === '/api/watch/latest?sid=sid%20one') {
    loadTrace.push('watch-fetch');
    return Promise.resolve({
      json() {
        loadTrace.push('watch-json');
        return watchJson;
      },
    });
  }
  if (url === '/api/student/bootstrap?sid=sid+one&date=2026-08-28') {
    loadTrace.push('bootstrap-fetch');
    return Promise.resolve({
      ok: true,
      status: 200,
      async json() {
        loadTrace.push('bootstrap-json');
        return {
          students: [{ id: 'sid one', name: '학생' }],
          videos: [{ mid: 'm-1' }],
          updates: { '2026-08-28': {} },
          materials: { 교재: [] },
          assigns: { 'sid one': ['교재'] },
          absent: { by_date: {} },
          logs: { '2026-08-28': {} },
          assignedTests: [{ id: 't-1' }],
          homeworkBooks: ['문제집'],
          reviewVideos: [],
          dashboard: { today: true },
        };
      },
    });
  }
  throw new Error(`unexpected fetch ${url}`);
};

let nonPublicSettled = false;
const nonPublicPromise = api.loadInitialData({
  publicMode: false,
  date: '2026-08-28',
  sid: 'sid one',
  fetchImpl,
  resolveAcademyAccess: () => true,
});
nonPublicPromise.finally(() => { nonPublicSettled = true; });
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(fetchCalls, [
  { url: '/api/watch/latest?sid=sid%20one', init: null },
  { url: '/api/student/bootstrap?sid=sid+one&date=2026-08-28', init: { cache: 'no-store' } },
]);
assert.ok(loadTrace.includes('bootstrap-json'), 'bootstrap JSON must load while watch JSON is still pending');
assert.equal(nonPublicSettled, false, 'initial state must wait for the already-started watch request');
releaseWatchJson({ watch: { 'm-1': { last: 20 } } });
const nonPublicLoaded = await nonPublicPromise;
assert.equal(nonPublicLoaded.activeSid, '');
assert.deepEqual(plain(nonPublicLoaded.initialData), [
  [{ id: 'sid one', name: '학생' }],
  [{ mid: 'm-1' }],
  { '2026-08-28': {} },
  { 교재: [] },
  { 'sid one': ['교재'] },
  { by_date: {} },
  { '2026-08-28': {} },
  { watch: { 'm-1': { last: 20 } } },
  {
    courseBlocked: false,
    selfStudy: false,
    blockMessage: '',
    courseVideosCompleted: false,
    academyAccessAllowed: true,
    academyOnlyMessage: '',
    assignedTests: [{ id: 't-1' }],
    homeworkBooks: ['문제집'],
    reviewVideos: [],
    reviewVideosMalformed: false,
    ghostStudent: false,
    redirectSid: '',
    recoveryReason: '',
    dashboard: { today: true },
    videoProjectionAuthoritative: true,
  },
]);

const watchFailureCalls = [];
const watchFailureLoaded = await api.loadInitialData({
  publicMode: false,
  date: '2026-08-28',
  sid: 's-2',
  fetchImpl(url, init) {
    watchFailureCalls.push({ url, init: init ? plain(init) : null });
    if (url.startsWith('/api/watch/latest?')) return Promise.reject(new Error('watch unavailable'));
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ student: { id: 's-2' }, reviewVideos: [] }),
    });
  },
  resolveAcademyAccess: () => true,
});
assert.deepEqual(plain(watchFailureLoaded.initialData[7]), {});
assert.equal(watchFailureCalls.length, 2, 'watch failure must not trigger legacy fallback requests');

const bootstrapFailureCalls = [];
await assert.rejects(api.loadInitialData({
  publicMode: false,
  date: '2026-08-28',
  sid: 's-3',
  fetchImpl(url, init) {
    bootstrapFailureCalls.push({ url, init: init ? plain(init) : null });
    if (url.startsWith('/api/watch/latest?')) {
      return Promise.resolve({ json: async () => ({ watch: {} }) });
    }
    return Promise.resolve({ ok: false, status: 503, json: async () => ({}) });
  },
  resolveAcademyAccess: () => true,
}), error => error?.message === 'bootstrap 503');
assert.deepEqual(bootstrapFailureCalls.map(call => call.url), [
  '/api/watch/latest?sid=s-3',
  '/api/student/bootstrap?sid=s-3&date=2026-08-28',
]);

const malformedBootstrapCalls = [];
await assert.rejects(api.loadInitialData({
  publicMode: false,
  date: '2026-08-28',
  sid: 's-4',
  fetchImpl(url) {
    malformedBootstrapCalls.push(url);
    if (url.startsWith('/api/watch/latest?')) {
      return Promise.resolve({ json: async () => ({ watch: {} }) });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => { throw new Error('malformed bootstrap JSON'); },
    });
  },
  resolveAcademyAccess: () => true,
}), error => error?.message === 'malformed bootstrap JSON');
assert.equal(malformedBootstrapCalls.length, 2, 'malformed bootstrap must stop without fallback requests');

const publicAdapter = { marker: 'public-session' };
let publicArgs = null;
let publicFetchCount = 0;
const publicLoaded = await api.loadInitialData({
  publicMode: true,
  date: '2026-08-28',
  sid: 'page-sid',
  pageSid: 'page-sid',
  publicSession: publicAdapter,
  fetchImpl() {
    publicFetchCount += 1;
    throw new Error('public mode must use the injected session loader');
  },
  async loadPublicBootstrap(args) {
    publicArgs = plain(args);
    assert.equal(args.adapter, publicAdapter);
    return {
      activeSid: 'active-sid',
      bootstrap: {
        student: { id: 'active-sid', name: '공개 학생' },
        videos: [],
        assignedTests: [],
        homeworkBooks: [],
        reviewVideos: [],
        academyAccessAllowed: false,
      },
      watch: { ok: true, sid: 'active-sid', date: '2026-08-28', watch: {} },
    };
  },
  resolveAcademyAccess: (publicMode, bootstrap) => publicMode === true && bootstrap.academyAccessAllowed === true,
});
assert.equal(publicFetchCount, 0);
assert.deepEqual(publicArgs, {
  adapter: { marker: 'public-session' },
  pageSid: 'page-sid',
  date: '2026-08-28',
});
assert.equal(publicLoaded.activeSid, 'active-sid');
assert.deepEqual(plain(publicLoaded.initialData), [
  [{ id: 'active-sid', name: '공개 학생' }],
  [],
  {},
  {},
  {},
  {},
  {},
  { ok: true, sid: 'active-sid', date: '2026-08-28', watch: {} },
  {
    courseBlocked: false,
    selfStudy: false,
    blockMessage: '',
    courseVideosCompleted: false,
    academyAccessAllowed: false,
    academyOnlyMessage: '',
    assignedTests: [],
    homeworkBooks: [],
    reviewVideos: [],
    reviewVideosMalformed: false,
    ghostStudent: false,
    redirectSid: '',
    recoveryReason: '',
    dashboard: null,
    videoProjectionAuthoritative: true,
  },
]);

const bootstrapScript = '/js/student/bootstrapState.js?v=20260828-bootstrap-state-r1';
const watchScript = '/js/student/watchState.js?v=20260828-watch-state-r1';
const playbackScript = '/js/student/playback.js?v=20260828-playback-r1';
const reviewPlaylistScript = '/js/student/reviewPlaylist.js?v=20260828-review-playlist-r1';
const announcementStateScript = '/js/student/announcementState.js?v=20260828-announcement-state-r1';
const testPresentationScript = '/js/student/testPresentation.js?v=20260828-test-presentation-r1';
const studentScript = '/js/student.js?v=20260828-test-presentation-r1';
assert.equal((htmlSource.match(/\/js\/student\/bootstrapState\.js/g) || []).length, 1);
assert.equal((htmlSource.match(/\/js\/student\/watchState\.js/g) || []).length, 1);
assert.equal((htmlSource.match(/\/js\/student\/playback\.js/g) || []).length, 1);
assert.equal((htmlSource.match(/\/js\/student\/reviewPlaylist\.js/g) || []).length, 1);
assert.equal((htmlSource.match(/\/js\/student\/announcementState\.js/g) || []).length, 1);
assert.equal((htmlSource.match(/\/js\/student\/testPresentation\.js/g) || []).length, 1);
assert.ok(htmlSource.includes(`<script defer src="${bootstrapScript}"></script>`));
assert.ok(htmlSource.includes(`<script defer src="${watchScript}"></script>`));
assert.ok(htmlSource.includes(`<script defer src="${playbackScript}"></script>`));
assert.ok(htmlSource.includes(`<script defer src="${reviewPlaylistScript}"></script>`));
assert.ok(htmlSource.includes(`<script defer src="${announcementStateScript}"></script>`));
assert.ok(htmlSource.includes(`<script defer src="${testPresentationScript}"></script>`));
assert.ok(htmlSource.indexOf(bootstrapScript) < htmlSource.indexOf(watchScript));
assert.ok(htmlSource.indexOf(watchScript) < htmlSource.indexOf(playbackScript));
assert.ok(htmlSource.indexOf(playbackScript) < htmlSource.indexOf(reviewPlaylistScript));
assert.ok(htmlSource.indexOf(reviewPlaylistScript) < htmlSource.indexOf(announcementStateScript));
assert.ok(htmlSource.indexOf(announcementStateScript) < htmlSource.indexOf(testPresentationScript));
assert.ok(htmlSource.indexOf(testPresentationScript) < htmlSource.indexOf(studentScript));
assert.ok(studentSource.includes('window.StudentBootstrapState.loadInitialData({'));
assert.equal(studentSource.includes('function bootstrapInitialData('), false);
const loadStart = studentSource.indexOf('async function loadInitialData()');
const loadEnd = studentSource.indexOf('\n\n  loadInitialData().then(init)', loadStart);
assert.ok(loadStart >= 0 && loadEnd > loadStart);
const loadBlock = studentSource.slice(loadStart, loadEnd);
assert.equal(loadBlock.includes('/api/'), false, 'student.js load wrapper must not own bootstrap endpoint calls');
assert.equal(loadBlock.includes('fetch('), false, 'student.js load wrapper must delegate transport');
for (const forbidden of ['document.', 'localStorage', 'sessionStorage', 'location.', 'alert(']) {
  assert.equal(moduleSource.includes(forbidden), false, `bootstrap state module must stay UI-free: ${forbidden}`);
}

console.log('student bootstrap state checks passed: literal projection, concurrent load, stop-on-failure, public injection, and script order');
