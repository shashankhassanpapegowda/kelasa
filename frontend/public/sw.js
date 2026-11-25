self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Face models are large and never change, so serve them cache-first.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !url.pathname.startsWith("/models/")) return;
  event.respondWith(caches.open("kelasa-face-models-v1").then(async (cache) => {
    const hit = await cache.match(event.request);
    if (hit) return hit;
    const res = await fetch(event.request);
    if (res.ok) cache.put(event.request, res.clone());
    return res;
  }));
});

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { /* plain text */ }
  const title = data.title || "Kelasa alert";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/kelasa-icon-192.png",
    badge: "/kelasa-icon-192.png",
    tag: data.tag || "kelasa",
    renotify: true,
    requireInteraction: !data.silent,
    silent: !!data.silent,
    ...(data.silent ? {} : { vibrate: [200, 100, 200] }),
    data: { url: data.url || "/admin#alerts" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/admin", self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if (w.url.startsWith(self.location.origin) && "focus" in w) {
        await w.focus();
        if ("navigate" in w) await w.navigate(target);
        return;
      }
    }
    if (self.clients.openWindow) await self.clients.openWindow(target);
  })());
});
