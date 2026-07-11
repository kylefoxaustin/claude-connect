// Conductor service worker — present only so the dashboard is installable to a
// phone home screen. It is deliberately **network-first**.
//
// Why not cache-first (the usual PWA default)? Conductor's entire value IS live
// backend data. An offline shell is worthless here — worse than worthless: a
// cached shell can boot against a changed backend, or serve newer JS against
// older HTML, producing a zombie UI that renders fine but where every button is
// dead. That's a far nastier failure than an honest "can't reach the server".
//
// So: always try the network; fall back to cache ONLY when genuinely offline
// (so a flaky tunnel doesn't blank the screen mid-use). Bump CACHE to evict.
const CACHE = "conductor-shell-v3";

self.addEventListener("install", () => {
  // Nothing to pre-cache — we never want to serve a shell we haven't just fetched.
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  // Drop EVERY previous cache (including the old cache-first v1/v2 bundles, which
  // are what could strand a client on stale code), then take over open pages.
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Only same-origin GETs. Cross-origin (Three.js from unpkg) and non-GETs pass
  // straight through untouched.
  if (url.origin !== location.origin || e.request.method !== "GET") return;
  // Never intercept live data — the API and websocket must always hit the network,
  // and caching an authed response would be wrong.
  if (url.pathname.startsWith("/api/") || url.pathname === "/ws") return;

  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        }
        return resp;
      })
      // Offline only: hand back the last good copy rather than a blank page.
      .catch(() => caches.match(e.request))
  );
});
