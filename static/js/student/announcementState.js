(function studentAnnouncementStateModule(global) {
  'use strict';

  const DEFAULT_REPLY_LIMIT = 3;
  const BOARD_TYPES = Object.freeze(['all', 'notice', 'video']);
  const BOARD_NOTICE_KEYS = new Set([
    'id', 'type', 'kind', 'title', 'content', 'createdAt', 'expiresAt', 'read',
    'notificationEventId', 'images', 'requireCompletion',
  ]);
  const BOARD_VIDEO_KEYS = new Set([
    'id', 'type', 'kind', 'title', 'content', 'createdAt', 'expiresAt', 'read',
    'notificationEventId', 'thumbnail', 'videoMid', 'locked',
  ]);

  function exactObjectKeys(value, expected) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const keys = Object.keys(value);
    return keys.length === expected.size && keys.every(key => expected.has(key));
  }

  function boardImageUrl(value) {
    const url = typeof value === 'string' ? value.trim() : '';
    return /^\/files\/announcements\/[A-Za-z0-9._-]+\.(?:jpe?g|png|gif|webp|bmp)$/i.test(url) ? url : '';
  }

  function normalizeBoardItem(source) {
    const type = source?.type;
    const expected = type === 'notice' ? BOARD_NOTICE_KEYS : type === 'video' ? BOARD_VIDEO_KEYS : null;
    if (!expected || !exactObjectKeys(source, expected)) return null;
    const id = typeof source.id === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(source.id) ? source.id : '';
    const eventId = typeof source.notificationEventId === 'string' && /^evt_[A-Za-z0-9_-]{32}$/.test(source.notificationEventId)
      ? source.notificationEventId
      : '';
    const createdAt = typeof source.createdAt === 'string' && Number.isFinite(Date.parse(source.createdAt)) ? source.createdAt : '';
    const expiresAt = typeof source.expiresAt === 'string' && Number.isFinite(Date.parse(source.expiresAt)) ? source.expiresAt : '';
    const title = typeof source.title === 'string' ? source.title.trim().slice(0, 400) : '';
    const content = typeof source.content === 'string' ? source.content.trim().slice(0, 10000) : '';
    if (!id || !eventId || !createdAt || !expiresAt || Date.parse(createdAt) >= Date.parse(expiresAt) || !title || typeof source.read !== 'boolean') return null;
    if (type === 'video') {
      const mid = typeof source.videoMid === 'string' ? source.videoMid.trim() : '';
      const thumbnail = source.thumbnail == null ? null : boardImageUrl(source.thumbnail);
      if (source.kind !== 'video' || !/^[A-Za-z0-9_-]{4,128}$/.test(mid) || typeof source.locked !== 'boolean' || (source.thumbnail != null && !thumbnail)) return null;
      return Object.freeze({ id, type, kind: 'video', title, content, createdAt, expiresAt, read: source.read, notificationEventId: eventId, thumbnail, videoMid: mid, locked: source.locked });
    }
    const kind = source.kind === 'survey' ? 'survey' : source.kind === 'announcement' ? 'announcement' : '';
    if (!kind || typeof source.requireCompletion !== 'boolean' || !Array.isArray(source.images) || source.images.length > 10) return null;
    const images = source.images.map(image => {
      if (!exactObjectKeys(image, new Set(['url', 'mime']))) return null;
      const url = boardImageUrl(image.url);
      const mime = typeof image.mime === 'string' ? image.mime.trim().slice(0, 100) : '';
      return url && /^image\//.test(mime) ? Object.freeze({ url, mime }) : null;
    });
    if (images.some(image => image === null)) return null;
    return Object.freeze({ id, type, kind, title, content, createdAt, expiresAt, read: source.read, notificationEventId: eventId, images: Object.freeze(images), requireCompletion: source.requireCompletion });
  }

  function normalizeBoardPage(source, requestedType) {
    const expected = new Set(['ok', 'type', 'items', 'nextCursor']);
    if (!exactObjectKeys(source, expected) || source.ok !== true || source.type !== requestedType || !Array.isArray(source.items) || source.items.length > 50) return null;
    const items = source.items.map(normalizeBoardItem);
    const cursor = source.nextCursor == null ? null : (typeof source.nextCursor === 'string' && /^[A-Za-z0-9_-]{1,1024}$/.test(source.nextCursor) ? source.nextCursor : '');
    if (items.some(item => item === null) || cursor === '') return null;
    const ids = new Set();
    if (items.some(item => ids.has(item.id) || (ids.add(item.id), false))) return null;
    return Object.freeze({ items: Object.freeze(items), nextCursor: cursor });
  }

  function normalizeAnnouncementImage(image) {
    if (!image || typeof image !== 'object') return null;
    const url = String(image.originalUrl || image.sourceUrl || image.fullUrl || image.url || '').trim();
    if (!url) return null;
    return { url, alt: '' };
  }

  function normalizeAnnouncementImages(announcement) {
    const rawImages = Array.isArray(announcement?.images) ? announcement.images : [];
    const images = rawImages.map(normalizeAnnouncementImage).filter(Boolean);
    if (!images.length) {
      const image = normalizeAnnouncementImage(announcement?.image);
      if (image) images.push(image);
    }
    const seen = new Set();
    return images.filter(image => {
      if (!image.url || seen.has(image.url)) return false;
      seen.add(image.url);
      return true;
    });
  }

  function getSurvey(announcement) {
    const survey = announcement?.survey;
    if (!survey || typeof survey !== 'object' || !Array.isArray(survey.questions)) return null;
    if (survey.status && survey.status !== 'public') return null;
    return survey;
  }

  function hasSurveySubmissionForStatus(status) {
    const value = status && typeof status === 'object' ? status : {};
    if (value.surveySubmittedAt && value.surveyAnswers && typeof value.surveyAnswers === 'object') return true;
    return Array.isArray(value.surveyResponses) && value.surveyResponses.some(row => row && typeof row.answers === 'object');
  }

  function replyRowsForStatus(status) {
    const value = status && typeof status === 'object' ? status : {};
    const rows = Array.isArray(value.replies)
      ? value.replies.filter(row => row && String(row.reply || '').trim())
      : [];
    const legacyReply = String(value.reply || '').trim();
    const legacyAt = String(value.repliedAt || '');
    if (legacyReply && !rows.some(row => String(row.reply || '').trim() === legacyReply && String(row.repliedAt || '') === legacyAt)) {
      rows.push({ reply: legacyReply, anonymous: !!value.anonymous, repliedAt: legacyAt });
    }
    return rows;
  }

  function replyLimitMessage(count) {
    if (count <= 1) return '2번 더 답장 가능!';
    if (count === 2) return '마지막 답장 남음!';
    return '이제 쉿!';
  }

  function surveyTypeText(type) {
    return {
      single: '하나만 선택',
      multiple: '복수 선택 가능',
      short: '짧은 답변',
      long: '긴 답변',
    }[type] || '질문';
  }

  function surveyOptionText(question, value) {
    const options = Array.isArray(question?.options) ? question.options : [];
    const found = options.find(option => String(option?.id) === String(value));
    return found?.text || value || '';
  }

  function createController(options = {}) {
    const parsedLimit = Number(options.replyLimit);
    const replyLimit = Number.isInteger(parsedLimit) && parsedLimit > 0 ? parsedLimit : DEFAULT_REPLY_LIMIT;
    let announcements = [];
    let statusMap = {};
    let boardType = 'all';
    let boardItems = [];
    let boardNextCursor = null;

    function announcementId(value) {
      return String(value && typeof value === 'object' ? value.id ?? '' : value ?? '');
    }

    function announcementItems() {
      return [...announcements];
    }

    function replaceAnnouncements(rawAnnouncements, rawStatusMap) {
      announcements = Array.isArray(rawAnnouncements) ? rawAnnouncements.slice() : [];
      statusMap = rawStatusMap && typeof rawStatusMap === 'object' ? { ...rawStatusMap } : {};
      return summary();
    }

    function findAnnouncement(identifier) {
      const id = String(identifier ?? '');
      return announcements.find(item => String(item?.id ?? '') === id) || null;
    }

    function statusFor(value) {
      const status = statusMap[announcementId(value)];
      return status && typeof status === 'object' ? status : {};
    }

    function hasSurveySubmission(announcement) {
      return hasSurveySubmissionForStatus(statusFor(announcement));
    }

    function isAcked(announcement) {
      return !!statusFor(announcement).acked;
    }

    function isComplete(announcement) {
      const survey = getSurvey(announcement);
      if (survey && announcement?.requireCompletion !== false) return hasSurveySubmission(announcement);
      return isAcked(announcement);
    }

    function pendingItems() {
      return announcements.filter(announcement => !isComplete(announcement));
    }

    function summary() {
      return { pending: pendingItems().length, total: announcements.length };
    }

    function markAcked(value) {
      const id = announcementId(value);
      if (!id) return null;
      const next = { ...statusFor(id), acked: true };
      statusMap = { ...statusMap, [id]: next };
      return next;
    }

    function recordSurvey(value, { surveyAnswers, surveyEntry, survey } = {}) {
      const id = announcementId(value);
      if (!id || !surveyAnswers || typeof surveyAnswers !== 'object' || !surveyEntry || typeof surveyEntry !== 'object') return null;
      const current = statusFor(id);
      const surveyResponses = Array.isArray(current.surveyResponses) ? current.surveyResponses.slice() : [];
      surveyResponses.push(surveyEntry);
      const next = {
        ...current,
        acked: true,
        surveyAnswers,
        surveyAnonymous: !!survey?.anonymous,
        surveySubmittedAt: surveyEntry.submittedAt,
        surveyResponses,
      };
      statusMap = { ...statusMap, [id]: next };
      return next;
    }

    function replyCount(value) {
      return replyRowsForStatus(statusFor(value)).length;
    }

    function replyLimitReached(value) {
      return replyCount(value) >= replyLimit;
    }

    function recordReply(value, { reply, anonymous, replyEntry } = {}) {
      const id = announcementId(value);
      const replyText = String(reply ?? '').trim();
      if (!id || !replyText || !replyEntry || typeof replyEntry !== 'object' || replyLimitReached(id)) return null;
      const current = statusFor(id);
      const replies = replyRowsForStatus(current).slice();
      replies.push(replyEntry);
      const next = {
        ...current,
        reply: replyText,
        anonymous: !!anonymous,
        repliedAt: replyEntry.repliedAt,
        replies,
      };
      statusMap = { ...statusMap, [id]: next };
      return next;
    }

    function currentBoardType() {
      return boardType;
    }

    function setBoardType(value) {
      if (!BOARD_TYPES.includes(value) || value === boardType) return false;
      boardType = value;
      return true;
    }

    function resetBoard() {
      boardItems = [];
      boardNextCursor = null;
    }

    function appendBoardPage(page) {
      if (!page || !Array.isArray(page.items) || !Object.hasOwn(page, 'nextCursor')) return false;
      const known = new Set(boardItems.map(item => item.id));
      boardItems = boardItems.concat(page.items.filter(item => !known.has(item.id)));
      boardNextCursor = page.nextCursor;
      return true;
    }

    function boardItemList() {
      return [...boardItems];
    }

    function boardCursor() {
      return boardNextCursor;
    }

    function boardItemByIdentifier(identifier) {
      return boardItems.find(item => item.id === identifier || item.notificationEventId === identifier) || null;
    }

    function markBoardItemRead(identifier) {
      let changed = false;
      boardItems = boardItems.map(item => {
        if (item.id !== identifier || item.read) return item;
        changed = true;
        return Object.freeze({ ...item, read: true });
      });
      return changed;
    }

    return Object.freeze({
      announcementItems,
      appendBoardPage,
      boardCursor,
      boardItemByIdentifier,
      boardItemList,
      currentBoardType,
      findAnnouncement,
      getSurvey,
      hasSurveySubmission,
      isAcked,
      isComplete,
      markAcked,
      markBoardItemRead,
      pendingItems,
      recordReply,
      recordSurvey,
      replaceAnnouncements,
      replyCount,
      replyLimit,
      replyLimitReached,
      resetBoard,
      setBoardType,
      statusFor,
      summary,
    });
  }

  global.StudentAnnouncementState = Object.freeze({
    BOARD_TYPES,
    DEFAULT_REPLY_LIMIT,
    boardImageUrl,
    createController,
    exactObjectKeys,
    getSurvey,
    hasSurveySubmissionForStatus,
    normalizeAnnouncementImage,
    normalizeAnnouncementImages,
    normalizeBoardItem,
    normalizeBoardPage,
    replyLimitMessage,
    replyRowsForStatus,
    surveyOptionText,
    surveyTypeText,
  });
})(window);
