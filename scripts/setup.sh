#!/usr/bin/env bash
# One-time local setup: create .venv and install VibeGraph in editable mode.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "[vibegraph] creating .venv with $PYTHON"
  "$PYTHON" -m venv .venv
fi

.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

echo
echo "[vibegraph] installed."
echo "  viewer demo:  ./scripts/demo.sh"
echo "  MCP server:   ./.venv/bin/vibegraph-mcp --graph \"$ROOT/graph.json\""
echo "  Claude Code:  .mcp.json is already in place — restart Claude Code and approve the server."
