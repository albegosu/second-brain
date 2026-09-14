# Contributing

Thanks for helping. second-brain is a small, personal-scale tool: a Shortcut, a
Supabase inbox, a worker on GitHub Actions and a Markdown wiki an agent reads.
Contributions that keep it simple and cheap to run are the most welcome.

## Before you start

- **Small fixes** (a broken extractor, a typo, a clearer prompt): open a pull
  request directly.
- **Anything bigger** (a new source, a change to the wiki layout, a new
  dependency or service): open an issue first, so we agree on the approach
  before you spend time on it. [ROADMAP.md](ROADMAP.md) lists what's planned.
- **Security issues:** don't open an issue, see [SECURITY.md](SECURITY.md).

## Development setup

```bash
brew install ffmpeg            # or your platform's package
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

The worker needs a vision model through Ollama: a local `ollama` with
`gemma4:31b-cloud`, or `OLLAMA_HOST=https://ollama.com` plus `OLLAMA_API_KEY`.
Page screenshots need Chrome or Chromium (`BRAIN_CHROME` if it isn't found).

Work on a throwaway wiki, never on your real one, and keep git sync off:

```bash
export BRAIN_WIKI=/tmp/brain-test/wiki BRAIN_MEDIA=/tmp/brain-test/media BRAIN_GIT_SYNC=0
python -m worker.run --url "https://example.com/some-page" --note "what caught my eye"
python -m worker.lint --dry-run
```

You don't need Supabase or a wiki repository to work on extraction, prompts or
the wiki structure: `--url` skips the inbox.

## How the code is organized

- `worker/pipeline.py`: fetching (per-source handlers), keyframes, palette,
  vision analysis.
- `worker/wiki.py`: source notes, topic pages, index. Code writes the structure
  (frontmatter, links, sources, index); the model only writes prose. Keep it
  that way, so a bad model answer can spoil a text but never the navigation.
- `worker/lint.py`: the weekly reorganization. The model proposes, the code
  validates; every source note must stay in exactly one topic.
- `worker/run.py`: inbox polling, ingestion, commits, notifications.
- `db/supabase.sql`: the inbox schema and functions.
- `templates/wiki-repo/`: what a user's private wiki repository starts from.
- `shortcut/`: the shareable Shortcut and its generator.
- `bin/new-wiki`: one-command setup of a user's wiki repository, secrets and
  Supabase inbox. Standard library only, since it runs before the virtualenv.

## Guidelines

- **English everywhere:** code, comments, prompts, docs and commit messages.
- **Match the surrounding code:** naming, comment density, small functions,
  standard library first. Explain *why* in comments, not *what*.
- **Validate model output in code.** When you change a prompt, also check what
  happens when the model ignores it.
- **No captured content in the repository.** No real captures as fixtures,
  screenshots of other people's posts, cookies, tokens, `.env` files, Supabase
  project refs or ntfy topics. Use your own material or synthetic examples.
- **Dependencies:** add one only when the standard library or an existing
  dependency can't reasonably do the job, and say why in the pull request.
- **Docs:** update [README.md](README.md) when behavior or settings change, and
  [ROADMAP.md](ROADMAP.md) when you complete or add an item.

## Pull requests

- Keep them focused; one change per pull request.
- Title in [Conventional Commits](https://www.conventionalcommits.org/) form:
  `feat(capture): …`, `fix(lint): …`, `docs: …`.
- Describe how you tested it: which sources or URLs, local or Actions, and for
  prompt or wiki changes a before/after excerpt of a generated page.

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
