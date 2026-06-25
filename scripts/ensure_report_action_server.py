from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 8765
HEALTH_URL = f"http://{HOST}:{PORT}/health"
AD_COMPLETE_URL = f"http://{HOST}:{PORT}/feedback/ad-action-complete"
LOG_PATH = ROOT / "data" / "output" / "report_action_server.log"


def _health_payload(timeout: float = 0.8) -> dict[str, object]:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                return {}
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return {}


def _health_ok(timeout: float = 0.8) -> bool:
    payload = _health_payload(timeout=timeout)
    return payload.get("service") == "report_action_server"


def _port_has_http_health(timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def _ad_completion_endpoint_ok(timeout: float = 0.8) -> bool:
    request = urllib.request.Request(
        AD_COMPLETE_URL,
        data=json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
        except Exception:
            payload = {}
        message = str(payload.get("message") or "")
        return exc.code == 403 and "token" in message
    except (OSError, urllib.error.URLError):
        return False
    return True


def _listener_pids() -> list[int]:
    try:
        completed = subprocess.run(
            ["lsof", "-tiTCP:8765", "-sTCP:LISTEN"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return []
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        try:
            pids.append(int(line.strip()))
        except ValueError:
            continue
    return pids


def _stop_stale_server() -> None:
    for pid in _listener_pids():
        try:
            os.kill(pid, 15)
            print(f"[report-action-server] stopped stale listener pid={pid}", flush=True)
        except OSError:
            continue
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not _health_ok(timeout=0.2):
            return
        time.sleep(0.2)


def ensure_server(wait_seconds: float = 5.0) -> int:
    health_payload = _health_payload()
    if health_payload.get("service") == "report_action_server" and _ad_completion_endpoint_ok():
        print(f"[report-action-server] already running at {HEALTH_URL}", flush=True)
        return 0
    if health_payload.get("service") == "report_action_server":
        print("[report-action-server] stale server detected; restarting", flush=True)
        _stop_stale_server()
    elif _port_has_http_health():
        print(
            f"[report-action-server] port {PORT} is used by another HTTP service; stop it before starting report_action_server",
            file=sys.stderr,
            flush=True,
        )
        return 1

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_PATH.open("a", encoding="utf-8")
    command = [sys.executable, "scripts/report_action_server.py"]
    subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"[report-action-server] starting in background; log: {LOG_PATH}", flush=True)

    deadline = time.monotonic() + max(wait_seconds, 0.5)
    while time.monotonic() < deadline:
        if _health_ok():
            print(f"[report-action-server] ready at {HEALTH_URL}", flush=True)
            return 0
        time.sleep(0.25)

    print(f"[report-action-server] failed to become ready; see {LOG_PATH}", file=sys.stderr, flush=True)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure the local report action server is running.")
    parser.add_argument("--wait-seconds", type=float, default=5.0)
    args = parser.parse_args()
    return ensure_server(wait_seconds=args.wait_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
