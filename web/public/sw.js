// App-shell cache, so the logger opens with no network at all.
//
// The queue in IndexedDB already survives offline, but that only helps if the page is
// running. A gym basement means the app is often *opened* offline, and without this a
// cold navigation fails at the transport before any of our code runs.
//
// Deliberately not Workbox: this caches a handful of routes and gets out of the way.
const CACHE = "loadout-shell-v3";
const SHELL = ["/", "/today", "/week", "/progress", "/onboarding", "/settings"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Never cache the API. A stale plan is worse than no plan, and events are queued
  // locally anyway rather than relying on an HTTP cache.
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      try {
        const fresh = await fetch(request);
        // Network wins when there is one, so a deploy is picked up on the next load.
        if (fresh.ok) cache.put(request, fresh.clone());
        return fresh;
      } catch {
        // ignoreSearch, because build assets carry a cache-busting query string that
        // differs between the load that cached them and the load that needs them.
        const hit =
          (await cache.match(request)) ??
          (await cache.match(request, { ignoreSearch: true }));
        if (hit) return hit;
        // A logger route is dynamic (/log/<id>) and will not be in the shell by name,
        // so fall back to the Today shell, which is the page it was opened from.
        if (request.mode === "navigate") {
          const shell = await cache.match("/today");
          if (shell) return shell;
        }
        throw new Error("offline and not cached");
      }
    })(),
  );
});
