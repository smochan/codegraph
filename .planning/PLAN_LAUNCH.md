# codegraph 0.1.0 — Public Launch Plan

Owner: smochan · Target window: next 48h · Total effort: ~4h

This is a **plan + draft assets** doc. Nothing is executed yet. No commits, no
push, no upload, no posting until the owner runs the steps below by hand.

---

## Section 1 — PyPI publish (≈ 1h)

PyPI distribution name: `codegraph-py` (plain `codegraph` is taken).
CLI command remains `codegraph`. Release workflow is at
`.github/workflows/release.yml` and triggers on tag push `v*` — it builds,
runs `twine check`, attaches `dist/*` to a GitHub Release, and uploads to
PyPI **only if** the `PYPI_API_TOKEN` secret is set on the repo.

### 1.1 Local pre-flight (≈ 10 min)

Run from repo root, in a clean shell:

```bash
cd /media/mochan/Files/projects/codegraph
rm -rf dist/ build/ *.egg-info
python -m pip install --upgrade build twine
python -m build                      # produces dist/codegraph_py-0.1.0-*.whl + .tar.gz
twine check dist/*                   # must say PASSED for both
ls -lh dist/                         # sanity check size (wheel < 500KB expected)
```

Then test install in a fresh venv to catch missing-data-files / entry-point
issues that don't show up in `-e .`:

```bash
python -m venv /tmp/cg-test && source /tmp/cg-test/bin/activate
pip install dist/codegraph_py-0.1.0-py3-none-any.whl
codegraph --help                     # entrypoint resolves
codegraph init --help                # subcommand wiring
codegraph build --help
codegraph mcp serve --help
deactivate && rm -rf /tmp/cg-test
```

If anything is missing (templates, static assets), fix `pyproject.toml`
package-data / `MANIFEST.in` before continuing. **Do not** bump to 0.1.1 to
fix this — fix locally, rebuild, re-verify, only then tag.

### 1.2 PyPI token + GitHub secret (≈ 10 min)

1. Sign in / create account at https://pypi.org (use the smochan email).
2. Pre-register the project name to lock it: PyPI → Manage → "Add project"
   isn't a thing; instead do a one-time manual upload of the wheel built
   above to claim `codegraph-py` (or skip and let the GH Action upload it
   for the first time — either works, manual is safer).

   Manual claim path:
   ```bash
   twine upload dist/* --repository pypi
   # Username: __token__
   # Password: <full-token-including-pypi--prefix>
   ```
   If the manual upload succeeds, the GH Action's `gh-action-pypi-publish`
   step on tag push will become a no-op for 0.1.0 (idempotent if version
   already exists it errors — see 1.5 fallback).

3. Generate a **scoped** API token at https://pypi.org/manage/account/token/
   — scope it to project `codegraph-py` (after first upload) or "entire
   account" (before first upload, then re-issue scoped after).
4. Add to GH repo: Settings → Secrets and variables → Actions → New
   repository secret. Name: `PYPI_API_TOKEN`. Value: the full
   `pypi-AgEI...` token string. **Do not** include `__token__` here — the
   `pypa/gh-action-pypi-publish` action uses the token as the password
   directly.
5. Verify the secret exists (UI shows last-updated timestamp; values are
   write-only).

### 1.3 Push the tag (≈ 5 min)

`v0.1.0` already exists locally. Push it to trigger `release.yml`:

```bash
git status                           # confirm clean tree
git log --oneline -5                 # confirm v0.1.0 points at a sane commit
git push origin main                 # push branch first if not pushed
git push origin v0.1.0               # triggers release workflow
```

### 1.4 Verify the release (≈ 10 min)

1. Watch the run: https://github.com/smochan/codegraph/actions — pick the
   newest "release" run. It should go green in 2–4 min.
2. GitHub Release page: https://github.com/smochan/codegraph/releases/tag/v0.1.0
   — confirm `CHANGELOG.md` is the body and `dist/codegraph_py-0.1.0-*.whl`
   + `.tar.gz` are attached.
3. PyPI listing: https://pypi.org/project/codegraph-py/ — confirm 0.1.0 is
   live with the long description from the README rendering correctly
   (markdown badges, table). If the table renders as raw markdown, fix
   `readme = {file = "README.md", content-type = "text/markdown"}` in
   `pyproject.toml` and ship 0.1.1.

### 1.5 Smoke test (≈ 10 min)

On the user's machine, brand-new venv, no source checkout in scope:

```bash
python -m venv /tmp/cg-pypi && source /tmp/cg-pypi/bin/activate
pip install codegraph-py             # ← real install from PyPI
codegraph --version                  # must print 0.1.0
mkdir -p /tmp/cg-demo && cd /tmp/cg-demo
git clone --depth 1 https://github.com/tiangolo/fastapi.git
cd fastapi
codegraph init --yes
codegraph build
codegraph analyze
codegraph serve &                    # http://localhost:8000
sleep 3 && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000
kill %1
deactivate
```

Any failure here → file an issue against your own repo, fix, ship 0.1.1.

### 1.6 Failure-mode fallback

If `release.yml` fails on the publish step (auth, network, gh-action-pypi
breakage):

```bash
# from the repo where dist/ was built locally in 1.1
twine upload dist/*                  # username __token__, password = secret
```

If the **GitHub Release** step failed but PyPI succeeded, run:

```bash
gh release create v0.1.0 dist/* --notes-file CHANGELOG.md
```

If the **tag** is broken (pointed at the wrong commit), do **not** force
push the tag. Delete + recreate:

```bash
git tag -d v0.1.0
git push origin :refs/tags/v0.1.0
git tag -a v0.1.0 <correct-sha> -m "codegraph 0.1.0"
git push origin v0.1.0
```

### 1.7 README diff after publish

After 1.5 passes, edit `README.md` to remove the not-yet-published note.

**Exact diff (lines 86–93 today):**

```diff
-> **Note:** `codegraph-py` is the PyPI distribution name. The CLI command is `codegraph`.
-> The package is not yet published to PyPI — to try it today, install from source:
->
-> ```bash
-> git clone https://github.com/smochan/codegraph.git
-> cd codegraph
-> pip install -e .
-> ```
+> **Note:** `codegraph-py` is the PyPI distribution name; the CLI command
+> is `codegraph`. To install from source instead:
+>
+> ```bash
+> git clone https://github.com/smochan/codegraph.git
+> cd codegraph && pip install -e .
+> ```
```

Also remove the inline comment on line 51:

```diff
-pip install codegraph-py           # install from PyPI (not yet published — see Install below)
+pip install codegraph-py           # install from PyPI
```

Commit message: `docs: README — drop "not yet published" note after PyPI 0.1.0`

---

## Section 2 — Demo recording plan (≈ 2h)

The demo is the LinkedIn payload. Without a video, the post dies in feed.

### 2.1 What we're recording

- **A**: 45s landscape (1920×1080, 30fps, MP4 H.264) — full demo with text
  overlays. Goes on the GitHub Release, README, and as the LinkedIn video
  attachment.
- **B**: 5s silent loop (square 1080×1080, 30fps, no audio) — for inline
  embedding inside the LinkedIn post body. LinkedIn auto-plays muted, so
  the loop sells the 3D graph in the first scroll.

### 2.2 Recording stack (Linux)

| Tool | Purpose | Why |
|------|---------|-----|
| **OBS Studio** | screen capture | already-installed-or-trivial `apt install obs-studio`; supports scenes, hotkey capture, lossless intermediate |
| **Kdenlive** or **Shotcut** | trim, overlays, export | both are apt-installable; Kdenlive has nicer text-overlay keyframing |
| **ffmpeg** | encode loop variant + WebM/MP4 sweep | scriptable, deterministic |
| **GIMP** | thumbnail (1280×720) | one-off |

OBS settings:
- Output: MKV (lossless intermediate), 1920×1080, 30fps, NVENC if on
  NVIDIA, otherwise x264 `veryfast` CRF 18.
- Scene 1: full screen, browser only. Scene 2: terminal split with Claude
  Code. Hotkey scene-switch with F1/F2.

Final encode for the 45s landscape:

```bash
ffmpeg -i raw.mkv -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart demo_45s.mp4
```

Loop variant (silent square 5s):

```bash
ffmpeg -ss 00:00:08 -t 5 -i raw.mkv \
  -vf "crop=ih:ih,scale=1080:1080" -an \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -movflags +faststart loop_5s.mp4
```

### 2.3 Storyboard (8 shots, ≤45s)

Pacing target: ~5–6s per shot. Text overlays in a clean sans (Inter / IBM
Plex Sans), 64px, 1.5s in / 1.5s hold / 1s out.

| # | Time | Visual | Overlay text / narration cue |
|---|------|--------|------------------------------|
| 1 | 0:00–0:04 | Cold open: terminal, type `pip install codegraph-py` then `codegraph build`. Progress bars fly. | `codegraph` (logo lockup) |
| 2 | 0:04–0:09 | Cut to dashboard hero: HLD navigator + layered architecture panel. Slow zoom-in on a module box. | `Map any repo. One SQLite file. No daemon.` |
| 3 | 0:09–0:17 | **Hero shot.** Switch to 3D graph view. Slow rotation around a dense cluster, edges glowing on hover. | `Functions, calls, imports, inheritance — visualised.` |
| 4 | 0:17–0:23 | Click a node → focus graph slides in showing callers/callees. | `Click any symbol. See exactly who calls it.` |
| 5 | 0:23–0:30 | Cut to Claude Code in a terminal. User types: *"What's the blast radius of changing `UserService.login`?"* Claude's tool-use panel shows `mcp__codegraph__blast_radius` firing. | `Your AI assistant gets the same map.` |
| 6 | 0:30–0:36 | Claude responds with a list of 14 affected callers and a one-line summary. Highlight the response. | `No more grep. Real graph queries.` |
| 7 | 0:36–0:41 | Quick montage: `codegraph review` printing risk-scored PR diff in markdown. | `Risk-scored PR review. SARIF for CI.` |
| 8 | 0:41–0:45 | End card: logo, `github.com/smochan/codegraph`, `pip install codegraph-py`, `MIT · v0.1.0`. | (no narration) |

Voiceover: optional. If recording v1 today, **skip VO** — text overlays
plus ambient lo-fi at -22 LUFS is enough. VO can come in v2.

For shot 3 (hero) the loop variant uses **only** seconds 8–13 of the raw
recording — that's the cleanest 5s of pure rotation.

### 2.4 Repo to demo against

**Recommendation: codegraph itself (meta).**

Reasons:
1. **Compelling narrative**: "the tool maps its own brain" reads well in
   feed. Reviewers can replicate exactly what they see.
2. **Honest size**: ~3–4K LOC, Python-only — the parser support is exactly
   one of the supported languages, so no asterisks.
3. **No third-party noise**: no need to apologise for unsupported nodes
   (Go/Java/Rust files in fastapi-fullstack would render as bare module
   nodes and look weak).
4. **Reproducible**: viewer can `git clone && codegraph build` and get the
   same dashboard.

**Alternative**: a small FastAPI + React example (e.g. `tiangolo/full-stack-fastapi-template`).
Use this **only after** v0.2 ships cross-stack data-flow tracing — that's
when the React↔FastAPI edges become the story. For 0.1.0 it weakens the
demo because TS/JS support exists but the cross-stack edges don't.

Decision: **demo codegraph against codegraph for 0.1.0 launch.**

### 2.5 Pre-record checklist

- [ ] Browser zoom 110%, hide bookmarks bar, fresh profile (no extensions)
- [ ] Terminal: large font (18pt+), high-contrast theme, clean prompt (`PS1='$ '`)
- [ ] Disable system notifications (`Do Not Disturb` on)
- [ ] Close Slack, mail, anything that can pop a banner
- [ ] Pre-warm: `codegraph build` already done, dashboard already open
- [ ] Hide cursor unless intentionally clicking (OBS source filter)

---

## Section 3 — LinkedIn post

Final copy lives in `.planning/draft_linkedin.md`. Time: 1h to write +
self-edit. Read it before posting; tweak with your voice.

Hook is the first 210 chars (LinkedIn's truncation point). The draft leads
with a number from running codegraph on itself — concrete, falsifiable,
not "I built X." Existing tools (GitNexus, code-graph-mcp,
JudiniLabs/mcp-code-graph) are acknowledged in a follow-up comment, not
hidden.

Tags (LinkedIn @-mentions to include in the post):
- `@Anthropic`
- `@Model Context Protocol` (the MCP org page if it exists; otherwise
  spell it out as MCP and tag a maintainer in the comment)
- `@Claude` (the Anthropic Claude page)

Hashtags (5–7, ordered by descending relevance):
`#AIagents #DeveloperTools #MCP #ClaudeCode #OpenSource #Python #CodeQuality`

**Comment-1 template (post 2 minutes after the main post)** — see the
full table copy at the bottom of `draft_linkedin.md`. Posting it as a
comment (not in the body) keeps the main post scannable, and LinkedIn
boosts posts where the author engages within the first 5 minutes.

---

## Section 4 — Posting strategy

### 4.1 Best time

Tech audience, US/EU overlap window:
- **Tuesday or Wednesday, 08:30–09:30 ET** (13:30–14:30 UK, 18:00–19:00
  IST). Catches East-coast US morning coffee, EU late-afternoon, India
  evening commute. Avoid Mon (low engagement, post drowned by week-start)
  and Fri (weekend drop-off).
- LinkedIn dwell-time decay is steep — first 60 minutes of engagement
  decides reach. Be at the keyboard for that hour to reply to comments.

### 4.2 Cross-post matrix

| Platform | Post? | Format | Notes |
|----------|-------|--------|-------|
| **LinkedIn** | yes | full post + 5s loop video, table comment | primary channel |
| **X / Twitter** | yes | 3-tweet thread, attach 45s MP4 | tweet 1 = hook + video, tweet 2 = "what's different vs GitNexus etc", tweet 3 = link + roadmap |
| **r/Python** | maybe | self-post, no link in title | only if 0.1.0 actually installs cleanly via pip; mods reject "look at my repo" posts. Title: "codegraph-py 0.1.0 — local code-graph + MCP server, MIT" |
| **r/programming** | **no** | — | bar is "general programming insight"; a tool launch will be removed or downvoted. Skip. |
| **r/LocalLLaMA** | yes | self-post | this audience cares about local-first AI tooling and MCP. Best fit. |
| **r/ClaudeAI** | yes | self-post | smaller but engaged; MCP-relevant |
| **HN Show HN** | **no** for 0.1.0 | — | bar for Show HN is roughly "I built a thing other people will actually use today." With GitNexus already on the front page in April 2026 and our cross-stack-tracing wedge still in v0.2, posting now likely gets "how is this different from GitNexus?" as the top comment and we don't have a sharp answer. **Hold for v0.2** when data-flow tracing ships — that's the Show HN. |
| **Lobsters** | yes | tag `programming, devtools` — link-only is fine here; the audience reads READMEs |
| **dev.to** | yes (week 2) | repurpose the LinkedIn post as a longer article with screenshots; cross-canonical to a blog if you have one |
| **Hacker News (regular submit, not Show HN)** | optional | link only | low effort, low expectation; if it catches it catches |

### 4.3 DM amplification list (TODO for owner)

Don't fabricate names. Owner picks 5–10 based on:

- People who've ⭐'d or commented on **other code-graph / MCP repos** in
  the last 60 days (skim stargazers of GitNexus, JudiniLabs/mcp-code-graph,
  RepoMapper).
- Anthropic DevRel + Claude Code maintainers (search LinkedIn for "Claude
  Code" in title; Anthropic posts a public DevRel team list).
- Tree-sitter community: GitHub maintainers of py-tree-sitter and
  tree-sitter-language-pack.
- 2–3 mutuals who post regularly about devtools/AI tooling and would
  re-share without a hard ask.
- 1–2 newsletter authors in the AI-tooling space (TLDR AI, Latent Space,
  Pragmatic Engineer's reader-tools section).

Template DM (tweak per recipient):

> Hey {name} — shipped a small thing this morning: codegraph, a
> local-first code-graph + MCP server for Claude Code. 45s demo here:
> {link}. No ask, just thought you might find the cross-stack tracing
> roadmap interesting given {specific reference to their work}.

---

## Section 5 — Anti-hype check

Six things to **not** claim and the credibility-kill list:

1. **Don't say "first" or "novel"** — code-graph + MCP is not new
   (JudiniLabs, sdsrss, code-graph-mcp, better-code-review-graph all
   exist). Wedge is *cross-stack data-flow tracing*, **and that ships in
   v0.2, not 0.1.0** — frame it as roadmap, not feature.
2. **Don't compare against GitNexus on stars/scale** — they have 28K
   stars, hit #1 trending. We have 0. Acknowledge them by name and explain
   the **different shape** (local-first, MCP-native, single SQLite file)
   not the different size.
3. **Don't claim multi-language coverage we don't have** — 0.1.0 ships
   Python / TypeScript / JavaScript function-level extractors only. Go,
   Java, Rust are module-level placeholders. README says this; the post
   must too.
4. **Don't post a benchmark we haven't actually run** — no "10x faster
   than X" lines. Numbers in the post must come from a real
   `codegraph build` on a real repo, with the repo named.
5. **Don't bury the prior art** — top comment on the post links to the
   competitor table and names GitNexus, JudiniLabs/mcp-code-graph,
   code-graph-mcp explicitly. If a reviewer Googles "code graph mcp" and
   finds those before our post mentions them, we look amateur.
6. **Don't promise the v0.2 wedge as if it's done** — "data-flow tracing
   from React component → FastAPI endpoint → Postgres column is the v0.2
   focus" is honest and exciting. "codegraph traces data flow across
   stacks" is a lie until it ships.

Credibility-kill list (any of these tank the launch):

- A pip install that fails on a fresh venv.
- A demo video that shows a feature the published wheel doesn't have.
- A feature comparison table with a competitor row that's wrong (e.g.
  "GitNexus: no MCP" when they shipped MCP last month — verify before
  posting).
- A post with no video, screenshot, or link to a runnable thing.
- Tagging Anthropic / Claude without something they'd actually want to
  retweet (i.e. don't tag them on a half-finished launch).

---

## Section 6 — Success metrics

### 24h targets

| Metric | Floor | Stretch |
|--------|-------|---------|
| GitHub stars | 25 | 100 |
| PyPI downloads (codegraph-py) | 50 | 250 |
| LinkedIn impressions | 3,000 | 10,000 |
| LinkedIn reactions | 30 | 120 |
| LinkedIn comments | 5 | 25 |
| Issues opened | 1 | 4 |
| Repo unique visitors (Insights) | 200 | 800 |

### 7d targets

| Metric | Floor | Stretch |
|--------|-------|---------|
| GitHub stars | 60 | 300 |
| Issues / PRs from non-owners | 2 | 10 |
| Contributors approached or volunteering | 1 | 5 |
| Claude Code users with codegraph in `~/.claude.json` (proxy: PyPI weekly downloads) | 200 | 1,500 |

### What's a "win" vs "validate-and-move-on"

- **Win** (≥ 7d stretch + 1 inbound contributor PR + 1 piece of feedback
  that *names* the cross-stack-tracing wedge as the reason they care):
  invest in v0.2 hard, hire focus on data-flow tracing for 4–6 weeks,
  prep Show HN around the v0.2 ship.
- **Validate-the-wedge** (≥ floor numbers, plus 2+ comments asking about
  cross-stack tracing or showing interest in the React↔FastAPI angle):
  the wedge is real but the audience is small. Build v0.2 at half pace,
  use the time for content (one technical blog post per week showing
  codegraph used in real refactors).
- **Move on** (below floor, no comments naming the wedge, no inbound
  signals): the space is too crowded for an indie launch. Keep codegraph
  as a portfolio artifact, refactor the differentiated parts (MCP-native
  local-first ergonomics) into a smaller, sharper tool, or fold the
  learnings into joining one of the existing projects as a contributor.

---
