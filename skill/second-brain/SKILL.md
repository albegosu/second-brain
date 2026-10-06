---
name: second-brain
description: The user's personal knowledge base, kept as a Markdown wiki of things they saved from X, Instagram, LinkedIn and the web. It has four categories. design covers UI patterns, interactions, motion and visual styles. features covers product functionality worth building. tools covers apps, libraries and services. practices covers how to work: engineering practices, workflows with AI agents and lessons from articles. It also turns the user's taste, or one saved style, into a DESIGN.md to build UI from. Check it BEFORE designing or implementing a UI component, animation, interaction or product feature, before choosing a tool or library, and when deciding how to approach agent or engineering work, in case there is a saved reference. Also use it when asked "¿tengo algo guardado sobre…?", "busca en mi second brain", "what did I save about…", "hazlo con el estilo X", or for inspiration.
---

# Second brain

The wiki is the `wiki/` folder of the user's private wiki repository: `$BRAIN_WIKI` if set, `~/Developer/second-brain-wiki/wiki/` by default. The paths below use the default. A model writes it from captures, so treat it as references and ideas, not as specs.

A worker in GitHub Actions writes it and the computer pulls it periodically. If the very latest captures matter, pull first:

```bash
git -C ~/Developer/second-brain-wiki pull --ff-only -q
```

## How to use it

1. Read `wiki/index.md` first. For every topic it lists a one-line summary, the blocks the page holds (patterns, styles, options or ideas) and how often it was used in a build, plus the latest captures. Match on block names, not only topic titles. Don't read whole folders.
2. Open only the matching topic pages (`wiki/<category>/<topic>.md`). Their structure is fixed, one `### <name> [n]` block per item:
   - `## Patterns` (design, features): **Use it when**, **How it works** (numbered steps), **Motion** and **Watch out**. One block is enough to build that pattern.
   - `## Styles` (design topics named `style-*` or made of looks): **Tokens** (measured palette, type family, radius, spacing, depth, motion feel), **Composition**, **Do**, **Don't**, **Use it for**. To build with one, generate its DESIGN.md (see "When building from it").
   - `## Options` (tools): **What it does**, **Use it when**, **Link** (only URLs found in the sources) and **Notes**.
   - `## Ideas` (practices): **Claim**, **Why it matters**, **How to apply**, **Watch out**.
   - `## Choosing`: which one fits which situation, when there are several.
   - `## See also`: related topics of the same category worth opening when the task spans them. A relevant tool page won't be linked from a design page, so check the index's tools section too.
   - `## Sources`: citations like `[2]` point here.
3. Open a source note (`wiki/sources/…`) only when you need the specifics: the user's note, the measured palette, the original post text or the link to the video.
   - Visual captures keep a `.jpg` next to their note (linked as `frames` in the topic's sources list): up to four frames in time order, left to right and top to bottom, or the image itself. Before building a look, a layout or an interaction from the wiki, open that image with the Read tool and look at it. The text describes the reference; the image is the reference.
4. If the index doesn't obviously cover it, search. Everything is in English:
   ```bash
   rg -i "<keyword>" ~/Developer/second-brain-wiki/wiki
   ```
5. Say which pages or sources you used.

## When building from it

- Designing something with no style given, neither by the user nor by the project's design system? Start from `wiki/DESIGN.md` (the weekly lint pass writes it; until then, `wiki/taste.md`): the same taste as `wiki/taste.md`, written as a [DESIGN.md](https://github.com/google-labs-code/design.md) (color roles, type scale, radius, spacing and components as tokens, then rules). Follow its tokens rather than inventing values; code derived them from measured palettes and already checked text contrast (4.5:1). `wiki/taste.md` has the counts behind them; treat anything marked "no clear lead" or "Not enough evidence" as a question to ask. An explicit request or the project's own tokens always win over both.
- Building with a saved style ("hazlo con el estilo X", or a `style-*` topic fits the task)? Generate that topic's DESIGN.md and build from it, then look at the topic's frames: the tokens set colors and scales, the image shows the composition.
  ```bash
  cd ~/Developer/second-brain && BRAIN_WIKI=~/Developer/second-brain-wiki/wiki .venv/bin/python -m worker.design_md --style <slug> --out <project>/DESIGN.md
  ```
  The slug is the topic's file name (`style-editorial`, or just `editorial`); without `--out` it prints. A topic with several looks gives its dominant one and names the others. A model writes only the overview and rules; `--no-model` skips it (a template writes them) when Ollama isn't reachable. The file carries capture numbers for the usage log but no links or post text; it is still derived from private captures, so ask before committing it to a public repository, and never overwrite a DESIGN.md the project already has.
- Steps, animated properties and easing come from a vision model looking at frames. They are good starting points. Durations are usually omitted on purpose, because they cannot be measured from stills.
- Palettes in source notes are measured from pixels but include the demo's content colors. Pick the UI ones.
- Adapt to the project's own design tokens and stack. The wiki never stores code.
- When something you built actually takes from captures, record it once, at the end, with their capture numbers (the `0007` in `sources/2026-09/0007-….md`). It shows the user which saves turn out useful. A save you only read or looked at is not logged, even if it informed your thinking.
  ```bash
  cd ~/Developer/second-brain && BRAIN_WIKI=~/Developer/second-brain-wiki/wiki BRAIN_GIT_SYNC=1 .venv/bin/python -m worker.used 7 21 --project "<repository or product>" --what "<what was taken, in one line>" --ref "<commit or pull request URL>"
  ```
  - Whenever the work lands as a commit or a pull request, pass its URL as `--ref`, so the credit can be checked by opening the diff; the index counts those uses as verifiable. Record after pushing, once the URL exists. Leave `--ref` out only when nothing was committed.
  - In a private repository you may also list the captures a change takes from (numbers and topic names) in its PR description. Never in a public repository: they come from the user's private wiki.

## Adding to it

Captures usually arrive through the share shortcut on iPhone or Mac, and GitHub Actions processes them. To file one from a session (needs the repo's `.env` and Ollama reachable):

```bash
cd ~/Developer/second-brain && BRAIN_WIKI=~/Developer/second-brain-wiki/wiki BRAIN_GIT_SYNC=1 .venv/bin/python -m worker.run --url "<url>" --note "<why it matters>"
```

- Put `style: <name>` in the note to file the capture under the design topic `style-<name>`.
- Topic pages are rewritten from their source notes whenever a capture arrives or the weekly lint pass reorganizes topics, so manual edits to a topic page don't last. Put lasting context in the capture's note instead.
- `wiki/index.md`, `wiki/taste.md`, `wiki/DESIGN.md` and `wiki/usage.md` are written by code, so never edit them by hand.
- Don't commit wiki changes: the worker commits and pushes them to the wiki repository. Engine code changes (`~/Developer/second-brain` by default) are the user's to commit.
