from __future__ import annotations

from pathlib import Path

import scripts.check_daily_update_preflight as preflight


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    inbox = root / "data" / "inbox"
    unknown = inbox / "_unknown"
    unknown.mkdir(parents=True)
    monkeypatch.setattr(preflight, "ROOT", root)
    monkeypatch.setattr(preflight, "INBOX", inbox)
    monkeypatch.setattr(preflight, "UNKNOWN_DIR", unknown)
    return inbox


def test_preflight_blocks_unknown_business_files(monkeypatch, tmp_path, capsys) -> None:
    inbox = _patch_paths(monkeypatch, tmp_path)
    (inbox / "_unknown" / "metric.xlsx").write_text("placeholder", encoding="utf-8")

    code = preflight.main([])
    output = capsys.readouterr().out

    assert code == 1
    assert "unknown inbox business files" in output
    assert "data/inbox/_unknown/metric.xlsx" in output


def test_preflight_requires_explicit_allow_for_pending_business_files(monkeypatch, tmp_path, capsys) -> None:
    inbox = _patch_paths(monkeypatch, tmp_path)
    (inbox / "ads_report_all.csv").write_text("placeholder", encoding="utf-8")

    blocked_code = preflight.main([])
    blocked_output = capsys.readouterr().out
    allowed_code = preflight.main(["--allow-inbox-business-files"])
    allowed_output = capsys.readouterr().out

    assert blocked_code == 1
    assert "pass --allow-inbox-business-files" in blocked_output
    assert allowed_code == 0
    assert "daily update will import inbox business files" in allowed_output


def test_preflight_allows_noise_files(monkeypatch, tmp_path, capsys) -> None:
    inbox = _patch_paths(monkeypatch, tmp_path)
    (inbox / ".DS_Store").write_text("placeholder", encoding="utf-8")

    code = preflight.main([])
    output = capsys.readouterr().out

    assert code == 0
    assert "ignored inbox noise files" in output
    assert "daily update preflight passed" in output
