from __future__ import annotations

import sys


def test_chrome_cdp_helper_builds_launch_and_probe_commands(monkeypatch, tmp_path) -> None:
    from scripts import chrome_cdp_helper as helper

    monkeypatch.setattr(helper, "endpoint_available", lambda endpoint: False)

    payload = helper.build_status_payload(
        marketplace="UK",
        asin="B0DEMOFRNT",
        endpoint="http://127.0.0.1:9222",
        port=9222,
        attempts=20,
        profile_dir=tmp_path / "chrome-profile",
        chrome_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )

    launch = payload["chrome_launch_command"]
    probe = payload["probe_command"]
    assert payload["endpoint_available"] is False
    assert "--remote-debugging-port=9222" in launch
    assert f"--user-data-dir={tmp_path / 'chrome-profile'}" in launch
    assert launch[-1] == "https://www.amazon.co.uk/dp/B0DEMOFRNT?th=1"
    assert probe[:4] == [sys.executable, "scripts/run_frontend_checks.py", "--method", "chrome-cdp"]
    assert "--cdp-attempts" in probe
    assert "20" in probe


def test_chrome_cdp_helper_accepts_windows_chrome_path(monkeypatch, tmp_path) -> None:
    from scripts import chrome_cdp_helper as helper

    monkeypatch.setattr(helper, "endpoint_available", lambda endpoint: False)

    payload = helper.build_status_payload(
        marketplace="US",
        asin="B0DEMOFRNT",
        profile_dir=tmp_path / "chrome-profile",
        chrome_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        python=r"C:\repo\.venv\Scripts\python.exe",
    )

    assert payload["chrome_launch_command"][0].endswith("chrome.exe")
    assert payload["probe_command"][0] == r"C:\repo\.venv\Scripts\python.exe"
    assert payload["chrome_launch_command"][-1] == "https://www.amazon.com/dp/B0DEMOFRNT"


def test_chrome_cdp_helper_json_output(monkeypatch, capsys) -> None:
    import sys

    from scripts import chrome_cdp_helper as helper

    monkeypatch.setattr(helper, "endpoint_available", lambda endpoint: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chrome_cdp_helper.py",
            "--marketplace",
            "UK",
            "--asin",
            "B0DEMOFRNT",
            "--json",
        ],
    )

    code = helper.main()

    assert code == 0
    output = capsys.readouterr().out
    assert '"endpoint_available": true' in output
    assert '"--cdp-attempts"' in output
