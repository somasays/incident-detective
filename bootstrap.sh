#!/bin/sh
# First run: uv installs the locked environment before the Python bootstrap runs.
set -eu
cd "$(dirname "$0")"
export LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
if ! command -v uv >/dev/null 2>&1; then
  echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
exec uv run --locked python scripts/bootstrap.py "$@"
