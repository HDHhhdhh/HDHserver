/* sw.js — minimal PWA runtime cache (safe + lightweight) */

const CACHE = 'apex-pwa-v2';
const CORE_URLS = [
  '/manifest.webmanifest',
  // 아이콘은 없어도 설치/동작은 되지만, 있으면 앱 아이콘 품질이 좋아짐
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-512-maskable.png',
];

self.addEventListener('install', (event) => {
  self.skipWaiting();

  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);

    // addAll은 404 하나라도 있으면 install 실패할 수 있어서, 안전하게 개별 캐시
    const results = await Promise.allSettled(
      CORE_URLS.map(async (url) => {
        try {
          const res = await fetch(url, { cache: 'no-store' });
          if (res && res.ok) await cache.put(url, res.clone());
        } catch (_) {}
      })
    );

    // results는 사용 안 함(실패해도 설치는 계속)
    void results;
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k === CACHE ? null : caches.delete(k))));
    await self.clients.claim();
  })());
});

function isNavigation(req) {
  return req.mode === 'navigate' ||
    (req.method === 'GET' && req.headers.get('accept')?.includes('text/html'));
}

function looksStatic(url) {
  return (
    url.pathname.startsWith('/js/') ||
    url.pathname.startsWith('/css/') ||
    url.pathname.startsWith('/static/') ||
    /\.(js|css|png|jpg|jpeg|webp|svg|ico|woff2?|ttf|otf)$/i.test(url.pathname)
  );
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 1) 페이지 이동(HTML): 네트워크 우선, 실패 시 캐시
  if (isNavigation(req)) {
    event.respondWith((async () => {
      try {
        const res = await fetch(req);
        // 최신 HTML을 캐시에 저장 (설치 앱 실행 안정화)
        const cache = await caches.open(CACHE);
        cache.put(req, res.clone()).catch(() => {});
        return res;
      } catch (_) {
        const cached = await caches.match(req);
        if (cached) return cached;
        // 마지막 보험: 루트라도 있으면 반환
        const fallback = await caches.match('/');
        if (fallback) return fallback;
        return new Response('오프라인 상태입니다.', {
          status: 503,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
      }
    })());
    return;
  }

  // 2) 정적 자원: 네트워크 우선, 실패 시 캐시
  // 오래된 JS가 남아 데이터 저장 API를 잘못 호출하는 일을 막기 위해 온라인에서는 항상 최신 파일을 받는다.
  if (looksStatic(url)) {
    event.respondWith((async () => {
      try {
        const res = await fetch(req, { cache: 'no-store' });
        if (res && res.ok) {
          const cache = await caches.open(CACHE);
          cache.put(req, res.clone()).catch(() => {});
        }
        return res;
      } catch (_) {
        const cached = await caches.match(req);
        if (cached) return cached;
        return new Response('', { status: 504 });
      }
    })());
  }
});
