#!/usr/bin/env bash
# Development server with reload-friendly logging. Requires uv.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --all-extras
exec uv run wenshu --no-browser "$@"
