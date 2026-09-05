#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  printf 'Python 3.11+ nicht gefunden. Bitte Python installieren oder PYTHON setzen.\n' >&2
  exit 1
fi
exec "$PYTHON" scripts/start.py "$@"
