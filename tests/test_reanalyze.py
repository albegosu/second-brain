"""Re-analysis files a capture again, on a throwaway wiki (no network: the
model's answers are stubbed). A topic the capture leaves is rewritten from the
sources it has left, so it never cites a number gone from its list."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"

MEDIA = {"kind": "text", "text": "A pricing card that lifts under the pointer."}


def page_for(key: str, meta: dict) -> str:
    """What the model would write: one block per source, numbered as listed."""
    blocks = "\n\n".join(f"### {Path(rel).stem.split('-', 1)[1]} [{i}]"
                         for i, rel in enumerate(meta["sources"], 1))
    return f"Rewritten {key}.\n\n## Patterns\n\n{blocks}"


class Reanalyze(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)

    def refile(self, cid: int, captured: str, url: str, category: str, topic: str) -> list[str]:
        """Files an already filed capture again under category/topic. Returns the
        keys of the topic pages the model was asked to write, in order."""
        composed = []

        def compose(key, meta):
            composed.append(key)
            return page_for(key, meta)

        with mock.patch.object(wiki, "classify", return_value={"category": category, "topic": topic,
                                                               "title": "Pricing Card Lift", "summary": "A card."}), \
                mock.patch.object(wiki, "compose", side_effect=compose):
            wiki.file_capture(cid=cid, captured=captured, url=url, source="web", media=MEDIA,
                              note=None, patterns=[], style=None)
        return composed

    def test_the_topic_it_leaves_is_rewritten_from_what_remains(self):
        composed = self.refile(7, "2026-01-07", "https://example.com/captures/pricing-card-lift",
                               "features", "pricing-tables")
        self.assertEqual(composed, ["features/pricing-tables", "design/card-hover-lifts"])
        meta, body = wiki.read_page(self.wiki / "design/card-hover-lifts.md")
        self.assertEqual(meta["sources"], ["sources/2026-01/0008-feature-tiles.md"])
        self.assertEqual(wiki.pattern_names(body), ["feature-tiles"])
        self.assertNotIn("[2]", wiki.strip_generated(body))  # the old text cited the capture as [1], the tiles as [2]
        self.assertRegex(meta["updated"], r"^\d{4}-\d{2}-\d{2}$")
        index = (self.wiki / "index.md").read_text()
        self.assertNotIn("Card lift on hover", index)
        self.assertIn("Patterns: feature-tiles", index)

    def test_the_same_topic_is_written_once(self):
        composed = self.refile(7, "2026-01-07", "https://example.com/captures/pricing-card-lift",
                               "design", "card-hover-lifts")
        self.assertEqual(composed, ["design/card-hover-lifts"])
        self.assertEqual(len(wiki.read_page(self.wiki / "design/card-hover-lifts.md")[0]["sources"]), 2)

    def test_a_topic_left_empty_is_deleted_not_rewritten(self):
        composed = self.refile(6, "2026-01-06", "https://example.com/captures/lilac-onboarding",
                               "features", "onboarding-flows")
        self.assertEqual(composed, ["features/onboarding-flows"])
        self.assertFalse((self.wiki / "design/style-soft-lilac.md").exists())


if __name__ == "__main__":
    unittest.main()
