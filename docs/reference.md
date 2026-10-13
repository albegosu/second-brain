# Reference

Every setting the engine reads, and the full list of known limits. Back to the
[README](../README.md).

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
| `BRAIN_PROVIDER` · `BRAIN_API_KEY` · `BRAIN_API_BASE` | `ollama` · — · per provider | another model provider through its OpenAI-compatible API: `openai`, `anthropic`, `gemini`, `openrouter`, or `openai-compatible` with `BRAIN_API_BASE`. `BRAIN_VLM` defaults to `gpt-4.1-mini`, `claude-haiku-4-5-20251001`, `gemini-2.5-flash` and `google/gemini-2.5-flash`. On Actions: repository variable `BRAIN_PROVIDER` (and optionally `BRAIN_VLM`), secret `BRAIN_API_KEY` |
| `SUPABASE_URL` · `SUPABASE_KEY` · `WORKER_TOKEN` | — | Supabase inbox |
| `INBOX_TOKEN` · `INBOX_URL` | — · `http://localhost:8000` | Shortcut token · local inbox |
| `NTFY_TOPIC` | — | phone notifications |
| `HYPAR_URL` · `HYPAR_TOKEN` | — | plant **Idea to grow** notes in hypar |
| `BRAIN_SPEECH` · `BRAIN_SPEECH_MODEL` | on · `base` | `off` to skip transcribing speech in videos · the [faster-whisper](https://github.com/SYSTRAN/faster-whisper) model (`small` is better and slower). On Actions: repository variables |
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
