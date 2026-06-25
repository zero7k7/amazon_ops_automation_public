from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_unknown_inbox as unknown_audit

DEFAULT_DESTINATION = ROOT / "data" / "archive" / "unknown_inbox_reviewed"
ALLOWED_REPORT_TYPES = {"seller_central_promotion_metrics"}


def _timestamped_destination(destination_dir: Path, filename: str) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = destination_dir / f"{stem}_{timestamp}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = destination_dir / f"{stem}_{timestamp}_{counter}{suffix}"
        counter += 1
    return candidate


def reviewed_quarantine_candidates(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("likely_report_type") or "") not in ALLOWED_REPORT_TYPES:
            continue
        path = Path(str(row.get("original_path") or ""))
        if not path.exists():
            continue
        candidates.append(row)
    return candidates


def quarantine_candidates(
    candidates: list[dict[str, object]],
    *,
    destination_dir: Path,
    apply: bool,
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for row in candidates:
        source = Path(str(row.get("original_path") or ""))
        target = _timestamped_destination(destination_dir, source.name)
        actions.append(
            {
                "source": str(source),
                "destination": str(target),
                "likely_report_type": str(row.get("likely_report_type") or ""),
                "mode": "moved" if apply else "dry_run",
            }
        )
        if apply:
            shutil.move(str(source), str(target))
    return actions


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quarantine reviewed unknown inbox files that are confirmed not to participate in daily import."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move reviewed files. Omit for dry-run.",
    )
    parser.add_argument(
        "--destination",
        default=str(DEFAULT_DESTINATION),
        help="Directory for reviewed unknown files.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rows = unknown_audit.build_audit_rows(unknown_audit._unknown_business_files())
    unknown_audit.write_outputs(rows)
    candidates = reviewed_quarantine_candidates(rows)
    if not candidates:
        print("[check] no reviewed unknown inbox files eligible for quarantine", flush=True)
        return 0

    actions = quarantine_candidates(
        candidates,
        destination_dir=Path(args.destination),
        apply=bool(args.apply),
    )
    for action in actions:
        print(
            f"[{action['mode']}] {action['source']} -> {action['destination']}"
            f" ({action['likely_report_type']})",
            flush=True,
        )
    if not args.apply:
        print("[check] dry-run only; pass --apply to move reviewed files", flush=True)
    else:
        refreshed_rows = unknown_audit.build_audit_rows(unknown_audit._unknown_business_files())
        unknown_audit.write_outputs(refreshed_rows)
        print("[done] reviewed unknown inbox files quarantined", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
