# What it writes for your agent

The files the worker derives from the wiki for a coding agent: the taste
profile, DESIGN.md, AGENTS.md, stack.md and the usage log. Back to the
[README](../README.md).

## Taste profile

After the [lint pass](wiki.md#lint-pass), `wiki/taste.md` is rewritten: the code
counts style traits, facets, animated properties, easing, background tone and
accent hues across every capture, and the model turns those counts and your
notes into a short default look and motion, each line citing its counts. The
skill starts from it when nothing else sets a style. `python -m worker.taste
--dry-run` prints the counts.

## DESIGN.md

Collections like getdesign.md give an agent a brand's
[DESIGN.md](https://github.com/google-labs-code/design.md) (Stripe's, Linear's);
this one is yours. After the lint pass, `wiki/DESIGN.md` holds the taste in that
format, and any style topic gets its own on demand. The code derives every token:
measured palettes become color roles (primary, secondary, tertiary, neutral,
surface, on-surface, outline), with text colors darkened or lightened along their
own hue until they reach 4.5:1; the type family category becomes an open font
(geometric sans → DM Sans, grotesk → Inter, serif → Source Serif 4, mono →
JetBrains Mono…, named as a default to swap); radius, spacing and depth become
scales and components. A model writes only the overview and the do's and don'ts,
and code drops any line with a hex code or a link; without a model a template
writes them. The file holds capture numbers but no links or post text.

- **Light and dark.** When your captures split between light and dark
  backgrounds with no clear lead, the taste comes as a pair: `wiki/DESIGN.md`
  for the more frequent tone and `wiki/DESIGN.dark.md` (or `DESIGN.light.md`)
  for the other. Both share type, shapes, spacing and motion; each has color
  roles measured on its own tone's captures.
- **Looks.** A style topic with several looks gives the dominant one, and
  `--look "<name>"` gives any other: each trait takes the value most of the
  look's captures share, and the colors come from the single capture that
  matches best, so palettes are never mixed.
- **A primary that may be a photo's.** Palettes are measured from pixels, so
  they include content colors. Accents are ranked vivid first, then clear, then
  muted or dark. When no accent is vivid, or the words the wiki uses for the look
  name other colors, the primary is marked **Low confidence** and a rule asks the
  agent to check it against the capture's frames.

```bash
python -m worker.design_md                                      # rewrite wiki/DESIGN.md (and its twin) from the taste
python -m worker.design_md --tone dark                          # print the taste's dark twin
python -m worker.design_md --style editorial --out app/DESIGN.md  # one style topic
python -m worker.design_md --style editorial --look "Night Edition"  # one of its looks
python -m worker.design_md --style editorial --dry-run          # print tokens and contrast, change nothing
python -m worker.design_md --no-model                           # template prose, no model call
```

The output passes `npx @google/design.md lint` with no errors or warnings. What
it looks like, from the synthetic test wiki: [taste](examples/DESIGN.taste.md)
and [a style](examples/DESIGN.style-paper-ink.md). The image at the top of the
README is built from the same test wiki and styled with that style's DESIGN.md:
`python docs/readme/build_flow.py`.

## AGENTS.md

The same for how you work: after the lint pass, `wiki/AGENTS.md` turns the ideas
of your `practices` topics into rules a coding agent follows, in the
[AGENTS.md](https://agents.md) format that Claude Code, Cursor and Codex read.
Code decides what goes in and how firmly:

- **Rules** are ideas two or more captures support, or that come from a capture
  that already shaped a build (the [usage log](#usage-log) below).
- **Worth trying** holds every other idea, up to three per topic. Ideas with
  something to apply and a note of yours come first, then the newest.

A model answers once per topic whether it is about writing, testing, reviewing
or shipping code, or about working with agents. The answer is saved in the
topic's frontmatter (`agents: true` or `false`), so the file stays stable, and
you can edit that field to override it. The model also words each idea as one
rule and its reason. Code checks the wording (short single lines, no links or
capture numbers) and otherwise uses the page's own words. A code block goes
along only when a cited source note recorded it verbatim. Every rule carries
its capture numbers, so a use can be logged, and a used idea becomes a rule.

```bash
python -m worker.agents_md                       # rewrite wiki/AGENTS.md and commit it
python -m worker.agents_md --dry-run             # each idea's evidence and tier, change nothing
python -m worker.agents_md --out app/AGENTS.md   # write it into a project
python -m worker.agents_md --no-model            # no topic filter, ideas in their pages' words
```

## stack.md

Before adding a dependency, an agent checks `wiki/stack.md`: the tools you
saved, grouped by the job they do (each tools topic), written by code with no
model. A tool is **used** when a capture behind it shaped a build (the usage
log), **to try** otherwise, and **stale** when its GitHub repository is
archived, gone or without a commit for a year. The repository is the one the
tool's Link points to, or the one its source note captured. Facts are read from
the GitHub API on every rewrite (the lint workflow passes its `GITHUB_TOKEN`),
and the facts recorded at capture time stand in when GitHub can't be reached.

```bash
python -m worker.stack                 # rewrite wiki/stack.md and commit it
python -m worker.stack --dry-run       # print it, change nothing
python -m worker.stack --offline       # no GitHub calls
GITHUB_TOKEN=$(gh auth token) python -m worker.stack   # locally: past 60 GitHub calls an hour
```

If GitHub refuses halfway through (a rate limit), the previous `stack.md` is
kept rather than replaced by one missing facts.

## Usage log

When Claude builds something that takes from the wiki, the skill records it with
`python -m worker.used <capture numbers> --project … --what … --ref <commit or
PR URL>`. Lines go to `wiki/usage.md` by capture number, and the index shows how
often each topic was used, so what proves useful stands out from what was only
saved. A save the agent only read isn't logged, and `--ref` links the line to
the change it shaped, so a credit can be checked by opening the diff; the index
counts those uses as verifiable.
