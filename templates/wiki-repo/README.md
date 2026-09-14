# second-brain wiki

The content of a [second-brain](https://github.com/albegosu/second-brain): the
Markdown wiki the worker writes from what you share, and the workflows that
write it.

- `wiki/`: written by the worker after each capture and by the weekly lint
  pass. Topic pages and `index.md` are regenerated, so don't edit them by hand;
  put lasting context in the capture's note.
- `.github/workflows/capture.yml`: processes the Supabase inbox.
- `.github/workflows/lint.yml`: weekly reorganization of the wiki.

**Keep this repository private.** Captures quote third-party posts and pages,
some fetched with logged-in sessions, and name their authors. The workflows run
here too because GitHub Actions logs of a public repository are public, and they
print what was captured.

Setup (deploy key, secrets, Supabase): the engine's README, section *Worker on
GitHub Actions*.
