"""The practices as an AGENTS.md, on a throwaway wiki (no network: the model's
answers are stubbed)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import agents_md
from worker import used
from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"

HARNESS = """Keeping agents reliable.

## Ideas

### Durable State [1, 2]

**Claim:** Keep state outside the context window. [1]

**Why it matters:** Agents survive resets
and crashes. [2]

**How to apply:** Write decisions to a file. Then commit it.

```bash
npm test -- --watch
```

```bash
rm -rf build
```

### Small Steps [1]

**Claim:** One change at a time.

**How to apply:** Commit after each passing test.

```markdown
### Not an idea [9]
```

### Untested [2]

**Claim:** A thought nobody applied.

**Why it matters:** It sounds right.

## Patterns

### Not an idea either [1]

**Use it when:** never.
"""

HOOKS = """Hooks for agents.

## Ideas

### Old But Noted [1]

**Claim:** Hooks can filter.

**How to apply:** Filter hooks by command.

### Newest [2]

**How to apply:** Keep hooks fast.

### Oldest [3]

**How to apply:** Log every hook run.

### No Apply [2]

**Claim:** Hooks are fun.
"""


class AgentsMd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)
        notes = {50: ("2026-02-01", "intent: idea to read", "```bash\nnpm test -- --watch\n```"),
                 51: ("2026-02-03", None, ""), 52: ("2026-02-02", None, ""),
                 53: ("2026-02-05", "the filter trick", ""), 54: ("2026-02-06", None, ""), 55: ("2026-02-04", None, "")}
        rel = {}
        for n, (day, note, code) in notes.items():
            rel[n] = f"sources/2026-02/{n:04d}-note-{n}.md"
            wiki.write_page(self.wiki / rel[n], {"title": f"Note {n}", "captured": day, "capture": n, "note": note},
                            f"# Note {n}\n\n## Key ideas\n\n### Something\n\n" + (f"## Code\n\n{code}\n" if code else ""))
        self.topic("agent-harness", "Agent Harness", [rel[50], rel[51]], HARNESS)
        self.topic("learning", "Learning", [rel[52]], "Learning.\n\n## Ideas\n\n### Read Daily [1]\n\n"
                                                      "**How to apply:** Read every day.\n")
        self.topic("hooks", "Hooks", [rel[53], rel[54], rel[55]], HOOKS)
        used.record([50], "acme", "small steps")

    def topic(self, slug, title, sources, body):
        wiki.write_page(self.wiki / "practices" / f"{slug}.md",
                        {"title": title, "category": "practices", "summary": f"About {slug}.", "sources": sources}, body)

    def chat(self, filter_answer, word_answer="not json"):
        replies = {agents_md.FILTER: filter_answer, agents_md.WORD: word_answer}
        return mock.patch.object(agents_md.p, "chat", side_effect=lambda system, user, **_: (
            replies[system] if isinstance(replies[system], str) else json.dumps(replies[system])))

    def ideas(self):
        return {(t["key"], i["name"]): i for t in agents_md.practices() for i in t["ideas"]}

    def test_idea_blocks(self):
        blocks = wiki.blocks(HARNESS, "Ideas")
        self.assertEqual([(b["name"], b["cites"]) for b in blocks],
                         [("Durable State", [1, 2]), ("Small Steps", [1]), ("Untested", [2])])
        first = blocks[0]
        self.assertEqual(first["fields"]["why it matters"], "Agents survive resets and crashes.")
        self.assertEqual(first["fields"]["claim"], "Keep state outside the context window.")
        self.assertEqual([c["code"] for c in first["code"]], ["npm test -- --watch", "rm -rf build"])

    def test_evidence(self):
        ideas = self.ideas()
        durable = ideas[("practices/agent-harness", "Durable State")]
        self.assertEqual((durable["captures"], durable["used"]), ([50, 51], [50]))
        self.assertEqual([c["code"] for c in durable["code"]], ["npm test -- --watch"])  # only what a note recorded
        self.assertTrue(ideas[("practices/hooks", "Old But Noted")]["noted"])
        self.assertFalse(ideas[("practices/agent-harness", "Untested")]["noted"])  # an intent alone is not a note

    def test_tiers(self):
        rules, tries = agents_md.tiers([t for t in agents_md.practices() if t["key"] != "practices/learning"])
        names = lambda groups: [(g["topic"]["key"], [i["name"] for i in g["ideas"]]) for g in groups]
        self.assertEqual(names(rules), [("practices/agent-harness", ["Durable State", "Small Steps"])])  # used, or 2+
        self.assertEqual(names(tries), [("practices/hooks", ["Old But Noted", "Newest", "Oldest"]),  # 3 sources first
                                        ("practices/agent-harness", ["Untested"])])

    def test_the_model_filters_topics_once(self):
        answer = {"topics": {"practices/agent-harness": True, "practices/learning": False, "practices/hooks": True}}
        with self.chat(answer) as chat:
            rules, tries, text = agents_md.generate()
        self.assertEqual([c.args[0] for c in chat.call_args_list], [agents_md.FILTER, agents_md.WORD])
        self.assertIn("practices/learning: Learning — About learning. (ideas: Read Daily)", chat.call_args_list[0].args[1])
        self.assertNotIn("Learning", text)
        self.assertIs(wiki.read_page(self.wiki / "practices/learning.md")[0]["agents"], False)
        self.assertIn("Keeping agents reliable.", wiki.read_page(self.wiki / "practices/agent-harness.md")[1])

        meta, body = wiki.read_page(self.wiki / "practices/learning.md")
        wiki.write_page(self.wiki / "practices/learning.md", {**meta, "agents": True}, body)  # the owner overrides it
        with self.chat({"topics": {}}) as chat:
            text = agents_md.generate()[2]
        self.assertEqual([c.args[0] for c in chat.call_args_list], [agents_md.WORD])  # nothing left to ask
        self.assertIn("### Learning", text)

    def test_without_an_answer_every_topic_goes_in_undecided(self):
        with self.chat("no json"):
            text = agents_md.generate()[2]
        self.assertIn("### Learning", text)
        self.assertNotIn("agents", wiki.read_page(self.wiki / "practices/learning.md")[0])

    def test_wording_is_checked(self):
        rules = {"rules": [{"n": 1, "rule": "Keep durable state in files the agent can reread.", "why": "Context resets."},
                           {"n": 2, "rule": "See https://example.com for steps.", "why": "x"},
                           {"n": 3, "rule": "Commit " + "often " * 60, "why": "x"}]}
        with self.chat({"topics": {}}, rules):
            text = agents_md.generate()[2]
        self.assertIn("- Keep durable state in files the agent can reread. Context resets. (#50, #51)", text)
        self.assertIn("- Commit after each passing test. (#50)", text)  # the page's own words
        self.assertNotIn("example.com", text)
        self.assertIn("- Filter hooks by command. (#53)", text)

    def test_render(self):
        with self.chat({"topics": {}}):
            text = agents_md.generate()[2]
        self.assertTrue(text.startswith("# AGENTS.md\n\nHow the owner works, from 6 saved captures"))
        rules, tries = text.index("## Rules\n\nBacked by"), text.index("## Worth trying")
        self.assertLess(rules, text.index("- Write decisions to a file."))
        self.assertLess(text.index("- Commit after each passing test."), tries)
        self.assertLess(tries, text.index("- Log every hook run."))
        self.assertIn("- Write decisions to a file. Agents survive resets and crashes. (#50, #51)\n\n"
                      "  ```bash\n  npm test -- --watch\n  ```", text)
        self.assertNotIn("rm -rf", text)  # on the page, but in no source note
        self.assertNotIn("Not an idea", text)
        self.assertNotIn("Hooks are fun", text)  # past the three per topic

    def test_no_rules_yet(self):
        (self.wiki / used.PATH).unlink()
        with self.chat({"topics": {"practices/agent-harness": False, "practices/learning": True,
                                   "practices/hooks": False}}):
            text = agents_md.generate()[2]
        self.assertIn("## Rules\n\nNone yet: no idea has two captures behind it", text)
        self.assertNotIn("Backed by", text)
        self.assertIn("### Learning\n\n- Read every day. (#52)", text)

    def test_build_links_it_and_removes_it_when_nothing_belongs(self):
        with self.chat({"topics": {}}):
            self.assertTrue(agents_md.build())
        wiki.build_index()
        self.assertIn("[AGENTS.md](AGENTS.md) holds the", (self.wiki / "index.md").read_text())
        for slug in ("agent-harness", "learning", "hooks"):
            meta, body = wiki.read_page(self.wiki / "practices" / f"{slug}.md")
            wiki.write_page(self.wiki / "practices" / f"{slug}.md", {**meta, "agents": False}, body)
        self.assertFalse(agents_md.build(model=False))
        self.assertFalse((self.wiki / "AGENTS.md").exists())

    def test_out_saves_no_decision(self):
        out = Path(self.dir.name) / "project" / "AGENTS.md"
        out.parent.mkdir()
        with self.chat({"topics": {"practices/learning": False}}), \
                mock.patch("sys.argv", ["agents_md", "--out", str(out)]), mock.patch("sys.stderr"):
            agents_md.main()
        self.assertNotIn("### Learning", out.read_text())
        self.assertNotIn("agents", wiki.read_page(self.wiki / "practices/learning.md")[0])
        self.assertFalse((self.wiki / "AGENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
