/* Versioned static shell only. HTML uses network-first; student/API/data responses are network-only. */
const SHELL_CACHE = 'student-app-shell-v1';
const SHELL_CACHE_PREFIX = 'student-app-shell-';
const SHELL_URLS = Object.freeze([
  '/app',
  '/css/student-app.css',
  '/js/student-app.js',
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

async function networkFirst(request, cacheResponse) {
  try {
    const response = await fetch(request);
    if (cacheResponse && response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    return (await caches.match(request)) ?? (await caches.match('/offline.html')) ?? new Response('오프라인 상태입니다.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
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
    event.respondWith(networkFirst(request, isShellUrl(url)));
    return;
  }
  if (isShellUrl(url)) event.respondWith(networkFirst(request, true));
});
