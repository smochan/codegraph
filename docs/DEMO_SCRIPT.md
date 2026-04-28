# Launch Demo Script

Storyboard for the 45-second landscape MP4 and the 5-second silent square
loop that go with the v0.1.0 LinkedIn launch post.

---

## What this demo proves

The single sentence: **"You can pick a function, see exactly which DB
column it touches, and watch the parameter travel from the React fetch all
the way to the SQL query."**

Watching it should feel like reading a flow chart — *not* like reading
graph theory. The hero moment is the chip click + travelling token.

---

## Hardware / setup

- Screen: 1920 × 1080 logical, recorded at 1× scale.
- Browser: Chrome / Brave, dark theme. Hide bookmark bar. Zoom 110%.
- Terminal: Ghostty / iTerm with a high-contrast theme. Font ~16pt.
- OBS preset: 1920×1080, 30 fps, MP4 (H.264). Audio: built-in mic, light
  noise gate.

Demo repo seed:

```bash
cd /media/mochan/Files/projects/codegraph
.venv/bin/codegraph build --no-incremental --root examples/cross-stack-demo
.venv/bin/codegraph serve
# in another terminal: open http://127.0.0.1:8765
```

---

## 45-second landscape MP4 — shot list

> Voice-over kept tight. Captions on for muted-autoplay viewers. Each
> beat is timed; total budget 45 sec.

| t | Visual | Voice-over (or caption) |
|---|---|---|
| 0:00 – 0:03 | Terminal: `codegraph build` runs, output scrolls past, "169 files / 8.7s" | "Codegraph builds a graph of your codebase in seconds." |
| 0:03 – 0:06 | Cut to dashboard Architecture tab. Endpoint list with method-coloured pills. Cursor hovers `GET /api/users/{user_id}`. | "Here are every backend route it found, classified by HTTP method." |
| 0:06 – 0:10 | Click the endpoint. Learn Mode modal animates open. TCP / TLS / HTTP phases pulse left-to-right. | "Click any endpoint and codegraph walks you through the full request lifecycle…" |
| 0:10 – 0:14 | Phase 4 lights up. Five swimlane rows appear: COMPONENT → HANDLER → SERVICE → REPO → DB. One arrow per hop, each labelled with arg names. | "…down to the actual handler, service, repository, and SQL query in YOUR code." |
| 0:14 – 0:18 | Cursor moves to the chip strip. Picker shows `user_id` as a single chip in amber. | "Now pick a parameter…" |
| 0:18 – 0:25 | Click the chip. Phase 4 redraws with `user_id` highlighted at every hop where it appears. The diagram view's animated dot travels along the bezier path. | "…and watch it travel through every layer that uses it." |
| 0:25 – 0:30 | Switch to a handler with a rename: `userId` in fetch body → `user_id` in service. Highlight follows; small `(was userId)` annotation surfaces inline. | "Even when names get renamed across layers, codegraph tracks them." |
| 0:30 – 0:35 | Cut back to terminal: `codegraph dataflow trace "GET /api/users/{user_id}" --format markdown` produces the exact same chain. | "Same data, available in your terminal — and in your AI assistant via MCP." |
| 0:35 – 0:40 | Cut to Claude Code (or Cursor) prompt: "What does the user_id parameter touch?" → response cites the trace inline. | "Now your agent can reason over flow, not just files." |
| 0:40 – 0:45 | End card: codegraph logo, `pip install codegraph-py`, GitHub URL. | "v0.1.0 just shipped. Open source. Link in comments." |

---

## 5-second silent square (1080×1080) — for LinkedIn auto-play

Trim the clearest 5 seconds of the chip-click + travelling-dot animation
(roughly 0:18 – 0:23 from the master). Crop to square; punch in slightly
on Phase 4 so the swimlanes fill the frame.

```bash
ffmpeg -ss 18 -t 5 -i master.mp4 \
  -vf "crop=1080:1080:(in_w-1080)/2:(in_h-1080)/2,scale=1080:1080" \
  -an -c:v libx264 -crf 18 -preset slow square-loop.mp4
```

`-an` strips audio. `crf 18` keeps the file under ~5 MB.

---

## Captions / subtitle file (`.vtt`)

For LinkedIn auto-play (silent), upload a WebVTT file alongside the MP4.

```vtt
WEBVTT

00:00.000 --> 00:03.500
Codegraph builds a graph of your codebase in seconds.

00:03.500 --> 00:06.500
Here are every backend route it found, classified by HTTP method.

00:06.500 --> 00:10.000
Click any endpoint to walk through the full request lifecycle…

00:10.000 --> 00:14.000
…down to the actual handler, service, and SQL query in your code.

00:14.000 --> 00:18.000
Pick a parameter…

00:18.000 --> 00:25.000
…and watch it travel through every layer that uses it.

00:25.000 --> 00:30.000
Even when names get renamed across layers, codegraph tracks them.

00:30.000 --> 00:35.000
Same data, available in your terminal — and in your AI assistant via MCP.

00:35.000 --> 00:40.000
Now your agent can reason over flow, not just files.

00:40.000 --> 00:45.000
v0.1.0 — open source. pip install codegraph-py.
```

---

## Common recording snags

- **Modal closes when you click outside it.** Keep the cursor inside the
  modal frame between hops.
- **Phase 4 hop labels overflow on small screens.** Use 1920×1080 logical;
  don't record at 1× retina (4K).
- **Browser auto-fill / extension overlays.** Use a fresh Chrome profile
  with no extensions for the recording.
- **Theme flicker between light/dark.** Pin one theme via the dashboard's
  toggle before starting; don't switch mid-recording.
- **Audio drift in long takes.** Restart OBS between takes — long sessions
  drift A/V sync.

---

## Where to put the finished files

`docs/launch-assets/` (locally; gitignored). Don't commit binaries to the
repo. Upload the MP4 directly to LinkedIn's video uploader, and link the
unlisted YouTube fallback URL in the post body.
