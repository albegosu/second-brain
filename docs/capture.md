# Capture

What second-brain can read, where captures wait, and how to send them from each
device. Back to the [README](../README.md).

## What it understands

| Source | How |
|---|---|
| X | fxtwitter: video, GIF or image; X Articles as text, with their key ideas; the media of a quoted post; the page a post without media links to |
| Instagram, LinkedIn | video through yt-dlp with your browser cookies (`BRAIN_COOKIES`); if yt-dlp can't get it, the video the page publishes as JSON-LD, and failing that (photos, carousels) the cover image |
| GitHub repositories | description and README through the API; as media, the first image, GIF or video in the README (badges skipped), else a screenshot of the project's homepage |
| YouTube, Vimeo, TikTok, Bluesky and every other site yt-dlp has an extractor for | the video through yt-dlp, at most 720p and 10 minutes; if it can't be downloaded, the page's thumbnail and description |
| Direct links to an image or a video | the file itself |
| Any other site (news, articles) | title, description and main text (trafilatura, without navigation or banners); the video or post from its JSON-LD if present, otherwise a screenshot of the rendered page (headless Chrome), the article's own figures and `og:image` |
| Speech in any video | transcribed on the machine that runs the worker (faster-whisper, first five minutes), so no audio goes to a model API and no quota is spent. A voice filter drops music and silence. The narration goes to the analysis beside the frames, never instead of them, and into the source note; a talk with no interface pattern yields ideas |
| A shared image (a screenshot or photo, no URL) | the image itself, analyzed like any other capture; if it holds no interface pattern, its text is read so it can still yield ideas. Identified by a content hash, so the same image shared twice isn't filed twice |
| A live web interface | its computed CSS, read in the same headless Chrome through the DevTools protocol: page, surface, text, button and link colors (the palette, instead of pixels with photos in them), fonts with size, weight, line height and tracking, corner radius of buttons, inputs and cards (the radius trait, instead of the model's guess), padding, gaps, shadows, the transitions declared on links and buttons, and the custom properties on `:root`. Only these values reach the note, never the page's HTML |

## Two inboxes

Captures wait in an inbox until the worker files them. `bin/setup` asks which:

- **GitHub (the default):** a private repository, `<wiki>-inbox`. The capture
  page writes one JSON file per capture into its `queue/` folder through the
  GitHub API, and each push starts its workflow
  ([templates/inbox-repo](../templates/inbox-repo)), which files what's queued
  into the wiki and empties the queue. No other account, and captures are filed
  right away. The token on your devices is a fine-grained GitHub token limited
  to the inbox repository with Contents: Read and write, so a lost phone can
  write captures and nothing else; `bin/setup` checks that it can't reach the
  wiki. The workflow writes the wiki with a deploy key that `bin/setup` creates
  and keeps in the inbox's secrets. When the queue is empty the inbox's history
  is started over, so shared images don't pile up. Fine-grained tokens expire (a
  year at most): when captures start failing with "rejected the capture token",
  make a new one and paste it in the page's Settings.
- **Supabase** (`bin/setup --inbox supabase`): a free Supabase project whose
  functions queue captures behind a capture-only token. With a Supabase access
  token, `bin/setup` creates the project and its database. To set it up by hand,
  see [Supabase inbox](self-hosting.md#supabase-inbox).

Each inbox has its own Shortcut: `Save to second-brain.shortcut` for Supabase
and `Save to second-brain (GitHub inbox).shortcut` for GitHub, which asks for
the inbox repository and the capture token and writes the capture as a file in
`queue/`.

## The Shortcut

Shortcuts is the same app on iOS and macOS and syncs over iCloud, so one
Shortcut covers the iPhone and the Mac share sheet. There's one file per inbox:
this section describes the Supabase one; the GitHub one,
[Save to second-brain (GitHub inbox).shortcut](../shortcut/Save%20to%20second-brain%20(GitHub%20inbox).shortcut),
asks for the inbox repository and the capture token instead and has the same
menu, note and image handling.

**Install it:** download
[Save to second-brain.shortcut](../shortcut/Save%20to%20second-brain.shortcut)
and open it (on a Mac it then syncs to the iPhone; on an iPhone, open it from
Files). Shortcuts asks for three values: your Supabase project URL, its
publishable key and your capture token. The file holds nothing personal;
`python shortcut/build.py` generates and signs it on macOS.

When you share, it asks what caught your eye (**Pattern to reuse**, **Visual
style**, **Tool to try**, **Idea to read**, **Idea to grow** or **Just save**) and
then for an optional note. Both reach the worker as `intent: … — note`: the intent
steers the category and the note goes into the analysis. **Idea to grow** also
plants the note in [hypar](integrations.md#hypar).

It also takes an **image**: share a screenshot or photo (no link needed) and it
converts it to JPEG, base64-encodes it and sends it to `capture_image` instead of
the first URL. The worker files it like any other capture, keyed by its content
hash so the same image isn't saved twice.

The note is worth it: it goes into the prompt and improves the analysis a lot,
because you know what caught your eye and the model doesn't. A note can also
start with `intent: Tool to try —` (or any of the menu's intents) when you build
the Shortcut by hand.

### Build it by hand

To build it by hand, or to use the local inbox instead of Supabase:

1. New shortcut → ⓘ → **Show in Share Sheet**. Receive **URLs**, **Text** (the
   LinkedIn app shares text, not a URL) and **Images**; if there's no input, **Stop**.
2. **Get Images from Input** → **Count** them. **If** the count **is** `0` it's a
   link or text (step 3); **Otherwise** it's an image (step 4).
3. *Link/text:* **Get URLs from Input** → **Get Item from List** (First Item) →
   **Get Contents of URL**, `POST`, JSON body `url` = *Item from List*,
   `note` = *Ask Each Time*:
   - with Supabase: `https://<project>.supabase.co/rest/v1/rpc/capture`, header
     `apikey: <SUPABASE_KEY>` and a third field `token` = `<INBOX_TOKEN>`
     (Supabase reads `Authorization` as a JWT, so the token goes in the body);
   - with the local inbox: `http://<mac>.local:8000/capture` and header
     `Authorization: Bearer <INBOX_TOKEN>`.
4. *Image:* **Get Item from List** (First Item) from the images → **Convert Image**
   to **JPEG** → **Base64 Encode** → **Get Contents of URL**, `POST`, to
   `.../rpc/capture_image` (or `.../capture_image` on the local inbox), JSON body
   `image` = the base64, `mime` = `image/jpeg`, `note` and `token` as above.
5. **Get Dictionary Value** `status` from *Contents of URL*, with the variable
   type set to **Text**. **If** it **is** `queued` → **Show Notification** "✓ Sent
   to second-brain"; **Otherwise** → "✗ Couldn't send: *Contents of URL*".

In Shortcuts, clicking a variable pill and typing renames the variable. To write
text, press **Clear** first and type in the empty field.

The local inbox runs on your Mac: see [All on this Mac](self-hosting.md#all-on-this-mac-no-actions).

## Android and desktop

The capture page does what the Shortcut does, for Android and any desktop
browser: [albegosu.github.io/second-brain/](https://albegosu.github.io/second-brain/).
It's a static page (in [`web/`](../web)) that calls the same Supabase functions,
so nothing changes on the server. It works with either [inbox](#two-inboxes).

- **Connect it:** scan the QR code `bin/setup` prints, open or paste its setup
  link, or fill in the inbox by hand (GitHub: the inbox repository and the
  capture token; Supabase: project URL, publishable key and capture token). The
  settings are kept in that browser's storage and sent only to your inbox. The
  setup link carries them in the URL fragment, which browsers never send to a
  server; the page removes it from the address bar once it's read. **Copy setup
  link** in Settings makes one to connect another device. The QR code needs
  `qrencode` (`brew install qrencode`) or the `segno` or `qrcode` Python
  package; without one, `bin/setup` prints only the link.
- **Back where you were:** after sending a capture shared from another app, the
  page closes itself so you return to that app (the bookmarklet's window too).
- **Android:** open the page in Chrome and install it (⋮ → **Install app** or
  **Add to Home screen**). It then shows up in the share sheet of every app, for
  links, text with a link in it (what LinkedIn and Instagram share) and images.
- **Desktop:** paste a link, or paste, drop or choose an image. Settings has a
  **Save to second-brain** bookmarklet for the bookmarks bar: on any page it opens
  a small window with that page's link, and closes it once it's sent.
- **Same flow as the Shortcut:** it asks what caught your eye and for an optional
  note, and sends `intent: … — note`. Images are converted to JPEG (at most
  2560 px on the long side) and sent to `capture_image`.
- **Offline or paused project:** a capture that can't be sent waits in the
  browser and is retried when you open the page again or come back online.

### Host your own copy

It's served by GitHub Pages from this repository (`.github/workflows/pages.yml`).
To host your own copy, publish `web/` anywhere with HTTPS; the page has no build
step and loads nothing from other sites. Change the link-preview URLs at the top
of `web/index.html` to your address; the preview image is `web/icons/og.png`,
rendered from `og.html` next to it. The local inbox isn't supported: a page
served over HTTPS can't call `http://<mac>.local`.

## Command line

To file one thing without the inbox — a URL, or a local image such as a
screenshot or photo — run the worker directly:

```bash
python -m worker.run --url https://example.com/article --note "why it caught my eye"
python -m worker.run --image ~/Desktop/screenshot.png --note "the empty state"
```

This runs the worker on your computer, so it needs the
[local install](self-hosting.md#install-the-worker-locally) first.
