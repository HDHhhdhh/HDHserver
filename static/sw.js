/* Versioned static shell only. HTML uses network-first; student/API/data responses are network-only. */
// Replaces student-app-shell-v10 after the browser-specific installation guide shipped.
const SHELL_CACHE = 'student-app-shell-v11';
const SHELL_CACHE_PREFIX = 'student-app-shell-';
const SHELL_URLS = Object.freeze([
  '/app',
  '/css/student-app.css',
  '/js/student-app.js',
  '/js/student-app-api.js',
  '/js/student-app-contract.js',
  '/js/student-app-push.js',
  '/manifest.webmanifest',
  '/offline.html',
  '/icons/student-app-192.png',
  '/icons/student-app-512.png',
  '/icons/student-app-maskable-512.png',
]);

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await cache.addAll(SHELL_URLS);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter((key) => key.startsWith(SHELL_CACHE_PREFIX) && key !== SHELL_CACHE)
      .map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

function isNavigation(request) {
  return request.mode === 'navigate' || (request.method === 'GET' && request.headers.get('accept')?.includes('text/html'));
}

function isShellUrl(url) {
  return SHELL_URLS.includes(url.pathname);
}

function isNetworkOnlyUrl(url) {
  return url.pathname.startsWith('/api/') || url.pathname.startsWith('/files/') || /(?:video|answer|data)/i.test(url.pathname);
}

async function networkFirst(request, cacheKey = '') {
  try {
    const response = await fetch(request);
    if (cacheKey && response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      await cache.put(cacheKey, response.clone());
    }
    return response;
  } catch {
    const cached = cacheKey ? await caches.match(cacheKey) : await caches.match(request);
    return cached ?? (await caches.match('/offline.html')) ?? new Response('오프라인 상태입니다.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Network-only by design: leave API, files, video, answer, and data requests
  // to the browser network without a Cache API interception or offline fallback.
  if (isNetworkOnlyUrl(url)) return;
  if (isNavigation(request)) {
    event.respondWith(networkFirst(request, isShellUrl(url) ? url.pathname : ''));
    return;
  }
  if (isShellUrl(url)) event.respondWith(networkFirst(request, url.pathname));
});

const ANNOUNCEMENT_ID = /[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/;
const NOTIFICATION_EVENT_ID = /evt_[A-Za-z0-9_-]{32}/;
const PUSH_TEST_HOST = 'dev-app.5a-math.com';

const GENERIC_NOTIFICATION_TYPES = Object.freeze({
  class_reminder: Object.freeze({
    title: '수업 알림',
    body: '학생 앱에서 예정된 수업을 확인해 주세요.',
    view: 'home',
    category: 'schedule',
  }),
  schedule_changed: Object.freeze({
    title: '수업 일정 안내',
    body: '학생 앱에서 변경된 수업 일정을 확인해 주세요.',
    view: 'home',
    category: 'schedule',
  }),
  homework_assigned: Object.freeze({
    title: '새 숙제가 등록되었습니다',
    body: '학생 앱에서 숙제와 기한을 확인해 주세요.',
    view: 'homework',
    category: 'homework',
  }),
  homework_due: Object.freeze({
    title: '숙제 기한 알림',
    body: '학생 앱에서 마감 예정 숙제를 확인해 주세요.',
    view: 'homework',
    category: 'homework',
  }),
  progress_milestone: Object.freeze({
    title: '진도 알림',
    body: '학생 앱에서 학습 진도를 확인해 주세요.',
    view: 'home',
    category: 'progress',
  }),
  announcement_published: Object.freeze({
    title: '새 공지가 도착했습니다',
    body: '학생 앱을 열어 공지 내용을 확인해 주세요.',
    view: 'board',
    category: 'announcement',
  }),
  push_test: Object.freeze({
    title: '학생 앱 테스트 알림',
    body: '개발용 Push 수신 테스트가 완료되었습니다.',
    view: 'home',
    category: 'test',
  }),
});

function safeAnnouncementId(value) {
  const id = typeof value === 'string' ? value : '';
  const match = ANNOUNCEMENT_ID.exec(id);
  return match?.index === 0 && match[0] === id ? id : '';
}

function safeNotificationEventId(value, view = '') {
  const id = typeof value === 'string' ? value : '';
  const match = NOTIFICATION_EVENT_ID.exec(id);
  return match?.index === 0 && match[0] === id ? id : '';
}

function announcementTarget(value) {
  const id = safeAnnouncementId(value);
  return id ? `/app?announcement=${encodeURIComponent(id)}` : '/app';
}

function genericNotificationTarget(view, eventId) {
  if (view === 'home') return '/app?view=home';
  if (view === 'homework') return `/app?view=homework&item=${encodeURIComponent(eventId)}`;
  if (view === 'board') return `/app?view=board&item=${encodeURIComponent(eventId)}`;
  return '/app';
}

function normalizedNotification(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  if (value.type === 'announcement') {
    const announcementId = safeAnnouncementId(value.announcementId);
    if (!announcementId) return null;
    return Object.freeze({
      type: 'announcement',
      eventId: announcementId,
      title: '새 공지가 도착했습니다',
      body: '학생 앱을 열어 공지 내용을 확인해 주세요.',
      target: announcementTarget(announcementId),
      tag: `student-announcement:${announcementId}`,
      data: Object.freeze({ type: 'announcement', announcementId }),
    });
  }
  const type = typeof value.type === 'string' ? value.type : '';
  if (type === 'push_test' && new URL(self.location.origin).hostname !== PUSH_TEST_HOST) return null;
  const spec = Object.hasOwn(GENERIC_NOTIFICATION_TYPES, type) ? GENERIC_NOTIFICATION_TYPES[type] : null;
  if (!spec) return null;
  const eventId = safeNotificationEventId(value.eventId, spec.view);
  if (!eventId) return null;
  return Object.freeze({
    type,
    eventId,
    title: spec.title,
    body: spec.body,
    target: genericNotificationTarget(spec.view, eventId),
    tag: `student-${spec.category}:${type}:${eventId}`,
    data: Object.freeze({ type, eventId }),
  });
}

self.addEventListener('push', (event) => {
  let payload = null;
  try { payload = event.data?.json(); }
  catch { payload = null; }
  const notification = normalizedNotification(payload);
  if (!notification) return;
  event.waitUntil(self.registration.showNotification(notification.title, {
    body: notification.body,
    icon: '/icons/student-app-192.png',
    badge: '/icons/student-app-192.png',
    tag: notification.tag,
    renotify: true,
    data: notification.data,
  }));
});

async function focusOrOpen(target) {
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  const existing = windows.find((client) => {
    try {
      const url = new URL(client.url);
      return url.origin === self.location.origin && (url.pathname === '/app' || url.pathname === '/app/' || url.pathname.startsWith('/student/'));
    }
    catch { return false; }
  });
  if (!existing) return self.clients.openWindow(target);
  if (typeof existing.navigate !== 'function') return self.clients.openWindow(target);
  try {
    const navigated = await existing.navigate(target);
    return typeof navigated?.focus === 'function' ? navigated.focus() : self.clients.openWindow(target);
  } catch {
    return self.clients.openWindow(target);
  }
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const data = event.notification?.data;
  // Notifications displayed by the previous worker stored only announcementId.
  const compatibleData = data?.type || !safeAnnouncementId(data?.announcementId)
    ? data
    : { type: 'announcement', announcementId: data.announcementId };
  const notification = normalizedNotification(compatibleData);
  if (!notification) return;
  event.waitUntil(focusOrOpen(notification.target));
});
