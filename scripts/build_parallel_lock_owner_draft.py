from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_parallel_lock_owners import (
    WORK_PACKAGE_ALLOWED_LOCKS,
    changed_paths,
    is_locked_parallel_path,
)


DEFAULT_OUTPUT = ROOT / "docs" / "parallel_lock_owners.draft.json"
WORK_PACKAGE_ORDER = ["business_config", "core_business", "report_display", "daily_frontend"]


def _work_package_for_path(path: str) -> str:
    for work_package in WORK_PACKAGE_ORDER:
        if path in WORK_PACKAGE_ALLOWED_LOCKS.get(work_package, set()):
            return work_package
    return "unassigned"


def build_owner_draft(paths: Sequence[str]) -> dict[str, object]:
    locked_paths = sorted({path for path in paths if is_locked_parallel_path(path)})
    grouped: dict[str, list[str]] = {}
    for path in locked_paths:
        grouped.setdefault(_work_package_for_path(path), []).append(path)

    owners = []
    for work_package in WORK_PACKAGE_ORDER:
        files = grouped.get(work_package)
        if not files:
            continue
        owners.append(
            {
                "owner": f"REVIEW_REQUIRED_{work_package}",
                "work_package": work_package,
                "files": files,
                "confirmation_status": "pending",
            }
        )
    if grouped.get("unassigned"):
        owners.append(
            {
                "owner": "REVIEW_REQUIRED_unassigned",
                "work_package": "unassigned",
                "files": grouped["unassigned"],
                "confirmation_status": "pending",
            }
        )

    return {
        "schema_version": 1,
        "round": "showcase_mvp_current",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "confirmation_status": "draft_requires_manual_owner_confirmation",
        "notes": (
            "Draft only. Copy confirmed owners into docs/parallel_lock_owners.json "
            "after each lock file has a single real owner."
        ),
        "owners": owners,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a draft owner manifest for changed locked parallel files.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_owner_draft(changed_paths())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[check] draft owner groups: {len(payload.get('owners') or [])}", flush=True)
    print(f"[check] wrote: {output}", flush=True)
    print("[warn] draft requires manual owner confirmation before strict readiness", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
