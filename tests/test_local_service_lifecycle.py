from __future__ import annotations

from pathlib import Path
import plistlib


def test_project_chrome_cdp_match_requires_project_profile() -> None:
    from scripts import stop_local_services as stop

    project_command = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        "--remote-debugging-port=9222 "
        f"--user-data-dir={stop.CHROME_PROFILE_DIR} about:blank"
    )
    normal_chrome_command = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        "--remote-debugging-port=9222 "
        "--user-data-dir=/Users/lynn/Library/Application Support/Google/Chrome"
    )
    other_project_command = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        "--remote-debugging-port=9222 "
        "--user-data-dir=/tmp/other-project/data/output/chrome_cdp_profile"
    )

    assert stop._is_project_chrome_cdp(project_command)
    assert not stop._is_project_chrome_cdp(normal_chrome_command)
    assert not stop._is_project_chrome_cdp(other_project_command)


def test_find_local_service_processes_limits_report_server_to_listener_pid() -> None:
    from scripts import stop_local_services as stop

    rows = [
        (111, "/usr/bin/python3 scripts/report_action_server.py"),
        (222, "/usr/bin/python3 scripts/report_action_server.py"),
        (
            333,
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            "--remote-debugging-port=9222 "
            f"--user-data-dir={stop.CHROME_PROFILE_DIR} about:blank",
        ),
    ]

    matches = stop.find_local_service_processes(rows=rows, listener_pids={222}, require_health=False)

    assert [(match.pid, match.reason) for match in matches] == [
        (222, "report_action_server"),
        (333, "chrome_cdp_profile"),
    ]


def test_run_today_report_command_uses_window_scoped_session() -> None:
    root = Path(__file__).resolve().parents[1]
    command = (root / "run_today_report.command").read_text(encoding="utf-8")

    assert 'exec "$PYTHON" scripts/run_report_window.py --workflow daily' in command
    assert "scripts/ensure_report_action_server.py" not in command


def test_retry_and_service_commands_use_window_scoped_session() -> None:
    root = Path(__file__).resolve().parents[1]
    retry = (root / "retry_frontend_checks.command").read_text(encoding="utf-8")
    service = (root / "start_report_action_server.command").read_text(encoding="utf-8")

    assert 'exec "$PYTHON" scripts/run_report_window.py --workflow frontend-retry' in retry
    assert "scripts/ensure_report_action_server.py" not in retry
    assert 'exec "$PYTHON" scripts/run_report_window.py --workflow service-only' in service


def test_terminal_launchers_run_window_scoped_sessions() -> None:
    root = Path(__file__).resolve().parents[1]
    terminal_expectations = {
        "run_today_report.terminal": "--workflow daily",
        "retry_frontend_checks.terminal": "--workflow frontend-retry",
        "start_report_action_server.terminal": "--workflow service-only",
    }

    if all((root / filename).exists() for filename in terminal_expectations):
        for filename, workflow in terminal_expectations.items():
            payload = plistlib.loads((root / filename).read_bytes())
            command = payload["CommandString"]
            assert "scripts/run_report_window.py" in command
            assert workflow in command
            assert payload["RunCommandAsShell"] is False
        return

    command_expectations = {
        "run_today_report.command": "--workflow daily",
        "retry_frontend_checks.command": "--workflow frontend-retry",
        "start_report_action_server.command": "--workflow service-only",
    }
    for filename, workflow in command_expectations.items():
        command = (root / filename).read_text(encoding="utf-8")
        assert "scripts/run_report_window.py" in command
        assert workflow in command
