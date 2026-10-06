"""The MCP server on the synthetic wiki: protocol, tools and the stdio loop (no network, no model)."""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from worker import mcp
from worker import wiki

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sample-wiki"


def rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, **({"params": params} if params is not None else {})}


class McpServer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wiki = Path(tmp.name) / "wiki"
        shutil.copytree(FIXTURE, self.wiki)
        patcher = mock.patch.object(wiki, "WIKI", self.wiki)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tool(self, tool_name, /, **args):
        result = mcp.handle(rpc("tools/call", {"name": tool_name, "arguments": args}))["result"]
        texts = [c["text"] for c in result["content"] if c["type"] == "text"]
        return result, "\n".join(texts)

    # ------------------------------------------------------------ protocol

    def test_initialize_agrees_on_a_version(self):
        known = mcp.handle(rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}}))["result"]
        self.assertEqual(known["protocolVersion"], "2025-03-26")
        self.assertEqual(known["capabilities"], {"tools": {"listChanged": False}})
        self.assertIn("get_index", known["instructions"])
        future = mcp.handle(rpc("initialize", {"protocolVersion": "2099-01-01"}))["result"]
        self.assertEqual(future["protocolVersion"], mcp.PROTOCOLS[0])

    def test_tools_are_listed_read_only(self):
        tools = mcp.handle(rpc("tools/list"))["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], list(mcp.HANDLERS))
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["annotations"]["readOnlyHint"])
            self.assertFalse(t["annotations"]["openWorldHint"])

    def test_errors_and_notifications(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(mcp.handle(rpc("ping"))["result"], {})
        self.assertEqual(mcp.handle(rpc("nope/nope"))["error"]["code"], -32601)
        self.assertEqual(mcp.handle(rpc("tools/call", {"name": "rm", "arguments": {}}))["error"]["code"], -32602)
        self.assertEqual(mcp.handle({"id": 3, "method": "ping"})["error"]["code"], -32600)  # no jsonrpc field
        self.assertEqual(mcp.handle(rpc("resources/list"))["result"], {"resources": []})
        result, text = self.tool("search", query="serif", colour="red")
        self.assertTrue(result["isError"])
        self.assertIn("search takes query, category, limit", text)
        result, text = self.tool("get_topic")
        self.assertIn("missing name", text)

    def test_stdio_carries_only_protocol(self):
        lines = [json.dumps(rpc("initialize", {"protocolVersion": "2025-06-18"})),
                 json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                 "{not json", "",
                 json.dumps([rpc("ping", id_=2), rpc("tools/call", {"name": "get_design_md", "arguments": {}}, 3)])]
        out = io.StringIO()
        mcp.serve(io.StringIO("\n".join(lines) + "\n"), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(replies[0]["id"], 1)
        self.assertEqual(replies[1]["error"]["code"], -32700)
        self.assertEqual([r["id"] for r in replies[2]], [2, 3])
        self.assertTrue(replies[2][1]["result"]["content"][0]["text"].startswith("---\nversion: \"alpha\""))

    def test_the_module_runs_as_a_server(self):
        env = {**os.environ, "BRAIN_WIKI": str(self.wiki)}
        msgs = [rpc("initialize", {"protocolVersion": "2025-06-18"}),
                rpc("tools/call", {"name": "recent_captures", "arguments": {"limit": 2}}, 2)]
        done = subprocess.run([sys.executable, "-m", "worker.mcp"], cwd=ROOT, env=env, capture_output=True, text=True,
                              input="".join(json.dumps(m) + "\n" for m in msgs), timeout=60)
        replies = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertIn("#9 Palette Picker App", replies[1]["result"]["content"][0]["text"])
        self.assertIn("[mcp] serving", done.stderr)

    # ------------------------------------------------------------ tools

    def test_index_is_read_or_built_without_writing(self):
        _, text = self.tool("get_index")
        self.assertTrue(text.startswith("# Second brain"))
        self.assertIn("[Paper and Ink](design/style-paper-ink.md)", text)
        self.assertFalse((self.wiki / "index.md").exists())
        (self.wiki / "index.md").write_text("# Second brain\n\nthe stored one\n")
        self.assertEqual(self.tool("get_index")[1], "# Second brain\n\nthe stored one\n")

    def test_search(self):
        _, text = self.tool("search", query="serif headlines")
        first = text.splitlines()[2]
        self.assertEqual(first, "- design/style-paper-ink.md — Paper and Ink")  # a topic page with both words
        _, text = self.tool("search", query="terminal", category="tools")
        self.assertEqual(text, "Nothing in the wiki mentions 'terminal'.")
        _, text = self.tool("search", query="terminal neon")
        self.assertIn("(1 of 2 words)", text)
        self.assertTrue(self.tool("search", query="a")[0]["isError"])

    def test_topic_by_name(self):
        _, text = self.tool("get_topic", name="night console")
        self.assertIn('title: "Night Console"', text)
        self.assertIn('title: "Night Console"', self.tool("get_topic", name="design/style-night-console")[1])
        _, text = self.tool("get_topic", name="style")
        self.assertTrue(text.startswith("Several topics match"))
        self.assertTrue(self.tool("get_topic", name="carousel")[0]["isError"])

    def test_pages_stay_inside_the_wiki(self):
        _, text = self.tool("get_page", path="../sources/2026-01/0001-warm-paper-journal.md")
        self.assertIn('title: "Warm Paper Journal"', text)
        (self.wiki.parent / "secret.md").write_text("private")
        for bad in ("sources/../../secret.md", str(self.wiki.parent / "secret.md"), "design/style-paper-ink",
                    "design/nothing.md"):
            with self.subTest(bad):
                result, text = self.tool("get_page", path=bad)
                self.assertTrue(result["isError"])
                self.assertNotIn("private", text)

    def test_recent_captures(self):
        _, text = self.tool("recent_captures", limit=3)
        self.assertEqual([line.split(" · ")[1].split(" ")[0] for line in text.splitlines()], ["#9", "#8", "#7"])
        _, text = self.tool("recent_captures", category="tools")
        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("→ tools/color-pickers", text)

    def test_frames(self):
        note = next((self.wiki / "sources").glob("*/0001-*.md"))
        note.with_suffix(".jpg").write_bytes(b"\xff\xd8\xff\xe0 tiny jpeg")
        result = mcp.handle(rpc("tools/call", {"name": "get_frames", "arguments": {"capture": 1}}))["result"]
        self.assertFalse(result["isError"])
        image = result["content"][1]
        self.assertEqual((image["type"], image["mimeType"]), ("image", "image/jpeg"))
        self.assertEqual(base64.b64decode(image["data"]), b"\xff\xd8\xff\xe0 tiny jpeg")
        self.assertIn("isn't a visual capture", self.tool("get_frames", capture=2)[1])
        self.assertIn("no capture #99", self.tool("get_frames", capture=99)[1])

    def test_design_md(self):
        _, taste = self.tool("get_design_md")
        self.assertIn('name: "Taste"', taste)
        _, look = self.tool("get_design_md", style="paper-ink", look="cool grotesk")
        self.assertIn('name: "Paper and Ink: Cool Grotesk Variant"', look)
        self.assertIn("looks: Warm Paper Editorial; Cool Grotesk Variant",
                      self.tool("get_design_md", style="paper-ink", look="neon")[1])
        self.assertIn("look needs style", self.tool("get_design_md", look="x")[1])
        self.assertIn("don't split", self.tool("get_design_md", tone="dark")[1])
        self.assertIn("no style topic 'nope'", self.tool("get_design_md", style="nope")[1])
        (self.wiki / "DESIGN.md").write_text("---\nversion: \"alpha\"\n---\n\nthe weekly file\n")
        self.assertIn("the weekly file", self.tool("get_design_md")[1])
        self.assertIn("the weekly file", self.tool("get_design_md", tone="light")[1])  # light is the main tone


if __name__ == "__main__":
    unittest.main()
