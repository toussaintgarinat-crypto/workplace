// Service worker PWA agenda (S178). Anti-intrusif : ne montre une notif QUE sur push.
const CACHE = "agenda-shell-v1";
const SHELL = ["/app"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) =>
    Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("push", (e) => {
  let d = { titre: "Agenda", corps: "", url: "/app", tag: "workplace" };
  try { d = Object.assign(d, e.data.json()); } catch (_) { if (e.data) d.corps = e.data.text(); }
  e.waitUntil(self.registration.showNotification(d.titre, {
    body: d.corps, tag: d.tag, data: { url: d.url }, badge: "/app/icone-192.png", icon: "/app/icone-192.png",
  }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/app";
  e.waitUntil(clients.matchAll({ type: "window" }).then((ws) => {
    for (const w of ws) { if (w.url.includes("/app") && "focus" in w) return w.focus(); }
    return clients.openWindow(url);
  }));
});
