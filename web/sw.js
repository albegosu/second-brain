// Service worker for the capture page: it receives Android shares (the
// manifest's share_target POSTs to ./share) and keeps the page usable offline.
// Requests to the Supabase inbox never pass through here: they're cross-origin.
const SHELL = "second-brain-shell-v1";
const SHARE = "second-brain-share";  // read and emptied by app.js
const FILES = ["./", "style.css", "app.js", "manifest.webmanifest", "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("second-brain-shell-") && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method === "POST" && url.pathname.endsWith("/share")) {
    event.respondWith(keepShare(request));
    return;
  }
  if (request.method !== "GET") return;
  // Network first, so an update shows up right away; the cached copy offline.
  // Every page load is cached as "./": the query can hold the link being saved.
  const key = request.mode === "navigate" ? "./" : request;
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put(key, copy));
        }
        return response;
      })
      .catch(() => caches.match(key, { ignoreSearch: true })),
  );
});

// Keep what was shared, then open the page, which picks it up and asks for the note.
async function keepShare(request) {
  const form = await request.formData();
  const file = form.getAll("image").find((f) => typeof f !== "string" && f.size > 0);
  const cache = await caches.open(SHARE);
  const meta = { title: form.get("title") || "", text: form.get("text") || "", url: form.get("url") || "" };
  await cache.put("share-meta", new Response(JSON.stringify(meta), { headers: { "Content-Type": "application/json" } }));
  if (file) await cache.put("share-file", new Response(file, { headers: { "Content-Type": file.type || "application/octet-stream" } }));
  else await cache.delete("share-file");
  return Response.redirect("./?share=1", 303);
}
