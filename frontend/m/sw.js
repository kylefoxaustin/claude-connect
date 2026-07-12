/* Service worker for the ops console.
 *
 * It exists for ONE reason: to receive a push when the app is closed. It is deliberately
 * NOT a cache.
 *
 * The desktop shell learned this the hard way — a cache-first service worker served a
 * stale HTML shell against a changed backend, producing a zombie UI that rendered fine and
 * where every button was dead. An offline shell is worthless for a live dashboard: there
 * is nothing to look at without the server. So this one never touches `fetch` at all. If
 * the network is down, the page fails honestly.
 */

self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch { /* keep the defaults */ }

  const title = d.title || "Conductor";
  const options = {
    body: d.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    // `tag` collapses repeats: a second nudge about the SAME pending question replaces
    // the first rather than stacking. Without it, an hour of reminders becomes a wall of
    // identical notifications and he stops reading any of them.
    tag: d.tag || "conductor",
    renotify: true,
    // Requires a deliberate dismissal. These are the only two things we notify about, and
    // both mean work is stopped dead — a notification that auto-fades is one that gets
    // missed on a phone in a pocket.
    requireInteraction: true,
    data: { url: d.url || "/m" },
    actions: [{ action: "open", title: "Open" }],
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/m";
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    // Focus an already-open console and steer it to the right pane, rather than opening a
    // second copy — and land on the SCREEN the notification is about. GitHub Mobile's
    // approval flow is unusable precisely because the notification is the only door and it
    // doesn't lead anywhere you can navigate back to.
    for (const c of all) {
      if (c.url.includes("/m")) {
        await c.focus();
        c.postMessage({ kind: "navigate", url });
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
