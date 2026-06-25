from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_step(args: list[str]) -> int:
    print("[run]", " ".join(args), flush=True)
    completed = subprocess.run(args, cwd=ROOT)
    print("[exit]", completed.returncode, flush=True)
    return completed.returncode


def run_frontend_price_sync(python: str) -> int:
    chrome_step = [
        python,
        "scripts/sync_frontend_prices.py",
        "--check",
        "--apply",
        "--method",
        "chrome",
        "--timeout",
        "30",
        "--scope",
        "ad-flagged",
    ]
    code = run_step(chrome_step)
    if code == 0:
        return 0

    fallback_step = [
        python,
        "scripts/sync_frontend_prices.py",
        "--check",
        "--apply",
        "--method",
        "playwright",
        "--timeout",
        "30",
        "--scope",
        "ad-flagged",
    ]
    print("[warn] Chrome price sync failed; retrying with Playwright Chromium.", flush=True)
    code = run_step(fallback_step)
    if code == 0:
        return 0

    print("[warn] Frontend price sync failed; continuing with cached/frontend-check fallback.", flush=True)
    return 0


def _browser_frontend_enabled(cli_enabled: bool, cli_disabled: bool) -> bool:
    if cli_disabled:
        return False
    if cli_enabled:
        return True
    value = os.environ.get("AMAZON_OPS_ENABLE_BROWSER_FRONTEND", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ALL reports with optional frontend enrichment.")
    parser.add_argument(
        "--live-browser-frontend",
        action="store_true",
        help="允许启动 Chrome/Playwright 做实时前台价格同步和页面检查。默认禁用，避免 macOS 权限环境弹出浏览器崩溃提示。",
    )
    parser.add_argument(
        "--no-live-browser-frontend",
        action="store_true",
        help="强制禁用 Chrome/Playwright，即使环境变量 AMAZON_OPS_ENABLE_BROWSER_FRONTEND 已设置也不启动浏览器。",
    )
    parser.add_argument(
        "--frontend-method",
        choices=["auto", "chrome", "chrome-persistent", "playwright", "urllib"],
        default="",
        help="前台检查读取方式。未指定时，安全模式使用 urllib；live-browser 模式使用 auto。",
    )
    args = parser.parse_args()

    python = sys.executable
    browser_enabled = _browser_frontend_enabled(args.live_browser_frontend, args.no_live_browser_frontend)
    frontend_method = args.frontend_method or ("auto" if browser_enabled else "urllib")
    steps = [
        [python, "main.py", "--marketplace", "ALL"],
        [
            python,
            "scripts/run_frontend_checks.py",
            "--method",
            frontend_method,
            "--timeout",
            "30",
            "--retries",
            "3",
            "--search-policy",
            "ad-driven",
            *(["--reuse-browser-session"] if browser_enabled else []),
        ],
        [python, "main.py", "--marketplace", "ALL"],
    ]
    code = run_step(steps[0])
    if code != 0:
        return code
    if browser_enabled:
        run_frontend_price_sync(python)
    else:
        print(
            "[skip] Browser frontend disabled; skipping Chrome/Playwright price sync to avoid macOS crash prompts.",
            flush=True,
        )
    for step in steps[1:]:
        code = run_step(step)
        if code != 0:
            return code
    mode = "live browser frontend" if browser_enabled else "no-browser cached/urllib frontend"
    print(f"[done] reports refreshed with {mode} and frontend_check_results.json", flush=True)
    print(f"[open] {ROOT / 'data' / 'output' / 'latest_recommendations.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
