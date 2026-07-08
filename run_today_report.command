#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
elif [[ -x ".venv_mac/bin/python" ]]; then
  PYTHON=".venv_mac/bin/python"
else
  PYTHON="python3"
fi

echo "Amazon Ops Automation"
echo "Starting window-scoped daily report session..."
exec "$PYTHON" scripts/run_report_window.py --workflow daily
