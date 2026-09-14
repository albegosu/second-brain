---
name: second-brain
description: The user's personal knowledge base, kept as a Markdown wiki of things they saved from X, Instagram, LinkedIn and the web. It has three categories. design covers UI patterns, interactions, motion and visual styles. features covers product functionality worth building. tools covers apps, libraries and services. Check it BEFORE designing or implementing a UI component, animation, interaction or product feature, and before choosing a tool or library, in case there is a saved reference. Also use it when asked "¿tengo algo guardado sobre…?", "busca en mi second brain", "what did I save about…", "hazlo con el estilo X", or for inspiration.
---

# Second brain

The wiki is the `wiki/` folder of the user's private wiki repository: `$BRAIN_WIKI` if set, `~/Developer/second-brain-wiki/wiki/` by default. The paths below use the default. A model writes it from captures, so treat it as references and ideas, not as specs.

A worker in GitHub Actions writes it and the computer pulls it periodically. If the very latest captures matter, pull first:

```bash
git -C ~/Developer/second-brain-wiki pull --ff-only -q
```

## How to use it

1. Read `wiki/index.md` first. For every topic it lists a one-line summary and the patterns (or, for tools, the options) the page holds, plus the latest captures. Match on pattern names, not only topic titles. Don't read whole folders.
2. Open only the matching topic pages (`wiki/<category>/<topic>.md`). Their structure is fixed:
   - `## Patterns` (or `## Options` for tools): one `### <name> [n]` block each, with **Use it when**, **How it works** (numbered steps), **Motion** and **Watch out**. One block is enough to build that pattern.
   - `## Choosing`: which pattern fits which situation, when there are several.
   - `## See also`: related topics of the same category worth opening when the task spans them. A relevant tool page won't be linked from a design page, so check the index's tools section too.
   - `## Sources`: citations like `[2]` point here.
3. Open a source note (`wiki/sources/…`) only when you need the specifics: the user's note, the measured palette, the original post text or the link to the video.
4. If the index doesn't obviously cover it, search. Everything is in English:
   ```bash
   rg -i "<keyword>" ~/Developer/second-brain-wiki/wiki
   ```
5. Say which pages or sources you used.

## When building from it

- Steps, animated properties and easing come from a vision model looking at frames. They are good starting points. Durations are usually omitted on purpose, because they cannot be measured from stills.
- Palettes in source notes are measured from pixels but include the demo's content colors. Pick the UI ones.
- Adapt to the project's own design tokens and stack. The wiki never stores code.

## Adding to it

Captures usually arrive through the share shortcut on iPhone or Mac, and GitHub Actions processes them. To file one from a session (needs the repo's `.env` and Ollama reachable):

```bash
cd ~/Developer/second-brain && BRAIN_WIKI=~/Developer/second-brain-wiki/wiki BRAIN_GIT_SYNC=1 .venv/bin/python -m worker.run --url "<url>" --note "<why it matters>"
```

- Put `style: <name>` in the note to file the capture under the design topic `style-<name>`.
- Topic pages are rewritten from their source notes whenever a capture arrives or the weekly lint pass reorganizes topics, so manual edits to a topic page don't last. Put lasting context in the capture's note instead.
- `wiki/index.md` is regenerated every time, so never edit it by hand.
- Don't commit wiki changes: the worker commits and pushes them to the wiki repository. Engine code changes (`~/Developer/second-brain` by default) are the user's to commit.
