from __future__ import annotations

from pathlib import Path

from src.sellersprite_history import (
    build_sellersprite_history_summary,
    load_sellersprite_history,
    sellersprite_cache_max_age_days_for_row,
    upsert_sellersprite_history,
)


def _record(asin: str, keyword: str, *, data_date: str, rank: str = "10", ppc: str = "1.00", source_role: str = "own", parent_asin: str = "") -> dict:
    return {
        "marketplace": "US",
        "sku": "SKU-1" if source_role == "own" else "COMP-SKU",
        "asin": asin,
        "source_role": source_role,
        "parent_marketplace": "US" if parent_asin else "",
        "parent_sku": "SKU-1" if parent_asin else "",
        "parent_asin": parent_asin,
        "seller_sprite_check_status": "已抓取",
        "data_date": data_date,
        "keywords": [{"keyword": keyword, "natural_rank": rank, "ppc": ppc, "monthly_searches": "1000"}],
    }


def test_sellersprite_history_upsert_dedupes_same_day_keyword(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"

    upsert_sellersprite_history([_record("B0OWN00001", "cable ties", data_date="2026-07-01", rank="10")], path=path, report_date="2026-07-01")
    upsert_sellersprite_history([_record("B0OWN00001", "cable ties", data_date="2026-07-01", rank="8")], path=path, report_date="2026-07-01")

    rows = load_sellersprite_history(path)
    assert len(rows) == 1
    assert rows[0]["natural_rank"] == "8"


def test_sellersprite_history_detects_keyword_trends_and_stable_competitors(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    upsert_sellersprite_history(
        [
            _record("B0OWN00001", "stable demand", data_date="2026-07-01", rank="20", ppc="1.00"),
            _record("B0OWN00001", "lost demand", data_date="2026-07-01", rank="30", ppc="0.80"),
            _record("B0COMP0001", "competitor gap", data_date="2026-07-01", source_role="competitor", parent_asin="B0OWN00001"),
        ],
        path=path,
        report_date="2026-07-01",
    )
    upsert_sellersprite_history(
        [
            _record("B0OWN00001", "stable demand", data_date="2026-07-02", rank="15", ppc="1.20"),
            _record("B0OWN00001", "lost demand", data_date="2026-07-02", rank="25", ppc="0.75"),
            _record("B0COMP0001", "competitor gap", data_date="2026-07-02", source_role="competitor", parent_asin="B0OWN00001"),
        ],
        path=path,
        report_date="2026-07-02",
    )
    upsert_sellersprite_history(
        [
            _record("B0OWN00001", "stable demand", data_date="2026-07-03", rank="9", ppc="1.50"),
            _record("B0OWN00001", "new demand", data_date="2026-07-03", rank="40", ppc="0.50"),
            _record("B0COMP0001", "competitor gap", data_date="2026-07-03", source_role="competitor", parent_asin="B0OWN00001"),
        ],
        path=path,
        report_date="2026-07-03",
    )

    summary = build_sellersprite_history_summary(
        {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001"},
        own_record=_record("B0OWN00001", "stable demand", data_date="2026-07-03"),
        target_asins=["B0COMP0001"],
        history_rows=load_sellersprite_history(path),
        report_date="2026-07-03",
    )

    assert summary["sellersprite_today_status"] == "今日已抓"
    assert summary["sellersprite_trend_status"] == "3天趋势可用"
    assert summary["sellersprite_persistent_keywords"] == "stable demand"
    assert summary["sellersprite_new_keywords"] == "new demand"
    assert summary["sellersprite_lost_keywords"] == "lost demand"
    assert summary["sellersprite_rank_improved_keywords"] == "stable demand"
    assert summary["sellersprite_ppc_up_keywords"] == "stable demand"
    assert summary["competitor_stable_asins"] == "B0COMP0001"
    assert summary["own_missing_competitor_keywords_trend"] == "competitor gap"
    assert summary["competitor_pressure_trend"] == "持续高"
    assert summary["sellersprite_evidence_tier"] == "今日趋势证据"


def test_sellersprite_history_uses_newer_snapshot_when_report_date_lags(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    upsert_sellersprite_history(
        [_record("B0OWN00001", "current demand", data_date="2026-07-03")],
        path=path,
        report_date="2026-07-03",
    )

    summary = build_sellersprite_history_summary(
        {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001"},
        own_record=_record("B0OWN00001", "current demand", data_date="2026-07-03"),
        history_rows=load_sellersprite_history(path),
        report_date="2026-07-02",
    )

    assert summary["sellersprite_today_status"] == "今日已抓"
    assert summary["sellersprite_cache_date"] == "2026-07-03"
    assert summary["sellersprite_evidence_tier"] == "今日单日证据"


def test_current_success_snapshot_overrides_same_day_failure_history(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    upsert_sellersprite_history(
        [
            {
                "marketplace": "US",
                "sku": "SKU-1",
                "asin": "B0OWN00001",
                "seller_sprite_check_status": "抓取失败",
                "data_date": "2026-07-03",
                "keywords": [],
            }
        ],
        path=path,
        report_date="2026-07-03",
    )
    upsert_sellersprite_history(
        [_record("B0OWN00001", "current demand", data_date="2026-07-03")],
        path=path,
        report_date="2026-07-03",
    )

    summary = build_sellersprite_history_summary(
        {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001"},
        own_record=_record("B0OWN00001", "current demand", data_date="2026-07-03"),
        history_rows=load_sellersprite_history(path),
        report_date="2026-07-03",
    )

    assert summary["sellersprite_today_status"] == "今日已抓"
    assert summary["sellersprite_evidence_tier"] == "今日单日证据"


def test_same_day_reused_sellersprite_cache_counts_as_current_evidence(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    upsert_sellersprite_history(
        [_record("B0OWN00001", "current demand", data_date="2026-07-03")],
        path=path,
        report_date="2026-07-03",
        snapshot_status="沿用缓存",
    )

    summary = build_sellersprite_history_summary(
        {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001"},
        own_record={**_record("B0OWN00001", "current demand", data_date="2026-07-03"), "seller_sprite_check_status": "沿用缓存"},
        history_rows=load_sellersprite_history(path),
        report_date="2026-07-03",
    )

    assert summary["sellersprite_today_status"] == "今日已抓"
    assert summary["sellersprite_evidence_tier"] == "今日单日证据"


def test_sellersprite_cache_age_rules_prioritize_own_and_p0_competitor() -> None:
    assert sellersprite_cache_max_age_days_for_row({"source_role": "own"}, competitor_cache_days=7) == 0
    assert sellersprite_cache_max_age_days_for_row({"source_role": "competitor", "priority": "P0"}, competitor_cache_days=7) == 0
    assert sellersprite_cache_max_age_days_for_row({"source_role": "competitor", "priority": "P2"}, competitor_cache_days=7) == 7
