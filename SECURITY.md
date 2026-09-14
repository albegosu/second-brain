# Security Policy

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub:
**Security → Report a vulnerability** in this repository. Include what you found,
how to reproduce it and what an attacker could do with it.

This is a personal project maintained on a best-effort basis: expect an
acknowledgement within a week. Fixes land on `main`, the only supported version.

## What's in scope

- **The Supabase inbox** (`db/supabase.sql`): row level security, the
  `SECURITY DEFINER` functions, token checks, the dispatch trigger and what it
  reads from the Vault.
- **The worker and its workflows** (`worker/`, `templates/wiki-repo/`): leaking
  secrets or captured content through logs, commits or notifications; running
  code from a captured page.
- **Handling untrusted input:** pages opened in headless Chrome, media processed
  by ffmpeg or yt-dlp, and text that ends up in model prompts (for example,
  instructions hidden in a page that change what gets written to the wiki).
- **The skill** (`skill/`): content in the wiki that could make an agent take
  actions it shouldn't.

Vulnerabilities in third-party services and tools (Supabase, GitHub, Ollama,
ntfy, yt-dlp, Chrome) should go to their maintainers; tell us too if second-brain
makes them easier to exploit.

## Keeping your own deployment safe

- Keep your wiki repository **private**: captures quote other people's content,
  and its Actions logs print what was captured.
- Tokens are compared by hash; still, rotate the capture token if your Shortcut
  leaks, and scope the GitHub dispatch token to the wiki repository only.
- Use a long random ntfy topic: anyone who knows it can read your notifications.
