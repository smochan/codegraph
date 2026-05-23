# Recording guide — how the visual assets are produced

All four README visual assets are reproducible from a clean clone:

| Asset | Path | Producer |
|---|---|---|
| Hero benchmark chart | `docs/images/hero_benchmark.png` | `scripts/render_hero_benchmark.py` |
| MOAT diagram | `docs/images/moat.png` + `moat-light.svg` + `moat-dark.svg` | `docs/diagrams/moat.mmd` via Mermaid CLI |
| DF4 trace GIF | `docs/images/df4_trace.gif` | 9 dashboard frames captured via Playwright + assembled by `scripts/assemble_df4_gif.py` |
| MCP response card | `docs/images/mcp_output_card.png` | Real `find_symbol` MCP response rendered via an HTML template + Playwright screenshot |

The DF4 GIF and MCP card were originally tagged as "user-side capture" tasks. They're now automated end-to-end. The detailed steps below are kept for re-capture with different framing or against a different target repo.

---

## 1. DF4 cross-stack trace screencast → `docs/images/df4_trace.gif`

**What it should show:** the dashboard's argument-flow timeline as `user_id` travels frontend → handler → service → SQL, with the rename annotations highlighted at each hop.

### Tooling

Pick one screen-recording tool:

| Tool | Cost | OS | Notes |
|---|---|---|---|
| **CleanShot X** | $30 one-time | macOS | Best polish, built-in GIF export, mouse-highlight, cursor-zoom. Recommended if you're on Mac. |
| **OBS Studio** | Free | macOS / Windows / Linux | More setup, more control, no built-in GIF (use `ffmpeg` or `gifski` after). |
| **ScreenToGif** | Free | Windows | Single binary. Good GIF editor built in. |
| **Kap** | Free | macOS | Lightweight, direct GIF export, mouse-highlight. Good free alternative to CleanShot. |

Then for high-quality GIF encoding (lower file size + sharper output than ffmpeg defaults):

```bash
brew install gifski        # macOS
# OR pipx install gifski
```

### Record

```bash
# Terminal 1 — make sure cross-stack-demo has a fresh graph
codegraph build --no-incremental --root examples/cross-stack-demo

# Terminal 2 — open the dashboard against the demo repo
cd examples/cross-stack-demo
codegraph serve
# opens http://127.0.0.1:8765
```

In the browser:

1. Switch to **Architecture view**.
2. Click the `POST /users` (or any handler) node — Learn Mode lifecycle modal opens.
3. Pick the `user_id` parameter from the dropdown.
4. Watch the timeline animate through fetch → handler → service → repo → SQL with `userId → user_id → id` rename annotations.

### Crop + export

Target frame: **1200 × 750** or **1600 × 900** (16:10-ish, mobile-readable). Crop tightly around the timeline animation — no browser chrome, no terminal.

Encoding target:

- **GIF**, not MP4 (GitHub auto-mutes MP4 thumbnails in some clients, GIF always plays inline).
- **≤ 8 seconds**, **≤ 2 MB**. If the recording is longer, trim the silent intro / outro.
- 12-15 fps is enough for a UI animation. Avoid 30+ fps — bloats file size.

If you're using OBS / ffmpeg path:

```bash
# Convert MP4 → high-quality GIF via gifski (best output)
gifski --width 1200 --fps 14 --quality 85 -o df4_trace.gif df4_trace.mp4

# Fallback via ffmpeg
ffmpeg -i df4_trace.mp4 -vf "fps=14,scale=1200:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=sierra2_4a" df4_trace.gif
```

Drop the result at:

```
docs/images/df4_trace.gif
```

Then in `README.md`, find the "What you can do" table row with `![arg_flow]` and change the screenshot reference to `df4_trace.gif`. (Or commit `df4_trace.gif` as a *replacement* image at the existing `arg_flow.png` path if you'd rather not touch the README table — but the explicit filename swap is clearer.)

---

## 2. MCP-in-Claude screenshot → `docs/images/mcp_in_claude.png`

**What it should show:** a single real turn in Claude Code where the user asks a polycodegraph-shaped question and Claude calls a polycodegraph MCP tool — with the tool call AND the tool result visible.

### Setup

You should already have polycodegraph registered in `~/.claude.json` (see README's Install & Use section). If not:

```jsonc
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve"]
    }
  }
}
```

Then in a Claude Code session inside the polycodegraph repo (so the MCP server finds `.codegraph/graph.db`):

### Suggested prompt

```
Trace GET /api/users/{user_id} from the frontend fetch to the database in this codebase.
```

Claude should call `mcp__codegraph__dataflow_trace` (or `dataflow_trace`) and return the ordered hops. The screenshot should show:

1. The user's question
2. The tool call (`dataflow_trace` with the route arg)
3. The tool result (the hops)
4. Claude's prose response

### Capture

- **macOS native:** `Cmd + Shift + 4` then `Space` then click the Claude Code window — captures the whole window with shadow. Quickest path.
- **CleanShot X (recommended):** lets you crop to just the relevant turn + add a subtle drop shadow + adjust contrast.

Target dimensions: **1400 × 900** (close-to-16:10). PNG, ≤ 500 KB. Crop **tight** to just the one turn — no sidebar, no unrelated chat history.

Drop the result at:

```
docs/images/mcp_in_claude.png
```

Then in `README.md`, find the 4th row of "What you can do":

```markdown
| _coming soon_ | **MCP tools in Claude Code** — Ask Claude ...
```

…and change `_coming soon_` to `![mcp_in_claude](docs/images/mcp_in_claude.png)`.

---

## Optional: regenerate the hero benchmark image

If you re-run the agent bench and want the hero image to track the new numbers:

```bash
# 1. update bench/RESULTS_AGENT_LATEST.md by re-running:
codegraph bench agent
cp bench/results/<latest-run-id>/RESULTS_AGENT.md bench/RESULTS_AGENT_LATEST.md
cp bench/results/<latest-run-id>/agent_raw.jsonl bench/agent_raw_latest.jsonl

# 2. update the ROWS list at the top of scripts/render_hero_benchmark.py
#    to match the new totals.

# 3. regenerate:
.venv/bin/python scripts/render_hero_benchmark.py
```

The script is the source of truth for the image — no manual editing.

---

## Optional: regenerate the MOAT diagram

If you tweak the inputs / outputs list:

```bash
# Edit docs/diagrams/moat.mmd, then:
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/diagrams/moat.mmd -o docs/images/moat-light.svg -t default -b transparent
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/diagrams/moat.mmd -o docs/images/moat-dark.svg  -t dark    -b transparent
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/diagrams/moat.mmd -o docs/images/moat.png       -t default -b white -w 1600
```

---

## Once both assets are in, the LinkedIn post is unblocked

`bench/LINKEDIN_POST.md` Version E will land after this guide is committed and the two assets are captured. The post's image attachment is `hero_benchmark.png`; the post's video attachment is `df4_trace.gif`.
