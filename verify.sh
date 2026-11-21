#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -r requirements.txt
pytest -q
python -m compileall -q app tests
if command -v node >/dev/null 2>&1; then
  node --check static/app.js
fi
echo "All local verification checks passed."
