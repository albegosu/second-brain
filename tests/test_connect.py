"""bin/connect on a throwaway home folder: detection, connecting, stale paths, removing, files it leaves alone."""
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from worker import connect as c

SERVER = str(c.SERVER)
OLD = "/old/place/second-brain/bin/second-brain-mcp"


class Connect(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()

    def agent(self, key, system="Darwin", env=None):
        return next(a for a in c.agents(self.home, system, env or {}) if a.key == key)

    def install(self, agent):
        agent.folder.mkdir(parents=True, exist_ok=True)
        return agent

    # ------------------------------------------------------------ detection

    def test_only_installed_agents_count(self):
        self.install(self.agent("cursor"))
        states = {a.key: c.status(a)[0] for a in c.agents(self.home, "Darwin", {})}
        self.assertEqual(states["cursor"], c.MISSING)
        self.assertEqual({k for k, s in states.items() if s != c.ABSENT}, {"cursor"})

    def test_paths_follow_the_system(self):
        mac = self.agent("claude-desktop", "Darwin").path
        linux = self.agent("claude-desktop", "Linux").path
        self.assertEqual(mac, self.home / "Library/Application Support/Claude/claude_desktop_config.json")
        self.assertEqual(linux, self.home / ".config/Claude/claude_desktop_config.json")
        self.assertEqual(self.agent("codex", env={"CODEX_HOME": "/elsewhere"}).path, Path("/elsewhere/config.toml"))

    def test_not_installed_is_not_created(self):
        agent = self.agent("cursor")
        with self.assertRaises(c.Skip):
            c.connect(agent)
        self.assertFalse(agent.folder.exists())

    # ------------------------------------------------------------ JSON clients

    def test_json_keeps_other_servers_and_settings(self):
        agent = self.install(self.agent("cursor"))
        agent.path.write_text(json.dumps({"mcpServers": {"figma": {"url": "https://figma"}}, "theme": "dark"}))
        self.assertEqual(c.connect(agent), "connected")
        data = json.loads(agent.path.read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["mcpServers"]["figma"], {"url": "https://figma"})
        self.assertEqual(data["mcpServers"]["second-brain"], {"command": SERVER})
        self.assertEqual(c.status(agent), (c.CONNECTED, ""))
        before = agent.path.read_text()
        self.assertEqual(c.connect(agent), "already connected")
        self.assertEqual(agent.path.read_text(), before)

    def test_new_config_file(self):
        agent = self.install(self.agent("claude-desktop"))
        c.connect(agent)
        self.assertEqual(json.loads(agent.path.read_text()), {"mcpServers": {"second-brain": {"command": SERVER}}})

    def test_stale_entry_gets_the_path_and_keeps_its_env(self):
        agent = self.install(self.agent("windsurf"))
        agent.path.parent.mkdir(parents=True, exist_ok=True)
        agent.path.write_text(json.dumps({"mcpServers": {"second-brain": {"command": OLD, "env": {"BRAIN_WIKI": "/w"}}}}))
        self.assertEqual(c.status(agent), (c.STALE, OLD))
        self.assertIn(OLD, c.connect(agent))
        entry = json.loads(agent.path.read_text())["mcpServers"]["second-brain"]
        self.assertEqual(entry, {"command": SERVER, "env": {"BRAIN_WIKI": "/w"}})

    def test_vscode_has_its_own_shape(self):
        agent = self.install(self.agent("vscode"))
        c.connect(agent)
        self.assertEqual(json.loads(agent.path.read_text()), {"servers": {"second-brain": {"type": "stdio", "command": SERVER}}})

    def test_json_with_comments_is_left_alone(self):
        agent = self.install(self.agent("cursor"))
        text = '// mine\n{"mcpServers": {}}\n'
        agent.path.write_text(text)
        self.assertEqual(c.status(agent)[0], c.LOCKED)
        with self.assertRaises(c.Skip):
            c.connect(agent)
        self.assertEqual(agent.path.read_text(), text)

    def test_remove_takes_only_its_entry(self):
        agent = self.install(self.agent("gemini"))
        agent.path.write_text(json.dumps({"mcpServers": {"figma": {"url": "x"}, "second-brain": {"command": SERVER}}}))
        self.assertEqual(c.remove(agent), "disconnected")
        self.assertEqual(json.loads(agent.path.read_text()), {"mcpServers": {"figma": {"url": "x"}}})
        self.assertEqual(c.remove(agent), "wasn't connected")

    def test_permissions_and_symlinked_configs_survive(self):
        agent = self.install(self.agent("cursor"))
        dotfiles = self.home / "dotfiles" / "mcp.json"
        dotfiles.parent.mkdir()
        dotfiles.write_text("{}")
        dotfiles.chmod(0o600)
        agent.path.symlink_to(dotfiles)
        c.connect(agent)
        self.assertTrue(agent.path.is_symlink())
        self.assertIn("second-brain", json.loads(dotfiles.read_text())["mcpServers"])
        self.assertEqual(stat.S_IMODE(dotfiles.stat().st_mode), 0o600)

    # ------------------------------------------------------------ Codex (TOML)

    def test_codex_appends_its_table_and_keeps_the_rest(self):
        agent = self.install(self.agent("codex"))
        agent.path.write_text('model = "o5"  # mine\n\n[mcp_servers.figma]\ncommand = "figma-mcp"\n')
        c.connect(agent)
        text = agent.path.read_text()
        self.assertTrue(text.startswith('model = "o5"  # mine\n\n[mcp_servers.figma]\ncommand = "figma-mcp"\n'))
        self.assertIn(f'[mcp_servers.second-brain]\ncommand = {json.dumps(SERVER)}\n', text)
        self.assertEqual(c.status(agent), (c.CONNECTED, ""))
        self.assertEqual(c.connect(agent), "already connected")

    def test_codex_stale_command_is_replaced_in_place(self):
        agent = self.install(self.agent("codex"))
        agent.path.write_text(f'[mcp_servers.second-brain]\ncommand = "{OLD}"\nstartup_timeout_sec = 20\n\n'
                              '[mcp_servers.second-brain.env]\nBRAIN_WIKI = "/w"\n\n[profiles.fast]\nmodel = "x"\n')
        self.assertEqual(c.status(agent), (c.STALE, OLD))
        c.connect(agent)
        self.assertEqual(agent.path.read_text(),
                         f'[mcp_servers.second-brain]\ncommand = {json.dumps(SERVER)}\nstartup_timeout_sec = 20\n\n'
                         '[mcp_servers.second-brain.env]\nBRAIN_WIKI = "/w"\n\n[profiles.fast]\nmodel = "x"\n')

    def test_codex_remove_takes_its_tables_only(self):
        agent = self.install(self.agent("codex"))
        agent.path.write_text(f'model = "o5"\n\n[mcp_servers.second-brain]\ncommand = "{SERVER}"\n\n'
                              '[mcp_servers.second-brain.env]\nBRAIN_WIKI = "/w"\n\n[mcp_servers.figma]\ncommand = "f"\n')
        self.assertEqual(c.remove(agent), "disconnected")
        self.assertEqual(agent.path.read_text(), 'model = "o5"\n\n[mcp_servers.figma]\ncommand = "f"\n')

    @unittest.skipUnless(c.tomllib, "needs tomllib (Python 3.11+)")
    def test_codex_inline_or_broken_is_left_alone(self):
        agent = self.install(self.agent("codex"))
        agent.path.write_text('[mcp_servers]\nsecond-brain = { command = "x" }\n')
        self.assertEqual(c.status(agent)[0], c.LOCKED)
        agent.path.write_text('model = \n')
        self.assertEqual(c.status(agent)[0], c.LOCKED)

    # ------------------------------------------------------------ Claude Code (the skill)

    def test_skill_link(self):
        agent = self.install(self.agent("claude-code"))
        self.assertEqual(c.connect(agent), "connected")
        self.assertEqual(agent.path.resolve(), c.SKILL.resolve())
        self.assertEqual(c.status(agent), (c.CONNECTED, ""))
        self.assertEqual(c.remove(agent), "disconnected")
        self.assertFalse(agent.path.is_symlink())

    def test_skill_link_to_a_moved_engine_is_stale(self):
        agent = self.install(self.agent("claude-code"))
        agent.path.parent.mkdir(parents=True)
        agent.path.symlink_to("/old/place/second-brain/skill/second-brain")
        self.assertEqual(c.status(agent)[0], c.STALE)
        c.connect(agent)
        self.assertEqual(agent.path.resolve(), c.SKILL.resolve())

    def test_a_copied_skill_folder_is_left_alone(self):
        agent = self.install(self.agent("claude-code"))
        agent.path.mkdir(parents=True)
        (agent.path / "SKILL.md").write_text("mine")
        self.assertEqual(c.status(agent)[0], c.LOCKED)
        with self.assertRaises(c.Skip):
            c.remove(agent)
        self.assertTrue((agent.path / "SKILL.md").exists())

    # ------------------------------------------------------------ what it prints

    def test_offer_connects_what_was_accepted(self):
        known = [self.install(self.agent(k)) for k in ("cursor", "codex")] + [self.agent("windsurf")]
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(c, "notes", return_value=[]):
            done = c.offer(lambda prompt: "Cursor" in prompt, known)
        self.assertEqual([a.key for a in done], ["cursor"])
        self.assertEqual(c.status(known[1])[0], c.MISSING)
        self.assertIn("not installed", out.getvalue())

    def test_notes_point_at_what_is_missing(self):
        mcp_agent, skill = self.agent("cursor"), self.agent("claude-code")
        with mock.patch.object(c, "env_wiki", return_value=None), mock.patch.object(c, "ENGINE", self.home):
            self.assertEqual(len(c.notes([mcp_agent])), 2)  # no virtualenv, no BRAIN_WIKI
        with mock.patch.object(c, "env_wiki", return_value=None), mock.patch.object(c, "ENGINE", self.home):
            self.assertEqual(c.notes([skill]), [])  # the skill reads the wiki without either

    def test_env_wiki_reads_the_env_file(self):
        env = self.home / ".env"
        env.write_text("OLLAMA_API_KEY=x\nexport BRAIN_WIKI='~/w/wiki'\n")
        self.assertEqual(c.env_wiki(env), Path("~/w/wiki").expanduser())
        self.assertIsNone(c.env_wiki(self.home / "missing"))

    def test_snippet_points_at_the_launcher(self):
        self.assertEqual(json.loads(c.snippet()), {"mcpServers": {"second-brain": {"command": SERVER}}})
        self.assertTrue(os.access(c.SERVER, os.X_OK))


if __name__ == "__main__":
    unittest.main()
