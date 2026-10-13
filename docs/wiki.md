# The wiki

How the wiki is laid out, what each page holds and how it stays tidy. Back to
the [README](../README.md).

It lives in its own private repository (`second-brain-wiki`), together with the
workflows that write it; this repository only holds the engine. Captures quote
third-party posts, so that content stays private even if the engine is
published, and the worker runs there because GitHub Actions logs of a public
repository are public and print what was captured. Point `BRAIN_WIKI` at its
`wiki/` folder.

## Layout

```
wiki/
  index.md                      map of topics; written by code
  taste.md                      recurring choices across captures; weekly
  DESIGN.md                     the same taste as design tokens; weekly
  DESIGN.dark.md                its dark twin, when the captures split (or .light)
  AGENTS.md                     the practices as rules for a coding agent; weekly
  stack.md                      the saved tools by job: used, to try or stale; weekly
  usage.md                      what was built from which captures
  design/ features/ tools/      one page per topic
  practices/
  sources/2026-09/0007-….md     one note per capture
  sources/2026-09/0007-….jpg    what it looked like: up to 4 frames in time order
```

`taste.md`, `DESIGN.md`, `AGENTS.md`, `stack.md` and `usage.md` are described in
[outputs.md](outputs.md).

## Categories

- `design`: how an interface looks and moves. Topics that collect a look are
  named `style-*`.
- `features`: what a product does for its user.
- `tools`: tools, libraries and services.
- `practices`: how to work (engineering practices, workflows with agents,
  lessons from articles).

The facets the model tags a capture with come from a closed vocabulary:
[taxonomy.md](taxonomy.md).

## Source notes

Source notes (`sources/`) are written by code from what was extracted, with no
reinterpretation. They hold your note, the patterns the model saw, the key ideas
of an article or long text, the style with its pixel-measured palette, the post
or page text, and a link to the original. Commands, code and config (a README's
fenced blocks, a page's `<pre>` blocks, shell commands in your note, a post or
its page) are kept verbatim under **Code**, up to six blocks. A GitHub
repository also gets its language, license, last commit date, archived status
and stars, in the note's frontmatter (`repo`) and under **Repository**.

## Topic pages

The model picks the topic (reusing an existing one if it fits) and rewrites the
page from all of its source notes, citing them as `[n]`. Pages are built for an
agent about to implement something, with one block per item: patterns (**Use it
when**, **How it works**, **Motion**, **Watch out**), styles as a DESIGN.md-like
sheet (**Tokens**, **Composition**, **Do**, **Don't**), tools (**What it does**,
**Use it when**, **Try it**, **Link**, **Notes**) or ideas (**Claim**, **Why it
matters**, **How to apply**). Commands and code are copied from the notes'
**Code**, never paraphrased. A "Choosing" section follows when there are
several, and "See also" links. The frontmatter, "See also", the sources list,
the links a tool can use and the index are written by code, so a bad answer can
at most spoil a text, never the navigation.

A note with `style: name` (or `estilo: name`) files the capture under
`design/style-name`, to collect a look across several captures.

## How it's written

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

## Re-analysis

After changing the analysis, this runs the model again over every capture the
current version hasn't analyzed (source notes record it as `analyzed`) and
rewrites the wiki. A capture now filed under another topic leaves its old page
rewritten from the sources that remain, or deleted if none do. If it stops on a
quota or network error, run it again and it resumes:

```bash
python -m worker.run --reanalyze
```

Topic pages are regenerated from their sources, so manual edits to them don't
last; put lasting context in the capture's note.

## Lint pass

Once a week, the wiki repository's `lint` workflow asks the model to review the
whole wiki: merge duplicate topics, split catch-alls, move misfiled captures and
relate topics. The code only applies proposals that keep every source note in
exactly one topic and only links topics within the same category (across
categories the model pairs things that merely share an area), rewrites the
affected pages and commits the result.

### Catch-alls

Catch-alls are found by counting, not by the model, which never proposed
splitting them while reviewing the whole wiki and would sooner merge one into an
even larger topic: a topic with 8 or more sources that holds a quarter of its
category, or any topic with 15 or more, but never a `style-*` topic (its size is
a look you keep saving). They are split first, so the plan reviews the finer
topics. For each one the model gets only that topic's notes, numbered, and
groups them into specific topics or into existing topics of the same category; a
note with no pair gets a topic of its own rather than one that doesn't fit. The
code keeps a note listed twice in its first group, gives back the notes of a
group with a vague name (`misc-…`, `other-…`), and leaves whatever no group took
in the original topic.

### Run it locally

```bash
python -m worker.lint --dry-run        # print the validated plan, change nothing
python -m worker.lint                  # apply it
python -m worker.lint --recompose-all  # also rewrite every page from its sources
python -m worker.lint --no-plan        # skip the model's plan, only apply the rules
```

After the lint pass, `taste.md`, `DESIGN.md`, `AGENTS.md` and `stack.md` are
rewritten: see [outputs.md](outputs.md).
