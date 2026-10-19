#!/usr/bin/env bash
# Stable launcher used by .mcp.json. Resolves the repo even when Claude Code
# starts the server from a different working directory.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname -- "$HERE")"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

if ! "$PYTHON" -c 'import mcp' >/dev/null 2>&1; then
  echo "[vibegraph] MCP SDK is not installed for $PYTHON." >&2
  echo "[vibegraph] Run $ROOT/scripts/setup.sh once, then restart Claude Code." >&2
  exit 1
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
GRAPH="${VIBEGRAPH_GRAPH:-$ROOT/graph.json}"

exec "$PYTHON" -m vibegraph --graph "$GRAPH" "$@"
