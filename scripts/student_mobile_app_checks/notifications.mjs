import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..', '..');
const files = Object.freeze({
  sw: path.join(root, 'static', 'sw.js'),
  contract: path.join(root, 'static', 'js', 'student-app-contract.js'),
  student: path.join(root, 'static', 'js', 'student.js'),
  html: path.join(root, 'static', 'student.html'),
  css: path.join(root, 'static', 'css', 'student.css'),
  push: path.join(root, 'static', 'js', 'student-app-push.js'),
  app: path.join(root, 'static', 'js', 'student-app.js'),
});

const CATEGORIES = Object.freeze(['schedule', 'homework', 'progress', 'announcement']);
const eventId = character => `evt_${String(character).repeat(32)}`;

function extract(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, `missing source scope ${startMarker}`);
  return source.slice(start, end);
}

function response(status, payload = null) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => payload,
  };
}

function preferencePayload(overrides = {}, revision = 0) {
  return {
    ok: true,
    preferences: {
      schedule: true,
      homework: true,
      progress: true,
      announcement: true,
      ...overrides,
    },
    revision,
  };
}

function loadStudentContracts(source) {
  const preferences = extract(
    source,
    '/* STUDENT_APP_NOTIFICATION_PREFERENCES_START */',
    '/* STUDENT_APP_NOTIFICATION_PREFERENCES_END */',
  );
  const homework = extract(source, '/* STUDENT_APP_HOMEWORK_START */', '/* STUDENT_APP_HOMEWORK_END */');
  const announcements = extract(
    source,
    '/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_START */',
    '/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_END */',
  );
  const context = vm.createContext({ URLSearchParams, Object, Number, String, Date, Set });
  vm.runInContext(`${preferences}\n${homework}\n${announcements}\n` + `
    globalThis.notificationContracts = {
      normalizeStudentNotificationPreferencesPayload,
      studentAppHomeDeepLink,
      studentHomeworkDeepLink,
      studentAppAnnouncementDeepLink,
      studentAppOpenAnnouncementDeepLink,
    };
  `, context, { filename: 'static/js/student.js#notification-contracts' });
  return context.notificationContracts;
}

class FakeElement {
  constructor() {
    this.hidden = true;
    this.disabled = false;
    this.checked = false;
    this.textContent = '';
    this.attributes = new Map();
  }

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }
}

function createPreferenceHarness(studentSource, { publicMode = true, initialResponses = [] } = {}) {
  const preferencesContract = extract(
    studentSource,
    '/* STUDENT_APP_NOTIFICATION_PREFERENCES_START */',
    '/* STUDENT_APP_NOTIFICATION_PREFERENCES_END */',
  );
  const settingsStart = studentSource.indexOf('  function setNotificationPreferencesBusy(busy)');
  const settingsEnd = studentSource.indexOf("  async function preparePublicStudentSettings()", settingsStart);
  assert.ok(settingsStart >= 0 && settingsEnd > settingsStart, 'notification settings controller scope');
  const settingsSource = studentSource.slice(settingsStart, settingsEnd);
  const fieldset = new FakeElement();
  const status = new FakeElement();
  const retry = new FakeElement();
  const inputs = Object.fromEntries(CATEGORIES.map(category => [category, new FakeElement()]));
  const calls = [];
  const recoveries = [];
  const queue = [...initialResponses];
  const context = vm.createContext({
    URLSearchParams,
    Object,
    Number,
    String,
    Date,
    Set,
    JSON,
    Promise,
    Error,
    STUDENT_APP_PUBLIC_MODE: publicMode,
    studentNotificationPreferences: fieldset,
    studentNotificationPreferencesStatus: status,
    studentNotificationPreferencesRetry: retry,
    studentNotificationPreferenceInputs: inputs,
    notificationPreferencesState: null,
    notificationPreferencesLoading: false,
    StudentAppSessionError: class StudentAppSessionError extends Error {
      constructor(code, httpStatus = 0) {
        super(code);
        this.code = code;
        this.status = httpStatus;
      }
    },
    handleStudentAppSessionFailure: error => {
      if (error?.status === 401 || error?.status === 403) {
        recoveries.push(error.status);
        return true;
      }
      return false;
    },
    studentAppRequest: async (url, init = {}) => {
      calls.push({ url, init });
      const next = queue.shift();
      if (next instanceof Error) throw next;
      assert.ok(next, `missing fake response for ${url}`);
      return next;
    },
  });
  vm.runInContext(`${preferencesContract}\n${settingsSource}\n` + `
    globalThis.preferenceController = {
      loadNotificationPreferences,
      saveNotificationPreferences,
      state: () => notificationPreferencesState,
    };
  `, context, { filename: 'static/js/student.js#notification-settings' });
  return {
    controller: context.preferenceController,
    fieldset,
    status,
    retry,
    inputs,
    calls,
    recoveries,
    enqueue: value => queue.push(value),
    source: settingsSource,
  };
}

function serviceWorkerHarness(source, { clients = [], origin = 'https://app.test' } = {}) {
  const listeners = new Map();
  const notifications = [];
  const opened = [];
  const navigated = [];
  let clientLookups = 0;
  const normalizedClients = clients.map(client => ({
    url: client.url,
    navigate: async target => {
      navigated.push(target);
      return { focus: async () => target };
    },
  }));
  const context = vm.createContext({
    console,
    URL,
    Response,
    Request,
    Promise,
    caches: {
      open: async () => ({ addAll: async () => {}, put: async () => {} }),
      keys: async () => [],
      delete: async () => true,
      match: async () => undefined,
    },
    fetch: async () => new Response('ok'),
    self: {
      location: { origin },
      addEventListener: (name, callback) => listeners.set(name, callback),
      skipWaiting: async () => {},
      registration: {
        showNotification: async (title, options) => notifications.push({ title, options }),
      },
      clients: {
        claim: async () => {},
        matchAll: async () => {
          clientLookups += 1;
          return normalizedClients;
        },
        openWindow: async target => {
          opened.push(target);
          return target;
        },
      },
    },
  });
  vm.runInContext(source, context, { filename: 'static/sw.js' });
  return {
    notifications,
    opened,
    navigated,
    get clientLookups() { return clientLookups; },
    async push(payload) {
      let pending = null;
      listeners.get('push')({
        data: { json: () => payload },
        waitUntil: promise => { pending = promise; },
      });
      if (pending) await pending;
      return pending !== null;
    },
    async click(data) {
      let pending = null;
      let closed = 0;
      listeners.get('notificationclick')({
        notification: { data, close: () => { closed += 1; } },
        waitUntil: promise => { pending = promise; },
      });
      if (pending) await pending;
      return { waited: pending !== null, closed };
    },
  };
}

async function traceCanonicalCacheKey(source) {
  const listeners = new Map();
  const putKeys = [];
  const context = vm.createContext({
    console,
    URL,
    Response,
    Request,
    Promise,
    caches: {
      open: async () => ({
        addAll: async () => {},
        put: async key => putKeys.push(typeof key === 'string' ? key : key.url),
      }),
      keys: async () => [],
      delete: async () => true,
      match: async () => undefined,
    },
    fetch: async () => new Response('shell', { status: 200 }),
    self: {
      location: { origin: 'https://app.test' },
      addEventListener: (name, callback) => listeners.set(name, callback),
      skipWaiting: async () => {},
      registration: { showNotification: async () => {} },
      clients: { claim: async () => {}, matchAll: async () => [], openWindow: async () => {} },
    },
  });
  vm.runInContext(source, context, { filename: 'static/sw.js#cache-key' });
  const request = new Request('https://app.test/app?view=homework&item=homework-1', {
    method: 'GET',
    headers: { Accept: 'text/html' },
  });
  let pending = null;
  listeners.get('fetch')({ request, respondWith: promise => { pending = promise; } });
  assert.ok(pending, 'app navigation should be intercepted');
  await pending;
  return putKeys;
}

export async function runChecks() {
  const [sw, student, html, css, push, app, contract] = await Promise.all([
    fs.readFile(files.sw, 'utf8'),
    fs.readFile(files.student, 'utf8'),
    fs.readFile(files.html, 'utf8'),
    fs.readFile(files.css, 'utf8'),
    fs.readFile(files.push, 'utf8'),
    fs.readFile(files.app, 'utf8'),
    import(pathToFileURL(files.contract).href),
  ]);
  const passed = [];
  const check = (name, callback) => { callback(); passed.push(name); };
  const checkAsync = async (name, callback) => { await callback(); passed.push(name); };
  const studentContracts = loadStudentContracts(student);

  check('preferences projection accepts only the four exact boolean categories and a nonnegative revision', () => {
    const normalized = studentContracts.normalizeStudentNotificationPreferencesPayload(preferencePayload({ homework: false }, 3));
    assert.equal(normalized.revision, 3);
    assert.deepEqual(JSON.parse(JSON.stringify(normalized.preferences)), {
      schedule: true,
      homework: false,
      progress: true,
      announcement: true,
    });
    assert.equal(studentContracts.normalizeStudentNotificationPreferencesPayload(preferencePayload({ extra: true })), null);
    assert.equal(studentContracts.normalizeStudentNotificationPreferencesPayload(preferencePayload({ progress: 'true' })), null);
    assert.equal(studentContracts.normalizeStudentNotificationPreferencesPayload({ ...preferencePayload(), revision: -1 }), null);
    assert.equal(studentContracts.normalizeStudentNotificationPreferencesPayload({ ...preferencePayload(), revision: '0' }), null);
    const missing = preferencePayload();
    delete missing.preferences.schedule;
    assert.equal(studentContracts.normalizeStudentNotificationPreferencesPayload(missing), null);
  });

  check('app and student deep-link parsers rebuild only unambiguous home, homework, board, or legacy announcement targets', () => {
    const homeworkEvent = eventId('H');
    const boardEvent = eventId('B');
    assert.equal(contract.studentPageUrl('sid-1', '?view=home'), '/student/sid-1?view=home');
    assert.equal(contract.studentPageUrl('sid-1', `?view=homework&item=${homeworkEvent}&next=https://evil.test`), `/student/sid-1?view=homework&item=${homeworkEvent}`);
    assert.equal(contract.studentPageUrl('sid-1', `?view=board&item=${boardEvent}`), `/student/sid-1?view=board&item=${boardEvent}`);
    assert.equal(contract.studentPageUrl('sid-1', '?view=homework&item=homework-1'), '/student/sid-1');
    assert.equal(contract.studentPageUrl('sid-1', '?view=board&item=ann:1'), '/student/sid-1');
    assert.equal(contract.studentPageUrl('sid-1', '?announcement=ann:1&next=https://evil.test'), '/student/sid-1?announcement=ann%3A1');
    assert.equal(contract.studentPageUrl('sid-1', '?view=homework&view=board&item=x'), '/student/sid-1');
    assert.equal(contract.studentPageUrl('sid-1', '?view=home&item=x'), '/student/sid-1');
    assert.equal(contract.studentPageUrl('sid-1', '?view=homework&item=..%2Fsecret'), '/student/sid-1');
    assert.equal(contract.studentPageUrl('sid-1', '?announcement=ann:1&view=board&item=ann:1'), '/student/sid-1');
    assert.equal(studentContracts.studentAppHomeDeepLink('?view=home'), true);
    assert.equal(studentContracts.studentAppHomeDeepLink('?view=home&item=x'), false);
    assert.equal(studentContracts.studentHomeworkDeepLink(`?view=homework&item=${homeworkEvent}`), homeworkEvent);
    assert.equal(studentContracts.studentHomeworkDeepLink('?announcement=ann:1&view=homework&item=homework-1'), '');
    assert.equal(studentContracts.studentAppAnnouncementDeepLink(`?view=board&item=${boardEvent}`), boardEvent);
    assert.equal(studentContracts.studentAppAnnouncementDeepLink('?announcement=ann:1'), 'ann:1');
    assert.equal(studentContracts.studentAppAnnouncementDeepLink('?view=board&item=one&item=two'), '');
    let opened = null;
    assert.equal(studentContracts.studentAppOpenAnnouncementDeepLink(
      'evt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
      [{ id: 'ann:1', notificationEventId: 'evt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' }],
      item => { opened = item.id; },
    ), true);
    assert.equal(opened, 'ann:1');
  });

  await checkAsync('generic service-worker copy is fixed by type and payload URL, title, body, SID, and details never become authority', async () => {
    const cases = [
      ['class_reminder', eventId('A'), '수업 알림', '학생 앱에서 예정된 수업을 확인해 주세요.', '/app?view=home'],
      ['schedule_changed', eventId('B'), '수업 일정 안내', '학생 앱에서 변경된 수업 일정을 확인해 주세요.', '/app?view=home'],
      ['homework_assigned', eventId('C'), '새 숙제가 등록되었습니다', '학생 앱에서 숙제와 기한을 확인해 주세요.', `/app?view=homework&item=${eventId('C')}`],
      ['homework_due', eventId('D'), '숙제 기한 알림', '학생 앱에서 마감 예정 숙제를 확인해 주세요.', `/app?view=homework&item=${eventId('D')}`],
      ['progress_milestone', eventId('E'), '진도 알림', '학생 앱에서 학습 진도를 확인해 주세요.', '/app?view=home'],
      ['announcement_published', eventId('F'), '새 공지가 도착했습니다', '학생 앱을 열어 공지 내용을 확인해 주세요.', `/app?view=board&item=${eventId('F')}`],
      ['push_test', eventId('T'), '학생 앱 테스트 알림', '개발용 Push 수신 테스트가 완료되었습니다.', '/app?view=home'],
    ];
    for (const [type, eventId, title, body, target] of cases) {
      const harness = serviceWorkerHarness(
        sw,
        type === 'push_test' ? { origin: 'https://dev-app.5a-math.com' } : {},
      );
      assert.equal(await harness.push({
        type,
        eventId,
        url: 'javascript:alert(1)',
        title: '한동훈',
        body: '개념서 42쪽 오후 6시',
        sid: 'private-sid',
      }), true);
      assert.equal(harness.notifications.length, 1);
      const shown = harness.notifications[0];
      assert.equal(shown.title, title);
      assert.equal(shown.options.body, body);
      const serialized = JSON.stringify(shown);
      for (const marker of ['javascript:', '한동훈', '개념서', 'private-sid']) assert.equal(serialized.includes(marker), false);
      assert.equal(await harness.click(shown.options.data).then(result => result.waited), true);
      assert.deepEqual(harness.opened, [target]);
    }
  });

  await checkAsync('legacy announcement remains compatible while malformed or unknown events do no work', async () => {
    const legacy = serviceWorkerHarness(sw);
    await legacy.push({ type: 'announcement', announcementId: 'ann:legacy', url: 'https://evil.test' });
    assert.equal(legacy.notifications.length, 1);
    assert.equal(legacy.notifications[0].title, '새 공지가 도착했습니다');
    await legacy.click(legacy.notifications[0].options.data);
    assert.deepEqual(legacy.opened, ['/app?announcement=ann%3Alegacy']);

    const invalid = serviceWorkerHarness(sw);
    assert.equal(await invalid.push({ type: 'push_test', eventId: eventId('T') }), false);
    for (const payload of [
      { type: 'unknown', eventId: 'event-1' },
      { type: 'toString', eventId: 'event-1' },
      { type: 'homework_due', eventId: '../secret' },
      { type: 'homework_due', eventId: 'homework:colon' },
      { type: 'announcement_published', eventId: '' },
      { type: 'push_test', eventId: '../secret', url: '/app?view=homework' },
      { type: 'push_test', eventId: `${eventId('T')}extra`, url: 'https://evil.test' },
      { type: 'announcement', announcementId: 'https://evil.test' },
    ]) assert.equal(await invalid.push(payload), false);
    assert.equal(invalid.notifications.length, 0);
    const lookupCount = invalid.clientLookups;
    const clicked = await invalid.click({ type: 'homework_due', eventId: '../secret', url: 'https://evil.test' });
    assert.equal(clicked.closed, 1);
    assert.equal(clicked.waited, false);
    assert.equal(invalid.clientLookups, lookupCount);
    assert.deepEqual(invalid.opened, []);
  });

  await checkAsync('existing app windows are navigated to canonical targets and query navigations cache under /app only', async () => {
    const harness = serviceWorkerHarness(sw, { clients: [{ url: 'https://app.test/student/sid-1' }] });
    await harness.push({ type: 'homework_due', eventId: eventId('D'), url: '//evil.test' });
    await harness.click(harness.notifications[0].options.data);
    assert.deepEqual(harness.navigated, [`/app?view=homework&item=${eventId('D')}`]);
    assert.deepEqual(harness.opened, []);
    assert.deepEqual(await traceCanonicalCacheKey(sw), ['/app']);
    assert.match(sw, /student-app-shell-v11/);
  });

  await checkAsync('preferences GET and POST use a full snapshot without SID, device, storage, authorization, or permission prompts', async () => {
    const harness = createPreferenceHarness(student, {
      initialResponses: [
        response(200, preferencePayload({ homework: false }, 0)),
        response(200, preferencePayload({ schedule: false, homework: false }, 1)),
      ],
    });
    await harness.controller.loadNotificationPreferences();
    assert.equal(harness.calls[0].url, '/api/mobile/push/preferences');
    assert.deepEqual(JSON.parse(JSON.stringify(harness.calls[0].init)), { cache: 'no-store' });
    assert.equal(harness.fieldset.hidden, false);
    assert.equal(harness.inputs.homework.checked, false);
    assert.equal(harness.inputs.schedule.checked, true);
    assert.equal(harness.inputs.schedule.disabled, false);
    harness.inputs.schedule.checked = false;
    await harness.controller.saveNotificationPreferences();
    const post = harness.calls[1];
    assert.equal(post.url, '/api/mobile/push/preferences');
    assert.equal(post.init.method, 'POST');
    assert.deepEqual(JSON.parse(post.init.body), {
      preferences: { schedule: false, homework: false, progress: true, announcement: true },
      expectedRevision: 0,
    });
    assert.equal(harness.controller.state().revision, 1);
    const serialized = JSON.stringify(post);
    assert.doesNotMatch(serialized, /(?:sid|studentSid|deviceId|authorization|bearer|csrf|endpoint)/i);
    assert.doesNotMatch(harness.source, /requestPermission|Notification\.permission|localStorage|sessionStorage|indexedDB/i);
  });

  await checkAsync('feature-off, conflict, session failure, and network/server failure stay explicit and preserve the last successful snapshot', async () => {
    const disabled = createPreferenceHarness(student, { initialResponses: [response(404)] });
    await disabled.controller.loadNotificationPreferences();
    assert.equal(disabled.fieldset.hidden, true);

    const local = createPreferenceHarness(student, { publicMode: false, initialResponses: [response(200, preferencePayload())] });
    await local.controller.loadNotificationPreferences();
    assert.equal(local.calls.length, 0);

    for (const status of [401, 403]) {
      const recovery = createPreferenceHarness(student, { initialResponses: [response(status)] });
      await recovery.controller.loadNotificationPreferences();
      assert.deepEqual(recovery.recoveries, [status]);
    }

    const malformed = createPreferenceHarness(student, { initialResponses: [response(200, { ok: true, internal: 'secret' })] });
    await malformed.controller.loadNotificationPreferences();
    assert.equal(malformed.retry.hidden, false);
    assert.equal(malformed.inputs.schedule.disabled, true);
    assert.doesNotMatch(malformed.status.textContent, /internal|secret/i);

    const failed = createPreferenceHarness(student, {
      initialResponses: [response(200, preferencePayload({}, 2)), response(503, { detail: 'sqlite secret' })],
    });
    await failed.controller.loadNotificationPreferences();
    failed.inputs.schedule.checked = false;
    await failed.controller.saveNotificationPreferences();
    assert.equal(failed.inputs.schedule.checked, true, 'failed save must restore the last server snapshot');
    assert.equal(failed.retry.hidden, false);
    assert.doesNotMatch(failed.status.textContent, /sqlite|secret|database|trace/i);
    failed.inputs.homework.checked = false;
    failed.enqueue(new Error('offline transport detail'));
    await failed.controller.saveNotificationPreferences();
    assert.equal(failed.inputs.homework.checked, true, 'offline save must retain the last server snapshot');
    assert.equal(failed.retry.hidden, false);
    assert.doesNotMatch(failed.status.textContent, /transport|offline detail/i);

    const conflict = createPreferenceHarness(student, {
      initialResponses: [
        response(200, preferencePayload({}, 4)),
        response(409),
        response(200, preferencePayload({ progress: false }, 5)),
      ],
    });
    await conflict.controller.loadNotificationPreferences();
    conflict.inputs.progress.checked = false;
    await conflict.controller.saveNotificationPreferences();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(conflict.calls.length, 3);
    assert.equal(conflict.controller.state().revision, 5);
    assert.equal(conflict.inputs.progress.checked, false);
  });

  check('settings markup and styles provide semantic labels, live feedback, mobile touch targets, dark tokens, and reduced motion', () => {
    assert.match(html, /student\.css\?v=20260809-focus-r1/);
    assert.match(html, /student\/announcementState\.js\?v=20260828-announcement-state-r1/);
    assert.match(html, /student\/testPresentation\.js\?v=20260828-test-presentation-r1/);
    assert.match(html, /student\.js\?v=20260828-test-presentation-r1/);
    assert.match(html, /<fieldset[^>]+id="studentNotificationPreferences"[^>]+hidden>/);
    assert.match(html, /<legend>받을 알림<\/legend>/);
    for (const [category, label] of [['schedule', '수업'], ['homework', '숙제'], ['progress', '진도'], ['announcement', '공지']]) {
      assert.match(html, new RegExp(`for="studentNotification[^\"]+"[\\s\\S]*?<span>${label}<\\/span>[\\s\\S]*?data-student-notification-category="${category}"`));
    }
    assert.match(html, /id="studentNotificationPreferencesStatus"[^>]+role="status"[^>]+aria-live="polite"/);
    const cssStart = css.indexOf('body.student-page.student-app-mobile-surface .student-notification-preferences');
    const cssEnd = css.indexOf('body.student-page #vidList li', cssStart);
    assert.ok(cssStart >= 0 && cssEnd > cssStart);
    const preferenceCss = css.slice(cssStart, cssEnd);
    assert.match(preferenceCss, /\.student-notification-toggle\s*\{[\s\S]*?min-height:\s*48px/);
    assert.match(preferenceCss, /touch-action:\s*manipulation/);
    assert.match(preferenceCss, /overflow-wrap:\s*anywhere/);
    assert.doesNotMatch(preferenceCss, /#[0-9a-f]{3,8}\b/i);
    assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.student-notification-toggle/);
  });

  check('generic wording is consistent while install permission remains behind the existing explicit action', () => {
    assert.match(push, /학습 알림 켜짐/);
    assert.match(app, /앱 설치와 학습 알림을 확인해 주세요/);
    const bootstrapScope = app.slice(app.indexOf('async function bootstrap'), app.indexOf('function destroy'));
    assert.doesNotMatch(bootstrapScope, /requestPermission|pushGate\.activate/);
    const switchStart = student.indexOf("studentAppCurriculum?.addEventListener('change'");
    const switchEnd = student.indexOf("studentAppLogout?.addEventListener", switchStart);
    const switchScope = student.slice(switchStart, switchEnd);
    assert.match(switchScope, /refreshSession\(\{\s*force:\s*true\s*\}\)[\s\S]*location\.assign\(['"]\/app['"]\)/);
    assert.doesNotMatch(switchScope, /location\.assign\(`\/student\//);
  });

  return Object.freeze({
    suite: 'student-mobile-app-notifications',
    checks: passed.length,
    checksPassed: Object.freeze(passed.slice()),
    files: Object.freeze(Object.fromEntries(Object.entries(files).map(([key, filename]) => [key, path.relative(root, filename)]))),
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const result = await runChecks();
    console.log(`student-mobile-app notifications: ${result.checks} assertions passed`);
  } catch (error) {
    console.error(`student-mobile-app notifications: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
