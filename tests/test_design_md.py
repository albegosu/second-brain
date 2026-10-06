"""DESIGN.md export, on a synthetic wiki (tests/fixtures/sample-wiki: invented captures).

    python -m unittest discover tests
    DESIGN_MD_LINT=1 python -m unittest discover tests   # also run the spec's linter (npx, network)

No model is called: the prose comes from the template, or from a stubbed chat().
Refresh the examples after an intended change to the output:

    BRAIN_WIKI=tests/fixtures/sample-wiki python -m worker.design_md --no-model --out docs/examples/DESIGN.taste.md
    BRAIN_WIKI=tests/fixtures/sample-wiki python -m worker.design_md --no-model --style paper-ink \
        --out docs/examples/DESIGN.style-paper-ink.md
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from worker import design_md as dm
from worker import pipeline as p
from worker import taste
from worker import wiki

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sample-wiki"
SECTIONS = ["Overview", "Colors", "Typography", "Layout", "Elevation & Depth", "Shapes", "Components",
            "Motion", "Do's and Don'ts"]
EXAMPLES = {None: "DESIGN.taste.md", "paper-ink": "DESIGN.style-paper-ink.md"}


def frontmatter(text: str) -> str:
    return text.split("\n---\n", 1)[0]


class DesignMdTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(wiki, "WIKI", FIXTURE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def made(self, style=None, look=None):
        made = dm.generate(style, model=False, look=look)
        self.assertIsNotNone(made)
        return made

    # ------------------------------------------------------------ color math

    def test_contrast_is_wcag(self):
        self.assertAlmostEqual(dm.contrast("#000000", "#ffffff"), 21, places=2)
        self.assertAlmostEqual(dm.contrast("#777777", "#ffffff"), 4.48, places=2)

    def test_readable_keeps_the_hue_and_reaches_aa(self):
        fixed = dm.readable("#8c8478", ["#f3ede1"])
        self.assertGreaterEqual(dm.contrast(fixed, "#f3ede1"), 4.5)
        self.assertLess(dm.hue_gap(fixed, "#8c8478"), 10)
        self.assertEqual(dm.readable("#141216", ["#ffffff"]), "#141216")  # already fine: untouched

    # ------------------------------------------------------------ taste

    def test_square_corners_can_lead(self):
        # "none" is a radius (square corners); for motion it means nothing was seen.
        self.assertEqual(taste.lead(Counter(none=6, rounded=2), "radius"), "none")
        self.assertIsNone(taste.lead(Counter(none=6, smooth=2), "motion_feel"))
        self.assertEqual(dm.choose(Counter(none=6, rounded=2), "rounded", "radius")[0], "none")

    def test_taste_tokens_come_from_the_design_captures(self):
        d, tok, _ = self.made()
        self.assertEqual(d["looks"], 8)  # the tools capture has a look but isn't counted
        self.assertEqual(tok["typography"]["body-md"]["fontFamily"], "DM Sans")  # geometric-sans leads
        self.assertEqual(tok["spacing"]["md"], "24px")  # airy leads
        self.assertNotIn("#ff0055", tok["colors"].values())  # the tools capture's accent
        self.assertEqual(dm.taste.hue(tok["colors"]["primary"]), "orange")  # the most frequent accent hue
        self.assertGreaterEqual(dm.hue_gap(tok["colors"]["tertiary"], tok["colors"]["primary"]), 45)
        self.assertIn("accent hue", d["unsettled"])  # orange 4 · red 3 · blue 2: no clear lead
        self.assertIn("radius", d["unsettled"])

    def test_taste_neutrals_share_one_palette(self):
        d, _, _ = self.made()
        owner = next(look["neutrals"] for look in dm.looks() if look["neutrals"][:1] == [d["colors"]["neutral"]])
        measured = [role for role in ("surface", "on-surface", "secondary", "outline")
                    if d["origin"][role] == "measured in the same capture as neutral"]
        self.assertIn("on-surface", measured)
        for role in measured:
            self.assertIn(d["colors"][role], owner)

    # ------------------------------------------------------------ styles

    def test_style_lookup(self):
        self.assertEqual(dm.find_style("paper-ink")["key"], "design/style-paper-ink")
        self.assertEqual(dm.find_style("style-paper-ink")["key"], "design/style-paper-ink")
        self.assertEqual(dm.find_style("design/style-night-console")["key"], "design/style-night-console")
        self.assertIsNone(dm.find_style("card-hover-lifts"))  # a Patterns topic, not a style
        self.assertEqual(sorted(t["slug"] for t in dm.style_topics()),
                         ["style-night-console", "style-paper-ink", "style-soft-lilac"])

    def test_style_takes_the_dominant_look(self):
        d, tok, text = self.made("paper-ink")
        self.assertEqual(d["traits"]["typography"][0], "serif")  # 2 of 3 captures
        self.assertEqual(d["anchor"], 3)  # #1 and #3 match every trait: the newest wins
        self.assertEqual(tok["colors"]["neutral"], "#f3ede1")  # capture #3's page color
        self.assertEqual(tok["colors"]["primary"], "#d9481f")
        self.assertEqual(tok["typography"]["headline-lg"]["fontFamily"], "Source Serif 4")
        self.assertEqual(tok["typography"]["label-md"]["fontFamily"], "Inter")  # labels stay sans
        self.assertEqual({tok["rounded"][k] for k in ("sm", "md", "lg")}, {"0px"})  # radius: none
        self.assertIn("Adjusted from `#8c8478`", text)  # a muted gray darkened to 4.5:1
        self.assertIn("It also holds: Cool Grotesk Variant.", text)
        self.assertIn("Let the text column breathe with wide margins.", text)  # the topic's own Do

    def test_a_look_by_name(self):
        d, tok, text = self.made("paper-ink", look="cool grotesk")  # part of the name is enough
        self.assertEqual(d["captures"], [2])
        self.assertEqual(d["name"], "Paper and Ink: Cool Grotesk Variant")
        self.assertEqual(d["traits"]["typography"][0], "grotesk")
        self.assertEqual(tok["colors"]["primary"], "#2f6fe4")  # capture #2's blue, not #3's orange
        self.assertIn('--style style-paper-ink --look "Cool Grotesk Variant"', text)
        self.assertIn('This is the look "Cool Grotesk Variant" of the topic. It also holds: Warm Paper Editorial.',
                      text)
        warm, dominant = self.made("paper-ink", look="Warm Paper Editorial")[1], self.made("paper-ink")[1]
        self.assertEqual({**warm, "name": ""}, {**dominant, "name": ""})  # the dominant look, by name
        with self.assertRaisesRegex(dm.NoLook, "Warm Paper Editorial; Cool Grotesk Variant"):
            dm.style_design("paper-ink", "neon")

    def test_dark_style(self):
        _, tok, text = self.made("night-console")
        self.assertEqual(dm.taste.tone(tok["colors"]["neutral"]), "dark")
        self.assertEqual(tok["typography"]["body-md"]["fontFamily"], "JetBrains Mono")
        self.assertIn("Corners are barely rounded", text)

    # ------------------------------------------------------------ a primary that may be a photo's

    def test_accents_rank_vivid_then_clear_then_muted(self):
        self.assertEqual([dm.accent_rank(c) for c in ("#d9481f", "#3b6462", "#3a2b22")], [0, 1, 2])
        self.assertEqual(dm.named_hues("Neon lime and electric blue accents, never `#0b0b0c` teal-free"),
                         {"green", "blue", "cyan"})

    def test_doubts(self):
        self.assertEqual(dm.doubts("#d9481f", True, {"orange"}), [])  # a red-orange: orange is next door
        self.assertEqual(len(dm.doubts("#3b6462", True, set())), 1)  # muted: maybe an image's
        self.assertIn("tinted dark surface", dm.doubts("#3a2b22", True, set())[0])
        self.assertEqual(dm.doubts("#d9481f", True, {"blue"}),
                         ["the wiki describes the look in blue and the primary is red"])
        self.assertEqual(dm.doubts("#211e1a", False, set()), [])  # the ink of a monochrome look
        self.assertEqual(dm.doubts("#211e1a", False, {"green", "orange"}),
                         ["the measured palette has no accent, but the wiki describes the look in green and orange"])

    def test_a_muted_primary_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "wiki"
            shutil.copytree(FIXTURE, copy)
            note = next((copy / "sources").glob("*/0003-*.md"))
            text = note.read_text()
            self.assertIn("`#d9481f` (accent), `#2d5b8a` (accent)", text)
            note.write_text(text.replace("`#d9481f` (accent), `#2d5b8a` (accent)", "`#3a2b22` (accent), `#3b6462` (accent)"))
            with mock.patch.object(wiki, "WIKI", copy):
                d, tok, text = dm.generate("paper-ink", model=False)
        self.assertEqual(d["anchor"], 3)
        self.assertEqual(tok["colors"]["primary"], "#3b6462")  # clear before muted and dark, whatever the area
        self.assertIn("**Low confidence:** no measured accent is vivid", text)
        self.assertIn("- **Do:** Check primary against the frames of capture #3 before you use it", text)
        self.assertNotIn("Low confidence", self.made("paper-ink")[2])

    # ------------------------------------------------------------ light and dark

    def split_wiki(self, tmp: str, extra: int = 3) -> Path:
        """The sample wiki with more dark captures: light 6 · dark 2 + extra."""
        copy = Path(tmp) / "wiki"
        shutil.copytree(FIXTURE, copy)
        dark = next((copy / "sources").glob("*/0004-*.md"))
        for n in range(10, 10 + extra):
            (dark.parent / f"{n:04d}-terminal-copy.md").write_text(dark.read_text().replace("capture: 4", f"capture: {n}"))
        return copy

    def test_no_pair_when_one_tone_leads(self):
        d, _, text = self.made()
        self.assertIsNone(d["pair"])
        self.assertIsNone(dm.taste_design("dark"))
        self.assertNotIn("DESIGN.dark.md", text)

    def test_a_split_taste_comes_as_a_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self.split_wiki(tmp)
            with mock.patch.object(wiki, "WIKI", copy):
                light, light_tok, light_text = dm.generate(model=False)
                dark, dark_tok, dark_text = dm.generate(model=False, tone="dark")
                self.assertEqual(dm.generate(model=False, tone="light")[2], light_text)
        self.assertEqual((light["pair"]["tone"], light["pair"]["twin"]), ("light", "dark"))
        self.assertEqual(dark["pair"]["path"], "DESIGN.dark.md")
        self.assertNotIn("background tone", light["unsettled"])
        self.assertEqual(dm.taste.tone(light_tok["colors"]["neutral"]), "light")
        self.assertEqual(dm.taste.tone(dark_tok["colors"]["neutral"]), "dark")
        self.assertEqual(dm.taste.hue(dark_tok["colors"]["primary"]), "green")  # the dark captures' own accent
        self.assertEqual(dark_tok["typography"], light_tok["typography"])  # the traits are the taste's
        self.assertEqual(dark_tok["spacing"], light_tok["spacing"])
        self.assertIn("this file is the light look and `DESIGN.dark.md` the dark one", light_text)
        self.assertIn("this file is the dark look and `DESIGN.md` the light one", dark_text)
        self.assertIn("(`python -m worker.design_md --tone dark`)", dark_text)
        self.assertIn('name: "Taste (dark)"', dark_text)
        for name, ratio in dm.contrast_pairs(dark_tok).items():
            self.assertGreaterEqual(ratio, 4.5, name)

    def test_build_writes_the_twin_and_removes_it_when_the_split_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = self.split_wiki(tmp)
            (copy / "taste.md").write_text("---\ntitle: \"Taste\"\n---\n\n# Taste\n")
            with mock.patch.object(wiki, "WIKI", copy):
                self.assertTrue(dm.build(model=False))
                wiki.build_index()
                self.assertIn("[DESIGN.dark.md](DESIGN.dark.md)", (copy / "index.md").read_text())
                self.assertEqual((copy / "DESIGN.dark.md").read_text(), dm.generate(model=False, tone="dark")[2])
                for extra in (copy / "sources").glob("*/001?-terminal-copy.md"):
                    extra.unlink()
                self.assertTrue(dm.build(model=False))
                wiki.build_index()
                self.assertFalse((copy / "DESIGN.dark.md").exists())
                self.assertNotIn("DESIGN.dark.md", (copy / "index.md").read_text())

    # ------------------------------------------------------------ the file

    def test_every_output_meets_the_spec(self):
        for style, look in ((None, None), ("paper-ink", None), ("paper-ink", "Cool Grotesk Variant"),
                            ("night-console", None), ("soft-lilac", None)):
            with self.subTest(style=style, look=look):
                _, tok, text = self.made(style, look)
                self.assertTrue(text.startswith("---\nversion: \"alpha\"\n"))
                head = frontmatter(text)
                for key in ("name:", "description:", "colors:", "typography:", "rounded:", "spacing:", "components:"):
                    self.assertIn(f"\n{key}", head)
                self.assertEqual(re.findall(r"^## (.+)$", text, re.M), SECTIONS)  # spec order, no duplicates
                for name, component in tok["components"].items():
                    for ref in (v for v in component.values() if v.startswith("{")):
                        self.assertIsNotNone(dm.resolve(tok, ref), f"{name}: {ref}")
                for name, ratio in dm.contrast_pairs(tok).items():
                    self.assertGreaterEqual(ratio, 4.5, name)
                for value in tok["colors"].values():
                    self.assertRegex(value, r"^#[0-9a-f]{6}$")
                self.assertNotIn("example.com", text)  # source links stay in the wiki
                self.assertEqual({u.rstrip(").,") for u in re.findall(r"https?://[^\s)]+", text)}, {dm.SPEC})

    def test_output_is_deterministic(self):
        self.assertEqual(self.made()[2], self.made()[2])
        self.assertEqual(self.made("paper-ink")[2], self.made("paper-ink")[2])

    def test_examples_are_current(self):
        for style, name in EXAMPLES.items():
            with self.subTest(example=name):
                self.assertEqual((ROOT / "docs" / "examples" / name).read_text(), self.made(style)[2],
                                 "refresh docs/examples (see this file's docstring)")

    # ------------------------------------------------------------ the model

    def test_model_prose_is_checked_by_code(self):
        answer = {"overview": "A calm, airy interface on light paper tones, with one warm accent reserved for the "
                              "main action and generous room around every group.",
                  "dos": ["Do use primary for the main action", "Paint it #ff0000", "ok"],
                  "donts": ["Avoid heavy shadows on cards", "See https://example.com for more"]}
        with mock.patch.object(p, "chat", return_value=json.dumps(answer)):
            d, tok, text = dm.generate(model=True)
        self.assertIn(answer["overview"], text)
        self.assertIn("- **Do:** Use primary for the main action.", text)
        self.assertIn("- **Don't:** Heavy shadows on cards.", text)
        self.assertNotIn("#ff0000", text)  # a hex code the tokens don't hold is dropped
        self.assertNotIn("example.com", text)
        self.assertEqual(tok, self.made()[1])  # the model never touches a token

    def test_a_bad_model_answer_falls_back_to_the_template(self):
        template = self.made()[2]
        for answer in ('{"overview": "Primary is #ff7a1a, very orange and bold, use it everywhere you can and more."}',
                       "not json", '["a list"]'):
            with self.subTest(answer=answer), mock.patch.object(p, "chat", return_value=answer):
                self.assertEqual(dm.generate(model=True)[2], template)
        with mock.patch.object(p, "chat", side_effect=RuntimeError("no model")):
            self.assertEqual(dm.generate(model=True)[2], template)

    # ------------------------------------------------------------ the wiki

    def test_build_writes_the_wiki_design_md_and_links_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "wiki"
            shutil.copytree(FIXTURE, copy)
            (copy / "taste.md").write_text("---\ntitle: \"Taste\"\n---\n\n# Taste\n")
            with mock.patch.object(wiki, "WIKI", copy):
                self.assertTrue(dm.build(model=False))
                wiki.build_index()
            self.assertEqual((copy / "DESIGN.md").read_text(), self.made()[2])
            self.assertIn("[DESIGN.md](DESIGN.md)", (copy / "index.md").read_text())

    def test_too_few_looks_means_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "wiki"
            shutil.copytree(FIXTURE, copy)
            for f in sorted((copy / "sources").glob("*/*.md"))[4:]:
                f.unlink()
            with mock.patch.object(wiki, "WIKI", copy):
                self.assertFalse(dm.build(model=False))
            self.assertFalse((copy / "DESIGN.md").exists())

    # ------------------------------------------------------------ the spec's own linter

    @unittest.skipUnless(os.environ.get("DESIGN_MD_LINT") == "1",
                         "set DESIGN_MD_LINT=1 to run npx @google/design.md lint")
    def test_the_spec_linter_finds_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = {style or "taste": self.made(style)[2] for style in (None, "paper-ink", "night-console", "soft-lilac")}
            outputs["paper-ink-look"] = self.made("paper-ink", "Cool Grotesk Variant")[2]
            with mock.patch.object(wiki, "WIKI", self.split_wiki(tmp)):
                outputs["taste-dark"] = dm.generate(model=False, tone="dark")[2]
            for style, text in outputs.items():
                path = Path(tmp) / f"{style}.md"
                path.write_text(text)
                done = subprocess.run(["npx", "-y", "@google/design.md@0.4.0", "lint", str(path)],
                                      capture_output=True, text=True, timeout=300)
                report = json.loads(done.stdout)
                with self.subTest(style=style):
                    self.assertEqual(report["summary"]["errors"], 0, report["findings"])
                    self.assertEqual(report["summary"]["warnings"], 0, report["findings"])


if __name__ == "__main__":
    unittest.main()
