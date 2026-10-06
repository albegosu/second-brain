"""A live page's computed CSS: the summary, where it goes, and a real headless Chrome run on a local page."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import page_css
from worker import pipeline as p
from worker import taste
from worker import wiki

# What EXTRACT returns, shaped like a real run (trimmed).
RAW = {"page": "#ffffff", "elements": 412,
       "backgrounds": [["#ffffff", 900000], ["#f6f9fc", 120000], ["#533afd", 9000]],
       "texts": [["#061b31", 5200], ["#50617a", 3100], ["#533afd", 400]],
       "buttons": [["#533afd", 6], ["#ffffff", 2]], "links": [["#5a6677", 300]],
       "borders": [["#e5edf5", 5000]],
       "type": {"body": [["sohne-var|16px|24px|300|", 5000]], "heading": [["sohne-var|48px|55.2px|300|-0.96px", 300]],
                "label": [["sohne-var|15px|normal|400|", 200]]},
       "radius": {"button": [["4px", 6]], "input": [], "card": [["8px", 4]]},
       "padding": [["8px 16px", 5]], "gaps": [["16px", 9], ["24px", 4]],
       "shadows": [["rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(50, 50, 93, 0.12) 0px 16px 32px 0px", 4]], "blur": 0,
       "transitions": [["color 0.24s cubic-bezier(0.45, 0.05, 0.55, 0.95)", 7]],
       "props": [["--brand", "#533afd"], ["--radius", "4px"]]}

PAGE = """<!doctype html><html><head><style>
  :root { --brand: oklch(0.65 0.2 40); --space: 12px; --color-red-500: #ef4444; --tw-ring: 0; }
  html, body { margin: 0; background: #fafafa; color: #111111; font: 16px/24px Georgia, serif; }
  h1 { font: 700 44px/1.1 "Helvetica Neue", Arial, sans-serif; letter-spacing: -0.02em; }
  .card { background: #ffffff; border: 1px solid #e4e4e7; border-radius: 12px; padding: 24px; width: 420px;
          box-shadow: 0 0 0 0 rgba(0,0,0,0), 0 8px 24px rgba(0,0,0,0.08); }
  button { background: var(--brand); color: #000; border: 0; border-radius: 8px; padding: 10px 18px;
           transition: background-color 150ms ease-out; font: 500 14px/20px Arial, sans-serif; }
  .chip { display: inline-block; border-radius: 999px; background: #eeeeee; padding: 2px 10px; }
  .row { display: flex; gap: 16px; }
  .hidden { display: none; background: #00ff00; color: #00ff00; }
</style></head><body>
  <h1>Design tokens, measured</h1>
  <div class="card"><p>Some body copy long enough to count as the main text of this page, set in the serif.</p>
    <div class="row"><button>Save it</button><span class="chip">tag</span></div></div>
  <div class="hidden">invisible text that must not count</div>
</body></html>"""


class Summary(unittest.TestCase):
    def test_palette_takes_buttons_as_accents_and_slate_as_neutral(self):
        css = page_css.summarize(RAW)
        neutrals = [c["hex"] for c in css["palette"] if c["role"] == "neutral"]
        accents = [c["hex"] for c in css["palette"] if c["role"] == "accent"]
        self.assertEqual(neutrals[0], "#ffffff")  # the page comes first: DESIGN.md reads it as neutral
        self.assertIn("#061b31", neutrals)  # dark navy text has a hue, but it's ink
        self.assertIn("#50617a", neutrals)
        self.assertEqual(accents, ["#533afd"])
        self.assertEqual(css["radius"], "subtle")

    def test_lines(self):
        lines = page_css.summarize(RAW)["lines"]
        self.assertIn("- Type: body sohne-var 16px/24px 300 · headings sohne-var 48px/55.2px 300 -0.96px · "
                      "labels sohne-var 15px/normal 400", lines)
        self.assertIn("- Corner radius: buttons 4px · cards 8px", lines)
        self.assertIn("- Spacing: button padding 8px 16px · gaps 16px, 24px", lines)
        self.assertIn("- Depth: `rgba(50, 50, 93, 0.12) 0px 16px 32px 0px`", lines)  # the invisible layer is gone
        self.assertIn("- Transitions declared on links, buttons and inputs: "
                      "`color 0.24s cubic-bezier(0.45, 0.05, 0.55, 0.95)` (7)", lines)

    def test_radius_and_shadows(self):
        trait = lambda value: page_css.radius_trait({"button": [[value, 1]]})
        self.assertEqual([trait(v) for v in ("0px", "4px", "8px", "24px", "pill")],
                         ["none", "subtle", "rounded", "rounded", "pill"])
        self.assertIsNone(page_css.radius_trait({"button": [], "card": [], "input": []}))
        self.assertEqual(page_css.visible_shadow("lab(2.7 0 0) 0px 0px 0px 0px, oklab(0.1 0 0 / 0.05) 0px 0px 0px 1px"),
                         "oklab(0.1 0 0 / 0.05) 0px 0px 0px 1px")

    def test_an_empty_read_is_nothing(self):
        self.assertIsNone(page_css.summarize(None))
        self.assertIsNone(page_css.summarize({"page": "#ffffff", "elements": 0}))


class IntoTheNote(unittest.TestCase):
    def test_css_wins_over_pixels(self):
        css = page_css.summarize(RAW)
        with mock.patch.object(p, "palette", return_value=[{"hex": "#123456", "role": "neutral"}]) as pixels:
            look = p.clean_style({"radius": "pill", "typography": "grotesk"}, [Path("shot.jpg")], css)
        pixels.assert_not_called()
        self.assertEqual(look["radius"], "subtle")  # measured beats the model's guess
        self.assertEqual(look["typography"], "grotesk")
        body = wiki.source_body(note=None, text=None, page=None, patterns=[], style=look)
        self.assertIn("Palette, measured from the page's CSS (the interface's own colors): `#ffffff`", body)
        self.assertIn("`#533afd` (accent)", body)
        self.assertIn("CSS computed on the live page, exact values rather than estimates:\n- Colors: page `#ffffff`", body)

    def test_without_css_the_pixels_stay(self):
        with mock.patch.object(p, "palette", return_value=[{"hex": "#123456", "role": "neutral"}]):
            look = p.clean_style({"radius": "pill"}, [Path("shot.jpg")])
        self.assertEqual(look["radius"], "pill")
        body = wiki.source_body(note=None, text=None, page=None, patterns=[], style=look)
        self.assertIn("Palette, measured from pixels (includes content colors): `#123456`", body)
        self.assertNotIn("CSS computed", body)


@unittest.skipUnless(p.chrome(), "needs Chrome or Chromium")
class RealChrome(unittest.TestCase):
    def test_a_local_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(PAGE)
            css = page_css.read(page.as_uri(), p.chrome())
        self.assertIsNotNone(css, "headless Chrome didn't answer over the pipe")
        neutrals = [c["hex"] for c in css["palette"] if c["role"] == "neutral"]
        accents = [c["hex"] for c in css["palette"] if c["role"] == "accent"]
        self.assertEqual(neutrals[0], "#fafafa")
        self.assertIn("#111111", neutrals)
        self.assertEqual(len(accents), 1)  # the button's oklch orange, as sRGB; the hidden green never counts
        self.assertIn(taste.hue(accents[0]), ("orange", "red"))  # oklch(0.65 0.2 40) is a red-orange
        self.assertEqual(css["radius"], "rounded")
        text = "\n".join(css["lines"])
        self.assertIn("body Georgia 16px/24px 400", text)
        self.assertIn("headings Helvetica Neue 44px", text)
        self.assertIn("buttons 8px", text)
        self.assertIn("cards 12px", text)
        self.assertIn("button padding 10px 18px", text)
        self.assertIn("gaps 16px", text)
        self.assertIn("`rgba(0, 0, 0, 0.08) 0px 8px 24px 0px`", text)
        self.assertIn("`background-color 0.15s ease-out` (1)", text)
        self.assertIn("`--space: 12px`", text)
        self.assertNotIn("--color-red-500", text)  # a framework's palette, not a choice
        self.assertNotIn("#00ff00", text)


if __name__ == "__main__":
    unittest.main()
