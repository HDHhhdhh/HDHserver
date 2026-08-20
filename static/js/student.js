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

function studentAppQueryFeatureGates(publicMode, search) {
  if (publicMode === true) return Object.freeze({ ocrEnabled: false, freshPhase2E: false, qaDate: '' });
  const params = new URLSearchParams(String(search || ''));
  const ocrEnabled = params.get('ocr') === '1';
  const requestedDate = ocrEnabled ? String(params.get('qaDate') || '').trim() : '';
  return Object.freeze({
    ocrEnabled,
    freshPhase2E: ocrEnabled && params.get('freshPhase2E') === '1',
    qaDate: /^\d{4}-\d{2}-\d{2}$/.test(requestedDate) ? requestedDate : '',
  });
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

function studentAppClassifySubmitFailure(error) {
  const status = Number(error?.status) || 0;
  const code = String(error?.code || '').trim().toLowerCase();
  const academyOnly = status === 403 || [
    'academy_only',
    'academy_network_required',
    'academy_required',
    'network_forbidden',
  ].includes(code);
  return Object.freeze({
    state: academyOnly ? 'academy_only' : 'retry',
    message: academyOnly
      ? '테스트 제출은 학원 Wi-Fi에서만 가능합니다.'
      : '테스트를 제출하지 못했습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.',
  });
}

async function studentAppResolveSubmitFailure({ publicMode, error, runLegacyFallback }) {
  const failure = studentAppClassifySubmitFailure(error);
  if (publicMode === true) return Object.freeze({ ...failure, mayUseLegacyFallback: false });
  if (typeof runLegacyFallback === 'function') await runLegacyFallback(error);
  return Object.freeze({ ...failure, mayUseLegacyFallback: true });
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
const STUDENT_APP_QUERY_FEATURES = studentAppQueryFeatureGates(STUDENT_APP_PUBLIC_MODE, location.search);
window.__OCR_TEST_SHEET_ENABLED__ = STUDENT_APP_QUERY_FEATURES.ocrEnabled;
window.__OCR_QA_DATE__ = STUDENT_APP_QUERY_FEATURES.qaDate;
const OCR_PHASE1_ALLOWED_TEST_IDS = new Set([
  't_unit_daesu_01_lv3_r1',
  't_unit_daesu_02_lv3_r1',
  't_unit_mijeok1_01_lv3_r1',
]);
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

function isOcrPhase1AllowedTestId(testId) {
  const normalized = String(testId || '').trim();
  return OCR_PHASE1_ALLOWED_TEST_IDS.has(normalized) || /^t_unit_[a-z0-9_]+_r[123]$/i.test(normalized) || /^t_training_pack_[a-z0-9_]+_r[12]$/i.test(normalized);
}

function isOcrPhase1AllowedTest(test) {
  const testId = test?.id || test?.testId;
  if (isOcrPhase1AllowedTestId(testId)) return true;
  const categoryKey = String(test?.categoryKey || test?.category || '').trim().toUpperCase();
  const categoryLabel = String(test?.categoryLabel || test?.label || '').trim();
  const problems = Number(test?.problems);
  const trainingPackLike = categoryKey === 'TRAINING_PACK' || categoryLabel.includes('트레이닝팩') || categoryLabel.includes('트팩');
  const unitLike = categoryKey === 'UNIT' || categoryLabel.includes('단원') || trainingPackLike;
  const roundMatch = String(test?.round || '').trim().match(trainingPackLike ? /^([12])(?:\D|$)/ : /^([123])(?:\D|$)/);
  const twentyProblems = !Number.isFinite(problems) || problems === 20;
  return unitLike && twentyProblems && Boolean(roundMatch);
}
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
    return window.__OCR_QA_DATE__ || todayLocalKey();
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
  const reviewSelection = new Set(); // chooser-only checked MIDs waiting for server registration
  let registeredReviewMids = []; // ordered, SID/date-scoped server-confirmed selections
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
  let testSubmissionBlocked = STUDENT_APP_PUBLIC_MODE;
  let reviewVideosMalformed = false;
  let ghostStudent = false;
  let announcementPendingCount = null;
  const COURSE_VIDEOS_COMPLETED_MESSAGE = "오늘 영상 진도를 모두 마쳤습니다. 추가 영상이 필요하면 학원에 문의해 주세요.";
  window.__ASSIGNED_TESTS__ = [];
  window.__STUDENT_ACCESS__ = {
    academyAccessAllowed,
    outsideAcademyBlocked: !academyAccessAllowed,
    testSubmissionBlocked,
    message: academyOnlyMessage,
  };

  function publishStudentAccess() {
    window.__STUDENT_ACCESS__ = {
      academyAccessAllowed,
      outsideAcademyBlocked: !academyAccessAllowed,
      testSubmissionBlocked,
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
    const updatedAt = Math.max(0, Number(entry.updatedAt) || 0);
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
        updatedAt: next.updatedAt | 0,
      });
    });

    try { updateListCompletionBadges(); } catch { }
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
      updatedAt: (prog.updatedAt | 0) || now
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
        testSubmissionBlocked: b.testSubmissionBlocked === true || (STUDENT_APP_PUBLIC_MODE && !academyAllowed),
        dashboard: b.dashboard && typeof b.dashboard === 'object' ? b.dashboard : null,
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

    try {
      const q = new URLSearchParams({ sid: String(sid), date: today }).toString();
      const res = await fetch(`/api/student/bootstrap?${q}`, { cache: 'no-store' });
      if (res.ok) {
        const b = await res.json();
        return bootstrapInitialData(b, await watchReq);
      }
      if (res.status !== 404) throw new Error(`bootstrap ${res.status}`);
    } catch (err) {
      console.warn('[student] bootstrap failed, using legacy load:', err);
    }

    return Promise.all([
      fetch("/api/students").then(r => r.json()),
      fetch("/api/videos").then(r => r.json()),
      fetch("/api/updates").then(r => r.json()).catch(() => ({})),
      fetch("/api/materials").then(r => r.json()).catch(() => ({})),
      fetch("/api/mat-assign").then(r => r.json()).catch(() => ({})),
      fetch("/api/absent").then(r => r.json()).catch(() => ({})),
      fetch(`/api/logs?date=${encodeURIComponent(today)}`).then(r => r.json()).catch(() => ({})),
      watchReq,
      {
        courseBlocked: false,
        selfStudy: false,
        blockMessage: '',
        courseVideosCompleted: false,
        academyAccessAllowed: true,
        academyOnlyMessage: '',
        assignedTests: [],
        homeworkBooks: [],
        reviewVideos: [],
        reviewVideosMalformed: false,
        ghostStudent: false,
        dashboard: null,
      },
    ]);
  }

  loadInitialData().then(init).catch(err => {
    if (handleStudentAppSessionFailure(err)) return;
    alert("데이터 로드 실패\n" + err);
  });

  /* ───────────── 자동배정 헬퍼 ───────────── */

  // 오늘 요일 기준으로 정규 수업 있는지
  function hasRegularToday(stu, todayStr) {
    if (!stu) return false;
    const wchr = '일월화수목금토'[new Date(todayStr).getDay()];
    const vals = Object.keys(stu)
      .filter(k => /^day\d+$/.test(k) && stu[k])
      .map(k => String(stu[k]));
    return vals.some(v => String(v).startsWith(wchr));
  }

  // /api/absent 응답에서 by_date 부분만 뽑기
  function normalizeAbsentByDate(payload) {
    if (!payload || typeof payload !== 'object') return {};
    if (payload.by_date && typeof payload.by_date === 'object') return payload.by_date;
    if (payload.byDate && typeof payload.byDate === 'object') return payload.byDate;
    return payload;
  }

  // “오늘 학생표 기준으로 자동배정 허용해도 되는지” 판단
  function isAllowedTodayForAutoAssign(sidVal, today) {
    if (!stuCache) return false;
    const sidStr = String(sidVal);

    // 1) 오늘 요일에 정규 수업이 있어야 함
    if (!hasRegularToday(stuCache, today)) return false;

    // 2) 결석 리스트에 있으면 안 됨
    const absList = (absentByDateCache[today] || []);
    const absSet = new Set(absList.map(String));
    if (absSet.has(sidStr)) return false;

    // 3) 오늘 로그가 done=true면 자유의 몸 → 안 됨
    // 3) 오늘 로그가 archived=true면 안 됨 (done은 허용!)
    const logsToday = (logsCache || {})[today] || {};
    const entry = logsToday[sidStr] || logsToday[sidVal] || {};
    const archived = entry.archived === true || entry.archived === 'true';
    if (archived) return false;

    return true;

  }

  // updates 전체에서 이 sid의 "마지막 배정" 찾기 (sid 키 숫자/문자 둘 다 허용)
  function getLastAssignedVideosForSid(sidVal, updatesObj) {
    const sidStr = String(sidVal);
    const sidNum = Number.isFinite(+sidVal) ? String(+sidVal) : null;
    const days = Object.keys(updatesObj || {}).sort();
    for (let i = days.length - 1; i >= 0; i--) {
      const day = days[i];
      const perDay = updatesObj[day] || {};
      const raw = perDay[sidStr] ?? (sidNum != null ? perDay[sidNum] : undefined);
      if (!raw) continue;
      if (Array.isArray(raw)) return raw.slice();
      if (raw && Array.isArray(raw.videos)) return raw.videos.slice();
    }
    return null;
  }

  // “오늘 학생표에 있는 애”만 자동 배정 (자동배정 로직 내부에서만 today 허용 체크)
  async function ensureTodayAssignmentIfMissing() {
    if (STUDENT_APP_PUBLIC_MODE) return false;
    const today = todayLocalKey();
    const dayMap = updatesCache[today] || {};
    const sidStr = String(sid);
    const sidNum = Number.isFinite(+sid) ? String(+sid) : null;

    const rawToday = dayMap[sidStr] ?? (sidNum != null ? dayMap[sidNum] : undefined);
    const hasToday = Array.isArray(rawToday)
      ? rawToday.length > 0
      : Array.isArray(rawToday?.videos)
        ? rawToday.videos.length > 0
        : (rawToday !== undefined); // 혹시라도 값만 있으면 "있다"로 간주

    if (hasToday) return false;

    // 오늘 학생표 대상이 아니면 자동 배정 금지 (수동 배정은 보여줘야 함)
    if (!isAllowedTodayForAutoAssign(sid, today)) return false;

    const last = getLastAssignedVideosForSid(sid, updatesCache);
    if (!last || !last.length) return false;

    const nextUpdates = { ...(updatesCache || {}) };
    const todayMap = { ...(nextUpdates[today] || {}) };
    todayMap[sidStr] = last.map(String);
    nextUpdates[today] = todayMap;

    await fetch('/api/updates/patch', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify({ date: today, sid: sidStr, videos: last.map(String) })
    });

    updatesCache = nextUpdates;
    return true;
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
      if (!mid || (reviewStatus !== 'done' && reviewStatus !== 'interrupted') || seen.has(mid)) return;
      seen.add(mid);
      normalized.push({ ...item, mid, reviewStatus });
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
    summary.textContent = '복습할 영상을 선택한 뒤 영상 등록을 누르세요';
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
      if (restricted) row.setAttribute('aria-disabled', 'true');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.dataset.mid = item.mid;
      checkbox.checked = registered || reviewSelection.has(item.mid);
      checkbox.disabled = registered || restricted;
      checkbox.setAttribute('aria-label', registered ? `${title.textContent} 등록됨` : title.textContent);
      if (registered) checkbox.setAttribute('data-registered', 'true');
      checkbox.addEventListener('change', () => {
        if (registered) {
          checkbox.checked = true;
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
    const openBtn = $('openTestSubmit');
    const hasTests = assignedTestsCache.length > 0;
    const canOpenOcrQaSubmit = window.__OCR_TEST_SHEET_ENABLED__ === true && !testSubmissionBlocked;
    const submissionBlocked = testSubmissionBlocked || (hasTests && assignedTestsCache.every(test => test?.submissionRestricted === true));

    if (openBtn) openBtn.hidden = (!hasTests && !canOpenOcrQaSubmit) || submissionBlocked;
    if (panel) panel.hidden = !hasTests;
    if (!hasTests || !list) return;

    list.textContent = '';
    assignedTestsCache.forEach(test => {
      const li = document.createElement('li');
      const answerUrl = assignedTestAnswerUrl(test);
      const answerRestricted = isAssignedTestAnswerRestricted(test, answerUrl);
      const canOpenAnswerUrl = canOpenAssignedTestAnswer(answerUrl);
      const ocrPhase1Allowed = isOcrPhase1AllowedTest(test);
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
      if (window.__OCR_TEST_SHEET_ENABLED__ === true && ocrPhase1Allowed) {
        btn.addEventListener('click', event => {
          event.preventDefault();
          event.stopPropagation();
          if (answerRestricted) {
            showAcademyOnlyNotice();
            return;
          }
          if (typeof window.ocrTestSheetStartCapture === 'function') {
            window.ocrTestSheetStartCapture(test);
            return;
          }
          if (typeof window.openAssignedTestSubmit === 'function') {
            window.openAssignedTestSubmit(test.id || test.label || '');
          }
        });
      } else if (!canOpenAnswerUrl) {
        btn.addEventListener('click', () => {
          if (answerRestricted) {
            showAcademyOnlyNotice();
            return;
          }
          const openSubmit = () => {
            if (typeof window.openAssignedTestSubmit === 'function') {
              window.openAssignedTestSubmit(test.id || test.label || '');
            }
          };
          if (typeof window.openAssignedTestAnswerLink === 'function') {
            Promise.resolve(window.openAssignedTestAnswerLink(test))
              .then(opened => { if (!opened) openSubmit(); })
              .catch(() => openSubmit());
            return;
          }
          openSubmit();
        });
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
      access.textContent = academyAccessAllowed ? '' : '영상 재생과 테스트 제출은 학원에서 이용할 수 있습니다.';
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
    testSubmissionBlocked = bootstrapMeta?.testSubmissionBlocked === true || (STUDENT_APP_PUBLIC_MODE && !academyAccessAllowed);
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

    // ❌ archived이면 오늘 영상 표시 금지 (done 여부와 무관)
    {
      const logsToday = (logsCache || {})[today] || {};
      const entry = logsToday[String(sid)] || logsToday[sid] || {};
      const archived = entry.archived === true || entry.archived === 'true';
      if (archived) {
        if (listBox) listBox.innerHTML = "<li style='opacity:.65'>오늘 영상이 없습니다</li>";
        setPlayerEmptyState('오늘 영상이 없습니다');
        return;
      }
    }


    // 🔐 여기서는 "오늘 학생 여부"로 막지 않는다.
    //     현재 진도가 완료인 영상은 서버·로컬 상태에서 목록에서 숨긴다.
    //     서버가 제외한 영상도 현재 목록에 내려보내지 않는다.
    //     중단 영상은 이어볼 수 있도록 현재 목록에 남긴다.
    const chosen = getAssignedVideos(updatesCache, today, sid);
    const chosenStrs = new Set(chosen.map(String));

    // ✅ [중요] mid/id 불일치로 비는 경우 방지: (mid || id)로 매칭
    let myVids = (vidsCache || []).filter(v => {
      const kMid = String(v?.mid ?? '');
      const kId = String(v?.id ?? '');
      const playlistMid = (kMid || kId).trim();
      return ((kMid && chosenStrs.has(kMid)) || (kId && chosenStrs.has(kId)))
        && !getProgress(playlistMid)?.completed;
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
        const num = isRegisteredReview ? '' : (v.exNum?.[essayBandOf(stuCache.level)] || '');
        const mid = String(v?.mid ?? v?.id ?? '').trim();
        const prog = getProgress(mid);
        const done = prog?.completed;
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
    listBox.querySelectorAll('li[data-mid]').forEach(li => {
      const mid = li.dataset.mid;
      const prog = getProgress(mid);
      const done = prog?.completed;
      if (done && li.dataset.reviewRegistered !== 'true') shouldRefreshPlaylist = true;
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

/* ─────────────────────────────────────────────
 * 학생 제출용: 테스트 성적 제출 모달  (회차 1~3 + 서버 자동 채점)
 *  - tests-config.json:
 *    test.answerKeys = { "1":[...], "2":[...], "3":[...] }
 *  - 학생 제출:
 *    POST /api/submit-test { sid, testId, round, answersText, memo }
 *    -> 서버가 회차별 정답으로 채점하고 score/wrong/pct 저장
 *  - 서버가 아직 구버전이면(채점 실패) 클라에서 fallback 채점 후 기존 방식으로 저장
 * ────────────────────────────────────────────*/
(() => {
  const CT = { 'Content-Type': 'application/json' };
  const OCR_TEST_SHEET_ENABLED = window.__OCR_TEST_SHEET_ENABLED__ === true;
  const OCR_PHASE2B_REVIEW_ENDPOINT = '/api/ocr-test-sheet-review';
  const OCR_PHASE2E_FRESH_REVIEW_REQUESTED = STUDENT_APP_QUERY_FEATURES.freshPhase2E;
  const OCR_PHASE1_INELIGIBLE_MESSAGE = '이 시험은 아직 사진 인식 테스트 대상이 아닙니다.';
  const OCR_PHASE2B_MAX_IMAGE_BYTES = 8 * 1024 * 1024;
  const OCR_PHASE2B_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
  const OCR_PHASE2B_IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp']);
  const OCR_REVIEW_PROBLEM_COUNT = 20;
  const OCR_REVIEW_FINAL_STATUSES = new Set([
    'safe_auto_grade',
    'auto_confirm',
    'confirmed',
    'student_confirmed',
    'student_edited',
    'student_entered',
    'student_selected_candidate',
    'student_direct_input',
    'safe_auto_grade_after_retake',
    'student_selected_candidate_after_retake',
    'student_direct_input_after_retake',
  ]);
  const OCR_REVIEW_AUTO_GRADE_STATUSES = new Set([
    'safe_auto_grade',
    'safe_auto_grade_after_retake',
  ]);
  const OCR_REVIEW_BLOCKING_STATUSES = new Set([
    'review_required',
    'retake_required',
    'retake_uploaded',
    'data_check_required',
  ]);
  const OCR_REVIEW_SELF_REVIEW_STATES = new Set([
    'auto_confirm',
    'review_recommended',
    'direct_input',
    'retake_required',
  ]);
  const OCR_REVIEW_RESOLVED_STATES = new Set([
    'auto_confirm',
    'student_confirmed',
    'student_edited',
    'student_entered',
  ]);
  const OCR_REVIEW_LOCAL_CANDIDATE_SOURCES = new Set([
    'phase2f_local_paddle_ocr',
  ]);
  const OCR_REVIEW_TRACE_WARNING_CODES = new Set([
    'erased_trace_detected',
    'crossed_out_answer',
    'overwritten_answer',
    'multiple_answer_candidates',
    'unclear_final_answer',
    'arrow_equal_confusion',
    'relation_symbol_confusion',
    'expression_operator_confusion',
    'choice_number_invalid_for_auto_grade',
    'answer_value_letter_confusion',
    'digit_shape_confusion',
    'answer_mode_unverified',
    'local_checker_blank_conflict',
    'local_checker_candidate_conflict',
    'tesseract_blank_like',
    'tesseract_choice_digit_veto',
    'tesseract_multiple_choice_candidates',
    'tesseract_multiple_candidates',
    'tesseract_answer_value_format_conflict',
    'tesseract_candidate_conflict',
    'paddleocr_candidate_conflict',
    'pix2tex_candidate_conflict',
    'local_ocr_unverified',
    'local_ocr_low_confidence',
  ]);
  const OCR_REVIEW_BULK_FILL_BLOCKING_WARNING_CODES = new Set([
    'erased_trace_detected',
    'crossed_out_answer',
    'overwritten_answer',
    'multiple_answer_candidates',
    'unclear_final_answer',
    'arrow_equal_confusion',
    'relation_symbol_confusion',
    'expression_operator_confusion',
    'choice_number_invalid_for_auto_grade',
    'answer_value_letter_confusion',
    'digit_shape_confusion',
    'answer_mode_unverified',
    'local_checker_blank_conflict',
    'local_checker_candidate_conflict',
    'tesseract_blank_like',
    'tesseract_choice_digit_veto',
    'tesseract_multiple_choice_candidates',
    'tesseract_multiple_candidates',
    'tesseract_answer_value_format_conflict',
    'tesseract_candidate_conflict',
    'paddleocr_candidate_conflict',
    'pix2tex_candidate_conflict',
  ]);
  const SUBMIT_OFFSET_GUARD_MIN_PROBLEMS = 10;
  const SUBMIT_OFFSET_GUARD_MIN_SHIFTED_RATIO = 0.6;
  const SUBMIT_OFFSET_GUARD_MIN_DELTA = 5;
  const OCR_REVIEW_WARNING_MESSAGES = {
    erased_trace_detected: '지운 흔적 또는 덧쓴 흔적이 있어 확인이 필요합니다.',
    crossed_out_answer: '지운 흔적 또는 덧쓴 흔적이 있어 확인이 필요합니다.',
    overwritten_answer: '지운 흔적 또는 덧쓴 흔적이 있어 확인이 필요합니다.',
    crop_quality_too_small: '답칸이 너무 작게 잡혀 다시 촬영하는 편이 안전합니다.',
    crop_quality_blurry: '답칸이 흐려 다시 촬영하는 편이 안전합니다.',
    crop_quality_exposure: '사진 밝기가 불안정해 다시 촬영하는 편이 안전합니다.',
    crop_quality_low_contrast: '답칸 대비가 낮아 다시 촬영하는 편이 안전합니다.',
    crop_quality_blank_like: '답칸이 빈칸처럼 보여 직접 확인이 필요합니다.',
    crop_quality_cutoff_risk: '답칸이 잘렸을 가능성이 있어 다시 촬영하는 편이 안전합니다.',
    multiple_answer_candidates: '여러 답안 흔적이 보여 확인이 필요합니다.',
    unclear_final_answer: '최종 답이 명확하지 않아 확인이 필요합니다.',
    arrow_equal_confusion: '화살표와 등호가 애매해 직접 확인이 필요합니다.',
    relation_symbol_confusion: '부등호 또는 등호가 애매해 직접 확인이 필요합니다.',
    expression_operator_confusion: '식의 연산 기호가 애매해 직접 확인이 필요합니다.',
    choice_number_invalid_for_auto_grade: '선택형 문항은 선지 번호(1~5)만 입력할 수 있어 확인이 필요합니다.',
    answer_value_letter_confusion: '답값이 글자처럼 보여 직접 확인이 필요합니다.',
    digit_shape_confusion: '숫자 모양이 애매해 직접 확인이 필요합니다.',
    answer_mode_unverified: '이 시험은 문항 형식표가 아직 없어 직접 확인이 필요합니다.',
    local_checker_blank_conflict: '보조 인식에서는 빈칸처럼 보여 직접 확인이 필요합니다.',
    local_checker_candidate_conflict: '서로 다른 인식 후보가 보여 직접 확인이 필요합니다.',
    tesseract_blank_like: '보조 인식에서는 빈칸처럼 보여 직접 확인이 필요합니다.',
    tesseract_choice_digit_veto: '보조 인식 결과 선지 번호가 명확하지 않아 직접 확인이 필요합니다.',
    tesseract_multiple_choice_candidates: '보조 인식에서 선지 후보가 여러 개 보여 직접 확인이 필요합니다.',
    tesseract_multiple_candidates: '보조 인식에서 답 후보가 여러 개 보여 직접 확인이 필요합니다.',
    tesseract_answer_value_format_conflict: '보조 인식 결과 답값 형식이 맞지 않아 직접 확인이 필요합니다.',
    tesseract_candidate_conflict: '서로 다른 인식 후보가 보여 직접 확인이 필요합니다.',
    paddleocr_candidate_conflict: '서로 다른 인식 후보가 보여 직접 확인이 필요합니다.',
    pix2tex_candidate_conflict: '서로 다른 수식 인식 후보가 보여 직접 확인이 필요합니다.',
    local_ocr_unverified: '사진에서 읽은 인식 후보입니다. 답안지와 비교한 뒤 확정해주세요.',
    local_ocr_low_confidence: '인식 후보가 불확실해 직접 확인이 필요합니다.',
    auto_confirm_policy_unverified: '자동 인식 근거를 확인할 수 없어 직접 확인이 필요합니다.',
  };
  const OCR_REVIEW_WARNING_LABELS = {
    erased_trace_detected: '지운 흔적',
    crossed_out_answer: '취소 흔적',
    overwritten_answer: '덧쓴 흔적',
    crop_quality_too_small: '답칸이 작음',
    crop_quality_blurry: '흐림',
    crop_quality_exposure: '노출 불안정',
    crop_quality_low_contrast: '대비 낮음',
    crop_quality_blank_like: '빈칸처럼 보임',
    crop_quality_cutoff_risk: '답칸 잘림 위험',
    multiple_answer_candidates: '후보 여러 개',
    unclear_final_answer: '최종 답 불명확',
    arrow_equal_confusion: '화살표/등호 애매',
    relation_symbol_confusion: '부등호/등호 애매',
    expression_operator_confusion: '연산 기호 애매',
    choice_number_invalid_for_auto_grade: '선지 형식 확인',
    answer_value_letter_confusion: '답값 글자 혼동',
    digit_shape_confusion: '숫자 모양 애매',
    answer_mode_unverified: '문항 형식 미확인',
    local_checker_blank_conflict: '보조 인식 빈칸 충돌',
    local_checker_candidate_conflict: '보조 인식 불일치',
    tesseract_blank_like: '보조 인식 빈칸 충돌',
    tesseract_choice_digit_veto: '선지 번호 불명확',
    tesseract_multiple_choice_candidates: '선지 후보 여러 개',
    tesseract_multiple_candidates: '답 후보 여러 개',
    tesseract_answer_value_format_conflict: '답 형식 충돌',
    tesseract_candidate_conflict: '보조 인식 불일치',
    paddleocr_candidate_conflict: '보조 인식 불일치',
    pix2tex_candidate_conflict: '수식 인식 불일치',
    local_ocr_unverified: '인식 후보 · 확인 필요',
    local_ocr_low_confidence: '인식 후보 불확실',
    auto_confirm_policy_unverified: '자동 인식 근거 미확인',
  };
  const OCR_REVIEW_ANSWER_KEY_FIELDS = new Set([
    ['exp', 'ected'].join(''),
    ['canonical', 'answer'].join('_'),
    ['accepted', 'answers'].join('_'),
    'answer_key',
    'correct',
    'is_correct',
    'incorrect',
    'score',
    'wrong',
    'pct',
    'grading',
    'student_name',
    'studentName',
    'student_id',
    'studentId',
    'sid',
    'memo',
    'path',
    'file_path',
    'local_path',
    'artifact_path',
    'provider_response',
    'provider_raw_response',
    'raw_provider_response',
    'raw_response',
  ]);
  const OCR_REVIEW_PRIMARY_KEYPAD_VALUES = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '-', '/'];
  const OCR_PHASE1_ANSWER_MODE_BY_TEST_ID = {
    t_unit_daesu_01_lv3_r1: {
      choice_number: new Set([1, 3, 5, 9, 13, 14, 17, 19]),
      answer_value: new Set([2, 4, 6, 7, 8, 10, 11, 12, 15, 16, 18, 20]),
    },
    t_unit_daesu_02_lv3_r1: {
      choice_number: new Set([3, 6, 7, 9, 10, 11, 15, 20]),
      answer_value: new Set([1, 2, 4, 5, 8, 12, 13, 14, 16, 17, 18, 19]),
    },
  };
  const OCR_REVIEW_ANSWER_MODE_LABELS = {
    choice_number: '선택형 · 번호만 입력',
    answer_value: '답값형 · 최종 답 입력',
  };
  const TEST_TYPE_OPTIONS = [
    { value: 'UNIT', label: '단원평가', keys: ['UNIT', '단원평가'] },
    { value: 'TRAINING_PACK', label: '트레이닝팩', keys: ['TRAINING_PACK', '트레이닝팩', '트팩'] },
    { value: 'REVIEW', label: '복습 테스트', keys: ['REVIEW'] },
    { value: 'SCHOOL_PAST', label: '학군지 기출', keys: ['SCHOOL_PAST'] },
    { value: 'ILSAN_PAST', label: '일산 기출', keys: ['ILSAN_PAST'] },
    { value: 'FINAL', label: 'APEX FINAL', keys: ['FINAL'] },
    { value: 'HELL', label: 'APEX HELL', keys: ['HELL'] },
  ];
  let TEST_ANSWER_LINK_MAP = {};
  let answerLinkMapPromise = null;
  let answerLinkMapLoaded = false;

  // 공개 앱은 URL/query가 아니라 세션 adapter의 active SID만 전송한다.
  const sid = STUDENT_APP_PUBLIC_MODE ? '' : (window.__STU_SID__ || (() => {
    const lastSeg = decodeURIComponent(location.pathname.split("/").pop() || "");
    const q = new URLSearchParams(location.search);
    return q.get("sid") || lastSeg || "";
  })());
  const currentStudentSid = () => STUDENT_APP_PUBLIC_MODE ? STUDENT_APP_PUBLIC_SESSION.activeSid() : sid;

  function studentAnswerAccessBlocked() {
    const access = window.__STUDENT_ACCESS__ || {};
    return access.academyAccessAllowed === false || access.outsideAcademyBlocked === true;
  }

  function studentTestSubmissionBlocked() {
    const access = window.__STUDENT_ACCESS__ || {};
    return access.testSubmissionBlocked === true
      || (STUDENT_APP_PUBLIC_MODE && access.academyAccessAllowed !== true);
  }

  function showStudentTestSubmissionBlockedNotice() {
    if (STUDENT_APP_PUBLIC_MODE && studentAnswerAccessBlocked()) {
      showStudentAccessNotice();
      return;
    }
    alert('테스트용 학생 페이지에서는 제출 기록을 저장하지 않습니다.');
  }

  function showStudentAccessNotice() {
    const access = window.__STUDENT_ACCESS__ || {};
    if (typeof access.showNotice === 'function') {
      access.showNotice();
      return;
    }
    alert(access.message || '영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다.');
  }

  async function fetchJSONSafe(url, init = {}) {
    const res = await studentAppRequest(url, { cache: "no-store", ...init });
    const body = await res.text();
    if (!res.ok) throw new Error(`[student tests] ${init.method || "GET"} ${url} -> ${res.status}\n${body.slice(0, 300)}`);
    try { return body.trim() ? JSON.parse(body) : {}; }
    catch (e) { throw new Error(`[student tests] Bad JSON from ${url}: ${e?.message}\n${body.slice(0, 300)}`); }
  }

  function todayLocalKey() {
    const now = new Date();
    const tz = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - tz).toISOString().slice(0, 10);
  }

  // ✅ DOM에서 "(공수1)" 같은 커리 텍스트를 파싱해서 필터용으로만 씀
  function getMyCurriculumFromNamebar() {
    const el = document.getElementById('stuName');
    const s = (el?.textContent || '').trim();
    const m = s.match(/\(([^)]+)\)\s*$/);
    return m ? m[1].trim() : '';
  }

  function getAssignedTestsForSubmit() {
    const assigned = Array.isArray(window.__ASSIGNED_TESTS__) ? window.__ASSIGNED_TESTS__ : [];
    if (assigned.length) return assigned;
    if (!OCR_TEST_SHEET_ENABLED) return [];
    return allConfiguredTests()
      .filter(test => isOcrPhase1AllowedTest(test))
      .map(test => ({
        id: test.id,
        sourceId: test.sourceId,
        name: test.name,
        label: test.name,
        categoryKey: test.categoryKey,
        categoryLabel: test.categoryLabel,
        curriculum: test.curriculum,
        difficulty: test.difficulty,
        round: test.round,
      }));
  }

  function assignedRound(value) {
    const raw = String(value || '').trim();
    const m = raw.match(/(\d{1,2})/);
    return m ? m[1] : raw;
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

  function typeLabel(typeVal) {
    return TEST_TYPE_OPTIONS.find(opt => opt.value === typeVal || opt.keys.includes(typeVal))?.label || typeVal || '';
  }

  // ───────────── tests-config 로드/정규화 ─────────────
  let TEST_CFG = { categories: {} };

  function normalizeCfg(x) {
    const cfg = (x && typeof x === 'object') ? x : {};
    if (!cfg.categories || typeof cfg.categories !== 'object') cfg.categories = {};

    for (const [k, v] of Object.entries(cfg.categories)) {
      const cat = cfg.categories[k] = (v && typeof v === 'object') ? v : {};
      cat.label = (typeof cat.label === 'string' && cat.label.trim()) ? cat.label : k;
      if (!Array.isArray(cat.tests)) cat.tests = [];

      cat.tests = cat.tests.map(t => {
        if (!t || typeof t !== 'object') return null;
        const id = String(t.id || '').trim();
        const name = String(t.name || '').trim();
        if (!id || !name) return null;

        const problems = Number.isFinite(+t.problems) ? Math.max(1, +t.problems) : 20;
        const curriculum = String(t.curriculum || '').trim() || '';
        const difficulty = String(t.difficulty || t.level || '').trim() || '';
        const round = String(t.round || t.session || t.no || '1').trim() || '1';

        // ✅ 새 스키마
        const answerKeys = (t.answerKeys && typeof t.answerKeys === 'object') ? t.answerKeys : null;
        // ✅ 구 스키마(혹시 남아있으면 fallback 용)
        const answerKey = t.answerKey ?? t.answers ?? null;

        return {
          id,
          sourceId: String(t.sourceId || t.source_id || '').trim(),
          name,
          problems,
          curriculum,
          difficulty,
          round,
          categoryKey: String(k || '').trim(),
          categoryLabel: cat.label,
          answerKeys,
          answerKey,
          sourceFiles: (t.sourceFiles && typeof t.sourceFiles === 'object') ? t.sourceFiles : null,
          answerUrl: String(t.answerUrl || t.answer_url || t.solutionUrl || t.solution_url || '').trim(),
          solutionFileId: String(t.solutionFileId || t.solution_file_id || '').trim(),
        };
      }).filter(Boolean);
    }
    return cfg;
  }

  async function loadTestsConfig() {
    // /api/tests-config 가 정석. 혹시 없으면 예전처럼 파일로도 한번 시도.
    try {
      TEST_CFG = normalizeCfg(await fetchJSONSafe('/api/tests-config'));
      return;
    } catch { }
    if (STUDENT_APP_PUBLIC_MODE) {
      TEST_CFG = { categories: {} };
      return;
    }
    try {
      TEST_CFG = normalizeCfg(await fetchJSONSafe('/api/tests-config.json'));
    } catch {
      TEST_CFG = { categories: {} };
    }
  }

  let testsConfigPromise = null;
  function ensureTestsConfigLoaded() {
    if (!testsConfigPromise) {
      testsConfigPromise = loadTestsConfig();
    }
    return testsConfigPromise;
  }

  function resolveCategoryKeysByType(typeVal) {
    const hits = [];
    const option = TEST_TYPE_OPTIONS.find(opt => opt.value === typeVal || opt.keys.includes(typeVal));
    for (const [key, cat] of Object.entries(TEST_CFG.categories || {})) {
      const label = String(cat.label || '').trim();
      const k = String(key || '').trim().toUpperCase();
      const lv = label.toUpperCase();

      if (option) {
        if (option.keys.some(rawKey => k === String(rawKey).toUpperCase())) hits.push(key);
        else if (option.keys.some(rawKey => lv.includes(String(rawKey).toUpperCase()))) hits.push(key);
        else if (option.label && label.includes(option.label.replace('APEX ', ''))) hits.push(key);
      } else if (typeVal === '단원평가') {
        if (lv.includes('단원') || lv.includes('UNIT') || k === 'UNIT') hits.push(key);
      } else if (typeVal === 'FINAL') {
        if (lv.includes('FINAL') || k === 'FINAL') hits.push(key);
      } else if (typeVal === 'HELL') {
        if (lv.includes('HELL') || k === 'HELL') hits.push(key);
      }
    }
    return hits;
  }

  function assignedMatchesTest(test) {
    const assigned = getAssignedTestsForSubmit();
    if (!assigned.length || !test) return false;
    return assigned.some(item => {
      const assignedId = String(item.id || item.testId || '').trim();
      if (assignedId && assignedId === String(test.id || '').trim()) return true;
      if (assignedId && assignedId === String(test.sourceId || test.source_id || '').trim()) return true;

      const itemName = String(item.name || item.testName || '').trim();
      const itemLabel = String(item.label || '').trim();
      const nameOk = itemName
        ? itemName === String(test.name || '').trim()
        : (itemLabel && itemLabel.includes(String(test.name || '').trim()));
      if (!nameOk) return false;

      const roundOk = !item.round || !test.round || assignedRound(item.round) === assignedRound(test.round);
      const curOk = !item.curriculum || !test.curriculum || String(item.curriculum) === String(test.curriculum);
      const itemDifficulty = normalizedTestDifficultyForCategory(test.categoryKey, assignedTestDifficultyLabel(item));
      const testDifficulty = normalizedTestDifficultyForCategory(test.categoryKey, test.difficulty);
      const diffOk = !itemDifficulty || !testDifficulty || itemDifficulty === testDifficulty;
      return roundOk && curOk && diffOk;
    });
  }

  function listTestsForType(typeVal, myCur) {
    const keys = resolveCategoryKeysByType(typeVal);
    const out = [];
    for (const k of keys) {
      const cat = TEST_CFG.categories[k];
      for (const t of (cat?.tests || [])) out.push(t);
    }

    const assigned = out.filter(assignedMatchesTest);
    if (!myCur) return assigned;

    const sameCurriculum = [];
    const otherCurriculum = [];
    assigned.forEach(test => {
      if (!test.curriculum || test.curriculum === myCur) sameCurriculum.push(test);
      else otherCurriculum.push(test);
    });
    return sameCurriculum.concat(otherCurriculum);
  }

  function findTestById(typeVal, testId, myCur) {
    const list = listTestsForType(typeVal, myCur);
    const id = String(testId || '').trim();
    return list.find(t =>
      String(t.id || '').trim() === id ||
      String(t.sourceId || t.source_id || '').trim() === id
    ) || null;
  }

  function listAssignedConfiguredTests(myCur) {
    const out = [];
    TEST_TYPE_OPTIONS.forEach(opt => {
      listTestsForType(opt.value, myCur).forEach(test => out.push(test));
    });
    return out;
  }

  function typeValueForTest(test) {
    const key = String(test?.categoryKey || '').trim().toUpperCase();
    const label = String(test?.categoryLabel || '').trim().toUpperCase();
    const hit = TEST_TYPE_OPTIONS.find(opt =>
      opt.keys.some(rawKey => key === String(rawKey).toUpperCase() || label.includes(String(rawKey).toUpperCase())) ||
      (opt.label && String(test?.categoryLabel || '').includes(opt.label.replace('APEX ', '')))
    );
    return hit?.value || 'UNIT';
  }

  function roundLabel(round) {
    const r = String(round || '').trim();
    return r ? (/회/.test(r) ? r : `${r}회차`) : '';
  }

  function findSiblingTestByRound(typeVal, test, round, myCur) {
    if (!test) return null;
    const targetRound = String(round || '').trim();
    return listTestsForType(typeVal, myCur).find(item =>
      String(item.name || '') === String(test.name || '') &&
      String(item.curriculum || '') === String(test.curriculum || '') &&
      String(item.difficulty || '') === String(test.difficulty || '') &&
      String(item.round || '') === targetRound
    ) || null;
  }

  function allConfiguredTests() {
    const out = [];
    Object.values(TEST_CFG.categories || {}).forEach(cat => {
      (cat?.tests || []).forEach(test => out.push(test));
    });
    return out;
  }

  function answerLinkCategoryLike(item, configuredTest = null) {
    const source = [
      item?.categoryKey,
      item?.category,
      item?.categoryLabel,
      item?.label,
      configuredTest?.categoryKey,
      configuredTest?.categoryLabel,
    ].map(v => String(v || '')).join(' ');
    return (
      /\bUNIT\b/i.test(source) || source.includes('단원평가') || source.includes('단원') ||
      /\bTRAINING_PACK\b/i.test(source) || /\bTRAINING\b/i.test(source) || source.includes('트레이닝팩') || source.includes('트팩') ||
      /\bREVIEW\b/i.test(source) || source.includes('복습') ||
      /\bSCHOOL_PAST\b/i.test(source) || /\bSCHOOL\b/i.test(source) || source.includes('학군지') || source.includes('학교별') ||
      /\bILSAN_PAST\b/i.test(source) || source.includes('일산')
    );
  }

  function findConfiguredTestForAssignment(item) {
    if (!item || typeof item !== 'object') return null;
    const assignedId = String(item.id || item.testId || '').trim();
    const assignedSourceId = assignedId.replace(/_r[123]$/, '');
    const itemName = String(item.name || item.testName || '').trim();
    const itemLabel = String(item.label || '').trim();
    const round = assignedRound(item.round);

    const tests = allConfiguredTests();
    if (assignedId) {
      const byId = tests.find(test =>
        String(test.id || '') === assignedId ||
        String(test.sourceId || '') === assignedId ||
        String(test.sourceId || '') === assignedSourceId
      );
      if (byId) return byId;
    }

    return tests.find(test => {
      const testName = String(test.name || '').trim();
      const nameOk = itemName ? itemName === testName : (itemLabel && itemLabel.includes(testName));
      if (!nameOk) return false;
      if (round && assignedRound(test.round) !== round) return false;
      if (item.curriculum && String(item.curriculum) !== String(test.curriculum || '')) return false;
      const itemDifficulty = normalizedTestDifficultyForCategory(test.categoryKey, assignedTestDifficultyLabel(item));
      const testDifficulty = normalizedTestDifficultyForCategory(test.categoryKey, test.difficulty);
      if (itemDifficulty && testDifficulty !== itemDifficulty) return false;
      return true;
    }) || null;
  }

  // ───────────── 답안 파싱/클라 채점(fallback용) ─────────────
  function parseAnswerEntries(text) {
    const s = String(text ?? '').trim();
    if (!s) return [];
    const lines = s.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').map(v => v.trim()).filter(Boolean);
    if (lines.length > 1) return lines;
    if (/[\s,]/.test(s)) return s.split(/[\s,]+/).map(v => v.trim()).filter(Boolean);
    return s.split('').map(v => v.trim()).filter(Boolean);
  }

  function parseAnswerSpec(text, problems) {
    const normalized = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const s = normalized.trim();
    if (!s) return new Array(problems).fill('');
    let arr = normalized.includes('\n')
      ? normalized.split('\n').map(value => value.trim())
      : parseAnswerEntries(s);

    if (arr.length > problems) arr = arr.slice(0, problems);
    if (arr.length < problems) arr = arr.concat(new Array(problems - arr.length).fill(''));
    return arr;
  }

  function answerCountValidationMessage(text, problems) {
    const total = Number(problems) || 0;
    if (!total) return '';
    const normalized = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    if (!normalized.trim()) return '';
    const entries = normalized.includes('\n')
      ? normalized.split('\n')
      : parseAnswerEntries(normalized);
    while (entries.length > total && !String(entries[entries.length - 1] || '').trim()) entries.pop();
    if (entries.length <= total) return '';
    return `답안 줄이 현재 시험 문항 수보다 많습니다. 현재 ${entries.length}줄 / 최대 ${total}줄입니다.`;
  }

  function submitAnswerModeForQuestion(testId, questionNo) {
    const no = Number(questionNo);
    const config = OCR_PHASE1_ANSWER_MODE_BY_TEST_ID[String(testId || '').trim()];
    if (!config || !Number.isInteger(no)) return '';
    if (config.choice_number.has(no)) return 'choice_number';
    if (config.answer_value.has(no)) return 'answer_value';
    return '';
  }

  function submitCleanOneLineAnswer(value) {
    const text = String(value || '').trim();
    if (/[\r\n]/.test(text)) return text;
    return text.replace(/\s+/g, '');
  }

  function submitIsChoiceNumberAnswer(answer) {
    return /^[1-5]$/.test(String(answer || '').trim());
  }

  function submitAnswerValidationMessage(answer, mode, questionNo) {
    const text = submitCleanOneLineAnswer(answer);
    if (!text) return '';
    if (/[\r\n]/.test(text)) return `${questionNo}번 문항 답안은 한 줄이어야 합니다.`;
    if (mode === 'choice_number' && !submitIsChoiceNumberAnswer(text)) {
      return `${questionNo}번 선택형 문항은 선지 번호(1~5)만 입력해야 합니다.`;
    }
    return '';
  }

  function answerModeValidationMessageForAnswersText(text, testId, problems) {
    const total = Number(problems) || parseAnswerEntries(text).length;
    const entries = parseAnswerSpec(text, total);
    for (let index = 0; index < Math.min(entries.length, total); index += 1) {
      const questionNo = index + 1;
      const mode = submitAnswerModeForQuestion(testId, questionNo);
      if (!mode) continue;
      const validationMessage = submitAnswerValidationMessage(entries[index], mode, questionNo);
      if (validationMessage) return validationMessage;
    }
    return '';
  }

  function submitAnswersTextForRequest(text, problems) {
    return parseAnswerSpec(text, Number(problems) || 0)
      .map((answer, index) => ({ questionNo: index + 1, answer: String(answer || '').trim() }))
      .filter(row => row.answer)
      .map(row => `${row.questionNo}: ${row.answer}`)
      .join('\n');
  }

  function submitBlankAnswerState(text, problems) {
    const answers = parseAnswerSpec(text, Number(problems) || 0);
    const blankQuestions = answers
      .map((answer, index) => String(answer || '').trim() ? null : index + 1)
      .filter(questionNo => questionNo !== null);
    if (!blankQuestions.length) return null;
    const allBlank = blankQuestions.length === answers.length;
    return {
      blocked: false,
      requiresConfirmation: true,
      count: blankQuestions.length,
      questionNumbers: blankQuestions,
      message: allBlank
        ? '답안이 모두 비어 있습니다. 빈 답안지를 그대로 제출하시겠습니까?'
        : `${blankQuestions.length}개 문항이 비어 있습니다. 빈칸은 오답으로 처리될 수 있습니다. 그대로 제출하시겠습니까?`,
    };
  }

  function getKeyForRound(test, roundNo) {
    const r = String(roundNo === 2 ? 2 : roundNo === 3 ? 3 : 1);

    if (test?.answerKeys && typeof test.answerKeys === 'object') {
      const k = test.answerKeys[r];
      if (Array.isArray(k)) return k.map(x => String(x ?? '').trim());
    }

    // legacy
    if (Array.isArray(test?.answerKey)) return test.answerKey.map(x => String(x ?? '').trim());
    if (typeof test?.answerKey === 'string') return parseAnswerSpec(test.answerKey, test.problems);

    return null;
  }

  function normalizeAnswerRound(round) {
    const r = String(round || '1').trim();
    return (r === '2' || r === '3') ? r : '1';
  }

  function getAnswerLinkForRound(testId, round, sourceId = '') {
    const id = String(testId || '').trim();
    const r = normalizeAnswerRound(round);
    const source = String(sourceId || '').trim() || id.replace(/_r[123]$/, '');
    const entry = TEST_ANSWER_LINK_MAP[id]?.[r] || TEST_ANSWER_LINK_MAP[source]?.[r];
    const answerUrl = (entry && typeof entry === 'object') ? (entry.answerUrl ?? entry.answer_url ?? entry.url ?? entry.link) : entry;
    return answerUrl ? String(answerUrl).trim() : null;
  }

  function driveFileUrl(fileId) {
    const id = String(fileId || '').trim();
    return id ? `https://drive.google.com/file/d/${encodeURIComponent(id)}/view?usp=drivesdk` : '';
  }

  function answerUrlFromConfiguredTest(test) {
    if (!test || typeof test !== 'object') return '';
    const direct = String(test.answerUrl || test.answer_url || test.solutionUrl || test.solution_url || '').trim();
    if (direct) return direct;
    const sourceFiles = (test.sourceFiles && typeof test.sourceFiles === 'object') ? test.sourceFiles : {};
    const sourceDirect = String(
      sourceFiles.answerUrl || sourceFiles.answer_url || sourceFiles.solutionUrl || sourceFiles.solution_url || ''
    ).trim();
    if (sourceDirect) return sourceDirect;
    return driveFileUrl(
      sourceFiles.solutionFileId || sourceFiles.solution_file_id ||
      sourceFiles.answerFileId || sourceFiles.answer_file_id ||
      test.solutionFileId || test.solution_file_id ||
      test.answerFileId || test.answer_file_id
    );
  }

  async function getAssignedAnswerLink(item) {
    const explicit = String(item?.answerUrl || item?.answer_url || item?.solutionUrl || item?.solution_url || '').trim();
    if (explicit) return { url: explicit, configuredTest: null };

    if (!Object.keys(TEST_CFG.categories || {}).length) {
      await ensureTestsConfigLoaded();
    }
    const configuredTest = findConfiguredTestForAssignment(item);
    const configUrl = answerUrlFromConfiguredTest(configuredTest);
    if (configUrl) return { url: configUrl, configuredTest };

    await loadAnswerLinkMap();
    const round = normalizeAnswerRound(item?.round || configuredTest?.round || '1');
    const candidates = [
      [item?.id || item?.testId, item?.sourceId || item?.source_id],
      [configuredTest?.id, configuredTest?.sourceId],
      [item?.sourceId || item?.source_id, ''],
    ];

    for (const [testId, sourceId] of candidates) {
      const url = getAnswerLinkForRound(testId, round, sourceId);
      if (url) return { url, configuredTest };
    }
    return { url: null, configuredTest };
  }

  window.openAssignedTestAnswerLink = async (item = {}) => {
    if (!answerLinkCategoryLike(item)) return false;
    if (studentAnswerAccessBlocked()) {
      showStudentAccessNotice();
      return true;
    }

    const openInSameTab = shouldOpenAssignedTestAnswerInSameTab();
    const popup = openInSameTab ? null : window.open('about:blank', '_blank');
    if (popup) popup.opener = null;

    try {
      const { url, configuredTest } = await getAssignedAnswerLink(item);
      if (!answerLinkCategoryLike(item, configuredTest) || !url) {
        if (popup) popup.close();
        return false;
      }
      if (openInSameTab) {
        window.location.assign(url);
      } else if (popup) {
        popup.location.replace(url);
      } else {
        window.location.assign(url);
      }
      return true;
    } catch (err) {
      if (popup) popup.close();
      console.warn('[test answer links] open failed', err);
      return false;
    }
  };

  function normalizeAnswerLinkMap(raw) {
    const out = {};
    const put = (testId, round, answerUrl) => {
      const id = String(testId || '').trim();
      const r = normalizeAnswerRound(round);
      const url = String(answerUrl || '').trim();
      if (!id || !r || !url) return;
      out[id] = out[id] || {};
      out[id][r] = url;
    };

    const putRows = rows => {
      rows.forEach(item => {
        if (!item || typeof item !== 'object') return;
        put(item.testId ?? item.test_id ?? item.id, item.round, item.answerUrl ?? item.answer_url ?? item.url ?? item.link);
      });
    };

    if (Array.isArray(raw)) {
      putRows(raw);
      return out;
    }

    if (!raw || typeof raw !== 'object') return out;
    if (Array.isArray(raw.links)) {
      putRows(raw.links);
      return out;
    }
    if (Array.isArray(raw.items)) {
      putRows(raw.items);
      return out;
    }

    Object.entries(raw).forEach(([testId, rounds]) => {
      if (!rounds || typeof rounds !== 'object') return;
      const roundMap = rounds.rounds || rounds.answers || rounds;
      if (!roundMap || typeof roundMap !== 'object') return;
      Object.entries(roundMap).forEach(([round, entry]) => {
        const answerUrl = (entry && typeof entry === 'object') ? (entry.answerUrl ?? entry.answer_url ?? entry.url ?? entry.link) : entry;
        put(testId, round, answerUrl);
      });
    });

    return out;
  }

  async function loadAnswerLinkMap() {
    if (answerLinkMapLoaded) return TEST_ANSWER_LINK_MAP;
    if (studentAnswerAccessBlocked()) {
      TEST_ANSWER_LINK_MAP = {};
      answerLinkMapLoaded = true;
      return TEST_ANSWER_LINK_MAP;
    }
    if (!answerLinkMapPromise) {
      answerLinkMapPromise = studentAppRequest('/js/test_answer_link_map.json', { cache: 'no-store' })
        .then(res => {
          if (!res.ok) throw new Error(String(res.status));
          return res.json();
        })
        .then(data => {
          TEST_ANSWER_LINK_MAP = normalizeAnswerLinkMap(data);
          return TEST_ANSWER_LINK_MAP;
        })
        .catch(err => {
          console.warn('[test answer links] load failed', err);
          TEST_ANSWER_LINK_MAP = {};
          return TEST_ANSWER_LINK_MAP;
        })
        .finally(() => {
          answerLinkMapLoaded = true;
        });
    }
    return answerLinkMapPromise;
  }

  function gradeClientSide(answersText, keyArr, problems) {
    const ans = parseAnswerSpec(answersText, problems);
    const key = (keyArr || []).slice(0, problems);
    if (key.length < problems) key.push(...new Array(problems - key.length).fill(''));

    const wrong = [];
    let correct = 0;

    for (let i = 0; i < problems; i++) {
      const a = String(ans[i] ?? '').replace(/\s+/g, '').toUpperCase();
      const k = String(key[i] ?? '').replace(/\s+/g, '').toUpperCase();

      if (!k) { // 키 비면 틀림 처리(원하면 여기 바꿔도 됨)
        wrong.push(i + 1);
        continue;
      }
      if (a === k) correct++;
      else wrong.push(i + 1);
    }

    const pct = problems ? +(correct / problems * 100).toFixed(2) : 0;
    return { correct, total: problems, wrong, pct };
  }

  function submitNormalizeGradingValue(value) {
    return String(value ?? '').replace(/\s+/g, '').toUpperCase();
  }

  function submitCountShiftedAnswerMatches(answers, key, problems, keyShift) {
    let matches = 0;
    for (let index = 0; index < problems; index += 1) {
      const keyIndex = index + keyShift;
      if (keyIndex < 0 || keyIndex >= problems) continue;
      const answer = submitNormalizeGradingValue(answers[index]);
      const expected = submitNormalizeGradingValue(key[keyIndex]);
      if (answer && expected && answer === expected) matches += 1;
    }
    return matches;
  }

  function submitDetectOffsetGuard(answersText, keyArr, problems) {
    const total = Number(problems) || 0;
    if (total < SUBMIT_OFFSET_GUARD_MIN_PROBLEMS || !Array.isArray(keyArr)) return null;
    const answers = parseAnswerSpec(answersText, total);
    const key = keyArr.slice(0, total).map(value => String(value ?? '').trim());
    if (key.length < total) key.push(...new Array(total - key.length).fill(''));

    const graded = gradeClientSide(answers.join('\n'), key, total);
    if (graded.correct > Math.floor(total / 2)) return null;

    const nextKeyMatches = submitCountShiftedAnswerMatches(answers, key, total, 1);
    const previousKeyMatches = submitCountShiftedAnswerMatches(answers, key, total, -1);
    const shiftedMatches = Math.max(nextKeyMatches, previousKeyMatches);
    const requiredMatches = Math.max(
      graded.correct + SUBMIT_OFFSET_GUARD_MIN_DELTA,
      Math.floor(total * SUBMIT_OFFSET_GUARD_MIN_SHIFTED_RATIO),
    );
    if (shiftedMatches < requiredMatches) return null;

    return {
      correct: graded.correct,
      total,
      shiftedMatches,
      requiredMatches,
      direction: nextKeyMatches >= previousKeyMatches ? 'next_key' : 'previous_key',
    };
  }

  function submitOffsetGuardMessage(guard) {
    const directionText = guard?.direction === 'previous_key'
      ? '\ud604\uc7ac 2\ubc88 \uc904\uc774 1\ubc88 \ubb38\ud56d \ub2f5\ucc98\ub7fc \ubcf4\uc774\ub294 \ud328\ud134\uc785\ub2c8\ub2e4.'
      : '\ud604\uc7ac 1\ubc88 \uc904\uc774 2\ubc88 \ubb38\ud56d \ub2f5\ucc98\ub7fc \ubcf4\uc774\ub294 \ud328\ud134\uc785\ub2c8\ub2e4.';
    return [
      '\ub2f5\uc548\uc774 \ud55c \ubb38\ud56d \ubc00\ub9b0 \ud328\ud134\uc73c\ub85c \ubcf4\uc785\ub2c8\ub2e4.',
      directionText,
      '\uc2dc\ud5d8/\ud68c\ucc28 \uc120\ud0dd\uacfc \ub2f5\uc548\uc9c0 \ubb38\ud56d \ubc88\ud638\ub97c \ud655\uc778\ud55c \ub4a4, 1\ubc88\ubd80\ud130 \ud55c \ubb38\ud56d\ub2f9 \ud55c \uc904\ub85c \ub2e4\uc2dc \ub9de\ucdb0\uc8fc\uc138\uc694.',
    ].join('\n');
  }

  function submitOffsetGuardMessageForAnswersText(answersText, test, round) {
    const key = getKeyForRound(test, round);
    if (!key) return '';
    const guard = submitDetectOffsetGuard(answersText, key, test?.problems);
    return guard ? submitOffsetGuardMessage(guard) : '';
  }

  // ───────────── UI ─────────────
  function injectStyles() {
    if (document.getElementById('test-submit-styles')) return;
    const s = document.createElement('style');
    s.id = 'test-submit-styles';
    s.textContent = `
    :root{
      --ts-card-bg:#fff; --ts-card-fg:#191f28; --ts-border:#e5e8eb; --ts-muted:#8b95a1;
      --ts-field-bg:#fff; --ts-focus:#3182f6; --ts-primary:#3182f6; --ts-primary-fg:#fff;
      --ts-ocr-tint:#f7f8fa; --ts-ocr-rule:#e5e8eb;
      --ts-warning:#e66b00; --ts-warning-bg:#fff7ed; --ts-backdrop:rgba(25,31,40,.48);
    }
    body.dark{
      --ts-card-bg:#0f172a; --ts-card-fg:#e5e7eb; --ts-border:#334155; --ts-muted:#94a3b8;
      --ts-field-bg:#0b1220; --ts-focus:#60a5fa; --ts-backdrop:rgba(0,0,0,.55);
      --ts-primary:#60a5fa; --ts-primary-fg:#0f172a; --ts-ocr-tint:#14232c; --ts-ocr-rule:#30515d;
      --ts-warning:#f59e0b; --ts-warning-bg:#2a1d0b;
    }
    #testSubmitModal{ position:fixed; inset:0; z-index:99999; display:none; justify-content:center; align-items:center; background:var(--ts-backdrop); }
    #testSubmitModal .ts-card{ width:480px; max-width:92vw; border-radius:18px; padding:20px;
      box-shadow:0 20px 48px rgba(25,31,40,.2); background:var(--ts-card-bg); color:var(--ts-card-fg);
      border:1px solid var(--ts-border); max-height:80vh; overflow:auto; }
    #testSubmitModal .ts-head{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
    #testSubmitModal h3{ margin:0; font-size:18px; font-weight:800; }
    #testSubmitModal label{ font-size:12px; color:var(--ts-muted); display:block; margin-bottom:6px; }
    #testSubmitModal select, #testSubmitModal textarea, #testSubmitModal input[type="file"]{
      width:100%; box-sizing:border-box; border:1px solid var(--ts-border); border-radius:6px;
      background:var(--ts-field-bg); color:var(--ts-card-fg); outline:none;
    }
    #testSubmitModal select{ height:36px; padding:0 10px; }
    #testSubmitModal input[type="file"]{ padding:7px 10px; min-height:36px; }
    #testSubmitModal textarea{ padding:8px 10px; resize:vertical; min-height:82px; }
    #testSubmitModal select:focus, #testSubmitModal textarea:focus, #testSubmitModal input[type="file"]:focus{
      border-color:var(--ts-focus); box-shadow:0 0 0 3px color-mix(in srgb, var(--ts-focus) 30%, transparent);
    }
    #testSubmitModal .ts-grid{ display:grid; gap:10px; }
    #testSubmitModal .ts-row3{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
    @media (max-width:520px){ #testSubmitModal .ts-row3{ grid-template-columns:1fr; } }
    #testSubmitModal .ts-info{ margin-top:6px; font-size:13px; color:var(--ts-muted); white-space:pre-wrap; }
    #testSubmitModal .ts-writing-rule{ margin-top:8px; padding:8px 10px; border:1px solid var(--ts-border); border-radius:6px; background:var(--ts-field-bg); color:var(--ts-card-fg); font-size:12px; line-height:1.45; }
    #testSubmitModal .ts-writing-rule ul{ margin:4px 0 0; padding-left:18px; }
    #testSubmitModal .ts-ocr-entry{
      display:grid; gap:14px; padding:16px 0; border-top:1px solid var(--ts-ocr-rule); border-bottom:1px solid var(--ts-ocr-rule);
      border-radius:0; background:transparent;
    }
    #testSubmitModal .ts-ocr-file-control{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; padding:14px; border:0; border-radius:14px; background:var(--ts-ocr-tint); }
    #testSubmitModal .ts-ocr-file-copy{ display:grid; min-width:0; gap:3px; }
    #testSubmitModal .ts-ocr-file-label{ color:var(--ts-card-fg); font-size:14px; font-weight:900; letter-spacing:-.01em; }
    #testSubmitModal .ts-ocr-file-name{ overflow:hidden; color:var(--ts-muted); font-size:12px; line-height:1.4; text-overflow:ellipsis; white-space:nowrap; }
    #testSubmitModal .ts-ocr-file-input{ position:absolute; width:1px; height:1px; margin:-1px; padding:0; overflow:hidden; clip:rect(0 0 0 0); border:0; white-space:nowrap; }
    #testSubmitModal .ts-ocr-file-pick{ min-height:40px; padding:0 14px; border:1px solid var(--ts-primary); border-radius:10px; background:var(--ts-card-bg); color:var(--ts-primary); cursor:pointer; font-weight:900; white-space:nowrap; }
    #testSubmitModal .ts-ocr-file-pick:focus-visible{ outline:none; box-shadow:0 0 0 3px color-mix(in srgb, var(--ts-focus) 30%, transparent); }
    #testSubmitModal .ts-ocr-open, #testSubmitModal .ts-ocr-apply, #testSubmitModal .ts-ocr-confirm{
      min-height:40px; padding:0 14px; border:none; border-radius:10px; cursor:pointer; font-weight:800; font-size:15px;
      background:var(--ts-primary); color:var(--ts-primary-fg); white-space:nowrap;
    }
    #testSubmitModal .ts-ocr-open{ justify-self:stretch; width:100%; min-height:44px; box-shadow:none; }
    /* Once a review is open, rerunning recognition is secondary to finishing the answers. */
    #testSubmitModal .ts-ocr-entry:has(#tsOcrReviewPanel:not([hidden])) .ts-ocr-open{
      justify-self:start; width:auto; min-height:30px; padding:0; border:0; background:transparent; color:var(--ts-muted);
      font-size:12px; font-weight:700; text-decoration:underline; text-decoration-thickness:1px; text-underline-offset:3px;
    }
    #testSubmitModal .ts-ocr-open:disabled, #testSubmitModal .ts-ocr-apply:disabled, #testSubmitModal .ts-ocr-confirm:disabled{ opacity:.55; cursor:not-allowed; }
    #testSubmitModal .ts-ocr-status{ min-height:18px; font-size:12px; color:var(--ts-muted); line-height:1.45; white-space:pre-wrap; }
    #testSubmitModal .ts-ocr-status:empty{ display:none; }
    #testSubmitModal .ts-ocr-status[data-state="error"]{ color:#dc2626; }
    #testSubmitModal .ts-ocr-status[data-state="ok"]{ color:#059669; }
    #testSubmitModal .ts-ocr-panel{ display:grid; gap:16px; }
    #testSubmitModal .ts-ocr-panel[hidden]{ display:none; }
    #testSubmitModal .ts-ocr-state-summary{ display:grid; gap:8px; padding:2px 0 14px; border-bottom:1px solid var(--ts-ocr-rule); }
    #testSubmitModal .ts-ocr-state-summary strong{ font-size:16px; line-height:1.3; color:var(--ts-card-fg); }
    #testSubmitModal .ts-ocr-state-summary p{ margin:0; color:var(--ts-muted); font-size:13px; line-height:1.5; word-break:keep-all; }
    #testSubmitModal .ts-ocr-state-stats{ display:flex; flex-wrap:wrap; gap:7px; }
    #testSubmitModal .ts-ocr-state-stats span{ min-height:28px; display:inline-flex; align-items:center; padding:0 9px; border:1px solid var(--ts-border); border-radius:999px; color:var(--ts-muted); font-size:12px; font-weight:800; }
    #testSubmitModal .ts-ocr-unresolved{
      display:grid; gap:10px; padding:14px 0; border-top:1px solid var(--ts-ocr-rule); border-bottom:1px solid var(--ts-ocr-rule);
      border-radius:0; background:transparent;
    }
    #testSubmitModal .ts-ocr-unresolved-head{ display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; justify-content:space-between; }
    #testSubmitModal .ts-ocr-unresolved-title{ font-size:16px; line-height:1.35; font-weight:900; color:var(--ts-card-fg); }
    #testSubmitModal .ts-ocr-unresolved-count{ padding:0; border-radius:0; background:transparent; color:var(--ts-muted); font-size:12px; font-weight:800; }
    #testSubmitModal .ts-ocr-unresolved-list{ display:flex; flex-wrap:wrap; gap:7px; }
    #testSubmitModal .ts-ocr-unresolved-question{
      min-height:32px; min-width:36px; padding:0 8px; border:1px solid var(--ts-ocr-rule); border-radius:5px;
      background:var(--ts-field-bg); color:var(--ts-primary); cursor:pointer; font-size:12px; font-weight:900;
    }
    #testSubmitModal .ts-ocr-unresolved-question:focus-visible,
    #testSubmitModal .ts-ocr-next-unresolved:focus-visible{ outline:none; box-shadow:0 0 0 3px color-mix(in srgb, var(--ts-focus) 30%, transparent); }
    #testSubmitModal .ts-ocr-next-unresolved{
      min-height:42px; padding:0 14px; border:1px solid var(--ts-primary); border-radius:10px;
      background:var(--ts-primary); color:var(--ts-primary-fg); cursor:pointer; font-weight:900;
    }
    #testSubmitModal .ts-ocr-next-unresolved:disabled{ opacity:.55; cursor:not-allowed; }
    #testSubmitModal .ts-ocr-card[data-ocr-focus="true"]{ box-shadow:0 0 0 3px color-mix(in srgb, var(--ts-focus) 26%, transparent); }
    #testSubmitModal .ts-ocr-guide-details{ border-top:1px solid var(--ts-border); border-bottom:1px solid var(--ts-border); border-radius:0; padding:10px 0; background:transparent; }
    #testSubmitModal .ts-ocr-guide-details summary{ cursor:pointer; font-size:13px; font-weight:900; color:var(--ts-card-fg); }
    #testSubmitModal .ts-ocr-guide-details[open] summary{ margin-bottom:9px; }
    #testSubmitModal .ts-ocr-guide-list{ display:grid; gap:10px; }
    #testSubmitModal .ts-ocr-guide{ display:grid; gap:4px; padding:4px 0; border:0; border-radius:0; background:transparent; color:var(--ts-card-fg); }
    #testSubmitModal .ts-ocr-guide strong{ font-size:14px; line-height:1.35; }
    #testSubmitModal .ts-ocr-guide span{ font-size:13px; line-height:1.5; color:var(--ts-muted); word-break:keep-all; overflow-wrap:anywhere; }
    #testSubmitModal .ts-ocr-guide[data-tone="warning"]{
      border-color:color-mix(in srgb, var(--ts-warning) 48%, var(--ts-border) 52%);
      background:color-mix(in srgb, var(--ts-warning-bg) 72%, var(--ts-card-bg) 28%);
    }
    #testSubmitModal .ts-ocr-guide[data-tone="danger"]{
      border-color:color-mix(in srgb, #dc2626 34%, var(--ts-border) 66%);
      background:color-mix(in srgb, #dc2626 10%, var(--ts-card-bg) 90%);
    }
    #testSubmitModal .ts-ocr-section{ display:grid; gap:12px; }
    #testSubmitModal .ts-ocr-section h5{ margin:0; padding:0 0 8px; border-bottom:1px solid var(--ts-ocr-rule); font-size:14px; font-weight:900; color:var(--ts-card-fg); }
    #testSubmitModal .ts-ocr-card{ display:grid; gap:12px; border:1px solid var(--ts-border); border-radius:14px; padding:16px; background:var(--ts-field-bg); }
    #testSubmitModal .ts-ocr-card h4{ margin:0; font-size:16px; line-height:1.3; font-weight:900; color:var(--ts-card-fg); }
    #testSubmitModal .ts-ocr-mode{ justify-self:start; display:inline-flex; align-items:center; min-height:0; padding:0; border:0; border-radius:0; background:transparent; color:var(--ts-muted); font-size:12px; font-weight:800; }
    #testSubmitModal .ts-ocr-card-help{ margin:0; color:var(--ts-muted); font-size:13px; line-height:1.5; word-break:keep-all; }
    #testSubmitModal .ts-ocr-card-main{ display:grid; grid-template-columns:minmax(0,1fr) minmax(142px,.65fr); gap:12px; align-items:start; }
    #testSubmitModal .ts-ocr-card-controls{ display:grid; gap:8px; min-width:0; }
    #testSubmitModal .ts-ocr-candidate-label{ color:var(--ts-muted); font-size:12px; font-weight:800; }
    #testSubmitModal .ts-ocr-crop{ min-width:0; border:1px solid var(--ts-border); border-radius:10px; padding:8px 10px; background:var(--ts-card-bg); }
    #testSubmitModal .ts-ocr-crop summary{ cursor:pointer; color:var(--ts-card-fg); font-size:12px; font-weight:800; }
    #testSubmitModal .ts-ocr-crop[open] summary{ margin-bottom:8px; }
    #testSubmitModal .ts-ocr-crop img{ display:block; width:100%; max-height:190px; object-fit:contain; border-radius:6px; background:var(--ts-ocr-tint); }
    #testSubmitModal .ts-ocr-recognized{ padding:0; border-radius:0; background:transparent; color:var(--ts-muted); font-size:14px; line-height:1.5; word-break:keep-all; overflow-wrap:anywhere; }
    #testSubmitModal .ts-ocr-prefill-note{ border:1px solid var(--ts-border); border-radius:10px; padding:9px 12px; background:var(--ts-card-bg); color:var(--ts-muted); font-size:14px; line-height:1.5; word-break:keep-all; overflow-wrap:anywhere; }
    #testSubmitModal .ts-ocr-warning{ border:1px solid color-mix(in srgb, var(--ts-warning) 45%, var(--ts-border) 55%); border-radius:10px; padding:9px 12px; background:var(--ts-warning-bg); color:var(--ts-warning); font-size:14px; line-height:1.5; word-break:keep-all; overflow-wrap:anywhere; }
    #testSubmitModal .ts-ocr-reason-row{ display:flex; flex-wrap:wrap; gap:8px; }
    #testSubmitModal .ts-ocr-reason-chip{
      display:inline-flex; align-items:center; min-height:28px; padding:0 10px; border:1px solid color-mix(in srgb, var(--ts-warning) 32%, var(--ts-border) 68%);
      border-radius:999px; background:var(--ts-card-bg); color:var(--ts-warning); font-size:12px; font-weight:800;
    }
    #testSubmitModal .ts-ocr-candidates{ display:flex; flex-wrap:wrap; gap:8px; }
    #testSubmitModal .ts-ocr-actions{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
    #testSubmitModal .ts-ocr-actions .ts-ocr-candidate, #testSubmitModal .ts-ocr-actions .ts-ocr-confirm{ width:100%; }
    #testSubmitModal .ts-ocr-actions .ts-ocr-confirm{ grid-column:1 / -1; }
    #testSubmitModal .ts-ocr-blocked-actions .ts-ocr-candidate{ min-width:0; }
    #testSubmitModal .ts-ocr-candidate, #testSubmitModal .ts-ocr-key{
      min-height:40px; padding:0 12px; border:1px solid var(--ts-border); border-radius:10px;
      background:var(--ts-card-bg); color:var(--ts-card-fg); cursor:pointer; font-weight:800;
    }
    #testSubmitModal .ts-ocr-choice-grid{ display:grid; grid-template-columns:repeat(5,minmax(48px,1fr)); gap:8px; }
    #testSubmitModal .ts-ocr-choice{
      min-height:48px; border:1px solid var(--ts-border); border-radius:10px; background:var(--ts-card-bg);
      color:var(--ts-card-fg); cursor:pointer; font-weight:900; font-size:17px;
    }
    #testSubmitModal .ts-ocr-choice[aria-pressed="true"]{ border-color:var(--ts-primary); background:var(--ts-primary); color:var(--ts-primary-fg); }
    #testSubmitModal .ts-ocr-choice[data-candidate="true"]{ border-color:color-mix(in srgb, var(--ts-primary) 55%, var(--ts-border) 45%); }
    #testSubmitModal .ts-ocr-choice:focus-visible{ outline:none; box-shadow:0 0 0 3px color-mix(in srgb, var(--ts-focus) 30%, transparent); }
    #testSubmitModal .ts-ocr-current{ width:100%; min-height:44px; box-sizing:border-box; border:1px solid var(--ts-border); border-radius:10px; padding:9px 12px; background:var(--ts-card-bg); color:var(--ts-card-fg); font-size:16px; }
    #testSubmitModal .ts-ocr-current[hidden]{ display:none; }
    #testSubmitModal .ts-ocr-keypad{ display:grid; grid-template-columns:repeat(auto-fit,minmax(46px,1fr)); gap:8px; }
    #testSubmitModal .ts-ocr-keypad-primary{ grid-template-columns:repeat(5,minmax(0,1fr)); }
    #testSubmitModal .ts-ocr-final-summary{ border-top:1px solid var(--ts-ocr-rule); border-bottom:1px solid var(--ts-ocr-rule); padding:10px 0; }
    #testSubmitModal .ts-ocr-final-summary details{ border:0; padding:0; }
    #testSubmitModal .ts-ocr-final-summary summary{ cursor:pointer; color:var(--ts-card-fg); font-size:14px; font-weight:900; }
    #testSubmitModal .ts-ocr-final-list{ display:grid; gap:7px; margin:10px 0 0; padding:0; list-style:none; }
    #testSubmitModal .ts-ocr-final-row{ display:grid; grid-template-columns:44px minmax(0,1fr) auto; gap:8px; align-items:center; }
    #testSubmitModal .ts-ocr-final-question{ color:var(--ts-card-fg); font-size:13px; font-weight:900; }
    #testSubmitModal .ts-ocr-final-input{ min-width:0; min-height:36px; box-sizing:border-box; border:1px solid var(--ts-border); border-radius:8px; padding:6px 9px; background:var(--ts-card-bg); color:var(--ts-card-fg); font-size:14px; font-weight:800; }
    #testSubmitModal .ts-ocr-final-status{ color:var(--ts-muted); font-size:12px; font-weight:800; white-space:nowrap; }
    #testSubmitModal .ts-ocr-final-row[data-resolution="unresolved"] .ts-ocr-final-status{ color:var(--ts-warning); }
    #testSubmitModal .ts-answer-details{ border:1px solid var(--ts-border); border-radius:10px; padding:8px 10px; background:var(--ts-field-bg); }
    #testSubmitModal .ts-answer-details summary{ cursor:pointer; color:var(--ts-card-fg); font-size:14px; font-weight:900; line-height:1.35; }
    #testSubmitModal .ts-answer-details[open] summary{ margin-bottom:8px; }
    #testSubmitModal .ts-ocr-fallback{ display:grid; gap:8px; padding:11px 12px; border:1px solid color-mix(in srgb, #dc2626 34%, var(--ts-border) 66%); border-radius:12px; background:color-mix(in srgb, #dc2626 5%, var(--ts-card-bg) 95%); }
    #testSubmitModal .ts-ocr-fallback[hidden]{ display:none; }
    #testSubmitModal .ts-ocr-fallback strong{ font-size:14px; color:var(--ts-card-fg); }
    #testSubmitModal .ts-ocr-fallback p{ margin:0; color:var(--ts-muted); font-size:13px; line-height:1.5; word-break:keep-all; overflow-wrap:anywhere; }
    #testSubmitModal .ts-ocr-fallback-actions{ display:flex; flex-wrap:wrap; gap:8px; }
    #testSubmitModal .ts-ocr-fallback-action{ min-height:36px; padding:0 11px; border:1px solid var(--ts-border); border-radius:10px; background:var(--ts-card-bg); color:var(--ts-card-fg); cursor:pointer; font-weight:800; }
    #testSubmitModal .ts-answer-link{ display:none; margin-top:8px; font-size:13px; color:var(--ts-muted); }
    #testSubmitModal .ts-answer-link a{
      display:inline-flex; align-items:center; justify-content:center; height:38px; padding:0 14px;
      border-radius:10px; background:var(--ts-primary); color:var(--ts-primary-fg); text-decoration:none; font-weight:800;
    }
    #testSubmitModal .ts-result-panel{
      display:grid; gap:14px; margin-top:14px; padding:18px; border:1px solid color-mix(in srgb, var(--ts-primary) 38%, var(--ts-border) 62%);
      border-radius:14px; background:color-mix(in srgb, var(--ts-primary) 6%, var(--ts-card-bg) 94%);
    }
    #testSubmitModal .ts-result-panel[hidden]{ display:none; }
    #testSubmitModal .ts-result-head{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
    #testSubmitModal .ts-result-title{ display:grid; gap:3px; }
    #testSubmitModal .ts-result-title strong{ font-size:21px; line-height:1.22; }
    #testSubmitModal .ts-result-title span{ font-size:14px; color:var(--ts-card-fg); opacity:.78; }
    #testSubmitModal .ts-result-rate{ min-width:132px; text-align:right; display:grid; gap:4px; justify-items:end; }
    #testSubmitModal .ts-result-rate-label{ font-size:13px; line-height:1.1; font-weight:900; color:var(--ts-card-fg); opacity:.72; }
    #testSubmitModal .ts-result-rate-value{ font-size:42px; line-height:.95; font-weight:900; color:var(--ts-primary); letter-spacing:0; }
    #testSubmitModal .ts-result-metrics{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
    #testSubmitModal .ts-result-metric{ padding:13px; border:1px solid var(--ts-border); border-radius:12px; background:var(--ts-card-bg); }
    #testSubmitModal .ts-result-metric span{ display:block; font-size:13px; color:var(--ts-card-fg); opacity:.72; margin-bottom:5px; }
    #testSubmitModal .ts-result-metric strong{ font-size:21px; line-height:1.12; }
    #testSubmitModal .ts-result-wrong-title{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between; font-size:17px; font-weight:900; }
    #testSubmitModal .ts-result-wrong-count{ display:inline-flex; min-height:34px; align-items:center; padding:0 12px; border:1px solid var(--ts-border); border-radius:999px; background:var(--ts-card-bg); color:var(--ts-card-fg); font-size:13px; font-weight:900; }
    #testSubmitModal .ts-result-empty{ padding:14px; border-radius:12px; background:var(--ts-card-bg); color:#047857; font-size:15px; font-weight:900; }
    #testSubmitModal .ts-result-compare{ display:grid; gap:10px; }
    #testSubmitModal .ts-result-comparison-card{
      display:grid; gap:10px; padding:12px; border:1px solid var(--ts-border); border-radius:12px;
      background:var(--ts-card-bg);
    }
    #testSubmitModal .ts-result-row-no{ color:var(--ts-card-fg); opacity:.82; font-size:16px; font-weight:900; }
    #testSubmitModal .ts-result-answer-values{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    #testSubmitModal .ts-result-answer-block{ display:grid; gap:6px; min-width:0; }
    #testSubmitModal .ts-result-answer-label{ font-size:12px; line-height:1.2; font-weight:900; color:var(--ts-card-fg); opacity:.72; }
    #testSubmitModal .ts-result-my-answer, #testSubmitModal .ts-result-correct-answer{
      display:inline-flex; width:100%; min-height:44px; box-sizing:border-box; align-items:center; justify-content:center;
      padding:6px 10px; border-radius:10px; font-size:17px; line-height:1.2; font-weight:900; text-align:center;
      overflow-wrap:anywhere; word-break:break-word;
    }
    #testSubmitModal .ts-result-my-answer{ border:1px solid color-mix(in srgb, var(--ts-danger) 35%, var(--ts-border) 65%); background:color-mix(in srgb, var(--ts-danger) 7%, var(--ts-card-bg) 93%); color:var(--ts-card-fg); }
    #testSubmitModal .ts-result-correct-answer{ border:1px solid color-mix(in srgb, var(--ts-success) 35%, var(--ts-border) 65%); background:color-mix(in srgb, var(--ts-success) 7%, var(--ts-card-bg) 93%); color:var(--ts-card-fg); }
    #testSubmitModal .ts-result-answer{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; align-items:center; }
    #testSubmitModal .ts-result-answer-button, #testSubmitModal .ts-result-answer-link{
      min-height:42px; padding:0 14px; border:1px solid var(--ts-primary); border-radius:10px;
      background:var(--ts-primary); color:var(--ts-primary-fg); font-weight:900; cursor:pointer; text-decoration:none;
    }
    #testSubmitModal .ts-result-answer-link{ display:inline-flex; align-items:center; justify-content:center; background:var(--ts-card-bg); color:var(--ts-primary); }
    #testSubmitModal.ts-result-view .ts-submit-fields,
    #testSubmitModal.ts-result-view .ts-answer-details,
    #testSubmitModal.ts-result-view .ts-ocr-entry,
    #testSubmitModal.ts-result-view .ts-memo-entry,
    #testSubmitModal.ts-result-view .ts-actions,
    #testSubmitModal.ts-result-view #tsInfo,
    #testSubmitModal.ts-result-view #tsAnswerLinkArea{ display:none !important; }
    #testAnswerPreviewModal{ position:fixed; inset:0; z-index:100000; display:none; justify-content:center; align-items:center; background:var(--ts-backdrop); }
    #testAnswerPreviewModal .ts-preview-card{ width:min(1100px,96vw); height:min(760px,90vh); display:grid; grid-template-rows:auto 1fr; border:1px solid var(--ts-border); border-radius:16px; background:var(--ts-card-bg); color:var(--ts-card-fg); box-shadow:0 20px 48px rgba(0,0,0,.4); overflow:hidden; }
    #testAnswerPreviewModal .ts-preview-head{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:12px 14px; border-bottom:1px solid var(--ts-border); }
    #testAnswerPreviewModal .ts-preview-title{ font-weight:900; font-size:16px; }
    #testAnswerPreviewModal .ts-preview-actions{ display:flex; gap:8px; align-items:center; }
    #testAnswerPreviewModal .ts-preview-link{ color:var(--ts-primary); font-weight:900; text-decoration:none; }
    #testAnswerPreviewModal .ts-preview-close{ border:1px solid var(--ts-border); border-radius:10px; background:var(--ts-field-bg); color:var(--ts-card-fg); min-height:34px; padding:0 10px; cursor:pointer; font-weight:800; }
    #testAnswerPreviewModal .ts-preview-body{ position:relative; min-height:0; background:#fff; }
    #testAnswerPreviewFrame{ width:100%; height:100%; border:0; background:#fff; }
    #testAnswerPreviewModal .ts-preview-loading{
      position:absolute; inset:0; display:grid; place-items:center; padding:24px;
      background:var(--ts-card-bg); color:var(--ts-card-fg); text-align:center; font-size:14px; line-height:1.55;
    }
    #testAnswerPreviewModal .ts-preview-loading strong{ display:block; margin-bottom:6px; font-size:16px; }
    #testAnswerPreviewModal .ts-preview-loading span{ color:var(--ts-muted); }
    #testAnswerPreviewModal .ts-preview-loading[hidden]{ display:none; }
    @media (max-width:520px){
      #testSubmitModal .ts-card{ max-height:88vh; }
      #testSubmitModal .ts-ocr-file-control{ grid-template-columns:1fr; }
      #testSubmitModal .ts-ocr-file-pick{ width:100%; }
      #testSubmitModal .ts-ocr-card-main{ grid-template-columns:1fr; }
      #testSubmitModal .ts-ocr-final-row{ grid-template-columns:40px minmax(0,1fr); }
      #testSubmitModal .ts-ocr-final-status{ grid-column:2; }
      #testSubmitModal .ts-result-head{ display:grid; }
      #testSubmitModal .ts-result-rate{ text-align:left; }
      #testSubmitModal .ts-result-metrics{ grid-template-columns:1fr; }
      #testSubmitModal .ts-result-answer{ grid-template-columns:1fr; }
    }
    #testSubmitModal .ts-actions{ display:flex; gap:8px; justify-content:flex-end; margin-top:12px; }
    #testSubmitModal .ts-submit{
      height:38px; padding:0 14px; border:none; border-radius:10px; cursor:pointer; font-weight:800;
      background:var(--ts-primary); color:var(--ts-primary-fg);
    }
    #testSubmitModal .ts-close{ border:none; background:transparent; font-size:20px; cursor:pointer; color:var(--ts-card-fg); }
    `;
    document.head.appendChild(s);
  }

  function ensureModal() {
    if (document.getElementById('testSubmitModal')) return;

    const ocrMarkup = OCR_TEST_SHEET_ENABLED ? `
            <div class="ts-ocr-entry">
              <div id="tsOcrReviewFileControl" class="ts-ocr-file-control">
                <div class="ts-ocr-file-copy">
                  <span class="ts-ocr-file-label">답안지 사진</span>
                  <span id="tsOcrReviewFileName" class="ts-ocr-file-name" aria-live="polite">사진을 선택해 주세요.</span>
                </div>
                <button id="tsOcrReviewPick" class="ts-ocr-file-pick" type="button">사진 선택</button>
                <input id="tsOcrReviewImage" class="ts-ocr-file-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" tabindex="-1" aria-hidden="true">
              </div>
              <button id="tsOcrReviewOpen" class="ts-ocr-open" type="button">사진 인식 결과 확인</button>
              <div id="tsOcrStatus" class="ts-ocr-status" aria-live="polite"></div>
              <div id="tsOcrFallback" class="ts-ocr-fallback" hidden></div>
              <div id="tsOcrReviewPanel" class="ts-ocr-panel" hidden></div>
            </div>
    ` : '';
    const writingRuleMarkup = OCR_TEST_SHEET_ENABLED ? `
              <div id="tsWritingRule" class="ts-writing-rule">
                <strong>답안 작성 기준</strong>
                <ul>
                  <li>객관식 문항은 선지 번호만 작성하세요.</li>
                  <li>주관식/답값형 문항은 최종 답만 작성하세요.</li>
                  <li>예: 객관식은 1~5, 답값형은 12, 64, 1/2처럼 한 답만 씁니다.</li>
                  <li>x=2, 3√2, 1,3처럼 식이나 여러 답을 쓰면 자동 채움이 막힐 수 있습니다.</li>
                  <li>풀이식, 중간식, 선지 내용은 오답 처리될 수 있습니다.</li>
                  <li>사진 인식은 답안 입력 보조이며, 채점은 기존 제출 버튼에서만 진행됩니다.</li>
                </ul>
              </div>
    ` : '';

    document.body.insertAdjacentHTML('beforeend', `
      <div id="testSubmitModal">
        <div class="ts-card">
          <div class="ts-head">
            <h3>테스트 성적 제출</h3>
            <button id="tsClose" class="ts-close" aria-label="close">✕</button>
          </div>

          <div class="ts-grid">
            <div class="ts-row3 ts-submit-fields">
              <div>
                <label>종류</label>
                <select id="tsType">
                  <option value="UNIT" selected>단원평가</option>
                  <option value="TRAINING_PACK">트레이닝팩</option>
                </select>
              </div>
              <div>
                <label>시험</label>
                <select id="tsTestId"></select>
              </div>
              <div>
                <label>회차</label>
                <select id="tsRound">
                  <option value="1" selected>1회차</option>
                  <option value="2">2회차</option>
                  <option value="3">3회차</option>
                </select>
              </div>
            </div>

            ${ocrMarkup}

            <div class="ts-answer-entry">
              <details id="tsAnswersDetails" class="ts-answer-details">
                <summary>답 입력 열기</summary>
                <label>답 입력 (20문항, 한 줄에 하나 · 직접 수정 가능)</label>
                <textarea id="tsAnswersText" placeholder="1번부터 20번까지 한 줄에 하나씩 직접 입력할 수 있습니다."></textarea>
                ${writingRuleMarkup}
              </details>
              <div id="tsInfo" class="ts-info"></div>
              <div id="tsAnswerLinkArea" class="ts-answer-link"></div>
              <div id="tsResultPanel" class="ts-result-panel" hidden></div>
            </div>

            <div class="ts-memo-entry">
              <label>메모(선택)</label>
              <textarea id="tsMemo" rows="2" placeholder="메모가 있으면 적어주세요"></textarea>
            </div>
          </div>

          <div class="ts-actions">
            <button id="tsSubmit" class="ts-submit">제출</button>
          </div>
        </div>
      </div>
      <div id="testAnswerPreviewModal" aria-hidden="true">
        <div class="ts-preview-card" role="dialog" aria-modal="true" aria-labelledby="testAnswerPreviewTitle">
          <div class="ts-preview-head">
            <div id="testAnswerPreviewTitle" class="ts-preview-title">전체 답지 보기</div>
            <div class="ts-preview-actions">
              <a id="testAnswerPreviewOpenExternal" class="ts-preview-link" target="_blank" rel="noopener noreferrer">새 탭으로 열기</a>
              <button id="testAnswerPreviewClose" class="ts-preview-close" type="button">닫기</button>
            </div>
          </div>
          <div class="ts-preview-body">
            <iframe id="testAnswerPreviewFrame" title="전체 답지 미리보기"></iframe>
            <div id="testAnswerPreviewLoading" class="ts-preview-loading" role="status" aria-live="polite" hidden>
              <div>
                <strong>답지를 불러오는 중입니다.</strong>
                <span>잠시 기다려주세요. 오래 걸리면 새 탭으로 열어주세요.</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    `);
  }

  async function initLogic() {
    const btnOpen = document.getElementById('openTestSubmit'); // ✅ HTML에 이미 있음
    const modal = document.getElementById('testSubmitModal');
    const btnClose = document.getElementById('tsClose');
    const btnSubmit = document.getElementById('tsSubmit');

    const selType = document.getElementById('tsType');
    const selTestId = document.getElementById('tsTestId');
    const selRound = document.getElementById('tsRound');

    const answersTextEl = document.getElementById('tsAnswersText');
    const memoEl = document.getElementById('tsMemo');
    const infoEl = document.getElementById('tsInfo');
    const answerLinkArea = document.getElementById('tsAnswerLinkArea');
    const resultPanel = document.getElementById('tsResultPanel');
    const answerPreviewModal = document.getElementById('testAnswerPreviewModal');
    const answerPreviewTitle = document.getElementById('testAnswerPreviewTitle');
    const answerPreviewFrame = document.getElementById('testAnswerPreviewFrame');
    const answerPreviewOpenExternal = document.getElementById('testAnswerPreviewOpenExternal');
    const answerPreviewClose = document.getElementById('testAnswerPreviewClose');
    const answerPreviewLoading = document.getElementById('testAnswerPreviewLoading');
    const ocrReviewImageEl = document.getElementById('tsOcrReviewImage');
    const ocrReviewFileControlEl = document.getElementById('tsOcrReviewFileControl');
    const ocrReviewFileNameEl = document.getElementById('tsOcrReviewFileName');
    const btnOcrReviewPick = document.getElementById('tsOcrReviewPick');
    const btnOcrReviewOpen = document.getElementById('tsOcrReviewOpen');
    const ocrStatusEl = document.getElementById('tsOcrStatus');
    const ocrFallbackEl = document.getElementById('tsOcrFallback');
    const ocrReviewPanel = document.getElementById('tsOcrReviewPanel');
    let ocrReviewPayload = null;
    let ocrReviewLastMeta = null;
    let ocrReviewNextBlankIndex = 0;
    let ocrReviewCurrentUnresolvedQuestion = null;
    let ocrReviewStartedAt = 0;

    const currentCur = () => getMyCurriculumFromNamebar();

    const testsConfigReady = ensureTestsConfigLoaded();

    function renderTypeOptions(preselectType = '') {
      const myCur = currentCur();
      const available = TEST_TYPE_OPTIONS.filter(opt => listTestsForType(opt.value, myCur).length);
      if (!available.length) {
        selType.innerHTML = `<option value="">(배정 없음)</option>`;
        return '';
      }

      selType.innerHTML = available.map(opt =>
        `<option value="${opt.value}">${opt.label}</option>`
      ).join('');
      selType.value = available.some(opt => opt.value === preselectType)
        ? preselectType
        : available[0].value;
      return selType.value;
    }

    function availableRoundsForType(typeVal = selType.value) {
      const rounds = new Set();
      listTestsForType(typeVal, currentCur()).forEach(test => {
        const round = assignedRound(test.round || '1');
        if (round) rounds.add(round);
      });
      return Array.from(rounds).sort((a, b) => Number(a) - Number(b));
    }

    function renderRoundOptions(preselectRound = '') {
      const rounds = availableRoundsForType();
      const fallbackRounds = rounds.length ? rounds : ['1'];
      const wanted = assignedRound(preselectRound || selRound.value || fallbackRounds[0]);
      selRound.innerHTML = fallbackRounds.map(round =>
        `<option value="${round}">${roundLabel(round)}</option>`
      ).join('');
      selRound.value = fallbackRounds.includes(wanted) ? wanted : fallbackRounds[0];
      return selRound.value;
    }
    function renderTestOptions(preselectTestId = '') {
      const myCur = currentCur();
      const type = selType.value;
      const list = listTestsForType(type, myCur);

      if (!list.length) {
        selTestId.innerHTML = `<option value="">(시험 없음)</option>`;
        selRound.innerHTML = `<option value="1">1회차</option>`;
        selRound.value = '1';
        infoEl.textContent = '오늘 배정된 시험이 없습니다.';
        return;
      }

      selTestId.innerHTML = list.map(t => {
        const curTag = t.curriculum ? ` (${t.curriculum})` : '';
        const meta = [t.difficulty, roundLabel(t.round)].filter(Boolean).join(' · ');
        return `<option value="${t.id}">${t.name}${curTag}${meta ? ` · ${meta}` : ''}</option>`;
      }).join('');

      if (preselectTestId) {
        const preselect = String(preselectTestId).trim();
        const match = list.find(t =>
          String(t.id || '').trim() === preselect ||
          String(t.sourceId || t.source_id || '').trim() === preselect
        );
        if (match) selTestId.value = String(match.id || '');
      }

      const selectedTest = findTestById(type, selTestId.value, myCur);
      renderRoundOptions(selectedTest?.round || selRound.value);
      updateInfo();
    }

    function updateInfo(extra) {
      const myCur = currentCur();
      const type = selType.value;
      const testId = selTestId.value;
      const t = findTestById(type, testId, myCur);
      const round = parseInt(t?.round || selRound.value, 10) || 1;

      if (!t) {
        infoEl.textContent = '시험을 선택하세요.';
        return;
      }

      if (selRound && String(selRound.value || '') !== String(round)) {
        selRound.value = String(round);
      }

      infoEl.textContent = extra ? String(extra) : '';
    }

    function resetAnswerLink() {
      if (!answerLinkArea) return;
      answerLinkArea.style.display = 'none';
      answerLinkArea.replaceChildren();
    }

    function setResultViewMode(active) {
      modal?.classList?.toggle?.('ts-result-view', Boolean(active));
    }

    function resetResultPanel() {
      if (!resultPanel) return;
      setResultViewMode(false);
      resultPanel.hidden = true;
      resultPanel.replaceChildren();
    }

    function formatSubmitPercent(value) {
      if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
      return `${value.toFixed(1)}%`;
    }

    function parseScoreParts(score, fallbackTotal) {
      const text = String(score || '').trim();
      const match = text.match(/^\s*(\d+)\s*\/\s*(\d+)\s*$/);
      if (!match) return { correct: null, total: Number(fallbackTotal) || null };
      return { correct: Number(match[1]), total: Number(match[2]) };
    }

    function submitResultRows(answersText, key, wrongNumbers, problems) {
      const answers = parseAnswerSpec(answersText, problems);
      return wrongNumbers.map(no => {
        const index = Number(no) - 1;
        return {
          questionNo: Number(no),
          myAnswer: String(answers[index] ?? '').trim() || '(빈칸)',
          correctAnswer: String(key?.[index] ?? '').trim() || '(정답 정보 없음)',
        };
      });
    }

    function submitResultRowsFromResponse(responseData) {
      const rows = Array.isArray(responseData?.wrongDetails) ? responseData.wrongDetails : [];
      return rows.map(row => ({
        questionNo: Number(row?.questionNo || row?.question_no),
        myAnswer: String(row?.myAnswer ?? row?.my_answer ?? '').trim() || '(빈칸)',
        correctAnswer: String(row?.correctAnswer ?? row?.correct_answer ?? '').trim() || '(정답 정보 없음)',
      })).filter(row => Number.isInteger(row.questionNo) && row.questionNo >= 1);
    }

    function buildSubmitResultViewModel({ test, round, answersText, responseData = {}, fallbackGraded = null, answerUrl = '' }) {
      const problems = Number(test?.problems) || parseAnswerEntries(answersText).length || 0;
      const key = getKeyForRound(test, round);
      const localGraded = key ? gradeClientSide(answersText, key, problems) : null;
      const responseRows = submitResultRowsFromResponse(responseData);
      const score = String(responseData.score || (fallbackGraded ? `${fallbackGraded.correct}/${fallbackGraded.total}` : '') || '').trim();
      const scoreParts = parseScoreParts(score, problems);
      const wrongNumbers = (Array.isArray(responseData.wrong) ? responseData.wrong : fallbackGraded?.wrong || localGraded?.wrong || [])
        .map(value => Number(value))
        .filter(value => Number.isInteger(value) && value >= 1 && (!problems || value <= problems))
        .sort((a, b) => a - b);
      const correct = scoreParts.correct ?? Math.max(0, (scoreParts.total || problems) - wrongNumbers.length);
      const total = scoreParts.total || problems;
      const pct = typeof responseData.pct === 'number'
        ? responseData.pct
        : (typeof fallbackGraded?.pct === 'number' ? fallbackGraded.pct : (typeof localGraded?.pct === 'number' ? localGraded.pct : null));
      return {
        title: String(test?.name || '선택한 시험'),
        round,
        score: score || `${correct}/${total}`,
        correct,
        total,
        pct,
        wrongNumbers,
        rows: responseRows.length ? responseRows : (key ? submitResultRows(answersText, key, wrongNumbers, problems) : []),
        answerUrl,
      };
    }

    function closeAnswerPreview() {
      if (!answerPreviewModal) return;
      answerPreviewModal.style.display = 'none';
      answerPreviewModal.setAttribute('aria-hidden', 'true');
      answerPreviewModal.dataset.state = 'closed';
      if (answerPreviewLoading) answerPreviewLoading.hidden = true;
      if (answerPreviewFrame) answerPreviewFrame.src = 'about:blank';
    }

    function setAnswerPreviewLoading(isLoading) {
      if (!answerPreviewModal || !answerPreviewLoading) return;
      answerPreviewModal.dataset.state = isLoading ? 'loading' : 'loaded';
      answerPreviewLoading.hidden = !isLoading;
    }

    function answerPreviewFrameUrl(url) {
      const text = String(url || '').trim();
      const filePathMatch = text.match(/^https:\/\/drive\.google\.com\/file\/d\/([^/?#]+)/i);
      if (filePathMatch) {
        return `https://drive.google.com/file/d/${filePathMatch[1]}/preview`;
      }
      const idQueryMatch = text.match(/^https:\/\/drive\.google\.com\/(?:open|uc)\?(?:[^#]*&)?id=([^&#]+)/i);
      if (idQueryMatch) {
        return `https://drive.google.com/file/d/${idQueryMatch[1]}/preview`;
      }
      return text;
    }

    function openAnswerPreview(url, title = '전체 답지 보기') {
      const safeUrl = String(url || '').trim();
      if (!safeUrl) return;
      if (!answerPreviewModal || !answerPreviewFrame || !answerPreviewOpenExternal) {
        window.open(safeUrl, '_blank', 'noopener,noreferrer');
        return;
      }
      if (answerPreviewTitle) answerPreviewTitle.textContent = title;
      answerPreviewOpenExternal.href = safeUrl;
      setAnswerPreviewLoading(true);
      answerPreviewFrame.src = answerPreviewFrameUrl(safeUrl);
      answerPreviewModal.style.display = 'flex';
      answerPreviewModal.setAttribute('aria-hidden', 'false');
    }

    function renderSubmitResultPanel(result) {
      if (!resultPanel) return;
      resultPanel.replaceChildren();
      if (!result) {
        setResultViewMode(false);
        resultPanel.hidden = true;
        return;
      }

      const head = document.createElement('div');
      head.className = 'ts-result-head';
      const title = document.createElement('div');
      title.className = 'ts-result-title';
      const strong = document.createElement('strong');
      strong.textContent = '채점 결과';
      const subtitle = document.createElement('span');
      subtitle.textContent = `${result.title} · ${roundLabel(result.round) || '1회차'}`;
      title.append(strong, subtitle);

      const rate = document.createElement('div');
      rate.className = 'ts-result-rate';
      const rateLabel = document.createElement('span');
      rateLabel.className = 'ts-result-rate-label';
      rateLabel.textContent = '정답률';
      const rateValue = document.createElement('strong');
      rateValue.className = 'ts-result-rate-value';
      rateValue.textContent = formatSubmitPercent(result.pct);
      rate.append(rateLabel, rateValue);
      head.append(title, rate);

      const metrics = document.createElement('div');
      metrics.className = 'ts-result-metrics';
      [
        ['점수', result.score],
        ['정답', `${result.correct}/${result.total}`],
        ['오답', `${result.wrongNumbers.length}개`],
      ].forEach(([label, value]) => {
        const metric = document.createElement('div');
        metric.className = 'ts-result-metric';
        const labelEl = document.createElement('span');
        labelEl.textContent = label;
        const valueEl = document.createElement('strong');
        valueEl.textContent = value;
        metric.append(labelEl, valueEl);
        metrics.appendChild(metric);
      });

      const wrongTitle = document.createElement('div');
      wrongTitle.className = 'ts-result-wrong-title';
      const wrongHeading = document.createElement('strong');
      wrongHeading.textContent = '틀린 문항 답 비교';
      const wrongCount = document.createElement('span');
      wrongCount.className = 'ts-result-wrong-count';
      wrongCount.textContent = result.wrongNumbers.length
        ? `틀린 문항: ${result.wrongNumbers.map(no => `${no}번`).join(', ')}`
        : '틀린 문항 없음';
      wrongTitle.append(wrongHeading, wrongCount);

      const wrongBody = document.createElement('div');
      if (!result.wrongNumbers.length) {
        wrongBody.className = 'ts-result-empty';
        wrongBody.textContent = '이번 제출에서 오답이 없습니다.';
      } else if (result.rows.length) {
        wrongBody.className = 'ts-result-compare';
        result.rows.forEach(row => {
          const card = document.createElement('div');
          card.className = 'ts-result-comparison-card';
          const question = document.createElement('div');
          question.className = 'ts-result-row-no';
          question.textContent = `${row.questionNo}번`;

          const values = document.createElement('div');
          values.className = 'ts-result-answer-values';
          const myAnswerBlock = document.createElement('div');
          myAnswerBlock.className = 'ts-result-answer-block';
          const myAnswerLabel = document.createElement('span');
          myAnswerLabel.className = 'ts-result-answer-label';
          myAnswerLabel.textContent = '내 답';
          const myAnswer = document.createElement('span');
          myAnswer.className = 'ts-result-my-answer';
          myAnswer.textContent = row.myAnswer;
          myAnswerBlock.append(myAnswerLabel, myAnswer);

          const correctAnswerBlock = document.createElement('div');
          correctAnswerBlock.className = 'ts-result-answer-block';
          const correctAnswerLabel = document.createElement('span');
          correctAnswerLabel.className = 'ts-result-answer-label';
          correctAnswerLabel.textContent = '정답';
          const correctAnswer = document.createElement('span');
          correctAnswer.className = 'ts-result-correct-answer';
          correctAnswer.textContent = row.correctAnswer;
          correctAnswerBlock.append(correctAnswerLabel, correctAnswer);

          values.append(myAnswerBlock, correctAnswerBlock);
          card.append(question, values);
          wrongBody.appendChild(card);
        });
      } else {
        wrongBody.className = 'ts-result-empty';
        wrongBody.textContent = '정답 비교 정보를 불러오지 못했습니다. 전체 답지에서 확인해주세요.';
      }

      const answerActions = document.createElement('div');
      answerActions.className = 'ts-result-answer';
      if (result.answerUrl) {
        const previewButton = document.createElement('button');
        previewButton.type = 'button';
        previewButton.className = 'ts-result-answer-button';
        previewButton.textContent = '전체 답지 크게 보기';
        previewButton.addEventListener('click', () => openAnswerPreview(result.answerUrl, `${result.title} ${roundLabel(result.round)} 답지`));
        const link = document.createElement('a');
        link.className = 'ts-result-answer-link';
        link.href = result.answerUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = '새 탭으로 열기';
        answerActions.append(previewButton, link);
      } else {
        const help = document.createElement('div');
        help.className = 'ts-info';
        help.textContent = studentAnswerAccessBlocked() ? '전체 답지는 학원 Wi-Fi에서만 볼 수 있습니다.' : '전체 답지 링크 준비 중';
        answerActions.appendChild(help);
      }

      resultPanel.append(head, metrics, wrongTitle, wrongBody, answerActions);
      resultPanel.hidden = false;
      setResultViewMode(true);
    }

    const OCR_PHASE1_READY_MESSAGE = '답안지 사진을 선택한 뒤 사진 인식 결과 확인 버튼을 눌러주세요.';

    function ocrTestSheetSetStatus(message = '', state = '') {
      if (!ocrStatusEl) return;
      ocrStatusEl.textContent = message;
      if (state) ocrStatusEl.dataset.state = state;
      else delete ocrStatusEl.dataset.state;
    }

    function ocrReviewClearFallback() {
      if (!ocrFallbackEl) return;
      ocrFallbackEl.hidden = true;
      ocrFallbackEl.replaceChildren();
    }

    function ocrReviewFocusManualAnswers() {
      const details = document.getElementById('tsAnswersDetails');
      if (details) details.open = true;
      ocrReviewEnsureAnswersTextLineCount();
      try { answersTextEl.focus(); } catch {}
      try { answersTextEl.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}
    }

    function ocrReviewRenderFallback(message) {
      if (!ocrFallbackEl) return;
      ocrFallbackEl.replaceChildren();
      const title = document.createElement('strong');
      title.textContent = '직접 입력으로 계속할 수 있습니다';
      const copy = document.createElement('p');
      copy.textContent = '다른 사진을 선택하거나, 20줄 답안칸에 직접 입력해 계속할 수 있습니다.';
      const actions = document.createElement('div');
      actions.className = 'ts-ocr-fallback-actions';
      const chooseImage = document.createElement('button');
      chooseImage.type = 'button';
      chooseImage.className = 'ts-ocr-fallback-action';
      chooseImage.textContent = '다른 사진 선택';
      chooseImage.addEventListener('click', () => {
        try { ocrReviewImageEl?.click(); } catch {}
      });
      const manualInput = document.createElement('button');
      manualInput.type = 'button';
      manualInput.className = 'ts-ocr-fallback-action';
      manualInput.textContent = '답안 직접 입력';
      manualInput.addEventListener('click', ocrReviewFocusManualAnswers);
      actions.append(chooseImage, manualInput);
      ocrFallbackEl.append(title, copy, actions);
      ocrFallbackEl.hidden = false;
    }

    function ocrReviewSafeFailureMessage(message) {
      const text = String(message || '').trim();
      if (
        text.includes('학생이 확인할 수 있는 인식 결과가 준비되지 않았습니다.') ||
        text.startsWith('인식 요청이') ||
        text.startsWith('인식 서비스를') ||
        text.startsWith('사진') ||
        text.startsWith('답안지') ||
        text.startsWith('현재 학생')
      ) return text;
      return '학생이 확인할 수 있는 인식 결과가 준비되지 않았습니다. 사진을 다시 선택하거나 답안을 직접 입력해 주세요.';
    }

    function ocrPhase1CurrentTest() {
      return findTestById(selType.value, selTestId.value, currentCur());
    }

    function ocrReviewCurrentSelectionContext() {
      const test = ocrPhase1CurrentTest();
      const round = parseInt(test?.round || selRound.value, 10) || 1;
      return {
        testId: String(test?.id || selTestId.value || '').trim(),
        round: String(round),
      };
    }

    function ocrReviewClearAnswersTextOrigin() {
      delete answersTextEl.dataset.ocrFilled;
      delete answersTextEl.dataset.ocrTestId;
      delete answersTextEl.dataset.ocrRound;
    }

    function ocrReviewAnswersTextContextMatches() {
      if (answersTextEl.dataset.ocrFilled !== '1') return true;
      const current = ocrReviewCurrentSelectionContext();
      return answersTextEl.dataset.ocrTestId === current.testId && answersTextEl.dataset.ocrRound === current.round;
    }

    function ocrReviewClearStaleAnswersText(message = '') {
      if (ocrReviewAnswersTextContextMatches()) return false;
      answersTextEl.value = '';
      ocrReviewClearAnswersTextOrigin();
      if (message) ocrTestSheetSetStatus(message, 'error');
      return true;
    }

    function ocrReviewApplyAnswersText(result, options = {}) {
      const current = ocrReviewCurrentSelectionContext();
      const resultTestId = String(result.testId || current.testId);
      const resultRound = String(result.round || current.round);
      if (resultTestId !== current.testId || resultRound !== current.round) {
        throw new Error('사진 인식 결과가 현재 선택한 시험/회차와 맞지 않습니다. 다시 인식해주세요.');
      }
      const preserveExisting = options.preserveExisting === true;
      const nextLines = ocrReviewNormalizeAnswerLines(result.answersText);
      if (preserveExisting) {
        const currentLines = ocrReviewNormalizeAnswerLines(answersTextEl.value);
        nextLines.forEach((line, index) => {
          if (String(currentLines[index] || '').trim()) nextLines[index] = currentLines[index];
        });
      }
      answersTextEl.dataset.ocrProgrammaticFill = '1';
      answersTextEl.value = nextLines.join('\n');
      answersTextEl.dataset.ocrFilled = '1';
      answersTextEl.dataset.ocrTestId = resultTestId;
      answersTextEl.dataset.ocrRound = resultRound;
      answersTextEl.dispatchEvent(new Event('input', { bubbles: true }));
      delete answersTextEl.dataset.ocrProgrammaticFill;
      ocrReviewRefreshUnresolvedSummary();
    }

    function ocrPhase1TestEligible(test = null) {
      if (test && typeof test === 'object') return isOcrPhase1AllowedTest(test);
      return isOcrPhase1AllowedTestId(selTestId.value);
    }

    function ocrPhase1UpdateEligibilityState() {
      if (!OCR_TEST_SHEET_ENABLED) return false;
      const allowed = ocrPhase1TestEligible(ocrPhase1CurrentTest());
      if (btnOcrReviewOpen) {
        btnOcrReviewOpen.hidden = !allowed;
        btnOcrReviewOpen.disabled = !allowed;
        if (allowed) {
          btnOcrReviewOpen.removeAttribute('aria-disabled');
          btnOcrReviewOpen.removeAttribute('title');
        } else {
          btnOcrReviewOpen.setAttribute('aria-disabled', 'true');
          btnOcrReviewOpen.title = OCR_PHASE1_INELIGIBLE_MESSAGE;
        }
      }
      if (ocrReviewImageEl) {
        ocrReviewImageEl.hidden = !allowed;
        ocrReviewImageEl.disabled = !allowed;
      }
      if (ocrReviewFileControlEl) ocrReviewFileControlEl.hidden = !allowed;
      if (btnOcrReviewPick) btnOcrReviewPick.disabled = !allowed;
      if (!allowed) {
        ocrReviewPayload = null;
        ocrReviewClearPanel();
        ocrReviewClearFallback();
        ocrTestSheetSetStatus(OCR_PHASE1_INELIGIBLE_MESSAGE, 'error');
      } else {
        const currentStatus = String(ocrStatusEl?.textContent || '').trim();
        if ((currentStatus === OCR_PHASE1_INELIGIBLE_MESSAGE || !currentStatus) && !ocrReviewSelectedImage() && !ocrReviewPayload) {
          ocrTestSheetSetStatus(OCR_PHASE1_READY_MESSAGE);
        }
      }
      return allowed;
    }

    function ocrReviewClearPanel() {
      if (!ocrReviewPanel) return;
      ocrReviewPanel.hidden = true;
      ocrReviewPanel.replaceChildren();
      ocrReviewStartedAt = 0;
    }

    function ocrTestSheetResetControls() {
      ocrReviewPayload = null;
      if (ocrReviewImageEl) ocrReviewImageEl.value = '';
      ocrReviewUpdateSelectedImageDisplay();
      ocrReviewClearAnswersTextOrigin();
      ocrTestSheetSetStatus();
      ocrReviewClearPanel();
      ocrReviewClearFallback();
    }

    function ocrReviewClone(value) {
      return JSON.parse(JSON.stringify(value));
    }

    function ocrReviewFindForbiddenKeys(value, path = '$', out = []) {
      if (Array.isArray(value)) {
        value.forEach((item, index) => ocrReviewFindForbiddenKeys(item, `${path}[${index}]`, out));
        return out;
      }
      if (value && typeof value === 'object') {
        Object.entries(value).forEach(([key, child]) => {
          const nextPath = `${path}.${key}`;
          if (OCR_REVIEW_ANSWER_KEY_FIELDS.has(key)) out.push(nextPath);
          ocrReviewFindForbiddenKeys(child, nextPath, out);
        });
      }
      return out;
    }

    function ocrReviewValueLooksLikePath(value) {
      const text = String(value || '').trim();
      if (!text) return false;
      if (/^[a-zA-Z]:[\\/]/.test(text)) return true;
      if (/^\\\\[^\\]+\\[^\\]+/.test(text)) return true;
      if (/^file:\/\//i.test(text)) return true;
      return /^\/(?:Users|home|var|tmp|server|mnt|opt|private)\//.test(text);
    }

    function ocrReviewFindForbiddenPathValues(value, path = '$', out = []) {
      if (typeof value === 'string') {
        if (ocrReviewValueLooksLikePath(value)) out.push(path);
        return out;
      }
      if (Array.isArray(value)) {
        value.forEach((item, index) => ocrReviewFindForbiddenPathValues(item, `${path}[${index}]`, out));
        return out;
      }
      if (value && typeof value === 'object') {
        Object.entries(value).forEach(([key, child]) => {
          ocrReviewFindForbiddenPathValues(child, `${path}.${key}`, out);
        });
      }
      return out;
    }

    function ocrReviewAnswerModeForQuestion(testId, questionNo) {
      const no = Number(questionNo);
      const config = OCR_PHASE1_ANSWER_MODE_BY_TEST_ID[String(testId || '').trim()];
      if (!config || !Number.isInteger(no)) return '';
      if (config.choice_number.has(no)) return 'choice_number';
      if (config.answer_value.has(no)) return 'answer_value';
      return '';
    }

    function ocrReviewAnswerModeLabel(mode) {
      return OCR_REVIEW_ANSWER_MODE_LABELS[mode] || '답안 형식 확인';
    }

    function ocrReviewIsChoiceNumberAnswer(answer) {
      return /^[1-5]$/.test(String(answer || '').trim());
    }

    function ocrReviewIsSimpleFinalAnswer(answer) {
      return /^[-+]?\d+(?:\/\d+|\.\d+)?$/.test(String(answer || '').trim());
    }

    function ocrReviewQuestionListText(questionNumbers) {
      return questionNumbers.map(no => `${no}번`).join(', ');
    }

    function ocrReviewNormalizeStringArray(value, label, questionNo) {
      const values = Array.isArray(value) ? value : [];
      return values.map(item => {
        const text = String(item);
        if (/[\r\n]/.test(text)) throw new Error(`${questionNo}번 문항 ${label}은 한 줄이어야 합니다.`);
        return text;
      });
    }

    function ocrReviewCandidateCanShow(answer, mode) {
      const text = ocrReviewCleanOneLineAnswer(answer);
      if (!ocrReviewHasReliableText(text)) return false;
      if (mode === 'choice_number') return ocrReviewIsChoiceNumberAnswer(text);
      if (mode === 'answer_value') return ocrReviewIsSimpleFinalAnswer(text);
      return ocrReviewIsSimpleFinalAnswer(text);
    }

    function ocrReviewCandidateValuesForItem(item, mode) {
      const values = ocrReviewNormalizeStringArray(item.candidates, '후보 답안', Number(item.question_no));
      const out = [];
      values.forEach(value => {
        const text = ocrReviewCleanOneLineAnswer(value);
        if (ocrReviewCandidateCanShow(text, mode) && !out.includes(text)) out.push(text);
      });
      return out;
    }

    function ocrReviewIsLocalCandidateItem(payloadSource, warnings) {
      if (OCR_REVIEW_LOCAL_CANDIDATE_SOURCES.has(String(payloadSource || '').trim())) return true;
      return warnings.includes('local_ocr_unverified') || warnings.includes('local_ocr_low_confidence');
    }

    function ocrReviewApplyLocalCandidatePolicy(item, payloadSource) {
      if (!ocrReviewIsLocalCandidateItem(payloadSource, item.warnings)) return item;
      const candidates = [...item.candidates];
      const recognizedCandidate = ocrReviewCleanOneLineAnswer(item.recognized);
      if (ocrReviewCandidateCanShow(recognizedCandidate, item.answer_mode) && !candidates.includes(recognizedCandidate)) {
        candidates.unshift(recognizedCandidate);
      }
      if (item.review_state === 'retake_required') {
        return {
          ...item,
          candidates,
          final_answer: null,
          resolution: 'unresolved',
          status: 'retake_required',
        };
      }
      if (ocrReviewIsUserConfirmedStatus(item)) return { ...item, candidates };
      return {
        ...item,
        review_state: 'review_recommended',
        resolution: 'unresolved',
        status: 'review_recommended',
        candidates,
        final_answer: null,
        source: null,
      };
    }

    function ocrReviewHasTraceWarning(warnings) {
      return warnings.some(warning => OCR_REVIEW_TRACE_WARNING_CODES.has(warning));
    }

    function ocrReviewHasReliableText(value) {
      const text = String(value || '').trim().toLowerCase();
      return text !== '' && text !== '?' && text !== '??' && text !== 'unknown' && text !== 'unclear';
    }

    function ocrReviewCleanOneLineAnswer(value) {
      const text = String(value || '').trim();
      if (text.includes(String.fromCharCode(10)) || text.includes(String.fromCharCode(13))) return text;
      return text
        .replace(/\s+/g, '')
        .replace(/\sqrt/gi, '√')
        .replace(/sqrt\(([^()]*)\)/gi, '√$1')
        .replace(/sqrt\{([^{}]*)\}/gi, '√$1')
        .replace(/sqrt/gi, '√');
    }

    function ocrReviewAnswerCanPrefill(answer, mode) {
      const text = ocrReviewCleanOneLineAnswer(answer);
      if (!ocrReviewHasReliableText(text)) return false;
      if (mode === 'choice_number') return ocrReviewIsChoiceNumberAnswer(text);
      if (mode === 'answer_value') return ocrReviewIsSimpleFinalAnswer(text);
      return ocrReviewIsSimpleFinalAnswer(text);
    }

    function ocrReviewDefaultAnswerForReviewInput(item) {
      if (item.status === 'review_required') {
        const candidates = item.candidates
          .map(candidate => ocrReviewCleanOneLineAnswer(candidate))
          .filter(candidate => ocrReviewCandidateCanShow(candidate, item.answer_mode));
        if (candidates.length < 2) return '';
        const recognized = ocrReviewCleanOneLineAnswer(item.recognized || '');
        return candidates.includes(recognized) ? recognized : candidates[0];
      }
      const answer = ocrReviewCleanOneLineAnswer(item.final_answer || '');
      return ocrReviewAnswerCanPrefill(answer, item.answer_mode) ? answer : '';
    }

    function ocrReviewPrefillNoticeText(item, recognizedAnswer, initialAnswer) {
      if (initialAnswer || item.status !== 'review_required') return '';
      if (!ocrReviewHasReliableText(recognizedAnswer)) return '인식값이 명확하지 않아 빈칸으로 두었습니다. 직접 입력해주세요.';
      if (item.answer_mode === 'choice_number') return '인식값이 선택형 형식에 맞지 않아 빈칸으로 두었습니다. 아래 번호 중 하나를 선택해주세요.';
      if (item.answer_mode === 'answer_value') return '인식값이 답값 형식에 맞지 않아 빈칸으로 두었습니다. 최종 답만 입력해주세요.';
      return '';
    }

    function ocrReviewAnswerValidationMessage(answer, mode, questionNo) {
      const text = ocrReviewCleanOneLineAnswer(answer);
      if (!text) return `${questionNo}번 문항 답안을 입력해주세요.`;
      if (/[\r\n]/.test(text)) return `${questionNo}번 문항 답안은 한 줄이어야 합니다.`;
      if (mode === 'choice_number' && !ocrReviewIsChoiceNumberAnswer(text)) {
        return `${questionNo}번 선택형 문항은 선지 번호(1~5)만 입력해야 합니다.`;
      }
      if (!mode && !ocrReviewIsSimpleFinalAnswer(text)) {
        return `${questionNo}번 문항은 자동 확인 가능한 숫자/분수/소수 답만 입력할 수 있습니다.`;
      }
      return '';
    }

    function ocrReviewHasBulkFillBlockingWarning(item) {
      if (item.warnings.some(warning => OCR_REVIEW_BULK_FILL_BLOCKING_WARNING_CODES.has(warning))) return true;
      return item.warnings.some(warning => /지운|덧쓴|취소|여러|복수|애매|불명확|명확하지|unclear|ambiguous|overwritten|erased|crossed/i.test(String(warning || '')));
    }

    function ocrReviewCandidatesAreUnambiguous(item, answer) {
      const candidates = item.candidates.map(candidate => ocrReviewCleanOneLineAnswer(candidate)).filter(Boolean);
      return !candidates.length || candidates.every(candidate => candidate === answer);
    }

    function ocrReviewBulkFillBlockingMessage(item) {
      if (item.warnings.includes('choice_number_invalid_for_auto_grade')) {
        return `${item.question_no}번 선택형 문항은 선지 번호(1~5)만 입력할 수 있어 직접 확정해야 합니다.`;
      }
      if (item.warnings.includes('answer_value_letter_confusion')) {
        return `${item.question_no}번 문항은 답값이 글자처럼 보여 직접 확정해야 합니다.`;
      }
      if (item.warnings.includes('digit_shape_confusion')) {
        return `${item.question_no}번 문항은 숫자 모양이 애매해 직접 확정해야 합니다.`;
      }
      if (item.warnings.includes('answer_mode_unverified')) {
        return `${item.question_no}번 문항은 문항 형식표가 아직 없어 직접 확정해야 합니다.`;
      }
      if (item.warnings.includes('local_checker_blank_conflict') || item.warnings.includes('tesseract_blank_like')) {
        return `${item.question_no}번 문항은 보조 인식에서 빈칸처럼 보여 직접 확정해야 합니다.`;
      }
      if (item.warnings.includes('tesseract_choice_digit_veto') || item.warnings.includes('tesseract_multiple_choice_candidates')) {
        return `${item.question_no}번 선택형 문항은 보조 인식 결과 선지 번호가 명확하지 않아 직접 확정해야 합니다.`;
      }
      if (item.warnings.includes('tesseract_multiple_candidates') || item.warnings.includes('tesseract_answer_value_format_conflict')) {
        return `${item.question_no}번 문항은 보조 인식 결과 답값 형식이 맞지 않아 직접 확정해야 합니다.`;
      }
      if (
        item.warnings.includes('local_checker_candidate_conflict') ||
        item.warnings.includes('tesseract_candidate_conflict') ||
        item.warnings.includes('paddleocr_candidate_conflict') ||
        item.warnings.includes('pix2tex_candidate_conflict')
      ) {
        return `${item.question_no}번 문항은 서로 다른 인식 후보가 보여 직접 확정해야 합니다.`;
      }
      return `${item.question_no}번 문항은 지운 흔적, 덧쓴 흔적, 또는 기호 애매함이 있어 직접 확정해야 합니다.`;
    }

    function ocrReviewBlockerMessage(item) {
      if (item.status === 'review_required') {
        const answer = ocrReviewCleanOneLineAnswer(item.recognized);
        const validationMessage = ocrReviewAnswerValidationMessage(answer, item.answer_mode, item.question_no);
        if (!ocrReviewHasReliableText(answer)) return `${item.question_no}번 문항 인식값이 명확하지 않습니다. 직접 확인해주세요.`;
        if (ocrReviewHasBulkFillBlockingWarning(item)) return ocrReviewBulkFillBlockingMessage(item);
        if (validationMessage) return validationMessage;
        return `${item.question_no}번 문항을 먼저 확정해야 합니다.`;
      }
      if (item.status === 'data_check_required') return `${item.question_no}번 문항은 선생님 확인이 필요합니다.`;
      if (item.status === 'retake_required' || item.status === 'retake_uploaded') return `${item.question_no}번 문항은 재촬영 또는 재인식이 필요합니다.`;
      return `${item.question_no}번 문항을 먼저 처리해야 합니다.`;
    }

    function ocrReviewTraceNeedsRetake(item) {
      if (!item.warnings.includes('unclear_final_answer')) return false;
      if (ocrReviewHasReliableText(item.final_answer) || ocrReviewHasReliableText(item.recognized)) return false;
      return !item.candidates.some(candidate => ocrReviewHasReliableText(candidate));
    }

    function ocrReviewApplyTraceSafetyPolicy(item) {
      const autoGradeStatus = OCR_REVIEW_AUTO_GRADE_STATUSES.has(item.status) || OCR_REVIEW_AUTO_GRADE_STATUSES.has(item.source);
      if (!autoGradeStatus || !ocrReviewHasTraceWarning(item.warnings)) return item;
      return {
        ...item,
        status: ocrReviewTraceNeedsRetake(item) ? 'retake_required' : 'review_required',
        final_answer: null,
        source: null,
      };
    }

    function ocrReviewWarningMessages(item) {
      const messages = [];
      item.warnings.forEach(warning => {
        const message = OCR_REVIEW_WARNING_MESSAGES[warning] || warning;
        if (message && !messages.includes(message)) messages.push(message);
      });
      return messages;
    }

    function ocrReviewWarningLabels(item) {
      const labels = [];
      item.warnings.forEach(warning => {
        if (warning === 'local_ocr_unverified' || warning === 'local_ocr_low_confidence') return;
        const label = OCR_REVIEW_WARNING_LABELS[warning] || warning;
        if (label && !labels.includes(label)) labels.push(label);
      });
      return labels;
    }

    function ocrReviewRenderReasonChips(item) {
      const labels = ocrReviewWarningLabels(item);
      if (!labels.length) return null;
      const wrap = document.createElement('div');
      wrap.className = 'ts-ocr-reason-row';
      labels.forEach(label => {
        const chip = document.createElement('span');
        chip.className = 'ts-ocr-reason-chip';
        chip.textContent = label;
        wrap.appendChild(chip);
      });
      return wrap;
    }

    function ocrReviewRenderWarnings(item) {
      const messages = ocrReviewWarningMessages(item);
      if (!messages.length) return null;
      const warning = document.createElement('div');
      warning.className = 'ts-ocr-warning';
      warning.textContent = messages.join(' ');
      return warning;
    }

    function ocrReviewFindQuestionsByWarning(items, warningCodes) {
      return items
        .filter(item => item.warnings.some(warning => warningCodes.has(warning)))
        .map(item => item.question_no);
    }

    function ocrReviewGuideEntries(payload, counts, fillPreview) {
      const entries = [];
      const overwrittenQuestions = ocrReviewFindQuestionsByWarning(payload.items, new Set(['erased_trace_detected', 'crossed_out_answer', 'overwritten_answer', 'unclear_final_answer']));
      if (overwrittenQuestions.length) {
        entries.push({
          tone: 'warning',
          title: '지운 흔적 또는 덧쓴 흔적 확인',
          body: `${ocrReviewQuestionListText(overwrittenQuestions)}은(는) 흔적이 남아 있어 자동으로 채우지 않습니다. 학생이 직접 답을 확정해야 합니다.`,
        });
      }
      const choiceFormatQuestions = ocrReviewFindQuestionsByWarning(payload.items, new Set(['choice_number_invalid_for_auto_grade']));
      if (choiceFormatQuestions.length) {
        entries.push({
          tone: 'warning',
          title: '선택형 번호 직접 확인',
          body: `${ocrReviewQuestionListText(choiceFormatQuestions)}은(는) 선택형 번호 형식이 맞지 않아 아래 1~5 버튼으로 다시 골라야 합니다.`,
        });
      }
      const retakeQuestions = payload.items
        .filter(item => item.status === 'retake_required' || item.status === 'retake_uploaded')
        .map(item => item.question_no);
      if (retakeQuestions.length) {
        entries.push({
          tone: 'danger',
          title: '재촬영 또는 재인식 권장',
          body: `${ocrReviewQuestionListText(retakeQuestions)}은(는) 사진 품질 때문에 학생 화면에서 바로 확정하지 않는 편이 안전합니다.`,
        });
      }
      if (fillPreview.blankQuestions.length) {
        entries.push({
          tone: 'default',
          title: '빈칸으로 남는 문항',
          body: `${ocrReviewQuestionListText(fillPreview.blankQuestions)}은(는) 답칸 채우기 버튼을 눌러도 비워 둡니다. 확인 카드부터 처리한 뒤 제출 버튼은 마지막에만 사용해주세요.`,
        });
      }
      if (!entries.length && counts.safe) {
        entries.push({
          tone: 'default',
          title: '확인된 답안 채우기 준비 완료',
          body: `확인 완료 ${counts.safe}개를 답칸에 채울 수 있습니다. 제출은 기존 제출 버튼에서만 진행됩니다.`,
        });
      }
      return entries;
    }

    function ocrReviewRenderGuideList(payload, counts, fillPreview) {
      const entries = ocrReviewGuideEntries(payload, counts, fillPreview);
      if (!entries.length) return null;
      const wrap = document.createElement('div');
      wrap.className = 'ts-ocr-guide-list';
      entries.forEach(entry => {
        const guide = document.createElement('section');
        guide.className = 'ts-ocr-guide';
        if (entry.tone && entry.tone !== 'default') guide.dataset.tone = entry.tone;
        const title = document.createElement('strong');
        title.textContent = entry.title;
        const body = document.createElement('span');
        body.textContent = entry.body;
        guide.append(title, body);
        wrap.appendChild(guide);
      });
      return wrap;
    }

    function ocrReviewRenderSection(titleText, items, renderer) {
      if (!items.length) return null;
      const wrap = document.createElement('section');
      wrap.className = 'ts-ocr-section';
      const title = document.createElement('h5');
      title.textContent = titleText;
      wrap.appendChild(title);
      items.forEach(item => wrap.appendChild(renderer(item)));
      return wrap;
    }

    function ocrReviewLegacyReviewState(item) {
      const status = String(item?.status || '');
      if (status === 'retake_required' || status === 'retake_uploaded') return 'retake_required';
      if (status === 'data_check_required') return 'direct_input';
      return 'review_recommended';
    }

    function ocrReviewLegacyResolution(item, reviewState) {
      const status = String(item?.status || '');
      if (status === 'confirmed' || status === 'student_selected_candidate' || status === 'student_selected_candidate_after_retake') {
        return 'student_confirmed';
      }
      if (status === 'student_direct_input' || status === 'student_direct_input_after_retake') return 'student_entered';
      return 'unresolved';
    }

    function ocrReviewCandidateValuesFromContract(item, answerMode, questionNo) {
      const rawValues = [];
      const candidate = item?.candidate;
      if (typeof candidate === 'string' || typeof candidate === 'number') rawValues.push(candidate);
      else if (candidate && typeof candidate === 'object') rawValues.push(candidate.value ?? candidate.answer ?? '');
      if (Array.isArray(item?.candidates)) rawValues.push(...item.candidates);
      if (!rawValues.some(value => ocrReviewHasReliableText(value))) {
        rawValues.push(item?.recognized ?? '', item?.final_answer ?? '');
      }
      const out = [];
      rawValues.forEach(value => {
        const text = ocrReviewCleanOneLineAnswer(value);
        if (ocrReviewCandidateCanShow(text, answerMode) && !out.includes(text)) out.push(text);
      });
      return out;
    }

    function ocrReviewWarningsFromContract(item, questionNo) {
      const rawWarnings = item?.warning ?? item?.warnings ?? [];
      const warnings = Array.isArray(rawWarnings) ? rawWarnings : [rawWarnings];
      return ocrReviewNormalizeStringArray(warnings, '경고 문구', questionNo).filter(Boolean);
    }

    function ocrReviewSafeCropPreview(value, questionNo, strict) {
      if (value == null || value === '') {
        if (strict) throw new Error(`${questionNo}번 문항 원본 사진 정보가 없습니다.`);
        return null;
      }
      if (typeof value !== 'string') throw new Error(`${questionNo}번 문항 원본 사진 정보가 올바르지 않습니다.`);
      const preview = value.trim();
      const dataImage = /^data:image\/(?:png|jpeg|webp);base64,[a-z0-9+/=\s]+$/i.test(preview);
      const sameOriginReviewImage = /^\/api\/ocr-[a-z0-9_\-/]+(?:\?[a-z0-9_=&-]+)?$/i.test(preview);
      if (!dataImage && !sameOriginReviewImage) throw new Error(`${questionNo}번 문항 원본 사진 정보가 안전하지 않습니다.`);
      return preview;
    }

    function ocrReviewHumanRetakeReason(item) {
      const raw = String(item?.retake_reason || '').trim();
      if (raw) return raw;
      const warnings = Array.isArray(item?.warnings) ? item.warnings : [];
      if (warnings.some(value => /blur|흐림/i.test(String(value)))) return '흐림';
      if (warnings.some(value => /cutoff|cut|잘림/i.test(String(value)))) return '잘림';
      if (warnings.some(value => /shadow|exposure|contrast|그림자/i.test(String(value)))) return '그림자';
      if (warnings.some(value => /overwritten|erased|multiple|겹침/i.test(String(value)))) return '답안 겹침';
      return '사진 품질 확인 필요';
    }

    function ocrReviewNormalizePayload(raw) {
      const leaks = ocrReviewFindForbiddenKeys(raw);
      if (leaks.length) throw new Error(`학생 화면에 노출할 수 없는 필드가 포함되어 있습니다: ${leaks.join(', ')}`);
      if (!raw || typeof raw !== 'object') throw new Error('학생이 확인할 수 있는 인식 결과가 준비되지 않았습니다. 답안을 직접 입력해 주세요.');
      const pathLeaks = ocrReviewFindForbiddenPathValues(raw);
      if (pathLeaks.length) throw new Error('학생 화면에 노출할 수 없는 경로 정보가 포함되어 있습니다.');
      const items = Array.isArray(raw.items) ? raw.items : [];
      const isSharedFourStateContract = Object.prototype.hasOwnProperty.call(raw, 'case_id') ||
        Object.prototype.hasOwnProperty.call(raw, 'item_count') ||
        items.some(item => Object.prototype.hasOwnProperty.call(item || {}, 'requires_action'));
      if (isSharedFourStateContract) {
        ['test_id', 'round', 'case_id', 'item_count', 'items'].forEach(field => {
          if (!Object.prototype.hasOwnProperty.call(raw, field)) throw new Error(`공용 검토 정보에 ${field} 항목이 없습니다.`);
        });
        if (typeof raw.case_id !== 'string' || !raw.case_id.trim()) throw new Error('공용 검토 정보의 사례 식별자가 올바르지 않습니다.');
      }
      const problemCount = Number(isSharedFourStateContract ? raw.item_count : raw.problem_count || OCR_REVIEW_PROBLEM_COUNT);
      if (problemCount !== OCR_REVIEW_PROBLEM_COUNT) throw new Error('문항 수가 맞지 않습니다.');
      if (items.length !== problemCount) throw new Error('문항 목록이 20개가 아닙니다.');
      const testId = String(raw.test_id || raw.testId || '');
      const round = String(raw.round || '');
      if (!testId || !round) throw new Error('시험 또는 회차 정보가 없습니다.');
      const seen = new Set();
      items.forEach(item => {
        const no = Number(item?.question_no);
        if (!Number.isInteger(no) || no < 1 || no > problemCount) throw new Error('문항 번호가 올바르지 않습니다.');
        if (seen.has(no)) throw new Error(`${no}번 문항이 중복되었습니다.`);
        seen.add(no);
        const isLegacyFourStateContract = !isSharedFourStateContract && Object.prototype.hasOwnProperty.call(item || {}, 'review_state');
        if (isSharedFourStateContract) {
          ['status', 'candidate', 'warning', 'crop_preview', 'requires_action', 'allow_edit'].forEach(field => {
            if (!Object.prototype.hasOwnProperty.call(item || {}, field)) throw new Error(`${no}번 문항 ${field} 정보가 없습니다.`);
          });
          const status = String(item.status || '');
          if (!OCR_REVIEW_SELF_REVIEW_STATES.has(status)) throw new Error(`${no}번 문항 검토 상태가 올바르지 않습니다.`);
          if (typeof item.allow_edit !== 'boolean' || typeof item.requires_action !== 'boolean') {
            throw new Error(`${no}번 문항 수정 또는 확인 설정이 올바르지 않습니다.`);
          }
          if (!item.allow_edit) throw new Error(`${no}번 문항에 학생 입력 수단이 없습니다.`);
          if ((status === 'auto_confirm') !== (item.requires_action === false)) {
            throw new Error(`${no}번 문항 자동 반영 설정이 상태와 맞지 않습니다.`);
          }
          ocrReviewSafeCropPreview(item.crop_preview, no, true);
          return;
        }
        if (isLegacyFourStateContract) {
          ['candidate', 'warning', 'crop_preview', 'allow_edit', 'requires_confirmation', 'retake_reason'].forEach(field => {
            if (!Object.prototype.hasOwnProperty.call(item, field)) throw new Error(`${no}번 문항 ${field} 정보가 없습니다.`);
          });
          if (!OCR_REVIEW_SELF_REVIEW_STATES.has(String(item.review_state || ''))) {
            throw new Error(`${no}번 문항 검토 상태가 올바르지 않습니다.`);
          }
          if (typeof item.allow_edit !== 'boolean' || typeof item.requires_confirmation !== 'boolean') {
            throw new Error(`${no}번 문항 수정 또는 확인 설정이 올바르지 않습니다.`);
          }
          if (!item.allow_edit) throw new Error(`${no}번 문항에 학생 입력 수단이 없습니다.`);
          if (typeof item.retake_reason !== 'string') throw new Error(`${no}번 문항 재촬영 사유가 올바르지 않습니다.`);
          return;
        }
        const status = String(item?.status || '');
        if (!OCR_REVIEW_FINAL_STATUSES.has(status) && !OCR_REVIEW_BLOCKING_STATUSES.has(status)) {
          throw new Error(`${no}번 문항 상태가 올바르지 않습니다.`);
        }
      });
      const payloadSource = String(raw.source || 'phase1_local_mock_review_payload');
      return {
        source: payloadSource,
        test_id: testId,
        round,
        ...(isSharedFourStateContract ? {
          case_id: raw.case_id.trim(),
          item_count: problemCount,
        } : {}),
        problem_count: problemCount,
        items: items.map(item => {
          const no = Number(item.question_no);
          const answerMode = ocrReviewAnswerModeForQuestion(testId, no);
          const isLegacyFourStateContract = !isSharedFourStateContract && Object.prototype.hasOwnProperty.call(item, 'review_state');
          const usesExplicitStateContract = isSharedFourStateContract || isLegacyFourStateContract;
          const rawReviewState = isSharedFourStateContract
            ? String(item.status || '')
            : isLegacyFourStateContract ? String(item.review_state || '') : ocrReviewLegacyReviewState(item);
          let warnings = ocrReviewWarningsFromContract(item, no);
          const candidates = isSharedFourStateContract
            ? ocrReviewCandidateValuesFromContract({ candidate: item.candidate }, answerMode, no)
            : ocrReviewCandidateValuesFromContract(item, answerMode, no);
          let reviewState = rawReviewState;
          const suppliedResolution = String(item.resolution || '');
          let resolution = isSharedFourStateContract
            ? reviewState === 'auto_confirm' ? 'auto_confirm' : 'unresolved'
            : isLegacyFourStateContract && OCR_REVIEW_RESOLVED_STATES.has(suppliedResolution)
            ? suppliedResolution
            : isLegacyFourStateContract ? 'unresolved' : ocrReviewLegacyResolution(item, reviewState);
          let finalAnswer = isSharedFourStateContract || item.final_answer == null ? null : ocrReviewCleanOneLineAnswer(item.final_answer);
          const candidate = candidates[0] || '';
          if (!usesExplicitStateContract && OCR_REVIEW_AUTO_GRADE_STATUSES.has(String(item.status || ''))) {
            warnings = Array.from(new Set([...warnings, 'auto_confirm_policy_unverified']));
          }
          if (reviewState === 'auto_confirm') {
            const automaticAnswer = ocrReviewCleanOneLineAnswer(finalAnswer || candidate);
            if (!ocrReviewAnswerCanPrefill(automaticAnswer, answerMode) || ocrReviewHasTraceWarning(warnings)) {
              if (isSharedFourStateContract) throw new Error(`${no}번 문항 자동 반영 정보가 안전하지 않습니다.`);
              reviewState = 'direct_input';
              resolution = 'unresolved';
              finalAnswer = null;
            } else {
              finalAnswer = automaticAnswer;
              resolution = resolution === 'student_edited' ? 'student_edited' : 'auto_confirm';
            }
          } else if (OCR_REVIEW_RESOLVED_STATES.has(resolution)) {
            const resolvedAnswer = ocrReviewCleanOneLineAnswer(finalAnswer || candidate);
            if (!ocrReviewAnswerCanPrefill(resolvedAnswer, answerMode)) {
              resolution = 'unresolved';
              finalAnswer = null;
            } else {
              finalAnswer = resolvedAnswer;
            }
          } else {
            finalAnswer = null;
          }
          const normalizedItem = {
            question_no: no,
            answer_mode: answerMode,
            review_state: reviewState,
            resolution,
            status: resolution === 'unresolved' ? reviewState : resolution,
            recognized: String(item.recognized || candidate || ''),
            candidate,
            warning: warnings,
            warnings,
            candidates,
            crop_preview: ocrReviewSafeCropPreview(item.crop_preview, no, usesExplicitStateContract),
            allow_edit: usesExplicitStateContract ? item.allow_edit === true : true,
            requires_confirmation: isSharedFourStateContract ? item.requires_action : isLegacyFourStateContract ? item.requires_confirmation : reviewState !== 'auto_confirm',
            retake_reason: ocrReviewHumanRetakeReason({ ...item, warnings }),
            user_modified: false,
            final_answer: finalAnswer,
            source: isSharedFourStateContract || item.source == null ? null : String(item.source),
          };
          if (usesExplicitStateContract) return normalizedItem;
          return ocrReviewApplyTraceSafetyPolicy(ocrReviewApplyLocalCandidatePolicy(normalizedItem, payloadSource));
        }).sort((a, b) => a.question_no - b.question_no),
      };
    }

    function ocrReviewCreateMockPayload(test, round) {
      const baseAnswers = ['1', '-3', 'x=n', '0.5', '2', 'ㄴ,ㄹ', '5', '2x+1', '4', '6', '256', 'a/2', '5', '1', '-1<x<5', 'y=n', '2', '139/2', 'x±2=4', '26sqrt(21)'];
      const reviewItems = new Map([
        [3, ['x=2', '3', 'x=n', 'x=?']],
        [10, ['0', '6', '?']],
        [18, ['129/2', '139/2', '?']],
        [19, ['x+2=4', '3', 'x±2=4', 'x-2=4']],
      ]);
      return ocrReviewNormalizePayload({
        source: 'versioned_auto_confirm_mock_review_payload',
        test_id: String(test?.id || selTestId.value || 'mock_subjective_test'),
        round: String(round || '1'),
        problem_count: OCR_REVIEW_PROBLEM_COUNT,
        items: baseAnswers.map((answer, index) => {
          const questionNo = index + 1;
          const candidates = reviewItems.get(questionNo);
          if (candidates) {
            return {
              question_no: questionNo,
              review_state: 'review_recommended',
              recognized: answer,
              candidate: answer,
              warning: ['확인이 필요한 인식값입니다.'],
              candidates,
              crop_preview: 'data:image/png;base64,iVBORw0KGgo=',
              allow_edit: true,
              requires_confirmation: true,
              retake_reason: '',
              resolution: 'unresolved',
              final_answer: null,
              source: null,
            };
          }
          return {
            question_no: questionNo,
            review_state: 'auto_confirm',
            recognized: answer,
            candidate: answer,
            warning: [],
            candidates: [answer],
            crop_preview: 'data:image/png;base64,iVBORw0KGgo=',
            allow_edit: true,
            requires_confirmation: false,
            retake_reason: '',
            resolution: 'auto_confirm',
            final_answer: answer,
            source: 'auto_confirm_mock_fixture',
          };
        }),
      });
    }

    function ocrReviewBlockingItems(payload) {
      const stateOrder = {
        retake_required: 0,
        direct_input: 1,
        review_recommended: 2,
      };
      return payload.items
        .filter(item => !ocrReviewIsItemResolved(item))
        .sort((left, right) => {
          const leftOrder = stateOrder[ocrReviewEffectiveReviewState(left)] ?? 3;
          const rightOrder = stateOrder[ocrReviewEffectiveReviewState(right)] ?? 3;
          return leftOrder - rightOrder || left.question_no - right.question_no;
        });
    }

    function ocrReviewIsUserConfirmedStatus(item) {
      return item.resolution === 'student_confirmed' ||
        item.resolution === 'student_edited' ||
        item.resolution === 'student_entered' ||
        item.status === 'confirmed' ||
        item.status === 'student_selected_candidate' ||
        item.status === 'student_direct_input' ||
        item.status === 'student_selected_candidate_after_retake' ||
        item.status === 'student_direct_input_after_retake';
    }

    function ocrReviewIsItemResolved(item) {
      return OCR_REVIEW_RESOLVED_STATES.has(String(item?.resolution || item?.status || ''));
    }

    function ocrReviewResolutionForStudentAnswer(item, answer, intent = 'edit') {
      const normalized = ocrReviewCleanOneLineAnswer(answer);
      if (!normalized) return 'unresolved';
      if (item.review_state === 'auto_confirm') return 'student_edited';
      if (item.review_state === 'review_recommended' && intent === 'confirm' && normalized === item.candidate) {
        return 'student_confirmed';
      }
      if (item.review_state === 'review_recommended') return 'student_edited';
      return 'student_entered';
    }

    function ocrReviewAnswerForPartialFill(item) {
      if (!ocrReviewIsItemResolved(item)) return '';
      const answer = ocrReviewCleanOneLineAnswer(item.final_answer);
      if (!ocrReviewAnswerCanPrefill(answer, item.answer_mode)) return '';
      if (ocrReviewAnswerValidationMessage(answer, item.answer_mode, item.question_no)) return '';
      return answer;
    }

    function ocrReviewPartialFillSummary(items) {
      const lines = items.map(item => ocrReviewAnswerForPartialFill(item));
      const filledQuestions = [];
      const blankQuestions = [];
      lines.forEach((line, index) => {
        const questionNo = index + 1;
        if (line) filledQuestions.push(questionNo);
        else blankQuestions.push(questionNo);
      });
      return { lines, filledQuestions, blankQuestions };
    }

    function ocrReviewNormalizeAnswerLines(value) {
      const lines = String(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').slice(0, OCR_REVIEW_PROBLEM_COUNT);
      while (lines.length < OCR_REVIEW_PROBLEM_COUNT) lines.push('');
      return lines;
    }

    function ocrReviewEnsureAnswersTextLineCount() {
      const lines = ocrReviewNormalizeAnswerLines(answersTextEl.value);
      const nextValue = lines.join('\n');
      if (answersTextEl.value !== nextValue) {
        const selectionStart = answersTextEl.selectionStart ?? nextValue.length;
        answersTextEl.value = nextValue;
        const cursor = Math.min(selectionStart, nextValue.length);
        try { answersTextEl.setSelectionRange(cursor, cursor); } catch {}
      }
      return lines;
    }

    function ocrReviewAnswerLineSummary(lines) {
      const filledQuestions = [];
      const blankQuestions = [];
      lines.forEach((line, index) => {
        const questionNo = index + 1;
        if (String(line || '').trim()) filledQuestions.push(questionNo);
        else blankQuestions.push(questionNo);
      });
      return { lines, filledQuestions, blankQuestions };
    }

    function ocrReviewCurrentAnswerLineSummary(fallbackSummary = null) {
      const textareaLines = ocrReviewNormalizeAnswerLines(answersTextEl.value);
      const hasTextareaState = textareaLines.some(line => String(line || '').trim()) || answersTextEl.dataset.ocrFilled === '1';
      if (!hasTextareaState && fallbackSummary) return fallbackSummary;
      return ocrReviewAnswerLineSummary(textareaLines);
    }

    function ocrReviewSetAnswerLine(questionNo, answer) {
      const no = Number(questionNo);
      if (!Number.isInteger(no) || no < 1 || no > OCR_REVIEW_PROBLEM_COUNT) return;
      const lines = ocrReviewNormalizeAnswerLines(answersTextEl.value);
      lines[no - 1] = String(answer || '');
      const current = ocrReviewCurrentSelectionContext();
      answersTextEl.dataset.ocrProgrammaticFill = '1';
      answersTextEl.value = lines.join('\n');
      answersTextEl.dataset.ocrFilled = '1';
      answersTextEl.dataset.ocrTestId = current.testId;
      answersTextEl.dataset.ocrRound = current.round;
      answersTextEl.dispatchEvent(new Event('input', { bubbles: true }));
      delete answersTextEl.dataset.ocrProgrammaticFill;
      ocrReviewRefreshUnresolvedSummary();
    }

    function ocrReviewSetItemAnswer(item, answer, intent = 'edit') {
      const cleanAnswer = ocrReviewCleanOneLineAnswer(answer);
      if (!cleanAnswer) {
        item.final_answer = null;
        item.resolution = 'unresolved';
        item.status = item.review_state;
        ocrReviewSetAnswerLine(item.question_no, '');
        return false;
      }
      const validationMessage = ocrReviewAnswerValidationMessage(cleanAnswer, item.answer_mode, item.question_no);
      if (validationMessage) {
        ocrTestSheetSetStatus(validationMessage, 'error');
        return false;
      }
      item.final_answer = cleanAnswer;
      item.resolution = ocrReviewResolutionForStudentAnswer(item, cleanAnswer, intent);
      item.user_modified = item.resolution === 'student_edited';
      item.status = item.resolution;
      item.source = item.resolution;
      ocrReviewSetAnswerLine(item.question_no, cleanAnswer);
      return true;
    }

    function ocrReviewSyncPayloadFromAnswersText() {
      if (!ocrReviewPayload) return;
      const lines = ocrReviewNormalizeAnswerLines(answersTextEl.value);
      ocrReviewPayload.items.forEach(item => {
        const answer = ocrReviewCleanOneLineAnswer(lines[item.question_no - 1]);
        if (!answer) {
          if (item.review_state !== 'auto_confirm' || item.final_answer) {
            item.final_answer = null;
            item.resolution = 'unresolved';
            item.user_modified = false;
            item.status = item.review_state;
          }
          return;
        }
        if (ocrReviewAnswerValidationMessage(answer, item.answer_mode, item.question_no)) return;
        if (item.final_answer !== answer || !ocrReviewIsItemResolved(item)) {
          item.final_answer = answer;
          item.resolution = ocrReviewResolutionForStudentAnswer(item, answer, 'edit');
          item.user_modified = item.resolution === 'student_edited';
          item.status = item.resolution;
          item.source = item.resolution;
        }
      });
    }

    function ocrReviewSeedAutoConfirmAnswers(payload) {
      const lines = ocrReviewNormalizeAnswerLines(answersTextEl.value);
      let changed = false;
      payload.items.forEach(item => {
        if (item.review_state !== 'auto_confirm' || item.resolution !== 'auto_confirm') return;
        const answer = ocrReviewAnswerForPartialFill(item);
        if (!answer) return;
        const index = item.question_no - 1;
        if (!String(lines[index] || '').trim()) {
          lines[index] = answer;
          changed = true;
          return;
        }
        if (ocrReviewCleanOneLineAnswer(lines[index]) !== answer) {
          item.final_answer = ocrReviewCleanOneLineAnswer(lines[index]);
          item.resolution = 'student_edited';
          item.user_modified = true;
          item.status = 'student_edited';
        }
      });
      if (!changed) return;
      const current = ocrReviewCurrentSelectionContext();
      ocrReviewApplyAnswersText({
        answersText: lines.join('\n'),
        testId: payload.test_id || current.testId,
        round: payload.round || current.round,
      });
    }

    function ocrReviewSelectAnswersTextLine(questionNo) {
      const no = Number(questionNo);
      if (!Number.isInteger(no) || no < 1 || no > OCR_REVIEW_PROBLEM_COUNT) return false;
      const lines = ocrReviewEnsureAnswersTextLineCount();
      let start = 0;
      for (let index = 0; index < no - 1; index += 1) start += lines[index].length + 1;
      const end = start + lines[no - 1].length;
      answersTextEl.focus();
      try { answersTextEl.setSelectionRange(start, end); } catch {}
      try { answersTextEl.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}
      return true;
    }

    function ocrReviewPrepareAnswersText(payload) {
      const isNormalizedReviewPayload = Array.isArray(payload?.items) && payload.items.length === OCR_REVIEW_PROBLEM_COUNT &&
        payload.items.every(item => Object.prototype.hasOwnProperty.call(item || {}, 'review_state') &&
          Object.prototype.hasOwnProperty.call(item || {}, 'answer_mode'));
      const normalized = isNormalizedReviewPayload ? payload : ocrReviewNormalizePayload(payload);
      const partial = ocrReviewPartialFillSummary(normalized.items);
      if (!partial.filledQuestions.length) throw new Error('사진 인식 결과에서 안전하게 채울 수 있는 문항이 없습니다. 기존 방식으로 직접 입력해주세요.');
      return {
        answersText: partial.lines.join('\n'),
        recognizedFillCount: 0,
        filledLineCount: partial.filledQuestions.length,
        blankLineCount: partial.blankQuestions.length,
        blankQuestions: partial.blankQuestions,
        testId: normalized.test_id,
        round: normalized.round,
      };
    }

    function ocrReviewConvertToAnswersText(payload) {
      return ocrReviewPrepareAnswersText(payload).answersText;
    }

    function ocrReviewQuestionLabelList(questionNumbers) {
      if (!questionNumbers.length) return '없음';
      return ocrReviewQuestionListText(questionNumbers);
    }

    function ocrReviewFocusQuestion(questionNo) {
      const no = Number(questionNo);
      if (!Number.isInteger(no)) return false;
      ocrReviewPanel?.querySelectorAll('.ts-ocr-card[data-ocr-focus="true"]').forEach(card => {
        delete card.dataset.ocrFocus;
      });
      const card = ocrReviewPanel?.querySelector(`[data-question-no="${no}"]`);
      if (card) {
        ocrReviewCurrentUnresolvedQuestion = no;
        card.dataset.ocrFocus = 'true';
        try { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}
        const focusTarget = card.querySelector('.ts-ocr-current:not([hidden])') ||
          card.querySelector('.ts-ocr-choice') ||
          card.querySelector('button');
        try { focusTarget?.focus(); } catch {}
        ocrTestSheetSetStatus(`${no}번 문항을 확인해주세요.`);
        return true;
      }
      if (ocrReviewSelectAnswersTextLine(no)) {
        ocrReviewCurrentUnresolvedQuestion = no;
        ocrTestSheetSetStatus(`${no}번 줄을 직접 입력해주세요.`);
        return true;
      }
      return false;
    }

    function ocrReviewSubmissionBlockState(testId = selTestId.value, round = selRound.value) {
      if (!OCR_TEST_SHEET_ENABLED || !ocrReviewPayload) return null;
      const requestedTestId = String(testId || '');
      const requestedRound = String(round || '1');
      if (String(ocrReviewPayload.test_id || '') !== requestedTestId || String(ocrReviewPayload.round || '1') !== requestedRound) {
        return {
          blocked: true,
          reason: 'context_mismatch',
          count: 0,
          questionNumbers: [],
          firstQuestionNo: null,
          message: '사진 인식 결과가 현재 시험 또는 회차와 맞지 않습니다. 다시 인식하거나 답안을 직접 확인해 주세요.',
        };
      }
      const unresolvedItems = ocrReviewBlockingItems(ocrReviewPayload);
      if (!unresolvedItems.length) return null;
      return {
        blocked: true,
        requiresConfirmation: false,
        reason: 'unresolved_ocr_items',
        count: unresolvedItems.length,
        questionNumbers: unresolvedItems.map(item => item.question_no),
        firstQuestionNo: unresolvedItems[0].question_no,
        message: `아직 확인하지 않은 문항이 ${unresolvedItems.length}개 있습니다. ${ocrReviewQuestionListText(unresolvedItems.map(item => item.question_no))}을(를) 확인하거나 직접 입력한 뒤 제출할 수 있습니다.`,
      };
    }

    function ocrReviewFocusAdjacentUnresolved(direction = 1) {
      const fallbackSummary = ocrReviewPayload ? ocrReviewPartialFillSummary(ocrReviewPayload.items) : null;
      const summary = ocrReviewCurrentAnswerLineSummary(fallbackSummary);
      const unresolvedQuestions = ocrReviewPayload
        ? ocrReviewBlockingItems(ocrReviewPayload).map(item => item.question_no)
        : summary.blankQuestions;
      if (!unresolvedQuestions.length) {
        ocrTestSheetSetStatus('모든 답안을 확인했습니다.', 'ok');
        ocrReviewRefreshUnresolvedSummary();
        return;
      }
      const currentIndex = unresolvedQuestions.indexOf(ocrReviewCurrentUnresolvedQuestion);
      const baseIndex = currentIndex >= 0
        ? currentIndex
        : direction < 0 ? 0 : -1;
      const index = (baseIndex + direction + unresolvedQuestions.length) % unresolvedQuestions.length;
      const questionNo = unresolvedQuestions[index];
      const previousQuestionNo = ocrReviewCurrentUnresolvedQuestion;
      ocrReviewFocusQuestion(questionNo);
      if (previousQuestionNo && previousQuestionNo !== questionNo && unresolvedQuestions.includes(previousQuestionNo)) {
        ocrTestSheetSetStatus(`${questionNo}번 문항을 확인해주세요. ${previousQuestionNo}번 문항은 아직 확인되지 않았습니다.`, 'error');
      }
      ocrReviewRefreshUnresolvedSummary();
    }

    function ocrReviewFocusNextUnresolved() {
      ocrReviewFocusAdjacentUnresolved(1);
    }

    function ocrReviewUpdateUnresolvedNumberList(listEl, blankQuestions) {
      if (!listEl) return;
      listEl.replaceChildren();
      blankQuestions.forEach(questionNo => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ts-ocr-unresolved-question';
        button.textContent = `${questionNo}번`;
        button.addEventListener('click', () => {
          ocrReviewFocusQuestion(questionNo);
          ocrReviewRefreshUnresolvedSummary();
        });
        listEl.appendChild(button);
      });
    }

    function ocrReviewRefreshUnresolvedSummary(fallbackSummary = null) {
      if (!ocrReviewPanel) return null;
      const summary = ocrReviewCurrentAnswerLineSummary(fallbackSummary);
      if (typeof ocrReviewPanel.querySelector !== 'function') return summary;
      const wrap = ocrReviewPanel.querySelector('.ts-ocr-unresolved');
      if (!wrap) return summary;
      const filledCount = summary.filledQuestions.length;
      const blankCount = summary.blankQuestions.length;
      const unresolvedQuestions = ocrReviewPayload
        ? ocrReviewBlockingItems(ocrReviewPayload).map(item => item.question_no)
        : summary.blankQuestions;
      if (ocrReviewNextBlankIndex >= unresolvedQuestions.length) ocrReviewNextBlankIndex = 0;
      const title = wrap.querySelector('.ts-ocr-unresolved-title');
      const count = wrap.querySelector('.ts-ocr-unresolved-count');
      const progress = wrap.querySelector('.ts-ocr-unresolved-progress');
      const list = wrap.querySelector('.ts-ocr-unresolved-list');
      const previousButton = wrap.querySelector('.ts-ocr-prev-unresolved');
      const nextButton = wrap.querySelector('.ts-ocr-next-unresolved');
      if (title) title.textContent = unresolvedQuestions.length ? `직접 확인할 문항 ${unresolvedQuestions.length}개` : '모든 답안을 확인했습니다';
      if (count) count.textContent = `채움 ${filledCount}개 · 빈칸 ${blankCount}개`;
      if (progress) {
        const currentIndex = Math.max(0, unresolvedQuestions.indexOf(ocrReviewCurrentUnresolvedQuestion));
        progress.textContent = unresolvedQuestions.length ? `현재 ${currentIndex + 1} / ${unresolvedQuestions.length}` : '확인 완료';
      }
      ocrReviewUpdateUnresolvedNumberList(list, unresolvedQuestions);
      if (previousButton) previousButton.disabled = unresolvedQuestions.length === 0;
      if (nextButton) {
        nextButton.disabled = unresolvedQuestions.length === 0;
        nextButton.textContent = unresolvedQuestions.length ? '다음 확인 문항' : '확인 완료';
      }
      wrap.dataset.blankCount = String(blankCount);
      wrap.dataset.filledCount = String(filledCount);
      wrap.dataset.blankQuestions = unresolvedQuestions.join(',');
      return summary;
    }

    function ocrReviewRenderUnresolvedNavigator(fillPreview) {
      const wrap = document.createElement('section');
      wrap.className = 'ts-ocr-unresolved';
      const head = document.createElement('div');
      head.className = 'ts-ocr-unresolved-head';
      const title = document.createElement('strong');
      title.className = 'ts-ocr-unresolved-title';
      const count = document.createElement('span');
      count.className = 'ts-ocr-unresolved-count';
      const list = document.createElement('div');
      list.className = 'ts-ocr-unresolved-list';
      list.setAttribute('aria-label', '직접 확인할 문항 번호');
      const progress = document.createElement('span');
      progress.className = 'ts-ocr-unresolved-progress';
      const previousButton = document.createElement('button');
      previousButton.type = 'button';
      previousButton.className = 'ts-ocr-prev-unresolved';
      previousButton.textContent = '이전 문항';
      previousButton.addEventListener('click', () => ocrReviewFocusAdjacentUnresolved(-1));
      const nextButton = document.createElement('button');
      nextButton.type = 'button';
      nextButton.className = 'ts-ocr-next-unresolved';
      nextButton.addEventListener('click', () => ocrReviewFocusNextUnresolved());
      head.append(title, count, progress);
      wrap.append(head, list, previousButton, nextButton);
      return wrap;
    }

    function ocrReviewCounts(payload) {
      return payload.items.reduce((acc, item) => {
        if (item.review_state === 'auto_confirm') acc.auto += 1;
        if (!ocrReviewIsItemResolved(item)) {
          if (item.review_state === 'review_recommended') acc.review += 1;
          else if (item.review_state === 'direct_input' || item.review_state === 'auto_confirm') acc.direct += 1;
          else if (item.review_state === 'retake_required') acc.retake += 1;
        }
        return acc;
      }, { auto: 0, review: 0, direct: 0, retake: 0 });
    }

    function ocrReviewTelemetrySnapshot(payload = ocrReviewPayload) {
      const items = Array.isArray(payload?.items) ? payload.items : [];
      const stateCounts = ocrReviewCounts({ items });
      return {
        total_items: items.length,
        auto_confirm_count: stateCounts.auto,
        review_recommended_count: stateCounts.review,
        direct_input_count: stateCounts.direct,
        retake_required_count: stateCounts.retake,
        user_confirmed_count: items.filter(item => item.resolution === 'student_confirmed').length,
        user_modified_count: items.filter(item => item.user_modified === true).length,
        direct_input_completed_count: items.filter(item => item.resolution === 'student_entered').length,
        unresolved_count: ocrReviewBlockingItems({ items }).length,
        review_duration_ms: ocrReviewStartedAt ? Math.max(0, Date.now() - ocrReviewStartedAt) : 0,
      };
    }

    function ocrReviewItemHasActionableReviewControl(item) {
      if (ocrReviewIsItemResolved(item)) return true;
      if (item.review_state === 'retake_required') return true;
      if (item.answer_mode === 'choice_number' || item.answer_mode === 'answer_value') return true;
      return Boolean(item.allow_edit);
    }

    function ocrReviewHasActionableItem(payload) {
      return payload.items.some(item => {
        if (ocrReviewAnswerForPartialFill(item)) return true;
        if (ocrReviewItemHasActionableReviewControl(item)) return true;
        return ocrReviewItemHasActionableReviewControl(item);
      });
    }

    function ocrReviewUnusablePayloadMessage(payload) {
      const normalizedSource = String(payload?.source || '').trim();
      if (normalizedSource === 'phase2d_cached_recognized') {
        return '학생이 확인할 수 있는 인식 결과가 준비되지 않았습니다. 답안을 직접 입력해 주세요.';
      }
      if (ocrReviewHasActionableItem(payload)) return '';
      return '학생이 확인할 수 있는 인식 결과가 준비되지 않았습니다. 답안을 직접 입력해 주세요.';
    }

    function ocrReviewEnsureActionablePayload(payload) {
      const normalized = ocrReviewNormalizePayload(payload);
      const current = ocrReviewCurrentSelectionContext();
      if (normalized.test_id !== current.testId || normalized.round !== current.round) {
        throw new Error('사진 인식 결과가 현재 시험 또는 회차와 맞지 않습니다. 답안을 직접 입력해 주세요.');
      }
      const unusableMessage = ocrReviewUnusablePayloadMessage(normalized);
      if (unusableMessage) throw new Error(unusableMessage);
      return normalized;
    }

    function ocrReviewAppendKey(input, value) {
      const token = value === '√( )' || value === 'sqrt( )' ? '√' : value;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? input.value.length;
      input.value = `${input.value.slice(0, start)}${token}${input.value.slice(end)}`;
      const cursor = start + token.length;
      input.focus();
      input.setSelectionRange(cursor, cursor);
      input.dataset.answerSource = 'student_direct_input';
    }

    function ocrReviewEffectiveReviewState(item) {
      if (item.review_state === 'auto_confirm' && !ocrReviewIsItemResolved(item)) return 'direct_input';
      return item.review_state;
    }

    function ocrReviewResolutionLabel(item) {
      if (!ocrReviewIsItemResolved(item)) return '미확정';
      if (item.resolution === 'auto_confirm') return '자동 인식';
      if (item.resolution === 'student_confirmed') return '학생 확인';
      if (item.user_modified || item.resolution === 'student_edited') return '사용자 수정';
      return '직접 입력';
    }

    function ocrReviewRenderCropPreview(item) {
      if (!item.crop_preview) return null;
      const details = document.createElement('details');
      details.className = 'ts-ocr-crop';
      const summary = document.createElement('summary');
      summary.textContent = '원본 사진 보기';
      const image = document.createElement('img');
      image.src = item.crop_preview;
      image.alt = `${item.question_no}번 답안 사진`;
      image.loading = 'lazy';
      image.referrerPolicy = 'no-referrer';
      details.append(summary, image);
      return details;
    }

    function ocrReviewRenderStateHeader(payload, counts) {
      const wrap = document.createElement('section');
      wrap.className = 'ts-ocr-state-summary';
      const heading = document.createElement('strong');
      heading.textContent = '답안 입력 검토';
      const copy = document.createElement('p');
      copy.textContent = '사진 인식은 답안 입력 보조입니다. 확인이 필요한 문항만 처리해 주세요.';
      const stats = document.createElement('div');
      stats.className = 'ts-ocr-state-stats';
      [
        ['자동 인식 완료', counts.auto],
        ['확인 필요', counts.review],
        ['직접 입력 필요', counts.direct],
        ['다시 촬영 필요', counts.retake],
      ].forEach(([label, value]) => {
        const stat = document.createElement('span');
        stat.textContent = `${label} ${value}문항`;
        stats.appendChild(stat);
      });
      const actions = document.createElement('div');
      actions.className = 'ts-ocr-state-actions';
      const reviewButton = document.createElement('button');
      reviewButton.type = 'button';
      reviewButton.className = 'ts-ocr-next-unresolved';
      reviewButton.textContent = '확인 필요한 문항 검토하기';
      reviewButton.disabled = counts.review + counts.direct + counts.retake === 0;
      reviewButton.addEventListener('click', () => ocrReviewFocusNextUnresolved());
      const summaryButton = document.createElement('button');
      summaryButton.type = 'button';
      summaryButton.className = 'ts-ocr-candidate';
      summaryButton.textContent = '전체 답안 보기';
      summaryButton.addEventListener('click', () => {
        const details = ocrReviewPanel?.querySelector('.ts-ocr-final-summary details');
        if (!details) return;
        details.open = true;
        try { details.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}
      });
      actions.append(reviewButton, summaryButton);
      wrap.append(heading, copy, stats, actions);
      return wrap;
    }

    function ocrReviewRender() {
      if (!ocrReviewPanel || !ocrReviewPayload) return;
      if (!ocrReviewStartedAt) ocrReviewStartedAt = Date.now();
      ocrReviewEnsureAnswersTextLineCount();
      ocrReviewSeedAutoConfirmAnswers(ocrReviewPayload);
      ocrReviewPanel.replaceChildren();
      ocrReviewClearFallback();
      ocrTestSheetSetStatus('검토 준비 완료. 확인이 필요한 문항만 확인해 주세요.', 'ok');
      const counts = ocrReviewCounts(ocrReviewPayload);
      const fillPreview = ocrReviewPartialFillSummary(ocrReviewPayload.items);
      const fillableCount = fillPreview.filledQuestions.length;
      ocrReviewPanel.appendChild(ocrReviewRenderStateHeader(ocrReviewPayload, counts));
      ocrReviewPanel.appendChild(ocrReviewRenderUnresolvedNavigator(fillPreview));
      ocrReviewRefreshUnresolvedSummary(fillPreview);

      const unresolvedItems = ocrReviewBlockingItems(ocrReviewPayload);
      const reviewItems = unresolvedItems.filter(item => ocrReviewEffectiveReviewState(item) === 'review_recommended');
      const directItems = unresolvedItems.filter(item => ocrReviewEffectiveReviewState(item) === 'direct_input');
      const retakeItems = unresolvedItems.filter(item => ocrReviewEffectiveReviewState(item) === 'retake_required');
      const retakeSection = ocrReviewRenderSection('다시 촬영 필요', retakeItems, ocrReviewRenderBlockedCard);
      if (retakeSection) ocrReviewPanel.appendChild(retakeSection);
      const directSection = ocrReviewRenderSection('직접 입력 필요', directItems, ocrReviewRenderReviewCard);
      if (directSection) ocrReviewPanel.appendChild(directSection);
      const reviewSection = ocrReviewRenderSection('확인 필요', reviewItems, ocrReviewRenderReviewCard);
      if (reviewSection) ocrReviewPanel.appendChild(reviewSection);
      ocrReviewPanel.appendChild(ocrReviewRenderSafeAutoList());

      const applyBtn = document.createElement('button');
      applyBtn.type = 'button';
      applyBtn.className = 'ts-ocr-apply';
      applyBtn.disabled = fillableCount === 0;
      applyBtn.textContent = fillableCount
        ? `확인된 답안 ${fillableCount}개만 답칸 채우기`
        : '확인된 답안 없음';
      applyBtn.addEventListener('click', () => {
        try {
          const result = ocrReviewPrepareAnswersText(ocrReviewPayload);
          ocrReviewApplyAnswersText(result, { preserveExisting: true });
          ocrReviewRefreshUnresolvedSummary();
          ocrTestSheetSetStatus(`${result.filledLineCount}문항을 답안칸에 반영했습니다. ${result.blankLineCount}문항은 직접 확인해 주세요.`, 'ok');
        } catch (err) {
          const first = ocrReviewBlockingItems(ocrReviewPayload)[0];
          if (first) ocrReviewFocusQuestion(first.question_no);
          ocrTestSheetSetStatus(err?.message || '아직 처리되지 않은 문항이 있습니다.', 'error');
        }
      });
      ocrReviewPanel.appendChild(applyBtn);
      ocrReviewPanel.hidden = false;
    }

    function ocrReviewRenderReviewCard(item) {
      const effectiveState = ocrReviewEffectiveReviewState(item);
      const card = document.createElement('section');
      card.className = 'ts-ocr-card';
      card.dataset.questionNo = String(item.question_no);
      const title = document.createElement('h4');
      title.className = 'ts-ocr-card-title';
      title.textContent = effectiveState === 'review_recommended'
        ? `${item.question_no}번 문항 확인 필요`
        : `${item.question_no}번 문항 직접 입력 필요`;
      const mode = document.createElement('div');
      mode.className = 'ts-ocr-mode';
      mode.textContent = ocrReviewAnswerModeLabel(item.answer_mode);
      const helper = document.createElement('p');
      helper.className = 'ts-ocr-card-help';
      helper.textContent = effectiveState === 'review_recommended'
        ? '내가 쓴 답과 같은지 확인해 주세요.'
        : '답안을 직접 입력한 뒤 완료를 눌러주세요.';
      const main = document.createElement('div');
      main.className = 'ts-ocr-card-main';
      const controls = document.createElement('div');
      controls.className = 'ts-ocr-card-controls';
      const isChoiceNumber = item.answer_mode === 'choice_number';
      const initialAnswer = effectiveState === 'review_recommended' ? item.candidate : '';
      const input = document.createElement('input');
      input.className = 'ts-ocr-current';
      input.type = isChoiceNumber ? 'hidden' : 'text';
      input.value = initialAnswer;
      input.hidden = isChoiceNumber;
      input.placeholder = effectiveState === 'review_recommended' ? '인식 후보를 확인하거나 수정' : '직접 입력';
      input.setAttribute('aria-label', `${item.question_no}번 직접 입력`);
      input.dataset.answerIntent = effectiveState === 'review_recommended' && initialAnswer ? 'confirm' : 'edit';
      input.addEventListener('input', () => { input.dataset.answerIntent = 'edit'; });

      if (effectiveState === 'review_recommended' && item.candidate && !isChoiceNumber) {
        const candidateLabel = document.createElement('span');
        candidateLabel.className = 'ts-ocr-candidate-label';
        candidateLabel.textContent = '인식 후보';
        controls.appendChild(candidateLabel);
      }

      const choiceGrid = document.createElement('div');
      choiceGrid.className = 'ts-ocr-choice-grid';
      choiceGrid.setAttribute('role', 'group');
      choiceGrid.setAttribute('aria-label', `${item.question_no}번 선택형 답 선택`);
      const syncChoiceButtons = selected => {
        choiceGrid.querySelectorAll('button').forEach(button => {
          button.setAttribute('aria-pressed', button.dataset.value === selected ? 'true' : 'false');
        });
      };
      ['1', '2', '3', '4', '5'].forEach(value => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ts-ocr-choice';
        button.textContent = value;
        button.dataset.value = value;
        button.setAttribute('aria-pressed', input.value === value ? 'true' : 'false');
        button.addEventListener('click', () => {
          input.value = value;
          input.dataset.answerIntent = effectiveState === 'review_recommended' && value === item.candidate ? 'confirm' : 'edit';
          syncChoiceButtons(value);
        });
        choiceGrid.appendChild(button);
      });

      if (isChoiceNumber) controls.append(choiceGrid, input);
      else controls.append(input);

      if (!isChoiceNumber && effectiveState !== 'review_recommended') {
        const keypad = document.createElement('div');
        keypad.className = 'ts-ocr-keypad ts-ocr-keypad-primary';
        OCR_REVIEW_PRIMARY_KEYPAD_VALUES.forEach(value => {
          const key = document.createElement('button');
          key.type = 'button';
          key.className = 'ts-ocr-key';
          key.textContent = value;
          key.addEventListener('click', () => ocrReviewAppendKey(input, value));
          keypad.appendChild(key);
        });
        controls.appendChild(keypad);
      }

      const preview = ocrReviewRenderCropPreview(item);
      main.append(controls);
      if (preview) main.append(preview);
      const actions = document.createElement('div');
      actions.className = 'ts-ocr-actions';
      if (effectiveState === 'review_recommended') {
        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'ts-ocr-candidate';
        editButton.textContent = '수정하기';
        editButton.addEventListener('click', () => {
          input.dataset.answerIntent = 'edit';
          try { input.focus(); input.select(); } catch {}
        });
        const directButton = document.createElement('button');
        directButton.type = 'button';
        directButton.className = 'ts-ocr-candidate';
        directButton.textContent = '직접 입력';
        directButton.addEventListener('click', () => {
          input.value = '';
          input.dataset.answerIntent = 'edit';
          if (isChoiceNumber) syncChoiceButtons('');
          const focusTarget = isChoiceNumber ? choiceGrid.querySelector('.ts-ocr-choice') : input;
          try { focusTarget?.focus(); } catch {}
        });
        actions.append(editButton, directButton);
      }
      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = 'ts-ocr-confirm';
      confirmBtn.textContent = effectiveState === 'review_recommended' ? '맞아요' : '입력 완료';
      confirmBtn.addEventListener('click', () => {
        const answer = ocrReviewCleanOneLineAnswer(input.value);
        if (!ocrReviewHasReliableText(answer)) {
          ocrTestSheetSetStatus(`${item.question_no}번 문항 답안을 선택하거나 입력해주세요.`, 'error');
          return;
        }
        if (!ocrReviewSetItemAnswer(item, answer, input.dataset.answerIntent || 'edit')) return;
        ocrTestSheetSetStatus(`${item.question_no}번 문항을 반영했습니다.`, 'ok');
        ocrReviewRender();
      });
      actions.appendChild(confirmBtn);
      card.append(title, mode, helper, main, actions);
      return card;
    }

    function ocrReviewRenderBlockedCard(item) {
      const card = ocrReviewRenderReviewCard(item);
      const title = card.querySelector('.ts-ocr-card-title');
      const helper = card.querySelector('.ts-ocr-card-help');
      if (title) title.textContent = `${item.question_no}번 문항 사진을 다시 확인해 주세요`;
      if (helper) helper.textContent = `${item.retake_reason} 때문에 재촬영을 권장합니다. 재촬영을 건너뛰면 답안을 직접 입력할 수 있습니다.`;
      const actions = card.querySelector('.ts-ocr-actions');
      const retakeButton = document.createElement('button');
      retakeButton.type = 'button';
      retakeButton.className = 'ts-ocr-candidate';
      retakeButton.textContent = '다시 촬영';
      retakeButton.addEventListener('click', () => {
        try { ocrReviewImageEl?.click(); } catch {}
      });
      const manualButton = document.createElement('button');
      manualButton.type = 'button';
      manualButton.className = 'ts-ocr-candidate';
      manualButton.textContent = '직접 입력';
      manualButton.addEventListener('click', () => {
        try { card.querySelector('.ts-ocr-current:not([hidden])')?.focus(); } catch {}
      });
      if (actions) actions.append(retakeButton, manualButton);
      return card;
    }

    function ocrReviewRenderSafeAutoList() {
      const wrap = document.createElement('section');
      wrap.className = 'ts-ocr-final-summary';
      const details = document.createElement('details');
      details.open = ocrReviewBlockingItems(ocrReviewPayload).length === 0;
      const summary = document.createElement('summary');
      summary.textContent = '전체 답안 요약 · 수정 가능';
      const list = document.createElement('ol');
      list.className = 'ts-ocr-final-list';
      ocrReviewPayload.items.forEach(item => {
        const row = document.createElement('li');
        row.className = 'ts-ocr-final-row';
        row.dataset.summaryQuestion = String(item.question_no);
        row.dataset.resolution = item.resolution;
        const question = document.createElement('span');
        question.className = 'ts-ocr-final-question';
        question.textContent = `${item.question_no}번`;
        const input = document.createElement('input');
        input.className = 'ts-ocr-final-input';
        input.type = 'text';
        input.value = item.final_answer || '';
        input.placeholder = '빈칸';
        input.setAttribute('aria-label', `${item.question_no}번 최종 답안 수정`);
        const label = document.createElement('span');
        label.className = 'ts-ocr-final-status';
        label.textContent = ocrReviewResolutionLabel(item);
        input.addEventListener('input', () => {
          const answer = ocrReviewCleanOneLineAnswer(input.value);
          if (!answer) {
            ocrReviewSetItemAnswer(item, '', 'edit');
          } else if (!ocrReviewSetItemAnswer(item, answer, 'edit')) {
            return;
          }
          row.dataset.resolution = item.resolution;
          label.textContent = ocrReviewResolutionLabel(item);
          ocrReviewRefreshUnresolvedSummary();
        });
        row.append(question, input, label);
        list.appendChild(row);
      });
      details.append(summary, list);
      wrap.appendChild(details);
      return wrap;
    }

    function ocrReviewRenderLegacy() {
      if (!ocrReviewPanel || !ocrReviewPayload) return;
      ocrReviewPanel.replaceChildren();
      ocrReviewClearFallback();
      const counts = ocrReviewCounts(ocrReviewPayload);
      const fillPreview = ocrReviewPartialFillSummary(ocrReviewPayload.items);
      const fillableCount = fillPreview.filledQuestions.length;
      ocrReviewPanel.appendChild(ocrReviewRenderUnresolvedNavigator(fillPreview));
      ocrReviewRefreshUnresolvedSummary(fillPreview);
      const guideList = ocrReviewRenderGuideList(ocrReviewPayload, counts, fillPreview);
      if (guideList) {
        const guideDetails = document.createElement('details');
        guideDetails.className = 'ts-ocr-guide-details';
        const guideSummary = document.createElement('summary');
        guideSummary.textContent = '확인 안내 보기';
        guideDetails.append(guideSummary, guideList);
        ocrReviewPanel.appendChild(guideDetails);
      }

      const reviewSection = ocrReviewRenderSection(
        `직접 확인할 문항 ${counts.review}개`,
        ocrReviewPayload.items.filter(item => item.status === 'review_required'),
        ocrReviewRenderReviewCard,
      );
      if (reviewSection) ocrReviewPanel.appendChild(reviewSection);
      const blockedSection = ocrReviewRenderSection(
        `재촬영 또는 별도 확인 문항 ${counts.retake + counts.pendingRetake + counts.dataCheck}개`,
        ocrReviewPayload.items.filter(item => item.status === 'retake_required' || item.status === 'retake_uploaded' || item.status === 'data_check_required'),
        ocrReviewRenderBlockedCard,
      );
      if (blockedSection) ocrReviewPanel.appendChild(blockedSection);
      ocrReviewPanel.appendChild(ocrReviewRenderSafeAutoList());
      const blockingItems = ocrReviewBlockingItems(ocrReviewPayload);
      const firstBlockingItem = blockingItems[0] || null;
      const applyBtn = document.createElement('button');
      applyBtn.type = 'button';
      applyBtn.className = 'ts-ocr-apply';
      applyBtn.disabled = fillableCount === 0;
      applyBtn.textContent = fillableCount
        ? `확인된 답안 ${fillableCount}개만 답칸 채우기`
        : '확인된 답안 없음';
      applyBtn.addEventListener('click', () => {
        if (!fillableCount) {
          const targetCard = firstBlockingItem
            ? ocrReviewPanel.querySelector('[data-question-no="' + firstBlockingItem.question_no + '"]') || ocrReviewPanel.querySelector('.ts-ocr-card')
            : ocrReviewPanel.querySelector('.ts-ocr-card');
          targetCard?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          ocrTestSheetSetStatus(firstBlockingItem ? ocrReviewBlockerMessage(firstBlockingItem) : '안전하게 채울 수 있는 문항이 없습니다.', 'error');
          return;
        }
        try {
          const result = ocrReviewPrepareAnswersText(ocrReviewPayload);
          ocrReviewApplyAnswersText(result);
          const lineCount = result.answersText.split('\n').length;
          ocrReviewRefreshUnresolvedSummary();
          ocrTestSheetSetStatus(`${result.filledLineCount}문항을 답안칸에 반영했습니다. ${result.blankLineCount}문항은 직접 확인해 주세요. 답안은 기존 제출 버튼에서만 제출됩니다.`, 'ok');
        } catch (err) {
          ocrTestSheetSetStatus(err?.message || '아직 처리되지 않은 문항이 있습니다.', 'error');
        }
      });
      ocrReviewPanel.appendChild(applyBtn);
      ocrReviewPanel.hidden = false;
    }

    function ocrReviewRenderReviewCardLegacy(item) {
      const card = document.createElement('section');
      card.className = 'ts-ocr-card';
      card.dataset.questionNo = String(item.question_no);
      const title = document.createElement('h4');
      title.textContent = `${item.question_no}번 문항 직접 확인 필요`;
      const mode = document.createElement('div');
      mode.className = 'ts-ocr-mode';
      mode.textContent = ocrReviewAnswerModeLabel(item.answer_mode);
      const visibleCandidates = item.candidates.filter(candidate => ocrReviewCandidateCanShow(candidate, item.answer_mode));
      const isChoiceNumber = item.answer_mode === 'choice_number';
      const initialAnswer = ocrReviewDefaultAnswerForReviewInput(item);
      const input = document.createElement('input');
      input.className = 'ts-ocr-current';
      input.type = isChoiceNumber ? 'hidden' : 'text';
      input.value = initialAnswer;
      input.dataset.answerSource = item.status === 'review_required' && initialAnswer
        ? 'student_selected_candidate'
        : 'student_direct_input';
      input.hidden = isChoiceNumber;
      input.placeholder = '직접 입력';
      input.setAttribute('aria-label', `${item.question_no}번 직접 입력`);

      const candidates = document.createElement('div');
      candidates.className = 'ts-ocr-candidates';
      visibleCandidates.forEach(candidate => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ts-ocr-candidate';
        btn.textContent = `인식 후보 ${candidate}`;
        btn.addEventListener('click', () => {
          input.value = candidate;
          input.dataset.answerSource = 'student_selected_candidate';
          if (isChoiceNumber) syncChoiceButtons(candidate);
        });
        candidates.appendChild(btn);
      });
      input.addEventListener('input', () => {
        input.dataset.answerSource = 'student_direct_input';
      });

      const choiceGrid = document.createElement('div');
      choiceGrid.className = 'ts-ocr-choice-grid';
      choiceGrid.setAttribute('role', 'group');
      choiceGrid.setAttribute('aria-label', `${item.question_no}번 선택형 답 선택`);
      const syncChoiceButtons = selected => {
        choiceGrid.querySelectorAll('button').forEach(button => {
          const isSelected = button.dataset.value === selected;
          button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
        });
      };
      ['1', '2', '3', '4', '5'].forEach(value => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ts-ocr-choice';
        btn.textContent = value;
        btn.dataset.value = value;
        btn.setAttribute('aria-pressed', input.value === value ? 'true' : 'false');
        btn.addEventListener('click', () => {
          input.value = value;
          input.dataset.answerSource = 'student_direct_input';
          syncChoiceButtons(value);
        });
        choiceGrid.appendChild(btn);
      });

      const keypad = document.createElement('div');
      keypad.className = 'ts-ocr-keypad ts-ocr-keypad-primary';
      OCR_REVIEW_PRIMARY_KEYPAD_VALUES.forEach(value => {
        const key = document.createElement('button');
        key.type = 'button';
        key.className = 'ts-ocr-key';
        key.textContent = value;
        key.addEventListener('click', () => ocrReviewAppendKey(input, value));
        keypad.appendChild(key);
      });
      const actions = document.createElement('div');
      actions.className = 'ts-ocr-actions';
      if (isChoiceNumber) {
        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'ts-ocr-candidate';
        clearBtn.textContent = '지우기';
        clearBtn.addEventListener('click', () => {
          input.value = '';
          input.dataset.answerSource = 'student_direct_input';
          syncChoiceButtons('');
        });
        const resetBtn = document.createElement('button');
        resetBtn.type = 'button';
        resetBtn.className = 'ts-ocr-candidate';
        resetBtn.textContent = '초기화';
        resetBtn.addEventListener('click', () => {
          input.value = '';
          input.dataset.answerSource = 'student_direct_input';
          syncChoiceButtons('');
        });
        actions.append(clearBtn, resetBtn);
      }
      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = 'ts-ocr-confirm';
      confirmBtn.textContent = '확정';
      confirmBtn.addEventListener('click', () => {
        const answer = ocrReviewCleanOneLineAnswer(input.value);
        if (!ocrReviewHasReliableText(answer)) {
          ocrTestSheetSetStatus(`${item.question_no}번 문항 답안을 선택하거나 입력해주세요.`, 'error');
          return;
        }
        const validationMessage = ocrReviewAnswerValidationMessage(answer, item.answer_mode, item.question_no);
        if (validationMessage) {
          ocrTestSheetSetStatus(validationMessage, 'error');
          return;
        }
        const source = input.dataset.answerSource === 'student_selected_candidate' ? 'student_selected_candidate' : 'student_direct_input';
        input.value = answer;
        item.final_answer = answer;
        item.source = source;
        item.status = source;
        item.warnings = [];
        item.candidates = [];
        ocrReviewSetAnswerLine(item.question_no, answer);
        ocrTestSheetSetStatus(`${item.question_no}번 문항을 확인했습니다.`);
        ocrReviewRender();
      });
      actions.appendChild(confirmBtn);
      const children = [title, mode];
      if (isChoiceNumber) {
        children.push(choiceGrid, input);
      }
      else {
        children.push(candidates, input, keypad);
      }
      children.push(actions);
      card.append(...children);
      return card;
    }
    function ocrReviewRenderBlockedCardLegacy(item) {
      const card = document.createElement('section');
      card.className = 'ts-ocr-card';
      card.dataset.questionNo = String(item.question_no);
      const title = document.createElement('h4');
      const statusLabel = item.status === 'data_check_required' ? '선생님 확인 필요' : item.status === 'retake_uploaded' ? '재인식 대기' : '재촬영 권장';
      title.textContent = `${item.question_no}번 문항 ${statusLabel}`;
      const mode = document.createElement('div');
      mode.className = 'ts-ocr-mode';
      mode.textContent = ocrReviewAnswerModeLabel(item.answer_mode);
      const actions = document.createElement('div');
      actions.className = 'ts-ocr-actions ts-ocr-blocked-actions';
      const retakeButton = document.createElement('button');
      retakeButton.type = 'button';
      retakeButton.className = 'ts-ocr-candidate';
      retakeButton.textContent = '다른 사진 선택';
      retakeButton.addEventListener('click', () => {
        try { ocrReviewImageEl?.click(); } catch {}
      });
      const manualButton = document.createElement('button');
      manualButton.type = 'button';
      manualButton.className = 'ts-ocr-candidate';
      manualButton.textContent = '답안 직접 입력';
      manualButton.addEventListener('click', ocrReviewFocusManualAnswers);
      actions.append(retakeButton, manualButton);
      card.append(title, mode, actions);
      return card;
    }

    function ocrReviewRenderSafeAutoListLegacy() {
      const wrap = document.createElement('div');
      wrap.className = 'ts-ocr-safe';
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = '전체 20문항 상태 보기';
      const list = document.createElement('ol');
      list.className = 'ts-ocr-safe-list';
      ocrReviewPayload.items.forEach(item => {
        const li = document.createElement('li');
        const label = OCR_REVIEW_FINAL_STATUSES.has(item.status)
          ? `입력 완료${item.final_answer ? ` · ${item.final_answer}` : ''}`
          : item.status === 'retake_required' ? '재촬영 또는 직접 입력 필요'
            : item.status === 'retake_uploaded' ? '재인식 대기'
              : item.status === 'data_check_required' ? '선생님 확인 필요'
                : '직접 확인 필요';
        li.textContent = `${item.question_no}번: ${label}`;
        list.appendChild(li);
      });
      details.append(summary, list);
      wrap.appendChild(details);
      return wrap;
    }

    function ocrReviewSelectedImage() {
      const file = ocrReviewImageEl?.files?.[0];
      return file || null;
    }

    function ocrReviewUpdateSelectedImageDisplay(file = ocrReviewSelectedImage()) {
      const filename = String(file?.name || '').trim();
      if (ocrReviewFileNameEl) {
        ocrReviewFileNameEl.textContent = filename || '사진을 선택해 주세요.';
        ocrReviewFileNameEl.title = filename;
      }
      if (btnOcrReviewPick) {
        btnOcrReviewPick.textContent = filename ? '다른 사진 선택' : '사진 선택';
        btnOcrReviewPick.setAttribute('aria-label', filename ? '다른 답안지 사진 선택' : '답안지 사진 선택');
      }
    }

    function ocrReviewImageExtension(filename) {
      const name = String(filename || '').trim();
      if (!name.includes('.')) return '';
      return name.split('.').pop().toLowerCase();
    }

    function ocrReviewImageValidationMessage(file) {
      if (!file) return '답안지 사진을 먼저 선택해주세요.';
      const extension = ocrReviewImageExtension(file.name);
      if (!OCR_PHASE2B_IMAGE_EXTENSIONS.has(extension)) return 'jpg, jpeg, png, webp 형식의 답안지 사진만 사용할 수 있습니다.';
      if (file.type && !OCR_PHASE2B_IMAGE_TYPES.has(file.type)) return 'jpg, jpeg, png, webp 형식의 답안지 사진만 사용할 수 있습니다.';
      if (file.size > OCR_PHASE2B_MAX_IMAGE_BYTES) return '답안지 사진은 8MB 이하만 사용할 수 있습니다.';
      return '';
    }

    function ocrReviewRouteErrorMessage(code, httpStatus = 0) {
      const normalized = String(code || '').trim();
      const status = Number(httpStatus) || 0;
      if (status === 429 || normalized === 'provider_quota_or_rate_limited' || normalized === 'provider_http_429') {
        return '인식 요청이 많아 잠시 후 다시 시도해주세요. 그동안 답안을 직접 입력할 수 있습니다.';
      }
      if (status === 503 || normalized === 'provider_http_503' || normalized === 'provider_unavailable') {
        return '인식 서비스를 잠시 사용할 수 없습니다. 잠시 후 다시 시도하거나 답안을 직접 입력해주세요.';
      }
      if (normalized === 'feature_disabled') return '사진 인식 결과를 사용할 수 없습니다. 답안을 직접 입력해 주세요.';
      if (normalized === 'recognition_unavailable') return '학생이 확인할 수 있는 인식 결과가 준비되지 않았습니다. 사진을 다시 선택하거나 답안을 직접 입력해 주세요.';
      if (normalized === 'missing_image') return '답안지 사진을 먼저 선택해주세요.';
      if (normalized === 'unsupported_image_type') return 'jpg, jpeg, png, webp 형식의 답안지 사진만 사용할 수 있습니다.';
      if (normalized === 'image_too_large') return '답안지 사진은 8MB 이하만 사용할 수 있습니다.';
      if (normalized === 'marker_detection_failed') return '\uC0AC\uC9C4\uC5D0\uC11C \uB2F5\uC548\uC9C0 \uAE30\uC900\uC810\uC744 \uCC3E\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4. \uBC1D\uC740 \uACF3\uC5D0\uC11C \uB124 \uBAA8\uC11C\uB9AC\uAC00 \uBCF4\uC774\uAC8C \uB2E4\uC2DC \uCD2C\uC601\uD574\uC8FC\uC138\uC694.';
      if (normalized === 'answer_box_detection_failed' || normalized === 'crop_failed') return '\uB2F5\uCE78 \uC704\uCE58\uB97C \uC548\uC815\uC801\uC73C\uB85C \uCC3E\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4. \uB2F5\uC548\uC9C0\uB97C \uD3C9\uD3C9\uD558\uAC8C \uB193\uACE0 \uB2E4\uC2DC \uCD2C\uC601\uD574\uC8FC\uC138\uC694.';
      if (normalized === 'image_quality_failed') return '\uC0AC\uC9C4\uC774 \uD750\uB9AC\uAC70\uB098 \uADF8\uB9BC\uC790\uAC00 \uAC15\uD574 \uC778\uC2DD\uD558\uAE30 \uC5B4\uB835\uC2B5\uB2C8\uB2E4. \uBC1D\uC740 \uACF3\uC5D0\uC11C \uB2E4\uC2DC \uCD2C\uC601\uD574\uC8FC\uC138\uC694.';
      if (normalized === 'test_not_allowlisted' || normalized === 'blocked_test') return OCR_PHASE1_INELIGIBLE_MESSAGE;
      if (normalized === 'round_not_allowlisted' || normalized === 'wrong_round') return '이 회차는 아직 사진 인식 테스트 대상이 아닙니다. 기존 방식으로 입력해주세요.';
      if (normalized === 'forbidden_student' || normalized === 'ghost_sid') return '현재 학생 정보에서는 사진 인식 결과를 사용할 수 없습니다. 답안을 직접 입력해 주세요.';
      return '사진 인식 결과를 준비하지 못했습니다. 사진을 다시 선택하거나 답안을 직접 입력해 주세요.';
    }

    function ocrReviewMetaStatusMessage(meta) {
      return '사진 인식 검토 준비를 마쳤습니다. 불확실한 문항만 확인하고 빈칸은 직접 입력해주세요.';
    }

    async function ocrReviewRunWithProgress(action) {
      const stages = [
        '이미지 업로드 중입니다...',
        '답안지를 처리 중입니다...',
        '글자 인식 중입니다...',
        '검토 화면을 준비 중입니다...',
      ];
      ocrTestSheetSetStatus(stages[0]);
      const timers = stages.slice(1).map((message, index) => setTimeout(() => ocrTestSheetSetStatus(message), 650 + index * 850));
      try {
        return await action();
      } finally {
        timers.forEach(timer => clearTimeout(timer));
      }
    }

    async function ocrReviewFetchRoutePayload(test, round, imageFile) {
      const form = new FormData();
      form.append('sid', String(currentStudentSid() || ''));
      form.append('testId', String(test?.id || test?.testId || selTestId.value || ''));
      form.append('round', String(round || '1'));
      if (OCR_PHASE2E_FRESH_REVIEW_REQUESTED) {
        form.append('freshPhase2E', '1');
      }
      form.append('image', imageFile);
      const res = await studentAppRequest(OCR_PHASE2B_REVIEW_ENDPOINT, {
        method: 'POST',
        body: form,
        cache: 'no-store',
      });
      const data = await res.json().catch(() => ({}));
      const leaks = ocrReviewFindForbiddenKeys(data);
      if (leaks.length) {
        throw new Error('학생 화면에 표시할 수 없는 검토 정보가 포함되어 있습니다. 기존 방식으로 입력해주세요.');
      }
      if (!res.ok || data?.ok !== true) {
        throw new Error(ocrReviewRouteErrorMessage(data?.errorCode || data?.code, res.status));
      }
      if (!data.review_payload) throw new Error(ocrReviewRouteErrorMessage('invalid_response'));
      ocrReviewLastMeta = (data.review_meta && typeof data.review_meta === 'object') ? data.review_meta : null;
      return ocrReviewEnsureActionablePayload(data.review_payload);
    }

    async function ocrReviewOpenRouteFlow() {
      if (!OCR_TEST_SHEET_ENABLED) return;
      try {
        const t = findTestById(selType.value, selTestId.value, currentCur());
        if (!ocrPhase1TestEligible(t)) {
          ocrPhase1UpdateEligibilityState();
          return;
        }
        const round = parseInt(t?.round || selRound.value, 10) || 1;
        const imageFile = ocrReviewSelectedImage();
        const imageValidationMessage = ocrReviewImageValidationMessage(imageFile);
        if (imageValidationMessage) {
          ocrReviewPayload = null;
          ocrReviewClearPanel();
          ocrReviewClearFallback();
          ocrTestSheetSetStatus(imageValidationMessage, 'error');
          return;
        }
        if (btnOcrReviewOpen) {
          btnOcrReviewOpen.disabled = true;
          btnOcrReviewOpen.textContent = '사진 인식 중...';
        }
        ocrReviewLastMeta = null;
        ocrReviewClearFallback();
        ocrReviewPayload = ocrReviewClone(await ocrReviewRunWithProgress(() => ocrReviewFetchRoutePayload(t, round, imageFile)));
        ocrReviewRender();
        ocrTestSheetSetStatus(ocrReviewMetaStatusMessage(ocrReviewLastMeta));
      } catch (err) {
        ocrReviewPayload = null;
        ocrReviewClearPanel();
        const message = ocrReviewSafeFailureMessage(err?.message);
        window.__OCR_PHASE1_LAST_OPEN_ERROR__ = message;
        ocrReviewRenderFallback(message);
        ocrTestSheetSetStatus(message, 'error');
      } finally {
        if (btnOcrReviewOpen) {
          btnOcrReviewOpen.disabled = !ocrPhase1TestEligible(ocrPhase1CurrentTest());
          btnOcrReviewOpen.textContent = '사진 인식 결과 확인';
        }
      }
    }

    async function resolveAnswerUrlForSelection(testId, round) {
      if (studentAnswerAccessBlocked()) {
        return '';
      }

      const configuredTest = findTestById(selType.value, testId, currentCur());
      let answerUrl = answerUrlFromConfiguredTest(configuredTest);
      if (!answerUrl) {
        await loadAnswerLinkMap();
        answerUrl = getAnswerLinkForRound(testId, round, configuredTest?.sourceId);
      }

      return answerUrl || '';
    }

    async function renderAnswerLink(testId, round) {
      if (!answerLinkArea) return '';
      answerLinkArea.replaceChildren();
      answerLinkArea.style.display = 'block';

      if (studentAnswerAccessBlocked()) {
        answerLinkArea.textContent = '전체 답지는 학원 Wi-Fi에서만 볼 수 있습니다.';
        return '';
      }

      const answerUrl = await resolveAnswerUrlForSelection(testId, round);
      if (!answerUrl) {
        answerLinkArea.textContent = '전체 답지 링크 준비 중';
        return '';
      }

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ts-result-answer-button';
      button.textContent = '전체 답지 크게 보기';
      button.addEventListener('click', () => openAnswerPreview(answerUrl, '전체 답지 크게 보기'));
      answerLinkArea.appendChild(button);
      return answerUrl;
    }

    const open = (preselectTestId = '') => {
      if (studentTestSubmissionBlocked()) {
        showStudentTestSubmissionBlockedNotice();
        return false;
      }
      const assigned = getAssignedTestsForSubmit();
      if (!assigned.length && !OCR_TEST_SHEET_ENABLED) return false;
      const renderSelection = (preferredTestId = '') => {
        const myCur = currentCur();
        const configured = listAssignedConfiguredTests(myCur);
        const fallback = configured[0] || null;
        const requested = preferredTestId
          ? configured.find(t => String(t.id) === String(preferredTestId)) || fallback
          : fallback;
        const nextType = requested ? typeValueForTest(requested) : '';
        renderTypeOptions(nextType);
        renderTestOptions(requested?.id || preferredTestId);
        return requested;
      };

      renderSelection(preselectTestId);
      answersTextEl.value = '';
      memoEl.value = '';
      if (OCR_TEST_SHEET_ENABLED) {
        ocrReviewClearAnswersTextOrigin();
        ocrReviewEnsureAnswersTextLineCount();
        ocrTestSheetResetControls();
        ocrPhase1UpdateEligibilityState();
      }
      resetAnswerLink();
      resetResultPanel();
      if (!studentAnswerAccessBlocked()) void loadAnswerLinkMap();
      modal.style.display = 'flex';
      void testsConfigReady.then(() => {
        if (modal.style.display === 'none') return;
        renderSelection(selTestId.value || preselectTestId);
        if (OCR_TEST_SHEET_ENABLED) ocrPhase1UpdateEligibilityState();
      });
      return true;
    };
    const close = () => { modal.style.display = 'none'; };

    btnOpen?.addEventListener('click', () => { open(); });
    btnClose?.addEventListener('click', close);
    modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
    answerPreviewClose?.addEventListener('click', closeAnswerPreview);
    answerPreviewModal?.addEventListener('click', (e) => { if (e.target === answerPreviewModal) closeAnswerPreview(); });
    answerPreviewFrame?.addEventListener('load', () => {
      if (answerPreviewModal?.style.display === 'flex') setAnswerPreviewLoading(false);
    });

    selType.addEventListener('change', () => {
      resetAnswerLink();
      resetResultPanel();
      renderTestOptions();
      if (OCR_TEST_SHEET_ENABLED) {
        ocrTestSheetSetStatus();
        ocrReviewClearPanel();
        ocrReviewClearFallback();
        ocrReviewClearStaleAnswersText('시험 종류가 바뀌어 OCR로 채운 답안을 비웠습니다. 다시 인식하거나 직접 입력해주세요.');
        ocrPhase1UpdateEligibilityState();
      }
    });
    selTestId.addEventListener('change', () => {
      resetAnswerLink();
      resetResultPanel();
      const t = findTestById(selType.value, selTestId.value, currentCur());
      renderRoundOptions(t?.round || selRound.value);
      updateInfo();
      if (OCR_TEST_SHEET_ENABLED) {
        ocrTestSheetSetStatus();
        ocrReviewClearPanel();
        ocrReviewClearFallback();
        ocrReviewClearStaleAnswersText('시험이 바뀌어 OCR로 채운 답안을 비웠습니다. 다시 인식하거나 직접 입력해주세요.');
        ocrPhase1UpdateEligibilityState();
      }
    });
    selRound.addEventListener('change', () => {
      resetAnswerLink();
      resetResultPanel();
      const myCur = currentCur();
      const current = findTestById(selType.value, selTestId.value, myCur);
      const sibling = findSiblingTestByRound(selType.value, current, selRound.value, myCur);
      if (sibling) selTestId.value = sibling.id;
      updateInfo();
      if (OCR_TEST_SHEET_ENABLED) {
        ocrTestSheetSetStatus();
        ocrReviewClearPanel();
        ocrReviewClearFallback();
        ocrReviewClearStaleAnswersText('회차가 바뀌어 OCR로 채운 답안을 비웠습니다. 다시 인식하거나 직접 입력해주세요.');
        ocrPhase1UpdateEligibilityState();
      }
    });

    window.openAssignedTestSubmit = (testId = '') => open(testId);
    if (OCR_TEST_SHEET_ENABLED) {
      window.ocrTestSheetStartCapture = (test = {}) => {
        try {
          const testId = String(test?.id || test?.testId || test?.label || '');
          if (!open(testId)) return false;
          if (!ocrPhase1UpdateEligibilityState()) return false;
          ocrTestSheetSetStatus('사진 인식 결과 확인 버튼을 눌러주세요.');
          setTimeout(() => {
            try { btnOcrReviewOpen?.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch {}
          }, 0);
          return true;
        } catch {
          ocrTestSheetSetStatus('사진 인식 결과를 열지 못했습니다. 답안을 직접 입력해 주세요.', 'error');
          return false;
        }
      };
      const createReviewFixturePayloadForTest = () => {
        const t = findTestById(selType.value, selTestId.value, currentCur());
        if (!ocrPhase1TestEligible(t)) throw new Error(OCR_PHASE1_INELIGIBLE_MESSAGE);
        return ocrReviewClone(ocrReviewCreateMockPayload(t, selRound.value));
      };
      const ocrPhase2ReviewTestHook = {
        phase: 'phase2_review',
        allowedTestIds: () => Array.from(OCR_PHASE1_ALLOWED_TEST_IDS),
        answerModeForQuestion: questionNo => ocrReviewAnswerModeForQuestion(selTestId.value, Number(questionNo)),
        createFixturePayload: createReviewFixturePayloadForTest,
        convertToAnswersText: payload => ocrReviewConvertToAnswersText(payload),
        findForbiddenKeys: payload => ocrReviewFindForbiddenKeys(payload),
        findForbiddenPathValues: payload => ocrReviewFindForbiddenPathValues(payload),
        parseAnswersTextForTest: (text, problems = OCR_REVIEW_PROBLEM_COUNT) => parseAnswerSpec(text, Number(problems) || OCR_REVIEW_PROBLEM_COUNT),
        answerCountValidationMessage: (text, problems = OCR_REVIEW_PROBLEM_COUNT) => answerCountValidationMessage(text, Number(problems) || OCR_REVIEW_PROBLEM_COUNT),
        answerModeValidationMessage: (text, testId = selTestId.value, problems = OCR_REVIEW_PROBLEM_COUNT) => answerModeValidationMessageForAnswersText(text, testId, Number(problems) || OCR_REVIEW_PROBLEM_COUNT),
        submitOffsetGuardMessage: (text, test = findTestById(selType.value, selTestId.value, currentCur()), round = selRound.value) => submitOffsetGuardMessageForAnswersText(text, test, round),
        validateActionablePayloadForTest: payload => ocrReviewEnsureActionablePayload(payload),
        getSubmitGuardStateForTest: (testId = selTestId.value, round = selRound.value) => ocrReviewClone(ocrReviewSubmissionBlockState(testId, round)),
        getSubmitReadinessStateForTest: (testId = selTestId.value, round = selRound.value) => ocrReviewClone(ocrReviewSubmissionBlockState(testId, round)),
        getBlankAnswerStateForTest: (text = answersTextEl.value, problems = OCR_REVIEW_PROBLEM_COUNT) => ocrReviewClone(submitBlankAnswerState(text, Number(problems) || OCR_REVIEW_PROBLEM_COUNT)),
        serializeAnswersTextForSubmitForTest: (text = answersTextEl.value, problems = OCR_REVIEW_PROBLEM_COUNT) => submitAnswersTextForRequest(text, Number(problems) || OCR_REVIEW_PROBLEM_COUNT),
        getCurrentPayload: () => ocrReviewPayload ? ocrReviewClone(ocrReviewPayload) : null,
        getAssignedCaptureStateForTest: (test = {}) => {
          const requestedTestId = String(test?.id || test?.testId || test?.label || '');
          const configured = requestedTestId
            ? findTestById(typeValueForTest(test), requestedTestId, currentCur()) || findTestById(selType.value, requestedTestId, currentCur())
            : null;
          const target = configured || test || ocrPhase1CurrentTest();
          return {
            enabled: OCR_TEST_SHEET_ENABLED === true,
            requestedTestId,
            selectedTestId: selTestId.value,
            selectedRound: selRound.value,
            eligible: ocrPhase1TestEligible(target),
            hasStartCapture: typeof window.ocrTestSheetStartCapture === 'function',
            hasOpenAssignedTestSubmit: typeof window.openAssignedTestSubmit === 'function',
          };
        },
        startAssignedCaptureForTest: (test = {}) => window.ocrTestSheetStartCapture(test),
        renderPayloadForTest: payload => {
          ocrReviewPayload = null;
          ocrReviewClearPanel();
          ocrReviewClearFallback();
          ocrReviewPayload = ocrReviewClone(ocrReviewEnsureActionablePayload(payload));
          ocrReviewRender();
          return ocrReviewPanel;
        },
        getAnswersTextState: () => ({
          value: answersTextEl.value,
          ocrFilled: answersTextEl.dataset.ocrFilled || '',
          ocrTestId: answersTextEl.dataset.ocrTestId || '',
          ocrRound: answersTextEl.dataset.ocrRound || '',
          contextMatches: ocrReviewAnswersTextContextMatches(),
        }),
        getUnresolvedStateForTest: () => {
          const fallbackSummary = ocrReviewPayload ? ocrReviewPartialFillSummary(ocrReviewPayload.items) : null;
          const summary = ocrReviewRefreshUnresolvedSummary(fallbackSummary) || ocrReviewCurrentAnswerLineSummary(fallbackSummary);
          const wrap = ocrReviewPanel?.querySelector('.ts-ocr-unresolved');
          return {
            filledCount: summary.filledQuestions.length,
            blankCount: summary.blankQuestions.length,
            blankQuestions: summary.blankQuestions,
            text: wrap?.textContent || '',
            title: wrap?.querySelector('.ts-ocr-unresolved-title')?.textContent || '',
            countText: wrap?.querySelector('.ts-ocr-unresolved-count')?.textContent || '',
            progressText: wrap?.querySelector('.ts-ocr-unresolved-progress')?.textContent || '',
            previousButtonDisabled: wrap?.querySelector('.ts-ocr-prev-unresolved')?.disabled === true,
            nextButtonDisabled: wrap?.querySelector('.ts-ocr-next-unresolved')?.disabled === true,
          };
        },
        getSelfReviewStateForTest: () => {
          const submissionReadiness = ocrReviewSubmissionBlockState();
          return {
            items: ocrReviewPayload ? ocrReviewPayload.items.map(item => ({
              question_no: item.question_no,
              review_state: item.review_state,
              resolution: item.resolution,
              final_answer: item.final_answer,
              allow_edit: item.allow_edit,
              requires_confirmation: item.requires_confirmation,
              retake_reason: item.retake_reason,
              user_modified: item.user_modified === true,
            })) : [],
            submissionReadiness,
            submissionBlock: submissionReadiness?.blocked ? submissionReadiness : null,
            telemetry: ocrReviewTelemetrySnapshot(),
          };
        },
        setReviewAnswerForTest: (questionNo, answer, intent = 'edit') => {
          const item = ocrReviewPayload?.items.find(entry => entry.question_no === Number(questionNo));
          if (!item) return false;
          const updated = ocrReviewSetItemAnswer(item, answer, intent);
          if (updated) ocrReviewRender();
          return updated;
        },
        focusNextUnresolvedForTest: () => {
          ocrReviewFocusNextUnresolved();
          const focusedCard = ocrReviewPanel?.querySelector('.ts-ocr-card[data-ocr-focus="true"]');
          return {
            focusedQuestionNo: focusedCard ? Number(focusedCard.dataset.questionNo) : null,
            status: ocrStatusEl?.textContent || '',
            state: window.__OCR_PHASE2_REVIEW_TEST_HOOK__?.getUnresolvedStateForTest?.() || null,
          };
        },
        setAnswersTextForTest: text => {
          answersTextEl.value = String(text || '');
          answersTextEl.dispatchEvent(new Event('input', { bubbles: true }));
          return window.__OCR_PHASE2_REVIEW_TEST_HOOK__?.getAnswersTextState?.();
        },
        setAnswerLineForTest: (questionNo, answer) => {
          ocrReviewSetAnswerLine(Number(questionNo), answer);
          ocrReviewSyncPayloadFromAnswersText();
          ocrReviewRefreshUnresolvedSummary();
          return window.__OCR_PHASE2_REVIEW_TEST_HOOK__?.getAnswersTextState?.();
        },
        applyAnswersTextForTest: payload => {
          const result = ocrReviewPrepareAnswersText(payload);
          ocrReviewApplyAnswersText(result);
          return {
            value: answersTextEl.value,
            ocrFilled: answersTextEl.dataset.ocrFilled || '',
            ocrTestId: answersTextEl.dataset.ocrTestId || '',
            ocrRound: answersTextEl.dataset.ocrRound || '',
            contextMatches: ocrReviewAnswersTextContextMatches(),
          };
        },
        clearStaleAnswersText: () => ocrReviewClearStaleAnswersText(),
        isCurrentTestEligible: () => ocrPhase1TestEligible(ocrPhase1CurrentTest()),
        setImageFileForTest: file => {
          const transfer = new DataTransfer();
          transfer.items.add(file);
          if (ocrReviewImageEl) ocrReviewImageEl.files = transfer.files;
        },
        fetchRoutePayload: () => ocrReviewFetchRoutePayload(ocrPhase1CurrentTest(), selRound.value, ocrReviewSelectedImage()),
        getLastReviewMeta: () => ocrReviewLastMeta ? ocrReviewClone(ocrReviewLastMeta) : null,
        openRouteFlow: ocrReviewOpenRouteFlow,
        openReviewFlow: ocrReviewOpenRouteFlow,
      };
      window.__OCR_PHASE2_REVIEW_TEST_HOOK__ = ocrPhase2ReviewTestHook;
      window.__OCR_PHASE1_TEST_HOOK__ = {
        ...ocrPhase2ReviewTestHook,
        createMockPayload: createReviewFixturePayloadForTest,
        openMockFlow: ocrReviewOpenRouteFlow,
      };
    }
    window.__TEST_SUBMIT_RESULT_UI_HOOK__ = {
      buildResultForTest: ({ testId = selTestId.value, round = selRound.value, answersText = '', responseData = {}, fallbackGraded = null, answerUrl = '' } = {}) => {
        const test = findTestById(selType.value, testId, currentCur()) || ocrPhase1CurrentTest();
        return buildSubmitResultViewModel({ test, round, answersText, responseData, fallbackGraded, answerUrl });
      },
      renderResultForTest: options => {
        const result = window.__TEST_SUBMIT_RESULT_UI_HOOK__.buildResultForTest(options || {});
        renderSubmitResultPanel(result);
        return resultPanel;
      },
      getResultPanelText: () => resultPanel?.textContent || '',
      hasAnswerPreview: () => Boolean(answerPreviewModal && answerPreviewFrame && answerPreviewOpenExternal),
    };
    if (OCR_TEST_SHEET_ENABLED) {
      ocrPhase1UpdateEligibilityState();
      ocrReviewUpdateSelectedImageDisplay();
      btnOcrReviewPick?.addEventListener('click', () => {
        try { ocrReviewImageEl?.click(); } catch {}
      });
      ocrReviewImageEl?.addEventListener('change', () => {
        ocrReviewPayload = null;
        ocrReviewClearPanel();
        ocrReviewClearFallback();
        const file = ocrReviewSelectedImage();
        ocrReviewUpdateSelectedImageDisplay(file);
        const validationMessage = ocrReviewImageValidationMessage(file);
        if (validationMessage) ocrTestSheetSetStatus(validationMessage, file ? 'error' : '');
        else ocrTestSheetSetStatus('사진이 선택되었습니다. 사진 인식 결과 확인 버튼을 눌러주세요.');
      });
      btnOcrReviewOpen?.addEventListener('click', () => { void ocrReviewOpenRouteFlow(); });
    }
    answersTextEl.addEventListener('input', () => {
      if (OCR_TEST_SHEET_ENABLED) {
        if (answersTextEl.dataset.ocrProgrammaticFill === '1') return;
        ocrReviewEnsureAnswersTextLineCount();
        ocrReviewClearAnswersTextOrigin();
        ocrReviewSyncPayloadFromAnswersText();
        ocrReviewRefreshUnresolvedSummary();
      }
      resetResultPanel();
    });

    btnSubmit?.addEventListener('click', async () => {
      if (studentTestSubmissionBlocked()) {
        showStudentTestSubmissionBlockedNotice();
        return;
      }
      const reviewBlock = OCR_TEST_SHEET_ENABLED
        ? ocrReviewSubmissionBlockState(selTestId.value, selRound.value)
        : null;
      if (reviewBlock?.blocked) {
        if (reviewBlock.firstQuestionNo) ocrReviewFocusQuestion(reviewBlock.firstQuestionNo);
        alert(reviewBlock.message);
        return;
      }
      const type = selType.value;
      const testId = selTestId.value;
      const answersText = String(answersTextEl.value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
      const memo = String(memoEl.value || '').trim();
      const ocrFilledSubmission = answersTextEl.dataset.ocrFilled === '1';
      resetAnswerLink();
      resetResultPanel();

      if (!testId) return alert('시험을 선택해주세요.');
      if (OCR_TEST_SHEET_ENABLED && !ocrReviewAnswersTextContextMatches()) {
        return alert('OCR로 채운 답안이 현재 선택한 시험/회차와 맞지 않습니다. 다시 인식하거나 직접 입력해주세요.');
      }

      const t = findTestById(type, testId, currentCur());
      if (!t) return alert('시험 정보를 찾지 못했습니다.');
      const answerCountMessage = answerCountValidationMessage(answersText, t.problems);
      if (answerCountMessage) return alert(answerCountMessage);
      const answerModeMessage = answerModeValidationMessageForAnswersText(answersText, testId, t.problems);
      if (answerModeMessage) return alert(answerModeMessage);
      const blankAnswerState = submitBlankAnswerState(answersText, t.problems);
      if (blankAnswerState && !window.confirm(blankAnswerState.message)) return;
      const round = parseInt(t.round || selRound.value, 10) || 1;
      if (selRound) selRound.value = String(round);
      const offsetGuardMessage = submitOffsetGuardMessageForAnswersText(answersText, t, round);
      if (offsetGuardMessage) {
        updateInfo(offsetGuardMessage);
        try { answersTextEl.focus(); } catch {}
        return alert(offsetGuardMessage);
      }

      // ✅ 1) 서버 자동 채점/저장
      try {
        const requestAnswersText = submitAnswersTextForRequest(answersText, t.problems);
        const requestSid = currentStudentSid();
        const res = await studentAppRequest('/api/submit-test', {
          method: 'POST',
          headers: CT,
          body: JSON.stringify({
            sid: requestSid,
            testId,
            round,
            answersText: requestAnswersText,
            memo,
            answerSource: ocrFilledSubmission ? 'ocr_review' : 'manual',
            ocrReview: ocrFilledSubmission
          })
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.ok === false) {
          const message = data?.message || '제출 안전 검사에 통과하지 못했습니다. 답안과 시험/회차를 다시 확인해주세요.';
          if (data?.fallbackAllowed === false || data?.errorCode === 'possible_answer_offset') {
            alert(message);
            return;
          }
          const failure = new Error(message || String(res.status));
          failure.status = res.status;
          failure.code = String(data?.errorCode || data?.code || '');
          throw failure;
        }

        updateInfo();
        resetAnswerLink();
        const answerUrl = await resolveAnswerUrlForSelection(testId, round);
        renderSubmitResultPanel(buildSubmitResultViewModel({
          test: t,
          round,
          answersText,
          responseData: data,
          answerUrl,
        }));

        try { localStorage.setItem('updPing', Date.now().toString()); } catch { }
        return;
      } catch (e) {
        console.warn('[submit-test] server submission failed', e);
        if (ocrFilledSubmission) {
          alert('OCR로 채운 답안은 서버 안전 검사를 통과해야 제출할 수 있습니다. 다시 인식하거나 직접 입력으로 바꾼 뒤 제출해주세요.');
          return;
        }
        /* STUDENT_APP_PUBLIC_SUBMIT_FAILURE_GATE */
        const failureDecision = await studentAppResolveSubmitFailure({
          publicMode: STUDENT_APP_PUBLIC_MODE,
          error: e,
        });
        if (!failureDecision.mayUseLegacyFallback) {
          updateInfo(failureDecision.message);
          alert(failureDecision.message);
          return;
        }
      }

      /* STUDENT_APP_LOCAL_SUBMIT_FALLBACK_START */
      // ✅ 2) fallback: 클라 채점 후 기존 방식으로 저장(서버가 구버전일 때 대비)
      const key = getKeyForRound(t, round);
      if (!key) {
        alert('정답키가 없어서 제출할 수 없습니다. 선생님께 정답 등록 요청하세요.');
        return;
      }

      const graded = gradeClientSide(answersText, key, t.problems);
      const score = `${graded.correct}/${graded.total}`;
      const fullName = (type === 'UNIT' || type === '단원평가') ? t.name : `${typeLabel(type)} / ${t.name}`;

      // 구버전 서버는 name/score/wrong로 저장되던 방식
      const requestSid = currentStudentSid();
      const payload = { sid: requestSid, name: fullName, score, wrong: graded.wrong, memo };

      try {
        const res = await fetch('/api/submit-test', { method: 'POST', headers: CT, body: JSON.stringify(payload) });
        if (!res.ok) throw new Error(String(res.status));
      } catch {
        // 마지막 백업: logs.json 직접 머지
        try {
          const today = todayLocalKey();
          const logs = await fetch(`/api/logs/entry?date=${encodeURIComponent(today)}&sid=${encodeURIComponent(requestSid)}`, { cache: 'no-store' })
            .then(r => r.json()).catch(() => ({}));
          const entry = (logs && logs.entry && typeof logs.entry === 'object') ? logs.entry : {};
          const tests = Array.isArray(entry.tests) ? entry.tests.slice() : [];
          tests.push({ name: fullName, score, wrong: graded.wrong, memo, createdAt: new Date().toISOString() });
          const ok = await fetch('/api/logs/patch', {
            method: 'POST',
            headers: CT,
            body: JSON.stringify({ date: today, sid: requestSid, entry: { tests } })
          });
          if (!ok.ok) throw new Error(String(ok.status));
        } catch {
          alert('제출 실패: 나중에 다시 시도해주세요.');
          return;
        }
      }

      // tests.json 집계용(가능하면)
      try {
        await fetch('/api/tests', {
          method: 'POST', headers: CT,
          body: JSON.stringify({
            [todayLocalKey()]: {
              [requestSid]: [{
                name: fullName,
                score,
                wrong: graded.wrong,
                memo,
                createdAt: new Date().toISOString()
              }]
            }
          })
        });
      } catch { }

      try { localStorage.setItem('updPing', Date.now().toString()); } catch { }
      updateInfo();
      resetAnswerLink();
      const answerUrl = await resolveAnswerUrlForSelection(testId, round);
      renderSubmitResultPanel(buildSubmitResultViewModel({
        test: t,
        round,
        answersText,
        fallbackGraded: graded,
        answerUrl,
      }));
    });
  }

  // ───────────── init ─────────────
  injectStyles();
  ensureModal();
  initLogic().catch(err => {
    console.warn('[test submit modal] init failed', err);
  });
})();
