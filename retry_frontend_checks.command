#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x ".venv_mac/bin/python" ]]; then
  PYTHON=".venv_mac/bin/python"
else
  PYTHON="python3"
fi

echo "Starting window-scoped frontend retry session..."
exec "$PYTHON" scripts/run_report_window.py --workflow frontend-retry
