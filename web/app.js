// Save to second-brain, the capture page for Android and desktop browsers.
//
// It does what the Shortcut does on iPhone and Mac: take a shared link, text or
// image, ask what caught your eye and an optional note, and send it to the
// inbox: a file in your GitHub inbox repository, or the Supabase inbox
// (capture for links, capture_image for images). The settings and
// any capture waiting to be sent stay in this browser; the page has no server.
"use strict";

const INTENTS = ["Pattern to reuse", "Visual style", "Tool to try", "Idea to read", "Idea to grow", "Just save"];
const DEFAULT_INTENT = "Just save";
const SETTINGS = "second-brain:settings";
const QUEUE = "second-brain:queue";
const SHARE_CACHE = "second-brain-share";  // where sw.js keeps an Android share
const POPUP = "second-brain-popup";        // window name the bookmarklet opens
const MAX_SIDE = 2560;                     // px; plenty for the analysis, keeps uploads small
const JPEG_QUALITY = 0.85;
const MAX_BASE64 = 12000000;               // capture_image's limit
const INBOX_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];
const ITEM_ERRORS = /invalid url|invalid image|unsupported image type/i;  // retrying won't help

const $ = (id) => document.getElementById(id);

// Storage can throw (private windows, blocked site data): the page still works
// for the capture in hand, it just can't remember anything.
function load(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function save(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

let settings = null;  // set in start(), after normalize() is defined
let image = null;        // the shared or chosen image (a Blob), when there is one
let installPrompt = null;
let flushing = false;
let fromShare = false;   // opened from Android's share sheet: close when done

// --- Settings ----------------------------------------------------------------

function projectUrl(value) {
  let url = value.trim().replace(/\/+$/, "").replace(/\/rest\/v1.*$/, "");
  if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
  return url;
}

// Two kinds of inbox: "github" (a private inbox repository the page writes a
// file into; bin/setup's default) and "supabase" (the database inbox). Settings
// saved before there were two kinds have no kind: they're Supabase.
function normalize(s) {
  if (!s || typeof s !== "object") return null;
  if (s.kind === "github") {
    const repo = String(s.repo || "").trim().replace(/^https:\/\/github\.com\//i, "").replace(/\/+$/, "");
    const token = String(s.token || "").trim();
    return /^[\w.-]+\/[\w.-]+$/.test(repo) && token ? { kind: "github", repo, token } : null;
  }
  const url = projectUrl(String(s.url || ""));
  const key = String(s.key || "").trim();
  const token = String(s.token || "").trim();
  return /^https:\/\/[^/\s]+$/i.test(url) && key && token ? { kind: "supabase", url, key, token } : null;
}

// bin/setup and "Copy setup link" put the settings in the fragment, which
// browsers never send to the server: #setup=<base64url of the settings JSON>.
function setupLink() {
  const json = JSON.stringify(settings);
  const b64 = btoa(json).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${new URL(".", location.href).href}#setup=${b64}`;
}

function readSetupLink() {
  if (!/^#setup=/.test(location.hash)) return null;
  const hash = location.hash;
  history.replaceState(null, "", location.pathname + location.search);  // drop the token from the address bar
  return parseSetupLink(hash);
}

function parseSetupLink(text) {
  const match = String(text).match(/#setup=([A-Za-z0-9_-]+)/);
  if (!match) return null;
  try {
    return normalize(JSON.parse(atob(match[1].replace(/-/g, "+").replace(/_/g, "/"))));
  } catch {
    return null;
  }
}

// --- What was shared ---------------------------------------------------------

// Android shares arrive as a POST the service worker keeps (?share=1); the
// bookmarklet opens the page with ?url=&title=.
async function readShared() {
  const params = new URLSearchParams(location.search);
  if (params.has("share")) {
    fromShare = true;
    history.replaceState(null, "", location.pathname);
    try {
      const cache = await caches.open(SHARE_CACHE);
      const meta = await cache.match("share-meta");
      if (!meta) return null;
      const file = await cache.match("share-file");
      const shared = { ...(await meta.json()), file: file ? await file.blob() : null };
      await Promise.all([cache.delete("share-meta"), cache.delete("share-file")]);
      return shared;
    } catch {
      return null;
    }
  }
  if (["url", "text", "title"].some((k) => params.has(k))) {
    history.replaceState(null, "", location.pathname);
    return { url: params.get("url"), text: params.get("text"), title: params.get("title") };
  }
  return null;
}

// The first link in what was shared: many apps (LinkedIn, Instagram, X) share
// text with the link inside it rather than a URL.
function firstUrl(...texts) {
  for (const text of texts) {
    const match = text && text.match(/https?:\/\/[^\s<>"'`]+/i);
    if (!match) continue;
    let url = match[0].replace(/[.,;:!?'"»]+$/, "");
    if (url.endsWith(")") && !url.includes("(")) url = url.slice(0, -1);
    return url;
  }
  return null;
}

function applyShared(shared) {
  if (!shared) return;
  if (shared.file && shared.file.type.startsWith("image/")) {
    setImage(shared.file);
    return;
  }
  const url = firstUrl(shared.url, shared.text, shared.title);
  if (url) {
    $("url").value = url;
    return;
  }
  const text = [shared.title, shared.text].filter(Boolean).join("\n").trim();
  if (text) {
    $("note").value = text;  // nothing to capture, but don't lose what was shared
    status("There's no link in what you shared: paste one, or choose an image.", "error");
  }
}

// --- Images ------------------------------------------------------------------

function setImage(blob) {
  image = blob;
  const preview = $("preview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.src = blob ? URL.createObjectURL(blob) : "";
  if (!blob) preview.removeAttribute("src");
  $("shared").hidden = !blob;
  $("link-input").hidden = Boolean(blob);
  if (blob) status("");
}

// JPEG, at most MAX_SIDE on the long edge, like the Shortcut's Convert Image step.
async function toJpeg(blob) {
  try {
    const bitmap = await createImageBitmap(blob);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";  // JPEG has no alpha: transparent pixels become white, not black
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const jpeg = await new Promise((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode"))), "image/jpeg", JPEG_QUALITY));
    return { blob: jpeg, mime: "image/jpeg" };
  } catch {
    // The browser can't decode it (HEIC in Chrome, for one): send it as it is if the inbox takes it.
    if (INBOX_TYPES.includes(blob.type)) return { blob, mime: blob.type };
    throw new Error("This browser can't read that image. Share a JPEG or PNG.");
  }
}

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// --- Sending -----------------------------------------------------------------

// ok: queued. retry: the inbox wasn't reachable, try later. Otherwise the
// message says what to fix.
async function send(item) {
  return settings.kind === "github" ? sendGithub(item) : sendSupabase(item);
}

// One file per capture in queue/ of the inbox repository; the push starts its workflow.
async function sendGithub(item) {
  const { repo, token } = settings;
  const name = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}.json`;
  const payload = item.image
    ? { image: item.image, mime: item.mime, note: item.note, at: new Date().toISOString() }
    : { url: item.url, note: item.note, at: new Date().toISOString() };
  let res;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/contents/queue/${name}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
      body: JSON.stringify({ message: "capture", content: utf8Base64(JSON.stringify(payload)) }),
    });
  } catch {
    return { retry: true, message: "GitHub isn't reachable." };
  }
  if (res.ok) return { ok: true };
  if (res.status >= 500 || res.status === 409 || res.status === 429) {
    return { retry: true, message: `GitHub answered ${res.status}.` };
  }
  if (res.status === 401) return { message: "GitHub rejected the capture token (expired?). Make a new one and update Settings." };
  if (res.status === 403 && res.headers.get("x-ratelimit-remaining") === "0") {
    return { retry: true, message: "GitHub's rate limit: it's sent later." };
  }
  if (res.status === 403 || res.status === 404) {
    return { message: `The token can't write to ${repo}. It needs that repository with Contents: Read and write.` };
  }
  let said = "";
  try { said = (await res.json()).message || ""; } catch { /* not JSON */ }
  return { message: said ? `GitHub said: ${said}` : `GitHub answered ${res.status}.` };
}

function utf8Base64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

async function sendSupabase(item) {
  const { url, key, token } = settings;
  const [fn, body] = item.image
    ? ["capture_image", { image: item.image, mime: item.mime, note: item.note, token }]
    : ["capture", { url: item.url, note: item.note, token }];
  let res;
  try {
    res = await fetch(`${url}/rest/v1/rpc/${fn}`, {
      method: "POST",
      headers: { apikey: key, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { retry: true, message: "The inbox isn't reachable." };
  }
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (res.ok && data && data.status === "queued") return { ok: true };
  if (res.status >= 500 || res.status === 429 || res.status === 408) {
    return { retry: true, message: `The inbox answered ${res.status}.` };  // a paused free project, for one
  }
  const said = (data && (data.message || data.error || data.hint)) || "";
  return { message: explain(res.status, said), itemError: ITEM_ERRORS.test(said) };
}

function explain(code, said) {
  if (/unauthorized/i.test(said)) return "The capture token was rejected. Check it in Settings.";
  if (/invalid url/i.test(said)) return "That doesn't look like a link.";
  if (/unsupported image type|invalid image/i.test(said)) return "The inbox doesn't take that image.";
  if (code === 401 || /api ?key|jwt/i.test(said)) return "The publishable key was rejected. Check it in Settings.";
  if (code === 404) return "There's no second-brain inbox at that Supabase URL. Check it in Settings.";
  return said ? `The inbox said: ${said}` : `The inbox answered ${code}.`;
}

// --- Captures waiting on this device -------------------------------------------

function queue() {
  return load(QUEUE, []);
}

function enqueue(item) {
  return save(QUEUE, [...queue(), { ...item, at: Date.now() }]);
}

async function flush() {
  if (!settings || flushing || !queue().length) return renderQueue();
  flushing = true;
  const waiting = queue();
  const left = [];
  let problem = "";
  for (let i = 0; i < waiting.length; i++) {
    const result = await send(waiting[i]);
    if (result.ok) continue;
    if (result.itemError) { problem = `One capture was dropped: ${result.message}`; continue; }
    problem = result.message;
    left.push(...waiting.slice(i));  // unreachable or wrong settings: keep the rest for later
    break;
  }
  save(QUEUE, left);
  flushing = false;
  renderQueue(problem);
}

function renderQueue(problem = "") {
  const n = queue().length;
  $("queue").hidden = !n;
  $("queue-count").textContent = n
    ? `${n} ${n === 1 ? "capture" : "captures"} waiting to send.${problem ? ` ${problem}` : ""}`
    : "";
}

// --- Screens -----------------------------------------------------------------

function status(message, kind = "", target = "status") {
  const el = $(target);
  el.textContent = message;
  el.className = `status${kind ? ` ${kind}` : ""}`;
}

function showCapture() {
  $("settings").hidden = true;
  $("capture").hidden = false;
  $("footer").hidden = false;
  $("title").textContent = "Save";
  $("toggle-settings").textContent = "Settings";
  renderQueue();
}

function showSettings() {
  $("capture").hidden = true;
  $("settings").hidden = false;
  $("footer").hidden = !settings;
  $("title").textContent = settings ? "Settings" : "Connect";
  $("toggle-settings").textContent = "Back";
  $("extras").hidden = !settings;
  const kind = settings ? settings.kind : "github";
  document.querySelector(`input[name="kind"][value="${kind}"]`).checked = true;
  showKind();
  $("s-repo").value = settings && kind === "github" ? settings.repo : "";
  $("s-gh-token").value = settings && kind === "github" ? settings.token : "";
  $("s-url").value = settings && kind === "supabase" ? settings.url : "";
  $("s-key").value = settings && kind === "supabase" ? settings.key : "";
  $("s-token").value = settings && kind === "supabase" ? settings.token : "";
  if (settings) $("bookmarklet").href = bookmarklet();
}

function bookmarklet() {
  const page = JSON.stringify(new URL(".", location.href).href);
  return `javascript:void(window.open(${page}+'?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title),'${POPUP}','width=460,height=760'))`;
}

function renderIntents() {
  $("intents").replaceChildren(...INTENTS.map((name) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "intent";
    input.value = name;
    input.checked = name === DEFAULT_INTENT;
    const span = document.createElement("span");
    span.textContent = name;
    label.append(input, span);
    return label;
  }));
}

function intent() {
  const checked = document.querySelector('input[name="intent"]:checked');
  return checked ? checked.value : DEFAULT_INTENT;
}

function updateGrowHint() {
  $("grow-hint").hidden = !(intent() === "Idea to grow" && !$("note").value.trim());
}

function resetCapture() {
  $("url").value = "";
  $("note").value = "";
  setImage(null);
  const fallback = document.querySelector(`input[name="intent"][value="${DEFAULT_INTENT}"]`);
  if (fallback) fallback.checked = true;
  updateGrowHint();
}

// --- Events ------------------------------------------------------------------

async function onCapture(event) {
  event.preventDefault();
  // Same format as the Shortcut: the worker reads the intent and the note from it.
  const note = `intent: ${intent()} — ${$("note").value.trim()}`;
  let item;
  if (image) {
    status("Preparing the image…");
    try {
      const { blob, mime } = await toJpeg(image);
      item = { image: await toBase64(blob), mime, note };
    } catch (error) {
      return status(error.message, "error");
    }
    if (item.image.length > MAX_BASE64) return status("That image is too large for the inbox.", "error");
  } else {
    const url = firstUrl($("url").value);
    if (!url) {
      $("url").focus();
      return status("Paste a link, or choose an image.", "error");
    }
    item = { url, note };
  }

  $("send").disabled = true;
  status("Sending…");
  const result = await send(item);
  $("send").disabled = false;

  if (result.ok) {
    finish("Sent to second-brain.");
  } else if (result.retry) {
    if (enqueue(item)) finish(`${result.message} Kept on this device: it's sent when the inbox is back.`);
    else status(`${result.message} It couldn't be kept on this device either: try again.`, "error");
  } else {
    status(result.message, "error");
  }
}

function finish(message) {
  status(message, "ok");
  resetCapture();
  renderQueue();
  flush();
  // Opened by the bookmarklet or from the share sheet: close and go back to where you were.
  if (window.name === POPUP || fromShare) setTimeout(() => window.close(), 900);
}

function showKind() {
  const kind = document.querySelector('input[name="kind"]:checked').value;
  $("github-fields").hidden = kind !== "github";
  $("supabase-fields").hidden = kind !== "supabase";
}

function onSettings(event) {
  event.preventDefault();
  const kind = document.querySelector('input[name="kind"]:checked').value;
  const next = normalize(kind === "github"
    ? { kind, repo: $("s-repo").value, token: $("s-gh-token").value }
    : { kind, url: $("s-url").value, key: $("s-key").value, token: $("s-token").value });
  if (!next) {
    return status(kind === "github"
      ? "Fill in both: the repository looks like you/second-brain-wiki-inbox."
      : "Fill in all three: the project URL looks like https://xxxx.supabase.co.", "error", "s-status");
  }
  applySettings(next);
}

function applySettings(next) {
  settings = next;
  if (!save(SETTINGS, settings)) {
    status("This browser won't store settings (private window?): they last until you close the page.", "error", "s-status");
  } else {
    status("", "", "s-status");
  }
  showCapture();
  status("Connected. Share something, or paste a link.", "ok");
  flush();
}

function bind() {
  $("capture").addEventListener("submit", onCapture);
  $("settings").addEventListener("submit", onSettings);
  $("s-link").addEventListener("input", () => {
    const s = parseSetupLink($("s-link").value);
    if (!s) return;
    $("s-link").value = "";
    applySettings(s);
  });
  document.querySelectorAll('input[name="kind"]').forEach((r) => r.addEventListener("change", showKind));
  $("intents").addEventListener("change", updateGrowHint);
  $("note").addEventListener("input", updateGrowHint);
  $("note").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("capture").requestSubmit();
  });
  $("file").addEventListener("change", () => {
    const [file] = $("file").files;
    if (file) setImage(file);
    $("file").value = "";
  });
  $("drop-image").addEventListener("click", () => setImage(null));
  $("toggle-settings").addEventListener("click", () => ($("settings").hidden ? showSettings() : showCapture()));
  $("retry").addEventListener("click", () => flush());
  $("forget").addEventListener("click", () => {
    if (!confirm("Forget the settings on this device? Captures waiting to send are kept.")) return;
    settings = null;
    save(SETTINGS, null);
    showSettings();
  });
  $("copy-link").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(setupLink());
      status("Setup link copied.", "ok", "s-status");
    } catch {
      status("The browser didn't allow copying.", "error", "s-status");
    }
  });
  $("bookmarklet").addEventListener("click", (e) => {
    e.preventDefault();  // it only works from the bookmarks bar
    status("Drag it to your bookmarks bar, then click it there on any page.", "", "s-status");
  });

  // A pasted or dropped image, on a computer.
  document.addEventListener("paste", (e) => {
    const file = [...(e.clipboardData ? e.clipboardData.files : [])].find((f) => f.type.startsWith("image/"));
    if (file && !$("capture").hidden) {
      e.preventDefault();
      setImage(file);
    }
  });
  document.addEventListener("dragover", (e) => {
    if ($("capture").hidden) return;
    e.preventDefault();
    document.body.classList.add("dragging");
  });
  document.addEventListener("dragleave", (e) => {
    if (!e.relatedTarget) document.body.classList.remove("dragging");
  });
  document.addEventListener("drop", (e) => {
    document.body.classList.remove("dragging");
    const file = [...(e.dataTransfer ? e.dataTransfer.files : [])].find((f) => f.type.startsWith("image/"));
    if (!file || $("capture").hidden) return;
    e.preventDefault();
    setImage(file);
  });

  window.addEventListener("online", () => flush());
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installPrompt = e;
    $("install-banner").hidden = false;
  });
  window.addEventListener("appinstalled", () => ($("install-banner").hidden = true));
  $("install").addEventListener("click", async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    $("install-banner").hidden = true;
  });
}

async function start() {
  settings = normalize(load(SETTINGS, null));
  renderIntents();
  bind();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});

  const fromLink = readSetupLink();
  if (fromLink) {
    settings = fromLink;
    save(SETTINGS, settings);
  }
  const shared = await readShared();

  if (!settings) {
    applyShared(shared);  // kept in the form while you connect
    showSettings();
    return;
  }
  showCapture();
  if (fromLink) status("Connected. Share something, or paste a link.", "ok");
  applyShared(shared);
  if (!shared && !image) $("url").focus({ preventScroll: true });
  flush();
}

start();
