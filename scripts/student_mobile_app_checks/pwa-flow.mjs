import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..', '..');
const pushModule = path.join(root, 'static', 'js', 'student-app-push.js');
const contractModule = path.join(root, 'static', 'js', 'student-app-contract.js');
const appModule = path.join(root, 'static', 'js', 'student-app.js');
const swPath = path.join(root, 'static', 'sw.js');
const studentPath = path.join(root, 'static', 'js', 'student.js');
const studentHtmlPath = path.join(root, 'static', 'student.html');
const artifactPath = process.env.STUDENT_APP_PWA_FLOW_EVIDENCE ?? path.join(root, '.omo', 'evidence', 'student-mobile-app-v2', 'task-12', 'pwa-flow-check.json');

function authState() {
  return { status: 'ready', sessionSid: 'sid-1', csrfToken: 'csrf-1', curris: [{ sid: 'sid-1', cur: 'A' }] };
}

function fakePlatform(overrides = {}) {
  const trace = [];
  let permission = overrides.permission ?? 'default';
  let subscription = overrides.subscription ?? null;
  const capabilities = { serviceWorker: true, pushManager: true, notification: true, standalone: true, ...(overrides.capabilities || {}) };
  return {
    trace,
    isIos: overrides.isIos === true,
    isMobile: overrides.isMobile === true,
    capabilities: () => ({ ...capabilities }),
    hasInstallPrompt: () => overrides.installPrompt === true,
    promptInstall: async () => { trace.push('install-prompt'); return overrides.installOutcome ?? 'accepted'; },
    register: async () => { trace.push('sw-register'); return { scope: '/' }; },
    getSubscription: async () => { trace.push('get-subscription'); return subscription; },
    notificationPermission: () => permission,
    requestPermission: async () => {
      trace.push('permission-request');
      permission = overrides.permissionResult ?? 'granted';
      return permission;
    },
    subscribe: async (_registration, publicKey) => {
      trace.push(`push-subscribe:${publicKey}`);
      if (overrides.subscribeError) throw new Error('subscribe rejected');
      subscription = { endpoint: 'https://push.test/sub-1', keys: { p256dh: 'p-key', auth: 'a-key' }, toJSON() { return { endpoint: this.endpoint, keys: this.keys }; } };
      return subscription;
    },
    deviceId: async (seed) => { trace.push(`device:${seed.startsWith('https://') ? 'endpoint' : 'capability'}`); return seed.startsWith('https://') ? 'device-endpoint-1' : 'device-capability-1'; },
    setStandalone: value => { capabilities.standalone = value === true; },
  };
}

function fakeApi(overrides = {}) {
  const trace = [];
  return {
    trace,
    getPushStatus: async (deviceId) => {
      trace.push(`status:${deviceId}`);
      if (overrides.statusError) throw overrides.statusError;
      return overrides.status ?? { ok: true, subscribed: false, bypassExpiresAt: null, pushRequired: true };
    },
    getPushPublicKey: async () => { trace.push('public-key'); return 'public-key-1'; },
    subscribePush: async (body, csrf) => { trace.push(`subscribe:${body.deviceId}:${csrf}`); if (overrides.subscribeApiError) throw new Error('server reject'); return { ok: true, subscribed: true }; },
    bypassPush: async (body, csrf) => { trace.push(`bypass:${body.deviceId}:${csrf}`); return { ok: true, bypassExpiresAt: overrides.bypassExpiry ?? 87400 }; },
  };
}

function loadDeepLinkContract(source) {
  const start = source.indexOf('/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_START */');
  const end = source.indexOf('/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_END */');
  assert.ok(start >= 0 && end > start, 'announcement deep-link contract markers');
  const context = vm.createContext({ URLSearchParams, Object, String });
  new vm.Script(`${source.slice(start, end)}\nglobalThis.deepLink = { studentAppAnnouncementDeepLink, studentAppOpenAnnouncementDeepLink };`).runInContext(context);
  return context.deepLink;
}

async function serviceWorkerTrace(source) {
  const listeners = new Map();
  const notifications = [];
  const opened = [];
  let closeCount = 0;
  let clientLookups = 0;
  const context = { console, URL, Response, Request, Promise, caches: { open: async () => ({ addAll: async () => {}, put: async () => {} }), keys: async () => [], delete: async () => true, match: async () => undefined }, fetch: async () => new Response('ok'), self: { location: { origin: 'https://app.test' }, addEventListener: (name, fn) => listeners.set(name, fn), skipWaiting: async () => {}, registration: { showNotification: async (title, options) => notifications.push({ title, options }) }, clients: { claim: async () => {}, matchAll: async () => { clientLookups += 1; return []; }, openWindow: async (url) => opened.push(url) } } };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'static/sw.js' });
  let pending;
  listeners.get('push')({ data: { json: () => ({ type: 'announcement', announcementId: 'ann:1', url: 'https://evil.test/takeover' }) }, waitUntil: value => { pending = value; } });
  await pending;
  listeners.get('notificationclick')({ notification: { data: { announcementId: 'ann:1', url: 'https://evil.test/takeover' }, close: () => { closeCount += 1; } }, waitUntil: value => { pending = value; } });
  await pending;
  const validClientLookups = clientLookups;
  pending = null;
  listeners.get('notificationclick')({ notification: { data: { announcementId: '../evil', url: 'https://evil.test/takeover' }, close: () => { closeCount += 1; } }, waitUntil: value => { pending = value; } });
  assert.equal(pending, null);
  listeners.get('notificationclick')({ notification: { data: { url: 'https://evil.test/takeover' }, close: () => { closeCount += 1; } }, waitUntil: value => { pending = value; } });
  assert.equal(pending, null);
  return { notifications, opened, closeCount, invalidClientLookups: clientLookups - validClientLookups };
}

export async function runChecks() {
  const [{ createPushGate, detectInstallEnvironment }, { safeAnnouncementId, studentPageUrl, isBackwardTransition }, { installGuideContent }, sw, student, studentHtml, appSource] = await Promise.all([
    import(pathToFileURL(pushModule).href),
    import(pathToFileURL(contractModule).href),
    import(pathToFileURL(appModule).href),
    fs.readFile(swPath, 'utf8'),
    fs.readFile(studentPath, 'utf8'),
    fs.readFile(studentHtmlPath, 'utf8'),
    fs.readFile(appModule, 'utf8'),
  ]);
  const checks = [];
  const receipts = {};
  const check = async (name, fn) => { await fn(); checks.push(name); };

  await check('browser and OS detection selects an exact installation guide', async () => {
    const detected = (userAgent, { standalone = false, maxTouchPoints = 0 } = {}) => detectInstallEnvironment({
      navigator: { userAgent, maxTouchPoints },
      matchMedia: () => ({ matches: standalone }),
    });
    const ios = detected('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1');
    assert.deepEqual({ platform: ios.platform, browser: ios.browser, standalone: ios.standalone }, { platform: 'ios', browser: 'safari', standalone: false });
    assert.match(installGuideContent(ios).steps.join(' '), /홈 화면에 추가|웹 앱으로 열기/);
    const android = detected('Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36');
    assert.deepEqual({ platform: android.platform, browser: android.browser }, { platform: 'android', browser: 'chrome' });
    assert.match(installGuideContent(android).steps.join(' '), /홈 화면에 추가.*설치/s);
    const inApp = detected('Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 Chrome/125.0 Mobile KAKAOTALK');
    assert.equal(inApp.browser, 'in_app');
    assert.match(installGuideContent(inApp).steps.join(' '), /외부 브라우저|Chrome/);
    const edge = detected('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 Edg/126.0');
    assert.deepEqual({ platform: edge.platform, browser: edge.browser }, { platform: 'windows', browser: 'edge' });
    assert.match(installGuideContent(edge).steps.join(' '), /이 사이트를 앱으로 설치/);
    const installed = detected('Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36', { standalone: true });
    assert.equal(installed.standalone, true);
    assert.match(appSource, /if \(environment\.standalone\)[\s\S]*opener\.hidden = true/);
    assert.match(appSource, /initInstallGuide\(\);/);
  });

  await check('auth and install states move forward and permission stays behind the click action', async () => {
    const sequence = ['signed_out', 'activation_code_required', 'credentials_required', 'push_required', 'ready'];
    for (let index = 1; index < sequence.length; index += 1) {
      assert.equal(isBackwardTransition({ status: sequence[index - 1] }, { status: sequence[index] }), false);
      if (index > 1) assert.equal(isBackwardTransition({ status: sequence[index] }, { status: sequence[index - 1] }), true);
    }
    assert.match(appSource, /action\.addEventListener\('click',\s*\(\)\s*=>\s*handleAction\(action\)\)/);
    const bootstrap = appSource.slice(appSource.indexOf('async function bootstrap'), appSource.indexOf('function destroy'));
    assert.doesNotMatch(bootstrap, /pushGate\.activate|requestPermission/);
  });

  await check('Android install and reopened-app permission gestures precede ready', async () => {
    const platform = fakePlatform({ capabilities: { standalone: false }, installPrompt: true, isMobile: true });
    const api = fakeApi();
    const gate = createPushGate({ api, platform, now: () => 1000 });
    const pending = await gate.assess(authState());
    assert.equal(pending.status, 'push_required');
    assert.equal(platform.trace.includes('permission-request'), false, 'permission must not be automatic');
    const installed = await gate.activate(pending);
    assert.equal(installed.status, 'push_required');
    assert.equal(installed.pushMode, 'install_complete');
    assert.deepEqual(platform.trace.filter(item => item === 'install-prompt' || item === 'permission-request'), ['install-prompt']);
    platform.setStandalone(true);
    const ready = await gate.activate(installed);
    assert.equal(ready.status, 'ready');
    assert.deepEqual(platform.trace.filter(item => item === 'install-prompt' || item === 'permission-request'), ['install-prompt', 'permission-request']);
    assert.deepEqual(api.trace.slice(-2), ['public-key', 'subscribe:device-endpoint-1:csrf-1']);
    receipts.android = { platform: [...platform.trace], api: [...api.trace] };
  });

  await check('desktop browsers can open the student page without PWA installation', async () => {
    const platform = fakePlatform({ capabilities: { standalone: false }, installPrompt: true, isMobile: false });
    const api = fakeApi();
    const ready = await createPushGate({ api, platform, now: () => 1000 }).assess(authState());
    assert.equal(ready.status, 'ready');
    assert.equal(ready.notificationState, 'browser');
    assert.match(ready.notificationLabel, /브라우저|설치 없이/);
    assert.deepEqual(platform.trace, []);
    assert.deepEqual(api.trace, []);
    receipts.desktop = { platform: [...platform.trace], api: [...api.trace] };
  });

  await check('installed iOS requests permission only from activation', async () => {
    const platform = fakePlatform({ isIos: true });
    const gate = createPushGate({ api: fakeApi(), platform, now: () => 1000 });
    const pending = await gate.assess(authState());
    assert.equal(platform.trace.includes('permission-request'), false);
    assert.equal((await gate.activate(pending)).status, 'ready');
    assert.equal(platform.trace.filter(item => item === 'permission-request').length, 1);
    receipts.iosInstalled = { platform: [...platform.trace] };
  });

  await check('unsupported capability receives only a 24-hour server bypass', async () => {
    const platform = fakePlatform({ capabilities: { pushManager: false, standalone: false } });
    const api = fakeApi({ bypassExpiry: 87400 });
    const gate = createPushGate({ api, platform, now: () => 1000 });
    const pending = await gate.assess(authState());
    assert.equal(pending.status, 'unsupported_bypass');
    const ready = await gate.activate(pending);
    assert.equal(ready.status, 'ready');
    assert.equal(ready.bypassExpiresAt, 87400);
    assert.match(ready.notificationLabel, /24시간|우회|미지원/);
    assert.equal(api.trace.some(item => item.startsWith('bypass:')), true);
    assert.equal(platform.trace.includes('permission-request'), false);
    const reusePlatform = fakePlatform({ capabilities: { pushManager: false, standalone: false } });
    const reuseApi = fakeApi({ status: { ok: true, subscribed: false, bypassExpiresAt: 87400, pushRequired: false } });
    const reused = await createPushGate({ api: reuseApi, platform: reusePlatform, now: () => 1000 }).assess(authState());
    assert.equal(reused.status, 'ready');
    assert.equal(reuseApi.trace.some(item => item.startsWith('bypass:')), false);
    receipts.unsupported = { platform: [...platform.trace], api: [...api.trace], bypassExpiresAt: ready.bypassExpiresAt };
  });

  await check('iOS tab, denied/default, and subscribe failures never bypass', async () => {
    const iosPlatform = fakePlatform({ isIos: true, capabilities: { standalone: false, pushManager: false, notification: false } });
    const iosApi = fakeApi();
    const iosGate = createPushGate({ api: iosApi, platform: iosPlatform, now: () => 1000 });
    const iosPending = await iosGate.assess(authState());
    assert.equal((await iosGate.activate(iosPending)).pushMode, 'ios_install');
    assert.equal(iosPlatform.trace.includes('permission-request'), false);
    assert.equal(iosApi.trace.some(item => item.startsWith('bypass:')), false);
    const deniedPlatform = fakePlatform({ permission: 'denied' });
    const deniedApi = fakeApi();
    const deniedGate = createPushGate({ api: deniedApi, platform: deniedPlatform, now: () => 1000 });
    const denied = await deniedGate.activate(await deniedGate.assess(authState()));
    assert.equal(denied.pushMode, 'permission_denied');
    assert.equal(deniedPlatform.trace.includes('permission-request'), false);
    assert.equal(deniedApi.trace.some(item => item.startsWith('bypass:')), false);
    const defaultPlatform = fakePlatform({ permissionResult: 'default' });
    const defaultApi = fakeApi();
    const defaultGate = createPushGate({ api: defaultApi, platform: defaultPlatform, now: () => 1000 });
    const unresolved = await defaultGate.activate(await defaultGate.assess(authState()));
    assert.equal(unresolved.pushMode, 'permission_default');
    assert.equal(defaultPlatform.trace.filter(item => item === 'permission-request').length, 1);
    assert.equal(defaultApi.trace.some(item => item.startsWith('bypass:')), false);
    const platform = fakePlatform({ subscribeError: true });
    const api = fakeApi();
    const failed = await createPushGate({ api, platform, now: () => 1000 }).activate(await createPushGate({ api, platform, now: () => 1000 }).assess(authState()));
    assert.equal(failed.pushMode, 'retry');
    assert.equal(api.trace.some(item => item.startsWith('bypass:')), false);
    receipts.failures = { iosTab: [...iosPlatform.trace], denied: [...deniedPlatform.trace], default: [...defaultPlatform.trace], subscribeReject: [...platform.trace] };
  });

  await check('existing subscription is reused and server status controls expiry/revocation', async () => {
    const existing = { endpoint: 'https://push.test/existing', keys: { p256dh: 'p', auth: 'a' }, toJSON() { return { endpoint: this.endpoint, keys: this.keys }; } };
    const platform = fakePlatform({ subscription: existing, permission: 'granted' });
    const ready = await createPushGate({ api: fakeApi({ status: { ok: true, subscribed: true, bypassExpiresAt: null, pushRequired: false } }), platform, now: () => 1000 }).assess(authState());
    assert.equal(ready.status, 'ready');
    assert.equal(platform.trace.some(item => item.startsWith('push-subscribe:')), false);
    const expiredPlatform = fakePlatform({ capabilities: { pushManager: false } });
    const expired = await createPushGate({ api: fakeApi({ status: { ok: true, subscribed: false, bypassExpiresAt: 999, pushRequired: true } }), platform: expiredPlatform, now: () => 1000 }).assess(authState());
    assert.equal(expired.status, 'unsupported_bypass');
    const revokedError = Object.assign(new Error('revoked'), { status: 401, code: 'unauthenticated' });
    const revoked = await createPushGate({ api: fakeApi({ statusError: revokedError }), platform: fakePlatform(), now: () => 1000 }).assess(authState());
    assert.equal(revoked.status, 'signed_out');
  });

  await check('service worker ignores payload URLs and opens only canonical app links', async () => {
    const trace = await serviceWorkerTrace(sw);
    assert.equal(trace.notifications.length, 1);
    assert.equal(trace.notifications[0].options.body?.includes('ann:1') ?? false, false);
    assert.deepEqual(trace.opened, ['/app?announcement=ann%3A1']);
    assert.equal(trace.closeCount, 3);
    assert.equal(trace.invalidClientLookups, 0);
    receipts.serviceWorker = trace;
  });

  await check('announcement deep-link opens only an exact visible announcement', async () => {
    const deepLink = loadDeepLinkContract(student);
    assert.equal(deepLink.studentAppAnnouncementDeepLink('?announcement=ann:1'), 'ann:1');
    assert.equal(deepLink.studentAppAnnouncementDeepLink('?announcement=../evil'), '');
    assert.equal(deepLink.studentAppAnnouncementDeepLink('?announcement=ann%0A'), '');
    const opened = [];
    assert.equal(deepLink.studentAppOpenAnnouncementDeepLink('ann:1', [{ id: 'ann:2' }], item => opened.push(item)), false);
    assert.equal(deepLink.studentAppOpenAnnouncementDeepLink('ann:1', [{ id: 'ann:1' }], item => opened.push(item.id)), true);
    assert.deepEqual(opened, ['ann:1']);
  });

  await check('safe app navigation and public settings keep secrets out of browser storage', async () => {
    assert.equal(safeAnnouncementId('ann_1:edit'), 'ann_1:edit');
    assert.equal(safeAnnouncementId('../evil'), '');
    assert.equal(safeAnnouncementId(' ann_1:edit'), '');
    assert.equal(safeAnnouncementId('ann_1:edit\n'), '');
    assert.equal(studentPageUrl('sid-1', '?announcement=ann:1&next=https://evil.test'), '/student/sid-1?announcement=ann%3A1');
    assert.match(studentHtml, /id=["']studentAppSettings["'][^>]*hidden/);
    assert.match(student, /\/api\/mobile\/auth\/(?:switch|logout)/);
    for (const source of [await fs.readFile(pushModule, 'utf8'), await fs.readFile(contractModule, 'utf8')]) assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB/i);
  });

  const artifact = { suite: 'student-mobile-app-pwa-flow', generatedAt: new Date().toISOString(), checks: checks.length, checksPassed: checks, receipts };
  await fs.mkdir(path.dirname(artifactPath), { recursive: true });
  await fs.writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
  return artifact;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  runChecks().then(result => console.log(`student-mobile-app pwa-flow: ${result.checks} assertions passed`), error => { console.error(error); process.exitCode = 1; });
}
