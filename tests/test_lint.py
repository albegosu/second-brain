"""The lint pass splits catch-all topics, on a throwaway wiki (no network: the
model's answers are stubbed)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import lint
from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"


def state_of(**sizes) -> dict:
    """{"tools/a": 3} → a state with that many made-up sources per topic."""
    out, n = {}, 0
    for key, size in sizes.items():
        key = key.replace("__", "/").replace("_", "-")
        sources = [f"sources/2026-01/{(n := n + 1):04d}-note.md" for _ in range(size)]
        out[key] = {"title": key, "summary": "", "category": key.split("/")[0], "sources": sources, "related": []}
    return out


class CatchAlls(unittest.TestCase):
    def test_a_topic_holding_much_of_its_category(self):
        state = state_of(tools__ai=10, tools__a=2, tools__b=2, design__x=11,
                         **{f"design__t{i}": 10 for i in range(10)})
        self.assertEqual(lint.catch_alls(state), ["tools/ai"])  # design/x holds 10% of design

    def test_a_very_large_topic_whatever_the_share(self):
        state = state_of(design__big=15, **{f"design__t{i}": 10 for i in range(10)})
        self.assertEqual(lint.catch_alls(state), ["design/big"])

    def test_never_a_style(self):
        self.assertEqual(lint.catch_alls(state_of(design__style_x=15, tools__ai=10, tools__a=2)), ["tools/ai"])

    def test_small_topics_are_never_catch_alls(self):
        self.assertEqual(lint.catch_alls(state_of(tools__ai=7)), [])


class ApplySplit(unittest.TestCase):
    def setUp(self):
        self.state = state_of(tools__ai=6, tools__recorders=1)
        self.state["tools/recorders"]["related"] = ["tools/ai"]
        self.notes = self.state["tools/ai"]["sources"]

    def split(self, *parts):
        return lint.apply_split(self.state, "tools/ai", {"parts": list(parts)})

    def test_numbers_become_topics(self):
        after, log = self.split({"slug": "coding-agents", "title": "Coding Agents", "summary": "s", "sources": [1, 2, 3]},
                                {"slug": "tools/code-review", "title": "Code Review", "sources": ["4", "[5]", 6]})
        self.assertNotIn("tools/ai", after)
        self.assertEqual(after["tools/coding-agents"]["sources"], self.notes[:3])
        self.assertEqual(after["tools/code-review"]["sources"], self.notes[3:])  # the category prefix is dropped
        self.assertEqual(after["tools/coding-agents"]["category"], "tools")
        self.assertEqual(after["tools/recorders"]["related"], [])  # no link to a topic that's gone
        self.assertEqual(log, ["split tools/ai into tools/coding-agents, tools/code-review"])
        self.assertEqual(len(self.state["tools/ai"]["sources"]), 6)  # the input is left alone

    def test_every_note_stays_in_exactly_one_topic(self):
        after, _ = self.split({"slug": "coding-agents", "sources": [1, 2, 2, 3]},
                              {"slug": "code-review", "sources": [3, 4, 99]},  # 3 is taken, 99 doesn't exist
                              {"slug": "single", "sources": [5]})  # a new topic needs two notes
        self.assertEqual(after["tools/coding-agents"]["sources"], self.notes[:3])
        self.assertNotIn("tools/code-review", after)  # one note left: it gave it back
        self.assertEqual(after["tools/ai"]["sources"], self.notes[3:])  # what no part took stays
        self.assertEqual(sorted(s for t in after.values() for s in t["sources"]),
                         sorted(s for t in self.state.values() for s in t["sources"]))

    def test_one_note_can_join_an_existing_topic(self):
        after, log = self.split({"slug": "recorders", "sources": [6]},
                                {"slug": "coding-agents", "sources": [1, 2, 3, 4, 5]})
        self.assertEqual(after["tools/recorders"]["sources"], [self.notes[5], *self.state["tools/recorders"]["sources"]])
        self.assertEqual(log, ["split tools/ai into tools/coding-agents, moving notes to tools/recorders"])

    def test_a_vague_part_gives_its_notes_back(self):
        after, _ = self.split({"slug": "misc-utilities", "sources": [1, 2]}, {"slug": "coding-agents", "sources": [3, 4]})
        self.assertNotIn("tools/misc-utilities", after)
        self.assertEqual(after["tools/ai"]["sources"], [*self.notes[:2], *self.notes[4:]])

    def test_the_topic_may_keep_part_of_itself(self):
        after, _ = self.split({"slug": "ai", "title": "AI Pair Programmers", "sources": [1, 2]},
                              {"slug": "coding-agents", "sources": [3, 4, 5, 6]})
        self.assertEqual(after["tools/ai"]["title"], "AI Pair Programmers")
        self.assertEqual(after["tools/ai"]["sources"], self.notes[:2])

    def test_one_subject_changes_nothing(self):
        for answer in ({"parts": []}, {"parts": [{"slug": "ai", "sources": [1, 2, 3, 4, 5, 6]}]}, ["junk"], None):
            with self.subTest(answer):
                self.assertEqual(lint.apply_split(self.state, "tools/ai", answer), (self.state, []))


class SplitOnDisk(unittest.TestCase):
    """The whole path: the model's numbered answer, then pages written and notes retargeted."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)
        names = ["terminal-agent", "ide-agent", "review-bot", "pr-reviewer", "agent-sandbox",
                 "sandbox-vm", "browser-agent", "agent-cli"]
        self.sources = []
        for n, name in enumerate(names, 20):
            rel = f"sources/2026-01/{n:04d}-{name}.md"
            wiki.write_page(self.wiki / rel, {"title": name.replace("-", " ").title(), "summary": f"About {name}.",
                                              "topic": "tools/ai-tools", "tags": [name.split("-")[0]], "capture": n},
                            f"# {name}\n\nFiled under [AI Tools](../../tools/ai-tools.md)\n\n## Key ideas\n\n### {name}\n\n"
                            "## Code\n\n```markdown\n### Not an idea\n```")
            self.sources.append(rel)
        wiki.write_topic(self.wiki / "tools/ai-tools.md", {"title": "AI Tools", "category": "tools",
                                                           "summary": "Everything AI.", "sources": self.sources}, "Old.")

    def test_a_catch_all_is_split_and_written(self):
        answer = {"parts": [{"slug": "coding-agents", "title": "Coding Agents", "summary": "Agents that write code.",
                             "sources": [1, 2, 7, 8]},
                            {"slug": "ai-code-review", "title": "AI Code Review", "sources": [3, 4]},
                            {"slug": "agent-sandboxes", "title": "Agent Sandboxes", "sources": [5, 6]}]}
        before = lint.snapshot()
        with mock.patch.object(lint.p, "chat", return_value=json.dumps(answer)) as chat:
            after, log = lint.split_catch_alls(before)
        prompt = chat.call_args.args[1]
        self.assertIn("[3] Review Bot — About review-bot. [tags: review] [patterns: review-bot]", prompt)
        self.assertNotIn("Not an idea", prompt)  # a heading inside code is not an idea
        self.assertIn("- tools/color-pickers: Color Pickers — Apps that pick palettes.", prompt)
        self.assertEqual(log, ["split tools/ai-tools into tools/coding-agents, tools/ai-code-review, tools/agent-sandboxes"])

        with mock.patch.object(wiki, "compose", return_value="Rewritten.\n\n## Options\n\n### A tool [1]"):
            rewritten = lint.write_state(before, after, recompose_all=False)
        self.assertEqual(sorted(rewritten), ["tools/agent-sandboxes", "tools/ai-code-review", "tools/coding-agents"])
        self.assertFalse((self.wiki / "tools/ai-tools.md").exists())
        meta, body = wiki.read_page(self.wiki / self.sources[2])
        self.assertEqual(meta["topic"], "tools/ai-code-review")
        self.assertIn("Filed under [AI Code Review](../../tools/ai-code-review.md)", body)
        index = (self.wiki / "index.md").read_text()
        self.assertIn("[Coding Agents](tools/coding-agents.md) — Agents that write code. (4 sources)", index)

    def test_the_plan_reviews_the_finer_topics(self):
        answer = {"parts": [{"slug": "coding-agents", "sources": [1, 2, 7, 8]},
                            {"slug": "ai-code-review", "sources": [3, 4, 5, 6]}]}
        plan = {"merge": [{"topics": ["tools/coding-agents", "tools/color-pickers"],
                           "into": {"category": "tools", "slug": "coding-agents"}}]}
        replies = {lint.SPLIT: answer, lint.PLAN: plan}
        with mock.patch.object(lint.p, "chat", side_effect=lambda system, user, **_: json.dumps(replies[system])) as chat, \
                mock.patch("sys.argv", ["lint", "--dry-run"]), mock.patch("builtins.print") as out:
            lint.main()
        self.assertEqual([c.args[0] for c in chat.call_args_list], [lint.SPLIT, lint.PLAN])  # split first
        self.assertIn("## tools/ai-code-review", chat.call_args_list[1].args[1])
        self.assertNotIn("## tools/ai-tools", chat.call_args_list[1].args[1])
        printed = [c.args[0] for c in out.call_args_list]
        self.assertEqual(printed[:2], ["[lint] split tools/ai-tools into tools/coding-agents, tools/ai-code-review",
                                       "[lint] merged tools/coding-agents, tools/color-pickers into tools/coding-agents"])
        self.assertTrue((self.wiki / "tools/ai-tools.md").exists())  # a dry run writes nothing

    def test_a_failed_answer_keeps_the_topic(self):
        with mock.patch.object(lint.p, "chat", return_value="not json"):
            after, log = lint.split_catch_alls(lint.snapshot())
        self.assertEqual((after["tools/ai-tools"]["sources"], log), (self.sources, []))


if __name__ == "__main__":
    unittest.main()
