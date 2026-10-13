import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';

const moduleSource = fs.readFileSync('static/js/student/announcementState.js', 'utf8');
const studentSource = fs.readFileSync('static/js/student.js', 'utf8');
const htmlSource = fs.readFileSync('static/student.html', 'utf8');
const context = { window: {} };
vm.runInNewContext(moduleSource, context, { filename: 'static/js/student/announcementState.js' });

const api = context.window.StudentAnnouncementState;
assert.ok(api && typeof api.createController === 'function', 'announcement state module contract was not published');

function sha256(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function eventId(character) {
  return `evt_${character.repeat(32)}`;
}

function boardNotice(id, character, overrides = {}) {
  return {
    id,
    type: 'notice',
    kind: 'announcement',
    title: `Notice ${id}`,
    content: 'Safe content',
    createdAt: '2026-08-28T01:00:00Z',
    expiresAt: '2026-08-29T01:00:00Z',
    read: false,
    notificationEventId: eventId(character),
    images: [{ url: '/files/announcements/safe.png', mime: 'image/png' }],
    requireCompletion: false,
    ...overrides,
  };
}

function boardVideo(overrides = {}) {
  return {
    id: 'video-1',
    type: 'video',
    kind: 'video',
    title: 'Video',
    content: 'Academy playback',
    createdAt: '2026-08-28T02:00:00Z',
    expiresAt: '2026-08-29T02:00:00Z',
    read: false,
    notificationEventId: eventId('v'),
    thumbnail: null,
    videoMid: 'video_mid_1',
    locked: true,
    ...overrides,
  };
}

const requiredSurvey = {
  id: 'survey-required',
  title: 'Required survey',
  content: 'Please answer',
  requireCompletion: true,
  survey: {
    status: 'public',
    anonymous: true,
    allowMultiple: false,
    questions: [{ id: 'q1', type: 'single', text: 'Choose', options: [{ id: 'yes', text: 'Yes' }] }],
  },
};
const notice = { id: 'notice-1', title: 'Notice', requireCompletion: false };
const replyAnnouncement = { id: 'reply-1', title: 'Reply', requireCompletion: false };
const fixtureInput = {
  announcements: [notice, requiredSurvey, replyAnnouncement],
  statuses: {
    'survey-required': { acked: true },
    'reply-1': {
      acked: true,
      reply: 'first',
      repliedAt: '2026-08-28T03:00:00Z',
      replies: [{ reply: 'first', anonymous: false, repliedAt: '2026-08-28T03:00:00Z' }],
    },
  },
};
const inputHash = sha256(fixtureInput);
const controller = api.createController({ replyLimit: 3 });

assert.deepEqual(plain(controller.replaceAnnouncements(fixtureInput.announcements, fixtureInput.statuses)), { pending: 2, total: 3 });
assert.deepEqual(Array.from(controller.pendingItems()).map(item => item.id), ['notice-1', 'survey-required']);
controller.markAcked(notice);
assert.deepEqual(plain(controller.summary()), { pending: 1, total: 3 });
controller.markAcked(requiredSurvey);
assert.deepEqual(plain(controller.summary()), { pending: 1, total: 3 }, 'ack alone cannot complete a required survey');

const surveyAnswers = { q1: 'yes' };
const surveyEntry = { answers: surveyAnswers, anonymous: true, submittedAt: '2026-08-28T04:00:00Z' };
controller.recordSurvey(requiredSurvey, { surveyAnswers, surveyEntry, survey: requiredSurvey.survey });
assert.deepEqual(plain(controller.summary()), { pending: 0, total: 3 });
assert.equal(controller.statusFor(requiredSurvey).acked, true);
assert.equal(controller.statusFor(requiredSurvey).surveySubmittedAt, surveyEntry.submittedAt);
assert.equal(controller.statusFor(requiredSurvey).surveyResponses.length, 1);

assert.equal(controller.replyCount(replyAnnouncement), 1, 'legacy reply mirror must not double count an existing row');
assert.equal(api.replyLimitMessage(1), '2번 더 답장 가능!');
assert.equal(api.replyLimitMessage(2), '마지막 답장 남음!');
assert.equal(api.replyLimitMessage(3), '이제 쉿!');
assert.ok(controller.recordReply(replyAnnouncement, {
  reply: 'second',
  anonymous: true,
  replyEntry: { reply: 'second', anonymous: true, repliedAt: '2026-08-28T05:00:00Z' },
}));
assert.ok(controller.recordReply(replyAnnouncement, {
  reply: 'third',
  anonymous: false,
  replyEntry: { reply: 'third', anonymous: false, repliedAt: '2026-08-28T06:00:00Z' },
}));
assert.equal(controller.replyCount(replyAnnouncement), 3);
assert.equal(controller.replyLimitReached(replyAnnouncement), true);
assert.equal(controller.recordReply(replyAnnouncement, {
  reply: 'fourth',
  replyEntry: { reply: 'fourth', repliedAt: '2026-08-28T07:00:00Z' },
}), null);
assert.equal(sha256(fixtureInput), inputHash, 'announcement transitions mutated their server fixture inputs');

assert.deepEqual(
  Array.from(api.normalizeAnnouncementImages({
    images: [{ url: '/files/announcements/a.png' }, { sourceUrl: '/files/announcements/a.png' }],
    image: { url: '/files/announcements/fallback.png' },
  })).map(item => item.url),
  ['/files/announcements/a.png'],
  'announcement images must keep first-seen URLs without adding a fallback when the list is usable',
);

const firstPageInput = {
  ok: true,
  type: 'all',
  items: [boardNotice('board-1', 'a'), boardVideo()],
  nextCursor: 'cursor_1',
};
const boardHash = sha256(firstPageInput);
const firstPage = api.normalizeBoardPage(firstPageInput, 'all');
assert.equal(firstPage.items.length, 2);
assert.equal(firstPage.items[1].locked, true);
assert.equal(api.normalizeBoardPage({ ...firstPageInput, extra: true }, 'all'), null);
assert.equal(api.normalizeBoardPage({ ...firstPageInput, items: [boardVideo({ videoMid: '../unsafe' })] }, 'all'), null);
assert.equal(api.normalizeBoardPage({ ...firstPageInput, items: [boardVideo({ thumbnail: 'https://evil.test/x.png' })] }, 'all'), null);
assert.equal(api.normalizeBoardPage({ ...firstPageInput, type: 'notice' }, 'all'), null);
assert.equal(sha256(firstPageInput), boardHash, 'board normalization mutated its transport fixture');

controller.resetBoard();
assert.equal(controller.appendBoardPage(firstPage), true);
assert.equal(controller.boardCursor(), 'cursor_1');
assert.equal(controller.boardItemByIdentifier(eventId('v')).id, 'video-1');
const secondPage = api.normalizeBoardPage({
  ok: true,
  type: 'all',
  items: [boardNotice('board-1', 'a'), boardNotice('board-2', 'b')],
  nextCursor: null,
}, 'all');
controller.appendBoardPage(secondPage);
assert.deepEqual(Array.from(controller.boardItemList()).map(item => item.id), ['board-1', 'video-1', 'board-2']);
assert.equal(controller.markBoardItemRead('video-1'), true);
assert.equal(controller.boardItemByIdentifier('video-1').read, true);
assert.equal(controller.setBoardType('unsafe'), false);
assert.equal(controller.setBoardType('all'), false);
assert.equal(controller.setBoardType('notice'), true);
assert.equal(controller.currentBoardType(), 'notice');
controller.resetBoard();
assert.deepEqual(Array.from(controller.boardItemList()), []);
assert.equal(controller.boardCursor(), null);

for (const forbidden of ['document', 'fetch(', 'localStorage', 'sessionStorage', '/api/']) {
  assert.equal(moduleSource.includes(forbidden), false, `announcement state module leaked an ambient dependency: ${forbidden}`);
}
for (const retired of [
  'let announcements = []',
  'let statusMap = {}',
  'let pending = []',
  'let boardType =',
  'let boardItems = []',
  'function normalizeBoardItem(',
  'function replyRowsForStatus(',
]) {
  assert.equal(studentSource.includes(retired), false, `student entrypoint still owns announcement state primitive: ${retired}`);
}
assert.ok(studentSource.includes('window.StudentAnnouncementState'));
assert.ok(studentSource.includes('announcementState.replaceAnnouncements(anns, stat)'));
assert.ok(studentSource.includes('announcementState.recordSurvey(item'));
assert.ok(studentSource.includes('announcementState.recordReply(item'));

const reviewPlaylistScript = '/js/student/reviewPlaylist.js?v=20260828-review-playlist-r1';
const announcementStateScript = '/js/student/announcementState.js?v=20260828-announcement-state-r1';
const testPresentationScript = '/js/student/testPresentation.js?v=20260907-ilsan-level-r1';
const studentScript = '/js/student.js?v=20260907-ilsan-level-r1';
assert.equal((htmlSource.match(/\/js\/student\/announcementState\.js/g) || []).length, 1);
assert.ok(htmlSource.indexOf(reviewPlaylistScript) < htmlSource.indexOf(announcementStateScript));
assert.ok(htmlSource.indexOf(announcementStateScript) < htmlSource.indexOf(testPresentationScript));
assert.ok(htmlSource.indexOf(testPresentationScript) < htmlSource.indexOf(studentScript));

console.log('student announcement state checks passed: strict board projection, pending, ack, survey, reply limit, pagination, isolation, and shell order');
