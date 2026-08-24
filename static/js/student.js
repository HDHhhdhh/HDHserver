/* student.js – 단일 플레이어 + 재생 목록 + 자료 다운로드 + 설정 패널 + 건의사항 제출 + 공지모달 + 오늘 자동배정 보정
   + (추가) 마지막 재생 기억 + 로컬 진행도(완주) 저장 + Kollus postMessage 대응(가능할 때만)
   + (표시개선) 파일명 표시에서 UUID/타임스탬프 접두어 제거(표시 전용, 실제 URL/경로는 그대로)
   + (Kollus 연동) VG Controller 브릿지: 플레이어 이벤트(progress/ready/done) → 우리 postMessage 포맷으로 재발행
*/
/* STUDENT_APP_PUBLIC_SESSION_START */
class StudentAppSessionError extends Error {
  constructor(code, status = 0, activeSid = '') {
    super(code);
    this.name = 'StudentAppSessionError';
    this.code = code;
    this.status = Number(status) || 0;
    this.activeSid = activeSid;
  }
}

function studentAppStrictSid(value) {
  const sid = typeof value === 'string' ? value.trim() : '';
  if (!sid || sid.length > 128 || sid === '.' || sid === '..') return '';
  return /[\s/\\%,\u0000-\u001f\u007f]/.test(sid) ? '' : sid;
}

const STUDENT_APP_PUBLIC_HOSTS = new Set(['app.5a-math.com', 'dev-app.5a-math.com']);

function studentAppIsPublicMode(locationRef) {
  const protocol = String(locationRef?.protocol || '').toLowerCase();
  const hostname = String(locationRef?.hostname || '').trim().toLowerCase();
  return protocol === 'https:' && STUDENT_APP_PUBLIC_HOSTS.has(hostname);
}

function createStudentAppSessionAdapter(options = {}) {
  const fetchImpl = options.fetchImpl || fetch;
  let current = null;
  let refreshPromise = null;

  async function responsePayload(response) {
    try { return await response.json(); }
    catch { return null; }
  }

  async function refreshSession({ force = false } = {}) {
    if (!force && current) return { activeSid: current.activeSid };
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      let response;
      try {
        response = await fetchImpl('/api/mobile/auth/session', {
          cache: 'no-store',
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
      } catch {
        current = null;
        throw new StudentAppSessionError('session_unavailable');
      }
      const payload = await responsePayload(response);
      const state = String(payload?.state || payload?.status || '');
      const activeSid = studentAppStrictSid(payload?.sid ?? payload?.sessionSid);
      const csrfToken = typeof payload?.csrfToken === 'string' ? payload.csrfToken.trim() : '';
      if (!response.ok || state !== 'ready' || !activeSid || !csrfToken) {
        current = null;
        throw new StudentAppSessionError(
          String(payload?.code || (response.status === 401 ? 'login_required' : 'session_not_ready')),
          response.status,
        );
      }
      const curris = Array.isArray(payload?.curris)
        ? payload.curris.map(item => ({ sid: studentAppStrictSid(item?.sid), cur: String(item?.cur || '').trim() })).filter(item => item.sid)
        : [];
      current = Object.freeze({ activeSid, csrfToken, curris, pushState: String(payload?.pushState || '') });
      return { activeSid };
    })();
    try { return await refreshPromise; }
    finally { refreshPromise = null; }
  }

  function assertBoundSid(input, init, activeSid) {
    const rawUrl = typeof input === 'string' ? input : input?.url;
    let allowsCurriculumTarget = false;
    if (typeof rawUrl === 'string') {
      const parsed = new URL(rawUrl, 'https://student-app.invalid');
      allowsCurriculumTarget = parsed.pathname === '/api/mobile/auth/switch';
      for (const requestedSid of parsed.searchParams.getAll('sid')) {
        if (requestedSid !== activeSid) throw new StudentAppSessionError('sid_mismatch', 403, activeSid);
      }
    }
    if (typeof init?.body !== 'string' || !init.body.trim()) return;
    let body;
    try { body = JSON.parse(init.body); }
    catch { return; }
    if (!body || typeof body !== 'object' || Array.isArray(body)) return;
    for (const key of ['sid', 'studentSid', 'activeSid']) {
      if (allowsCurriculumTarget && key === 'sid') continue;
      if (Object.hasOwn(body, key) && String(body[key]) !== activeSid) {
        throw new StudentAppSessionError('sid_mismatch', 403, activeSid);
      }
    }
  }

  async function request(input, init = {}, retryOnRotation = true) {
    const session = await refreshSession();
    assertBoundSid(input, init, session.activeSid);
    const method = String(init.method || 'GET').toUpperCase();
    const headers = new Headers(init.headers || {});
    if (!headers.has('Accept')) headers.set('Accept', 'application/json');
    headers.delete('Authorization');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('X-CSRF-Token', current.csrfToken);

    let response;
    try {
      response = await fetchImpl(input, { ...init, method, headers, credentials: 'same-origin' });
    } catch {
      throw new StudentAppSessionError('request_unavailable');
    }
    if (!retryOnRotation || (response.status !== 401 && response.status !== 403)) return response;

    let code = '';
    try { code = String((await response.clone().json())?.code || ''); }
    catch { code = ''; }
    const shouldRefresh = response.status === 401 || code === 'csrf_invalid' || code === 'csrf_required'
      || code === 'unauthenticated' || code === 'sid_mismatch';
    if (!shouldRefresh) return response;

    const previousSid = session.activeSid;
    current = null;
    const refreshed = await refreshSession({ force: true });
    if (refreshed.activeSid !== previousSid) {
      throw new StudentAppSessionError('sid_rotated', 409, refreshed.activeSid);
    }
    return request(input, init, false);
  }

  return Object.freeze({
    activeSid: () => current?.activeSid || '',
    sessionState: () => current ? { activeSid: current.activeSid, curris: current.curris.map(item => ({ ...item })), pushState: current.pushState } : null,
    refreshSession,
    request,
  });
}

async function loadPublicStudentBootstrap({ adapter, pageSid, date }) {
  const session = await adapter.refreshSession();
  if (pageSid && pageSid !== session.activeSid) {
    throw new StudentAppSessionError('sid_rotated', 409, session.activeSid);
  }
  const query = new URLSearchParams({ sid: session.activeSid, date: String(date) }).toString();
  const response = await adapter.request(`/api/student/bootstrap?${query}`, { cache: 'no-store' });
  if (!response.ok) throw new StudentAppSessionError('bootstrap_failed', response.status, session.activeSid);
  let bootstrap;
  try { bootstrap = await response.json(); }
  catch { throw new StudentAppSessionError('bootstrap_malformed', response.status, session.activeSid); }
  if (!bootstrap || typeof bootstrap !== 'object' || Array.isArray(bootstrap)) {
    throw new StudentAppSessionError('bootstrap_malformed', response.status, session.activeSid);
  }
  return { activeSid: session.activeSid, bootstrap, watch: bootstrap.watch || { ok: true, sid: session.activeSid, date: String(date), watch: {} } };
}
/* STUDENT_APP_PUBLIC_SESSION_END */

/* STUDENT_APP_ACADEMY_GATES_START */
const STUDENT_APP_KOLLUS_CONTROLLER_URL = 'https://file.kollus.com/vgcontroller/vg-controller-client.latest.min.js';
let studentAppKollusControllerPromise = null;

function studentAppAcademyAccessFromBootstrap(publicMode, bootstrap) {
  const value = bootstrap && typeof bootstrap === 'object' ? bootstrap : {};
  const notBlocked = value.outsideAcademyBlocked !== true && value.networkBlocked !== true;
  if (publicMode === true) return value.academyAccessAllowed === true && notBlocked;
  return value.academyAccessAllowed !== false && notBlocked;
}

function studentAppShouldLoadKollusController(publicMode, academyAccessAllowed) {
  return publicMode === true ? academyAccessAllowed === true : academyAccessAllowed !== false;
}

function loadStudentAppKollusController({
  publicMode,
  academyAccessAllowed,
  documentRef,
  globalRef,
}) {
  if (!studentAppShouldLoadKollusController(publicMode, academyAccessAllowed)) return Promise.resolve(false);
  if (globalRef?.VgControllerClient) return Promise.resolve(true);
  if (studentAppKollusControllerPromise) return studentAppKollusControllerPromise;

  const existing = documentRef?.querySelector?.('script[data-student-academy-controller="kollus"]');
  if (existing) return Promise.resolve(true);
  const parent = documentRef?.head || documentRef?.documentElement;
  if (!parent || typeof documentRef?.createElement !== 'function') return Promise.resolve(false);

  studentAppKollusControllerPromise = new Promise((resolve, reject) => {
    const script = documentRef.createElement('script');
    script.src = STUDENT_APP_KOLLUS_CONTROLLER_URL;
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.dataset.studentAcademyController = 'kollus';
    script.onload = () => resolve(true);
    script.onerror = () => {
      studentAppKollusControllerPromise = null;
      reject(new Error('kollus_controller_unavailable'));
    };
    parent.appendChild(script);
  });
  return studentAppKollusControllerPromise;
}

/* STUDENT_APP_ACADEMY_GATES_END */

/* STUDENT_APP_DASHBOARD_START */
const STUDENT_DASHBOARD_SCHEDULE_KIND_LABELS = Object.freeze({
  regular: '정규 수업',
  extra: '추가 수업',
  makeup: '보강',
  absence: '결석',
});
const STUDENT_DASHBOARD_SCHEDULE_STATUS_LABELS = Object.freeze({
  scheduled: '예정',
  completed: '완료',
  cancelled: '취소',
});

function studentDashboardNonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0 ? value : null;
}

function studentDashboardSafeText(value, maxLength = 80) {
  if (typeof value !== 'string') return '';
  const text = value.trim().replace(/\s+/g, ' ').slice(0, maxLength);
  const urlLike = /^(?:\/|\\)|(?:[a-z][a-z0-9+.-]*:|\/\/|www\.)|\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|app|kr|co\.kr)(?:[/?#]|$)/i;
  return urlLike.test(text) ? '' : text;
}

function studentDashboardDateLabel(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) return '';
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const leapYear = year % 400 === 0 || (year % 4 === 0 && year % 100 !== 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth[month - 1]) return '';
  return `${month}월 ${day}일`;
}

function studentDashboardTimeLabel(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) return '';
  const match = /^(\d{2}):(\d{2})$/.exec(text);
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return '';
  return text;
}

function normalizeStudentDashboard(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.enabled !== true) return null;

  const progressSource = value.curriculumProgress;
  if (!progressSource || typeof progressSource !== 'object' || Array.isArray(progressSource)) return null;
  if (progressSource.basis !== 'curriculum_videos_v1') return null;
  const progressState = String(progressSource.state || '');
  if (!['available', 'unavailable'].includes(progressState)) return null;
  const curriculum = studentDashboardSafeText(progressSource.curriculum);
  const subCurriculum = studentDashboardSafeText(progressSource.subCurriculum);
  let curriculumProgress;
  if (progressState === 'available') {
    const completed = studentDashboardNonNegativeInteger(progressSource.completed);
    const interrupted = studentDashboardNonNegativeInteger(progressSource.interrupted);
    const total = studentDashboardNonNegativeInteger(progressSource.total);
    const percent = studentDashboardNonNegativeInteger(progressSource.percent);
    const calculatedPercent = total > 0 && completed != null ? Math.round((completed / total) * 100) : null;
    if (completed == null || interrupted == null || total == null || percent == null
      || total === 0 || percent > 100 || percent !== calculatedPercent
      || completed > total || interrupted > total || completed + interrupted > total) return null;
    curriculumProgress = Object.freeze({
      state: progressState,
      curriculum,
      subCurriculum,
      completed,
      interrupted,
      total,
      percent,
    });
  } else {
    curriculumProgress = Object.freeze({
      state: progressState,
      curriculum,
      subCurriculum,
      completed: null,
      interrupted: null,
      total: null,
      percent: null,
    });
  }

  const homeworkSource = value.homeworkSummary;
  if (!homeworkSource || typeof homeworkSource !== 'object' || Array.isArray(homeworkSource)) return null;
  const homeworkState = String(homeworkSource.state || '');
  const homeworkCount = studentDashboardNonNegativeInteger(homeworkSource.count);
  if (!['assigned', 'empty'].includes(homeworkState) || homeworkCount == null
    || (homeworkState === 'assigned' && homeworkCount === 0)
    || (homeworkState === 'empty' && homeworkCount !== 0)) return null;

  let unreadBoardCount = null;
  if (value.unreadBoardCount != null) {
    unreadBoardCount = studentDashboardNonNegativeInteger(value.unreadBoardCount);
    if (unreadBoardCount == null) return null;
  }

  let nextSchedule = null;
  if (value.nextSchedule != null) {
    const source = value.nextSchedule;
    if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
    const kind = String(source.kind || '');
    const status = String(source.status || '');
    const dateLabel = studentDashboardDateLabel(source.date);
    const timeLabel = studentDashboardTimeLabel(source.timeLabel);
    if (!Object.hasOwn(STUDENT_DASHBOARD_SCHEDULE_KIND_LABELS, kind)
      || !Object.hasOwn(STUDENT_DASHBOARD_SCHEDULE_STATUS_LABELS, status)
      || !dateLabel || (source.timeLabel && !timeLabel) || !Array.isArray(source.slots)
      || source.slots.length > 3
      || source.slots.some(slot => !Number.isInteger(slot) || slot < 1 || slot > 3)
      || new Set(source.slots).size !== source.slots.length) return null;
    nextSchedule = Object.freeze({
      dateLabel,
      kind,
      status,
      timeLabel,
      slots: Object.freeze(source.slots.slice()),
    });
  }

  return Object.freeze({
    enabled: true,
    curriculumProgress,
    nextSchedule,
    homeworkSummary: Object.freeze({ state: homeworkState, count: homeworkCount }),
    unreadBoardCount,
  });
}

function studentDashboardViewModel(value) {
  const dashboard = normalizeStudentDashboard(value);
  if (!dashboard) return null;
  const progress = dashboard.curriculumProgress;
  const courseLabel = [progress.curriculum, progress.subCurriculum].filter(Boolean).join(' · ');
  const progressAvailable = progress.state === 'available';
  const schedule = dashboard.nextSchedule
    ? Object.freeze({
      available: true,
      kindLabel: STUDENT_DASHBOARD_SCHEDULE_KIND_LABELS[dashboard.nextSchedule.kind],
      statusLabel: STUDENT_DASHBOARD_SCHEDULE_STATUS_LABELS[dashboard.nextSchedule.status],
      whenLabel: [dashboard.nextSchedule.dateLabel, dashboard.nextSchedule.timeLabel].filter(Boolean).join(' · '),
      slotsLabel: dashboard.nextSchedule.slots.map(slot => `${slot}교시`).join(' · '),
    })
    : Object.freeze({
      available: false,
      kindLabel: '예정된 수업 없음',
      statusLabel: '',
      whenLabel: '다음 일정이 등록되면 알려드립니다.',
      slotsLabel: '',
    });
  return Object.freeze({
    progress: Object.freeze({
      available: progressAvailable,
      courseLabel: courseLabel || '과정 정보 없음',
      percent: progressAvailable ? progress.percent : null,
      percentLabel: progressAvailable ? `${progress.percent}%` : '확인 불가',
      countLabel: progressAvailable
        ? `완료 ${progress.completed} · 중단 ${progress.interrupted} · 전체 ${progress.total}`
        : '진도 정보를 확인할 수 없습니다.',
    }),
    schedule,
    homework: Object.freeze({
      count: dashboard.homeworkSummary.count,
      countLabel: dashboard.homeworkSummary.count ? `${dashboard.homeworkSummary.count}권` : '없음',
      summaryLabel: dashboard.homeworkSummary.count
        ? `숙제 교재 ${dashboard.homeworkSummary.count}권 등록`
        : '등록된 숙제 교재 없음',
    }),
    unreadBoardCount: dashboard.unreadBoardCount,
  });
}
/* STUDENT_APP_DASHBOARD_END */

/* STUDENT_APP_HOMEWORK_START */
const STUDENT_HOMEWORK_CANONICAL_STATUSES = Object.freeze(['assigned', 'completed', 'cancelled']);
const STUDENT_HOMEWORK_STATUS_LABELS = Object.freeze({
  assigned: '진행 중',
  overdue: '기한 지남',
  completed: '완료',
  cancelled: '취소',
});

function studentHomeworkOpaqueId(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text || text.length > 128 || text === '.' || text === '..') return '';
  return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(text) ? text : '';
}

function studentHomeworkOpaqueCursor(value) {
  if (value == null) return null;
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text || text.length > 256 || text === '.' || text === '..') return '';
  return /^[A-Za-z0-9][A-Za-z0-9._~-]*$/.test(text) ? text : '';
}

function studentHomeworkSafeText(value, maxLength) {
  if (typeof value !== 'string') return null;
  return value.replace(/[\u0000-\u001f\u007f]/g, ' ').trim().replace(/\s+/g, ' ').slice(0, maxLength);
}

function studentHomeworkIsoTimestamp(value) {
  if (value == null) return null;
  if (typeof value !== 'string' || value.length > 40) return '';
  const text = value.trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):?(\d{2})?(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(text);
  if (!match) return '';
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] || 0);
  const date = new Date(Date.UTC(year, month - 1, day));
  const calendarValid = date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
  if (!calendarValid || hour > 23 || minute > 59 || second > 59 || !Number.isFinite(Date.parse(text))) return '';
  return text;
}

function normalizeStudentHomeworkPayload(value, nowValue = Date.now()) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || !Array.isArray(value.items)) return null;
  if (!Object.hasOwn(value, 'nextCursor')) return null;
  if (value.items.length > 50) return null;
  const now = Number(nowValue);
  if (!Number.isFinite(now)) return null;
  const nextCursor = studentHomeworkOpaqueCursor(value.nextCursor);
  if (value.nextCursor != null && !nextCursor) return null;
  const ids = new Set();
  const items = [];
  for (const source of value.items) {
    if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
    if (!['id', 'title', 'book', 'scope', 'assignedAt', 'dueAt', 'status', 'completedAt', 'legacy', 'notificationEligible']
      .every(key => Object.hasOwn(source, key))) return null;
    const id = studentHomeworkOpaqueId(source.id);
    const title = studentHomeworkSafeText(source.title, 160);
    const book = studentHomeworkSafeText(source.book, 120);
    const scope = studentHomeworkSafeText(source.scope, 240);
    const assignedAt = studentHomeworkIsoTimestamp(source.assignedAt);
    const dueAt = studentHomeworkIsoTimestamp(source.dueAt);
    const completedAt = studentHomeworkIsoTimestamp(source.completedAt);
    const status = String(source.status || '');
    const rawNotificationIds = source.notificationEventIds == null ? [] : source.notificationEventIds;
    if (!Array.isArray(rawNotificationIds) || rawNotificationIds.length > 2) return null;
    const notificationEventIds = rawNotificationIds.map(studentHomeworkOpaqueId);
    if (!id || ids.has(id) || !title || book == null || scope == null || !assignedAt
      || !STUDENT_HOMEWORK_CANONICAL_STATUSES.includes(status)
      || typeof source.legacy !== 'boolean' || typeof source.notificationEligible !== 'boolean'
      || notificationEventIds.some((eventId, index) => !/^evt_[A-Za-z0-9_-]{32}$/.test(eventId)
        || notificationEventIds.indexOf(eventId) !== index)
      || (source.dueAt != null && !dueAt) || (source.completedAt != null && !completedAt)
      || (status === 'completed' ? !completedAt : completedAt != null)
      || (source.notificationEligible && (source.legacy || status !== 'assigned' || !dueAt || Date.parse(dueAt) <= now))) return null;
    ids.add(id);
    items.push(Object.freeze({
      id,
      title,
      book,
      scope,
      assignedAt,
      dueAt,
      status,
      completedAt,
      legacy: source.legacy,
      notificationEligible: source.notificationEligible,
      notificationEventIds: Object.freeze(notificationEventIds),
    }));
  }
  items.sort((left, right) => {
    const leftDue = left.dueAt == null ? Number.POSITIVE_INFINITY : Date.parse(left.dueAt);
    const rightDue = right.dueAt == null ? Number.POSITIVE_INFINITY : Date.parse(right.dueAt);
    if (leftDue !== rightDue) return leftDue - rightDue;
    const assignedOrder = Date.parse(left.assignedAt) - Date.parse(right.assignedAt);
    return assignedOrder || left.id.localeCompare(right.id);
  });
  return Object.freeze({ items: Object.freeze(items), nextCursor });
}

function studentHomeworkDeepLink(search) {
  const params = new URLSearchParams(String(search || ''));
  const views = params.getAll('view');
  const items = params.getAll('item');
  if (params.has('announcement') || views.length !== 1 || items.length !== 1 || views[0] !== 'homework') return '';
  return studentHomeworkOpaqueId(items[0]);
}

function studentHomeworkTimeLabel(value) {
  const timestamp = studentHomeworkIsoTimestamp(value);
  if (!timestamp) return '';
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(timestamp);
  return match ? `${Number(match[2])}월 ${Number(match[3])}일 ${match[4]}:${match[5]}` : '';
}

function studentHomeworkViewModel(item, nowValue = Date.now()) {
  const now = Number(nowValue);
  if (!item || !Number.isFinite(now)) return null;
  const status = item.status === 'assigned' && item.dueAt && Date.parse(item.dueAt) <= now
    ? 'overdue'
    : item.status;
  return Object.freeze({
    id: item.id,
    title: item.title,
    bookLabel: item.book || '교재 미지정',
    scopeLabel: item.scope || '범위 미지정',
    assignedLabel: `지정 ${studentHomeworkTimeLabel(item.assignedAt)}`,
    dueLabel: item.dueAt ? `기한 ${studentHomeworkTimeLabel(item.dueAt)}` : '기한 미지정 · 알림 제외',
    status,
    statusLabel: STUDENT_HOMEWORK_STATUS_LABELS[status],
    notificationEligible: item.notificationEligible,
    notificationEventIds: item.notificationEventIds,
  });
}
/* STUDENT_APP_HOMEWORK_END */

/* STUDENT_APP_NOTIFICATION_PREFERENCES_START */
const STUDENT_NOTIFICATION_CATEGORIES = Object.freeze(['schedule', 'homework', 'progress', 'announcement']);

function normalizeStudentNotificationPreferencesPayload(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.ok !== true) return null;
  const revision = value.revision;
  const preferences = value.preferences;
  if (typeof revision !== 'number' || !Number.isSafeInteger(revision) || revision < 0
    || !preferences || typeof preferences !== 'object' || Array.isArray(preferences)) return null;
  const keys = Object.keys(preferences).sort();
  const expected = [...STUDENT_NOTIFICATION_CATEGORIES].sort();
  if (keys.length !== expected.length || keys.some((key, index) => key !== expected[index])) return null;
  if (STUDENT_NOTIFICATION_CATEGORIES.some(key => typeof preferences[key] !== 'boolean')) return null;
  return Object.freeze({
    revision,
    preferences: Object.freeze(Object.fromEntries(
      STUDENT_NOTIFICATION_CATEGORIES.map(key => [key, preferences[key]])
    )),
  });
}

function studentAppHomeDeepLink(search) {
  const params = new URLSearchParams(String(search || ''));
  return !params.has('announcement')
    && params.getAll('view').length === 1
    && params.getAll('view')[0] === 'home'
    && params.getAll('item').length === 0;
}
/* STUDENT_APP_NOTIFICATION_PREFERENCES_END */

const STUDENT_APP_PUBLIC_MODE = studentAppIsPublicMode(location);
const STUDENT_APP_PAGE_SID = resolveStudentId();
document.body?.classList.toggle('student-app-mobile-surface', STUDENT_APP_PUBLIC_MODE);
const STUDENT_APP_PUBLIC_SESSION = STUDENT_APP_PUBLIC_MODE ? createStudentAppSessionAdapter() : null;
let studentFocusController = null;

async function studentAppRequest(url, init = {}) {
  if (!STUDENT_APP_PUBLIC_MODE) return fetch(url, init);
  return STUDENT_APP_PUBLIC_SESSION.request(url, init);
}

function initStudentFocusController() {
  if (!STUDENT_APP_PUBLIC_MODE || studentFocusController || !window.StudentFocus?.createController) return;
  studentFocusController = window.StudentFocus.createController({
    request: studentAppRequest,
    onSessionFailure: handleStudentAppSessionFailure,
    makeSessionError: (code, status) => new StudentAppSessionError(code, status),
  });
  void studentFocusController.load();
}

function handleStudentAppSessionFailure(error) {
  if (!STUDENT_APP_PUBLIC_MODE || !(error instanceof StudentAppSessionError)) return false;
  const activeSid = studentAppStrictSid(error?.activeSid);
  if (error?.code === 'sid_rotated' && activeSid) {
    location.replace(`/student/${encodeURIComponent(activeSid)}`);
    return true;
  }

  document.querySelector('.student-shell')?.setAttribute('hidden', '');
  let panel = document.getElementById('studentSessionRecovery');
  if (!panel) {
    panel = document.createElement('main');
    panel.id = 'studentSessionRecovery';
    panel.className = 'student-session-recovery';
    panel.setAttribute('role', 'alert');
    panel.setAttribute('aria-labelledby', 'studentSessionRecoveryTitle');
    const title = document.createElement('h1');
    title.id = 'studentSessionRecoveryTitle';
    title.textContent = '학생 앱 연결을 확인해 주세요';
    const message = document.createElement('p');
    message.textContent = error?.status === 401
      ? '로그인이 만료되었습니다. 다시 로그인해 주세요.'
      : '학생 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = '다시 시도';
    retry.addEventListener('click', () => location.reload());
    const login = document.createElement('button');
    login.type = 'button';
    login.textContent = '로그인 화면';
    login.addEventListener('click', () => location.assign('/app'));
    panel.append(title, message, retry, login);
    document.body.prepend(panel);
    retry.focus();
  }
  return true;
}

function resolveStudentId() {
  const lastSeg = decodeURIComponent(location.pathname.split("/").pop() || "");
  // /student/123 처럼 마지막 세그먼트가 숫자면 그걸 sid로 사용
  if (/^\d+$/.test(lastSeg)) return lastSeg;

  // 그 외(정적 html 등)는 ?sid=123 에서 읽어옴
  const q = new URLSearchParams(location.search);
  const fromQuery = q.get("sid");
  if (fromQuery) return decodeURIComponent(fromQuery);

  // 그래도 없으면 일단 마지막 세그먼트 그대로 (완전 비상용)
  return lastSeg || "";
}

// 공개 앱에서는 이 값이 권한 근거가 아니다. 서버 세션 확인 뒤에만 active SID를 채운다.
window.__STU_SID__ = STUDENT_APP_PUBLIC_MODE ? '' : STUDENT_APP_PAGE_SID;
try {
  if (!STUDENT_APP_PUBLIC_MODE && window.__STU_SID__) localStorage.setItem("studentSid", String(window.__STU_SID__));
} catch {}

const STUDENT_SEARCH_HELP_TEXT = '초성/영타 검색 · 띄어쓰기=AND';
const STUDENT_HANGUL_INITIALS = [
  '\u3131', '\u3132', '\u3134', '\u3137', '\u3138', '\u3139', '\u3141', '\u3142', '\u3143',
  '\u3145', '\u3146', '\u3147', '\u3148', '\u3149', '\u314a', '\u314b', '\u314c', '\u314d', '\u314e',
];
const STUDENT_HANGUL_MEDIALS = [
  '\u314f', '\u3150', '\u3151', '\u3152', '\u3153', '\u3154', '\u3155',
  '\u3156', '\u3157', '\u3158', '\u3159', '\u315a', '\u315b', '\u315c',
  '\u315d', '\u315e', '\u315f', '\u3160', '\u3161', '\u3162', '\u3163',
];
const STUDENT_HANGUL_FINALS = [
  '', '\u3131', '\u3132', '\u3133', '\u3134', '\u3135', '\u3136',
  '\u3137', '\u3139', '\u313a', '\u313b', '\u313c', '\u313d', '\u313e',
  '\u313f', '\u3140', '\u3141', '\u3142', '\u3144', '\u3145', '\u3146',
  '\u3147', '\u3148', '\u314a', '\u314b', '\u314c', '\u314d', '\u314e',
];
const STUDENT_DUBEOLSIK_COMPAT_BY_KEY = new Map([
  ['r', '\u3131'], ['R', '\u3132'], ['s', '\u3134'], ['e', '\u3137'], ['E', '\u3138'],
  ['f', '\u3139'], ['a', '\u3141'], ['q', '\u3142'], ['Q', '\u3143'], ['t', '\u3145'],
  ['T', '\u3146'], ['d', '\u3147'], ['w', '\u3148'], ['W', '\u3149'], ['c', '\u314a'],
  ['z', '\u314b'], ['x', '\u314c'], ['v', '\u314d'], ['g', '\u314e'],
  ['k', '\u314f'], ['o', '\u3150'], ['i', '\u3151'], ['O', '\u3152'], ['j', '\u3153'],
  ['p', '\u3154'], ['u', '\u3155'], ['P', '\u3156'], ['h', '\u3157'], ['y', '\u315b'],
  ['n', '\u315c'], ['b', '\u3160'], ['m', '\u3161'], ['l', '\u3163'],
]);
const STUDENT_COMPOUND_INITIALS = new Map([
  ['\u3133', '\u3131\u3145'],
  ['\u3135', '\u3134\u3148'],
  ['\u3136', '\u3134\u314e'],
  ['\u313a', '\u3139\u3131'],
  ['\u313b', '\u3139\u3141'],
  ['\u313c', '\u3139\u3142'],
  ['\u313d', '\u3139\u3145'],
  ['\u313e', '\u3139\u314c'],
  ['\u313f', '\u3139\u314d'],
  ['\u3140', '\u3139\u314e'],
  ['\u3144', '\u3142\u3145'],
]);

const STUDENT_COMPOUND_VOWEL_BY_PAIR = new Map([
  ['\u3157\u314f', '\u3158'], ['\u3157\u3150', '\u3159'], ['\u3157\u3163', '\u315a'],
  ['\u315c\u3153', '\u315d'], ['\u315c\u3154', '\u315e'], ['\u315c\u3163', '\u315f'],
  ['\u3161\u3163', '\u3162'],
]);
const STUDENT_COMPOUND_FINAL_BY_PAIR = new Map(
  Array.from(STUDENT_COMPOUND_INITIALS, ([compound, expanded]) => [expanded, compound])
);
const STUDENT_INITIAL_INDEX = new Map(STUDENT_HANGUL_INITIALS.map((ch, index) => [ch, index]));
const STUDENT_MEDIAL_INDEX = new Map(STUDENT_HANGUL_MEDIALS.map((ch, index) => [ch, index]));
const STUDENT_FINAL_INDEX = new Map(STUDENT_HANGUL_FINALS.map((ch, index) => [ch, index]));

function studentSearchPlaceholder(label = '검색') {
  return window.SearchUtils?.searchPlaceholder?.(label) || `${label} (${STUDENT_SEARCH_HELP_TEXT})`;
}

function studentNormalizeSearch(value) {
  if (window.SearchUtils?.normalizeSearch) return window.SearchUtils.normalizeSearch(value);
  return Array.from(String(value || ''))
    .map(ch => STUDENT_COMPOUND_INITIALS.get(ch) || ch)
    .join('')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, '');
}

function studentSearchTerms(value) {
  if (window.SearchUtils?.searchTerms) return window.SearchUtils.searchTerms(value);
  return String(value || '').trim().split(/\s+/).map(studentNormalizeSearch).filter(Boolean);
}

function studentIsCompatVowel(ch) {
  return STUDENT_MEDIAL_INDEX.has(ch);
}

function studentDubeolsikKeysToCompatJamo(value) {
  return Array.from(String(value || ''))
    .map(ch => STUDENT_DUBEOLSIK_COMPAT_BY_KEY.get(ch) || ch)
    .join('');
}

function studentComposeCompatJamo(value) {
  const chars = Array.from(String(value || ''));
  let out = '';

  for (let i = 0; i < chars.length;) {
    const initialIndex = STUDENT_INITIAL_INDEX.get(chars[i]);
    if (initialIndex == null || !studentIsCompatVowel(chars[i + 1])) {
      out += chars[i] || '';
      i += 1;
      continue;
    }

    let medial = chars[i + 1];
    let consumed = 2;
    const compoundVowel = STUDENT_COMPOUND_VOWEL_BY_PAIR.get(`${medial}${chars[i + 2] || ''}`);
    if (compoundVowel) {
      medial = compoundVowel;
      consumed = 3;
    }

    const medialIndex = STUDENT_MEDIAL_INDEX.get(medial);
    let finalIndex = 0;
    const finalOne = chars[i + consumed];
    if (STUDENT_FINAL_INDEX.has(finalOne)) {
      const finalTwo = chars[i + consumed + 1];
      const afterFinalTwo = chars[i + consumed + 2];
      const compoundFinal = STUDENT_COMPOUND_FINAL_BY_PAIR.get(`${finalOne}${finalTwo || ''}`);

      if (studentIsCompatVowel(finalTwo)) {
        finalIndex = 0;
      } else if (compoundFinal && !studentIsCompatVowel(afterFinalTwo)) {
        finalIndex = STUDENT_FINAL_INDEX.get(compoundFinal) || 0;
        consumed += 2;
      } else {
        finalIndex = STUDENT_FINAL_INDEX.get(finalOne) || 0;
        consumed += 1;
      }
    }

    out += String.fromCharCode(0xac00 + ((initialIndex * 21 + medialIndex) * 28) + finalIndex);
    i += consumed;
  }

  return out;
}

function studentSearchTermVariants(value) {
  const raw = String(value || '');
  const variants = [studentNormalizeSearch(raw)];
  if (/^[A-Za-z]+$/.test(raw) && raw.length >= 2) {
    const jamo = studentDubeolsikKeysToCompatJamo(raw);
    const lowerJamo = studentDubeolsikKeysToCompatJamo(raw.toLowerCase());
    variants.push(
      studentNormalizeSearch(jamo),
      studentNormalizeSearch(studentComposeCompatJamo(jamo)),
      studentNormalizeSearch(lowerJamo),
      studentNormalizeSearch(studentComposeCompatJamo(lowerJamo)),
    );
  }
  return Array.from(new Set(variants.filter(Boolean)));
}

function studentSearchTermVariantGroups(value) {
  return String(value || '')
    .trim()
    .split(/\s+/)
    .map(studentSearchTermVariants)
    .filter(group => group.length);
}

function studentHangulInitials(value) {
  return Array.from(String(value || '')).map(ch => {
    const code = ch.charCodeAt(0);
    if (code < 0xac00 || code > 0xd7a3) return ch;
    return STUDENT_HANGUL_INITIALS[Math.floor((code - 0xac00) / 588)] || ch;
  }).join('');
}

function studentSearchKeyForText(value) {
  if (window.SearchUtils?.searchKeyForText) return window.SearchUtils.searchKeyForText(value);
  const raw = String(value || '');
  return studentNormalizeSearch([raw, studentHangulInitials(raw)].join(' '));
}

function studentMatchesSearchKey(key, query) {
  if (window.SearchUtils?.matchesSearchKey) return window.SearchUtils.matchesSearchKey(key, query);
  const termGroups = studentSearchTermVariantGroups(query);
  if (!termGroups.length) return true;
  const hay = String(key || '');
  return termGroups.every(group => group.some(term => hay.includes(term)));
}


// VG Controller는 bootstrap이 학원망 접근을 허용한 뒤에만 동적으로 불러온다.

window.todayLocalKey = function () {
  const now = new Date();
  const tz = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - tz).toISOString().slice(0, 10);
};

(() => {
  /* ───────────── 공통 util ───────────── */
  const $ = id => document.getElementById(id);
  const CT = { "Content-Type": "application/json" };
  const LS_TOKEN_ACTIVE = "studentToken";
  const LS_TOKEN_MASTER = "studentTokenMaster";
  let sid = STUDENT_APP_PUBLIC_MODE ? '' : (window.__STU_SID__ || decodeURIComponent(location.pathname.split("/").pop()));
  let currentMid = null;

  function todayLocalKey() {
    const now = new Date();
    const tz = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - tz).toISOString().slice(0, 10);
  }

  function studentDataDateKey() {
    return todayLocalKey();
  }

  // (표시 전용) 파일명에서 UUID/긴 타임스탬프 접두 제거
  function cleanDisplayName(name) {
    const base = String(name || "").split("/").pop();
    const s1 = base.replace(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}[\s_-]*/i, "");
    const s2 = s1.replace(/^[0-9]{13,17}[\s_-]*/, "");
    const s3 = s2.replace(/^[0-9a-z]{20,}[\s_-]*/i, "");
    return s3 || base;
  }

  // 전역 캐시
  let vidsCache = [];        // /api/videos
  let reviewVideosCache = []; // server-authorized previous-video membership for this page session
  const reviewSelection = new Set(); // chooser-only checked MIDs waiting for local registration
  let registeredReviewMids = []; // ordered, SID/date-scoped local playlist selections
  const REVIEW_PLAYLIST_STORAGE_PREFIX = 'student:review-playlist';
  let updatesCache = {};     // /api/updates
  let stuCache = null;       // 내 학생 객체 (stu)
  let absentByDateCache = {}; // { "YYYY-MM-DD": [sid,...] }
  let logsCache = {};         // /api/logs 전체
  let assignedTestsCache = [];
  let homeworkBooksCache = [];
  let studentDashboardCache = null;
  let canonicalHomeworkState = null;
  let canonicalHomeworkLoading = false;
  const canonicalHomeworkElements = new Map();
  let notificationPreferencesState = null;
  let notificationPreferencesLoading = false;
  let studentHomeDeepLinkHandled = !studentAppHomeDeepLink(location.search);
  let courseBlocked = false;
  let courseBlockMessage = "오늘은 지정된 수업일이 아닙니다. 일정이 다르면 학원에 문의해 주세요.";
  let courseVideosCompleted = false;
  let academyAccessAllowed = !STUDENT_APP_PUBLIC_MODE;
  let academyOnlyMessage = "영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다.";
  let academyOnlyInitialNoticeShown = false;

  let reviewVideosMalformed = false;
  let ghostStudent = false;
  let announcementPendingCount = null;
  const COURSE_VIDEOS_COMPLETED_MESSAGE = "오늘 영상 진도를 모두 마쳤습니다. 추가 영상이 필요하면 학원에 문의해 주세요.";
  window.__ASSIGNED_TESTS__ = [];
  window.__STUDENT_ACCESS__ = {
    academyAccessAllowed,
    outsideAcademyBlocked: !academyAccessAllowed,
    message: academyOnlyMessage,
  };

  function publishStudentAccess() {
    window.__STUDENT_ACCESS__ = {
      academyAccessAllowed,
      outsideAcademyBlocked: !academyAccessAllowed,
        message: academyOnlyMessage,
      showNotice: () => showAcademyOnlyNotice(),
    };
  }

  function showAcademyOnlyNotice(options = {}) {
    if (options.once && academyOnlyInitialNoticeShown) return;
    if (options.once) academyOnlyInitialNoticeShown = true;
    alert(academyOnlyMessage);
  }

  function setPlayerEmptyState(message = '') {
    const frame = $('player');
    const card = frame?.closest?.('.player-card');
    const box = $('playerBox');
    if (frame) {
      frame.src = "";
      frame.hidden = true;
      frame.title = message || '재생할 영상이 없습니다.';
    }
    if (card) card.hidden = true;
    if (box) box.classList.add('is-player-empty');
  }

  function setPlayerReadyState() {
    const frame = $('player');
    const card = frame?.closest?.('.player-card');
    const box = $('playerBox');
    if (frame) {
      frame.hidden = false;
      frame.title = '';
    }
    if (card) card.hidden = false;
    if (box) box.classList.remove('is-player-empty');
  }

  /* ───────────── 진행도 저장/복구(로컬) ───────────── */
  const LSKeys = {
    lastMid: (sid) => `stu:${sid}:last_video_mid`,
    prog: (sid, mid) => `stu:${sid}:watch:${mid}`, // {last, dur, completed, updatedAt}
  };
  const WATCH_DONE_RATIO = 0.90;
  const WATCH_UPDATED_AT_MIN_MS = 1_000_000_000_000;

  function normalizeWatchUpdatedAt(value, fallback = 0) {
    const parsed = Number(value);
    const updatedAt = Number.isFinite(parsed) ? Math.floor(parsed) : 0;
    return updatedAt >= WATCH_UPDATED_AT_MIN_MS ? updatedAt : fallback;
  }

  function getProgress(mid) {
    try {
      const raw = localStorage.getItem(LSKeys.prog(sid, mid));
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }

  function normalizeProgressRecord(entry) {
    if (!entry || typeof entry !== 'object') entry = {};

    const last = Math.max(0, Number(entry.last) || 0);
    const dur = Math.max(0, Number(entry.dur) || 0);
    const updatedAt = normalizeWatchUpdatedAt(entry.updatedAt);
    const completed = !!entry.completed || (dur > 0 && last >= Math.max(dur - 1, Math.floor(dur * WATCH_DONE_RATIO)));

    return {
      last: Math.floor(last),
      dur: Math.floor(dur),
      completed,
      updatedAt,
    };
  }

  function mergeProgressRecord(base, patch) {
    const a = normalizeProgressRecord(base);
    const b = normalizeProgressRecord(patch);

    const last = Math.max(a.last, b.last);
    const dur = Math.max(a.dur, b.dur);
    const completed = a.completed || b.completed || (dur > 0 && last >= Math.max(dur - 1, Math.floor(dur * WATCH_DONE_RATIO)));

    return {
      last,
      dur,
      completed,
      updatedAt: Math.max(a.updatedAt, b.updatedAt, Date.now()),
    };
  }

  function storeProgress(mid, next) {
    try { localStorage.setItem(LSKeys.prog(sid, mid), JSON.stringify(next)); } catch { }
  }

  function setProgress(mid, patch, options = {}) {
    const cur = getProgress(mid) || {};
    const next = mergeProgressRecord(cur, patch);
    storeProgress(mid, next);
    try { updateListCompletionBadges(); } catch { }

    if (options.sync !== false) enqueueSync(mid);
    return next;
  }
  function setLastMid(mid) {
    try { localStorage.setItem(LSKeys.lastMid(sid), mid); } catch { }
  }
  function getLastMid() {
    try { return localStorage.getItem(LSKeys.lastMid(sid)) || null; } catch { return null; }
  }

  function fmtPct(n) {
    if (!Number.isFinite(n)) return '';
    return `${Math.max(0, Math.min(100, Math.round(n)))}%`;
  }

  /* ───────────── 서버 동기화 (/api/watch) ───────────── */
  const SYNC_DEBOUNCE_MS = 1500;      // 너무 자주 쏘지 않도록 디바운스
  const _syncTimers = new Map();      // mid -> timeout id
  const _lastSent = new Map();        // mid -> { last, dur, completed, updatedAt } (보낸 스냅샷)

  function mergeServerWatchIntoLocal(watchMap) {
    if (!watchMap || typeof watchMap !== 'object') return;

    Object.entries(watchMap).forEach(([mid, rec]) => {
      const key = String(mid || '').trim();
      if (!key) return;
      const next = mergeProgressRecord(getProgress(key), rec);
      storeProgress(key, next);
      _lastSent.set(key, {
        last: next.last | 0,
        dur: next.dur | 0,
        completed: !!next.completed,
        updatedAt: normalizeWatchUpdatedAt(next.updatedAt),
      });
    });

    try { updateListCompletionBadges(); } catch { }
  }

  function clearStaleCompletedWatchForServerPlaylist(videos, updates, authoritative) {
    if (!authoritative) return;
    const assigned = new Set(getAssignedVideos(updates, studentDataDateKey(), sid).map(String));
    (videos || []).forEach(video => {
      const mid = String(video?.mid ?? video?.id ?? '').trim();
      if (!mid || !assigned.has(mid) || !normalizeProgressRecord(getProgress(mid)).completed) return;
      if (video?.todayAutoAssignmentStatus === 'done') return;
      try { localStorage.removeItem(LSKeys.prog(sid, mid)); } catch { }
      _lastSent.delete(mid);
    });
  }

  function enqueueSync(mid) {
    if (_syncTimers.has(mid)) clearTimeout(_syncTimers.get(mid));
    const t = setTimeout(() => doSync(mid), SYNC_DEBOUNCE_MS);
    _syncTimers.set(mid, t);
  }

  async function doSync(mid, options = {}) {
    if (!academyAccessAllowed) return;
    _syncTimers.delete(mid);
    const prog = getProgress(mid);
    if (!prog) return;
    const now = Date.now();
    const snap = {
      last: prog.last | 0,
      dur: prog.dur | 0,
      completed: !!prog.completed,
      updatedAt: normalizeWatchUpdatedAt(prog.updatedAt, now)
    };

    const prev = _lastSent.get(mid);
    if (prev && prev.last === snap.last && prev.dur === snap.dur && prev.completed === snap.completed) return;

    const canonicalSid = String(stuCache?.id || sid || '').trim();
    const payload = {
      date: todayLocalKey(),
      sid: canonicalSid,
      mid,
      last: snap.last,
      dur: snap.dur,
      completed: snap.completed,
      updatedAt: snap.updatedAt
    };

    try {
      const res1 = await studentAppRequest('/api/watch', {
        method: 'POST', headers: CT, body: JSON.stringify(payload), keepalive: !!options.keepalive
      });
      if (res1.ok) _lastSent.set(mid, snap);
    } catch (e) {
      console.warn('[watch sync] failed', e);
    }
  }

  async function flushSyncQueue(options = {}) {
    const mids = new Set(_syncTimers.keys());
    if (currentMid) mids.add(currentMid);
    if (!mids.size) return;

    mids.forEach(mid => {
      try { clearTimeout(_syncTimers.get(mid)); } catch { }
      _syncTimers.delete(mid);
    });

    await Promise.allSettled([...mids].map(mid => doSync(mid, options)));
  }

  function flushCurrentWatch() {
    flushSyncQueue({ keepalive: true });
  }

  window.addEventListener('beforeunload', flushCurrentWatch);
  window.addEventListener('pagehide', flushCurrentWatch, { capture: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushCurrentWatch();
  });

  /* ───────────── 설정 패널 & 다크모드 ───────────── */
  const setBtn = $('setBtn');
  const setPanel = $('setPanel');
  const setPanelClose = $('setPanelClose');
  const darkTgl = $('darkToggle');
  const studentAppSettings = $('studentAppSettings');
  const studentAppCurriculum = $('studentAppCurriculum');
  const studentAppNotificationStatus = $('studentAppNotificationStatus');
  const studentNotificationPreferences = $('studentNotificationPreferences');
  const studentNotificationPreferencesStatus = $('studentNotificationPreferencesStatus');
  const studentNotificationPreferencesRetry = $('studentNotificationPreferencesRetry');
  const studentNotificationPreferenceInputs = Object.freeze(Object.fromEntries(
    STUDENT_NOTIFICATION_CATEGORIES.map(category => [
      category,
      document.querySelector(`[data-student-notification-category="${category}"]`),
    ])
  ));
  const studentAppLogout = $('studentAppLogout');
  const studentLocalFeedbackSettings = $('studentLocalFeedbackSettings');
  const studentLocalLoginSettings = $('studentLocalLoginSettings');

  if (STUDENT_APP_PUBLIC_MODE) {
    if (studentAppSettings) studentAppSettings.hidden = false;
    if (studentLocalFeedbackSettings) studentLocalFeedbackSettings.hidden = true;
    if (studentLocalLoginSettings) studentLocalLoginSettings.hidden = true;
  }

  function publicNotificationStatus() {
    if (!('serviceWorker' in navigator) || typeof window.PushManager === 'undefined' || typeof window.Notification === 'undefined') {
      return '이 기기는 학습 알림을 지원하지 않아 학생 앱의 24시간 기본 방식을 사용합니다.';
    }
    if (Notification.permission === 'granted') return '학습 알림이 허용되어 있습니다.';
    if (Notification.permission === 'denied') return '학습 알림이 차단되어 있습니다. 브라우저 설정에서 허용할 수 있습니다.';
    return '학습 알림 권한을 아직 선택하지 않았습니다. 학생 앱에서 설정할 수 있습니다.';
  }

  function setNotificationPreferencesBusy(busy) {
    if (!studentNotificationPreferences) return;
    studentNotificationPreferences.setAttribute('aria-busy', busy ? 'true' : 'false');
    STUDENT_NOTIFICATION_CATEGORIES.forEach(category => {
      const input = studentNotificationPreferenceInputs[category];
      if (input) input.disabled = busy || !notificationPreferencesState;
    });
    if (studentNotificationPreferencesRetry) studentNotificationPreferencesRetry.disabled = busy;
  }

  function renderNotificationPreferences(payload, message = '원하는 알림을 변경할 수 있습니다.') {
    if (!studentNotificationPreferences || !payload) return;
    notificationPreferencesState = payload;
    STUDENT_NOTIFICATION_CATEGORIES.forEach(category => {
      const input = studentNotificationPreferenceInputs[category];
      if (input) input.checked = payload.preferences[category];
    });
    studentNotificationPreferences.hidden = false;
    if (studentNotificationPreferencesStatus) studentNotificationPreferencesStatus.textContent = message;
    if (studentNotificationPreferencesRetry) studentNotificationPreferencesRetry.hidden = true;
  }

  function hideNotificationPreferences() {
    notificationPreferencesState = null;
    if (studentNotificationPreferences) studentNotificationPreferences.hidden = true;
    if (studentNotificationPreferencesStatus) studentNotificationPreferencesStatus.textContent = '';
    if (studentNotificationPreferencesRetry) studentNotificationPreferencesRetry.hidden = true;
  }

  function showNotificationPreferencesError() {
    if (!studentNotificationPreferences) return;
    studentNotificationPreferences.hidden = false;
    if (studentNotificationPreferencesStatus) {
      studentNotificationPreferencesStatus.textContent = '알림 설정을 확인하지 못했습니다. 연결 후 다시 시도해 주세요.';
    }
    if (studentNotificationPreferencesRetry) studentNotificationPreferencesRetry.hidden = false;
  }

  function handleNotificationPreferencesSessionFailure(error) {
    if (!(error instanceof StudentAppSessionError)) return false;
    if (![401, 403].includes(error.status) && error.code !== 'sid_rotated') return false;
    return handleStudentAppSessionFailure(error);
  }

  async function loadNotificationPreferences({ message = '' } = {}) {
    if (!STUDENT_APP_PUBLIC_MODE || !studentNotificationPreferences || notificationPreferencesLoading) return null;
    notificationPreferencesLoading = true;
    studentNotificationPreferences.hidden = false;
    if (studentNotificationPreferencesStatus) studentNotificationPreferencesStatus.textContent = '알림 설정을 불러오는 중입니다.';
    if (studentNotificationPreferencesRetry) studentNotificationPreferencesRetry.hidden = true;
    setNotificationPreferencesBusy(true);
    try {
      const response = await studentAppRequest('/api/mobile/push/preferences', { cache: 'no-store' });
      if (response.status === 404) {
        hideNotificationPreferences();
        return null;
      }
      if (response.status === 401 || response.status === 403) {
        throw new StudentAppSessionError('notification_preferences_session_failed', response.status);
      }
      if (!response.ok) throw new Error('notification_preferences_unavailable');
      const raw = await response.json().catch(() => null);
      const payload = normalizeStudentNotificationPreferencesPayload(raw);
      if (!payload) throw new Error('notification_preferences_malformed');
      renderNotificationPreferences(payload, message || '원하는 알림을 변경할 수 있습니다.');
      return payload;
    } catch (error) {
      if (!handleNotificationPreferencesSessionFailure(error)) showNotificationPreferencesError();
      return null;
    } finally {
      notificationPreferencesLoading = false;
      setNotificationPreferencesBusy(false);
    }
  }

  async function saveNotificationPreferences() {
    if (!STUDENT_APP_PUBLIC_MODE || !notificationPreferencesState || notificationPreferencesLoading) return;
    const previous = notificationPreferencesState;
    const preferences = Object.fromEntries(STUDENT_NOTIFICATION_CATEGORIES.map(category => [
      category,
      studentNotificationPreferenceInputs[category]?.checked === true,
    ]));
    let conflict = false;
    notificationPreferencesLoading = true;
    if (studentNotificationPreferencesStatus) studentNotificationPreferencesStatus.textContent = '알림 설정을 저장하는 중입니다.';
    if (studentNotificationPreferencesRetry) studentNotificationPreferencesRetry.hidden = true;
    setNotificationPreferencesBusy(true);
    try {
      const response = await studentAppRequest('/api/mobile/push/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preferences, expectedRevision: previous.revision }),
      });
      if (response.status === 404) {
        hideNotificationPreferences();
        return;
      }
      if (response.status === 401 || response.status === 403) {
        throw new StudentAppSessionError('notification_preferences_session_failed', response.status);
      }
      if (response.status === 409) {
        conflict = true;
        return;
      }
      if (!response.ok) throw new Error('notification_preferences_unavailable');
      const raw = await response.json().catch(() => null);
      const payload = normalizeStudentNotificationPreferencesPayload(raw);
      if (!payload) throw new Error('notification_preferences_malformed');
      renderNotificationPreferences(payload, '알림 설정을 저장했습니다.');
    } catch (error) {
      if (!handleNotificationPreferencesSessionFailure(error)) {
        renderNotificationPreferences(previous);
        showNotificationPreferencesError();
      }
    } finally {
      notificationPreferencesLoading = false;
      setNotificationPreferencesBusy(false);
      if (conflict) {
        renderNotificationPreferences(previous, '다른 화면의 변경을 확인하는 중입니다.');
        void loadNotificationPreferences({ message: '다른 화면의 변경을 반영했습니다.' });
      }
    }
  }

  async function preparePublicStudentSettings() {
    if (!STUDENT_APP_PUBLIC_MODE || !studentAppSettings) return;
    studentAppSettings.hidden = false;
    if (studentLocalFeedbackSettings) studentLocalFeedbackSettings.hidden = true;
    if (studentLocalLoginSettings) studentLocalLoginSettings.hidden = true;
    const session = await STUDENT_APP_PUBLIC_SESSION.refreshSession();
    const state = STUDENT_APP_PUBLIC_SESSION.sessionState();
    if (!state || session.activeSid !== state.activeSid) return;
    if (studentAppNotificationStatus) studentAppNotificationStatus.textContent = publicNotificationStatus();
    if (studentAppCurriculum) {
      studentAppCurriculum.replaceChildren(...state.curris.map(curriculum => {
        const option = document.createElement('option');
        option.value = curriculum.sid;
        option.textContent = curriculum.cur || curriculum.sid;
        option.selected = curriculum.sid === state.activeSid;
        return option;
      }));
      studentAppCurriculum.disabled = state.curris.length < 2;
    }
    await loadNotificationPreferences();
  }

  STUDENT_NOTIFICATION_CATEGORIES.forEach(category => {
    studentNotificationPreferenceInputs[category]?.addEventListener('change', () => {
      void saveNotificationPreferences();
    });
  });

  studentNotificationPreferencesRetry?.addEventListener('click', () => {
    void loadNotificationPreferences({ message: '알림 설정을 다시 불러왔습니다.' });
  });

  studentAppCurriculum?.addEventListener('change', async () => {
    if (!STUDENT_APP_PUBLIC_MODE) return;
    const targetSid = studentAppStrictSid(studentAppCurriculum.value);
    if (!targetSid || targetSid === STUDENT_APP_PUBLIC_SESSION.activeSid()) return;
    studentAppCurriculum.disabled = true;
    try {
      const response = await STUDENT_APP_PUBLIC_SESSION.request('/api/mobile/auth/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sid: targetSid }),
      });
      if (!response.ok) throw new StudentAppSessionError('switch_failed', response.status);
      await STUDENT_APP_PUBLIC_SESSION.refreshSession({ force: true });
      // Session rotation invalidates the previous Push binding. Re-enter the
      // app shell so the existing browser subscription is bound to the new SID.
      location.assign('/app');
    } catch (error) {
      handleStudentAppSessionFailure(error);
      if (studentAppNotificationStatus) studentAppNotificationStatus.textContent = '커리큘럼을 바꾸지 못했습니다. 다시 시도해 주세요.';
      studentAppCurriculum.disabled = false;
    }
  });

  studentAppLogout?.addEventListener('click', async () => {
    if (!STUDENT_APP_PUBLIC_MODE) return;
    studentAppLogout.disabled = true;
    try {
      const response = await STUDENT_APP_PUBLIC_SESSION.request('/api/mobile/auth/logout', { method: 'POST', body: '{}' });
      if (!response.ok) throw new StudentAppSessionError('logout_failed', response.status);
      location.replace('/app');
    } catch (error) {
      handleStudentAppSessionFailure(error);
      if (studentAppNotificationStatus) studentAppNotificationStatus.textContent = '로그아웃에 실패했습니다. 다시 시도해 주세요.';
      studentAppLogout.disabled = false;
    }
  });

  function setSettingsPanelOpen(open) {
    setPanel?.classList.toggle('open', open);
    setPanel?.setAttribute('aria-hidden', open ? 'false' : 'true');
    setBtn?.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  setBtn?.addEventListener('click', e => {
    e.stopPropagation();
    setSettingsPanelOpen(!setPanel?.classList.contains('open'));
  });
  setPanelClose?.addEventListener('click', () => {
    setSettingsPanelOpen(false);
    setBtn?.focus();
  });
  document.addEventListener('click', e => {
    if (!setPanel || !setBtn) return;
    if (!setPanel.contains(e.target) && !setBtn.contains(e.target)) {
      setSettingsPanelOpen(false);
    }
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || !setPanel?.classList.contains('open')) return;
    setSettingsPanelOpen(false);
    setBtn?.focus();
  });

  if (localStorage.theme === "dark") {
    document.body.classList.add("dark");
    if (darkTgl) darkTgl.checked = true;
  }
  if (darkTgl) {
    darkTgl.onchange = () => {
      document.body.classList.toggle("dark", darkTgl.checked);
      localStorage.theme = darkTgl.checked ? 'dark' : 'light';
    };
  }

  function essayBandOf(level) {
    if (level === '상' || level === '중상') return '상';
    if (level === '중') return '중';
    return '하';
  }

  /* ───────────── 헤더 시계 ───────────── */
  const clk = $('clock');
  if (clk) {
    const fmt2 = n => String(n).padStart(2, '0');
    const tick = () => {
      const d = new Date(), w = '일월화수목금토'[d.getDay()];
      const date = `${d.getFullYear()}.${fmt2(d.getMonth() + 1)}.${fmt2(d.getDate())}`;
      const time = `${fmt2(d.getHours())}<span class="colon">:</span>${fmt2(d.getMinutes())}`;
      clk.innerHTML = `
        <span class="date">${date}</span>
        <span class="day">(${w})</span>
        <span class="time">${time}</span>
      `;
    };
    tick();
    setInterval(tick, 60 * 1000);
  }

  /* ───────────── 데이터 로드 ───────────── */
  function bootstrapInitialData(b, watchRaw) {
    const academyAllowed = studentAppAcademyAccessFromBootstrap(STUDENT_APP_PUBLIC_MODE, b);
    return [
      Array.isArray(b.students) ? b.students : (b.student ? [b.student] : []),
      Array.isArray(b.videos) ? b.videos : [],
      b.updates || {},
      b.materials || {},
      b.assigns || {},
      b.absent || {},
      b.logs || {},
      watchRaw,
      {
        courseBlocked: b.courseBlocked === true,
        selfStudy: b.selfStudy === true,
        blockMessage: b.blockMessage || '',
        courseVideosCompleted: b.courseVideosCompleted === true,
        academyAccessAllowed: academyAllowed,
        academyOnlyMessage: b.academyOnlyMessage || b.academyOnlyNotice || b.restrictedMessage || '',
        assignedTests: Array.isArray(b.assignedTests) ? b.assignedTests : [],
        homeworkBooks: Array.isArray(b.homeworkBooks) ? b.homeworkBooks : [],
        reviewVideos: b.reviewVideos,
        reviewVideosMalformed: !Array.isArray(b.reviewVideos),
        ghostStudent: b.ghostStudent === true,
        redirectSid: b.redirectSid || b.recoveredSid || '',
        recoveryReason: b.recoveryReason || '',

        dashboard: b.dashboard && typeof b.dashboard === 'object' ? b.dashboard : null,
        videoProjectionAuthoritative: true,
      },
    ];
  }

  async function loadInitialData() {
    const today = studentDataDateKey();
    if (STUDENT_APP_PUBLIC_MODE) {
      const loaded = await loadPublicStudentBootstrap({
        adapter: STUDENT_APP_PUBLIC_SESSION,
        pageSid: STUDENT_APP_PAGE_SID,
        date: today,
      });
      sid = loaded.activeSid;
      window.__STU_SID__ = loaded.activeSid;
      return bootstrapInitialData(loaded.bootstrap, loaded.watch);
    }

    const watchReq = fetch(`/api/watch/latest?sid=${encodeURIComponent(sid)}`)
      .then(r => r.json()).catch(() => ({}));

    const q = new URLSearchParams({ sid: String(sid), date: today }).toString();
    const res = await fetch(`/api/student/bootstrap?${q}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`bootstrap ${res.status}`);
    const b = await res.json();
    return bootstrapInitialData(b, await watchReq);
  }

  loadInitialData().then(init).catch(err => {
    if (handleStudentAppSessionFailure(err)) return;
    alert("데이터 로드 실패\n" + err);
  });

  // /api/absent 응답에서 by_date 부분만 뽑기
  function normalizeAbsentByDate(payload) {
    if (!payload || typeof payload !== 'object') return {};
    if (payload.by_date && typeof payload.by_date === 'object') return payload.by_date;
    if (payload.byDate && typeof payload.byDate === 'object') return payload.byDate;
    return payload;
  }

  /* ───────────── [추가] updates에서 배정 읽기 공통 함수 ───────────── */
  function getAssignedVideos(updatesObj, day, sidVal) {
    const dayMap = (updatesObj && updatesObj[day]) ? updatesObj[day] : {};
    const k1 = String(sidVal);
    const k2 = Number.isFinite(+sidVal) ? String(+sidVal) : null;

    const raw = dayMap[k1] ?? (k2 != null ? dayMap[k2] : undefined);

    if (Array.isArray(raw)) return raw.map(String);
    if (raw && Array.isArray(raw.videos)) return raw.videos.map(String);
    return [];
  }

  function isTodayAutoVideoAssignment(updatesObj, day, sidVal) {
    if (day !== todayLocalKey()) return false;
    const dayMap = (updatesObj && updatesObj[day]) ? updatesObj[day] : {};
    const k1 = String(sidVal);
    const k2 = Number.isFinite(+sidVal) ? String(+sidVal) : null;
    const raw = dayMap[k1] ?? (k2 != null ? dayMap[k2] : undefined);
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return false;
    if (raw.manual === true || raw.manualVideoAssign === true) return false;
    return String(raw.source || '').trim().toLowerCase() === 'auto';
  }

  function videoChapterRank(v) {
    const raw = String(v?.chapter ?? '').trim();
    const n = Number.parseFloat(raw.replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
  }

  function isSupplementVideo(v) {
    if (v?.isExtraAssignment === true) return true;
    if (v?.isExtraAssignment === false) return false;

    const stuCur = String(stuCache?.curriculum || '').trim();
    const stuSub = String(stuCache?.subCurriculum || '').trim();
    const vidCur = String(v?.curriculum || '').trim();
    const vidSub = String(v?.subCurriculum || '').trim();

    if (stuCur && vidCur && stuCur !== vidCur) return true;
    if (stuSub && vidSub && stuSub !== vidSub) return true;
    return false;
  }

  function assignedVideoTitle(v) {
    const prefix = isSupplementVideo(v) ? '(보충) ' : '';
    const chapter = String(v?.chapter ?? '').trim();
    const title = String(v?.title || v?.name || '').trim();
    return `${prefix}${chapter ? `${chapter}. ` : ''}${title || String(v?.mid || '')}`.trim();
  }

  // Bootstrap is the only source of previous-video membership. Do not enrich
  // or infer this projection from the catalog, progress, watch, or storage.
  function normalizeReviewVideos(items) {
    const seen = new Set();
    const normalized = [];
    if (!Array.isArray(items)) return normalized;
    items.forEach(item => {
      if (!item || typeof item !== 'object') return;
      const mid = String(item.mid ?? '').trim();
      const reviewStatus = item.reviewStatus;
      if (!mid || reviewStatus !== 'done' || seen.has(mid)) return;
      seen.add(mid);
      normalized.push({ ...item, mid, reviewStatus });
    });
    normalized.sort((a, b) => {
      const chapterDiff = videoChapterRank(a) - videoChapterRank(b);
      if (chapterDiff) return chapterDiff;
      return String(a.mid).localeCompare(String(b.mid), 'ko', { numeric: true });
    });
    return normalized;
  }

  function reviewPlaylistStorageKey() {
    return `${REVIEW_PLAYLIST_STORAGE_PREFIX}:${String(sid)}:${studentDataDateKey()}`;
  }

  function normalizeStoredReviewMids(value) {
    const seen = new Set();
    const normalized = [];
    if (!Array.isArray(value)) return normalized;
    value.forEach(raw => {
      const mid = String(raw ?? '').trim();
      if (mid && !seen.has(mid)) {
        seen.add(mid);
        normalized.push(mid);
      }
    });
    return normalized;
  }

  function saveRegisteredReviewMids() {
    try {
      localStorage.setItem(reviewPlaylistStorageKey(), JSON.stringify(registeredReviewMids));
    } catch (_) {
      // Browser storage is a convenience only; the server-authorized chooser remains usable.
    }
  }

  function loadRegisteredReviewMids() {
    let parsed = [];
    try {
      const raw = localStorage.getItem(reviewPlaylistStorageKey());
      if (raw) parsed = JSON.parse(raw);
    } catch (_) {
      parsed = [];
    }
    const allowed = new Set(reviewVideosCache.map(item => item.mid));
    const normalized = normalizeStoredReviewMids(parsed);
    const next = normalized.filter(mid => allowed.has(mid));
    const changed = JSON.stringify(next) !== JSON.stringify(normalized);
    registeredReviewMids = next;
    reviewSelection.clear();
    if (changed) saveRegisteredReviewMids();
  }

  function registeredReviewVideos() {
    if (!academyAccessAllowed || reviewSurfaceBlocked()) return [];
    const byMid = new Map(reviewVideosCache.map(item => [item.mid, item]));
    return registeredReviewMids
      .map(mid => byMid.get(mid))
      .filter(item => item && item.playbackRestricted !== true);
  }

  function reviewVideoTitle(item) {
    const chapter = String(item?.chapter ?? '').trim();
    const title = String(item?.title || item?.name || '').trim();
    return `${chapter ? `${chapter}. ` : ''}${title || String(item?.mid || '')}`.trim();
  }

  function isAbsentOnStudentDate() {
    const today = studentDataDateKey();
    const absent = absentByDateCache?.[today] || [];
    return Array.isArray(absent) && absent.map(String).includes(String(sid));
  }

  function isArchivedOnStudentDate() {
    const today = studentDataDateKey();
    const logsToday = (logsCache || {})[today] || {};
    const entry = logsToday[String(sid)] || logsToday[sid] || {};
    return entry.archived === true || entry.archived === 'true';
  }

  function reviewSurfaceBlocked() {
    return !stuCache || courseBlocked || ghostStudent || reviewVideosMalformed
      || isAbsentOnStudentDate() || isArchivedOnStudentDate();
  }

  function setActiveVideo(mid) {
    const key = String(mid || '');
    $('vidList')?.querySelectorAll('li[data-mid]').forEach(item => {
      const active = item.dataset.mid === key;
      item.classList.toggle('active', active);
      const action = item.querySelector('.video-row-action');
      if (active) action?.setAttribute('aria-current', 'true');
      else action?.removeAttribute('aria-current');
    });
    const reviewItems = [
      ...($('previousVidList')?.querySelectorAll('button[data-mid]') || []),
      ...($('previousVidList')?.querySelectorAll('label[data-mid]') || []),
    ];
    reviewItems.forEach(item => {
      const active = item.dataset.mid === key;
      item.classList.toggle('is-active', active);
      item.setAttribute('aria-current', String(active));
    });
  }

  function syncReviewRegisterControl(register) {
    if (!register) return;
    const eligible = new Set(reviewVideosCache.map(item => item.mid));
    const registered = new Set(registeredReviewMids);
    const selected = [...reviewSelection].filter(mid => eligible.has(mid) && !registered.has(mid));
    register.disabled = reviewSurfaceBlocked() || !academyAccessAllowed || selected.length === 0;
  }

  function registerReviewVideos() {
    if (reviewSurfaceBlocked() || !academyAccessAllowed) return false;
    const eligible = new Set(reviewVideosCache.map(item => item.mid));
    const registered = new Set(registeredReviewMids);
    const selected = [...reviewSelection].filter(mid => eligible.has(mid) && !registered.has(mid));
    if (!selected.length) return false;

    registeredReviewMids = normalizeStoredReviewMids([...registeredReviewMids, ...selected]);
    reviewSelection.clear();
    saveRegisteredReviewMids();
    void renderAssignedList({ autoPlay: false });
    renderPreviousVideos();
    return true;
  }

  function cancelRegisteredReviewVideo(rawMid) {
    const mid = String(rawMid ?? '').trim();
    if (!mid || reviewSurfaceBlocked() || !academyAccessAllowed || !registeredReviewMids.includes(mid)) {
      return false;
    }

    registeredReviewMids = registeredReviewMids.filter(registeredMid => registeredMid !== mid);
    reviewSelection.delete(mid);
    saveRegisteredReviewMids();
    void renderAssignedList({ autoPlay: false });
    renderPreviousVideos();
    return true;
  }

  function renderPreviousVideos() {
    const wrapper = $('previousVideos');
    const toggle = $('previousVideosToggle');
    const panel = $('previousVideosPanel');
    const summary = $('previousVideosSummary');
    const register = $('previousVideosRegister');
    const list = $('previousVidList');
    if (!wrapper || !toggle || !panel || !summary || !list) return;

    if (!toggle.dataset.reviewBound) {
      toggle.addEventListener('click', () => {
        if (toggle.disabled) return;
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        panel.hidden = expanded;
      });
      toggle.dataset.reviewBound = '1';
    }
    if (register && !register.dataset.reviewBound) {
      register.addEventListener('click', () => { void registerReviewVideos(); });
      register.dataset.reviewBound = '1';
    }

    wrapper.hidden = false;
    wrapper.classList.remove('is-empty', 'is-disabled', 'is-restricted');
    toggle.textContent = '영상 복습';
    toggle.disabled = true;
    toggle.setAttribute('aria-expanded', 'false');
    panel.hidden = true;
    summary.textContent = '';
    summary.classList.remove('is-empty');
    list.textContent = '';
    if (register) {
      register.hidden = false;
      register.disabled = true;
    }

    if (reviewSurfaceBlocked()) {
      wrapper.hidden = true;
      wrapper.classList.add('is-disabled');
      return;
    }

    if (!reviewVideosCache.length) {
      wrapper.classList.add('is-empty');
      summary.classList.add('is-empty');
      summary.textContent = '복습 가능한 영상이 없습니다';
      panel.hidden = false;
      if (register) register.hidden = true;
      return;
    }

    for (const mid of reviewSelection) {
      if (!reviewVideosCache.some(item => item.mid === mid) || registeredReviewMids.includes(mid)) {
        reviewSelection.delete(mid);
      }
    }
    toggle.disabled = false;
    toggle.textContent = `영상 복습 (${reviewVideosCache.length})`;
    summary.textContent = '등록할 영상은 체크하고, 등록 취소는 체크를 해제하세요';
    if (register) {
      register.hidden = false;
      syncReviewRegisterControl(register);
    }
    reviewVideosCache.forEach(item => {
      const title = document.createElement('span');
      const restricted = item.playbackRestricted === true || !academyAccessAllowed;
      const registered = registeredReviewMids.includes(item.mid);

      // Outside the academy, keep the existing title-only restriction row. It
      // cannot register or play; clicking it only explains the access rule.
      if (!academyAccessAllowed) {
        if (register) register.hidden = true;
        const row = document.createElement('li');
        const playButton = document.createElement('button');
        row.className = 'previous-video-play-row';
        playButton.type = 'button';
        playButton.className = 'previous-video-play';
        playButton.dataset.mid = item.mid;
        playButton.dataset.playbackRestricted = 'true';
        playButton.disabled = true;
        title.className = 'previous-video-title';
        title.textContent = reviewVideoTitle(item);
        playButton.setAttribute('aria-label', `${title.textContent} (학원에서만 재생 가능)`);
        playButton.addEventListener('click', () => showAcademyOnlyNotice());
        playButton.appendChild(title);
        row.dataset.mid = item.mid;
        row.appendChild(playButton);
        list.appendChild(row);
        return;
      }

      const row = document.createElement('label');
      row.className = 'previous-video-row';
      const active = currentMid === item.mid;
      title.className = 'previous-video-title';
      title.textContent = reviewVideoTitle(item);
      row.dataset.mid = item.mid;
      row.classList.toggle('is-active', active);
      row.setAttribute('aria-current', String(active));
      row.classList.toggle('is-restricted', restricted);
      if (restricted && !registered) row.setAttribute('aria-disabled', 'true');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.dataset.mid = item.mid;
      checkbox.checked = registered || reviewSelection.has(item.mid);
      checkbox.disabled = restricted && !registered;
      checkbox.setAttribute('aria-label', registered ? `${title.textContent} 등록 취소` : title.textContent);
      if (registered) checkbox.setAttribute('data-registered', 'true');
      checkbox.addEventListener('change', () => {
        if (registered) {
          if (checkbox.checked) return;
          cancelRegisteredReviewVideo(item.mid);
          return;
        }
        if (checkbox.checked) reviewSelection.add(item.mid);
        else reviewSelection.delete(item.mid);
        syncReviewRegisterControl(register);
      });
      row.append(checkbox, title);
      list.appendChild(row);
    });
    syncReviewRegisterControl(register);
  }

  function normalizeAssignedTestStatus(status) {
    const s = String(status || '').trim();
    if (s === 'interrupted' || s === 'skip' || s === 'done' || s === 'assigned') return s;
    return s ? 'assigned' : '';
  }

  function assignedTestStatusLabel(status) {
    const s = normalizeAssignedTestStatus(status);
    if (s === 'done') return '완료';
    if (s === 'interrupted') return '배부';
    if (s === 'skip') return '제외';
    return s ? '배정' : '';
  }

  function assignedTestDifficultyLabel(item) {
    const category = `${item?.categoryKey || ''} ${item?.categoryLabel || ''} ${item?.category || ''} ${item?.label || ''}`;
    const difficulty = String(item?.difficulty || '').trim();
    if (category.includes('ILSAN') || category.includes('일산')) {
      if (difficulty.includes('그래프')) return '그래프 포함';
      if (difficulty === '상') return '중상';
    }
    return difficulty;
  }

  function normalizedTestDifficultyForCategory(categoryKey, difficulty) {
    const text = String(difficulty || '').trim();
    if (String(categoryKey || '') === 'ILSAN_PAST') {
      if (text.includes('그래프')) return '그래프 포함';
      if (text === '상' || text.includes('중상')) return '중상';
      if (text.includes('중')) return '중';
    }
    return text;
  }

  function normalizeAssignedTests(items) {
    const seen = new Set();
    return (Array.isArray(items) ? items : []).map(item => {
      if (!item || typeof item !== 'object') return null;
      const id = String(item.id || item.testId || '').trim();
      const label = String(item.label || '').trim();
      const name = String(item.name || item.testName || label || '').trim();
      if (!id && !label && !name) return null;
      const status = normalizeAssignedTestStatus(item.status) || 'assigned';
      const key = id || label || name;
      if (seen.has(key)) return null;
      seen.add(key);
      return {
        ...item,
        id,
        label,
        name,
        categoryLabel: String(item.categoryLabel || item.category || '').trim(),
        curriculum: String(item.curriculum || '').trim(),
        difficulty: assignedTestDifficultyLabel(item),
        round: String(item.round || '').trim(),
        status,
        statusLabel: item.statusLabel || assignedTestStatusLabel(status),
      };
    }).filter(Boolean);
  }

  function cleanHomeworkBookName(value) {
    const text = String(value || '').trim();
    if (!text || text.includes('\ufffd')) return '';
    const compact = text.replace(/\s+/g, '');
    if (compact.length >= 2 && /^\?+$/.test(compact)) return '';
    return text;
  }

  function normalizeHomeworkBooks(items) {
    const seen = new Set();
    const out = [];
    (Array.isArray(items) ? items : []).forEach(value => {
      const book = cleanHomeworkBookName(value);
      const key = book.replace(/\s+/g, '').toLowerCase();
      if (!book || seen.has(key)) return;
      seen.add(key);
      out.push(book);
    });
    return out;
  }

  function homeworkBooksFromLogs() {
    const today = studentDataDateKey();
    const logsToday = (logsCache || {})[today] || {};
    const entry = logsToday[String(sid)] || logsToday[sid] || {};
    const rows = Array.isArray(entry.homeworkTable) ? entry.homeworkTable : [];
    return normalizeHomeworkBooks(
      rows
        .filter(row => row && typeof row === 'object' && !row._deleted)
        .map(row => row.book)
    );
  }

  function renderHomeworkBooks() {
    const panel = $('studentHomeworkPanel');
    const list = $('studentHomeworkBooks');
    if (!panel || !list) return;

    const books = homeworkBooksCache.length ? homeworkBooksCache : homeworkBooksFromLogs();
    panel.hidden = books.length === 0;
    if (!books.length) return;

    list.textContent = '';
    books.forEach(book => {
      const li = document.createElement('li');
      li.textContent = book;
      list.appendChild(li);
    });
  }

  function restoreLegacyHomeworkFallback() {
    canonicalHomeworkState = null;
    canonicalHomeworkElements.clear();
    const title = $('studentHomeworkTitle');
    const assignments = $('studentHomeworkAssignments');
    const books = $('studentHomeworkBooks');
    const status = $('studentHomeworkStatus');
    const retry = $('studentHomeworkRetry');
    if (title) title.textContent = '오늘 숙제';
    if (assignments) {
      assignments.hidden = true;
      assignments.textContent = '';
    }
    if (books) books.hidden = false;
    if (status) {
      status.hidden = true;
      status.textContent = '';
    }
    if (retry) retry.hidden = true;
    renderHomeworkBooks();
    renderStudentTodayOverview();
  }

  function renderCanonicalHomework(payload) {
    const panel = $('studentHomeworkPanel');
    const title = $('studentHomeworkTitle');
    const assignments = $('studentHomeworkAssignments');
    const books = $('studentHomeworkBooks');
    const status = $('studentHomeworkStatus');
    const retry = $('studentHomeworkRetry');
    if (!panel || !assignments) return;

    canonicalHomeworkElements.clear();
    assignments.textContent = '';
    payload.items.forEach(item => {
      const view = studentHomeworkViewModel(item);
      if (!view) return;
      const card = document.createElement('li');
      card.className = `student-homework-card is-${view.status}`;
      card.tabIndex = -1;

      const heading = document.createElement('div');
      heading.className = 'student-homework-card-heading';
      const itemTitle = document.createElement('h3');
      itemTitle.textContent = view.title;
      const state = document.createElement('strong');
      state.className = 'student-homework-state';
      state.textContent = view.statusLabel;
      heading.append(itemTitle, state);

      const details = document.createElement('p');
      details.className = 'student-homework-details';
      details.textContent = `${view.bookLabel} · ${view.scopeLabel}`;
      const timing = document.createElement('p');
      timing.className = 'student-homework-timing';
      timing.textContent = `${view.assignedLabel} · ${view.dueLabel}`;
      card.append(heading, details, timing);
      assignments.appendChild(card);
      canonicalHomeworkElements.set(view.id, card);
      view.notificationEventIds.forEach(eventId => canonicalHomeworkElements.set(eventId, card));
    });

    if (!payload.items.length) {
      const empty = document.createElement('li');
      empty.className = 'student-homework-empty';
      empty.textContent = '등록된 숙제가 없습니다.';
      assignments.appendChild(empty);
    }
    if (title) title.textContent = '숙제';
    if (books) books.hidden = true;
    if (status) {
      status.hidden = true;
      status.textContent = '';
    }
    if (retry) retry.hidden = true;
    assignments.hidden = false;
    panel.hidden = false;
  }

  function showCanonicalHomeworkError() {
    const panel = $('studentHomeworkPanel');
    const status = $('studentHomeworkStatus');
    const retry = $('studentHomeworkRetry');
    if (status) {
      status.textContent = '숙제 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
      status.hidden = false;
    }
    if (retry) retry.hidden = false;
    if (panel) panel.hidden = false;
  }

  function focusCanonicalHomeworkDeepLink() {
    const requestedId = studentHomeworkDeepLink(location.search);
    if (!requestedId) return;
    const card = canonicalHomeworkElements.get(requestedId);
    if (!card) return;
    card.classList.add('student-homework-deep-link');
    card.setAttribute('aria-current', 'true');
    requestAnimationFrame(() => {
      card.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
      card.focus?.({ preventScroll: true });
    });
  }

  async function loadCanonicalStudentHomework() {
    if (!STUDENT_APP_PUBLIC_MODE || canonicalHomeworkLoading) return;
    canonicalHomeworkLoading = true;
    const retry = $('studentHomeworkRetry');
    if (retry) retry.disabled = true;
    try {
      const response = await studentAppRequest('/api/mobile/student/homework?status=open', { cache: 'no-store' });
      if (response.status === 404) {
        restoreLegacyHomeworkFallback();
        return;
      }
      if (response.status === 401 || response.status === 403) {
        throw new StudentAppSessionError('homework_session_failed', response.status);
      }
      if (!response.ok) {
        showCanonicalHomeworkError();
        return;
      }
      const raw = await response.json().catch(() => null);
      const payload = normalizeStudentHomeworkPayload(raw);
      if (!payload) {
        showCanonicalHomeworkError();
        return;
      }
      canonicalHomeworkState = Object.freeze({ state: 'ready', payload });
      renderCanonicalHomework(payload);
      renderStudentTodayOverview();
      focusCanonicalHomeworkDeepLink();
    } catch (error) {
      if (!handleStudentAppSessionFailure(error)) showCanonicalHomeworkError();
    } finally {
      canonicalHomeworkLoading = false;
      if (retry) retry.disabled = false;
    }
  }

  function assignedTestAnswerUrl(test) {
    return String(test?.answerUrl || test?.answer_url || test?.solutionUrl || test?.solution_url || '').trim();
  }

  function isAssignedTestAnswerRestricted(test, answerUrl) {
    return test?.answerRestricted === true || (!academyAccessAllowed && !!answerUrl);
  }

  function canOpenAssignedTestAnswer(answerUrl) {
    return academyAccessAllowed && !!answerUrl;
  }

  function shouldOpenAssignedTestAnswerInSameTab() {
    const width = Number(window.innerWidth || 0);
    const viewportLooksMobileOrTablet = width > 0 && width <= 1024;
    const nav = window.navigator || {};
    const touchPoints = Number(nav.maxTouchPoints || nav.msMaxTouchPoints || 0);
    let coarsePointer = false;
    if (typeof window.matchMedia === 'function') {
      try {
        coarsePointer = window.matchMedia('(pointer: coarse)').matches;
      } catch (_) {
        coarsePointer = false;
      }
    }
    return viewportLooksMobileOrTablet || coarsePointer || touchPoints > 0;
  }

  function createAssignedTestActionElement(canOpenAnswerUrl, answerUrl) {
    const btn = document.createElement(canOpenAnswerUrl ? 'a' : 'button');
    if (canOpenAnswerUrl) {
      btn.href = answerUrl;
      if (!shouldOpenAssignedTestAnswerInSameTab()) {
        btn.target = '_blank';
        btn.rel = 'noopener noreferrer';
      }
    } else {
      btn.type = 'button';
    }
    return btn;
  }

  function renderAssignedTests() {
    const panel = $('assignedTestsPanel');
    const list = $('assignedTestList');
    const hasTests = assignedTestsCache.length > 0;

    if (panel) panel.hidden = !hasTests;
    if (!hasTests || !list) return;

    list.textContent = '';
    assignedTestsCache.forEach(test => {
      const li = document.createElement('li');
      const answerUrl = assignedTestAnswerUrl(test);
      const answerRestricted = isAssignedTestAnswerRestricted(test, answerUrl);
      const canOpenAnswerUrl = canOpenAssignedTestAnswer(answerUrl);
      const btn = createAssignedTestActionElement(canOpenAnswerUrl, answerUrl);
      btn.className = 'assigned-test-btn';
      btn.dataset.testId = test.id || '';
      btn.dataset.status = normalizeAssignedTestStatus(test.status) || 'assigned';
      if (answerUrl) btn.dataset.answerUrl = answerUrl;
      if (answerRestricted) btn.dataset.answerRestricted = '1';

      const main = document.createElement('span');
      main.className = 'assigned-test-main';

      const name = document.createElement('span');
      name.className = 'assigned-test-name';
      name.textContent = test.name || test.label || '배정 테스트';

      const meta = document.createElement('span');
      meta.className = 'assigned-test-meta';
      meta.textContent = [
        test.categoryLabel,
        test.curriculum,
        test.difficulty,
        test.round ? (String(test.round).includes('회') ? test.round : `${test.round}회차`) : '',
      ].filter(Boolean).join(' · ');

      const status = document.createElement('span');
      status.className = 'assigned-test-status';
      status.textContent = test.statusLabel || assignedTestStatusLabel(test.status);

      main.append(name, meta);
      btn.append(main, status);
      if (!canOpenAnswerUrl) {
        if (answerRestricted) {
          btn.addEventListener('click', showAcademyOnlyNotice);
        } else {
          btn.disabled = true;
          btn.setAttribute('aria-disabled', 'true');
        }
      }

      li.appendChild(btn);
      list.appendChild(li);
    });
  }
  async function recoverStudentSid(stuArr, missingSid) {
    if (STUDENT_APP_PUBLIC_MODE) return '';
    const byId = new Map((Array.isArray(stuArr) ? stuArr : []).map(s => [String(s?.id || ""), s]));
    const missing = String(missingSid || "").trim();

    try {
      const storedSid = String(localStorage.getItem("studentSid") || "").trim();
      if (storedSid && storedSid !== missing && byId.has(storedSid)) {
        return storedSid;
      }
    } catch {}

    let token = "";
    try {
      token = String(
        localStorage.getItem(LS_TOKEN_MASTER)
        || localStorage.getItem(LS_TOKEN_ACTIVE)
        || ""
      ).trim();
    } catch {}
    if (!token) return "";

    try {
      const res = await fetch("/api/auth/me", {
        cache: "no-store",
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) return "";

      const candidates = [
        String(data?.sid || "").trim(),
        ...((Array.isArray(data?.curris) ? data.curris : []).map(x => String(x?.sid || "").trim()))
      ].filter(Boolean);

      return candidates.find(x => x !== missing && byId.has(x)) || "";
    } catch {
      return "";
    }
  }

  function renderStudentDashboardDetails(view) {
    const details = $('studentDashboardDetails');
    if (!details) return;
    details.hidden = !view;

    const progressBar = $('studentCurriculumProgress');
    if (!view) {
      if (progressBar) {
        progressBar.hidden = true;
        progressBar.value = 0;
        progressBar.textContent = '';
        progressBar.removeAttribute('aria-valuetext');
      }
      return;
    }

    const progressCourse = $('studentCurriculumProgressCourse');
    const progressPercent = $('studentCurriculumProgressPercent');
    const progressMeta = $('studentCurriculumProgressMeta');
    if (progressCourse) progressCourse.textContent = view.progress.courseLabel;
    if (progressPercent) progressPercent.textContent = view.progress.percentLabel;
    if (progressMeta) progressMeta.textContent = view.progress.countLabel;
    if (progressBar) {
      progressBar.hidden = !view.progress.available;
      progressBar.value = view.progress.percent ?? 0;
      progressBar.textContent = view.progress.available ? view.progress.percentLabel : '';
      if (view.progress.available) progressBar.setAttribute('aria-valuetext', view.progress.percentLabel);
      else progressBar.removeAttribute('aria-valuetext');
    }

    const scheduleKind = $('studentNextScheduleKind');
    const scheduleStatus = $('studentNextScheduleStatus');
    const scheduleWhen = $('studentNextScheduleWhen');
    const scheduleSlots = $('studentNextScheduleSlots');
    if (scheduleKind) scheduleKind.textContent = view.schedule.kindLabel;
    if (scheduleStatus) {
      scheduleStatus.hidden = !view.schedule.statusLabel;
      scheduleStatus.textContent = view.schedule.statusLabel;
    }
    if (scheduleWhen) scheduleWhen.textContent = view.schedule.whenLabel;
    if (scheduleSlots) {
      scheduleSlots.hidden = !view.schedule.slotsLabel;
      scheduleSlots.textContent = view.schedule.slotsLabel;
    }
  }

  function focusStudentHomeDeepLink() {
    if (studentHomeDeepLinkHandled) return;
    const overview = $('studentTodayOverview');
    if (!overview || overview.hidden) return;
    studentHomeDeepLinkHandled = true;
    overview.tabIndex = -1;
    overview.classList.add('student-app-deep-link-target');
    requestAnimationFrame(() => {
      const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true;
      overview.scrollIntoView?.({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
      overview.focus?.({ preventScroll: true });
    });
  }

  function renderStudentTodayOverview() {
    if (!STUDENT_APP_PUBLIC_MODE) return;
    const overview = $('studentTodayOverview');
    if (!overview) return;

    const dashboardView = studentDashboardViewModel(studentDashboardCache);
    renderStudentDashboardDetails(dashboardView);
    const books = homeworkBooksCache.length ? homeworkBooksCache : homeworkBooksFromLogs();
    const canonicalHomeworkCount = canonicalHomeworkState?.state === 'ready'
      ? canonicalHomeworkState.payload.items.length
      : null;
    const videoRows = Array.from($('vidList')?.querySelectorAll('li[data-mid]') || [])
      .filter(row => row.dataset.reviewRegistered !== 'true');
    const completedVideos = videoRows.filter(row => getProgress(row.dataset.mid)?.completed).length;
    const pendingTests = assignedTestsCache.filter(test => !['done', 'skip'].includes(normalizeAssignedTestStatus(test?.status))).length;
    const unreadCount = dashboardView?.unreadBoardCount ?? announcementPendingCount;

    const homeworkCount = $('studentTodayHomeworkCount');
    const videoCount = $('studentTodayVideoCount');
    const testCount = $('studentTodayTestCount');
    const noticeCount = $('studentTodayNoticeCount');
    const summary = $('studentTodaySummary');
    if (homeworkCount) {
      homeworkCount.textContent = canonicalHomeworkCount == null
        ? (dashboardView?.homework.countLabel || `${books.length}권`)
        : `${canonicalHomeworkCount}개`;
    }
    if (videoCount) videoCount.textContent = videoRows.length ? `${completedVideos}/${videoRows.length} 완료` : '없음';
    if (testCount) testCount.textContent = pendingTests ? `${pendingTests}개` : '없음';
    if (noticeCount) noticeCount.textContent = unreadCount == null ? '확인 중' : unreadCount ? `${unreadCount}개` : '없음';
    if (summary) {
      const nextSummary = [
        canonicalHomeworkCount == null
          ? (dashboardView?.homework.summaryLabel
            || (books.length ? `숙제 교재 ${books.length}권 등록` : '등록된 숙제 교재 없음'))
          : (canonicalHomeworkCount ? `숙제 ${canonicalHomeworkCount}개 확인 필요` : '등록된 숙제 없음'),
        videoRows.length ? `영상 ${completedVideos}/${videoRows.length} 완료` : '오늘 영상 없음',
        pendingTests ? `테스트 ${pendingTests}개 확인 필요` : '확인할 테스트 없음',
      ].join(' · ');
      if (summary.textContent !== nextSummary) summary.textContent = nextSummary;
    }

    const linkTargets = {
      homework: $('studentHomeworkPanel'),
      video: $('studentVideoPanel'),
      tests: $('assignedTestsPanel'),
    };
    overview.querySelectorAll('[data-student-summary-link]').forEach(link => {
      const target = linkTargets[link.dataset.studentSummaryLink];
      link.hidden = !target || target.hidden;
    });
    const access = $('studentTodayAccess');
    if (access) {
      access.hidden = academyAccessAllowed;
      access.textContent = academyAccessAllowed ? '' : '영상 재생과 테스트 답지 열람은 학원에서 이용할 수 있습니다.';
    }
    overview.hidden = false;
    focusStudentHomeDeepLink();
  }

  document.addEventListener('student-app:announcement-summary', event => {
    const pending = Number(event?.detail?.pending);
    announcementPendingCount = Number.isFinite(pending) ? Math.max(0, Math.floor(pending)) : null;
    renderStudentTodayOverview();
  });

  document.querySelector('[data-student-notice-shortcut]')?.addEventListener('click', () => {
    $('noticeBtn')?.click();
  });

  $('studentHomeworkRetry')?.addEventListener('click', () => {
    void loadCanonicalStudentHomework();
  });

  /* ───────────── main ───────────── */
  async function init([stuArr, vids, upd, mats, assigns, absentRaw, logsRaw, watchRaw, bootstrapMeta]) {
    const redirectSid = String(bootstrapMeta?.redirectSid || '').trim();
    if (redirectSid && redirectSid !== String(sid)) {
      if (STUDENT_APP_PUBLIC_MODE) {
        handleStudentAppSessionFailure(new StudentAppSessionError('session_not_ready', 409));
        return;
      }
      try { localStorage.setItem("studentSid", redirectSid); } catch {}
      location.replace(`/student/${encodeURIComponent(redirectSid)}`);
      return;
    }

    let stu = stuArr.find(s => String(s.id) === String(sid));
    if (!stu) {
      const recoveredSid = await recoverStudentSid(stuArr, sid);
      if (recoveredSid) {
        try { localStorage.setItem("studentSid", recoveredSid); } catch {}
        location.replace(`/student/${encodeURIComponent(recoveredSid)}`);
        return;
      }
      if (STUDENT_APP_PUBLIC_MODE) {
        handleStudentAppSessionFailure(new StudentAppSessionError('student_not_found', 404));
        return;
      }
      alert("학생 정보가 없습니다");
      return;
    }

    // 캐시에 보관
    stuCache = stu;
    vidsCache = vids || [];
    updatesCache = upd || {};
    absentByDateCache = normalizeAbsentByDate(absentRaw);
    logsCache = logsRaw || {};
    assignedTestsCache = normalizeAssignedTests(bootstrapMeta?.assignedTests);
    homeworkBooksCache = normalizeHomeworkBooks(bootstrapMeta?.homeworkBooks);
    studentDashboardCache = bootstrapMeta?.dashboard || null;
    reviewVideosCache = normalizeReviewVideos(bootstrapMeta?.reviewVideos);
    reviewVideosMalformed = bootstrapMeta?.reviewVideosMalformed === true;
    loadRegisteredReviewMids();
    ghostStudent = bootstrapMeta?.ghostStudent === true;
    window.__ASSIGNED_TESTS__ = assignedTestsCache;
    courseBlocked = bootstrapMeta?.courseBlocked === true;
    courseBlockMessage = bootstrapMeta?.blockMessage || courseBlockMessage;
    courseVideosCompleted = bootstrapMeta?.courseVideosCompleted === true;
    academyAccessAllowed = studentAppAcademyAccessFromBootstrap(STUDENT_APP_PUBLIC_MODE, bootstrapMeta);
    academyOnlyMessage = bootstrapMeta?.academyOnlyMessage || academyOnlyMessage;

    publishStudentAccess();
    if (academyAccessAllowed) {
      void loadStudentAppKollusController({
        publicMode: STUDENT_APP_PUBLIC_MODE,
        academyAccessAllowed,
        documentRef: document,
        globalRef: window,
      }).catch(err => console.warn('[KollusBridge] controller load failed:', err));
    }
    mergeServerWatchIntoLocal((watchRaw && typeof watchRaw.watch === 'object') ? watchRaw.watch : {});
    clearStaleCompletedWatchForServerPlaylist(
      vidsCache,
      updatesCache,
      bootstrapMeta?.videoProjectionAuthoritative === true,
    );

    const nameEl = $('stuName');
    if (nameEl) nameEl.textContent = `${stu.name} (${stu.curriculum})`;
    void preparePublicStudentSettings().catch(error => {
      handleStudentAppSessionFailure(error);
      console.warn('[student-app-settings] load failed:', error);
    });
    initStudentFocusController();

    // 재생 목록 최초 렌더
    renderHomeworkBooks();
    renderAssignedTests();
    renderAssignedList();
    renderPreviousVideos();
    renderStudentTodayOverview();
    if (STUDENT_APP_PUBLIC_MODE) void loadCanonicalStudentHomework();

    const listBox = $('vidList');
    if (listBox) {
      listBox.onclick = e => {
        const li = e.target.closest('li[data-mid]');
        if (!li) return;
        if (!academyAccessAllowed) {
          showAcademyOnlyNotice();
          return;
        }
        setActiveVideo(li.dataset.mid);
        play(li.dataset.mid);
      };
    }

    /* ─────────────────────────────────────────────────────────────
       [자료 다운로드] — 혼합 배정(숫자 ID + /files/URL) 완전 지원
       (표시 개선) title은 materials.title 우선, 없으면 URL 파일명에서 UUID/타임스탬프 접두 제거
    ──────────────────────────────────────────────────────────────*/

    function getAssignedRaw(assignsObj, sid) {
      if (!assignsObj) return [];
      const k1 = String(sid);
      const k2 = Number.isNaN(Number(sid)) ? null : Number(sid);
      let v = assignsObj[k1];
      if (!v && k2 != null) v = assignsObj[k2];
      if (Array.isArray(v)) return v.slice();
      if (v && Array.isArray(v.materials)) return v.materials.slice();
      return [];
    }

    function indexMaterials(matsMap) {
      const byId = new Map();
      for (const [key, val] of Object.entries(matsMap || {})) {
        const m = { key, ...(val || {}) };
        const candidates = [
          m.id, m.mid, key,
          typeof m.id === 'number' ? String(m.id) : null,
          typeof key === 'string' ? key : null
        ].filter(x => x !== undefined && x !== null);
        for (const c of candidates) byId.set(String(c), m);
      }
      return byId;
    }

    const rawAssigned = getAssignedRaw(assigns, sid);
    const matIndex = indexMaterials(mats);

    function normalizeAssignedItem(item) {
      if (item && typeof item === 'object') {
        const idOrUrl = item.id ?? item.url ?? item.path ?? item;
        return normalizeAssignedItem(idOrUrl);
      }
      const s = String(item || '').trim();
      if (!s) return null;

      if (s.includes('/files/')) {
        const url = s;
        const rawName = decodeURIComponent(url.split('/').pop() || '파일');
        return { title: cleanDisplayName(rawName), url, _from: 'url' };
      }

      const hit = matIndex.get(s);
      if (hit && hit.url) {
        const baseTitle = hit.title || decodeURIComponent(hit.url.split('/').pop() || '파일');
        return { title: cleanDisplayName(baseTitle), url: hit.url, _from: 'id' };
      }

      if (/\.(pdf|png|jpe?g|pptx?|docx?)$/i.test(s)) {
        const url = s.startsWith('/files/') ? s : `/files/${s.replace(/^\/+/, '')}`;
        const rawName = decodeURIComponent(url.split('/').pop() || '파일');
        return { title: cleanDisplayName(rawName), url, _from: 'url' };
      }

      return null;
    }

    const myMats = rawAssigned.map(normalizeAssignedItem).filter(Boolean);

    const matListEl = $('matList');
    if (matListEl) {
      if (!document.getElementById('mat-browser-style')) {
        const st = document.createElement('style');
        st.id = 'mat-browser-style';
        st.textContent = `
          .mbox{display:flex;gap:8px;align-items:center;margin:6px 0 10px}
          .mbox .crumb{display:flex;gap:6px;flex-wrap:wrap;font-size:14px}
          .mbox .crumb a{cursor:pointer;text-decoration:underline}
          .mbox .sep{opacity:.5}
          .mbox .right{margin-left:auto;display:flex;gap:8px;align-items:center}
          .mbox input[type="search"]{height:30px;border:1px solid var(--line);border-radius:8px;background:transparent;padding:0 8px;color:inherit}
          .mbox .toggle{border:1px solid var(--line);border-radius:8px;padding:4px 8px;background:transparent;cursor:pointer}
          .mat-folder,.mat-file{display:flex;align-items:center;gap:6px}
          .muted{opacity:.65}
          .badge-done{margin-left:.5rem; font-size:.9em; color:var(--accent)}
        `;
        document.head.appendChild(st);
      }
      const ctrl = document.createElement('div');
      ctrl.className = 'mbox';
      ctrl.innerHTML = `
        <div class="crumb" id="matCrumb"></div>
        <div class="right">
          <input id="matSearch" type="search" placeholder="${studentSearchPlaceholder('검색')}" />
          <button id="matMode" class="toggle" aria-pressed="false">폴더 보기</button>
        </div>
      `;
      matListEl.insertAdjacentElement('beforebegin', ctrl);
    }

    function pathOfUrl(u) {
      try { return new URL(u, location.origin).pathname; }
      catch { const a = document.createElement('a'); a.href = u; return a.pathname || u; }
    }

    const tree = { name: '/', children: new Map(), files: [] };
    myMats.forEach(m => {
      const p = pathOfUrl(m.url);
      const segs = String(p || '').split('/').filter(Boolean);
      const fname = decodeURIComponent(segs.pop() || m.title || (m.url || '').split('/').pop());
      let cur = tree;
      for (const s of segs) {
        if (!cur.children.has(s)) cur.children.set(s, { name: s, children: new Map(), files: [] });
        cur = cur.children.get(s);
      }
      cur.files.push({ title: m.title || cleanDisplayName(fname), url: m.url, name: fname });
    });

    const state = { curPath: [], mode: 'tree', query: '' };

    function getNode(segs) {
      let cur = tree;
      for (const s of segs) { cur = cur.children.get(s); if (!cur) return null; }
      return cur;
    }
    function setMode(m) {
      state.mode = m;
      const b = $('matMode');
      if (b) { b.textContent = (m === 'tree') ? '폴더 보기' : '전체 보기'; b.setAttribute('aria-pressed', String(m !== 'tree')); }
      renderMat(); pushHistory();
    }
    function setPath(segs) { state.curPath = segs.slice(); renderMat(); pushHistory(); }
    function setQuery(q) { state.query = q.trim(); renderMat(); }

    function pushHistory() {
      const q = new URLSearchParams(location.search);
      q.set('mpath', state.curPath.join('/')); q.set('mmode', state.mode);
      history.replaceState({ mpath: state.curPath, mmode: state.mode }, '', `${location.pathname}?${q.toString()}${location.hash || ''}`);
    }
    (function applyHistory() {
      try {
        const q = new URLSearchParams(location.search);
        const mpath = (q.get('mpath') || '').split('/').filter(Boolean);
        const mmode = q.get('mmode');
        if (mpath.length) state.curPath = mpath;
        if (mmode === 'flat') state.mode = 'flat';
      } catch { }
    })();

    function renderCrumb() {
      const el = $('matCrumb'); if (!el) return;
      el.textContent = '';
      const root = document.createElement('a');
      root.dataset.idx = '-1';
      root.textContent = '/';
      el.appendChild(root);
      state.curPath.forEach((s, i) => {
        const sep = document.createElement('span');
        sep.className = 'sep';
        sep.textContent = '›';
        const link = document.createElement('a');
        link.dataset.idx = String(i);
        link.textContent = s;
        el.append(' ', sep, ' ', link);
      });
      el.querySelectorAll('a[data-idx]').forEach(a => {
        a.addEventListener('click', () => {
          const idx = +a.dataset.idx;
          if (idx < 0) setPath([]); else setPath(state.curPath.slice(0, idx + 1));
        });
      });
    }

    function liFolder(name, count) {
      const li = document.createElement('li');
      li.className = 'mat-folder';
      li.dataset.type = 'dir';
      li.dataset.name = String(name || '');

      const icon = document.createElement('span');
      icon.textContent = '📁';
      const label = document.createElement('span');
      label.textContent = String(name || '');
      const badge = document.createElement('span');
      badge.className = 'muted';
      badge.textContent = `(${count})`;

      li.append(icon, label, badge);
      return li;
    }
    function liFile(title, url, pathHint) {
      const disp = cleanDisplayName(title);
      const li = document.createElement('li');
      li.className = 'mat-file';
      li.dataset.type = 'file';

      const icon = document.createElement('span');
      icon.textContent = '📄';
      const link = document.createElement('a');
      link.href = String(url || '');
      link.download = '';
      link.textContent = disp;

      li.append(icon, link);
      if (pathHint) {
        const hint = document.createElement('span');
        hint.className = 'muted';
        hint.style.marginLeft = '6px';
        hint.textContent = `(${pathHint})`;
        li.append(hint);
      }
      return li;
    }

    function appendEmptyMatMessage(list, text) {
      const li = document.createElement('li');
      li.className = 'muted';
      li.textContent = text;
      list.appendChild(li);
    }

    function renderMat() {
      const list = $('matList'); if (!list) return;
      renderCrumb();
      const q = state.query;

      if (state.mode === 'tree') {
        const cur = getNode(state.curPath) || tree;
        const folders = Array.from(cur.children.values())
          .filter(nd => studentMatchesSearchKey(studentSearchKeyForText(nd.name), q))
          .sort((a, b) => a.name.localeCompare(b.name, 'ko'));
        const files = (cur.files || [])
          .filter(f => studentMatchesSearchKey(studentSearchKeyForText([f.title, f.name].join(' ')), q))
          .sort((a, b) => (a.title || a.name).localeCompare(b.title || b.name, 'ko'));

        list.textContent = '';
        folders.forEach(nd => list.appendChild(liFolder(nd.name, nd.files.length + nd.children.size)));
        files.forEach(f => list.appendChild(liFile(f.title || f.name, f.url)));
        if (!folders.length && !files.length) appendEmptyMatMessage(list, '이 폴더에 항목이 없습니다');

        list.querySelectorAll('li[data-type="dir"]').forEach(li => {
          li.addEventListener('click', () => setPath([...state.curPath, li.getAttribute('data-name')]));
        });
      } else {
        const all = [];
        (function walk(nd, acc = []) {
          for (const f of (nd.files || [])) {
            const t = f.title || f.name;
            if (studentMatchesSearchKey(studentSearchKeyForText([t, acc.join('/')].join(' ')), q)) {
              all.push({ title: t, url: f.url, path: acc.join('/') });
            }
          }
          for (const ch of nd.children.values()) walk(ch, [...acc, ch.name]);
        })(tree, []);
        all.sort((a, b) => a.title.localeCompare(b.title, 'ko'));
        list.textContent = '';
        all.forEach(f => list.appendChild(liFile(f.title, f.url, f.path)));
        if (!all.length) appendEmptyMatMessage(list, '표시할 파일이 없습니다');
      }
    }

    $('matSearch')?.addEventListener('input', e => setQuery(e.target.value || ''));
    $('matMode')?.addEventListener('click', () => setMode(state.mode === 'tree' ? 'flat' : 'tree'));
    setMode(state.mode);
    setPath(state.curPath);

    /* ───────────── 건의사항 제출 ───────────── */
    const fbBtn = document.querySelector('#submitFeedback');
    if (fbBtn) {
      fbBtn.addEventListener('click', () => {
        const text = document.querySelector('#feedbackBox')?.value.trim();
        if (!text) return alert('내용을 입력해주세요!');
        const name = stu?.name || '익명';

        studentAppRequest('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, text })
        }).then(() => {
          alert('소중한 의견 감사합니다!');
          const box = document.querySelector('#feedbackBox');
          if (box) box.value = '';
        }).catch(() => {
          alert('전송에 실패했습니다. 나중에 다시 시도해주세요.');
        });
      });
    }

    window.addEventListener('storage', (e) => {
      if (e.key === 'updPing') location.reload();
    });
  }

  // 오늘 배정 리스트 그리는 함수
  async function renderAssignedList(options = {}) {
    if (!stuCache) return;
    const listBox = $('vidList');
    const frame = $('player');

    const today = studentDataDateKey();
    const keepCompletedAutoAssignment = isTodayAutoVideoAssignment(updatesCache, today, sid);
    const hasServerCompletedAutoAssignment = keepCompletedAutoAssignment
      && (vidsCache || []).some(video => video?.todayAutoAssignmentStatus === 'done');

    if (courseBlocked) {
      if (listBox) {
        listBox.textContent = '';
        const li = document.createElement('li');
        li.style.opacity = '.75';
        li.textContent = courseBlockMessage;
        listBox.appendChild(li);
      }
      setPlayerEmptyState(courseBlockMessage);
      return;
    }

    // ❌ 결석이면 오늘 영상 표시 금지
    {
      const absList = (absentByDateCache?.[today] || []);
      const absSet = new Set(absList.map(String));
      if (absSet.has(String(sid))) {
        if (listBox) listBox.innerHTML = "<li style='opacity:.65'>오늘 결석 처리되었습니다</li>";
        setPlayerEmptyState('오늘 결석 처리되었습니다');
        return;
      }
    }

    // archived 수업도 오늘 자동배정 완료 영상은 개인페이지에 남긴다.
    {
      const logsToday = (logsCache || {})[today] || {};
      const entry = logsToday[String(sid)] || logsToday[sid] || {};
      const archived = entry.archived === true || entry.archived === 'true';
      if (archived && !hasServerCompletedAutoAssignment) {
        if (listBox) listBox.innerHTML = "<li style='opacity:.65'>오늘 영상이 없습니다</li>";
        setPlayerEmptyState('오늘 영상이 없습니다');
        return;
      }
    }


    // 🔐 여기서는 "오늘 학생 여부"로 막지 않는다.
    //     오늘 자동배정은 완료되어도 파란 상태로 목록에 남긴다.
    //     서버가 제외한 skip·자율학습 영상은 현재 목록에 내려보내지 않는다.
    //     중단 영상은 이어볼 수 있도록 현재 목록에 남긴다.
    const chosen = getAssignedVideos(updatesCache, today, sid);
    const chosenStrs = new Set(chosen.map(String));

    // ✅ [중요] mid/id 불일치로 비는 경우 방지: (mid || id)로 매칭
    let myVids = (vidsCache || []).filter(v => {
      const kMid = String(v?.mid ?? '');
      const kId = String(v?.id ?? '');
      const playlistMid = (kMid || kId).trim();
      return ((kMid && chosenStrs.has(kMid)) || (kId && chosenStrs.has(kId)))
        && (keepCompletedAutoAssignment || !getProgress(playlistMid)?.completed);
    });

    // 보충 영상은 먼저 보여주고, 각 그룹 안에서는 기존 오늘 목록 순서를 유지한다.
    myVids.sort((a, b) => {
      const extraDiff = Number(isSupplementVideo(b)) - Number(isSupplementVideo(a));
      if (extraDiff) return extraDiff;
      const chapterDiff = videoChapterRank(a) - videoChapterRank(b);
      if (chapterDiff) return chapterDiff;
      return String(a.title || a.mid || '').localeCompare(String(b.title || b.mid || ''), 'ko');
    });

    const registeredVids = registeredReviewVideos();
    const todayMids = new Set(myVids.map(v => String(v?.mid ?? v?.id ?? '').trim()).filter(Boolean));
    const appendedReviewVids = registeredVids.filter(v => !todayMids.has(String(v.mid).trim()));

    const emptyMessage = courseVideosCompleted
      ? COURSE_VIDEOS_COMPLETED_MESSAGE
      : "오늘 할당된 영상이 없습니다.";

    if (!myVids.length && !appendedReviewVids.length) {
      if (listBox) listBox.innerHTML = `<li style='opacity:.65'>${emptyMessage}</li>`;
      setPlayerEmptyState(emptyMessage);
      return;
    }

    if (listBox) {
      listBox.textContent = '';
      [...myVids, ...appendedReviewVids].forEach((v, index) => {
        const isRegisteredReview = index >= myVids.length;
        const num = v.exNum?.[essayBandOf(stuCache.level)] || '';
        const mid = String(v?.mid ?? v?.id ?? '').trim();
        const prog = getProgress(mid);
        const done = prog?.completed || v?.todayAutoAssignmentStatus === 'done';
        const pct = (prog?.dur > 0)
          ? Math.min(100, Math.round((prog.last || 0) / prog.dur * 100))
          : 0;

        const li = document.createElement('li');
        li.dataset.mid = mid;
        if (!isRegisteredReview && index === 0) li.className = 'active';
        if (isRegisteredReview) li.dataset.reviewRegistered = 'true';

        const action = document.createElement('button');
        action.type = 'button';
        action.className = 'video-row-action';
        const main = document.createElement('span');
        main.className = 'video-main';
        main.append(assignedVideoTitle(v));

        if (done || pct) {
          const badge = document.createElement('span');
          badge.className = 'badge-done';
          badge.textContent = done ? '완료' : fmtPct(pct);
          if (!done) badge.title = '진행도';
          main.append(' ', badge);
        }
        action.appendChild(main);

        if (num) {
          const essay = document.createElement('span');
          essay.className = 'essay-badge';
          essay.textContent = `[서술형 ${num}번]`;
          action.appendChild(essay);
        }

        li.appendChild(action);
        listBox.appendChild(li);
      });
      if (currentMid) setActiveVideo(currentMid);
    }

    const preferMid = getLastMid();
    const firstMid = myVids.length
      ? ((preferMid && myVids.some(x => String(x.mid) === String(preferMid)))
        ? preferMid
        : myVids[0]?.mid)
      : null;

    if (!academyAccessAllowed) {
      setPlayerEmptyState(academyOnlyMessage);
      return;
    }

    if (firstMid) setPlayerReadyState();

    if (options.autoPlay !== false && firstMid && firstMid !== currentMid) {
      setActiveVideo(firstMid);
      play(firstMid);
    }
  }

  function updateListCompletionBadges() {
    let shouldRefreshPlaylist = false;
    const listBox = $('vidList');
    if (!listBox) return;
    const keepCompletedAutoAssignment = isTodayAutoVideoAssignment(
      updatesCache,
      studentDataDateKey(),
      sid,
    );
    listBox.querySelectorAll('li[data-mid]').forEach(li => {
      const mid = li.dataset.mid;
      const prog = getProgress(mid);
      const serverDone = (vidsCache || []).some(video => {
        const videoMid = String(video?.mid ?? video?.id ?? '').trim();
        return videoMid === mid && video?.todayAutoAssignmentStatus === 'done';
      });
      const done = prog?.completed || serverDone;
      if (done && li.dataset.reviewRegistered !== 'true' && !keepCompletedAutoAssignment) {
        shouldRefreshPlaylist = true;
      }
      const pct = (prog?.dur > 0) ? Math.min(100, Math.round((prog.last || 0) / prog.dur * 100)) : 0;
      const main = li.querySelector('.video-main');
      let badge = li.querySelector('.badge-done');
      if (done || pct) {
        if (!badge && main) {
          badge = document.createElement('span');
          badge.className = 'badge-done';
          main.append(' ', badge);
        }
        if (badge) badge.textContent = done ? '완료' : fmtPct(pct);
      } else {
        badge?.remove();
      }

      if (done) {
        li.title = '완료됨';
      } else if (pct) {
        li.title = `진행도 ${pct}%`;
      } else {
        li.removeAttribute('title');
      }
    });
    if (shouldRefreshPlaylist) void renderAssignedList({ autoPlay: false });
    renderStudentTodayOverview();
  }

  /* ───────────── Kollus 플레이어 교체 + 진행도(옵션) ───────────── */
  function withStartParam(url, seconds) {
    if (!seconds || seconds < 5) return url;
    try {
      const u = new URL(url, location.origin);
      if (!u.searchParams.has('start')) u.searchParams.set('start', Math.floor(seconds));
      if (!u.searchParams.has('t')) u.searchParams.set('t', Math.floor(seconds));
      return u.toString();
    } catch {
      if (!/#t=\d+/.test(url)) return url + `#t=${Math.floor(seconds)}`;
      return url;
    }
  }

  function attachKollusBridgeToIframe(frameEl, mid, resumeAtSec) {
    if (!frameEl) return;
    if (frameEl.__vgAttached && frameEl.__vgAttached === mid) return;

    function repost(type, payload) {
      window.postMessage({ type, mid, ...payload }, '*');
    }

    let tries = 0;
    const MAX_TRIES = 200;
    const iv = setInterval(() => {
      tries++;
      const ok = !!(window.VgControllerClient && frameEl.contentWindow);
      if (!ok && tries < MAX_TRIES) return;
      clearInterval(iv);
      if (!ok) {
        console.warn('[KollusBridge] VgControllerClient not available (timeout)');
        return;
      }

      try {
        const controller = new VgControllerClient({ target_window: frameEl.contentWindow });
        let lastSent = 0;

        controller.on('ready', function () {
          repost('kollus.ready', {});
          if (typeof controller.seek === 'function' && Number(resumeAtSec) > 5) {
            try { controller.seek(Math.floor(resumeAtSec)); } catch { }
          }

          const poll = async () => {
            try {
              const pos = await controller.getPosition?.();
              const dur = await controller.getDuration?.();
              if (Number.isFinite(pos) && Number.isFinite(dur) && dur > 0) {
                const pct = (pos / dur) * 100;
                const ended = pct >= 90 || pos >= dur - 1;
                if (Math.abs(pos - lastSent) >= 1) {
                  repost('kollus.progress', { currentTime: pos, duration: dur, ended });
                  lastSent = pos;
                }
              }
            } catch { }
            setTimeout(poll, 3000);
          };
          poll();
        });

        controller.on('progress', function (percent, position, duration) {
          const cur = Number(position) || 0;
          const dur = Number(duration) || 0;
          repost('kollus.progress', { currentTime: cur, duration: dur, ended: false });
        });

        controller.on('done', function () {
          repost('kollus.progress', { ended: true });
        });

        controller.on('play', async function () {
          try {
            const pos = await controller.getPosition?.();
            const dur = await controller.getDuration?.();
            if (Number.isFinite(pos) && Number.isFinite(dur)) {
              repost('kollus.progress', { currentTime: pos, duration: dur, ended: false });
            }
          } catch { }
        });

        controller.on('pause', async function () {
          try {
            const pos = await controller.getPosition?.();
            const dur = await controller.getDuration?.();
            if (Number.isFinite(pos) && Number.isFinite(dur)) {
              repost('kollus.progress', { currentTime: pos, duration: dur, ended: false });
            }
          } catch { }
        });

        frameEl.__vgAttached = mid;
        console.log('[KollusBridge] attached for', mid);
      } catch (e) {
        console.warn('[KollusBridge] init failed:', e);
      }
    }, 100);
  }

  window.addEventListener('message', (e) => {
    if (e?.source !== window) return;
    const data = e?.data;
    if (!data || typeof data !== 'object') return;
    const mid = String(data.mid ?? '').trim();
    const activeMid = String(currentMid ?? '').trim();
    if (!mid || !activeMid || mid !== activeMid) return;
    if (data.type === 'kollus.ready') {
      if (Number.isFinite(Number(data.duration))) {
        setProgress(mid, { dur: Number(data.duration) || undefined });
      }
    }
    if (data.type === 'kollus.progress') {
      const cur = Math.max(0, Number(data.currentTime) || 0);
      const dur = Math.max(0, Number(data.duration) || 0);
      const ended = !!data.ended || (dur > 0 && cur >= dur - 1);
      const pct = dur > 0 ? (cur / dur) : 0;
      const doneByPct = pct >= WATCH_DONE_RATIO;
      setProgress(mid, {
        last: cur,
        dur,
        completed: (ended || doneByPct) || undefined
      });
    }
  });

  async function play(mid) {
    if (!academyAccessAllowed) {
      showAcademyOnlyNotice();
      return;
    }
    if (currentMid && currentMid !== mid) {
      flushSyncQueue();
    }
    currentMid = mid;
    setLastMid(mid);
    const frame = $('player');
    if (frame) frame.src = "";

    const prog = getProgress(mid);
    const resumeAt = prog?.last || 0;

    try {
      const res = await studentAppRequest(`/api/get-url?mid=${encodeURIComponent(mid)}&sid=${encodeURIComponent(sid)}`);
      if (!res.ok) {
        if (res.status === 403) showAcademyOnlyNotice();
        throw new Error(res.status === 403 ? 'academy-network-required' : `get-url ${res.status}`);
      }
      let baseUrl = await res.text();
      console.log('[play] baseUrl from server =', baseUrl);

      if (location.protocol === 'https:' && /^http:\/\//i.test(baseUrl)) {
        baseUrl = baseUrl.replace(/^http:\/\//i, 'https://');
        console.log('[play] forced https url =', baseUrl);
      }

      let urlWithStart = withStartParam(baseUrl, resumeAt);

      if (frame) {
        frame.onload = () => {
          attachKollusBridgeToIframe(frame, mid, resumeAt);
        };
        frame.src = urlWithStart;
      }
    } catch (err) {
      console.error(err);
      if (err?.message === 'academy-network-required') return;
      alert("영상을 불러오지 못했습니다.");
    }
  }

  document.addEventListener('student-app:play-board-video', (event) => {
    if (!STUDENT_APP_PUBLIC_MODE) return;
    const mid = typeof event?.detail?.mid === 'string' ? event.detail.mid.trim() : '';
    if (!/^[A-Za-z0-9_-]{4,128}$/.test(mid)) return;
    const playerBox = $('playerBox');
    if (playerBox) {
      playerBox.tabIndex = -1;
      playerBox.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      playerBox.focus?.({ preventScroll: true });
    }
    void play(mid);
  });
})();

/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_START */
function studentAppValidAnnouncementId(value) {
  const id = typeof value === 'string' ? value : '';
  const match = /[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/.exec(id);
  return match?.index === 0 && match[0] === id;
}

function studentAppValidNotificationEventId(value) {
  return typeof value === 'string' && /^evt_[A-Za-z0-9_-]{32}$/.test(value);
}

function studentAppAnnouncementDeepLink(search) {
  const params = new URLSearchParams(String(search || ''));
  const announcements = params.getAll('announcement');
  const views = params.getAll('view');
  const items = params.getAll('item');
  if (announcements.length === 1 && views.length === 0 && items.length === 0) {
    return studentAppValidAnnouncementId(announcements[0]) ? announcements[0] : '';
  }
  if (announcements.length !== 0 || views.length !== 1 || views[0] !== 'board' || items.length !== 1) return '';
  return studentAppValidNotificationEventId(items[0]) ? items[0] : '';
}

function studentAppBoardDeepLink(search) {
  const params = new URLSearchParams(String(search || ''));
  const views = params.getAll('view');
  const items = params.getAll('item');
  if (params.has('announcement') || views.length !== 1 || views[0] !== 'board' || items.length !== 1) return '';
  return studentAppValidNotificationEventId(items[0]) ? items[0] : '';
}

function studentAppOpenAnnouncementDeepLink(id, announcements, openAnnouncement) {
  const safeId = studentAppValidAnnouncementId(id) || studentAppValidNotificationEventId(id) ? id : '';
  if (!safeId || !Array.isArray(announcements) || typeof openAnnouncement !== 'function') return false;
  const selected = announcements.find(item => String(item?.id || '') === safeId
    || String(item?.notificationEventId || '') === safeId);
  if (!selected) return false;
  openAnnouncement(selected);
  return true;
}
/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_END */

/* ────────────────────────────────────────────────────────────────────────────
   공지 팝업 / 공지함
──────────────────────────────────────────────────────────────────────────── */
(() => {
  const CT = { 'Content-Type': 'application/json' };
  const $ = s => document.querySelector(s);
  const SID = STUDENT_APP_PUBLIC_MODE ? '' : (window.__STU_SID__ || decodeURIComponent(location.pathname.split('/').pop()));

  const modal = $('#announceModal');
  const historyModal = $('#announceHistoryModal');
  const noticeBtn = $('#noticeBtn');
  const badge = $('#noticeBadge');
  const annTitle = $('#annTitle');
  const annContent = $('#annContent');
  const annImageSection = $('#annImageSection');
  const annImageCarousel = $('#annImageCarousel');
  const annImageTrack = $('#annImageTrack');
  const annImagePrev = $('#annImagePrev');
  const annImageNext = $('#annImageNext');
  const annImageDots = $('#annImageDots');
  const annImageCounter = $('#annImageCounter');
  const annCreatedAt = $('#annCreatedAt');
  const annReply = $('#annReply');
  const annAnonymous = $('#annAnonymous');
  const annSendReply = $('#annSendReply');
  const annReplyStatus = $('#annReplyStatus');
  const annRead = $('#annRead');
  const annSurvey = $('#annSurvey');
  const annSurveyQuestions = $('#annSurveyQuestions');
  const annSurveyError = $('#annSurveyError');
  const annSurveySubmit = $('#annSurveySubmit');
  const annSurveyMeta = $('#annSurveyMeta');
  const historyList = $('#annHistoryList');
  const historyClose = $('#annHistoryClose');
  const boardFilters = $('#studentBoardFilters');
  const boardStatus = $('#studentBoardStatus');
  const boardMore = $('#studentBoardMore');
  const ANN_REPLY_LIMIT = 3;
  const requestedBoardId = STUDENT_APP_PUBLIC_MODE ? studentAppBoardDeepLink(location.search) : '';
  const requestedAnnouncementId = STUDENT_APP_PUBLIC_MODE && !requestedBoardId
    ? studentAppAnnouncementDeepLink(location.search)
    : '';

  if (!modal || !historyModal || !noticeBtn || !annTitle || !annContent || !annRead) {
    console.warn('[announce] required elements not found on this page, skip init');
    return;
  }

  let announcements = [];
  let statusMap = {};
  let pending = [];
  let active = null;
  let activeFromHistory = false;
  let loading = false;
  let boardType = 'all';
  let boardItems = [];
  let boardNextCursor = null;
  let boardLoading = false;
  let boardRequestId = 0;
  let imageCarouselIndex = 0;
  let imagePointerStartX = 0;
  let imagePointerStartY = 0;
  let imagePointerMoved = false;
  let imagePointerActive = false;
  let announcementDeepLinkHandled = !requestedAnnouncementId;
  let announcementReturnFocus = null;
  let historyReturnFocus = null;
  const studentShell = document.querySelector('.student-shell');
  const DIALOG_FOCUS_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  function dialogControls(dialog) {
    return Array.from(dialog?.querySelectorAll(DIALOG_FOCUS_SELECTOR) || [])
      .filter(control => !control.hidden && control.getAttribute('aria-hidden') !== 'true' && control.getClientRects().length);
  }

  function syncDialogIsolation() {
    const dialogOpen = modal.style.display === 'flex' || historyModal.style.display === 'flex';
    studentShell?.toggleAttribute('inert', dialogOpen);
  }

  function openDialog(dialog, preferredFocus) {
    dialog.style.display = 'flex';
    dialog.setAttribute('aria-hidden', 'false');
    syncDialogIsolation();
    window.requestAnimationFrame(() => {
      (preferredFocus || dialogControls(dialog)[0])?.focus?.();
    });
  }

  function closeDialog(dialog, returnFocus, { restoreFocus = true } = {}) {
    dialog.style.display = 'none';
    dialog.setAttribute('aria-hidden', 'true');
    syncDialogIsolation();
    if (restoreFocus) window.requestAnimationFrame(() => returnFocus?.focus?.());
  }

  function trapDialogFocus(dialog, event) {
    if (event.key !== 'Tab') return;
    const controls = dialogControls(dialog);
    if (!controls.length) {
      event.preventDefault();
      dialog.querySelector('[role="dialog"]')?.focus?.();
      return;
    }
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (!controls.includes(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function openAnnouncementDialog(opener) {
    if (modal.style.display !== 'flex' && !announcementReturnFocus) {
      const activeElement = document.activeElement;
      announcementReturnFocus = opener?.focus
        ? opener
        : (activeElement && activeElement !== document.body && activeElement.focus ? activeElement : noticeBtn);
    }
    openDialog(modal, $('#annModalHeading'));
  }

  function closeAnnouncementDialog(options = {}) {
    const restoreFocus = options.restoreFocus !== false && !!announcementReturnFocus;
    closeDialog(modal, announcementReturnFocus || noticeBtn, { restoreFocus });
    if (options.restoreFocus !== false) announcementReturnFocus = null;
  }

  function openHistoryDialog(opener) {
    historyReturnFocus = opener?.focus ? opener : noticeBtn;
    openDialog(historyModal, historyClose);
  }

  function closeHistoryDialog(options = {}) {
    const restoreFocus = options.restoreFocus !== false && !!historyReturnFocus;
    closeDialog(historyModal, historyReturnFocus || noticeBtn, { restoreFocus });
    if (options.restoreFocus !== false) historyReturnFocus = null;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[ch]));
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${mm}/${dd} ${hh}:${mi}`;
  }

  function formatPopupCreatedAt(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const month = d.getMonth() + 1;
    const date = d.getDate();
    const hour12 = d.getHours() % 12 || 12;
    const minute = String(d.getMinutes()).padStart(2, '0');
    return `${month}월 ${date}일 ${hour12}:${minute}`;
  }

  function timeLeftText(expiresAt) {
    const end = new Date(expiresAt).getTime();
    if (!Number.isFinite(end)) return '4시간 동안 표시';
    const ms = end - Date.now();
    if (ms <= 0) return '만료됨';
    const mins = Math.ceil(ms / 60000);
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    if (h <= 0) return `${m}분 남음`;
    return `${h}시간 ${m}분 남음`;
  }

  function normalizeAnnouncementImage(image) {
    if (!image || typeof image !== 'object') return null;
    const url = String(image.originalUrl || image.sourceUrl || image.fullUrl || image.url || '').trim();
    if (!url) return null;
    return {
      url,
      alt: '',
    };
  }

  function normalizeAnnouncementImages(ann) {
    const rawImages = Array.isArray(ann?.images) ? ann.images : [];
    const images = rawImages.map(normalizeAnnouncementImage).filter(Boolean);
    if (!images.length) {
      const image = normalizeAnnouncementImage(ann?.image);
      if (image) images.push(image);
    }
    const seen = new Set();
    return images.filter((image) => {
      if (!image.url || seen.has(image.url)) return false;
      seen.add(image.url);
      return true;
    });
  }

  /* STUDENT_APP_BOARD_START */
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

  function setBoardStatus(message, state = '') {
    if (!boardStatus) return;
    boardStatus.hidden = false;
    boardStatus.textContent = String(message || '');
    boardStatus.dataset.state = state;
  }

  function renderStudentBoard() {
    if (!STUDENT_APP_PUBLIC_MODE || !historyList) return false;
    if (boardFilters) boardFilters.hidden = false;
    boardFilters?.querySelectorAll('[data-student-board-type]').forEach(button => {
      button.setAttribute('aria-pressed', button.dataset.studentBoardType === boardType ? 'true' : 'false');
    });
    historyList.replaceChildren();
    if (!boardItems.length) {
      const empty = document.createElement('p');
      empty.className = 'announce-history-empty';
      empty.textContent = boardLoading ? '게시판을 불러오는 중입니다.' : '현재 볼 수 있는 게시물이 없습니다.';
      historyList.append(empty);
    } else {
      const fragment = document.createDocumentFragment();
      boardItems.forEach(item => {
        const card = document.createElement('article');
        card.className = `student-board-card is-${item.type}${item.read ? ' is-read' : ''}`;
        card.dataset.studentBoardId = item.id;
        card.tabIndex = -1;
        if (item.type === 'video' && item.thumbnail) {
          const image = document.createElement('img');
          image.className = 'student-board-thumbnail';
          image.src = item.thumbnail;
          image.alt = '';
          card.append(image);
        }
        const header = document.createElement('div');
        header.className = 'student-board-card-head';
        const badgeNode = document.createElement('span');
        badgeNode.className = 'student-board-kind';
        badgeNode.textContent = item.type === 'video' ? '영상' : item.kind === 'survey' ? '설문' : '공지';
        const stateNode = document.createElement('span');
        stateNode.className = 'student-board-read-state';
        stateNode.textContent = item.read ? '확인함' : '새 글';
        header.append(badgeNode, stateNode);
        const titleNode = document.createElement('h4');
        titleNode.textContent = item.title;
        const contentNode = document.createElement('p');
        contentNode.textContent = item.content;
        const meta = document.createElement('time');
        meta.dateTime = item.createdAt;
        meta.textContent = `${formatDateTime(item.createdAt)} · ${timeLeftText(item.expiresAt)}`;
        const action = document.createElement('button');
        action.type = 'button';
        action.dataset.studentBoardAction = item.id;
        action.textContent = item.type === 'video'
          ? (item.locked ? '학원에서 재생할 수 있어요' : '영상 재생')
          : '내용 보기';
        if (item.type === 'video' && item.locked) action.dataset.locked = 'true';
        card.append(header, titleNode, contentNode, meta, action);
        fragment.append(card);
      });
      historyList.append(fragment);
    }
    if (boardMore) {
      boardMore.hidden = !boardNextCursor;
      boardMore.disabled = boardLoading;
    }
    return true;
  }

  function boardItemByIdentifier(identifier) {
    return boardItems.find(item => item.id === identifier || item.notificationEventId === identifier) || null;
  }

  function focusBoardItem(identifier) {
    const item = boardItemByIdentifier(identifier);
    if (!item) return false;
    const card = historyList?.querySelector(`[data-student-board-id="${CSS.escape(item.id)}"]`);
    if (!card) return false;
    card.classList.add('student-app-deep-link-target');
    card.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
    card.focus?.();
    window.setTimeout(() => card.classList.remove('student-app-deep-link-target'), 2400);
    return true;
  }

  async function loadStudentBoard({ reset = false, seekId = '' } = {}) {
    if (!STUDENT_APP_PUBLIC_MODE) return false;
    const requestId = ++boardRequestId;
    boardLoading = true;
    if (reset) {
      boardItems = [];
      boardNextCursor = null;
    }
    renderStudentBoard();
    setBoardStatus('게시판을 불러오는 중입니다.', 'loading');
    let cursor = boardNextCursor;
    let pages = 0;
    try {
      do {
        const suffix = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
        const response = await studentAppRequest(`/api/mobile/student/board?type=${encodeURIComponent(boardType)}${suffix}`, { cache: 'no-store' });
        if (response.status === 401 || response.status === 403) {
          throw new StudentAppSessionError(
            response.status === 401 ? 'unauthenticated' : 'session_not_ready',
            response.status,
            STUDENT_APP_PUBLIC_SESSION.activeSid(),
          );
        }
        if (!response.ok) throw new Error(`board_${response.status}`);
        const page = normalizeBoardPage(await response.json(), boardType);
        if (!page) throw new Error('board_malformed');
        if (requestId !== boardRequestId) return false;
        const known = new Set(boardItems.map(item => item.id));
        boardItems = boardItems.concat(page.items.filter(item => !known.has(item.id)));
        boardNextCursor = page.nextCursor;
        cursor = boardNextCursor;
        pages += 1;
      } while (seekId && !boardItemByIdentifier(seekId) && cursor && pages < 10);
      renderStudentBoard();
      const found = seekId ? focusBoardItem(seekId) : true;
      setBoardStatus(found ? `${boardItems.length}개의 게시물을 표시했습니다.` : '만료되었거나 볼 수 없는 게시물입니다.', found ? 'ready' : 'empty');
      return found;
    } catch (error) {
      if (handleStudentAppSessionFailure(error)) return false;
      if (requestId !== boardRequestId) return false;
      console.warn('[board] load failed:', error);
      renderStudentBoard();
      setBoardStatus('게시판을 불러오지 못했습니다. 다시 시도해 주세요.', 'error');
      return false;
    } finally {
      if (requestId === boardRequestId) {
        boardLoading = false;
        renderStudentBoard();
      }
    }
  }
  /* STUDENT_APP_BOARD_END */

  function getSurvey(ann) {
    const survey = ann?.survey;
    if (!survey || typeof survey !== 'object' || !Array.isArray(survey.questions)) return null;
    if (survey.status && survey.status !== 'public') return null;
    return survey;
  }

  function isSurveyAnnouncement(ann) {
    return !!getSurvey(ann);
  }

  function hasSurveySubmission(ann) {
    const status = statusMap?.[ann?.id] || {};
    if (status.surveySubmittedAt && status.surveyAnswers && typeof status.surveyAnswers === 'object') return true;
    return Array.isArray(status.surveyResponses) && status.surveyResponses.some(row => row && typeof row.answers === 'object');
  }

  function replyRowsForStatus(status) {
    const rows = Array.isArray(status?.replies)
      ? status.replies.filter(row => row && String(row.reply || '').trim())
      : [];
    const legacyReply = String(status?.reply || '').trim();
    const legacyAt = String(status?.repliedAt || '');
    if (legacyReply && !rows.some(row => String(row.reply || '').trim() === legacyReply && String(row.repliedAt || '') === legacyAt)) {
      rows.push({ reply: legacyReply, anonymous: !!status?.anonymous, repliedAt: legacyAt });
    }
    return rows;
  }

  function replyCountFor(ann) {
    return replyRowsForStatus(statusMap?.[ann?.id] || {}).length;
  }

  function replyLimitMessage(count) {
    if (count <= 1) return '2번 더 답장 가능!';
    if (count === 2) return '마지막 답장 남음!';
    return '이제 쉿!';
  }

  function syncReplyLimitUi() {
    if (!active || !annReply || !annSendReply) return;
    const isMaxed = replyCountFor(active) >= ANN_REPLY_LIMIT;
    annReply.disabled = isMaxed;
    annSendReply.disabled = isMaxed;
    annReply.placeholder = isMaxed ? '답장은 최대 3회까지 가능합니다.' : '답장을 입력하세요.';
  }

  function isComplete(ann) {
    const survey = getSurvey(ann);
    if (survey && ann?.requireCompletion !== false) return hasSurveySubmission(ann);
    return isAcked(ann);
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

  function setBadge(count) {
    if (!badge) return;
    if (!count) {
      badge.hidden = true;
      badge.textContent = '0';
      return;
    }
    badge.hidden = false;
    badge.textContent = String(count);
  }

  function isAcked(ann) {
    return !!statusMap?.[ann?.id]?.acked;
  }

  function updatePending() {
    pending = announcements.filter(ann => !isComplete(ann));
    setBadge(pending.length);
    document.dispatchEvent(new CustomEvent('student-app:announcement-summary', {
      detail: { pending: pending.length, total: announcements.length },
    }));
  }

  function renderSurvey(ann) {
    if (!annSurvey || !annSurveyQuestions) return;
    const survey = getSurvey(ann);
    const status = statusMap?.[ann?.id] || {};
    const submitted = hasSurveySubmission(ann);
    modal.classList.toggle('has-survey', !!survey);

    if (!survey) {
      annSurvey.hidden = true;
      annSurveyQuestions.innerHTML = '';
      if (annSurveyError) annSurveyError.textContent = '';
      return;
    }

    annSurvey.hidden = false;
    if (annSurveyMeta) {
      annSurveyMeta.textContent = submitted && !survey.allowMultiple
        ? '이미 제출한 설문입니다.'
        : `${survey.anonymous ? '익명 응답' : '실명 응답'} · ${survey.allowMultiple ? '여러 번 제출 가능' : '1회 제출'}`;
    }

    const latestAnswers = status.surveyAnswers && typeof status.surveyAnswers === 'object'
      ? status.surveyAnswers
      : {};
    const readonly = submitted && !survey.allowMultiple;

    annSurveyQuestions.innerHTML = survey.questions.map((question, qIndex) => {
      const qid = String(question.id || `q${qIndex + 1}`);
      const type = question.type || 'single';
      const required = question.required !== false;
      const value = latestAnswers[qid];
      const disabled = readonly ? 'disabled' : '';
      const requiredMark = required ? '<b>필수</b>' : '<b class="optional">선택</b>';

      if (type === 'single' || type === 'multiple') {
        const options = Array.isArray(question.options) ? question.options : [];
        const selected = type === 'multiple'
          ? new Set(Array.isArray(value) ? value.map(String) : [])
          : new Set(value ? [String(value)] : []);
        return `
          <fieldset class="announce-survey-question" data-survey-qid="${escapeHtml(qid)}" data-survey-type="${escapeHtml(type)}" ${required ? 'data-required="true"' : ''}>
            <legend>
              <span>${escapeHtml(question.text || '질문')}</span>
              <em>${requiredMark}${escapeHtml(surveyTypeText(type))}</em>
            </legend>
            <div class="announce-survey-options">
              ${options.map((option, optIndex) => {
                const oid = String(option.id || `o${optIndex + 1}`);
                const inputType = type === 'single' ? 'radio' : 'checkbox';
                return `
                  <label class="announce-survey-option">
                    <input type="${inputType}" name="survey_${escapeHtml(qid)}" value="${escapeHtml(oid)}" ${selected.has(oid) ? 'checked' : ''} ${disabled}>
                    <span>${escapeHtml(option.text || '')}</span>
                  </label>
                `;
              }).join('')}
            </div>
          </fieldset>
        `;
      }

      const textValue = typeof value === 'string' ? value : '';
      return `
        <fieldset class="announce-survey-question" data-survey-qid="${escapeHtml(qid)}" data-survey-type="${escapeHtml(type)}" ${required ? 'data-required="true"' : ''}>
          <legend>
            <span>${escapeHtml(question.text || '질문')}</span>
            <em>${requiredMark}${escapeHtml(surveyTypeText(type))}</em>
          </legend>
          ${type === 'long'
            ? `<textarea rows="4" placeholder="답변을 입력하세요." ${disabled}>${escapeHtml(textValue)}</textarea>`
            : `<input type="text" value="${escapeHtml(textValue)}" placeholder="답변을 입력하세요." ${disabled}>`}
        </fieldset>
      `;
    }).join('');

    if (annSurveyError) annSurveyError.textContent = submitted && !survey.allowMultiple ? '제출 완료된 설문입니다.' : '';
    if (annSurveySubmit) {
      annSurveySubmit.hidden = readonly;
      annSurveySubmit.disabled = readonly;
      annSurveySubmit.textContent = survey.allowMultiple && submitted ? '추가 제출' : '설문 제출';
    }
  }

  function updateImageCarousel(nextIndex = imageCarouselIndex) {
    const slides = Array.from(annImageTrack?.children || []);
    const total = slides.length;
    if (!annImageTrack || !total) return;

    imageCarouselIndex = Math.max(0, Math.min(nextIndex, total - 1));
    annImageTrack.style.transform = `translateX(${-imageCarouselIndex * 100}%)`;
    slides.forEach((slide, index) => {
      slide.toggleAttribute('aria-hidden', index !== imageCarouselIndex);
    });

    const activeSlide = slides[imageCarouselIndex];
    const ratio = activeSlide?.dataset?.imageRatio || '16 / 9';
    annImageCarousel?.style.setProperty('--ann-active-image-ratio', ratio);

    if (annImageCounter) {
      annImageCounter.textContent = total > 1 ? `${imageCarouselIndex + 1} / ${total}` : '';
    }
    if (annImagePrev) annImagePrev.hidden = total <= 1;
    if (annImageNext) annImageNext.hidden = total <= 1;
    if (annImageDots) {
      annImageDots.hidden = total <= 1;
      annImageDots.querySelectorAll('button').forEach((dot, index) => {
        dot.classList.toggle('is-active', index === imageCarouselIndex);
        dot.setAttribute('aria-current', index === imageCarouselIndex ? 'true' : 'false');
      });
    }
  }

  function moveImageCarousel(delta) {
    const total = annImageTrack?.children?.length || 0;
    if (total <= 1) return;
    updateImageCarousel((imageCarouselIndex + delta + total) % total);
  }

  function shouldIgnoreImageGestureTarget(target) {
    return !!target?.closest?.('.announce-image-nav, .announce-image-dots');
  }

  function beginImageGesture(clientX, clientY) {
    imagePointerStartX = clientX;
    imagePointerStartY = clientY;
    imagePointerMoved = false;
  }

  function finishImageGesture(clientX, clientY, ev) {
    const dx = clientX - imagePointerStartX;
    const dy = clientY - imagePointerStartY;
    if (Math.abs(dx) < 42 || Math.abs(dx) < Math.abs(dy) * 1.15) return false;
    ev?.preventDefault?.();
    imagePointerMoved = true;
    moveImageCarousel(dx < 0 ? 1 : -1);
    return true;
  }

  function clearImageCarousel() {
    imageCarouselIndex = 0;
    if (!annImageSection || !annImageTrack) return;
    annImageSection.hidden = true;
    annImageTrack.innerHTML = '';
    if (annImageDots) annImageDots.innerHTML = '';
    if (annImageCounter) annImageCounter.textContent = '';
    if (annImagePrev) annImagePrev.hidden = true;
    if (annImageNext) annImageNext.hidden = true;
    if (annImageDots) annImageDots.hidden = true;
    annImageCarousel?.style.removeProperty('--ann-active-image-ratio');
  }

  function renderImageCarousel(images, title) {
    if (!annImageSection || !annImageTrack || !annImageCarousel) return;
    if (!images.length) {
      clearImageCarousel();
      return;
    }

    imageCarouselIndex = 0;
    annImageSection.hidden = false;
    annImageTrack.innerHTML = images.map((image, index) => `
      <div class="announce-image-slide" data-image-ratio="16 / 9" role="group" aria-label="이미지 ${index + 1} / ${images.length}">
        <a class="announce-image-frame" href="${escapeHtml(image.url)}" target="_blank" rel="noopener noreferrer">
          <img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.alt || title || '공지 이미지')}" draggable="false">
        </a>
      </div>
    `).join('');
    if (annImageDots) {
      annImageDots.innerHTML = images.map((_, index) => `
        <button type="button" aria-label="이미지 ${index + 1} 보기" ${index === 0 ? 'aria-current="true"' : 'aria-current="false"'}><span aria-hidden="true"></span></button>
      `).join('');
    }

    const removeFailedImage = (img) => {
      const slide = img.closest('.announce-image-slide');
      slide?.remove();
      if (!annImageTrack.children.length) {
        clearImageCarousel();
        modal.classList.remove('has-image');
        return;
      }
      Array.from(annImageTrack.children).forEach((item, idx) => {
        item.setAttribute('aria-label', `이미지 ${idx + 1} / ${annImageTrack.children.length}`);
      });
      if (annImageDots) {
        annImageDots.innerHTML = Array.from(annImageTrack.children).map((_, index) => `
          <button type="button" aria-label="이미지 ${index + 1} 보기" ${index === 0 ? 'aria-current="true"' : 'aria-current="false"'}><span aria-hidden="true"></span></button>
        `).join('');
      }
      updateImageCarousel(Math.min(imageCarouselIndex, annImageTrack.children.length - 1));
    };

    annImageTrack.querySelectorAll('img').forEach((img, index) => {
      const syncRatio = () => {
        if (!img.naturalWidth || !img.naturalHeight) return;
        const slide = img.closest('.announce-image-slide');
        if (!slide) return;
        slide.dataset.imageRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
        if (index === imageCarouselIndex) updateImageCarousel(imageCarouselIndex);
      };
      img.addEventListener('load', syncRatio, { once: true });
      img.addEventListener('error', () => removeFailedImage(img), { once: true });
      if (img.complete && img.naturalWidth) syncRatio();
      else if (img.complete) removeFailedImage(img);
    });

    updateImageCarousel(0);
  }

  function renderActive(ann, options = {}) {
    active = ann || null;
    activeFromHistory = !!options.fromHistory;
    if (!active) return;
    const images = normalizeAnnouncementImages(active);
    annTitle.textContent = active.title || '공지';
    annContent.textContent = active.content || '';
    modal.classList.toggle('has-image', !!images.length);
    renderImageCarousel(images, active.title);
    if (annCreatedAt) annCreatedAt.textContent = formatPopupCreatedAt(active.createdAt);
    if (annReply) annReply.value = statusMap?.[active.id]?.reply || '';
    if (annAnonymous) annAnonymous.checked = !!statusMap?.[active.id]?.anonymous;
    if (annReplyStatus) annReplyStatus.textContent = '';
    renderSurvey(active);
    syncReplyLimitUi();
    if (annRead) annRead.textContent = isSurveyAnnouncement(active) && !hasSurveySubmission(active) ? '설문 제출 필요' : '읽었습니다.';
    openAnnouncementDialog(options.opener);
  }

  function showNextPending() {
    updatePending();
    if (!pending.length) {
      closeAnnouncementDialog();
      active = null;
      activeFromHistory = false;
      return;
    }
    renderActive(pending[0]);
  }

  async function fetchJSON(url, init) {
    const res = await studentAppRequest(url, init);
    if (!res.ok) {
      let text = '';
      try { text = await res.text(); } catch {}
      throw new Error(text || `${url} ${res.status}`);
    }
    return res.json();
  }

  async function announcementSid() {
    if (!STUDENT_APP_PUBLIC_MODE) return SID;
    return (await STUDENT_APP_PUBLIC_SESSION.refreshSession()).activeSid;
  }

  function handleAnnouncementSessionFailure(error) {
    if (!['login_required', 'unauthenticated', 'session_not_ready', 'sid_mismatch', 'sid_rotated'].includes(error?.code)) return;
    handleStudentAppSessionFailure(error);
  }

  async function markBoardVideoRead(item) {
    try {
      const requestSid = await announcementSid();
      await fetchJSON('/api/announce-ack', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({ sid: requestSid, id: item.id }),
      });
      statusMap[item.id] = { ...(statusMap[item.id] || {}), acked: true };
      boardItems = boardItems.map(row => row.id === item.id ? Object.freeze({ ...row, read: true }) : row);
    } catch (error) {
      handleAnnouncementSessionFailure(error);
      console.warn('[board] read receipt failed:', error);
    }
  }

  async function openStudentBoardItem(identifier, opener) {
    const item = boardItemByIdentifier(identifier);
    if (!item) return false;
    if (item.type === 'video') {
      if (item.locked) {
        setBoardStatus('영상은 학원 네트워크에서만 재생할 수 있습니다.', 'locked');
        focusBoardItem(item.id);
        return false;
      }
      void markBoardVideoRead(item);
      closeHistoryDialog({ restoreFocus: false });
      historyReturnFocus = null;
      document.dispatchEvent(new CustomEvent('student-app:play-board-video', { detail: { mid: item.videoMid } }));
      return true;
    }
    let announcement = announcements.find(row => String(row?.id || '') === item.id);
    if (!announcement) {
      await loadAnnouncements({ showPopup: false });
      announcement = announcements.find(row => String(row?.id || '') === item.id);
    }
    if (!announcement) {
      setBoardStatus('만료되었거나 더 이상 볼 수 없는 공지입니다.', 'empty');
      return false;
    }
    const returnFocus = historyReturnFocus || noticeBtn;
    closeHistoryDialog({ restoreFocus: false });
    historyReturnFocus = null;
    renderActive(announcement, { fromHistory: true, opener: returnFocus });
    return true;
  }

  async function loadAnnouncements({ showPopup = true } = {}) {
    if (loading) return;
    loading = true;
    try {
      const requestSid = await announcementSid();
      const [anns, stat] = await Promise.all([
        fetchJSON(`/api/announcements?sid=${encodeURIComponent(requestSid)}`, { cache: 'no-store' }),
        fetchJSON(`/api/announce-status?sid=${encodeURIComponent(requestSid)}`, { cache: 'no-store' }),
      ]);
      announcements = Array.isArray(anns) ? anns : [];
      statusMap = stat && typeof stat === 'object' ? stat : {};
      updatePending();
      renderHistory();
      if (showPopup && !announcementDeepLinkHandled) {
        announcementDeepLinkHandled = studentAppOpenAnnouncementDeepLink(requestedAnnouncementId, announcements, ann => renderActive(ann, { fromHistory: true }));
        if (announcementDeepLinkHandled || requestedAnnouncementId) return;
      }
      if (showPopup) showNextPending();
    } catch (err) {
      handleAnnouncementSessionFailure(err);
      console.warn('[announce] load failed:', err);
      if (historyList) historyList.innerHTML = '<div class="muted">공지를 불러오지 못했습니다.</div>';
    } finally {
      loading = false;
    }
  }

  async function ackActive() {
    if (!active) return;
    if (isSurveyAnnouncement(active) && active.requireCompletion !== false && !hasSurveySubmission(active)) {
      if (annReplyStatus) annReplyStatus.textContent = '설문을 먼저 제출해 주세요.';
      if (annSurveyError) annSurveyError.textContent = '필수 설문은 제출 전까지 닫을 수 없습니다.';
      annSurvey?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      annSurveyQuestions?.querySelector('input:not(:disabled), textarea:not(:disabled)')?.focus?.();
      return;
    }
    const id = active.id;
    const shouldContinuePending = !activeFromHistory;
    try {
      const requestSid = await announcementSid();
      await fetchJSON('/api/announce-ack', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({ sid: requestSid, id }),
      });
      statusMap[id] = { ...(statusMap[id] || {}), acked: true };
      active = null;
      activeFromHistory = false;
      updatePending();
      renderHistory();
      if (shouldContinuePending && pending.length) renderActive(pending[0]);
      else closeAnnouncementDialog();
    } catch (err) {
      handleAnnouncementSessionFailure(err);
      console.warn('[announce] ack failed:', err);
      if (annReplyStatus) annReplyStatus.textContent = '읽음 처리에 실패했습니다. 다시 눌러 주세요.';
    }
  }

  function collectSurveyAnswers({ focusInvalid = false } = {}) {
    if (!active || !annSurveyQuestions) return null;
    const survey = getSurvey(active);
    if (!survey) return null;

    const answers = {};
    for (const question of survey.questions) {
      const qid = String(question.id || '');
      const type = question.type || 'single';
      const required = question.required !== false;
      const field = annSurveyQuestions.querySelector(`[data-survey-qid="${CSS.escape(qid)}"]`);
      if (!field) continue;

      let value = null;
      if (type === 'single') {
        value = field.querySelector('input[type="radio"]:checked')?.value || '';
      } else if (type === 'multiple') {
        value = Array.from(field.querySelectorAll('input[type="checkbox"]:checked')).map(input => input.value);
      } else {
        value = (field.querySelector('textarea, input[type="text"]')?.value || '').trim();
      }

      const missing = type === 'multiple' ? !value.length : !String(value || '').trim();
      field.classList.toggle('is-invalid', required && missing);
      if (required && missing) {
        if (annSurveyError) annSurveyError.textContent = '필수 질문에 모두 응답해 주세요.';
        if (focusInvalid) field.querySelector('input, textarea')?.focus?.();
        return null;
      }

      if (!missing) answers[qid] = value;
    }

    if (annSurveyError) annSurveyError.textContent = '';
    return answers;
  }

  async function submitSurvey() {
    if (!active || !annSurveySubmit) return;
    const survey = getSurvey(active);
    if (!survey) return;
    if (hasSurveySubmission(active) && !survey.allowMultiple) {
      if (annSurveyError) annSurveyError.textContent = '이미 제출한 설문입니다.';
      return;
    }
    const surveyAnswers = collectSurveyAnswers({ focusInvalid: true });
    if (!surveyAnswers) return;

    annSurveySubmit.disabled = true;
    try {
      const requestSid = await announcementSid();
      const saved = await fetchJSON('/api/announce-submit', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({
          sid: requestSid,
          id: active.id,
          surveyAnswers,
        }),
      });
      const currentStatus = statusMap[active.id] || {};
      const surveyEntry = saved?.survey || {
        answers: surveyAnswers,
        anonymous: !!survey.anonymous,
        submittedAt: new Date().toISOString(),
      };
      const surveyResponses = Array.isArray(currentStatus.surveyResponses) ? currentStatus.surveyResponses.slice() : [];
      surveyResponses.push(surveyEntry);
      statusMap[active.id] = {
        ...currentStatus,
        acked: true,
        surveyAnswers,
        surveyAnonymous: !!survey.anonymous,
        surveySubmittedAt: surveyEntry.submittedAt,
        surveyResponses,
      };
      renderSurvey(active);
      updatePending();
      renderHistory();
      if (annReplyStatus) annReplyStatus.textContent = '설문을 제출했습니다.';
      if (!activeFromHistory) {
        const submittedAnnId = active.id;
        window.setTimeout(() => {
          if (active?.id !== submittedAnnId) return;
          closeAnnouncementDialog({ restoreFocus: false });
          active = null;
          showNextPending();
        }, 650);
      }
    } catch (err) {
      handleAnnouncementSessionFailure(err);
      console.warn('[announce] survey submit failed:', err);
      if (annSurveyError) annSurveyError.textContent = '설문 제출에 실패했습니다.';
    } finally {
      annSurveySubmit.disabled = false;
    }
  }

  async function submitReply() {
    if (!active || !annReply) return;
    const currentCount = replyCountFor(active);
    if (currentCount >= ANN_REPLY_LIMIT) {
      alert('이제 쉿!');
      syncReplyLimitUi();
      return;
    }
    const reply = annReply.value.trim();
    if (!reply) {
      annReply.focus();
      if (annReplyStatus) annReplyStatus.textContent = '답장을 입력해 주세요.';
      return;
    }
    annSendReply.disabled = true;
    try {
      const requestSid = await announcementSid();
      const saved = await fetchJSON('/api/announce-submit', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({
          sid: requestSid,
          id: active.id,
          reply,
          anonymous: !!annAnonymous?.checked,
        }),
      });
      const currentStatus = statusMap[active.id] || {};
      const replyEntry = saved?.reply || {
        reply,
        anonymous: !!annAnonymous?.checked,
        repliedAt: new Date().toISOString(),
      };
      const replies = replyRowsForStatus(currentStatus).slice();
      replies.push(replyEntry);
      statusMap[active.id] = {
        ...currentStatus,
        reply,
        anonymous: !!annAnonymous?.checked,
        repliedAt: replyEntry.repliedAt,
        replies,
      };
      annReply.value = '';
      if (annReplyStatus) annReplyStatus.textContent = '답장을 보냈습니다.';
      const nextCount = replyCountFor(active);
      alert(replyLimitMessage(nextCount));
      syncReplyLimitUi();
      renderHistory();
    } catch (err) {
      handleAnnouncementSessionFailure(err);
      console.warn('[announce] reply failed:', err);
      if (err?.message?.includes('reply limit') || err?.message?.includes('429')) {
        alert('이제 쉿!');
        syncReplyLimitUi();
      }
      if (annReplyStatus) annReplyStatus.textContent = '전송에 실패했습니다.';
    } finally {
      syncReplyLimitUi();
    }
  }

  function renderHistory() {
    if (!historyList) return;
    if (renderStudentBoard()) return;
    if (!announcements.length) {
      historyList.innerHTML = '<div class="announce-history-empty">최근 4시간 안에 도착한 공지가 없습니다.</div>';
      return;
    }
    historyList.innerHTML = announcements.map(ann => {
      const status = statusMap[ann.id] || {};
      const survey = getSurvey(ann);
      const surveyDone = survey && hasSurveySubmission(ann);
      const surveyLabel = survey
        ? `<span class="announce-history-survey-badge">${surveyDone ? '설문 완료' : '설문 대기'}</span>`
        : '';
      const answerSummary = survey && status.surveyAnswers && typeof status.surveyAnswers === 'object'
        ? survey.questions.map(question => {
            const value = status.surveyAnswers[String(question.id || '')];
            if (value == null || value === '' || (Array.isArray(value) && !value.length)) return '';
            const text = Array.isArray(value)
              ? value.map(item => surveyOptionText(question, item)).filter(Boolean).join(', ')
              : (question.type === 'single' ? surveyOptionText(question, value) : String(value));
            return text ? `${question.text}: ${text}` : '';
          }).filter(Boolean).slice(0, 2).join(' · ')
        : '';
      const images = normalizeAnnouncementImages(ann);
      const imageLabel = images.length
        ? `<span class="announce-history-image-badge">${images.length > 1 ? `이미지 ${images.length}장` : '이미지 첨부'}</span>`
        : '';
      const badges = `${surveyLabel}${imageLabel}`;
      const replySummary = status.reply
        ? `<span class="announce-history-note">내 답장: ${escapeHtml(status.reply)}</span>`
        : '';
      const surveySummary = answerSummary
        ? `<span class="announce-history-note">내 설문: ${escapeHtml(answerSummary)}</span>`
        : '';
      return `
        <button class="announce-history-item" type="button" data-ann-history-id="${escapeHtml(ann.id)}">
          <div class="announce-history-item-head">
            <div class="announce-history-main">
              <strong class="announce-history-title">${escapeHtml(ann.title || (survey ? '설문조사' : '공지'))}</strong>
              <span class="announce-history-meta">${escapeHtml(formatDateTime(ann.createdAt))} · ${escapeHtml(timeLeftText(ann.expiresAt))}</span>
            </div>
            ${badges ? `<div class="announce-history-badges">${badges}</div>` : ''}
          </div>
          <p class="announce-history-content">${escapeHtml(ann.content || '')}</p>
          ${surveySummary || replySummary ? `<div class="announce-history-foot">${surveySummary}${replySummary}</div>` : ''}
        </button>
      `;
    }).join('');
  }

  function openHistoryAnnouncement(id) {
    const ann = announcements.find(item => String(item?.id) === String(id));
    if (!ann) return;
    const returnFocus = historyReturnFocus || noticeBtn;
    closeHistoryDialog({ restoreFocus: false });
    historyReturnFocus = null;
    renderActive(ann, { fromHistory: true, opener: returnFocus });
  }

  noticeBtn.addEventListener('click', async () => {
    await loadAnnouncements({ showPopup: false });
    openHistoryDialog(noticeBtn);
    if (STUDENT_APP_PUBLIC_MODE) await loadStudentBoard({ reset: true });
  });

  historyClose?.addEventListener('click', () => {
    closeHistoryDialog();
  });

  historyModal.addEventListener('click', (ev) => {
    if (ev.target === historyModal) closeHistoryDialog();
  });

  historyList?.addEventListener('click', (ev) => {
    const boardAction = ev.target.closest('[data-student-board-action]');
    if (boardAction) {
      void openStudentBoardItem(boardAction.dataset.studentBoardAction || '', boardAction);
      return;
    }
    const item = ev.target.closest('[data-ann-history-id]');
    if (!item) return;
    openHistoryAnnouncement(item.dataset.annHistoryId || '');
  });

  historyList?.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const item = ev.target.closest('[data-ann-history-id]');
    if (!item) return;
    ev.preventDefault();
    openHistoryAnnouncement(item.dataset.annHistoryId || '');
  });

  boardFilters?.addEventListener('click', (ev) => {
    const button = ev.target.closest('[data-student-board-type]');
    const selected = button?.dataset.studentBoardType;
    if (!['all', 'notice', 'video'].includes(selected) || selected === boardType) return;
    boardType = selected;
    void loadStudentBoard({ reset: true });
  });

  boardMore?.addEventListener('click', () => {
    if (!boardNextCursor || boardLoading) return;
    void loadStudentBoard();
  });

  annImagePrev?.addEventListener('click', (ev) => {
    ev.preventDefault();
    moveImageCarousel(-1);
  });

  annImageNext?.addEventListener('click', (ev) => {
    ev.preventDefault();
    moveImageCarousel(1);
  });

  annImageDots?.addEventListener('click', (ev) => {
    const dot = ev.target.closest('button');
    if (!dot) return;
    const dots = Array.from(annImageDots.querySelectorAll('button'));
    const index = dots.indexOf(dot);
    if (index >= 0) updateImageCarousel(index);
  });

  annImageCarousel?.addEventListener('pointerdown', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    ev.preventDefault();
    imagePointerActive = true;
    beginImageGesture(ev.clientX, ev.clientY);
    annImageCarousel.setPointerCapture?.(ev.pointerId);
  });

  annImageCarousel?.addEventListener('pointerup', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    annImageCarousel.releasePointerCapture?.(ev.pointerId);
    finishImageGesture(ev.clientX, ev.clientY, ev);
    window.setTimeout(() => {
      imagePointerActive = false;
    }, 0);
  });

  annImageCarousel?.addEventListener('mousedown', (ev) => {
    if (imagePointerActive || shouldIgnoreImageGestureTarget(ev.target)) return;
    ev.preventDefault();
    beginImageGesture(ev.clientX, ev.clientY);
  });

  annImageCarousel?.addEventListener('mouseup', (ev) => {
    if (imagePointerActive || shouldIgnoreImageGestureTarget(ev.target)) return;
    finishImageGesture(ev.clientX, ev.clientY, ev);
  });

  annImageCarousel?.addEventListener('touchstart', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    const touch = ev.touches?.[0];
    if (!touch) return;
    beginImageGesture(touch.clientX, touch.clientY);
  }, { passive: true });

  annImageCarousel?.addEventListener('touchend', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    const touch = ev.changedTouches?.[0];
    if (!touch) return;
    finishImageGesture(touch.clientX, touch.clientY, ev);
  });

  annImageCarousel?.addEventListener('click', (ev) => {
    if (!imagePointerMoved) return;
    ev.preventDefault();
    ev.stopPropagation();
    imagePointerMoved = false;
  }, true);

  annImageCarousel?.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
    ev.preventDefault();
    moveImageCarousel(ev.key === 'ArrowLeft' ? -1 : 1);
  });

  modal.addEventListener('keydown', (ev) => {
    trapDialogFocus(modal, ev);
    if (ev.key !== 'Escape' || (!activeFromHistory && !isComplete(active))) return;
    ev.preventDefault();
    closeAnnouncementDialog();
    active = null;
    activeFromHistory = false;
  });

  historyModal.addEventListener('keydown', (ev) => {
    trapDialogFocus(historyModal, ev);
    if (ev.key !== 'Escape') return;
    ev.preventDefault();
    closeHistoryDialog();
  });

  modal.addEventListener('click', (ev) => {
    if (ev.target === modal) ackActive();
  });

  annRead.addEventListener('click', ackActive);
  annSendReply?.addEventListener('click', submitReply);
  annSurveySubmit?.addEventListener('click', submitSurvey);
  annSurveyQuestions?.addEventListener('input', () => {
    if (annSurveyError) annSurveyError.textContent = '';
    annSurveyQuestions.querySelectorAll('.is-invalid').forEach(field => field.classList.remove('is-invalid'));
  });
  annSurveyQuestions?.addEventListener('change', () => {
    if (annSurveyError) annSurveyError.textContent = '';
    annSurveyQuestions.querySelectorAll('.is-invalid').forEach(field => field.classList.remove('is-invalid'));
  });
  annReply?.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
      ev.preventDefault();
      submitReply();
    }
  });

  void loadAnnouncements({ showPopup: !requestedBoardId }).then(async () => {
    if (!requestedBoardId) return;
    openHistoryDialog(noticeBtn);
    const found = await loadStudentBoard({ reset: true, seekId: requestedBoardId });
    const item = found ? boardItemByIdentifier(requestedBoardId) : null;
    if (item?.type === 'notice') await openStudentBoardItem(item.id, noticeBtn);
  });
  window.setInterval(() => {
    if (!document.hidden) loadAnnouncements({ showPopup: !active });
  }, 30000);
})();
