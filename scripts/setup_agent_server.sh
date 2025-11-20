#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="$ROOT/agent-server"

echo "Creating venv in $AGENT_DIR/venv"
python3 -m venv "$AGENT_DIR/venv"

echo "Installing Python dependencies into venv"
if [ -f "$AGENT_DIR/requirements.txt" ]; then
  "$AGENT_DIR/venv/bin/pip" install --upgrade pip
  "$AGENT_DIR/venv/bin/pip" install -r "$AGENT_DIR/requirements.txt"
else
  echo "No requirements.txt found in $AGENT_DIR"
  exit 1
fi

echo "Done. To run the agent-server: $AGENT_DIR/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000"