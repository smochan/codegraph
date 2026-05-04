# Launch Demo Script

Storyboard for the 45-second landscape MP4 and the 5-second silent square
loop that go with the v0.1.0 LinkedIn launch post.

---

## What this demo proves

The single sentence: **"Codegraph reads its own code, finds its own dead
code, and then watches a parameter travel from a React fetch all the way
to the SQL query in a real cross-stack app."**

Watching it should feel like reading a flow chart — *not* like reading
graph theory. The hero moments are:
1. The 3D focus view landing on `shape_hops_for_handler` — codegraph
   looking at the function that powers its own arg-flow visualizer.
2. The dead-code reveal (15 → 0 verified) on the self-graph.
3. The chip click + travelling token on `GET /api/users/{user_id}`.

---

## Hardware / setup

- Screen: 1920 × 1080 logical, recorded at 1× scale.
- Browser: Chrome / Brave, dark theme. Hide bookmark bar. Zoom 110%.
- Terminal: Ghostty / iTerm with a high-contrast theme. Font ~16pt.
- OBS preset: 1920×1080, 30 fps, MP4 (H.264). Audio: built-in mic, light
  noise gate.

Demo seeds — two graphs in two terminals, switched mid-take:

```bash
# Terminal A — codegraph analyzing itself (dogfood)
cd /media/mochan/Files/projects/codegraph
.venv/bin/codegraph build --no-incremental
.venv/bin/codegraph serve            # http://127.0.0.1:8765

# Terminal B — codegraph analyzing the cross-stack example
cd /media/mochan/Files/projects/codegraph
.venv/bin/codegraph build --no-incremental --root examples/cross-stack-demo
.venv/bin/codegraph serve --port 8766 # http://127.0.0.1:8766
```

The cut between graphs happens at 0:18. Pre-load both tabs before recording.

---

## 45-second landscape MP4 — shot list

> Voice-over kept tight. Captions on for muted-autoplay viewers. Each
> beat is timed; total budget 45 sec.

| t | Visual | Voice-over (or caption) |
|---|---|---|
| 0:00 – 0:03 | Terminal A: `codegraph build` runs on codegraph's own repo. Output scrolls past, ends on the node/edge totals. | "Codegraph builds a graph of your codebase in seconds. This is it reading its own code." |
| 0:03 – 0:08 | Cut to dashboard 3D focus view at `http://127.0.0.1:8765`. Camera lands on `codegraph.analysis.dataflow.shape_hops_for_handler`. Caller chips fan out — `serialize_route_edges`, `test_arg_flow.*`, `test_hld_dataflow.*`. Cursor orbits once. | "Pick any function and you get a focus view — callers fanning in, callees fanning out." |
| 0:08 – 0:13 | Cut to terminal: `codegraph dead-code` runs on the self-graph. Output ends on `0 findings`. Lower-third overlay: **451 → 15 → 0** with a small "self-reported baseline" footnote under 451. | "We pointed it at itself. 451 findings became 15 — then we shipped a public-API pragma and the self-graph went to zero." |
| 0:13 – 0:18 | Switch tabs to `http://127.0.0.1:8766` (cross-stack-demo graph). Architecture tab. Endpoint list with method-coloured pills. Cursor hovers `GET /api/users/{user_id}`. | "Now switch to a real cross-stack app. Every backend route, classified by HTTP method." |
| 0:18 – 0:22 | Click the endpoint. Learn Mode modal animates open. TCP / TLS / HTTP phases pulse left-to-right. | "Click any endpoint and codegraph walks you through the full request lifecycle…" |
| 0:22 – 0:26 | Phase 4 lights up. Swimlanes: COMPONENT → HANDLER → SERVICE → REPO → DB. One arrow per hop, each labelled with arg names. | "…down to the actual handler, service, repository, and SQL query in your code." |
| 0:26 – 0:30 | Cursor moves to the chip strip. Picker shows `user_id` as a single chip in amber. Click it. | "Now pick a parameter…" |
| 0:30 – 0:35 | Phase 4 redraws with `user_id` highlighted at every hop where it appears. Animated dot travels along the bezier path from FETCH → ROUTE → SERVICE → REPO. | "…and watch it travel through every layer that uses it — even when names get renamed across boundaries." |
| 0:35 – 0:40 | Cut to terminal: `codegraph dataflow trace "GET /api/users/{user_id}" --format markdown` produces the same chain. Then a Claude Code prompt: "What does the user_id parameter touch?" → response cites the trace inline. | "Same data in your terminal — and in your AI assistant via MCP. Your agent reasons over flow, not just files." |
| 0:40 – 0:45 | End card: codegraph logo, `pip install codegraph-py`, GitHub URL. | "v0.1.0 just shipped. Open source. Link in comments." |

---

## 5-second silent square (1080×1080) — for LinkedIn auto-play

Trim the clearest 5 seconds of the chip-click + travelling-dot animation
(roughly 0:30 – 0:35 from the master). Crop to square; punch in slightly
on Phase 4 so the swimlanes fill the frame.

```bash
ffmpeg -ss 30 -t 5 -i master.mp4 \
  -vf "crop=1080:1080:(in_w-1080)/2:(in_h-1080)/2,scale=1080:1080" \
  -an -c:v libx264 -crf 18 -preset slow square-loop.mp4
```

`-an` strips audio. `crf 18` keeps the file under ~5 MB.

---

## Captions / subtitle file (`.vtt`)

For LinkedIn auto-play (silent), upload a WebVTT file alongside the MP4.

```vtt
WEBVTT

00:00.000 --> 00:03.000
Codegraph builds a graph of your codebase in seconds. This is it reading its own code.

00:03.000 --> 00:08.000
Pick any function — focus view shows callers in, callees out.

00:08.000 --> 00:13.000
Pointed at itself: 451 findings to 15 to zero, after a public-API pragma.

00:13.000 --> 00:18.000
Switch to a cross-stack app. Every backend route, classified.

00:18.000 --> 00:22.000
Click any endpoint to walk through the full request lifecycle…

00:22.000 --> 00:26.000
…down to the actual handler, service, and SQL query in your code.

00:26.000 --> 00:30.000
Pick a parameter…

00:30.000 --> 00:35.000
…and watch it travel through every layer, even across renames.

00:35.000 --> 00:40.000
Same data in your terminal — and in your AI assistant via MCP.

00:40.000 --> 00:45.000
v0.1.0 — open source. pip install codegraph-py.
```

---

## Numbers — what's verified vs. self-reported

Keep this honest in the lower-third overlay:

- **0 findings** on the current self-graph: **verified** (PR #21,
  `feat/pragma-public-api`, merged 2026-04-28).
- **15 findings** before the pragma: **self-reported** in the PR #21
  body and `SESSION_HANDOFF.md`; not independently re-run.
- **451 findings** at session zero: **self-reported baseline** captured
  in `SESSION_HANDOFF.md` from the first `codegraph dead-code` run on
  2026-04-25. Predates tracking — frame as "where we started", not as
  a hard benchmark.

Only the **15 → 0** drop is solidly verified. Don't claim the 451 as a
measured number; treat it as the starting point of the journey.

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
- **Tab-switch jank at 0:13.** Pre-load both `:8765` and `:8766` in
  adjacent tabs; use Cmd/Ctrl+Tab, not the mouse, for a clean cut.
- **3D focus view camera spin.** Let the orbit complete one rotation;
  don't grab the camera mid-frame or the focus node will look unstable.
- **Audio drift in long takes.** Restart OBS between takes — long sessions
  drift A/V sync.

---

## Where to put the finished files

`docs/launch-assets/` (locally; gitignored). Don't commit binaries to the
repo. Upload the MP4 directly to LinkedIn's video uploader, and link the
unlisted YouTube fallback URL in the post body.
