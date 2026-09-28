"""The model call through OpenAI-compatible providers (no network)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import pipeline


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.is_error = payload, status, status >= 400
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class OpenAICompatible(unittest.TestCase):
    def call(self, provider, **kwargs):
        base = pipeline.PROVIDERS[provider][0]
        with mock.patch.multiple(pipeline, PROVIDER=provider, API_BASE=base, API_KEY="k",
                                 VLM=pipeline.PROVIDERS[provider][1]), \
             mock.patch.object(pipeline.httpx, "post",
                               return_value=Response({"choices": [{"message": {"content": "{}"}}]})) as post:
            out = pipeline.chat("sys", "user", **kwargs)
        return out, post.call_args

    def test_request_shape_with_an_image(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "frame.png"
            img.write_bytes(b"\x89PNG fake")
            out, call = self.call("openai", images=[img], as_json=True)
        self.assertEqual(out, "{}")
        self.assertEqual(call.args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(call.kwargs["headers"], {"Authorization": "Bearer k"})
        body = call.kwargs["json"]
        self.assertEqual(body["model"], "gpt-4.1-mini")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["messages"][0], {"role": "system", "content": "sys"})
        parts = body["messages"][1]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "user"})
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_anthropic_skips_response_format(self):
        _, call = self.call("anthropic", as_json=True)
        self.assertEqual(call.args[0], "https://api.anthropic.com/v1/chat/completions")
        self.assertNotIn("response_format", call.kwargs["json"])

    def test_error_names_the_provider(self):
        with mock.patch.multiple(pipeline, PROVIDER="gemini", API_BASE="https://x", API_KEY="k", VLM="m"), \
             mock.patch.object(pipeline.httpx, "post", return_value=Response({"error": "bad key"}, 401)):
            with self.assertRaisesRegex(RuntimeError, "gemini m: 401"):
                pipeline.chat("s", "u")


if __name__ == "__main__":
    unittest.main()
