// Conductor service worker — makes the dashboard installable to a phone home
// screen and gives it an instant offline shell. Deliberately minimal:
//   • The app SHELL (HTML/JS/CSS/icons) is cache-first, so a cold launch paints
//     immediately and survives a flaky link.
//   • LIVE DATA (/api/*, /ws) is never cached — always the network — so the
//     fleet view is never stale and auth is never bypassed.
// Bump CACHE when the shell asset list changes to evict the old bundle.
const CACHE = "conductor-shell-v1";
const SHELL = [
  "/",
  "/static/app.js",
  "/static/tiles.js",
  "/static/lines.js",
  "/static/style.css",
  "/static/logo.svg",
  "/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
];

self.addEventListener("install", (e) => {
  // addAll is atomic; if any shell asset 404s the whole install fails (good —
  // we never want a half-cached shell). skipWaiting so an update takes effect
  // on next load without needing every tab closed.
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Only ever touch same-origin GETs. Cross-origin (Three.js from unpkg, etc.)
  // and non-GET requests pass straight through to the browser untouched.
  if (url.origin !== location.origin || e.request.method !== "GET") return;
  // Never intercept the API or the websocket — live data must hit the network,
  // and caching an authed response would be wrong.
  if (url.pathname.startsWith("/api/") || url.pathname === "/ws") return;

  // Shell: cache-first, then network (and refresh the cache in the background so
  // a deploy propagates). Falls back to whatever's cached if the network fails.
  e.respondWith(
    caches.match(e.request).then((hit) => {
      const net = fetch(e.request)
        .then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
          }
          return resp;
        })
        .catch(() => hit);
      return hit || net;
    })
  );
});
