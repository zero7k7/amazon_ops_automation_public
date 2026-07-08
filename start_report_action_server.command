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

echo "Starting Amazon Ops report action server..."
echo "Keep this window open while using page buttons."
exec "$PYTHON" scripts/run_report_window.py --workflow service-only
