# Roadmap

Where second-brain goes next. Each item says what it is, why it matters and,
when it comes from another product, where the idea comes from (see the research
notes in [PRODUCT.md](PRODUCT.md#closest-alternatives)). Order within a section
is rough priority.

## Capture: understand anything you share

- ~~**Any URL, robustly.**~~ Done: main-text extraction with trafilatura, a
  headless Chrome screenshot of every page next to `og:image`, GitHub repositories
  through the API (README text and demo media), video sites through yt-dlp, and
  direct image or video links. Still open: text from the rendered HTML of
  client-side pages, and scrolling past the first screen.
- ~~**X, completely.**~~ Done: X Articles are read as text, a post without media
  uses its quoted post's media or the page it links to, and a capture with
  nothing to read fails and asks for a note instead of being guessed.
- **Images shared directly.** Photos and screenshots from the share sheet, not
  only links: upload from the Shortcut to storage, run OCR plus the vision
  analysis, and file them like any other capture.
  *Inspired by mymind and Karakeep.*
- **Real DOM and CSS for web UI.** For a live web page, capture the actual
  elements and computed styles instead of a screenshot, so style notes carry
  exact colors, fonts, radii and spacing rather than estimates.
  *Inspired by Stele.*
- **Audio transcription.** Many videos explain the idea out loud. Transcribe
  speech and feed it to the analysis next to the frames, so spoken context isn't
  lost.
  *Inspired by Fabric and ReelRecall.*
- ~~**Every image of a carousel,** not just the cover.~~ Done: an X post whose
  media are all photos, or an Instagram post yt-dlp reads as a playlist, downloads
  every image (up to twelve) into `extra`, so the analysis and the contact sheet
  see the whole set. A video, or a post that mixes video and photos, keeps the
  first item as before.
- **Reliable Instagram reels from GitHub Actions,** where there are no browser
  cookies and data-center IPs get blocked more often.

## Wiki: organized for an agent to use

- ~~**Lint pass.**~~ Done: `worker/lint.py`, weekly on GitHub Actions. Merges
  duplicate topics, splits catch-alls, moves misfiled captures, adds "See also"
  links and reports contradictions in the commit message.
  *Inspired by Karpathy's LLM wiki pattern.*
- ~~**Style topics as `DESIGN.md`.**~~ Done: design topics made of looks (or
  named `style-*`) are written as a `## Styles` sheet with tokens (measured
  palette, type, radius, spacing, depth, motion), composition and do/don't.
  *Inspired by Refero Styles.*
- ~~**Ideas from what you read.**~~ Done: a `practices` category; articles and
  long texts get their key ideas extracted, and topic pages list them with claim,
  why and how to apply.
- ~~**See the reference.**~~ Done: each visual capture keeps a small contact sheet
  (up to four frames in time order, or the image) next to its note, and the skill
  tells Claude to look at it before building.
- ~~**Taste profile.**~~ Done: `worker/taste.py`, after each lint pass. Counts by
  code, a default look and motion written from them.
- ~~**Usage log.**~~ Done: `worker/used.py` records which captures shaped a build;
  the index shows uses per topic.
- **Topic hierarchy.** When a category grows, group topics into clusters and
  subtopics so the index stays scannable in one read.
  *Inspired by ContextBolt's topic clusters.*
- **Answers filed back.** When Claude answers a question from the wiki, let it
  save the synthesis as a page, so exploration compounds instead of evaporating.
  *Inspired by Karpathy's LLM wiki pattern.*
- **Normalized tags.** Map free-form tags onto a controlled set so they work as
  filters, the way facets already do.
- ~~**Implementation-oriented sections.**~~ Done: pages are rewritten from their
  sources as one block per pattern (use it when, steps, motion, pitfalls), a
  "Choosing" section, and an index that lists every pattern.

## hypar: from references to your own ideas

[hypar](https://github.com/albegosu/hypar) grows your own ideas; second-brain
keeps what others made. The bridge runs from the wiki repository, which holds
every credential, so the deployed hypar never reads the private wiki. The two
projects are developed apart; only what the bridge needs is synchronized, in the
[Lab roadmap](https://github.com/users/albegosu/projects/5) cards titled
`Loop — …`.

- ~~**Idea to grow.**~~ Done: a Shortcut intent that plants the note as a latent
  embryo through a per-user hypar token, with the original and the source note
  beside it.
- ~~**What sparked the idea.**~~ Done: a planted embryo carries the capture's
  essence (title, summary, what it shows, key ideas, visual style), so hypar's
  agent knows what "this" is.
- **References as contrast.** Phase 1 done: `index.md` (topic and pattern names,
  no quoted posts) reaches hypar after each capture and lint pass. Next, hypar's
  agent uses it to press on a growing idea
  with what you already saved. Only while probing and opening paths, never when
  the problem is still being defined. An experiment in hypar first.
- **Fossils as practices.** Pull hypar's fossils and mature embryos into the
  `practices` category, so the reason an idea died reaches the coding agent
  before it builds the same thing again. Needs text-only captures.

## Agent access: beyond the skill

- **Curated references as a fallback.** When the wiki has nothing on a subject,
  the skill looks it up in curated libraries and says so, keeping your own saves
  first.
  *Mobbin MCP and Refero MCP.*
- **MCP server over the wiki.** Search, recent captures and topic lookup for
  clients that don't load skills (Cursor, ChatGPT, Claude Desktop).
  *Inspired by ContextBolt, Karakeep and the Readwise MCP.*
- **Semantic search, only if needed.** At personal scale the index plus the
  context window is enough; add embeddings only when the index stops fitting.
  *Karpathy's LLM wiki pattern.*

## Open-source the engine

The code can be public; the wiki can't. Captures quote posts and pages (some
fetched with logged-in Instagram and LinkedIn sessions) and name their authors,
and the worker commits them without review, so publishing the current repo would
redistribute third-party content. Secrets are not the problem: none appear in the
history, and the Supabase design only stores token hashes.

- ~~**Split content from code.**~~ Done: `wiki/` lives in the private
  `second-brain-wiki` repository, and the workflows run there too, checking out
  the engine, because Actions logs of a public repository are public and print
  what was captured. The Mac pulls that repository.
- ~~**Publish the engine as a new repository with fresh history.**~~ Done: the
  old history, which contains the wiki, stays in an archived private repository.
- ~~**Remove personal details.**~~ Done: a neutral skill description, and the
  wiki repository the Supabase trigger dispatches to comes from the Vault
  instead of `db/supabase.sql`.
- ~~**Make it installable by someone else.**~~ Done: `bin/new-wiki` creates the
  private wiki repository, its secrets, the Supabase inbox and the local
  settings in one command, the README opens with a quick start, and the
  Shortcut ships as a signed file that asks for its settings on import.
- ~~**Review before publishing.**~~ Done: secrets and personal data scan of the
  published tree, MIT license.

## Operations

- **Extractor test suite** with recorded fixtures (X, Instagram, LinkedIn, plain
  pages), so platform changes show up as failing tests instead of failed captures.
- **Weekly digest** through ntfy: what was saved, which topics grew, what failed.
- **Quota awareness** for the Ollama Cloud free plan: back off and retry instead
  of failing when limits are hit.
- **Retry visibility:** a way to see and re-run captures that exhausted their
  retries.
