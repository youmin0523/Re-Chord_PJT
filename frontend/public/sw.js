/* Re:Chord service worker.
 *
 * Goal: keep the app shell + last-loaded job artifacts available offline so
 * the PerformanceView still works on stage even when WiFi flakes mid-set.
 *
 * Strategy:
 *   - app shell (HTML / JS / CSS / icons): stale-while-revalidate
 *   - GET /jobs/<id>/download/<key>: cache-first (audio/PDF/SVG are heavy)
 *   - GET /jobs/<id> JSON:           network-first w/ cache fallback
 *   - everything else:               network passthrough
 *
 * No precache list — we let the cache grow naturally as the user touches
 * each artifact. Caches are pruned by name+version on activate.
 */
const VERSION = "v1-2026-05-20";
const SHELL_CACHE = `rechord-shell-${VERSION}`;
const API_CACHE   = `rechord-api-${VERSION}`;
const MEDIA_CACHE = `rechord-media-${VERSION}`;

self.addEventListener("install", (event) => {
  // Activate immediately so the next page load uses the new SW.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((n) => n.startsWith("rechord-") && !n.endsWith(VERSION))
        .map((n) => caches.delete(n)),
    );
    await self.clients.claim();
  })());
});

function isJobDownload(url) {
  return /\/jobs\/[^/]+\/download\//.test(url.pathname);
}
function isJobMeta(url) {
  return /^\/jobs\/[^/?]+(\?|$)/.test(url.pathname);
}
function isAppShell(req) {
  // HTML pages + bundled JS/CSS/font/image assets from the same origin.
  if (req.mode === "navigate") return true;
  if (req.destination === "script" || req.destination === "style" ||
      req.destination === "font" || req.destination === "image") return true;
  return false;
}

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    return hit || Response.error();
  }
}

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    const hit = await cache.match(req);
    return hit || Response.error();
  }
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  const fetchPromise = fetch(req).then((res) => {
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  return hit || (await fetchPromise) || Response.error();
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Only handle same-origin + the backend on 7860 (Phase A dev).
  const sameOrigin = url.origin === self.location.origin;
  const isBackend = /:(7860|8000)$/.test(url.host);
  if (!sameOrigin && !isBackend) return;

  if (isJobDownload(url)) {
    event.respondWith(cacheFirst(req, MEDIA_CACHE));
    return;
  }
  if (isJobMeta(url)) {
    event.respondWith(networkFirst(req, API_CACHE));
    return;
  }
  if (isAppShell(req)) {
    event.respondWith(staleWhileRevalidate(req, SHELL_CACHE));
    return;
  }
  // Default: passthrough, no caching.
});
