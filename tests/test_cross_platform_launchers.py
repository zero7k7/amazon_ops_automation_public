from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_launchers_use_window_scoped_report_sessions() -> None:
    expectations = {
        "run_today_report.bat": "--workflow daily",
        "retry_frontend_checks.bat": "--workflow frontend-retry",
        "start_report_action_server.bat": "--workflow service-only",
    }

    for filename, workflow in expectations.items():
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert "scripts\\windows_python.bat" in text
        assert "scripts\\run_report_window.py" in text
        assert workflow in text


def test_import_and_uk_bat_use_public_python_resolver() -> None:
    for filename in ["scripts/import_and_run_all.bat", "scripts/run_uk_daily_report.bat"]:
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert "scripts\\windows_python.bat" in text
        assert "C:\\Users\\Admin" not in text
        assert ".venv_mac" not in text


def test_report_window_opens_with_cross_platform_webbrowser(monkeypatch) -> None:
    from scripts import run_report_window

    opened: list[str] = []
    monkeypatch.setattr(run_report_window.webbrowser, "open", lambda url: opened.append(url) or True)

    run_report_window._open_report()

    assert opened == [run_report_window.REPORT_URL]


def test_stop_local_services_matches_windows_paths_and_netstat() -> None:
    from scripts import stop_local_services as stop

    command = (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe "
        "--remote-debugging-port=9222 "
        f"--user-data-dir={stop.CHROME_PROFILE_DIR}"
    )
    assert stop._is_project_chrome_cdp(command)

    netstat = """
      Proto  Local Address          Foreign Address        State           PID
      TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       4321
      TCP    127.0.0.1:9222         0.0.0.0:0              LISTENING       8765
    """
    assert stop._listener_pids_from_netstat(netstat, 8765) == {4321}
