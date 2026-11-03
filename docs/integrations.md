# Integrations

Other agents over MCP, hypar for the ideas a capture gives you, and push
notifications on your phone. Back to the [README](../README.md).

## Other agents (MCP)

Claude Code reads the wiki through the skill. Clients that don't load skills
(Claude Desktop, Cursor, Windsurf, Zed…) can read it over MCP:
`bin/second-brain-mcp` is a read-only server on stdio, with no dependencies
beyond the engine's. It reads `BRAIN_WIKI` from `.env` and only reads that
folder: no tool writes, calls a model or reaches the network, so the private
wiki goes nowhere except to the client you connect.

| Tool | What it returns |
|---|---|
| `get_index` | The map: topics, what each holds, uses, latest captures |
| `search` | Topic pages and source notes that mention some words, best first |
| `get_topic` | A topic page by title or slug |
| `get_page` | Any wiki page by its path: a source note, `taste.md`, `DESIGN.md`… |
| `recent_captures` | The latest captures, newest first, with their links |
| `get_frames` | What a visual capture looked like, as an image |
| `get_design_md` | The taste (or its light or dark twin), or a style or one of its looks, as a DESIGN.md |

### Connect your agents

`bin/connect` finds the agents installed on your computer and connects each one
the way it reads the wiki best (`bin/setup` runs it at the end):

| Agent | How | Where |
|---|---|---|
| Claude Code | The skill, linked | `~/.claude/skills/second-brain` |
| Cursor | MCP | `~/.cursor/mcp.json` |
| Codex | MCP | `~/.codex/config.toml` (or `$CODEX_HOME`) |
| Claude Desktop | MCP | `claude_desktop_config.json` in Claude's settings folder |
| Windsurf | MCP | `~/.codeium/windsurf/mcp_config.json` |
| VS Code | MCP | `mcp.json` in VS Code's user settings folder |
| Gemini CLI | MCP | `~/.gemini/settings.json` |

```bash
bin/connect                  # lists your agents and connects the ones that aren't, asking for each
bin/connect cursor codex     # only these
bin/connect --status         # the list, without changing anything
bin/connect --remove cursor  # disconnects one
```

It writes or removes only its own `second-brain` entry: other servers and
settings stay, and the file keeps its permissions. A file it can't parse, such
as a JSON with comments, is left alone. An entry that points at another engine
folder, because the engine moved, shows as stale and gets the current path,
keeping anything else it says, such as an `env`.

For any other client (Zed, for one), `bin/connect other` prints the snippet to
paste into its MCP settings, with this engine's path:

```json
{
  "mcpServers": {
    "second-brain": { "command": "/Users/you/Developer/second-brain/bin/second-brain-mcp" }
  }
}
```

The server tells the client how to use the wiki (index first, frames before
building a look), the way the skill does. It doesn't record uses: that stays
with the skill. ChatGPT only connects to remote MCP servers, which would mean
putting the wiki on the internet, so it isn't supported.

## hypar

[hypar](https://github.com/albegosu/hypar) is a garden for your own ideas: each
one starts as a one-sentence seed and an agent challenges it. When a capture
gives you an idea, share it as **Idea to grow** and write the idea as the note.
The capture is filed as usual, and the worker then plants the note in your
hypar garden as a latent embryo, with the original link and the source note
beside it.

- **The seed is your note**, never the model's summary. Without a note nothing
  is planted, and the notification says so.
- **What goes to hypar:** the note (the seed), the post URL, the source note's
  GitHub URL (it only opens for people who can read the wiki repository) and
  the capture's essence: its title and summary and the source note's *What it
  shows*, *Key ideas* and *Visual style* sections, so hypar's agent knows what
  sparked the idea. Quoted post and page text never leave the wiki.
- **The index follows.** After every capture and lint pass the worker also
  sends `index.md` (topic and item names with their summaries); hypar keeps the
  latest one, for its agent to use later as contrast.
- **Sharing again fills in** what an embryo planted earlier is missing, such as
  the essence, without planting a second one.
- **A failure doesn't lose the capture.** It is already filed; the notification
  says hypar couldn't be reached. Share it again later: hypar ignores a URL it
  already has, so nothing is planted twice. A failed index push is only logged.
- `--reanalyze` never plants.

To connect it, create a token in hypar under **Settings → integrations** and add
both values to the wiki repository (the capture workflow already passes them):

```bash
gh secret set HYPAR_URL -R <owner>/second-brain-wiki     # e.g. https://hypar.example.com
gh secret set HYPAR_TOKEN -R <owner>/second-brain-wiki   # hyp_…
```

A wiki repository created before this needs the two `HYPAR_*` lines of
[capture.yml](../templates/wiki-repo/.github/workflows/capture.yml) and
[lint.yml](../templates/wiki-repo/.github/workflows/lint.yml) in its own workflows.

## Phone notifications

The inbox answers instantly (`queued`), so the Shortcut can't know how the
analysis went. With `NTFY_TOPIC` set, the worker sends a push through
[ntfy](https://ntfy.sh) when each Shortcut capture is done: where it was filed
(category and topic, or a new topic) with a summary, or the error. Tapping it
opens the original. Install the ntfy app and subscribe to the topic.

The topic is the only protection, because anyone who knows it can read the
notifications. Make it long and random: `second-brain-$(openssl rand -hex 12)`.
Only the title, the summary and the URL go to ntfy.sh.
