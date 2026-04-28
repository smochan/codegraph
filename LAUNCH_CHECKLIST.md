# 0.1.0 Launch Checklist

The product is functionally complete on `main`. This is the concrete,
sequenced list of remaining manual steps to ship 0.1.0 publicly. Tick
each box as you finish.

> **Status as of 2026-04-29:** all code shipped, all tests green
> (537 pytest + 100 Node = 637), self-graph reports 0 dead code, 3
> documented cycles, 0 open PRs.

---

## 1. Pre-flight smoke (~10 min)

```bash
git fetch origin && git pull origin main
.venv/bin/pip install -e ".[dev]"

# Code quality gates
.venv/bin/ruff check . --exclude .claude --exclude examples
.venv/bin/mypy --strict codegraph
.venv/bin/python -m pytest -q
node --test tests/*.js

# Real-world smoke
rm -f .codegraph/graph.db
.venv/bin/codegraph build --no-incremental
.venv/bin/codegraph analyze | head -30

# Dashboard
.venv/bin/codegraph serve  # http://127.0.0.1:8765 — verify Architecture tab + Learn Mode modal
```

- [ ] All tests green
- [ ] ruff + mypy clean
- [ ] Self-graph analyze shows 0 dead-code, 3 cycles, 537+ untested-functions counts as expected
- [ ] Dashboard renders; Architecture view → click `/api/users/{user_id}` → Learn Mode → Phase 4 shows the real chain → click `user_id` chip → highlight follows it

If any step fails, stop and fix before proceeding.

## 2. Record the launch demo (~2 hours)

Storyboard: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md). Two outputs:

- [ ] **45-second landscape MP4** — full demo with narration / captions
- [ ] **5-second silent square loop** — for LinkedIn auto-play (muted)

Tools: OBS for capture, Kdenlive (or DaVinci Resolve / iMovie) for trim,
`ffmpeg` for the silent loop. Exact commands in the script.

Save final files to `docs/launch-assets/` (gitignored — too large for the repo).

## 3. Tag and PyPI publish (~30 min)

> **Run `twine upload` MANUALLY first** to claim the `codegraph-py` name on PyPI before the automated workflow runs. After that, tag-push triggers `release.yml`.

```bash
# Build locally to confirm the wheel is clean
python -m build
twine check dist/*

# Manual first-publish — claim the name
twine upload dist/*
# enter PyPI credentials when prompted
```

- [ ] `pip install codegraph-py` works in a fresh venv
- [ ] `codegraph --help` runs after install

Then enable the automated release pipeline:

```bash
# Set the secret on the repo so future tag pushes auto-publish
gh secret set PYPI_API_TOKEN --repo smochan/codegraph
# paste the pypi-... token

# Tag and push
git tag -a v0.1.0 -m "v0.1.0 — first public release"
git push origin v0.1.0
```

The `release.yml` workflow will:

1. Build sdist + wheel
2. `twine check`
3. Upload artifacts
4. Skip the publish step (since we already published manually)
5. Create the GitHub Release with `CHANGELOG.md` body

- [ ] `gh release view v0.1.0` shows the release
- [ ] PyPI shows version 0.1.0
- [ ] `pip install codegraph-py==0.1.0` works

## 4. README badge update (~5 min)

After the tag, update the status badge:

```bash
# In README.md, replace
# [![Status](https://img.shields.io/badge/status-0.1.0--pre-yellow.svg)](...)
# with the live PyPI badge:
# [![PyPI](https://img.shields.io/pypi/v/codegraph-py.svg)](https://pypi.org/project/codegraph-py/)
```

- [ ] PR opened, merged

## 5. LinkedIn launch (~30 min)

Draft is ready in [`.planning/draft_linkedin.md`](.planning/draft_linkedin.md).
Verify the metrics match `main` before posting.

- [ ] Numbers in the post match the latest `codegraph analyze` (537 tests, 0 dead, 3 cycles)
- [ ] Demo video attached (45s landscape) or 5s loop in the comments
- [ ] Post on LinkedIn
- [ ] 2 minutes after posting, drop the pinned comparison-table comment (template in the draft)
- [ ] Cross-post: r/Python, r/LocalLLaMA, r/ClaudeAI, X/Twitter

> **Hold off on Show HN** until v0.4-shaped follow-ups have shipped, per
> the strategic note in earlier session research. Posting now risks
> "isn't this GitNexus?" as the top comment.

## 6. Post-launch (the same day)

- [ ] Reply to every comment within 6 hours
- [ ] If anyone files an issue, fix or label it within 24 hours
- [ ] Add `good first issue` labels to 3-5 known small tasks (TS R2 resolver
      patterns, Typer CLI HANDLER classification, multi-param arg-flow) so
      drive-by contributors have somewhere to start

---

## What if something goes wrong?

- **PyPI name is taken?** `codegraph-py` is reserved (verify via `pip search`
  or open the URL). If unavailable, fall back to `codegraph-mcp` or
  `mochan-codegraph` and update `pyproject.toml` accordingly.
- **`release.yml` fails on tag push?** Don't panic — the manual `twine
  upload` already published. Just edit the GitHub Release manually with
  the CHANGELOG body.
- **Demo recording crashes / weird timing?** OBS captures at 60 fps by
  default; drop to 30 if your machine struggles. Re-record only the bad
  segment and stitch with `ffmpeg -f concat -i list.txt -c copy out.mp4`.

---

## Numbers source-of-truth

If anything in this checklist (or any other doc) cites a number that
disagrees with reality, **`codegraph analyze` is the source of truth.**
Update the doc to match, never the other way around.

```bash
.venv/bin/codegraph build --no-incremental
.venv/bin/codegraph analyze
.venv/bin/python -m pytest -q
node --test tests/*.js
```
