"""The GitHub inbox's queue folder, as the worker reads it (no network, no model)."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import run


class QueueInbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.q = Path(self.dir.name)
        (self.q / "1-a.json").write_text(json.dumps({"url": "https://example.com/x", "note": "intent: Tool to try — n"}))
        (self.q / "2-b.json").write_text(json.dumps({"image": base64.b64encode(b"jpegbytes").decode(), "mime": "image/jpeg"}))
        (self.q / "3-c.json").write_text("{not json")
        self.patch = mock.patch.object(run, "QUEUE_DIR", str(self.q))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def test_pending_retry_claim(self):
        items = run.inbox("pending")
        self.assertEqual([i["id"] for i in items], ["1-a", "2-b", "3-c"])
        self.assertEqual(items[0]["url"], "https://example.com/x")
        self.assertEqual(items[1]["mime"], "image/jpeg")
        self.assertIsNone(items[2]["url"])
        self.assertEqual(run.fetch_inbox_image("2-b"), b"jpegbytes")
        run.inbox("retry", "1-a", "timeout")
        self.assertEqual(run.inbox("pending")[0]["attempts"], 1)
        run.inbox("claim", "1-a")
        self.assertFalse((self.q / "1-a.json").exists())

    def test_poll_files_and_removes(self):
        with mock.patch.object(run, "ingest", return_value={"text": "filed"}) as ingest, \
             mock.patch.object(run, "ingest_image", return_value={"text": "filed"}) as ingest_image, \
             mock.patch.object(run, "notify") as notify:
            self.assertEqual(run.poll_once(), 3)
        ingest.assert_called_once()
        self.assertEqual(ingest.call_args.args[1], "intent: Tool to try — n")
        self.assertEqual(ingest_image.call_args.args[0], b"jpegbytes")
        self.assertEqual(notify.call_count, 3)  # the broken file is reported, not retried forever
        self.assertEqual(list(self.q.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
