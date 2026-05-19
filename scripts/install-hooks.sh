#!/usr/bin/env bash
# scripts/install-hooks.sh — wire git to use the tracked .githooks/ dir.
# Run once after cloning.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

git config core.hooksPath .githooks
chmod +x .githooks/pre-push

echo "✓ git hooks installed"
echo "  core.hooksPath = $(git config core.hooksPath)"
echo "  pre-push will now run ruff + pytest before any push."
echo "  Skip in a pinch with:  git push --no-verify"
