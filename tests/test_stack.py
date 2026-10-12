"""stack.md: the saved tools by job, on a throwaway wiki (no network: GitHub is stubbed)."""
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import httpx

from worker import pipeline as p
from worker import stack
from worker import used
from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"
TODAY = date.today().isoformat()
RECENT = (date.today() - timedelta(days=10)).isoformat()

AGENTS = """Tools that run coding agents.

## Options

### Agent CLI [1]

**What it does:** Runs agents from the terminal. It also does more.

### Old Lib [2]

**What it does:** Does old things.

**Link:** https://github.com/acme/old-lib

### Post Tool [2]

**What it does:** Seen in a post.

**Link:** https://x.com/someone/status/1

### Gone Tool [3]

**What it does:** Was here.

**Link:** https://github.com/acme/gone.

### Web App [3]

**What it does:** An app.

**Link:** https://webapp.example
"""

FACTS = {"acme/agent": {"name": "acme/agent", "language": "Python", "license": "MIT", "last_commit": RECENT,
                        "archived": False, "stars": 5, "checked": TODAY},
         "acme/old-lib": {"name": "acme/old-lib", "language": "Go", "license": None, "last_commit": "2024-01-01",
                          "archived": False, "stars": 1, "checked": TODAY},
         "acme/gone": None}


class Stack(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)
        recorded = {**FACTS["acme/agent"], "last_commit": "2026-01-01", "checked": "2026-02-01"}
        notes = {60: ("https://github.com/acme/agent", {"repo": recorded}),
                 61: ("https://x.com/someone/status/1", {}), 62: ("https://webapp.example", {})}
        rels = []
        for n, (url, extra) in notes.items():
            rels.append(f"sources/2026-02/{n:04d}-tool-{n}.md")
            wiki.write_page(self.wiki / rels[-1], {"title": f"Tool {n}", "url": url, "capture": n, **extra}, "# Tool")
        wiki.write_page(self.wiki / "tools/coding-agents.md", {"title": "Coding Agents", "category": "tools",
                                                               "summary": "Agents that write code.", "sources": rels},
                        AGENTS)
        used.record([60], "acme-web", "agent setup")

    def github(self, names=None):
        def facts(name):
            if names is not None:
                names.append(name)
            return FACTS[name]
        return mock.patch.object(stack.p, "github_facts", side_effect=facts)

    def test_tools_and_their_repositories(self):
        items = {i["name"]: i for i in stack.tools()}
        self.assertEqual({k: i["repo"] for k, i in items.items()},
                         {"Palette Picker": None, "Agent CLI": "acme/agent", "Old Lib": "acme/old-lib",
                          "Post Tool": None, "Gone Tool": "acme/gone", "Web App": None})
        self.assertIsNone(items["Post Tool"]["link"])  # the post it was seen in is not the tool
        self.assertEqual(items["Web App"]["link"], "https://webapp.example")
        self.assertEqual(items["Agent CLI"]["what"], "Runs agents from the terminal.")
        self.assertEqual(items["Agent CLI"]["recorded"]["checked"], "2026-02-01")
        self.assertEqual([u["project"] for u in items["Agent CLI"]["uses"]], ["acme-web"])
        self.assertEqual(items["Old Lib"]["uses"], [])

    def test_the_map(self):
        with self.github():
            text, refused = stack.generate()
        self.assertFalse(refused)
        self.assertIn(f"Repository facts as of {TODAY}.", text)
        self.assertIn(f"## Used in builds\n\n- **Agent CLI** (Coding Agents): Used 1×, last in acme-web on {TODAY}. "
                      "(#60)", text)
        job = text.split("## Coding Agents\n\n", 1)[1].split("\n## ", 1)[0]
        self.assertTrue(job.startswith("[Topic page](tools/coding-agents.md): Agents that write code."))
        self.assertEqual([l.split("**")[1] for l in job.splitlines() if l.startswith("- ")],
                         ["Agent CLI", "Post Tool", "Web App", "Old Lib", "Gone Tool"])  # used, to try, stale
        self.assertIn(f"[acme/agent: Python, MIT license, last commit {RECENT}](https://github.com/acme/agent) (#60)", job)
        self.assertIn("- **Web App** — An app. To try. <https://webapp.example> (#62)", job)
        self.assertIn("- **Post Tool** — Seen in a post. To try. (#61)", job)
        self.assertIn("Stale: no commit since 2024-01-01. [acme/old-lib: Go, no license found, last commit 2024-01-01]", job)
        self.assertIn("Stale: repository gone. [acme/gone: gone]", job)
        self.assertIn("## Stale\n\nSaved, but not worth a new dependency:\n\n- **Old Lib** (Coding Agents): no commit "
                      "since 2024-01-01\n- **Gone Tool** (Coding Agents): repository gone", text)
        self.assertIn("## Color Pickers", text)  # jobs in title order
        self.assertLess(text.index("## Coding Agents"), text.index("## Color Pickers"))

    def test_without_github_the_recorded_facts_stand_in(self):
        names = []
        limit = httpx.HTTPStatusError("rate limit", request=httpx.Request("GET", "https://api.github.com"),
                                      response=httpx.Response(403))
        with mock.patch.object(stack.p, "github_facts", side_effect=lambda n: names.append(n) or (_ for _ in ()).throw(limit)), \
                mock.patch("sys.stderr"):
            text, refused = stack.generate()
        self.assertTrue(refused)
        self.assertEqual(names, ["acme/agent"])  # one refusal and it stops asking
        self.assertIn("[acme/agent: Python, MIT license, last commit 2026-01-01, checked 2026-02-01]", text)
        self.assertIn("[acme/old-lib](https://github.com/acme/old-lib)", text)  # nothing known: just the name
        self.assertNotIn("## Stale", text)
        with self.github(names := []):
            self.assertFalse(stack.generate(online=False)[1])  # offline by choice is not a refusal
        self.assertEqual(names, [])

    def test_a_refusal_keeps_the_previous_file(self):
        limit = httpx.HTTPStatusError("rate limit", request=httpx.Request("GET", "https://api.github.com"),
                                      response=httpx.Response(403))
        with mock.patch.object(stack.p, "github_facts", side_effect=limit), mock.patch("sys.stderr"):
            self.assertTrue(stack.build())  # nothing to keep: the partial file is better than none
            (self.wiki / stack.PATH).write_text("last week's map\n")
            self.assertFalse(stack.build())
        self.assertEqual((self.wiki / stack.PATH).read_text(), "last week's map\n")

    def test_build_links_it(self):
        with self.github():
            self.assertTrue(stack.build())
        wiki.build_index()
        self.assertIn("[stack.md](stack.md) maps the saved tools by job", (self.wiki / "index.md").read_text())
        for page in (self.wiki / "tools").glob("*.md"):
            page.unlink()
        self.assertFalse(stack.build(online=False))
        self.assertFalse((self.wiki / stack.PATH).exists())


class GitHub(unittest.TestCase):
    def test_names(self):
        cases = {"https://github.com/a/b": "a/b", "https://www.github.com/a/b.git": "a/b",
                 "https://github.com/a/b/tree/main/x": "a/b", "https://github.com/orgs/a": None,
                 "https://github.com/a": None, "https://gitlab.com/a/b": None, None: None, "not a url": None}
        for url, name in cases.items():
            with self.subTest(url):
                self.assertEqual(p.github_name(url), name)

    def test_facts_by_name(self):
        repo = {"full_name": "acme/kit", "language": "Go", "license": None, "archived": False,
                "pushed_at": "2026-09-01T00:00:00Z", "default_branch": "main", "stargazers_count": 3}
        responses = {"https://api.github.com/repos/acme/kit": httpx.Response(200, json=repo),
                     "https://api.github.com/repos/acme/kit/commits": httpx.Response(500),
                     "https://api.github.com/repos/acme/gone": httpx.Response(404),
                     "https://api.github.com/repos/acme/limited": httpx.Response(403)}

        def get(url, **kwargs):
            r = responses[url]
            r.request = httpx.Request("GET", url)
            return r
        with mock.patch.object(p.httpx, "get", side_effect=get):
            facts = p.github_facts("acme/kit")
            self.assertEqual((facts["name"], facts["last_commit"], facts["stars"]), ("acme/kit", "2026-09-01", 3))
            self.assertIsNone(p.github_facts("acme/gone"))
            with self.assertRaises(httpx.HTTPStatusError):
                p.github_facts("acme/limited")


if __name__ == "__main__":
    unittest.main()
