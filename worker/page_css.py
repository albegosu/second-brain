"""What a live page's interface is made of, read from its computed CSS.

Pixels give estimates: a palette with the photos' colors in it, a radius the
model guesses. A web page can say exactly. This opens the page in headless
Chrome, the same browser the screenshots use, and reads the computed styles of
what is visible in the first three screens: page, surface, text, button and link
colors; the type of body text, headings and labels; corner radius of buttons,
inputs and cards; padding and gaps; shadows; the CSS transitions declared on
interactive elements; and the custom properties on :root.

It talks to Chrome through the DevTools protocol over a pipe
(--remote-debugging-pipe: JSON messages separated by NUL, commands on the
child's fd 3, replies on fd 4), so it needs nothing beyond the standard library.
Only these values reach the source note, never the page's HTML.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import select
import signal
import sys
import tempfile
import time

WIDTH, HEIGHT = 1280, 800

# Runs in the page. Colors go through a 1×1 canvas, so oklch(), color-mix() and
# friends all come back as sRGB bytes.
EXTRACT = r"""
(async () => {
  try { await Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 1500))]); } catch (e) {}
  const W = innerWidth, H = innerHeight * 3, LIMIT = 6000;
  const cv = document.createElement("canvas"); cv.width = cv.height = 1;
  const cx = cv.getContext("2d", {willReadFrequently: true});
  const memo = new Map();
  const color = c => {
    if (!c || c === "transparent" || !CSS.supports("color", c)) return null;
    if (memo.has(c)) return memo.get(c);
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    const v = d[3] >= 128 ? "#" + [d[0], d[1], d[2]].map(x => x.toString(16).padStart(2, "0")).join("") : null;
    memo.set(c, v); return v;
  };
  const add = (map, key, n = 1) => { if (key) map[key] = (map[key] || 0) + n; };
  const top = (map, n) => Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, n)
    .map(([k, v]) => [k, Math.round(v)]);
  const m = {bg: {}, text: {}, buttons: {}, links: {}, borders: {}, body: {}, heading: {}, label: {},
             rButton: {}, rInput: {}, rCard: {}, pButton: {}, gaps: {}, shadows: {}, transitions: {}};
  let blur = 0, seen = 0;
  const pageOf = el => color(getComputedStyle(el).backgroundColor);
  const page = pageOf(document.documentElement) || (document.body && pageOf(document.body)) || "#ffffff";
  const BUTTON = "button, [role=button], input[type=submit], input[type=button], a[class*=btn], a[class*=button]";
  const INPUT = "input:not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea, select";
  const typeKey = cs => [cs.fontFamily.split(",")[0].replace(/["']/g, "").trim(), cs.fontSize,
                         cs.lineHeight, cs.fontWeight, cs.letterSpacing === "normal" ? "" : cs.letterSpacing].join("|");
  const radius = (cs, r) => {
    const px = parseFloat(cs.borderTopLeftRadius) || 0;
    return px > 0 && px >= Math.min(r.width, r.height) / 2 - 0.5 ? "pill" : Math.round(px) + "px";
  };
  for (const el of document.body ? document.body.querySelectorAll("*") : []) {
    if (seen >= LIMIT) break;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.top > H || r.bottom < 0 || r.left > W || r.right < 0) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || parseFloat(cs.opacity) === 0) continue;
    seen++;
    const area = Math.min(r.width, W) * Math.min(r.height, H);
    const bg = color(cs.backgroundColor);
    const button = el.matches(BUTTON), input = el.matches(INPUT);
    if (bg) add(m.bg, bg, area);
    if (button && bg) add(m.buttons, bg);
    const bordered = parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== "none";
    if (bordered) add(m.borders, color(cs.borderTopColor), r.width + r.height);
    let own = 0;
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent.trim().length;
    const heading = el.matches("h1, h2, h3"), label = button || el.matches("label, nav a");
    if (own || heading || button) {
      const chars = heading || button ? el.textContent.trim().length : own;
      if (chars) {
        add(m.text, color(cs.color), chars);
        if (el.matches("a") && !button) add(m.links, color(cs.color), chars);
        const size = parseFloat(cs.fontSize), display = heading || size > 20;  // a big hero line is a headline too
        if (display || label || size >= 12) add(display ? m.heading : label ? m.label : m.body, typeKey(cs), chars);
      }
    }
    if (button) {
      add(m.rButton, radius(cs, r));
      if (parseFloat(cs.paddingTop) || parseFloat(cs.paddingRight)) add(m.pButton, `${cs.paddingTop} ${cs.paddingRight}`);
    } else if (input) {
      add(m.rInput, radius(cs, r));
    } else if ((bg && bg !== page) || bordered || cs.boxShadow !== "none") {
      if (area > 4000 && area < W * innerHeight * 0.6) add(m.rCard, radius(cs, r));
    }
    if ((cs.display.includes("flex") || cs.display.includes("grid")) && cs.gap && cs.gap !== "normal" && parseFloat(cs.gap) > 0)
      add(m.gaps, cs.gap);
    if (cs.boxShadow && cs.boxShadow !== "none") add(m.shadows, cs.boxShadow);
    if (cs.backdropFilter && cs.backdropFilter !== "none") blur++;
    if ((button || input || el.matches("a")) && cs.transitionDuration.split(",").some(d => parseFloat(d) > 0)) {
      const i = cs.transitionDuration.split(",").findIndex(d => parseFloat(d) > 0);
      const pick = s => (s.match(/(?:[^,(]+|\([^)]*\))+/g) || [s])[i] || s;
      add(m.transitions, `${pick(cs.transitionProperty).trim()} ${pick(cs.transitionDuration).trim()} ${pick(cs.transitionTimingFunction).trim()}`);
    }
  }
  const props = [];
  // Tailwind's default palette and internals: present on every Tailwind page, chosen by nobody.
  const FRAMEWORK = /^--(tw-|color-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|black|white)(-\d+)?$|default-|animate-|ease-|blur-|text-(xs|sm|base|lg|\d?xl)|font-weight-|tracking-|leading-|breakpoint-|container-|spacing$|radius-(xs|sm|md|lg|\d?xl)$|inset-shadow-|drop-shadow-|shadow-(2xs|xs|sm|md|lg|\d?xl)$|perspective-|aspect-)/;
  const rules = list => { for (const rule of list) {
    if (props.length >= 30) return;
    if (rule.cssRules && !rule.selectorText && !(rule.media && /prefers-color-scheme:\s*dark/.test(rule.media.mediaText))) rules(rule.cssRules);
    if (rule.selectorText && /^(:root|html)\b/.test(rule.selectorText.trim()) && rule.style)
      for (const name of rule.style) if (name.startsWith("--") && props.length < 30) {
        const value = rule.style.getPropertyValue(name).trim();
        if (!value || value.length > 80 || /^var\(--[\w-]+\)$/.test(value) || FRAMEWORK.test(name)) continue;
        if (!props.some(p => p[0] === name)) props.push([name, value]);
      }
  } };
  for (const sheet of document.styleSheets) { try { rules(sheet.cssRules); } catch (e) {} }
  return {page, backgrounds: top(m.bg, 8), texts: top(m.text, 6), buttons: top(m.buttons, 4),
          links: top(m.links, 4), borders: top(m.borders, 4),
          type: {body: top(m.body, 2), heading: top(m.heading, 2), label: top(m.label, 2)},
          radius: {button: top(m.rButton, 3), input: top(m.rInput, 3), card: top(m.rCard, 3)},
          padding: top(m.pButton, 3), gaps: top(m.gaps, 4), shadows: top(m.shadows, 3), blur,
          transitions: top(m.transitions, 4), props, elements: seen};
})()
"""


class Chrome:
    """Headless Chrome driven over --remote-debugging-pipe."""

    def __init__(self, binary: str):
        self.profile = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        to_chrome, self.out = os.pipe()
        self.inp, from_chrome = os.pipe()
        # Chrome expects its end of the pipes as fds 3 and 4. Move ours above 10 first,
        # so the dup2 always makes a fresh, inheritable copy.
        high = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10) for fd in (to_chrome, from_chrome)]
        os.close(to_chrome)
        os.close(from_chrome)
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG")}  # no secrets
        args = [binary, "--headless=new", "--remote-debugging-pipe", "--disable-gpu", "--hide-scrollbars",
                "--mute-audio", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={self.profile.name}",
                f"--window-size={WIDTH},{HEIGHT}", "about:blank"]
        try:
            self.pid = os.posix_spawnp(binary, args, env, setpgroup=0, file_actions=[
                (os.POSIX_SPAWN_DUP2, high[0], 3), (os.POSIX_SPAWN_DUP2, high[1], 4),
                (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
                (os.POSIX_SPAWN_OPEN, 1, os.devnull, os.O_WRONLY, 0),
                (os.POSIX_SPAWN_OPEN, 2, os.devnull, os.O_WRONLY, 0)])
        finally:
            for fd in high:
                os.close(fd)
        self.buf, self.last, self.events = b"", 0, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.call("Browser.close", timeout=3)
        except Exception:
            pass
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        os.waitpid(self.pid, 0)
        os.close(self.out)
        os.close(self.inp)
        self.profile.cleanup()

    def _next(self, deadline: float) -> dict:
        while b"\0" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.inp], [], [], left)[0]:
                raise TimeoutError("Chrome didn't answer in time")
            chunk = os.read(self.inp, 1 << 16)
            if not chunk:
                raise ConnectionError("Chrome closed the pipe")
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\0", 1)
        return json.loads(raw)

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 15):
        self.last += 1
        msg = {"id": self.last, "method": method, "params": params or {}, **({"sessionId": session} if session else {})}
        data = json.dumps(msg).encode() + b"\0"
        while data:
            data = data[os.write(self.out, data):]
        deadline = time.monotonic() + timeout
        while True:
            reply = self._next(deadline)
            if reply.get("id") == self.last:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error'].get('message')}")
                return reply.get("result", {})
            self.events.append(reply)

    def wait_for(self, event: str, session: str, timeout: float) -> bool:
        match = lambda m: m.get("method") == event and m.get("sessionId") == session
        if any(map(match, self.events)):
            return True
        deadline = time.monotonic() + timeout
        try:
            while not match(msg := self._next(deadline)):
                self.events.append(msg)
        except TimeoutError:
            return False
        return True


def read(url: str, binary: str) -> dict | None:
    """The page's computed CSS, summarized; None when it can't be read (the
    capture goes on without it)."""
    try:
        with Chrome(binary) as chrome:
            target = chrome.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session = chrome.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            chrome.call("Page.enable", session=session)
            chrome.call("Emulation.setDeviceMetricsOverride",
                        {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False}, session)
            nav = chrome.call("Page.navigate", {"url": url}, session, timeout=30)
            if nav.get("errorText"):
                raise RuntimeError(nav["errorText"])
            chrome.wait_for("Page.loadEventFired", session, 20)  # some pages never finish; read what's there
            time.sleep(1)  # client-side rendering after load
            done = chrome.call("Runtime.evaluate", {"expression": EXTRACT, "returnByValue": True,
                                                    "awaitPromise": True}, session, timeout=20)
            if "exceptionDetails" in done:
                raise RuntimeError(done["exceptionDetails"].get("text", "script error"))
            return summarize(done.get("result", {}).get("value"))
    except Exception as e:
        print(f"[pipeline] no page CSS for {url}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- summary

def accent(hex_: str) -> bool:
    """The same test palette() applies to pixels: a color with a hue, not a gray."""
    rgb = [int(hex_[i:i + 2], 16) for i in (1, 3, 5)]
    hi, lo = max(rgb), min(rgb)
    return hi > 40 and (hi - lo) / hi > 0.25


def colored(hex_: str) -> bool:
    """Clearly a color, not a tinted gray or a near-black: slate text has a hue too."""
    rgb = [int(hex_[i:i + 2], 16) for i in (1, 3, 5)]
    hi, lo = max(rgb), min(rgb)
    return hi >= 90 and (hi - lo) / hi >= 0.45


def distinct(colors: list[str], limit: int) -> list[str]:
    """In order, without near-duplicates (less than 12 apart in RGB)."""
    out = []
    for c in colors:
        rgb = [int(c[i:i + 2], 16) for i in (1, 3, 5)]
        if not any(sum((x - int(o[i:i + 2], 16)) ** 2 for x, i in zip(rgb, (1, 3, 5))) < 144 for o in out):
            out.append(c)
    return out[:limit]


def radius_trait(radius: dict) -> str | None:
    """The radius trait the buttons (else cards, else inputs) actually have."""
    found = radius.get("button") or radius.get("card") or radius.get("input")
    if not found:
        return None
    value = found[0][0]
    if value == "pill":
        return "pill"
    px = float(value.removesuffix("px") or 0)
    return "none" if px == 0 else "subtle" if px <= 5 else "rounded"


def summarize(raw) -> dict | None:
    """The palette (page first, then surfaces, text and borders; accents from
    buttons, links, text and fills), the radius trait and the lines for the note."""
    if not isinstance(raw, dict) or not raw.get("page") or not raw.get("elements"):
        return None
    colors = lambda key: [c for c, _ in raw.get(key) or [] if c]
    accents = distinct([c for key in ("buttons", "links") for c in colors(key) if accent(c)]
                       + [c for key in ("texts", "backgrounds") for c in colors(key) if colored(c)], 5)
    neutrals = distinct([raw["page"]] + [c for key in ("backgrounds", "texts", "borders") for c in colors(key)
                                          if c not in accents], 5)
    palette = [{"hex": c, "role": "neutral"} for c in neutrals] + [{"hex": c, "role": "accent"} for c in accents]
    return {"palette": palette if len(neutrals) >= 2 else [], "radius": radius_trait(raw.get("radius") or {}),
            "lines": lines(raw)}


def visible_shadow(value: str) -> str:
    """A box-shadow without its invisible layers (Tailwind stacks transparent rings
    under every shadow)."""
    def shows(layer: str) -> bool:
        if re.search(r"rgba\([^)]*,\s*0\)|/\s*0\)", layer):  # a transparent color
            return False
        lengths = re.sub(r"[a-z-]+\([^)]*\)|#[0-9a-f]+|[a-z]+", " ", layer.lower()).split()
        return any(float(x.removesuffix("px") or 0) for x in lengths)  # all zero: no offset, blur or spread
    return ", ".join(x.strip() for x in re.findall(r"(?:[^,(]+|\([^)]*\))+", value) if shows(x.strip()))[:160]


def lines(raw: dict) -> list[str]:
    code = lambda xs: ", ".join(f"`{x}`" for x in xs)
    named = lambda key, n=3: [c for c, _ in raw.get(key) or [] if c][:n]
    colors = [f"page `{raw['page']}`"] + [f"{label} {code(named(key))}" for key, label in
                                          (("texts", "text"), ("buttons", "buttons"), ("links", "links"),
                                           ("borders", "borders")) if named(key)]
    out = ["- Colors: " + " · ".join(colors)]

    def type_(entries):
        family, size, line, weight, tracking = entries[0][0].split("|")
        return f"{family} {size}/{line} {weight}" + (f" {tracking}" if tracking else "")
    if kinds := [f"{name} {type_(raw['type'][key])}" for key, name in
                 (("body", "body"), ("heading", "headings"), ("label", "labels")) if raw["type"].get(key)]:
        out.append("- Type: " + " · ".join(kinds))
    if kinds := [f"{name} {raw['radius'][key][0][0]}" for key, name in
                 (("button", "buttons"), ("input", "inputs"), ("card", "cards")) if raw["radius"].get(key)]:
        out.append("- Corner radius: " + " · ".join(kinds))
    spacing = ([f"button padding {raw['padding'][0][0]}"] if raw.get("padding") else []) + \
              ([f"gaps {', '.join(g for g, _ in raw['gaps'])}"] if raw.get("gaps") else [])
    if spacing:
        out.append("- Spacing: " + " · ".join(spacing))
    depth = [f"`{s}`" for s in dict.fromkeys(filter(None, (visible_shadow(s) for s, _ in raw.get("shadows") or [])))][:2] + \
            ([f"backdrop blur on {raw['blur']} elements"] if raw.get("blur") else [])
    if depth:
        out.append("- Depth: " + " · ".join(depth))
    if raw.get("transitions"):
        out.append("- Transitions declared on links, buttons and inputs: "
                   + " · ".join(f"`{t}` ({n})" for t, n in raw["transitions"]))
    if raw.get("props"):
        out.append("- Custom properties on :root: " + "; ".join(f"`{k}: {v}`" for k, v in raw["props"][:20]))
    return out
