# Self-hosting

How the pieces fit, how to set them up by hand, and how to run the worker on
your own computer instead. Back to the [README](../README.md).

## How it fits together

A memory for things worth keeping: interface patterns and styles, feature ideas
and tools. You share something from your phone or computer. A model analyzes it,
files it under a topic and merges it into a Markdown wiki kept in a separate
private repository. Claude then reads it through the `second-brain` skill before
designing or building something. This repository is the engine.

```
capture page ──► inbox repository (queue/) ──► GitHub Actions (worker + model) ──► wiki repository
 or Shortcut        (or Supabase inbox)
                                                     │                                       │
                                                     ▼                                  git pull on the Mac
                                             ntfy push to the phone                          ▼
                                                                                    second-brain skill
```

## Worker on GitHub Actions (recommended)

It doesn't depend on any computer. `bin/setup` sets all of this up (see
[Quick start](../README.md#quick-start)); these are the steps it takes. The
workflows live in the private wiki repository; start it from
[templates/wiki-repo](../templates/wiki-repo) with the wiki in `wiki/`.
`capture` processes the pending inbox when Supabase triggers it (see the
[Supabase inbox](#supabase-inbox) below) and every 6 hours as a safety net;
`lint` runs weekly. Both check out this engine next to the wiki, call Ollama
Cloud with an API key (ollama.com/settings/keys) and commit and push the wiki.

### A private engine

The workflows check out this public engine by default and need no key. If you
run a private fork instead, give the wiki repository a read-only deploy key on
it:

```bash
ssh-keygen -t ed25519 -N "" -C second-brain-wiki -f engine_key
gh repo deploy-key add engine_key.pub -R <owner>/second-brain --title second-brain-wiki
gh secret set ENGINE_DEPLOY_KEY -R <owner>/second-brain-wiki < engine_key
rm engine_key engine_key.pub
```

If the engine is another repository or branch, set the `ENGINE_REPOSITORY` and
`ENGINE_REF` variables of the wiki repository.

### Secrets

Secrets of the wiki repository:

```bash
gh secret set OLLAMA_API_KEY -R <owner>/second-brain-wiki
gh secret set -f <file with SUPABASE_URL, SUPABASE_KEY, WORKER_TOKEN and NTFY_TOPIC> -R <owner>/second-brain-wiki
```

Other model providers and every other variable: [Settings](reference.md#settings).

### Start right away from Supabase

To have Supabase launch it right away, create a fine-grained GitHub token with
access to the wiki repository only and the *Contents: read and write*
permission, and store it and the wiki repository's name in the Supabase Vault:

```sql
select vault.create_secret('<token>', 'github_dispatch_token');
select vault.create_secret('<owner>/second-brain-wiki', 'github_dispatch_repo');
```

### Keep the wiki current on the Mac

On the Mac you only need to pull the wiki: a LaunchAgent that runs
`git -C <wiki repository> pull --ff-only` every 15 minutes (`StartInterval`
900) keeps it current.

## Install the worker locally

Only to run the worker on your own computer: [all on this Mac](#all-on-this-mac-no-actions)
or the [command line](capture.md#command-line). With GitHub Actions you don't
need this.

```bash
brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama signin                 # cloud models
ollama pull gemma4:31b-cloud  # vision and writing; the only free one on the free plan
```

## All on this Mac (no Actions)

Inbox and worker together, reachable from the iPhone on the same Wi-Fi. Create
`.env` with `INBOX_TOKEN`, `INBOX_URL=http://localhost:8000`, `POLL_INTERVAL=20`
and `BRAIN_WIKI`, and start:

```bash
bin/second-brain
```

To file one thing without the inbox, run the worker directly: see
[Command line](capture.md#command-line).

To start it at login, use a LaunchAgent that runs `/bin/sh bin/second-brain`
with `/opt/homebrew/bin` in its `PATH`. launchd doesn't inherit your shell, and
without it ffmpeg isn't found.

**The repo can't live in `~/Documents`, `~/Desktop` or `~/Downloads`:** macOS
doesn't let launchd read those folders ("Operation not permitted").

In the Shortcut, the URL is `http://<mac-name>.local:8000/capture` (the name
comes from `scutil --get LocalHostName`). The first time, macOS asks whether to
allow incoming connections to Python. To build the Shortcut for the local
inbox, see [Build it by hand](capture.md#build-it-by-hand).

## Supabase inbox

Capture with the laptop off or away from home. Create a free project, apply
`db/supabase.sql` and register the hashes of both tokens (the Shortcut's and the
worker's), as the [file header](../db/supabase.sql) explains:

```bash
printf %s "$INBOX_TOKEN" | shasum -a 256    # capture
printf %s "$WORKER_TOKEN" | shasum -a 256   # worker
```

With `SUPABASE_URL`, `SUPABASE_KEY` (the publishable key) and `WORKER_TOKEN` in
`.env`, the worker reads from Supabase and `bin/second-brain` stops starting the
local inbox. Supabase only stores the hashes: the tokens never leave your Mac
and iPhone. Free projects pause after a few days without activity; the
workflow's 6-hour run prevents that.

## Skill

Link it where Claude reads skills:

```bash
ln -s ~/Developer/second-brain/skill/second-brain ~/.claude/skills/second-brain
```
