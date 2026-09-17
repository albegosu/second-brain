# second-brain

A memory for things worth keeping: interface patterns and styles, feature ideas
and tools. You share a post from X, Instagram or LinkedIn, or any web page, from
your iPhone or Mac. A model analyzes it, files it under a topic and merges it
into a Markdown wiki kept in a separate private repository. Claude then reads it
through the `second-brain` skill before designing or building something. This
repository is the engine.

What sets it apart and where it's going: [PRODUCT.md](PRODUCT.md) ·
[ROADMAP.md](ROADMAP.md).

```
Shortcut ──► Supabase (inbox) ──► GitHub Actions (worker + Ollama Cloud) ──► wiki repository
                                          │                                       │
                                          ▼                                  git pull on the Mac
                                  ntfy push to the phone                          ▼
                                                                         second-brain skill
```

## Quick start

You need a GitHub account with [gh](https://cli.github.com) logged in, a free
[Supabase](https://supabase.com) project, an [Ollama](https://ollama.com) API key
and an iPhone or Mac with Shortcuts.

1. Get the engine:

   ```bash
   git clone https://github.com/albegosu/second-brain ~/Developer/second-brain
   cd ~/Developer/second-brain
   ```

2. Create your private wiki repository and wire everything to it. It asks for
   the Supabase project, an optional Supabase access token (to set up the
   database for you) and the Ollama key:

   ```bash
   bin/new-wiki
   ```

3. Open `shortcut/Save to second-brain.shortcut` and answer its three questions
   with the values `bin/new-wiki` prints at the end.
4. Optionally, subscribe to the printed topic in the [ntfy](https://ntfy.sh) app
   to get a push when each capture is filed.
5. Share a post or a page. A few minutes later it's in your wiki, and Claude
   reads it through the `second-brain` skill.

The rest of this README explains the pieces, how to set them up by hand, and how
to run the worker on your own computer instead.

## The wiki

It lives in its own private repository (`second-brain-wiki`), together with the
workflows that write it; this repository only holds the engine. Captures quote
third-party posts, so that content stays private even if the engine is
published, and the worker runs there because GitHub Actions logs of a public
repository are public and print what was captured. Point `BRAIN_WIKI` at its
`wiki/` folder.

```
wiki/
  index.md                      map of topics; written by code
  taste.md                      recurring choices across captures; weekly
  usage.md                      what was built from which captures
  design/ features/ tools/      one page per topic
  practices/
  sources/2026-09/0007-….md     one note per capture
  sources/2026-09/0007-….jpg    what it looked like: up to 4 frames in time order
```

- **Categories:**
  - `design`: how an interface looks and moves. Topics that collect a look are
    named `style-*`.
  - `features`: what a product does for its user.
  - `tools`: tools, libraries and services.
  - `practices`: how to work (engineering practices, workflows with agents,
    lessons from articles).
- **Source notes** (`sources/`): written by code from what was extracted, with
  no reinterpretation. They hold your note, the patterns the model saw, the key
  ideas of an article or long text, the style with its pixel-measured palette,
  the post or page text, and a link to the original.
- **Topic pages:** the model picks the topic (reusing an existing one if it fits)
  and rewrites the page from all of its source notes, citing them as `[n]`. Pages
  are built for an agent about to implement something, with one block per item:
  patterns (**Use it when**, **How it works**, **Motion**, **Watch out**), styles
  as a DESIGN.md-like sheet (**Tokens**, **Composition**, **Do**, **Don't**),
  tools (**What it does**, **Use it when**, **Link**) or ideas (**Claim**, **Why it
  matters**, **How to apply**). A "Choosing" section follows when there are
  several, and "See also" links. The frontmatter, "See also", the sources list,
  the links a tool can use and the index are written by code, so a bad answer can
  at most spoil a text, never the navigation.
- **Nothing is guessed:** a capture with no image, video or text to read (a bare
  link, a one-line caption) isn't filed; you get a notification asking to share
  it again with a note.
- **Language:** everything in English.
- **Commits:** with `BRAIN_GIT_SYNC=1`, the worker commits and pushes the wiki
  folder to the repository that holds it after each capture. The commits are
  unsigned (it runs without a terminal for the GPG passphrase) and never touch
  anything outside that folder; code commits are yours.
- **Videos and frames:** the downloads stay in `data/`, out of git. The wiki keeps
  one small jpg per visual capture next to its note (up to four frames spread
  across the video, or the image), so an agent can look at the reference and not
  only read about it.

A note with `style: name` (or `estilo: name`) files the capture under
`design/style-name`, to collect a look across several captures.

After changing the analysis, this runs the model again over every capture the
current version hasn't analyzed (source notes record it as `analyzed`) and
rewrites the wiki. If it stops on a quota or network error, run it again and it
resumes:

```bash
python -m worker.run --reanalyze
```

Topic pages are regenerated from their sources, so manual edits to them don't
last; put lasting context in the capture's note.

**Lint pass.** Once a week, the wiki repository's `lint` workflow asks the model to review
the whole wiki: merge duplicate topics, split catch-alls, move misfiled captures
and relate topics. The code only applies proposals that keep every source note in
exactly one topic and only links topics within the same category (across
categories the model pairs things that merely share an area), rewrites the
affected pages and commits the result. Locally:

```bash
python -m worker.lint --dry-run        # print the validated plan, change nothing
python -m worker.lint                  # apply it
python -m worker.lint --recompose-all  # also rewrite every page from its sources
python -m worker.lint --no-plan        # skip the model's plan, only apply the rules
```

**Taste profile.** After the lint pass, `wiki/taste.md` is rewritten: the code
counts style traits, facets, animated properties, easing, background tone and
accent hues across every capture, and the model turns those counts and your
notes into a short default look and motion, each line citing its counts. The
skill starts from it when nothing else sets a style. `python -m worker.taste
--dry-run` prints the counts.

**Usage log.** When Claude builds something that takes from the wiki, the skill
records it with `python -m worker.used <capture numbers> --project … --what …`.
Lines go to `wiki/usage.md` by capture number, and the index shows how often each
topic was used, so what proves useful stands out from what was only saved.

## What it understands

| Source | How |
|---|---|
| X | fxtwitter: video, GIF or image; X Articles as text, with their key ideas; the media of a quoted post; the page a post without media links to |
| Instagram, LinkedIn | video through yt-dlp with your browser cookies (`BRAIN_COOKIES`); if yt-dlp can't get it, the video the page publishes as JSON-LD, and failing that (photos, carousels) the cover image |
| GitHub repositories | description and README through the API; as media, the first image, GIF or video in the README (badges skipped), else a screenshot of the project's homepage |
| YouTube, Vimeo, TikTok, Bluesky and every other site yt-dlp has an extractor for | the video through yt-dlp, at most 720p and 10 minutes; if it can't be downloaded, the page's thumbnail and description |
| Direct links to an image or a video | the file itself |
| Any other site | title, description and main text (trafilatura, without navigation or banners); the video or post from its JSON-LD if present, otherwise a screenshot of the rendered page (headless Chrome) plus `og:image` |

## Setup

```bash
brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama signin                 # cloud models
ollama pull gemma4:31b-cloud  # vision and writing; the only free one on the free plan
```

**Worker on GitHub Actions (recommended).** It doesn't depend on any computer.
`bin/new-wiki` sets all of this up (see Quick start); these are the steps it takes.
The workflows live in the private wiki repository; start it from
[templates/wiki-repo](templates/wiki-repo) with the wiki in `wiki/`. `capture`
processes the pending inbox when Supabase triggers it (see the Supabase inbox
below) and every 6 hours as a safety net; `lint` runs weekly. Both check out
this engine next to the wiki, call Ollama Cloud with an API key
(ollama.com/settings/keys) and commit and push the wiki.

The workflows check out this public engine by default and need no key. If you
run a private fork instead, give the wiki repository a read-only deploy key on
it:

```bash
ssh-keygen -t ed25519 -N "" -C second-brain-wiki -f engine_key
gh repo deploy-key add engine_key.pub -R <owner>/second-brain --title second-brain-wiki
gh secret set ENGINE_DEPLOY_KEY -R <owner>/second-brain-wiki < engine_key
rm engine_key engine_key.pub
```

Secrets of the wiki repository:

```bash
gh secret set OLLAMA_API_KEY -R <owner>/second-brain-wiki
gh secret set -f <file with SUPABASE_URL, SUPABASE_KEY, WORKER_TOKEN and NTFY_TOPIC> -R <owner>/second-brain-wiki
```

If the engine is another repository or branch, set the `ENGINE_REPOSITORY` and
`ENGINE_REF` variables of the wiki repository.

To have Supabase launch it right away, create a fine-grained GitHub token with
access to the wiki repository only and the *Contents: read and write*
permission, and store it and the wiki repository's name in the Supabase Vault:

```sql
select vault.create_secret('<token>', 'github_dispatch_token');
select vault.create_secret('<owner>/second-brain-wiki', 'github_dispatch_repo');
```

On the Mac you only need to pull the wiki: a LaunchAgent that runs
`git -C <wiki repository> pull --ff-only` every 15 minutes (`StartInterval`
900) keeps it current.

**All on this Mac (no Actions).** Inbox and worker together, reachable from the
iPhone on the same Wi-Fi. Create `.env` with `INBOX_TOKEN`,
`INBOX_URL=http://localhost:8000`, `POLL_INTERVAL=20` and `BRAIN_WIKI`, and start:

```bash
bin/second-brain
```

To start it at login, use a LaunchAgent that runs `/bin/sh bin/second-brain`
with `/opt/homebrew/bin` in its `PATH`. launchd doesn't inherit your shell, and
without it ffmpeg isn't found.

**The repo can't live in `~/Documents`, `~/Desktop` or `~/Downloads`:** macOS
doesn't let launchd read those folders ("Operation not permitted").

In the Shortcut, the URL is `http://<mac-name>.local:8000/capture` (the name
comes from `scutil --get LocalHostName`). The first time, macOS asks whether to
allow incoming connections to Python.

**Supabase inbox.** Capture with the laptop off or away from home. Create a free
project, apply `db/supabase.sql` and register the hashes of both tokens (the
Shortcut's and the worker's), as the file header explains:

```bash
printf %s "$INBOX_TOKEN" | shasum -a 256    # capture
printf %s "$WORKER_TOKEN" | shasum -a 256   # worker
```

With `SUPABASE_URL`, `SUPABASE_KEY` (the publishable key) and `WORKER_TOKEN` in
`.env`, the worker reads from Supabase and `bin/second-brain` stops starting the
local inbox. Supabase only stores the hashes: the tokens never leave your Mac
and iPhone. Free projects pause after a few days without activity; the
workflow's 6-hour run prevents that.

**Skill.** Link it where Claude reads skills:

```bash
ln -s ~/Developer/second-brain/skill/second-brain ~/.claude/skills/second-brain
```

## The Shortcut

A single one: Shortcuts is the same app on iOS and macOS and syncs over iCloud.
It shows up in the share sheet on the iPhone and on the Mac.

**Install it:** download
[Save to second-brain.shortcut](shortcut/Save%20to%20second-brain.shortcut) and
open it (on a Mac it then syncs to the iPhone; on an iPhone, open it from
Files). Shortcuts asks for three values: your Supabase project URL, its
publishable key and your capture token. The file holds nothing personal;
`python shortcut/build.py` generates and signs it on macOS.

When you share, it asks what caught your eye (**Pattern to reuse**, **Visual
style**, **Tool to try**, **Idea to read**, **Idea to grow** or **Just save**) and
then for an optional note. Both reach the worker as `intent: … — note`: the intent
steers the category and the note goes into the analysis. **Idea to grow** also
plants the note in [hypar](#hypar).

**To build it by hand,** or to use the local inbox instead of Supabase:

1. New shortcut → ⓘ → **Show in Share Sheet**. Receive **URLs** and **Text**
   (the LinkedIn app shares text, not a URL); if there's no input, **Stop**.
2. **Get URLs from Input** (Shortcut Input) → **Get Item from List**: First Item.
3. **Get Contents of URL**, method `POST`, JSON body with `url` = *Item from
   List* and `note` = *Ask Each Time*:
   - with Supabase: `https://<project>.supabase.co/rest/v1/rpc/capture`, header
     `apikey: <SUPABASE_KEY>` and a third field `token` = `<INBOX_TOKEN>`
     (Supabase reads `Authorization` as a JWT, so the token goes in the body);
   - with the local inbox: `http://<mac>.local:8000/capture` and header
     `Authorization: Bearer <INBOX_TOKEN>`.
4. **Get Dictionary Value** `status` from *Contents of URL*, with the variable
   type set to **Text**. **If** it **is** `queued` → **Show Notification** "✓ Sent
   to second-brain"; **Otherwise** → "✗ Couldn't send: *Contents of URL*".

In Shortcuts, clicking a variable pill and typing renames the variable. To write
text, press **Clear** first and type in the empty field.

The note is worth it: it goes into the prompt and improves the analysis a lot,
because you know what caught your eye and the model doesn't. A note can also
start with `intent: Tool to try —` (or any of the menu's intents) when you build
the Shortcut by hand.

## hypar

[hypar](https://github.com/albegosu/hypar) is a garden for your own ideas: each
one starts as a one-sentence seed and an agent challenges it. When a capture
gives you an idea, share it as **Idea to grow** and write the idea as the note.
The capture is filed as usual, and the worker then plants the note in your
hypar garden as a latent embryo, with the original link and the source note
beside it.

- **The seed is your note**, never the model's summary. Without a note nothing
  is planted, and the notification says so.
- **What goes to hypar:** the note, the post URL and the source note's GitHub
  URL. That link only opens for people who can read the wiki repository.
- **A failure doesn't lose the capture.** It is already filed; the notification
  says hypar couldn't be reached. Share it again later: hypar ignores a URL it
  already has, so nothing is planted twice.
- `--reanalyze` never plants.

To connect it, create a token in hypar under **Settings → integrations** and add
both values to the wiki repository (the capture workflow already passes them):

```bash
gh secret set HYPAR_URL -R <owner>/second-brain-wiki     # e.g. https://hypar.example.com
gh secret set HYPAR_TOKEN -R <owner>/second-brain-wiki   # hyp_…
```

A wiki repository created before this needs the two `HYPAR_*` lines of
[templates/wiki-repo/.github/workflows/capture.yml](templates/wiki-repo/.github/workflows/capture.yml)
in its own `capture.yml`.

## Phone notifications

The inbox answers instantly (`queued`), so the Shortcut can't know how the
analysis went. With `NTFY_TOPIC` set, the worker sends a push through
[ntfy](https://ntfy.sh) when each Shortcut capture is done: where it was filed
(category and topic, or a new topic) with a summary, or the error. Tapping it
opens the original. Install the ntfy app and subscribe to the topic.

The topic is the only protection, because anyone who knows it can read the
notifications. Make it long and random: `second-brain-$(openssl rand -hex 12)`.
Only the title, the summary and the URL go to ntfy.sh.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `BRAIN_VLM` | `gemma4:31b-cloud` | vision and writing model; every other cloud vision model needs a paid plan (402) |
| `BRAIN_COOKIES` | — | `firefox`, `firefox:<profile>`, `chrome` or a path to `cookies.txt` |
| `BRAIN_CHROME` | `google-chrome`, `chromium` or the macOS app | browser for page screenshots; without one, pages fall back to `og:image` |
| `GITHUB_TOKEN` | — | GitHub API rate limit for repository captures (Actions passes its own) |
| `BRAIN_WIKI` | `wiki/` in this repo | where the wiki is written: the `wiki/` folder of the wiki repository, or a copy for tests |
| `BRAIN_MEDIA` | `data/media` | downloaded media (out of git) |
| `OLLAMA_HOST` · `OLLAMA_API_KEY` | `http://localhost:11434` · — | local Ollama, or `https://ollama.com` with an API key (on Actions, with `BRAIN_VLM=gemma4:31b`) |
| `SUPABASE_URL` · `SUPABASE_KEY` · `WORKER_TOKEN` | — | Supabase inbox |
| `INBOX_TOKEN` · `INBOX_URL` | — · `http://localhost:8000` | Shortcut token · local inbox |
| `NTFY_TOPIC` | — | phone notifications |
| `HYPAR_URL` · `HYPAR_TOKEN` | — | plant **Idea to grow** notes in hypar |
| `BRAIN_GIT_SYNC` | — | `1` to commit and push the wiki automatically after each capture |
| `POLL_INTERVAL` | `60` | seconds between inbox polls |

## Known limits

**The wiki is written by gemma4.** It classifies sensibly and cites its sources,
but it can over-generalize or slip in a detail that isn't there. That's why
source notes keep what was extracted verbatim and every claim on a page points
to a source `[n]`.

**Timing can't be measured from still frames.** Steps, animated properties and
easing are reliable. Durations are omitted on purpose. When what sets a video
apart is the quality of its motion, a lot gets lost.

**Instagram and LinkedIn use your browser cookies.** That automates access to
logged-in content, against both platforms' terms. Use it only for yourself; don't
redistribute what you save. For Instagram photos and carousels only the cover
image is analyzed, at low resolution.

**Instagram from GitHub Actions.** Without cookies and from data-center IPs,
reels fail more often than from home. Instagram photos and covers and LinkedIn
posts with JSON-LD work the same, since they need no login. A network or Ollama
failure doesn't lose the capture: it's retried up to 5 times.

**Page screenshots show the first screen only,** at 1280×800 and with whatever
cookie banner the site shows. Text on pages built client-side comes from that
screenshot, not from the rendered HTML.

**The inbox doesn't validate URLs beyond their scheme.** The token is enough for
personal use, but don't expose it without rate limiting if you give it a public
domain.

## Contributing

Issues and pull requests are welcome: read [CONTRIBUTING.md](CONTRIBUTING.md)
first, and report vulnerabilities privately as [SECURITY.md](SECURITY.md)
explains. Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE). What you capture still belongs to its authors: keep your wiki
repository private.
