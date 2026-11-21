#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
PORT="${AGENTSHIELD_PORT:-8000}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10 or newer, then try again."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating a local Python environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -r requirements.txt

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  HEALTH=""
  if command -v curl >/dev/null 2>&1; then
    HEALTH="$(curl -fsS "http://127.0.0.1:${PORT}/api/health" 2>/dev/null || true)"
  fi
  if printf '%s' "$HEALTH" | grep -q '"build":"agentshield-final"'; then
    echo "The final AgentShield build is already running at http://127.0.0.1:${PORT}."
    echo "Do not start a second server. Open that address in your browser."
    exit 0
  fi
  echo "Port ${PORT} is already in use by another process or an older AgentShield build."
  echo "Stop the old server with Ctrl+C in its original terminal."
  echo "Or start this final build on another port with:"
  echo "AGENTSHIELD_PORT=8001 ./run.sh"
  echo "Then open http://127.0.0.1:8001"
  echo "Check the process with: lsof -nP -iTCP:${PORT} -sTCP:LISTEN"
  exit 1
fi

echo
echo "AgentShield is starting. Open http://127.0.0.1:${PORT} in your browser."
echo "Keep this terminal open while using the dashboard. Press Ctrl+C to stop."
echo
python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload
