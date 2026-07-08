from __future__ import annotations

import argparse
import json
import shlex
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "http://127.0.0.1:9222"
DEFAULT_PROFILE_DIR = ROOT / "data" / "output" / "chrome_cdp_profile"
MAC_CHROME_APP = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PRODUCT_URLS = {
    "UK": "https://www.amazon.co.uk/dp/{asin}?th=1",
    "US": "https://www.amazon.com/dp/{asin}",
    "DE": "https://www.amazon.de/dp/{asin}",
}


def endpoint_available(endpoint: str, timeout: int = 2) -> bool:
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(payload.get("webSocketDebuggerUrl"))


def product_url(marketplace: str, asin: str) -> str:
    marketplace = str(marketplace or "").strip().upper()
    template = PRODUCT_URLS.get(marketplace)
    if not template:
        raise ValueError(f"unsupported marketplace: {marketplace}")
    return template.format(asin=str(asin or "").strip().upper())


def chrome_launch_command(
    *,
    marketplace: str,
    asin: str,
    port: int = 9222,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    chrome_path: str = MAC_CHROME_APP,
) -> list[str]:
    return [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        product_url(marketplace, asin),
    ]


def probe_command(
    *,
    marketplace: str,
    asin: str,
    endpoint: str = DEFAULT_ENDPOINT,
    attempts: int = 20,
) -> list[str]:
    return [
        ".venv_mac/bin/python",
        "scripts/run_frontend_checks.py",
        "--method",
        "chrome-cdp",
        "--cdp-endpoint",
        endpoint,
        "--cdp-attempts",
        str(attempts),
        "--search-policy",
        "never",
        "--marketplace",
        str(marketplace or "").strip().upper(),
        "--asin",
        str(asin or "").strip().upper(),
    ]


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def build_status_payload(
    *,
    marketplace: str,
    asin: str,
    endpoint: str = DEFAULT_ENDPOINT,
    port: int = 9222,
    attempts: int = 20,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    chrome_path: str = MAC_CHROME_APP,
) -> dict[str, Any]:
    available = endpoint_available(endpoint)
    return {
        "endpoint": endpoint,
        "endpoint_available": available,
        "marketplace": str(marketplace or "").strip().upper(),
        "asin": str(asin or "").strip().upper(),
        "chrome_launch_command": chrome_launch_command(
            marketplace=marketplace,
            asin=asin,
            port=port,
            profile_dir=profile_dir,
            chrome_path=chrome_path,
        ),
        "probe_command": probe_command(
            marketplace=marketplace,
            asin=asin,
            endpoint=endpoint,
            attempts=attempts,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the real Chrome CDP setup needed for 20-run Amazon frontend validation.")
    parser.add_argument("--marketplace", default="UK")
    parser.add_argument("--asin", default="B0H73CXQ5J")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--chrome-path", default=MAC_CHROME_APP)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_status_payload(
        marketplace=args.marketplace,
        asin=args.asin,
        endpoint=args.endpoint,
        port=args.port,
        attempts=args.attempts,
        profile_dir=args.profile_dir,
        chrome_path=args.chrome_path,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"CDP endpoint: {payload['endpoint']}")
    print(f"CDP available: {payload['endpoint_available']}")
    print("Chrome launch command:")
    print(shell_join(payload["chrome_launch_command"]))
    print("20-run probe command:")
    print(shell_join(payload["probe_command"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
