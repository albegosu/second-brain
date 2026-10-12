"""Technical capture (verbatim code, repository facts) and the lint pass's split
of catch-all topics, on a copy of the synthetic wiki (no network, no model)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import lint
from worker import pipeline
from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"

README = """# acme-cli

A tool. Install it with `npm install -g acme-cli` and then:

```bash
acme init --template minimal
acme serve --port 3000
```

Config lives in `acme.toml`:

```toml
[server]
port = 3000
```

    $ npx acme doctor

Some prose that is not a command.
"""


class CodeSnippets(unittest.TestCase):
    def test_fenced_blocks_are_kept_verbatim(self):
        code = pipeline.code_snippets(README)
        self.assertEqual(code[0], {"lang": "bash", "code": "acme init --template minimal\nacme serve --port 3000"})
        self.assertEqual(code[1], {"lang": "toml", "code": "[server]\nport = 3000"})

    def test_command_lines_in_prose_are_collected(self):
        loose = pipeline.code_snippets(README)[-1]
        self.assertEqual(loose["lang"], "bash")
        self.assertEqual(loose["code"], "npm install -g acme-cli\nnpx acme doctor")

    def test_duplicates_and_prose_are_left_out(self):
        code = pipeline.code_snippets("Run `uvx ruff check .` now.", "Run `uvx ruff check .` now.", "plain words")
        self.assertEqual(code, [{"lang": "bash", "code": "uvx ruff check ."}])
        self.assertEqual(pipeline.code_snippets(None, "", "nothing technical here"), [])

    def test_long_blocks_are_cut_at_a_line(self):
        block = "```\n" + "\n".join(f"line {i}" for i in range(400)) + "\n```"
        code = pipeline.code_snippets(block, size=100)[0]["code"]
        self.assertTrue(code.endswith("\n…"))
        self.assertLessEqual(len(code), 102)


class RepoFacts(unittest.TestCase):
    def test_facts_from_the_api(self):
        commits = mock.Mock(status_code=200, json=lambda: [{"commit": {"committer": {"date": "2026-09-30T10:00:00Z"}}}])
        with mock.patch.object(pipeline.httpx, "get", return_value=commits) as get:
            facts = pipeline.repo_facts("https://api.github.com/repos/acme/cli",
                                        {"language": "Go", "license": {"spdx_id": "MIT"}, "archived": True,
                                         "pushed_at": "2026-10-01T00:00:00Z", "default_branch": "main",
                                         "stargazers_count": 42}, {})
        self.assertEqual(get.call_args.kwargs["params"], {"per_page": 1, "sha": "main"})
        self.assertEqual(facts, {"language": "Go", "license": "MIT", "last_commit": "2026-09-30",
                                 "archived": True, "stars": 42})

    def test_last_push_when_commits_cant_be_read(self):
        with mock.patch.object(pipeline.httpx, "get", return_value=mock.Mock(status_code=409)):
            facts = pipeline.repo_facts("https://api.github.com/repos/acme/empty",
                                        {"pushed_at": "2025-01-02T00:00:00Z", "license": None}, {})
        self.assertEqual(facts["last_commit"], "2025-01-02")
        self.assertIsNone(facts["license"])
        self.assertFalse(facts["archived"])


class SourceBody(unittest.TestCase):
    def test_repository_and_code_sections(self):
        page = {"title": "acme/cli", "description": "A tool.", "excerpt": README[:80],
                "repo": {"language": "Go", "license": "MIT", "last_commit": "2026-09-30", "archived": False, "stars": 42},
                "code": pipeline.code_snippets(README)}
        body = wiki.source_body(note="try `brew install acme`", text="A tool.", page=page,
                                patterns=[], style=None)
        self.assertIn("## Repository\n\nLanguage: Go · License: MIT · Last commit: 2026-09-30 · Archived: no · Stars: 42", body)
        self.assertIn("```bash\nbrew install acme\n```", body)
        self.assertIn("```toml\n[server]\nport = 3000\n```", body)
        # Ahead of the page excerpt, which gets trimmed first when a topic is composed.
        self.assertLess(body.index("## Code"), body.index("## Page"))

    def test_no_sections_without_code_or_repo(self):
        body = wiki.source_body(note=None, text="Nice gradient.", page=None, patterns=[], style=None)
        self.assertNotIn("## Code", body)
        self.assertNotIn("## Repository", body)


class CatchAllSplit(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sources = sorted(str(f.relative_to(self.wiki)) for f in (self.wiki / "sources").rglob("*.md"))

        def topic(sources, title="T"):
            return {"title": title, "summary": "", "category": "tools", "sources": sources, "related": []}
        self.state = {"tools/ai-tools": topic(self.sources[:8], "AI Tools"),
                      "tools/color-pickers": topic(self.sources[8:]),
                      "tools/a": topic(["sources/x/1.md"]), "tools/b": topic(["sources/x/2.md"])}

    def test_a_topic_far_above_its_category_is_a_catch_all(self):
        self.assertEqual(lint.catch_alls(self.state), ["tools/ai-tools"])
        # Visual styles gather many captures by nature.
        self.state["tools/style-x"] = self.state.pop("tools/ai-tools")
        self.assertEqual(lint.catch_alls(self.state), [])

    def test_a_small_category_has_no_catch_all(self):
        small = {k: {**t, "sources": t["sources"][:7]} for k, t in self.state.items()}
        self.assertEqual(lint.catch_alls(small), [])

    def test_the_focused_split_is_validated_and_applied(self):
        parts = {"into": [{"category": "tools", "slug": "browser-tools", "title": "Browser Tools", "summary": "s",
                           "sources": self.sources[:5]},
                          {"category": "tools", "slug": "ai-tools", "title": "AI Tools", "summary": "s",
                           "sources": self.sources[5:8]}]}
        with mock.patch.object(lint.p, "chat", return_value="{}") as chat, \
                mock.patch.object(lint.p, "parse_json", return_value=parts):
            splits = lint.split_catch_alls(self.state)
        self.assertIn("Other topics in tools:\n- tools/a: T", chat.call_args.args[1])
        after, log = lint.apply_plan(self.state, {"split": splits})
        self.assertEqual(after["tools/browser-tools"]["sources"], self.sources[:5])
        self.assertEqual(after["tools/ai-tools"]["sources"], self.sources[5:8])
        self.assertEqual(log, ["split tools/ai-tools into tools/browser-tools, tools/ai-tools"])

    def test_a_split_that_drops_a_source_is_rejected(self):
        parts = {"into": [{"category": "tools", "slug": "x", "sources": self.sources[:4]},
                          {"category": "tools", "slug": "y", "sources": self.sources[4:7]}]}
        with mock.patch.object(lint.p, "chat", return_value="{}"), \
                mock.patch.object(lint.p, "parse_json", return_value=parts):
            after, log = lint.apply_plan(self.state, {"split": lint.split_catch_alls(self.state)})
        self.assertEqual(after, lint.apply_plan(self.state, {})[0])
        self.assertEqual(log, [])

    def test_describe_lists_ideas(self):
        note = self.wiki / self.sources[0]
        meta, body = wiki.read_page(note)
        wiki.write_page(note, meta, body + "\n\n## Key ideas\n\n### Small diffs\n\nclaim\n\n## Page\n\n### Not an idea\n")
        self.assertIn("[ideas: Small diffs]", lint.describe({"tools/ai-tools": self.state["tools/ai-tools"]}))


if __name__ == "__main__":
    unittest.main()
