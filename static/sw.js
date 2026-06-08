/**
 * Service Worker — Health Dashboard
 * Cachea: assets estáticos, tiles de OpenStreetMap
 */

const CACHE_STATIC  = 'health-static-v6';
const CACHE_TILES   = 'health-tiles-v6';
const CACHE_API     = 'health-api-v6';

const STATIC_ASSETS = [
  '/static/css/base.css',
  '/static/css/dashboard.css',
  '/static/js/utils.js',
  '/static/js/health_metrics.js',
  '/static/favicon.svg',
];

// ── Instalación: precachear assets estáticos ──────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_STATIC)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// ── Activación: limpiar caches antiguas ───────────────────────────────────────
self.addEventListener('activate', event => {
  const valid = [CACHE_STATIC, CACHE_TILES, CACHE_API];
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => !valid.includes(k)).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch: estrategia por tipo de recurso ─────────────────────────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Tiles de OpenStreetMap → Cache First (rara vez cambian)
  if (url.hostname.includes('tile.openstreetmap.org')) {
    event.respondWith(cacheFirst(event.request, CACHE_TILES, 7 * 24 * 60 * 60));
    return;
  }

  // Assets estáticos propios → Cache First con fallback a red
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(event.request, CACHE_STATIC));
    return;
  }

  // APIs → Network First (datos frescos) con fallback a cache
  if (url.pathname.startsWith('/api/day') || url.pathname.startsWith('/api/calendar')) {
    event.respondWith(networkFirst(event.request, CACHE_API, 60));
    return;
  }

  // Todo lo demás → red directamente
  // Para HTML: siempre red, nunca caché
  if (event.request.headers.get('Accept')?.includes('text/html')) {
    event.respondWith(fetch(event.request).catch(() => new Response('', {status:503})));
    return;
  }
  event.respondWith(fetch(event.request).catch(() => new Response('', {status:503})));
});

// ── Caché de fuentes externas ────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const url = event.request.url;
  if (url.includes('fonts.googleapis.com') || url.includes('fonts.gstatic.com') || url.includes('cdnjs.cloudflare.com')) {
    event.respondWith(
      caches.open('health-fonts-v1').then(cache =>
        cache.match(event.request).then(cached => {
          if (cached) return cached;
          return fetch(event.request).then(response => {
            if (response.ok) cache.put(event.request, response.clone());
            return response;
          }).catch(() => cached || new Response('', {status:503}));
        })
      )
    );
  }
});

// ── Estrategia Cache First ─────────────────────────────────────────────────────
async function cacheFirst(request, cacheName, maxAgeSeconds = null) {
  const cache    = await caches.open(cacheName);
  const cached   = await cache.match(request);

  if (cached) {
    // Verificar si ha expirado (para tiles)
    if (maxAgeSeconds) {
      const dateHeader = cached.headers.get('sw-cached-at');
      if (dateHeader) {
        const age = (Date.now() - parseInt(dateHeader)) / 1000;
        if (age > maxAgeSeconds) {
          // Revalidar en background
          fetchAndCache(request, cache);
          return cached; // Devolver el cache mientras tanto
        }
      }
    }
    return cached;
  }

  return fetchAndCache(request, cache);
}

// ── Estrategia Network First ──────────────────────────────────────────────────
async function networkFirst(request, cacheName, maxAgeSeconds = 300) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cache  = await caches.open(cacheName);
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

// ── Guardar en cache con timestamp ────────────────────────────────────────────
async function fetchAndCache(request, cache) {
  const response = await fetch(request);
  if (response.ok) {
    const headers  = new Headers(response.headers);
    headers.append('sw-cached-at', Date.now().toString());
    const modified = new Response(await response.blob(), {
      status: response.status, statusText: response.statusText, headers
    });
    cache.put(request, modified);
  }
  return response;
}
