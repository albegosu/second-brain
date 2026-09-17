"""Ingestion pipeline.

    URL → media → keyframes → VLM → patterns + style → wiki (worker/wiki.py)
"""
from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx
import trafilatura
import yt_dlp

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# Without a local Ollama (GitHub Actions): OLLAMA_HOST=https://ollama.com plus the API key.
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
VLM = os.environ.get("BRAIN_VLM", "gemma4:31b-cloud")
ROOT = Path(__file__).resolve().parent.parent
# Absolute, so paths stay valid whatever the working directory.
MEDIA = Path(os.environ.get("BRAIN_MEDIA", ROOT / "data" / "media")).expanduser().resolve()

# Closed vocabulary (what each value means: docs/taxonomy.md). The prompt and
# clean_patterns() are built from it.
FACETS = {
    "component": ["accordion", "card", "nav", "modal", "table", "form", "timeline",
                  "hero", "sidebar", "carousel", "tooltip", "command-palette", "chart", "other"],
    "motion": ["fade", "slide", "scale", "morph", "stagger", "parallax", "spring", "reveal", "none"],
    "layout": ["grid", "split", "stacked", "bento", "full-bleed", "centered", "asymmetric"],
    "density": ["sparse", "balanced", "dense"],
    "color": ["monochrome", "high-contrast", "pastel", "dark", "vibrant", "muted"],
}

# Style traits: one set per capture, one value per trait. The palette isn't here:
# it is measured from pixels (palette()).
STYLE = {
    "typography": ["geometric-sans", "grotesk", "humanist-sans", "serif", "mono", "display"],
    "radius": ["none", "subtle", "rounded", "pill"],
    "spacing": ["tight", "comfortable", "airy"],
    "depth": ["flat", "soft-shadow", "layered", "glass"],
    "motion_feel": ["snappy", "smooth", "springy", "none"],
}

SYSTEM = """You analyze interface captures for a reference catalog.
You receive the frames of a UI demo in time order.

Return ONLY valid JSON, with no markdown or preamble:

{"patterns": [{
  "title": "short, specific name",
  "summary": "1-2 sentences: what it is and what makes it notable",
  "trigger": "hover|click|scroll|load|drag|focus|auto",
  "behavior": "what happens, step by step, in order",
  "notes": "why it works / what is worth copying",
  "facets": __FACETS__,
  "motion_spec": {
    "properties": [],
    "duration_ms": null,
    "easing": null,
    "stagger_ms": null,
    "description": "how the motion feels"
  }
}],
 "style": {
  "typography": null,
  "radius": null,
  "spacing": null,
  "depth": null,
  "motion_feel": null,
  "description": "the look in 2-3 sentences"
 }}

Rules:
- facets: each dimension is an array of one or more values, chosen ONLY from the
  options listed above (["nav"], never "nav"). For component, pick the most
  specific one that fits (a floating label on hover is a tooltip; tabs are nav).
  "other" only if nothing really fits.
- A video can contain several patterns: separate them. If it compares variants
  (before/after, good/great), describe the recommended one.
- If no interaction or interface pattern is visible (a screenshot of a tool, a
  chart, a photo), return "patterns": []. Don't invent them.
- behavior: numbered steps. 1) initial state, 2) what triggers it and where,
  3) which elements change, in which direction and order, 4) final state.
  It must be enough to reimplement it without watching the video.
- motion_spec.properties: properties that actually change in what you see
  (transform, opacity, height, width, clip-path, border-radius, color,
  box-shadow...). Don't copy examples.
- motion_spec.easing: "ease-out", "ease-in-out", "linear" or "spring" (only with
  visible bounce or overshoot). If you can't tell, null. Never write a
  cubic-bezier curve: you can't measure it.
- duration_ms and stagger_ms: from still frames you almost never can tell, so
  null is expected. Only give a number if the post itself states it.
- If the post text describes the interaction, use it to interpret the frames:
  they are isolated moments and the motion between them is invisible. But every
  pattern must be visible in the frames: ignore anything the text mentions that
  doesn't appear.
- Write title, summary, behavior, notes and every description in English, even
  if the post or the note is in another language.
- style describes the visual language of the whole capture, not of one pattern.
  One value (string) per trait, from these options: __STYLE__. null if you can't
  tell. typography is the dominant family, not the exact font: you can't
  identify it. style.description covers typography, surfaces, contrast and
  rhythm; colors are measured separately, so don't list codes.
- Don't name specific technologies ("uses Framer Motion"): you can't know that.
""".replace("__FACETS__", json.dumps(FACETS)).replace("__STYLE__", json.dumps(STYLE))


def detect_source(url: str) -> str:
    host = httpx.URL(url).host.removeprefix("www.")
    if host in ("x.com", "twitter.com"):
        return "x"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("linkedin.com"):
        return "linkedin"
    if host == "github.com":
        return "github"
    return video_site(url) or "web"


def video_site(url: str) -> str | None:
    """The yt-dlp extractor for a site it knows (youtube, vimeo, tiktok, bluesky…),
    never its generic one, which would claim any page."""
    for ie in yt_dlp.extractor.gen_extractor_classes():
        if ie.ie_key() != "Generic" and ie.suitable(url):
            return ie.ie_key().lower()
    return None


# Parameters apps add when sharing. Without stripping them, the same post shared
# from the iPhone (?s=12) and from the Mac would become two captures.
TRACKING = re.compile(r"utm_\w+|fbclid|gclid|igsh|igshid|mibextid|si|trk|trackingId|rcm|ref_src|ref_url")
TRACKING_X = re.compile(r"s|t")  # meaningless on X; on an arbitrary site they might matter


def canonical_url(url: str) -> str:
    u = httpx.URL(url.strip())
    x = detect_source(str(u)) == "x"
    for key in set(u.params.keys()):
        if TRACKING.fullmatch(key) or (x and TRACKING_X.fullmatch(key)):
            u = u.copy_remove_param(key)
    return str(u.copy_with(fragment=None))


# ---------------------------------------------------------------- ingestion

X_URL = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/", re.I)


def fetch_x(url: str, cid: int) -> dict | None:
    """X serves video as chunked HLS behind a blob: URL. fxtwitter normalizes it
    into a direct mp4 with no API key, and it also returns what a post only links
    to: the text of an X Article and the media of a quoted post. A post with none
    of that but an outside link is read through the linked page. Without this the
    model got a bare link and made the capture up. Returns None when it doesn't
    apply."""
    m = re.search(r"status/(\d+)", url)
    if not m:
        return None
    r = httpx.get(f"https://api.fxtwitter.com/status/{m.group(1)}",
                  headers={"User-Agent": "second-brain/1.0"}, timeout=30)
    if r.status_code != 200:
        return None
    tweet = r.json().get("tweet") or {}
    author = (tweet.get("author") or {}).get("screen_name")
    text = (tweet.get("text") or "").strip()

    if article := tweet.get("article"):  # the cover is decoration: the text is the capture
        blocks = (article.get("content") or {}).get("blocks") or []
        body = "\n\n".join(str(b.get("text")).strip() for b in blocks if isinstance(b, dict) and str(b.get("text") or "").strip())
        return {"path": None, "kind": "text", "article": True, "author": author,
                "text": "\n\n".join(x for x in (article.get("title"), article.get("preview_text")) if x),
                "page": {"title": article.get("title"), "description": article.get("preview_text"),
                         "excerpt": body or article.get("preview_text") or ""}}

    media = (tweet.get("media") or {}).get("all") or []
    quote = tweet.get("quote") or {}
    if not media and quote:
        media = (quote.get("media") or {}).get("all") or []
        quoted = (quote.get("author") or {}).get("screen_name")
        text = f"{text}\n\nQuoting @{quoted}: {(quote.get('text') or '').strip()}".strip()
    if media:
        item = media[0]
        kind = "video" if item["type"] in ("video", "gif") else "image"
        path = MEDIA / f"{cid}.{'mp4' if kind == 'video' else 'jpg'}"
        path.write_bytes(httpx.get(item["url"], follow_redirects=True, timeout=120).content)
        return {"path": path, "kind": kind, "author": author, "text": text}

    for link in re.findall(r"https?://[^\s<>\"')]+", text):
        if X_URL.match(link):
            continue
        try:
            linked = canonical_url(link)
            return {**fetch_media(linked, detect_source(linked), cid), "author": author, "text": text}
        except Exception as e:
            print(f"[pipeline] linked page dropped: {e}", file=sys.stderr)
        break
    return {"path": None, "kind": "text", "author": author, "text": text}


def fetch_ytdlp(url: str, cid: int) -> dict:
    """Instagram and LinkedIn have no public route. yt-dlp with your browser's
    cookies is what works. It automates logged-in access, so use it for your
    personal catalog and nothing else.

        BRAIN_COOKIES=firefox                          (or chrome, safari)
        BRAIN_COOKIES=firefox:xxxx.dev-edition-default (browser:profile)
        BRAIN_COOKIES=/path/to/cookies.txt
    """
    opts = {
        "outtmpl": str(MEDIA / f"{cid}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,  # quiet doesn't silence the download bar: it would flood the log
        # Frames are scaled to 1024 px and a demo is short: no 4K, no hour-long talks.
        "format": "b[height<=?720]/bv*[height<=?720]/b",
        "match_filter": yt_dlp.utils.match_filter_func("duration <=? 600"),
    }
    cookies = os.environ.get("BRAIN_COOKIES")
    if cookies:
        if "/" in cookies:
            opts["cookiefile"] = cookies
        else:  # yt-dlp wants (browser, profile), not the CLI's "browser:profile"
            browser, _, profile = cookies.partition(":")
            opts["cookiesfrombrowser"] = (browser, profile or None)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    path = Path(ydl.prepare_filename(info))
    if not path.exists():  # skipped by match_filter
        raise yt_dlp.utils.DownloadError(f"not downloaded, longer than 10 minutes? {url}")
    return {"path": path,
            "kind": "image" if path.suffix in (".jpg", ".png", ".webp") else "video",
            "author": info.get("uploader") or info.get("channel"),
            "text": info.get("description")}


POST_TYPES = {"VideoObject", "SocialMediaPosting", "DiscussionForumPosting",
              "Article", "NewsArticle", "BlogPosting"}


def _types(item: dict) -> list[str]:
    t = item.get("@type") or []
    return [t] if isinstance(t, str) else [x for x in t if isinstance(x, str)]


def json_ld(html: str) -> list[dict]:
    """The page's schema.org objects. Many sites publish there the video, the
    author and the text that the visible page hides behind a login."""
    items = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        data = None
        for raw in (block, unescape(block)):
            try:
                data = json.loads(raw)
                break
            except json.JSONDecodeError:
                continue
        candidates = data if isinstance(data, list) else (data or {}).get("@graph", [data] if data else [])
        items += [item for item in candidates if isinstance(item, dict)]
    return items


UA = {"User-Agent": "Mozilla/5.0 (Macintosh) second-brain/1.0"}


def to_jpg(src: Path, dst: Path) -> Path:
    """Always to jpg, at most 1024 px wide: webp, svg or avif don't work for every
    model or for the palette."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-frames:v", "1",
                    "-vf", "scale='min(1024,iw)':-2", "-q:v", "3", str(dst)],
                   capture_output=True, check=True)
    return dst


def save_media(r: httpx.Response, cid: int) -> dict:
    """A downloaded file by its type: videos and GIFs (they animate) go through
    keyframes, images become one jpg."""
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not ctype.startswith(("image/", "video/")):  # raw file hosts often say octet-stream
        ctype = mimetypes.guess_type(r.url.path)[0] or ctype
    if ctype.startswith("video/") or ctype == "image/gif":
        path = MEDIA / f"{cid}{'.gif' if ctype == 'image/gif' else '.mp4'}"
        path.write_bytes(r.content)
        return {"path": path, "kind": "video"}
    if ctype.startswith("image/"):
        src = MEDIA / f"{cid}.download"
        src.write_bytes(r.content)
        try:
            return {"path": to_jpg(src, MEDIA / f"{cid}.jpg"), "kind": "image"}
        finally:
            src.unlink(missing_ok=True)
    raise RuntimeError(f"not an image or a video: {ctype or 'unknown type'}")


def download_media(url: str, cid: int) -> dict:
    r = httpx.get(url, follow_redirects=True, timeout=120, headers=UA)
    r.raise_for_status()
    return save_media(r, cid)


def chrome() -> str | None:
    """Chrome or Chromium for screenshots: BRAIN_CHROME, the PATH (GitHub's Ubuntu
    runners ship google-chrome) or the macOS app."""
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return (os.environ.get("BRAIN_CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
            or shutil.which("chromium-browser") or (mac if Path(mac).exists() else None))


def screenshot(url: str, cid: int) -> Path | None:
    """The first 1280×800 of the rendered page. og:image is usually a marketing
    card rather than the interface, and pages built client-side often have none.
    None without Chrome or when the page doesn't render."""
    binary = chrome()
    if not binary:
        return None
    shot = MEDIA / f"{cid}-page.png"
    shot.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG")}  # no secrets
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        proc = subprocess.Popen(
            [binary, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={profile}", "--window-size=1280,800",
             "--timeout=10000", f"--screenshot={shot}", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        # Chrome writes the screenshot, but pages with running timers (canvas apps)
        # keep it alive: once the file stops growing, kill the whole process group.
        deadline, size = time.monotonic() + 40, -1
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.5)
            now = shot.stat().st_size if shot.exists() else -1
            if now == size > 0:
                break
            size = now
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    if not shot.exists() or not shot.stat().st_size:
        print(f"[pipeline] no screenshot of {url}", file=sys.stderr)
        return None
    try:
        return to_jpg(shot, MEDIA / f"{cid}-page.jpg")
    finally:
        shot.unlink(missing_ok=True)


def readable(html: str, url: str) -> str:
    """The main content (article, README, landing copy) without navigation,
    banners or footers; all visible text when that can't be found."""
    if text := trafilatura.extract(html, url=url, favor_precision=True, include_comments=False,
                                   include_tables=False):
        return text
    text = re.sub(r"<(script|style|noscript|svg|template)\b.*?</\1>", " ", html, flags=re.I | re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text))).strip()


GITHUB_REPO = re.compile(r"^/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/|$)")
GITHUB_RESERVED = {"orgs", "topics", "collections", "features", "marketplace", "sponsors", "settings",
                   "search", "trending", "explore", "enterprise", "pricing", "login", "about"}
README_MEDIA = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)|<img[^>]+src=[\"']([^\"']+)"
                          r"|^\s*(https://github\.com/user-attachments/assets/[\w-]+)\s*$", re.I | re.M)
BADGE = re.compile(r"shields\.io|badgen|badge|/workflows/|codecov|\.svg(?:\?|$)", re.I)


def fetch_github(url: str, cid: int) -> dict | None:
    """A repository: description and README from the API. As media, the first
    image or video in the README (demos are often a GIF), else a screenshot of the
    project's homepage. GitHub's own og:image is a generated card with the repo
    name. None when the URL isn't a repository."""
    m = GITHUB_REPO.match(httpx.URL(url).path)
    if not m or m.group(1).lower() in GITHUB_RESERVED:
        return None
    api = f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "second-brain/1.0"}
    if token := os.environ.get("GITHUB_TOKEN"):  # higher rate limit on Actions
        headers["Authorization"] = f"Bearer {token}"
    r = httpx.get(api, headers=headers, timeout=30)
    if r.status_code != 200:
        return None
    repo = r.json()
    readme = httpx.get(f"{api}/readme", headers={**headers, "Accept": "application/vnd.github.raw"},
                       follow_redirects=True, timeout=30)
    readme = readme.text if readme.status_code == 200 else ""

    result = {"path": None, "kind": "text", "author": repo["owner"]["login"],
              "text": repo.get("description"),
              "page": {"title": repo["full_name"], "description": repo.get("description"),
                       "excerpt": readme[:3000]}}
    raw = f"https://raw.githubusercontent.com/{repo['full_name']}/{repo.get('default_branch') or 'HEAD'}/"
    for match in README_MEDIA.finditer(readme):
        src = next(g for g in match.groups() if g)
        if BADGE.search(src):
            continue
        src = re.sub(r"^https://github\.com/([^/]+/[^/]+)/(?:blob|raw)/", r"https://raw.githubusercontent.com/\1/",
                     urljoin(raw, src))
        try:
            return {**result, **download_media(src, cid)}
        except Exception as e:
            print(f"[pipeline] README media dropped: {e}", file=sys.stderr)
            break
    if repo.get("homepage") and (shot := screenshot(repo["homepage"], cid)):
        return {**result, "path": shot, "kind": "image"}
    return result


def fetch_page(url: str, cid: int, visible_text: bool = True) -> dict:
    """Regular web pages (tools, landings, articles): title, description, main
    text and how the page looks. If the page publishes a video or a post as
    JSON-LD, that video, its author and its text are used; otherwise the frames
    are a screenshot of the rendered page plus og:image. visible_text=False for
    social networks and video sites, where the visible page is a cookie and login
    banner: no text, no screenshot. A direct link to an image or a video is
    downloaded as it is."""
    r = httpx.get(url, follow_redirects=True, timeout=30, headers=UA)
    r.raise_for_status()
    host = httpx.URL(url).host.removeprefix("www.")
    if (r.headers.get("content-type") or "").lower().startswith(("image/", "video/")):
        return {**save_media(r, cid), "author": host, "text": r.url.path.rsplit("/", 1)[-1]}
    html = r.text

    def meta(name: str) -> str | None:
        for pattern in (rf'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]*content=["\']([^"\']*)',
                        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{name}["\']'):
            if m := re.search(pattern, html, re.I):
                return unescape(m.group(1)).strip() or None
        return None

    title = meta("og:title")
    if not title and (m := re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)):
        title = unescape(m.group(1)).strip()

    page = {"title": title, "description": meta("og:description") or meta("description"),
            "excerpt": readable(html, str(r.url))[:3000] if visible_text else ""}
    result = {"path": None, "kind": "text", "author": host,
              "text": "\n\n".join(x for x in (title, page["description"]) if x), "page": page}

    if post := next((i for i in json_ld(html) if POST_TYPES & set(_types(i))), None):
        who = post.get("creator") or post.get("author")
        who = who[0] if isinstance(who, list) and who else who
        if isinstance(who, dict) and who.get("name"):
            result["author"] = who["name"]
        body = post.get("articleBody") or post.get("text") or post.get("description")
        if body and not page["excerpt"]:  # on a regular site the visible text wins; on social, the post
            page["excerpt"] = str(body)[:3000]
        if "VideoObject" in _types(post) and post.get("contentUrl"):
            try:
                dst = MEDIA / f"{cid}.mp4"
                with httpx.stream("GET", post["contentUrl"], follow_redirects=True, timeout=120) as v:
                    v.raise_for_status()
                    with dst.open("wb") as fh:
                        for chunk in v.iter_bytes():
                            fh.write(chunk)
                return {**result, "path": dst, "kind": "video"}
            except Exception as e:
                print(f"[pipeline] JSON-LD video dropped: {e}", file=sys.stderr)

    images = []
    if visible_text and (shot := screenshot(str(r.url), cid)):
        images.append(shot)
    if image := meta("og:image"):
        try:
            og = download_media(urljoin(str(r.url), image), cid)
            if og["kind"] == "image":
                images.append(og["path"])
        except Exception as e:
            print(f"[pipeline] og:image dropped: {e}", file=sys.stderr)
    if images:
        result.update(path=images[0], kind="image", extra=images[1:])
    return result


def fetch_media(url: str, source: str, cid: int) -> dict:
    MEDIA.mkdir(parents=True, exist_ok=True)
    if source == "x":
        if result := fetch_x(url, cid):
            return result
    if source == "github":
        return fetch_github(url, cid) or fetch_page(url, cid)
    if source == "web":
        return fetch_page(url, cid)
    try:
        return fetch_ytdlp(url, cid)
    except yt_dlp.utils.DownloadError as e:
        # Instagram photos and carousels, LinkedIn videos yt-dlp can't extract, long
        # or blocked videos: the page serves the video (JSON-LD) or else og:image.
        print(f"[pipeline] no video, using the page: {str(e)[:120]}", file=sys.stderr)
        result = fetch_page(url, cid, visible_text=False)
        # Instagram: "490 likes, 80 comments - username on April 29, 2026: "text…""
        if m := re.search(r" - ([\w.]+) on [A-Z][a-z]+ \d{1,2}, \d{4}:", result["page"].get("description") or ""):
            result["author"] = m.group(1)
        return result


def video_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:  # "N/A" in some containers
        return 6.0


def scene_peaks(video: Path, threshold: float = 0.04) -> list[tuple[float, float]]:
    """(second, score) of each scene change. In real UI demos peaks sit around
    0.05-0.10; 0.25 is for editing cuts and never fires."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-an",
         "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stdout
    peaks, t = [], None
    for line in out.splitlines():
        if m := re.search(r"pts_time:([\d.]+)", line):
            t = float(m.group(1))
        elif t is not None and (m := re.search(r"scene_score=([\d.]+)", line)):
            peaks.append((t, float(m.group(1))))
    return peaks


def keyframes(video: Path, cid: int, limit: int = 12) -> list[Path]:
    """A uniform grid across the whole video plus the strongest scene peaks.

    Scene detection alone misses whole demos: UI changes are subtle, and a 29 s
    video with six micro-interactions gave 4 frames, none from its first 14 s.
    A uniform grid alone falls between transitions. The grid guarantees coverage
    (initial state included) and the rest of the budget goes to transitions."""
    out = MEDIA / f"frames-{cid}"
    shutil.rmtree(out, ignore_errors=True)  # a re-analysis doesn't inherit stale frames
    out.mkdir(parents=True)

    length = video_duration(video)
    grid = max(3, min(math.ceil(length / 2.5), limit - limit // 3))
    times = [i * length / grid for i in range(grid)]
    for t, _ in sorted(scene_peaks(video), key=lambda peak: -peak[1]):
        if len(times) >= limit:
            break
        if all(abs(t - x) > 0.5 for x in times):
            times.append(t)

    for i, t in enumerate(sorted(times), 1):
        subprocess.run(  # no check: a seek near the end may yield no frame
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=1024:-2:out_range=full", "-q:v", "3",
             str(out / f"{i:03d}.jpg")],
            capture_output=True,
        )
    return sorted(out.glob("*.jpg"))


def palette(frames: list[Path], width: int = 96) -> list[dict]:
    """Colors measured from pixels, not estimated: a VLM makes up hex codes.
    Neutrals and accents are kept apart, because a brand color often covers
    1-2% of the screen and a top-N by area loses it."""
    buckets: dict[tuple, list[int]] = {}
    for f in frames:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(f), "-vf", f"scale={width}:-2",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True,
        ).stdout
        for i in range(0, len(raw) - 2, 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            s = buckets.setdefault((r >> 3, g >> 3, b >> 3), [0, 0, 0, 0])
            s[0] += 1; s[1] += r; s[2] += g; s[3] += b
    total = sum(s[0] for s in buckets.values()) or 1

    merged: list[list] = []  # [pixels, (r, g, b)], merging shades less than 40 apart in RGB
    for n, r, g, b in sorted(buckets.values(), reverse=True):
        rgb = (r // n, g // n, b // n)
        for m in merged:
            if sum((x - y) ** 2 for x, y in zip(m[1], rgb)) < 1600:
                m[0] += n
                break
        else:
            merged.append([n, rgb])
    merged.sort(reverse=True)

    def accent(rgb):
        hi, lo = max(rgb), min(rgb)
        return hi > 40 and (hi - lo) / hi > 0.25

    def entry(n, rgb, role):
        return {"hex": "#%02x%02x%02x" % rgb, "share": round(100 * n / total, 1), "role": role}

    neutrals = [entry(n, rgb, "neutral") for n, rgb in merged if not accent(rgb)][:4]
    accents = [entry(n, rgb, "accent") for n, rgb in merged if accent(rgb) and 100 * n / total >= 0.2][:5]
    return neutrals + accents


# ---------------------------------------------------------------- model

def chat(system: str, user: str, images: list[Path] | None = None, as_json: bool = False,
         num_ctx: int = 16384) -> str:
    message = {"role": "user", "content": user}
    if images:
        message["images"] = [base64.b64encode(f.read_bytes()).decode() for f in images]
    body = {"model": VLM, "stream": False, "options": {"temperature": 0.2, "num_ctx": num_ctx},
            "messages": [{"role": "system", "content": system}, message]}
    if as_json:
        body["format"] = "json"
    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {}
    r = httpx.post(f"{OLLAMA}/api/chat", json=body, headers=headers, timeout=600)
    if r.is_error:  # Ollama explains why in the body (e.g. a paid cloud model)
        raise RuntimeError(f"{VLM}: {r.status_code} {r.text[:300]}")
    return r.json()["message"]["content"]


def unfence(raw: str) -> str:
    """Cloud models sometimes wrap the answer in ```json or ```markdown."""
    return re.sub(r"^\s*```[a-z]*[ \t]*\n?|\n?\s*```\s*$", "", raw)


def parse_json(raw: str):
    try:
        return json.loads(unfence(raw))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"the model did not return JSON: {raw[:300]}") from e


IDEAS = """You extract the ideas worth keeping from a text a user saved: an article,
a thread or a page, usually about how to work (engineering practices, workflows
with AI agents, learning, product thinking).

Return ONLY JSON:
{"ideas": [{"title": "short, specific name of the idea",
            "claim": "the idea itself, in one or two sentences",
            "why": "the reasoning or evidence the text gives for it",
            "apply": "how to put it into practice, as concretely as the text allows"}]}

Rules:
- Only ideas the text states. No outside knowledge, no generic advice.
- Up to 8 ideas, the most useful first; fewer if the text has fewer.
- If the text isn't about ideas or practices (a product launch, an ad for a
  course or service, a list of tools, a UI demo, a caption), return {"ideas": []}.
- English, whatever the language of the text. Leave a field empty rather than guess.
"""


def ideas(text: str, note: str | None = None) -> list[dict]:
    """The ideas of an article or a long text, for practices topics."""
    prompt = ([f"User's note (why they saved it): {note}"] if note else []) + [f"Text:\n{text[:24000]}"]
    data = parse_json(chat(IDEAS, "\n\n".join(prompt), as_json=True, num_ctx=32768))
    items = data.get("ideas") if isinstance(data, dict) else data
    return [i for i in items or [] if isinstance(i, dict) and i.get("title") and i.get("claim")]


def readable_words(media: dict) -> int:
    """Words there are to read in a capture, links left out. A post whose text is
    the page's title and description (Instagram) doesn't count them twice."""
    page = media.get("page") or {}
    text = str(media.get("text") or "")
    parts = [text, page.get("excerpt")] + [x for x in (page.get("title"), page.get("description"))
                                           if x and str(x) not in text]
    return len(re.sub(r"https?://\S+", " ", " ".join(str(x or "") for x in parts)).split())


def analyze(frames: list[Path], note: str | None, post_text: str | None = None) -> dict:
    prompt = ["Analyze these frames in order."]
    if note:
        prompt.append(f"User's note (what caught their eye): {note}")
    if post_text:
        prompt.append(f"Post text: {post_text}")
    data = parse_json(chat(SYSTEM, "\n\n".join(prompt), images=frames, as_json=True))
    return data if isinstance(data, dict) else {"patterns": data}


# ---------------------------------------------------------------- cleanup

def clean_patterns(patterns: list) -> list[dict]:
    """Only patterns with a title, and facets from the closed vocabulary.
    Anything the model returns outside the lists is dropped with a warning: a
    value that keeps coming back is a candidate for FACETS."""
    out = []
    for pt in patterns:
        if not isinstance(pt, dict) or not pt.get("title"):
            continue
        facets = {}
        for dim, values in (pt.get("facets") or {}).items():
            for v in [values] if isinstance(values, str) else values or []:  # sometimes "nav" instead of ["nav"]
                if v in FACETS.get(dim, ()):
                    facets.setdefault(dim, []).append(v)
                else:
                    print(f"[pipeline] facet dropped: {dim}={v!r}", file=sys.stderr)
        out.append({**pt, "facets": facets})
    return out


def clean_style(style: dict | None, frames: list[Path]) -> dict:
    """Traits from the closed vocabulary, plus the palette measured from pixels."""
    style = style or {}
    traits = {}
    for dim, values in STYLE.items():
        v = style.get(dim)
        if v is not None and v not in values:
            print(f"[pipeline] trait dropped: {dim}={v!r}", file=sys.stderr)
            v = None
        traits[dim] = v
    return {**traits, "description": style.get("description"), "palette": palette(frames)}
