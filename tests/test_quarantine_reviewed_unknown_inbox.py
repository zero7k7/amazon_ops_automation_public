from __future__ import annotations

from pathlib import Path

import scripts.quarantine_reviewed_unknown_inbox as quarantine


def test_reviewed_quarantine_candidates_keep_only_allowed_existing_files(tmp_path) -> None:
    promo = tmp_path / "promo.xlsx"
    promo.write_text("placeholder", encoding="utf-8")
    generic = tmp_path / "generic.xlsx"
    generic.write_text("placeholder", encoding="utf-8")

    rows = [
        {"original_path": str(promo), "likely_report_type": "seller_central_promotion_metrics"},
        {"original_path": str(generic), "likely_report_type": "unknown"},
        {"original_path": str(tmp_path / "missing.xlsx"), "likely_report_type": "seller_central_promotion_metrics"},
    ]

    candidates = quarantine.reviewed_quarantine_candidates(rows)

    assert candidates == [rows[0]]


def test_quarantine_candidates_dry_run_does_not_move(tmp_path) -> None:
    source = tmp_path / "promo.xlsx"
    source.write_text("placeholder", encoding="utf-8")
    destination = tmp_path / "reviewed"

    actions = quarantine.quarantine_candidates(
        [{"original_path": str(source), "likely_report_type": "seller_central_promotion_metrics"}],
        destination_dir=destination,
        apply=False,
    )

    assert source.exists()
    assert not (destination / source.name).exists()
    assert actions[0]["mode"] == "dry_run"


def test_quarantine_candidates_apply_moves_file(tmp_path) -> None:
    source = tmp_path / "promo.xlsx"
    source.write_text("placeholder", encoding="utf-8")
    destination = tmp_path / "reviewed"

    actions = quarantine.quarantine_candidates(
        [{"original_path": str(source), "likely_report_type": "seller_central_promotion_metrics"}],
        destination_dir=destination,
        apply=True,
    )

    moved = Path(actions[0]["destination"])
    assert not source.exists()
    assert moved.exists()
    assert moved.read_text(encoding="utf-8") == "placeholder"
    assert actions[0]["mode"] == "moved"
