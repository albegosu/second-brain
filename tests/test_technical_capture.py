"""Commands, code and repository facts kept as the source gave them (no network,
no model: the APIs and the model's answers are stubbed)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import pipeline as p
from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"

README = """# Kit

![build](https://img.shields.io/badge/build-passing-green.svg)

```bash
npm install -g acme-kit
```

````markdown
Put this in AGENTS.md:
```
acme-kit check
```
````

```mermaid
graph TD; A-->B
```

```bash
npm install -g acme-kit
```
"""


class Snippets(unittest.TestCase):
    def test_fenced_blocks_of_a_readme(self):
        self.assertEqual(p.snippets(markdown=README), [
            {"lang": "bash", "code": "npm install -g acme-kit"},
            {"lang": "markdown", "code": "Put this in AGENTS.md:\n```\nacme-kit check\n```"},
        ])  # the diagram and the repeat are left out

    def test_pre_blocks_of_a_page(self):
        html = ('<p>Install:</p><pre><code class="language-ts">const ok = 1 &lt; 2;<br>'
                '<span class="k">export</span> default ok;</code></pre><pre>a</pre>')
        self.assertEqual(p.snippets(html=html), [{"lang": "ts", "code": "const ok = 1 < 2;\nexport default ok;"}])

    def test_commands_in_plain_text(self):
        text = ("Try it:\n$ npx skills add acme/kit\nnpm install -g acme\n\n"
                "npm install is slow these days.\nI use git every day\nRun `uvx acme serve --port 8000` to start.")
        self.assertEqual(p.snippets(text=text), [
            {"lang": "shell", "code": "npx skills add acme/kit\nnpm install -g acme"},
            {"lang": "shell", "code": "uvx acme serve --port 8000"},
        ])

    def test_a_long_block_is_cut_and_says_so(self):
        (snippet,) = p.snippets(markdown="```py\n" + "\n".join(f"x = {i}" for i in range(60)) + "\n```\n")
        lines = snippet["code"].splitlines()
        self.assertEqual((len(lines), lines[-2], lines[-1]), (p.SNIPPET_LINES + 1, "x = 39", "…"))

    def test_at_most_a_few(self):
        markdown = "".join(f"```sh\necho {i}\n```\n" for i in range(10))
        self.assertEqual(len(p.snippets(markdown=markdown)), p.SNIPPETS)


class Response:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


REPO = {"full_name": "someone/kit", "owner": {"login": "someone"}, "description": "A kit", "default_branch": "main",
        "language": "TypeScript", "license": {"spdx_id": "MIT", "name": "MIT License"}, "archived": True,
        "pushed_at": "2026-09-30T10:00:00Z"}


class RepositoryFacts(unittest.TestCase):
    def fetch(self, commits, repo=REPO):
        def get(url, **kwargs):
            if url.endswith("/someone/kit"):
                return Response(200, repo)
            if url.endswith("/commits"):
                self.assertEqual(kwargs["params"], {"per_page": 1, "sha": "main"})
                return commits
            return Response(200, text=README)
        with mock.patch.object(p.httpx, "get", side_effect=get), mock.patch.object(p, "download_media"):
            return p.fetch_github("https://github.com/someone/kit", 7)

    def test_language_license_last_commit_and_archived(self):
        result = self.fetch(Response(200, [{"commit": {"committer": {"date": "2026-08-01T09:00:00Z"}}}]))
        repo = result["repo"]
        self.assertEqual({k: v for k, v in repo.items() if k != "checked"},
                         {"name": "someone/kit", "language": "TypeScript", "license": "MIT",
                          "last_commit": "2026-08-01", "archived": True})
        self.assertRegex(repo["checked"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(result["code"][0], {"lang": "bash", "code": "npm install -g acme-kit"})

    def test_last_push_when_commits_cant_be_listed(self):
        self.assertEqual(self.fetch(Response(409, {"message": "empty"}))["repo"]["last_commit"], "2026-09-30")

    def test_licenses(self):
        cases = {None: None, "NOASSERTION": "Other License", "Apache-2.0": "Apache-2.0"}
        for spdx, expected in cases.items():
            repo = {**REPO, "license": {"spdx_id": spdx, "name": "Other License"} if spdx else None}
            with self.subTest(spdx):
                self.assertEqual(self.fetch(Response(500), repo)["repo"]["license"], expected)

    def test_one_line(self):
        self.assertEqual(wiki.repo_line({"name": "a/b", "language": "Go", "license": None, "last_commit": "2026-01-02",
                                         "archived": True, "checked": "2026-10-12"}),
                         "a/b · Go · no license found · last commit 2026-01-02 · archived (checked 2026-10-12)")


class SourceNote(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_code_goes_verbatim_before_the_style(self):
        body = wiki.source_body(note=None, text=None, page=None, patterns=[], style={"description": "Dark."},
                                code=[{"lang": "markdown", "code": "```\nx\n```"}, {"lang": "", "code": "a  b"}],
                                repo={"name": "a/b", "license": "MIT"})
        self.assertTrue(body.startswith("## Repository\n\na/b · MIT license\n\n## Code\n"))
        self.assertIn("````markdown\n```\nx\n```\n````", body)  # a longer fence around a fence
        self.assertIn("```\na  b\n```", body)
        self.assertLess(body.index("## Code"), body.index("## Visual style"))

    def test_filed_with_the_repository_and_the_posts_commands_first(self):
        media = {"kind": "text", "text": "Ship it with\n$ npx acme-kit init",
                 "page": {"title": "someone/kit", "excerpt": "A kit."},
                 "code": [{"lang": "bash", "code": "npm install -g acme-kit"}],
                 "repo": {"name": "someone/kit", "language": "TypeScript", "license": "MIT",
                          "last_commit": "2026-08-01", "archived": False, "checked": "2026-10-12"}}
        with mock.patch.object(wiki, "classify", return_value={"category": "tools", "topic": "color-pickers",
                                                               "title": "Kit", "summary": "A kit."}), \
                mock.patch.object(wiki, "compose", return_value="Page."):
            entry = wiki.file_capture(cid=40, captured="2026-10-12", url="https://github.com/someone/kit",
                                      source="github", media=media, note=None, patterns=[], style=None)
        meta, body = wiki.read_page(self.wiki / entry["source"])
        self.assertEqual(meta["repo"], media["repo"])
        self.assertIn("## Repository\n\nsomeone/kit · TypeScript · MIT license · last commit 2026-08-01", body)
        self.assertLess(body.index("npx acme-kit init"), body.index("npm install -g acme-kit"))
        self.assertNotIn("repo", wiki.read_page(next(self.wiki.rglob("0009-*.md")))[0])  # only where there is one

    def test_the_topic_page_keeps_code_untouched(self):
        code = "### Rules\n**Notes:** none\n## Sources\nkeep this"
        answer = ("```markdown\nKits that check a repository before an agent works on it, "
                  "so the agent starts from rules it can follow and a command that verifies them.\n\n## Options\n\n### Kit [1]\n**What it does:** Checks a repo.\n"
                  f"**Try it:**\n```markdown\n{code}\n```\n**Notes:** none\n```")
        meta = wiki.read_page(self.wiki / "tools/color-pickers.md")[0]
        with mock.patch.object(wiki.p, "chat", return_value=answer):
            body = wiki.compose("tools/color-pickers", meta)
        self.assertIn(f"```markdown\n{code}\n```", body)  # inside code, nothing is "fixed"
        self.assertTrue(body.endswith("```"))  # the block's closing fence survives the unwrapping
        self.assertNotIn("**Notes:** none\n```", body)  # outside code, the empty field goes
        self.assertIn("\n\n**What it does:**", body)
        self.assertEqual(wiki.pattern_names(body), ["Kit"])
        self.assertEqual(wiki.section_label(body), "Options")
        self.assertEqual(wiki.strip_generated(body + "\n\n## Sources\n\n1. x"), body)


class Unfence(unittest.TestCase):
    def test_only_a_wrapper_goes(self):
        self.assertEqual(p.unfence('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(p.unfence("Text.\n\n```bash\nnpx kit\n```"), "Text.\n\n```bash\nnpx kit\n```")
        self.assertEqual(p.unfence("```markdown\nText.\n```bash\nnpx kit\n```\n```"), "Text.\n```bash\nnpx kit\n```")


if __name__ == "__main__":
    unittest.main()
