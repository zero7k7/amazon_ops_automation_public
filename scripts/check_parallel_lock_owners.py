from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs" / "parallel_lock_owners.json"
MAX_EXECUTION_AGENTS = 4

LOCKED_PARALLEL_FILES = {
    "main.py",
    "scripts/check_parallel_lock_owners.py",
    "scripts/check_showcase_commit_readiness.py",
    "scripts/report_action_server.py",
    "scripts/run_all_with_frontend_checks.py",
    "scripts/run_frontend_checks.py",
    "scripts/validate_showcase_mvp.py",
    "src/autoopt_feedback.py",
    "src/generate_html_report.py",
    "src/merge_data.py",
    "src/metrics.py",
    "src/report_presentation.py",
    "config/product_cost_config.xlsx",
}

LOCKED_PARALLEL_PATTERNS = (
    "config/*.xlsx",
)

WORK_PACKAGE_ALLOWED_LOCKS = {
    "docs": set(),
    "daily_frontend": {
        "scripts/check_parallel_lock_owners.py",
        "scripts/check_showcase_commit_readiness.py",
        "scripts/report_action_server.py",
        "scripts/run_all_with_frontend_checks.py",
        "scripts/run_frontend_checks.py",
    },
    "report_display": {
        "scripts/check_parallel_lock_owners.py",
        "scripts/check_showcase_commit_readiness.py",
        "scripts/validate_showcase_mvp.py",
        "src/generate_html_report.py",
    },
    "core_business": {
        "main.py",
        "src/autoopt_feedback.py",
        "src/merge_data.py",
        "src/metrics.py",
        "src/report_presentation.py",
    },
    "business_config": {
        "config/product_cost_config.xlsx",
        "config/sku_alias_map.xlsx",
        "config/sku_asin_map.xlsx",
        "config/ignored_quality_issues.xlsx",
        "config/templates/product_cost_config.example.xlsx",
        "config/templates/sku_alias_map.example.xlsx",
        "config/templates/sku_asin_map.example.xlsx",
    },
}


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_locked_parallel_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized in LOCKED_PARALLEL_FILES or any(
        fnmatch.fnmatch(normalized, pattern) for pattern in LOCKED_PARALLEL_PATTERNS
    )


def git_lines(args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def changed_paths() -> list[str]:
    paths = set(git_lines(["diff", "--name-only"]))
    paths.update(git_lines(["diff", "--cached", "--name-only"]))
    paths.update(git_lines(["ls-files", "--others", "--exclude-standard"]))
    return sorted(_normalize_path(path) for path in paths)


def load_manifest(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [f"owner manifest missing: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"owner manifest cannot be read: {exc}"]
    if not isinstance(data, dict):
        return None, ["owner manifest root must be an object"]
    return data, []


def _owner_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    owners = manifest.get("owners")
    if not isinstance(owners, list):
        return []
    return [owner for owner in owners if isinstance(owner, dict)]


def validate_owner_manifest(
    changed: Sequence[str],
    manifest: dict[str, Any],
    *,
    max_execution_agents: int = MAX_EXECUTION_AGENTS,
) -> list[str]:
    failures: list[str] = []
    locked_changed = sorted({_normalize_path(path) for path in changed if is_locked_parallel_path(path)})
    entries = _owner_entries(manifest)
    if not entries:
        failures.append("owner manifest must contain a non-empty owners list")
        return failures

    file_owners: dict[str, list[str]] = {}
    execution_owners: set[str] = set()
    for idx, entry in enumerate(entries, start=1):
        owner = str(entry.get("owner") or "").strip()
        if not owner:
            failures.append(f"owners[{idx}] missing owner")
            continue
        role = str(entry.get("role") or "execution_agent").strip()
        work_package = str(entry.get("work_package") or "").strip()
        if role != "main_thread" and not work_package:
            failures.append(f"owners[{idx}] missing work_package")
        allowed_locks = WORK_PACKAGE_ALLOWED_LOCKS.get(work_package, set())
        if work_package and work_package not in WORK_PACKAGE_ALLOWED_LOCKS:
            failures.append(f"owners[{idx}] has unknown work_package: {work_package}")
        files = entry.get("files")
        if not isinstance(files, list) or not files:
            failures.append(f"owners[{idx}] must list files")
            continue
        if role != "main_thread":
            execution_owners.add(owner)
        for raw_path in files:
            path = _normalize_path(str(raw_path or ""))
            if not path:
                failures.append(f"owners[{idx}] contains empty file path")
                continue
            if not is_locked_parallel_path(path):
                failures.append(f"owners[{idx}] assigns non-locked file: {path}")
                continue
            if role != "main_thread" and path not in allowed_locks:
                failures.append(f"owners[{idx}] assigns file outside work_package {work_package}: {path}")
                continue
            file_owners.setdefault(path, []).append(owner)

    if len(execution_owners) > max_execution_agents:
        failures.append(
            f"too many execution owners: {len(execution_owners)} > {max_execution_agents}"
        )

    for path, owners in sorted(file_owners.items()):
        unique_owners = sorted(set(owners))
        if len(unique_owners) > 1:
            failures.append(f"locked file has multiple owners: {path} -> {', '.join(unique_owners)}")

    for path in locked_changed:
        if path not in file_owners:
            failures.append(f"changed locked file has no owner: {path}")

    return failures


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check multi-agent locked file owner assignments.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Path to owner manifest JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = changed_paths()
    locked_changed = [path for path in paths if is_locked_parallel_path(path)]
    if not locked_changed:
        print("[check] no changed locked parallel files", flush=True)
        return 0

    manifest, load_failures = load_manifest(Path(args.manifest))
    failures = load_failures
    if manifest is not None:
        failures = validate_owner_manifest(paths, manifest)

    if failures:
        for failure in failures:
            print(f"[fail] {failure}", flush=True)
        return 1

    print("[check] locked parallel files have single owners:", len(locked_changed), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
