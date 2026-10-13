import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..', '..');
const files = Object.freeze({
  student: path.join(root, 'static', 'js', 'student.js'),
  announcementState: path.join(root, 'static', 'js', 'student', 'announcementState.js'),
  playback: path.join(root, 'static', 'js', 'student', 'playback.js'),
  app: path.join(root, 'static', 'js', 'student-app.js'),
  contract: path.join(root, 'static', 'js', 'student-app-contract.js'),
  html: path.join(root, 'static', 'student.html'),
  css: path.join(root, 'static', 'css', 'student.css'),
  adminHtml: path.join(root, 'static', 'admin.html'),
  adminJs: path.join(root, 'static', 'js', 'admin', 'features', 'announcements.js'),
});

function extract(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, `missing source scope ${startMarker}`);
  return source.slice(start, end);
}

function eventId(character = 'a') {
  return `evt_${character.repeat(32)}`;
}

function notice(overrides = {}) {
  return {
    id: 'ann-1',
    type: 'notice',
    kind: 'announcement',
    title: '<img src=x onerror=alert(1)>',
    content: 'safe content',
    createdAt: '2026-08-09T01:00:00Z',
    expiresAt: '2026-08-10T01:00:00Z',
    read: false,
    notificationEventId: eventId('a'),
    images: [{ url: '/files/announcements/safe.png', mime: 'image/png' }],
    requireCompletion: false,
    ...overrides,
  };
}

function video(overrides = {}) {
  return {
    id: 'video-1',
    type: 'video',
    kind: 'video',
    title: '보강 영상',
    content: '학원에서 재생',
    createdAt: '2026-08-09T02:00:00Z',
    expiresAt: '2026-08-10T02:00:00Z',
    read: false,
    notificationEventId: eventId('b'),
    thumbnail: null,
    videoMid: 'video_mid_1',
    locked: true,
    ...overrides,
  };
}

function loadContracts(studentSource, announcementStateSource) {
  const links = extract(studentSource, '/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_START */', '/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_END */');
  const sandbox = {
    Object, Set, Date, String, Array, Number, URLSearchParams, RegExp, JSON, Promise, Error,
  };
  sandbox.window = sandbox;
  const context = vm.createContext(sandbox);
  vm.runInContext(announcementStateSource, context, { filename: 'static/js/student/announcementState.js' });
  vm.runInContext(`${links}\n` + `
    globalThis.boardContracts = {
      normalizeBoardItem: StudentAnnouncementState.normalizeBoardItem,
      normalizeBoardPage: StudentAnnouncementState.normalizeBoardPage,
      studentAppBoardDeepLink,
    };
  `, context, { filename: 'static/js/student.js#board-contracts' });
  return context.boardContracts;
}

function loadBoardController(studentSource, mode) {
  const start = studentSource.indexOf('  async function loadStudentBoard');
  const end = studentSource.indexOf('  /* STUDENT_APP_BOARD_END */', start);
  assert.ok(start >= 0 && end > start, 'board loader scope must exist');
  const scope = studentSource.slice(start, end);
  class FakeStudentAppSessionError extends Error {
    constructor(code, status = 0, activeSid = '') {
      super(code);
      this.code = code;
      this.status = status;
      this.activeSid = activeSid;
    }
  }
  const recoveries = [];
  const statuses = [];
  const context = vm.createContext({
    Promise, Object, Set, console,
    STUDENT_APP_PUBLIC_MODE: true,
    STUDENT_APP_PUBLIC_SESSION: { activeSid: () => 'sid-current' },
    StudentAppSessionError: FakeStudentAppSessionError,
    boardRequestId: 0,
    boardLoading: false,
    announcementState: {
      resetBoard() {},
      boardCursor: () => null,
      currentBoardType: () => 'all',
      appendBoardPage: () => true,
      boardItemByIdentifier: () => null,
      boardItemList: () => [],
    },
    renderStudentBoard: () => true,
    setBoardStatus: (message, state) => statuses.push({ message, state }),
    normalizeBoardPage: () => null,
    focusBoardItem: () => false,
    handleStudentAppSessionFailure: error => {
      if (!(error instanceof FakeStudentAppSessionError)) return false;
      recoveries.push({ code: error.code, status: error.status, activeSid: error.activeSid });
      return true;
    },
    studentAppRequest: async () => {
      if (mode === 'stale-rotated') {
        context.boardRequestId += 1;
        throw new FakeStudentAppSessionError('sid_rotated', 409, 'sid-new');
      }
      if (mode === 'rotated') throw new FakeStudentAppSessionError('sid_rotated', 409, 'sid-new');
      return { status: 403, ok: false };
    },
  });
  vm.runInContext(`${scope}\nglobalThis.__loadStudentBoard = loadStudentBoard;`, context, {
    filename: 'static/js/student.js#board-loader',
  });
  return { load: context.__loadStudentBoard, recoveries, statuses };
}

async function noticeFocusResult(studentSource) {
  const start = studentSource.indexOf('  async function openStudentBoardItem');
  const end = studentSource.indexOf('  async function loadAnnouncements', start);
  assert.ok(start >= 0 && end > start, 'board item opener scope must exist');
  const noticeButton = { id: 'notice-button', focus() {} };
  const hiddenAction = { id: 'hidden-action', focus() {} };
  let rendered = null;
  const context = vm.createContext({
    Promise,
    announcementState: {
      boardItemByIdentifier: () => ({ id: 'ann-1', type: 'notice' }),
      findAnnouncement: () => ({ id: 'ann-1' }),
    },
    historyReturnFocus: noticeButton,
    noticeBtn: noticeButton,
    closeHistoryDialog: () => {},
    renderActive: (_announcement, options) => { rendered = options; },
  });
  vm.runInContext(`${studentSource.slice(start, end)}\nglobalThis.__openBoardItem = openStudentBoardItem;`, context, {
    filename: 'static/js/student.js#board-item',
  });
  assert.equal(await context.__openBoardItem('ann-1', hiddenAction), true);
  return { rendered, noticeButton, hiddenAction };
}

export async function runChecks() {
  const sources = await Object.fromEntries(await Promise.all(Object.entries(files).map(async ([key, value]) => [key, await fs.readFile(value, 'utf8')])));
  const contracts = loadContracts(sources.student, sources.announcementState);
  const checks = [];
  const check = (name, fn) => { fn(); checks.push(name); };
  const checkAsync = async (name, fn) => { await fn(); checks.push(name); };

  check('strict board payload accepts only the public projection', () => {
    const payload = { ok: true, type: 'all', items: [notice(), video()], nextCursor: null };
    const normalized = contracts.normalizeBoardPage(payload, 'all');
    assert.equal(normalized.items.length, 2);
    assert.equal(normalized.items[0].title, '<img src=x onerror=alert(1)>');
    assert.equal(normalized.items[1].locked, true);
  });

  check('malformed or authority-bearing board fields fail closed', () => {
    assert.equal(contracts.normalizeBoardPage({ ok: true, type: 'all', items: [video({ url: 'https://evil.test' })], nextCursor: null }, 'all'), null);
    assert.equal(contracts.normalizeBoardPage({ ok: true, type: 'all', items: [video({ videoMid: '../secret' })], nextCursor: null }, 'all'), null);
    assert.equal(contracts.normalizeBoardPage({ ok: true, type: 'all', items: [video({ thumbnail: 'https://evil.test/x.png' })], nextCursor: null }, 'all'), null);
    assert.equal(contracts.normalizeBoardPage({ ok: true, type: 'video', items: [video()], nextCursor: null }, 'all'), null);
    assert.equal(contracts.normalizeBoardPage({ ok: true, type: 'all', items: [notice(), notice()], nextCursor: null }, 'all'), null);
  });

  check('board deep links accept only one opaque notification alias', () => {
    assert.equal(contracts.studentAppBoardDeepLink(`?view=board&item=${eventId('c')}`), eventId('c'));
    assert.equal(contracts.studentAppBoardDeepLink('?view=board&item=ann-1'), '');
    assert.equal(contracts.studentAppBoardDeepLink(`?view=board&item=${eventId('c')}&item=${eventId('d')}`), '');
    assert.equal(contracts.studentAppBoardDeepLink(`?announcement=ann-1&view=board&item=${eventId('c')}`), '');
  });

  check('student board fetch never sends SID and pagination is stale-safe', () => {
    const boardScope = extract(sources.student, '/* STUDENT_APP_BOARD_START */', '/* STUDENT_APP_BOARD_END */');
    assert.match(boardScope, /\/api\/mobile\/student\/board\?type=\$\{encodeURIComponent\(requestedType\)\}/);
    assert.doesNotMatch(boardScope, /[?&]sid=|localStorage|sessionStorage/);
    assert.match(boardScope, /requestId !== boardRequestId/);
    assert.match(boardScope, /announcementState\.resetBoard\(\)/);
    assert.match(boardScope, /announcementState\.appendBoardPage\(page\)/);
  });

  check('locked video returns before playback and safe MID dispatch is single-owner', () => {
    const openStart = sources.student.indexOf('  async function openStudentBoardItem');
    const openEnd = sources.student.indexOf('  async function loadAnnouncements', openStart);
    const scope = sources.student.slice(openStart, openEnd);
    assert.ok(scope.indexOf('if (item.locked)') >= 0);
    assert.ok(scope.indexOf("return false;", scope.indexOf('if (item.locked)')) < scope.indexOf("new CustomEvent('student-app:play-board-video'"));
    assert.match(sources.student, /document\.addEventListener\('student-app:play-board-video'/);
    assert.match(sources.playback, /async function play\(mid\)[\s\S]*\/api\/get-url\?mid=/);
  });

  check('board session failures and notice focus return use the public recovery boundary', () => {
    const loadStart = sources.student.indexOf('  async function loadStudentBoard');
    const loadEnd = sources.student.indexOf('  /* STUDENT_APP_BOARD_END */', loadStart);
    const loadScope = sources.student.slice(loadStart, loadEnd);
    const openStart = sources.student.indexOf('  async function openStudentBoardItem');
    const openEnd = sources.student.indexOf('  async function loadAnnouncements', openStart);
    const openScope = sources.student.slice(openStart, openEnd);
    assert.match(loadScope, /throw new StudentAppSessionError\([\s\S]*response\.status/);
    assert.match(loadScope, /if \(handleStudentAppSessionFailure\(error\)\) return false/);
    assert.doesNotMatch(loadScope, /handleStudentAppSessionFailure\(\s*\{/);
    assert.match(openScope, /const returnFocus = historyReturnFocus \|\| noticeBtn/);
    assert.doesNotMatch(openScope, /const returnFocus = opener\?\.focus/);
  });

  await checkAsync('board rotation and 403 responses recover with typed errors and notice returns to the board opener', async () => {
    const rotated = loadBoardController(sources.student, 'rotated');
    assert.equal(await rotated.load({ reset: true }), false);
    assert.deepEqual(rotated.recoveries, [{ code: 'sid_rotated', status: 409, activeSid: 'sid-new' }]);
    assert.equal(rotated.statuses.some(row => row.state === 'error'), false);

    const forbidden = loadBoardController(sources.student, 'forbidden');
    assert.equal(await forbidden.load({ reset: true }), false);
    assert.deepEqual(forbidden.recoveries, [{ code: 'session_not_ready', status: 403, activeSid: 'sid-current' }]);

    const staleRotated = loadBoardController(sources.student, 'stale-rotated');
    assert.equal(await staleRotated.load({ reset: true }), false);
    assert.deepEqual(staleRotated.recoveries, [{ code: 'sid_rotated', status: 409, activeSid: 'sid-new' }]);
    assert.equal(staleRotated.statuses.some(row => row.state === 'error'), false);

    const focus = await noticeFocusResult(sources.student);
    assert.equal(focus.rendered.opener, focus.noticeButton);
    assert.notEqual(focus.rendered.opener, focus.hiddenAction);
  });

  check('board rendering uses textContent and accessible focus controls', () => {
    const renderStart = sources.student.indexOf('  function renderStudentBoard()');
    const renderEnd = sources.student.indexOf('  function focusBoardItem', renderStart);
    const scope = sources.student.slice(renderStart, renderEnd);
    assert.match(scope, /titleNode\.textContent = item\.title/);
    assert.match(scope, /contentNode\.textContent = item\.content/);
    assert.doesNotMatch(scope, /innerHTML/);
    assert.match(sources.student, /trapDialogFocus\(historyModal, ev\)/);
    assert.match(sources.student, /closeHistoryDialog\(\)/);
  });

  check('board shell exposes filters, pagination, status, and 44px responsive controls', () => {
    for (const value of ['all', 'notice', 'video']) assert.match(sources.html, new RegExp(`data-student-board-type=["']${value}["']`));
    assert.match(sources.html, /id=["']studentBoardMore["']/);
    assert.match(sources.html, /id=["']studentBoardStatus["'][^>]*role=["']status["']/);
    assert.match(sources.css, /student-app-mobile-surface[\s\S]*student-board-filters/);
    assert.match(sources.css, /student-board-card button, \.student-board-more[\s\S]*min-height:\s*44px/);
    assert.match(sources.css, /#annHistoryList\s*\{[\s\S]*?grid-auto-rows:\s*max-content/);
    assert.match(sources.css, /#announceHistoryModal \.announce-close\s*\{[\s\S]*?flex:\s*0 0 44px[\s\S]*?min-width:\s*44px[\s\S]*?min-height:\s*44px/);
    assert.match(sources.css, /safe-area-inset-left/);
  });

  check('existing acknowledgement reply and survey flows remain delegated', () => {
    assert.match(sources.student, /renderActive\(announcement, \{ fromHistory: true/);
    for (const endpoint of ['/api/announce-ack', '/api/announce-submit']) assert.ok(sources.student.includes(endpoint));
    assert.match(sources.student, /submitSurvey/);
    assert.match(sources.student, /submitReply/);
  });

  check('admin video posts choose a catalog MID and never accept a free URL', () => {
    assert.match(sources.adminHtml, /id=["']annVideoMid["'][^>]*>/);
    assert.doesNotMatch(sources.adminHtml, /id=["']annVideoUrl["']/);
    assert.match(sources.adminJs, /Array\.isArray\(state\.videos\)/);
    assert.match(sources.adminJs, /payload\.videoMid = videoMid/);
    assert.match(sources.adminJs, /kind:\s*isSurvey \? 'survey' : isVideo \? 'video'/);
  });

  check('ready session auto-entry waits for push assessment and runs once', () => {
    const bootstrap = sources.app.slice(sources.app.indexOf('  async function bootstrap()'), sources.app.indexOf('  function destroy'));
    assert.match(sources.app, /let readyEntryStarted = false/);
    assert.match(sources.app, /if \(!autoEnterReady \|\| readyEntryStarted \|\| state\.status !== 'ready'\) return false/);
    assert.match(bootstrap, /const next = await resolveGate\(await api\.getInitialState\(\)\)/);
    assert.match(bootstrap, /if \(!enterReady\(next\)\) render/);
    assert.doesNotMatch(bootstrap, /pushGate\.activate|requestPermission/);
  });

  const { studentPageUrl } = await import(pathToFileURL(files.contract).href);
  check('active SID navigation preserves only canonical board targets', () => {
    assert.equal(studentPageUrl('sid-new', `?view=board&item=${eventId('d')}`), `/student/sid-new?view=board&item=${eventId('d')}`);
    assert.equal(studentPageUrl('sid-new', '?view=board&item=ann-old'), '/student/sid-new');
    assert.equal(studentPageUrl('../sid-old', `?view=board&item=${eventId('d')}`), '/app');
  });

  return { name: 'board', checks: checks.length, passed: true };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  runChecks().then(result => console.log(`student-mobile-app board: ${result.checks} assertions passed`), error => {
    console.error(error);
    process.exitCode = 1;
  });
}
