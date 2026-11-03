#!/usr/bin/env python3
"""Connects your coding agents to the wiki: one command instead of a config file each.

    bin/connect                  # lists your agents and connects the ones that aren't, asking for each
    bin/connect cursor codex     # only these
    bin/connect --status         # the list, without changing anything
    bin/connect --remove cursor  # disconnects one
    bin/connect other            # the snippet for any other client that reads an mcp.json

Claude Code gets the skill, linked into ~/.claude/skills: it reads the wiki with
its own tools and records what a build used. Every other agent gets the
read-only MCP server (bin/second-brain-mcp) in its own config file, as the
"second-brain" server. Only that entry is written or removed: other servers and
settings stay, the file keeps its permissions, and a file that doesn't parse (a
JSON with comments) is left alone, with the snippet to paste by hand. An entry
that points at another engine folder, because the engine moved, is stale and
gets the current path, keeping the rest of what it says (an `env`, say).

Standard library only, so bin/setup runs it before the virtualenv exists.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+; older ones only skip the check that a config.toml parses
except ImportError:
    tomllib = None

NAME = "second-brain"
ENGINE = Path(__file__).resolve().parent.parent
SKILL = ENGINE / "skill" / NAME
SERVER = ENGINE / "bin" / "second-brain-mcp"
DEFAULT_WIKI = Path.home() / "Developer" / "second-brain-wiki" / "wiki"  # where the skill looks without BRAIN_WIKI

CONNECTED, STALE, MISSING, ABSENT, LOCKED = "connected", "stale", "not connected", "not installed", "left alone"


class Skip(Exception):
    """An agent this run can't change, and why."""


@dataclass
class Agent:
    key: str        # its name on the command line
    name: str
    path: Path      # the skill link, or the config file that lists MCP servers
    folder: Path    # exists once the agent is installed
    kind: str       # "skill", "json" or "toml"
    servers: str = "mcpServers"                # json: the key that holds the servers
    extra: dict = field(default_factory=dict)  # json: what the client needs besides the command


def agents(home: Path | None = None, system: str | None = None, env: dict | None = None) -> list[Agent]:
    """Every agent this knows, with this computer's paths (the arguments are for tests)."""
    home = home or Path.home()
    system = system or platform.system()
    env = os.environ if env is None else env
    if system == "Darwin":
        config = home / "Library" / "Application Support"
    elif system == "Windows":
        config = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    else:
        config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    codex = Path(env.get("CODEX_HOME") or home / ".codex")
    return [
        Agent("claude-code", "Claude Code", home / ".claude" / "skills" / NAME, home / ".claude", "skill"),
        Agent("cursor", "Cursor", home / ".cursor" / "mcp.json", home / ".cursor", "json"),
        Agent("codex", "Codex", codex / "config.toml", codex, "toml"),
        Agent("claude-desktop", "Claude Desktop", config / "Claude" / "claude_desktop_config.json",
              config / "Claude", "json"),
        Agent("windsurf", "Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json",
              home / ".codeium" / "windsurf", "json"),
        Agent("vscode", "VS Code", config / "Code" / "User" / "mcp.json", config / "Code" / "User", "json",
              servers="servers", extra={"type": "stdio"}),
        Agent("gemini", "Gemini CLI", home / ".gemini" / "settings.json", home / ".gemini", "json"),
    ]


def short(path: Path | str) -> str:
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if text.startswith(home + os.sep) else text


# ---------------------------------------------------------------- reading and writing config files

def read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def write(path: Path, text: str):
    """Atomically, through a symlinked config (dotfiles) to its target, keeping the file's permissions:
    a config can hold other servers' keys."""
    path = path.resolve() if path.is_symlink() else path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".second-brain.tmp")
    tmp.write_text(text)
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def read_json(agent: Agent) -> tuple[dict, dict]:
    """The config and its servers object, created empty when missing."""
    text = read(agent.path)
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as e:
        raise Skip(f"{short(agent.path)} isn't plain JSON ({e.msg}, line {e.lineno}): paste the snippet by hand")
    servers = data.setdefault(agent.servers, {}) if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise Skip(f"{short(agent.path)} has an unexpected shape: paste the snippet by hand")
    return data, servers


def dump_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# A TOML file is edited as text, so comments and layout survive: the [mcp_servers.second-brain] table
# and its sub-tables ([mcp_servers.second-brain.env]) run from their header to the next one.
TABLE = re.compile(r"""^\s*\[\s*mcp_servers\s*\.\s*(?:second-brain|"second-brain"|'second-brain')\s*(\.[^\]]*)?\]""")
HEADER = re.compile(r"^\s*\[")
COMMAND = re.compile(r"""^\s*command\s*=\s*("(?:[^"\\]|\\.)*"|'[^']*')""")


def toml_tables(lines: list[str]) -> list[tuple[int, int, bool]]:
    """(start, end, is the main table) line ranges of the second-brain table and its sub-tables."""
    out, start, main = [], None, False
    for i, line in enumerate(lines):
        if HEADER.match(line):
            if start is not None:
                out.append((start, i, main))
                start = None
            if m := TABLE.match(line):
                start, main = i, not m.group(1)
    if start is not None:
        out.append((start, len(lines), main))
    return out


def toml_command(agent: Agent) -> str | None:
    """What the entry runs: None without one, "" for an entry without a command."""
    text = read(agent.path)
    tables = toml_tables(text.splitlines())
    if tomllib:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise Skip(f"{short(agent.path)} doesn't parse ({e}): paste the snippet by hand")
        if NAME in (data.get("mcp_servers") or {}) and not tables:
            raise Skip(f"{short(agent.path)} defines {NAME} inline: change it by hand")
    lines = text.splitlines()
    for start, end, main in tables:
        if main:
            for line in lines[start + 1:end]:
                if m := COMMAND.match(line):
                    value = m.group(1)
                    return json.loads(value) if value.startswith('"') else value[1:-1]
            return ""
    return None


def toml_connected(text: str) -> str:
    lines = text.splitlines()
    command = f"command = {json.dumps(str(SERVER), ensure_ascii=False)}"
    for start, end, main in toml_tables(lines):
        if main:
            at = next((i for i in range(start + 1, end) if COMMAND.match(lines[i])), None)
            if at is None:
                lines.insert(start + 1, command)
            else:
                lines[at] = command
            return "\n".join(lines) + "\n"
    body = text.rstrip("\n")
    return (body + "\n\n" if body else "") + f"[mcp_servers.{NAME}]\n{command}\n"


def toml_removed(text: str) -> str:
    lines = text.splitlines()
    for start, end, _ in reversed(toml_tables(lines)):
        del lines[start:end]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
    return body + "\n" if body else ""


# ---------------------------------------------------------------- one agent

def target(agent: Agent) -> str:
    return str(SKILL.resolve()) if agent.kind == "skill" else str(SERVER)


def current(agent: Agent) -> str | None:
    """What the agent's second-brain entry points at now, None without one. Raises Skip."""
    if agent.kind == "skill":
        if agent.path.is_symlink():
            return str(agent.path.resolve())
        if agent.path.exists():
            raise Skip(f"{short(agent.path)} is a folder, not a link to this engine's skill")
        return None
    if agent.kind == "toml":
        return toml_command(agent)
    _, servers = read_json(agent)
    entry = servers.get(NAME)
    return None if entry is None else str(entry.get("command", "")) if isinstance(entry, dict) else ""


def status(agent: Agent) -> tuple[str, str]:
    """(state, detail): the detail is where a stale entry points, or why a file is left alone."""
    if not agent.folder.exists() and not agent.path.exists() and not agent.path.is_symlink():
        return ABSENT, ""
    try:
        now = current(agent)
    except Skip as e:
        return LOCKED, str(e)
    if now is None:
        return MISSING, ""
    return (CONNECTED, "") if now == target(agent) else (STALE, now)


def connect(agent: Agent) -> str:
    state, detail = status(agent)
    if state == ABSENT:
        raise Skip(f"{agent.name} isn't installed here")
    if state == LOCKED:
        raise Skip(detail)
    if state == CONNECTED:
        return "already connected"
    if agent.kind == "skill":
        if agent.path.is_symlink():
            agent.path.unlink()
        agent.path.parent.mkdir(parents=True, exist_ok=True)
        agent.path.symlink_to(SKILL)
    elif agent.kind == "toml":
        write(agent.path, toml_connected(read(agent.path)))
    else:
        data, servers = read_json(agent)
        entry = servers.get(NAME) if isinstance(servers.get(NAME), dict) else {}
        servers[NAME] = {**agent.extra, **entry, "command": str(SERVER)}
        write(agent.path, dump_json(data))
    return f"updated, was {short(detail) or 'without a command'}" if state == STALE else "connected"


def remove(agent: Agent) -> str:
    state, detail = status(agent)
    if state == LOCKED:
        raise Skip(detail)
    if state in (ABSENT, MISSING):
        return "wasn't connected"
    if agent.kind == "skill":
        agent.path.unlink()
    elif agent.kind == "toml":
        write(agent.path, toml_removed(read(agent.path)))
    else:
        data, servers = read_json(agent)
        del servers[NAME]
        write(agent.path, dump_json(data))
    return "disconnected"


def snippet() -> str:
    return dump_json({"mcpServers": {NAME: {"command": str(SERVER)}}}).rstrip("\n")


# ---------------------------------------------------------------- what bin/connect and bin/setup print

def line(agent: Agent) -> str:
    state, detail = status(agent)
    how = "skill" if agent.kind == "skill" else "MCP"
    text = {CONNECTED: f"connected ({how})",
            STALE: f"stale ({how}): points at {short(detail) or 'nothing'}",
            MISSING: f"not connected · {short(agent.path)}",
            ABSENT: "not installed",
            LOCKED: f"left alone: {detail}"}[state]
    return f"    {agent.name:<15} {text}"


def env_wiki(env_file: Path = ENGINE / ".env") -> Path | None:
    """BRAIN_WIKI as the engine's .env sets it: what the MCP server reads."""
    for text in read(env_file).splitlines():
        if m := re.match(r"\s*(?:export\s+)?BRAIN_WIKI\s*=\s*(.*)", text):
            return Path(m.group(1).strip().strip("'\"")).expanduser()
    return None


def notes(done: list[Agent]) -> list[str]:
    """What still stands between the agents just connected and the wiki."""
    out, wiki = [], env_wiki()
    if any(a.kind != "skill" for a in done):
        if not (ENGINE / ".venv" / "bin" / "python").exists():
            out.append("the MCP server runs in the engine's virtualenv, which isn't there yet: "
                       "see docs/self-hosting.md#install-the-worker-locally")
        if wiki is None:
            out.append(f"the MCP server reads the wiki from BRAIN_WIKI in {short(ENGINE / '.env')}, which isn't set")
    if any(a.kind == "skill" for a in done) and wiki and wiki.resolve() != DEFAULT_WIKI.resolve():
        out.append(f"the skill looks in {short(DEFAULT_WIKI)} unless BRAIN_WIKI is set where your agent runs")
    return out


def confirm(prompt: str, default: bool = True) -> bool:
    if not sys.stdin.isatty():
        return default
    answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer.startswith("y")


def offer(ask=confirm, known: list[Agent] | None = None) -> list[Agent]:
    """Lists the agents, then connects each installed one that isn't (or is stale), asking first.
    Without a terminal it connects them all. bin/setup calls this."""
    known = known if known is not None else agents()
    for agent in known:
        print(line(agent))
    done = []
    for agent in known:
        state, _ = status(agent)
        if state in (MISSING, STALE) and ask(f"    {'Update' if state == STALE else 'Connect'} {agent.name}?"):
            print(f"    {agent.name}: {connect(agent)}")
            done.append(agent)
    if all(status(a)[0] == ABSENT for a in known):
        print("    No agent found here: `bin/connect other` prints the snippet for any MCP client")
    for note in notes(done):
        print(f"    note: {note}")
    return done


def main(argv: list[str] | None = None) -> int:
    known = agents()
    keys = [a.key for a in known]
    ap = argparse.ArgumentParser(prog="bin/connect", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agents", nargs="*", metavar="agent", help=f"{', '.join(keys)} or other (default: all)")
    ap.add_argument("--status", action="store_true", help="only list the agents and how they are connected")
    ap.add_argument("--remove", action="store_true", help="disconnect the agents named")
    args = ap.parse_args(argv)
    unknown = [k for k in args.agents if k not in keys and k != "other"]
    if unknown:
        ap.error(f"unknown agent {', '.join(unknown)}: choose from {', '.join(keys)} or other")
    named = [a for a in known if a.key in args.agents]
    if "other" in args.agents:
        print(f"Paste this into the client's MCP settings (its servers key may be named differently):\n{snippet()}")
        if not named:
            return 0
    if args.status:
        for agent in known:
            print(line(agent))
        return 0
    if args.remove and not named:
        ap.error("--remove needs the agents to disconnect")
    if not named:
        offer()
        return 0
    done, failed = [], False
    for agent in named:
        try:
            print(f"    {agent.name}: {(remove if args.remove else connect)(agent)}")
            done.append(agent)
        except Skip as e:
            print(f"    {agent.name}: {e}")
            failed = True
    for note in [] if args.remove else notes(done):
        print(f"    note: {note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
