#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS packaging must be run on macOS." >&2
  exit 1
fi

PYTHON_BIN="${PYTHON:-python3}"

if [[ ! -d ".venv" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m PyInstaller --noconfirm DanmuAI-macOS.spec

echo "Built dist/DanmuAI.app"
