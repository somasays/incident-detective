#!/bin/sh
# Subsequent runs use only installed dependencies, the local image and local model.
set -eu
cd "$(dirname "$0")"
export LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
if ! command -v uv >/dev/null 2>&1; then
  echo "Install uv, then run ./bootstrap.sh once." >&2
  exit 1
fi
exec uv run --locked --offline python scripts/bootstrap.py --offline "$@"
