"""Collections on a copy of the synthetic wiki: the note keyword, the command, the
index, a collection's DESIGN.md and the MCP tools (no network, no model, no git:
the pipeline's fetch and the model's answers are stubbed)."""
import contextlib
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import collect
from worker import design_md as dm
from worker import hypar
from worker import mcp
from worker import pipeline as p
from worker import run
from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"
CARD = "https://example.com/captures/pricing-card-lift"  # capture #7, design/card-hover-lifts
MEDIA = {"kind": "text", "text": "A pricing card that lifts under the pointer, its shadow growing as it rises. "
                                 "Three tiers side by side, the middle one marked as the most popular plan."}


def frontmatter(n: int) -> dict:
    return wiki.read_page(next((wiki.WIKI / "sources").glob(f"*/{n:04d}-*.md")))[0]


class Collections(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        for patcher in (mock.patch.object(wiki, "WIKI", self.wiki), mock.patch.object(run, "GIT_SYNC", False),
                        mock.patch.object(hypar, "sync_index")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tool(self, tool_name, /, **args):
        result = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": tool_name, "arguments": args}})["result"]
        return result, "\n".join(c["text"] for c in result["content"] if c["type"] == "text")

    # ------------------------------------------------------------ the note keyword

    def test_the_keyword_is_read_and_kept_from_the_model(self):
        note = "intent: Pattern to reuse — collection: Checkout the lift colección: acme-web, style: paper-ink"
        self.assertEqual(run.collections_in(note), ["acme-web", "checkout"])
        style, intent, rest = run.parse_note(note)
        self.assertEqual((style, intent), ("paper-ink", "pattern to reuse"))
        self.assertEqual(rest, "the lift")  # neither keyword reaches the model
        self.assertEqual(run.collections_in("coleccion: checkout"), ["checkout"])
        self.assertEqual(run.collections_in("a recollection: nothing"), [])
        self.assertEqual(run.collections_in(None), [])

    def file(self, url, note, reanalyze=False):
        """Ingests url with the pipeline stubbed; returns the result and the
        note the model was given."""
        given = []

        def classify(header, body, known, intent=None):
            given.append(body)
            return {"category": "design", "topic": "card-hover-lifts", "title": "Pricing Card Lift",
                    "summary": "A card."}

        with mock.patch.object(p, "fetch_media", return_value=dict(MEDIA)) as fetch, \
                mock.patch.object(wiki, "classify", side_effect=classify), \
                mock.patch.object(wiki, "compose", return_value="Cards that lift.\n\n## Patterns\n\n### Lift [1]\n"
                                                                "\n**Use it when:** clickable cards. " * 3):
            result = run.ingest(url, note, reanalyze=reanalyze)
        return result, given, fetch

    def test_a_new_capture_joins_its_collections_and_stays_in_its_topic(self):
        result, given, _ = self.file("https://example.com/new-card", "collection: checkout collection: acme the lift")
        self.assertIn("entry", result, result["text"])
        self.assertTrue(result["text"].endswith(" · in acme, checkout"))
        meta = frontmatter(10)
        self.assertEqual(meta["collections"], ["acme", "checkout"])
        self.assertEqual(meta["topic"], "design/card-hover-lifts")  # the model's topic, unlike style:
        self.assertEqual(meta["note"], "collection: checkout collection: acme the lift")  # the note as written
        self.assertIn("> the lift", given[0])
        self.assertNotIn("collection", given[0])

    def test_sharing_a_saved_link_again_adds_it_without_analysis(self):
        result, _, fetch = self.file(CARD, "collection: checkout")
        fetch.assert_not_called()
        self.assertEqual((result["already"], result["collected"]), (True, ["checkout"]))
        self.assertEqual(frontmatter(7)["collections"], ["checkout"])
        self.assertIsNone(frontmatter(7)["note"])  # nothing else in the note changes
        self.assertIn("- **checkout** (1 capture)", (self.wiki / "index.md").read_text())
        again, _, _ = self.file(CARD, "collection: checkout")
        self.assertNotIn("collected", again)
        self.assertEqual(again["text"], "already filed: #7")

    def test_reanalysis_keeps_the_collections_in_the_frontmatter(self):
        self.file(CARD, "collection: checkout collection: acme", reanalyze=True)
        self.assertEqual(frontmatter(7)["collections"], ["acme", "checkout"])
        collect.collect([7], "checkout", remove=True)
        self.file(CARD, None, reanalyze=True)  # the stored note still says checkout
        self.assertEqual(frontmatter(7)["collections"], ["acme"])
        self.assertEqual(frontmatter(7)["note"], "collection: checkout collection: acme")

    def test_the_notification_says_where_it_went(self):
        sent = []
        with mock.patch.object(run, "NTFY_TOPIC", "t"), mock.patch.object(run.httpx, "post",
                                                                           side_effect=lambda *a, **k: sent.append(k["json"])):
            run.notify(CARD, {"text": "", "already": True, "collected": ["checkout"]})
            run.notify(CARD, {"text": "", "entry": {"category": "design", "topic": "t", "new_topic": False,
                                                    "title": "T", "summary": "S", "collections": ["checkout"]}})
        self.assertEqual(sent[0]["title"], "Added to checkout")
        self.assertTrue(sent[1]["message"].endswith("\nIn checkout"))

    # ------------------------------------------------------------ the command

    def test_the_command_only_edits_the_frontmatter(self):
        note = next((self.wiki / "sources").glob("*/0007-*.md"))
        before = note.read_text()
        self.assertEqual(collect.collect([7, 3, 7], "Checkout"), ["#7: checkout", "#3: checkout"])
        self.assertEqual(collect.collect([7], "acme-web"), ["#7: acme-web, checkout"])
        after = note.read_text()
        self.assertEqual(after.replace('collections: ["acme-web", "checkout"]\n', ""), before)
        self.assertEqual(wiki.collections(), {"acme-web": ["sources/2026-01/0007-pricing-card-lift.md"],
                                              "checkout": ["sources/2026-01/0003-serif-longform-reader.md",
                                                           "sources/2026-01/0007-pricing-card-lift.md"]})
        self.assertEqual(collect.collect([7], "acme-web", remove=True), ["#7: checkout"])
        self.assertEqual(collect.collect([3], "checkout", remove=True), ["#3: in no collection"])
        self.assertNotIn("collections", frontmatter(3))
        self.assertEqual(note.read_text().replace('collections: ["checkout"]\n', ""), before)

    def test_an_unknown_capture_changes_nothing(self):
        with self.assertRaisesRegex(SystemExit, "no capture #99"):
            collect.collect([7, 99], "checkout")
        self.assertEqual(wiki.collections(), {})

    def test_the_command_line(self):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["collect", "4", "5", "night-ops"]), contextlib.redirect_stdout(out):
            collect.main()
        self.assertEqual(out.getvalue(), "#4: night-ops\n#5: night-ops\n")
        self.assertIn("- **night-ops** (2 captures)", (self.wiki / "index.md").read_text())

    def test_hand_edited_frontmatter_is_read(self):
        note = next((self.wiki / "sources").glob("*/0008-*.md"))
        note.write_text(note.read_text().replace("analyzed: 3\n", "analyzed: 3\ncollections: [checkout, 'Acme Web']\n"))
        self.assertEqual(frontmatter(8)["collections"], "[checkout, 'Acme Web']")  # not JSON
        self.assertEqual(wiki.note_collections(frontmatter(8)), ["acme-web", "checkout"])
        self.assertEqual(wiki.join_collections(8, ["checkout"]), ["acme-web", "checkout"])
        self.assertIn("collections: [checkout, 'Acme Web']", note.read_text())  # unchanged: nothing to write

    # ------------------------------------------------------------ the index

    def test_the_index_lists_each_collection_with_its_captures(self):
        wiki.build_index()
        self.assertNotIn("## Collections", (self.wiki / "index.md").read_text())  # none yet: no section
        collect.collect([5, 4, 7], "night-ops")
        collect.collect([7], "checkout")
        wiki.build_index()
        index = (self.wiki / "index.md").read_text()
        section = index.split("## Collections\n", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(re.findall(r"^- \*\*(.+?)\*\* \((.+?)\)$", section, re.M),
                         [("checkout", "1 capture"), ("night-ops", "3 captures")])
        self.assertIn("  - #4 [Terminal Dashboard](sources/2026-01/0004-terminal-dashboard.md) → "
                      "design/style-night-console\n  - #5 [Log Viewer]", section)
        self.assertLess(index.index("## Tools"), index.index("## Collections"))
        self.assertLess(index.index("## Collections"), index.index("## Recent captures"))
        self.assertIn("[Card Hover Lifts](design/card-hover-lifts.md)", index)  # #7 is still in its topic

    # ------------------------------------------------------------ DESIGN.md

    def test_a_collection_design_md_comes_only_from_its_captures(self):
        collect.collect([4, 5, 7, 9], "night-ops")
        d, tok, text = dm.generate(model=False, collection="Night-Ops")
        self.assertEqual(d["kind"], "collection")
        self.assertEqual(d["captures"], [4, 5, 7])  # #9 is a tool: its landing page wasn't saved for its look
        self.assertEqual(d["looks"], 3)
        self.assertEqual(tok["name"], "Night Ops")
        self.assertEqual(dm.taste.tone(tok["colors"]["neutral"]), "dark")  # the taste's is light
        self.assertNotIn("#ff0055", tok["colors"].values())  # the tool's accent
        palettes = {c for n in (4, 5, 7) for c in re.findall(r"`(#[0-9a-f]{6})`",
                                                                next((self.wiki / "sources").glob(f"*/{n:04d}-*.md"))
                                                                .read_text())}
        for role in ("neutral", "surface", "on-surface", "tertiary"):
            self.assertIn(tok["colors"][role], palettes, role)
        self.assertEqual(tok["typography"]["body-md"]["fontFamily"], "JetBrains Mono")  # mono 2 of 3
        self.assertIn("from the collection `night-ops`, captures #4, #5, #7 "
                      "(`python -m worker.design_md --collection night-ops`)", text)
        self.assertEqual(re.findall(r"^## (.+)$", text, re.M)[0], "Overview")
        for name, ratio in dm.contrast_pairs(tok).items():
            self.assertGreaterEqual(ratio, 4.5, name)
        self.assertNotIn("example.com", text)
        self.assertEqual(dm.generate(model=False, collection="night-ops")[2], text)  # deterministic

    def test_one_capture_is_enough_for_a_collection(self):
        collect.collect([3], "reader")
        d, tok, text = dm.generate(model=False, collection="reader")
        self.assertEqual((d["captures"], d["pair"]), ([3], None))
        self.assertEqual(tok["colors"]["neutral"], "#f3ede1")  # capture #3's page color
        self.assertIn("across 1 capture with a measured look", text)

    def test_no_design_md_without_a_look(self):
        collect.collect([9], "tools-only")
        self.assertIsNone(dm.taste_design(collection="tools-only"))
        self.assertIsNone(dm.taste_design(collection="nope"))
        self.assertEqual(dm.missing_collection("nope"), "no collection 'nope' (collections: tools-only)")
        self.assertIn("no design or features capture", dm.missing_collection("tools-only"))
        self.assertIsNone(dm.taste_design("dark", collection="tools-only"))

    def test_the_taste_is_untouched_by_collections(self):
        taste = dm.generate(model=False)[2]
        collect.collect([4, 5], "night-ops")
        self.assertEqual(dm.generate(model=False)[2], taste)

    def test_the_design_md_command_line(self):
        collect.collect([4, 5], "night-ops")
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["design_md", "--collection", "night-ops", "--no-model"]), \
                contextlib.redirect_stdout(out):
            dm.main()
        self.assertIn('name: "Night Ops"', out.getvalue())
        self.assertFalse((self.wiki / "DESIGN.md").exists())  # printed, never the taste's file
        for argv, error in ((["--collection", "nope"], "no collection 'nope' (collections: night-ops)"),):
            with mock.patch.object(sys, "argv", ["design_md", *argv]), self.assertRaises(SystemExit) as stop:
                dm.main()
            self.assertEqual(str(stop.exception), f"[design] {error}")
        for argv in (["--collection", "night-ops", "--tone", "dark"], ["--collection", "night-ops", "--style", "x"]):
            with mock.patch.object(sys, "argv", ["design_md", *argv]), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                dm.main()

    # ------------------------------------------------------------ MCP

    def test_mcp_reads_a_collection(self):
        self.assertIn("No collections yet", self.tool("get_collection")[1])
        collect.collect([4, 5, 9], "night-ops")
        collect.collect([7], "checkout")
        self.assertEqual(self.tool("get_collection")[1], "- checkout (1 capture)\n- night-ops (3 captures)")
        result, text = self.tool("get_collection", name="Night-Ops")
        self.assertFalse(result["isError"])
        self.assertIn("Collection night-ops: 3 captures, oldest first", text)
        self.assertIn("- #9 Palette Picker App → tools/color-pickers · sources/2026-01/0009-palette-picker-app.md · "
                      "https://example.com/captures/palette-picker-app", text)
        result, text = self.tool("get_collection", name="nope")
        self.assertTrue(result["isError"])
        self.assertEqual(text, "no collection 'nope' (collections: checkout, night-ops)")

    def test_mcp_design_md_of_a_collection(self):
        collect.collect([4, 5], "night-ops")
        (self.wiki / "DESIGN.md").write_text("the weekly taste file\n")
        _, text = self.tool("get_design_md", collection="night-ops")
        self.assertEqual(text, dm.generate(model=False, collection="night-ops")[2])
        self.assertIn("collection takes neither", self.tool("get_design_md", collection="night-ops", tone="dark")[1])
        self.assertIn("collection takes neither", self.tool("get_design_md", collection="night-ops", style="x")[1])
        result, text = self.tool("get_design_md", collection="nope")
        self.assertTrue(result["isError"])
        self.assertIn("no collection 'nope'", text)


if __name__ == "__main__":
    unittest.main()
