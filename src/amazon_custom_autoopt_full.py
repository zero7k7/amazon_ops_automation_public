from __future__ import annotations

import sys


def main() -> int:
    if "--marketplace" not in sys.argv:
        sys.argv.extend(["--marketplace", "ALL"])
    from main import main as run_main

    return run_main()


if __name__ == "__main__":
    raise SystemExit(main())
