"""Sharing a filed link again as "Idea to grow": the note plants it in hypar."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import hypar, run, wiki

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-wiki"
CARD = "https://example.com/captures/pricing-card-lift"  # capture #7, already filed


class GrowAgain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.wiki = Path(self.dir.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        for patcher in (mock.patch.object(wiki, "WIKI", self.wiki), mock.patch.object(run, "GIT_SYNC", False),
                        mock.patch.object(hypar, "sync_index"), mock.patch.object(hypar, "enabled", return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_filed_link_shared_again_with_a_note_is_planted(self):
        with mock.patch.object(hypar, "plant", return_value={"id": "e1"}) as plant:
            result = run.ingest(CARD, "intent: Idea to grow — lift cards in hypar")
        self.assertTrue(result["already"])
        self.assertEqual(result["embryo"], {"id": "e1"})
        self.assertIn("planted in hypar (e1)", result["text"])
        self.assertEqual(plant.call_args.args[:2], ("lift cards in hypar", CARD))

    def test_without_a_note_nothing_is_planted_and_nothing_is_reported(self):
        with mock.patch.object(hypar, "plant") as plant:
            result = run.ingest(CARD, "intent: Idea to grow —")
        plant.assert_not_called()
        self.assertEqual(result["text"], "already filed: #7")

    def test_other_intents_are_left_alone(self):
        with mock.patch.object(hypar, "plant") as plant:
            result = run.ingest(CARD, "intent: Tool to try — something")
        plant.assert_not_called()
        self.assertEqual(result["text"], "already filed: #7")

    def test_the_push_says_what_happened_in_hypar(self):
        sent = []
        with mock.patch.object(run, "NTFY_TOPIC", "t"), \
                mock.patch.object(run.httpx, "post", side_effect=lambda *a, **k: sent.append(k["json"])), \
                mock.patch.object(hypar, "embryo_url", return_value="https://h/e1"):
            run.notify(CARD, {"already": True, "embryo": {"id": "e1"}})
            run.notify(CARD, {"already": True, "hypar_error": "boom"})
        self.assertEqual(sent[0]["title"], "Planted in hypar")
        self.assertEqual(sent[0]["click"], "https://h/e1")
        self.assertIn("Not planted in hypar: boom", sent[1]["message"])


if __name__ == "__main__":
    unittest.main()
