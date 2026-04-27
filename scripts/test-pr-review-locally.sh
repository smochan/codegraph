#!/usr/bin/env bash
# Dry-run the PR review workflow locally so you can validate it before pushing.
#
# Requires:
#   - clean repo (no uncommitted changes)
#   - origin/main fetched (`git fetch origin main`)
#   - codegraph installed in editable mode (`pip install -e .`)
#
# Produces ./review.md and ./comment.md exactly like the CI does, but skips
# the GitHub-API steps (comment posting, artifact upload, exit code).
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

if ! git diff-index --quiet HEAD --; then
  echo "[WARN] working tree has uncommitted changes; review will reflect them" >&2
fi

if ! command -v codegraph >/dev/null 2>&1; then
  echo "[ERROR] codegraph not on PATH — run \`pip install -e .\` first" >&2
  exit 1
fi

echo "==> Building baseline from origin/main"
rm -rf /tmp/cg-baseline-checkout
git worktree add /tmp/cg-baseline-checkout origin/main
trap 'git worktree remove --force /tmp/cg-baseline-checkout 2>/dev/null || true' EXIT

(
  cd /tmp/cg-baseline-checkout
  codegraph build --no-incremental
  codegraph baseline save --output "$REPO_ROOT/.codegraph/baseline.db"
)

echo "==> Building PR-head graph"
codegraph build --no-incremental

echo "==> Running codegraph review"
set +e
codegraph review \
  --format markdown \
  --output review.md \
  --fail-on high \
  --baseline .codegraph/baseline.db
rc=$?
set -e

echo "==> Wrapping into comment.md"
{
  echo "## codegraph PR review"
  echo
  echo "<details open>"
  echo "<summary><b>Diff vs main</b> · severity ≤ <code>high</code></summary>"
  echo
  cat review.md
  echo
  echo "</details>"
} > comment.md

echo
echo "----"
echo "review.md and comment.md written. Review exit code: $rc"
echo "(Non-zero = high/critical findings; CI would fail on this.)"
exit "$rc"
