from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORT_MANIFEST_JSON = ROOT / "data" / "output" / "import_manifest.json"


def run_step(args: list[str]) -> int:
    print("[run]", " ".join(args), flush=True)
    completed = subprocess.run(args, cwd=ROOT)
    print("[exit]", completed.returncode, flush=True)
    return completed.returncode


def import_manifest_failures(path: Path = IMPORT_MANIFEST_JSON) -> list[str]:
    if not path.exists():
        return [f"import manifest missing: {path}"]
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"import manifest cannot be read: {exc}"]
    if not isinstance(rows, list):
        return ["import manifest root must be a list"]

    failures: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            failures.append("import manifest contains non-object row")
            continue
        status = str(row.get("status") or "").strip()
        if status == "unknown" or status.startswith("error"):
            filename = str(row.get("original_filename") or row.get("original_path") or "unknown_file")
            reason = str(row.get("reason") or "")
            failures.append(f"{filename}: {status}{' | ' + reason if reason else ''}")
    return failures


def main() -> int:
    python = sys.executable
    pre_import_steps = [
        [python, "scripts/check_daily_update_preflight.py", "--allow-inbox-business-files"],
        [python, "scripts/import_inbox_files.py"],
    ]
    post_import_steps = [
        [
            python,
            "scripts/run_all_with_frontend_checks.py",
            "--no-live-browser-frontend",
            "--frontend-method",
            "urllib",
        ],
    ]
    for step in pre_import_steps:
        code = run_step(step)
        if code != 0:
            return code
    manifest_failures = import_manifest_failures()
    if manifest_failures:
        for failure in manifest_failures:
            print(f"[fail] import manifest blocker: {failure}", flush=True)
        return 1
    for step in post_import_steps:
        code = run_step(step)
        if code != 0:
            return code
    output = ROOT / "data" / "output"
    print("[done] daily update completed with inbox import and no-browser frontend cache checks", flush=True)
    print(f"[open] {output / 'latest_recommendations.html'}", flush=True)
    print(f"[open] {output / 'dashboard.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
