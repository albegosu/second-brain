"""The usage log on a copy of the synthetic wiki (no network, no model, no git)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import used
from worker import wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"


class UsageLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ref_labels(self):
        self.assertEqual(used.ref_label("https://github.com/acme/web/pull/42"), "acme/web#42")
        self.assertEqual(used.ref_label("https://github.com/acme/web/commit/0123456789abcdef0123"), "acme/web@0123456")
        self.assertEqual(used.ref_label("https://gitlab.com/acme/ui/web/-/merge_requests/7"), "acme/ui/web#7")
        self.assertEqual(used.ref_label("https://gitlab.com/acme/web/-/commit/abcdef1234"), "acme/web@abcdef1")
        self.assertEqual(used.ref_label("https://example.com/review/9"), "example.com/review/9")

    def test_a_line_with_a_ref_reads_back(self):
        line = used.record([7], "acme-web", "card lift on hover · pricing", "https://github.com/acme/web/pull/42")
        self.assertTrue(line.endswith(" · card lift on hover - pricing · [acme/web#42](https://github.com/acme/web/pull/42)"))
        used.record([8], "acme-web", "feature tiles")
        first, second = used.uses()
        self.assertEqual(first["captures"], [7])
        self.assertEqual(first["what"], "card lift on hover - pricing")
        self.assertEqual(first["ref"], "https://github.com/acme/web/pull/42")
        self.assertEqual(second["what"], "feature tiles")
        self.assertIsNone(second["ref"])

    def test_lines_written_before_refs_still_read(self):
        (self.wiki / used.PATH).write_text("\n".join(used.HEADER) + "\n- 2026-09-20 · **old** · #7, #8 · a loader\n")
        (use,) = used.uses()
        self.assertEqual((use["captures"], use["what"], use["ref"]), ([7, 8], "a loader", None))

    def test_a_ref_must_be_a_url(self):
        for bad in ("abc1234", "acme/web#42", "https://github.com/acme/web/pull/42 extra", "https://x.dev/a)b"):
            with self.subTest(bad), self.assertRaises(SystemExit):
                used.record([7], "acme-web", "x", bad)
        self.assertFalse((self.wiki / used.PATH).exists())

    def test_the_index_counts_verifiable_uses(self):
        used.record([7], "acme-web", "card lift", "https://github.com/acme/web/commit/abcdef1")
        used.record([7], "acme-app", "card lift again")
        topic = wiki.read_page(next(self.wiki.joinpath("sources").rglob("0007-*.md")))[0]["topic"]
        self.assertEqual(used.topic_uses()[topic], 2)
        self.assertEqual(used.topic_uses(verifiable=True)[topic], 1)
        wiki.build_index()
        line = next(l for l in (self.wiki / "index.md").read_text().splitlines() if f"]({topic}.md)" in l)
        self.assertIn("used 2×, 1 verifiable", line)


if __name__ == "__main__":
    unittest.main()
