from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

try:
    from scripts import stop_local_services
except ModuleNotFoundError:  # pragma: no cover
    import stop_local_services  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
REPORT_URL = "http://127.0.0.1:8765/report/latest_recommendations.html"
HEALTH_URL = "http://127.0.0.1:8765/health"

_children: list[subprocess.Popen[object]] = []
_cleaned = False


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    root = str(ROOT)
    env["PYTHONPATH"] = root if not existing else f"{root}{os.pathsep}{existing}"
    return env


def _health_ok(timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError):
        return False
    return 200 <= getattr(response, "status", 0) < 300 and "report_action_server" in body


def _wait_for_server(process: subprocess.Popen[object], wait_seconds: float = 8.0) -> None:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _health_ok():
            return
        if process.poll() is not None:
            raise RuntimeError(f"report_action_server.py exited early with code {process.returncode}")
        time.sleep(0.25)
    raise RuntimeError("report_action_server.py did not become ready on http://127.0.0.1:8765")


def _terminate_children() -> None:
    for process in list(_children):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if all(process.poll() is not None for process in _children):
            return
        time.sleep(0.1)
    for process in list(_children):
        if process.poll() is None:
            process.kill()


def cleanup() -> None:
    global _cleaned
    if _cleaned:
        return
    _cleaned = True
    _terminate_children()
    stop_local_services.stop_local_services(quiet=False)


def _signal_handler(signum: int, _frame: object) -> None:
    print(f"\n[session] received signal {signum}; closing local services", flush=True)
    cleanup()
    raise SystemExit(128 + signum)


def _install_signal_handlers() -> None:
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, _signal_handler)


def _start_report_server() -> subprocess.Popen[object]:
    process = subprocess.Popen([sys.executable, "scripts/report_action_server.py"], cwd=ROOT, env=_child_env())
    _children.append(process)
    _wait_for_server(process)
    return process


def _run_checked(command: list[str]) -> int:
    process = subprocess.Popen(command, cwd=ROOT, env=_child_env())
    _children.append(process)
    return process.wait()


def _open_report() -> None:
    if not webbrowser.open(REPORT_URL):
        print(REPORT_URL, flush=True)


def _wait_for_enter() -> None:
    print("", flush=True)
    print("本地按钮服务正在运行。按 Enter 或关闭这个窗口后，会自动停止本项目服务。", flush=True)
    try:
        input()
    except EOFError:
        pass


def run_workflow(workflow: str) -> int:
    print("[session] cleaning stale project services before start", flush=True)
    stop_local_services.stop_local_services(quiet=False)
    print("[session] starting report button service", flush=True)
    _start_report_server()

    if workflow == "service-only":
        _open_report()
        _wait_for_enter()
        return 0

    if workflow == "daily":
        print("[session] running daily update", flush=True)
        code = _run_checked([sys.executable, "scripts/run_daily_update.py"])
    elif workflow == "frontend-retry":
        print("[session] running frontend checks and report refresh", flush=True)
        code = _run_checked([sys.executable, "scripts/run_all_with_frontend_checks.py"])
    else:
        raise ValueError(f"unsupported workflow: {workflow}")

    if code == 0:
        _open_report()
        _wait_for_enter()
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Amazon Ops Automation in a window-scoped local session.")
    parser.add_argument(
        "--workflow",
        choices=("daily", "frontend-retry", "service-only"),
        default="daily",
    )
    args = parser.parse_args()
    _install_signal_handlers()
    try:
        return run_workflow(args.workflow)
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
