// AGOS service worker: makes the installed app behave like one.
//
// - Build assets (/_next/static, hashed, immutable) are served from cache.
// - Pages go to the network; when the phone is offline (or the server is
//   unreachable) the installed app shows /offline.html instead of Chrome's
//   dinosaur. Pages are never cached: they are personal and session-bound.
// - API calls, server actions, streams and media are never touched.
// - A push from AGOS (an approval wait, one of its cards, a finished answer)
//   becomes a notification; tapping it opens that chat. Quiet when the chat it
//   is about is already on screen.
//
// Bump VERSION when the precached files change; old caches are deleted on
// activation.

const VERSION = "agos-sw-v2";
const SHELL = `${VERSION}-shell`;
const STATIC = `${VERSION}-static`;
const OFFLINE_URL = "/offline.html";
const PRECACHE = [
  OFFLINE_URL,
  "/icon.svg",
  "/icons/agos-192.png",
  "/icons/agos-512.png",
  "/icons/agos-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("agos-sw-") && !k.startsWith(VERSION))
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Hashed build assets: cache first, fill the cache from the network.
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // Page loads: network, and the offline page when the network is gone.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(OFFLINE_URL).then(
          (hit) =>
            hit ??
            new Response("AGOS is offline.", {
              status: 503,
              headers: { "Content-Type": "text/plain" },
            }),
        ),
      ),
    );
    return;
  }

  // Precached shell files (icons) when offline.
  if (PRECACHE.includes(url.pathname)) {
    event.respondWith(
      caches.match(request).then((hit) => hit ?? fetch(request)),
    );
  }
  // Everything else (API, actions, streams, media): the browser as usual.
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "AGOS";
  const url = data.url || "/";
  const where = data.where || "";
  event.waitUntil(
    (async () => {
      if (where) {
        const open = await self.clients.matchAll({
          type: "window",
          includeUncontrolled: true,
        });
        const looking = open.some(
          (c) =>
            c.visibilityState === "visible" &&
            c.focused &&
            sameChat(c.url, where),
        );
        if (looking) return;
      }
      await self.registration.showNotification(title, {
        body: data.body || "",
        icon: "/icons/agos-192.png",
        badge: "/icons/agos-192.png",
        tag: data.tag || undefined,
        renotify: Boolean(data.tag),
        data: { url },
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(
    (event.notification.data && event.notification.data.url) || "/",
    self.location.origin,
  ).href;
  event.waitUntil(
    (async () => {
      const open = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      const same = open.find((c) => sameChat(c.url, url)) || open[0];
      if (same) {
        if ("navigate" in same && !sameChat(same.url, url))
          await same.navigate(url);
        return same.focus();
      }
      return self.clients.openWindow(url);
    })(),
  );
});

/** Same page and same ?chat= (other query parts don't count). */
function sameChat(a, b) {
  try {
    const ua = new URL(a, self.location.origin);
    const ub = new URL(b, self.location.origin);
    return (
      ua.pathname === ub.pathname &&
      ua.searchParams.get("chat") === ub.searchParams.get("chat")
    );
  } catch {
    return false;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok && response.type === "basic") {
    cache.put(request, response.clone()).catch(() => {});
  }
  return response;
}
