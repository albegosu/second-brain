"""A repository whose README has no media falls back to its homepage, with the
homepage's computed CSS (no network: the API, screenshot and CSS are stubbed)."""
import unittest
from pathlib import Path
from unittest import mock

from worker import pipeline


class Response:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


REPO = {"full_name": "someone/tool", "owner": {"login": "someone"}, "description": "A tool",
        "default_branch": "main", "homepage": "https://tool.example"}


def get(url, **kwargs):
    return Response(200, REPO) if url.endswith("/someone/tool") else Response(200, text="# Tool\n\nNo images here.")


class HomepageCss(unittest.TestCase):
    def fetch(self, css):
        with mock.patch.object(pipeline.httpx, "get", side_effect=get), \
             mock.patch.object(pipeline, "screenshot", return_value=Path("shot.jpg")), \
             mock.patch.object(pipeline, "chrome", return_value="chrome"), \
             mock.patch.object(pipeline.page_css, "read", return_value=css) as read:
            return pipeline.fetch_github("https://github.com/someone/tool", 7), read

    def test_homepage_css_is_kept(self):
        css = {"palette": [{"hex": "#111111"}], "radius": "sharp", "lines": ["- font: Inter 16px"]}
        result, read = self.fetch(css)
        read.assert_called_once_with("https://tool.example", "chrome")
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["css"], css)

    def test_no_css_no_key(self):
        result, _ = self.fetch(None)
        self.assertEqual(result["kind"], "image")
        self.assertNotIn("css", result)


if __name__ == "__main__":
    unittest.main()
