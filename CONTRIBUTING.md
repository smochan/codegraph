# Contributing to codegraph

Thanks for taking the time to contribute. This doc covers everything you
need to open a PR that lands cleanly: the local setup, what CI is going to
check, how to run the same checks locally before pushing, the expected
commit / PR format, and the merge process.

If anything here is unclear or out of date, that's a bug — open an issue or
a PR against this file.

---

## Quick start

```bash
# 1. Fork on GitHub, then clone your fork
git clone https://github.com/<your-user>/codegraph.git
cd codegraph

# 2. Add upstream so you can pull updates
git remote add upstream https://github.com/smochan/codegraph.git

# 3. Set up the env (Python 3.10+)
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4. Make sure the baseline tests pass before changing anything
pytest -q

# 5. Branch and start hacking
git checkout -b feat/your-thing
```

If you want the optional embeddings layer (`semantic_search` /
`hybrid_search` MCP tools, `codegraph embed` CLI), also run
`pip install -e ".[embed]"`.

---

## What CI checks (so you can run the same checks locally)

Two workflows run on every PR against `main`:

### 1. `ci.yml` — formatter, type-checker, tests

Runs on Python 3.10, 3.11, and 3.12. Fails the PR if any step fails.

```bash
# Ruff — lint
ruff check . --exclude .claude --exclude examples

# mypy --strict — type-check
mypy --strict codegraph

# pytest — full suite (currently 467+ tests)
pytest -q

# Optional but recommended for JS / TSX changes
node --test tests/test_*.js
```

Run all four locally before pushing. The whole loop takes ~30s.

### 2. `pr-review.yml` — codegraph reviews itself

This workflow dogfoods our own analyzer:

1. Builds a graph from `origin/main` and saves it as a baseline.
2. Builds a graph from your PR head.
3. Runs `codegraph review --fail-on high --baseline ...` against the diff.
4. Posts a sticky comment on the PR with the markdown report.
5. Fails the check if any high-or-critical findings show up.

Findings include:
- new dead code (functions you added that nothing calls)
- new cycles (PR introduces an import or call cycle)
- modified-signature on high-blast-radius nodes (you changed a function
  that's called from many places)
- coverage gaps (PR adds public callables without tests)

### Run the review yourself, BEFORE you push

```bash
# Make sure you have origin/main up to date
git fetch origin main

# Run the same review CI runs
./scripts/test-pr-review-locally.sh
```

This script:

- Worktree-checks-out `origin/main` to a temp dir
- Builds the baseline graph
- Builds your current working-tree graph
- Runs `codegraph review` with the same flags CI uses
- Writes `review.md` and `comment.md` so you can read the exact comment
  CI would post

If the script exits non-zero, your PR will fail CI. Fix the findings
before pushing — this saves you (and reviewers) one round trip.

---

## What "good" looks like in a PR

We're pretty strict because the project's pitch is *"trust this analyzer
on your code,"* which only works if our own code is clean.

### Code

- **Tests for new behaviour.** New functions need direct unit tests. New
  bug fixes need a regression test that fails on `main` and passes on
  your branch.
- **Type-clean** — `mypy --strict` must pass on `codegraph/`. No `Any`
  unless there's a `# type: ignore[reason]` comment explaining why.
- **Ruff-clean** — including import ordering (`I001`). Run
  `ruff check . --fix` to auto-fix.
- **No `print()`** in production code. Use the existing `console` (Rich)
  or, in libraries, raise an exception.
- **Match the style of the file you're editing.** If a module uses
  `from __future__ import annotations`, keep it. If it uses dataclasses,
  use dataclasses.
- **No emoji** in code, comments, or docstrings.

### Commits

We follow conventional commits. The most common prefixes:

| Prefix | Use for |
|---|---|
| `feat(scope)` | a new user-visible feature |
| `fix(scope)` | a bug fix |
| `refactor(scope)` | code movement that doesn't change behaviour |
| `test(scope)` | tests-only changes |
| `docs(scope)` | docs-only changes |
| `chore(ci)` / `chore(deps)` | infra / dependency bumps |
| `perf(scope)` | performance fix with a measurable improvement |

`<scope>` is one of: `parser`, `parser/py`, `parser/ts`, `analysis`,
`resolve`, `cli`, `mcp`, `web/3d`, `embed`, `hld`, `dataflow`, `examples`,
`ci`, `readme`. Use a new scope if none of those fit.

Format the body for humans, not just machines. The first line is the
summary; below that, explain *why* the change is needed and what the
trade-offs are. Reference an issue number with `Closes #N` when applicable.

### PRs

- **One concern per PR.** A 50-line bug fix and a 1500-line refactor go
  in two different PRs.
- **Title follows the conventional-commit format** of the squash commit
  the maintainer will use.
- **Body** describes:
  1. What changed (1 paragraph)
  2. Why it changed (1 paragraph)
  3. Test plan: bullet list of `pytest`, browser smoke, or manual repro
- **Don't worry about the codegraph PR review comment if you're forking** —
  GitHub restricts our token to read-only on fork PRs, so the comment is
  skipped. Download the `codegraph-review` workflow artifact instead;
  it has the same `review.md`.

---

## Branch protection and merge process

`main` is protected:

- Direct pushes are rejected. Every change goes through a PR.
- The `ci.yml` and `codegraph PR review` checks must be green.
- Force-pushes and branch deletion are blocked.
- Admins are not exempt.

**Maintainer merge** uses `gh pr merge --merge` (preserves the merge
commit and PR number — easier to audit later).

---

## Working on a fixture or example

The `examples/cross-stack-demo/` repo is what we point at for the
end-to-end `codegraph dataflow trace` story. If you change it, also run:

```bash
pytest -q tests/test_demo_repo.py
```

The 9 regression tests there assert it still produces the expected
ROUTE / FETCH_CALL / READS_FROM / WRITES_TO / role counts.

---

## Reporting bugs and asking questions

- **Bug reports:** open a GitHub issue with a minimal reproducer.
  Include the codegraph version, Python version, and what
  `codegraph analyze` (or `codegraph dataflow trace ...`) outputs.
- **Questions / design discussions:** open a Discussion (or issue with
  the `question` label).
- **Security issues:** email the maintainer instead of opening a public
  issue. Currently this is `smochan` — see the GitHub profile for
  contact.

---

## License

By contributing, you agree your contribution is licensed under the
[MIT License](LICENSE) of the project.
