from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "inbox"
UNKNOWN_DIR = INBOX / "_unknown"
BLOCKED_SUFFIXES = {".csv", ".xlsx"}


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _business_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in BLOCKED_SUFFIXES
    )


def _noise_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() not in BLOCKED_SUFFIXES
    )


def fail(message: str) -> int:
    print(f"[fail] {message}", flush=True)
    return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether daily update can safely mutate inbox and formal outputs.")
    parser.add_argument(
        "--allow-inbox-business-files",
        action="store_true",
        help="Allow recognized business files in data/inbox. Use only immediately before intentional daily import.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    inbox_files = [
        path
        for path in _business_files(INBOX)
        if UNKNOWN_DIR not in path.parents
    ]
    unknown_files = _business_files(UNKNOWN_DIR)
    noise_files = _noise_files(INBOX)

    if unknown_files:
        return fail("unknown inbox business files must be reviewed before daily update: " + ", ".join(_relative(path) for path in unknown_files))
    if inbox_files and not args.allow_inbox_business_files:
        return fail("inbox business files present; pass --allow-inbox-business-files only for intentional import: " + ", ".join(_relative(path) for path in inbox_files))

    if inbox_files:
        print("[warn] daily update will import inbox business files: " + ", ".join(_relative(path) for path in inbox_files), flush=True)
    else:
        print("[check] no pending inbox business files", flush=True)
    if noise_files:
        print("[warn] ignored inbox noise files: " + ", ".join(_relative(path) for path in noise_files), flush=True)
    else:
        print("[check] no inbox noise files", flush=True)
    print("[done] daily update preflight passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
