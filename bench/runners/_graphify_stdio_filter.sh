#!/bin/sh
# Stdio shim that wraps graphify's MCP server, filtering its stdout to
# only emit JSON-RPC frames (lines starting with `{`).
#
# Graphify's MCP server emits banner / log / warning text to stdout
# during normal operation, which corrupts the JSON-RPC frame stream and
# crashes our MCP client with cancel-scope errors. awk's per-line
# fflush() gives us real-time filtering without async overhead.

VENV_PY="$(cd "$(dirname "$0")/../.venvs/graphify/bin" && pwd)/python"

if [ ! -x "$VENV_PY" ]; then
    echo "[graphify-shim] missing $VENV_PY; install graphifyy[mcp] first" >&2
    exit 1
fi

# PYTHONUNBUFFERED=1 forces line-buffered stdout from the Python child.
PYTHONUNBUFFERED=1 exec "$VENV_PY" -m graphify.serve 2>/dev/null \
    | awk '/^\{/ {print; fflush()}'
