// 思在 Service Worker — v2
// 网络优先策略，确保始终拿到最新版本

const CACHE_NAME = 'sizai-v2';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // 跳过 API 请求
  if (event.request.url.includes('/api/')) return;
  // 跳过非 GET 请求
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request).then((response) => {
      // 网络成功 → 缓存并返回
      if (response.ok) {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, clone);
        });
      }
      return response;
    }).catch(() => {
      // 网络失败 → 从缓存取
      return caches.match(event.request);
    })
  );
});
