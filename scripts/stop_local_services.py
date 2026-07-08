from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_SERVER_PORT = 8765
REPORT_SERVER_HEALTH_URL = f"http://127.0.0.1:{REPORT_SERVER_PORT}/health"
REPORT_SERVER_SCRIPT = ROOT / "scripts" / "report_action_server.py"
CHROME_PROFILE_DIR = ROOT / "data" / "output" / "chrome_cdp_profile"


@dataclass(frozen=True)
class ProcessMatch:
    pid: int
    command: str
    reason: str


def _ps_rows() -> list[tuple[int, str]]:
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return []

    rows: list[tuple[int, str]] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        rows.append((pid, command.strip()))
    return rows


def _listener_pids(port: int = REPORT_SERVER_PORT) -> set[int]:
    try:
        completed = subprocess.run(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return set()
    pids: set[int] = set()
    for line in completed.stdout.splitlines():
        try:
            pids.add(int(line.strip()))
        except ValueError:
            continue
    return pids


def _listener_pids_from_netstat(output: str, port: int = REPORT_SERVER_PORT) -> set[int]:
    pids: set[int] = set()
    suffix = f":{port}"
    for line in str(output or "").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        state = parts[-2].upper()
        pid_text = parts[-1]
        if not local_address.endswith(suffix) or state != "LISTENING":
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue
    return pids


def _report_server_health_ok(timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(REPORT_SERVER_HEALTH_URL, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError):
        return False
    return 200 <= getattr(response, "status", 0) < 300 and "report_action_server" in body


def _is_project_report_server(command: str) -> bool:
    normalized = command.replace("\\ ", " ")
    return (
        str(REPORT_SERVER_SCRIPT) in normalized
        or "scripts/report_action_server.py" in normalized
    )


def _is_project_chrome_cdp(command: str, profile_dir: Path = CHROME_PROFILE_DIR) -> bool:
    normalized = command.replace("\\ ", " ")
    lowered = normalized.lower()
    profile = str(profile_dir)
    return (
        ("google chrome" in lowered or "chrome.exe" in lowered or "chromium" in lowered)
        and "--remote-debugging-port=9222" in normalized
        and (
            f"--user-data-dir={profile}" in normalized
            or f"--user-data-dir {profile}" in normalized
        )
    )


def find_local_service_processes(
    *,
    rows: list[tuple[int, str]] | None = None,
    listener_pids: set[int] | None = None,
    require_health: bool = False,
) -> list[ProcessMatch]:
    current_pid = os.getpid()
    rows = _ps_rows() if rows is None else rows
    listener_pids = _listener_pids() if listener_pids is None else listener_pids
    health_ok = _report_server_health_ok() if require_health else True

    matches: list[ProcessMatch] = []
    seen: set[int] = set()
    for pid, command in rows:
        if pid == current_pid:
            continue
        if pid in listener_pids and health_ok and _is_project_report_server(command):
            matches.append(ProcessMatch(pid=pid, command=command, reason="report_action_server"))
            seen.add(pid)
            continue
        if _is_project_chrome_cdp(command):
            matches.append(ProcessMatch(pid=pid, command=command, reason="chrome_cdp_profile"))
            seen.add(pid)
    return [match for match in matches if match.pid in seen]


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_processes(matches: list[ProcessMatch], *, wait_seconds: float = 3.0) -> list[ProcessMatch]:
    if not matches:
        return []

    for match in matches:
        try:
            os.kill(match.pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except OSError:
            continue

    deadline = time.monotonic() + max(wait_seconds, 0.1)
    while time.monotonic() < deadline:
        if not any(_pid_exists(match.pid) for match in matches):
            return []
        time.sleep(0.1)

    still_running = [match for match in matches if _pid_exists(match.pid)]
    for match in still_running:
        try:
            os.kill(match.pid, signal.SIGKILL)
        except OSError:
            continue
    return still_running


def stop_local_services(*, dry_run: bool = False, quiet: bool = False) -> list[ProcessMatch]:
    matches = find_local_service_processes()
    if not quiet:
        if matches:
            for match in matches:
                print(f"[local-services] {match.reason}: pid={match.pid}", flush=True)
        else:
            print("[local-services] no project local services found", flush=True)
    if dry_run or not matches:
        return matches
    terminate_processes(matches)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop Amazon Ops Automation local helper services.")
    parser.add_argument("--dry-run", action="store_true", help="List matching project processes without stopping them.")
    parser.add_argument("--quiet", action="store_true", help="Suppress informational output.")
    args = parser.parse_args()
    stop_local_services(dry_run=args.dry_run, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
