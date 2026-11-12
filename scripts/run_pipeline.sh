#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Missing $ROOT/.venv/bin/python — create the venv first." >&2
  exit 1
fi

exec "$ROOT/.venv/bin/python" -m src.graph.pipeline
