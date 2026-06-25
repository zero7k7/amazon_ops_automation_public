from __future__ import annotations

import pandas as pd

from src import report_presentation
from src.analyze_rules import _is_low_acos, _target_acos_value
from src.report_presentation import _apply_manual_feedback_to_search_queue, _search_term_action_from_item


def search_item(target: str, clicks: int, spend: float, **evidence: object) -> dict:
    payload = {
        "category": "搜索词",
        "target": target,
        "action": evidence.pop("action", ""),
        "note": evidence.pop("note", ""),
        "evidence": {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B000TEST01",
            "product_name": "Test product",
            "search_term": target,
            "clicks": clicks,
            "spend": spend,
            "ad_orders": 0,
            "intent": "core_relevant",
            **evidence,
        },
    }
    return payload


def test_bid_down_copy_line_never_says_price_down() -> None:
    row = _search_term_action_from_item(search_item("bamboo cutting board", 12, 6), "US")

    assert row["suggested_action"] == "降竞价10%-20%"
    assert row["copy_action_line"] == "建议降竞价 10%-15%"
    assert "降价" not in row["copy_action_line"]


def test_low_sample_asin_target_stays_watch() -> None:
    row = _search_term_action_from_item(
        search_item("B012345678", 3, 1.2, is_asin_term=True, intent="unknown"),
        "US",
    )

    assert row["suggested_action"] == "观察"
    assert row["copy_action_line"] == "建议观察"


def test_search_queue_feedback_matches_exact_term_not_whole_product(monkeypatch) -> None:
    rows = [
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B000TEST01",
            "search_term_or_target": "first term",
            "suggested_action": "降竞价10%-20%",
        },
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B000TEST01",
            "search_term_or_target": "second term",
            "suggested_action": "降竞价10%-20%",
        },
    ]
    monkeypatch.setattr(
        report_presentation,
        "load_feedback_input",
        lambda *_args, **_kwargs: [
            {
                "marketplace": "US",
                "sku": "SKU-1",
                "asin": "B000TEST01",
                "search_term_or_target": "first term",
                "suggested_action": "降竞价10%-20%",
                "confirmed_status": "已执行",
            }
        ],
    )

    updated = _apply_manual_feedback_to_search_queue(rows)

    assert updated[0]["confirmed_status"] == "已执行"
    assert updated[1]["confirmed_status"] == "待确认"


def test_product_level_feedback_does_not_mark_watch_rows_executed(monkeypatch) -> None:
    rows = [
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B000TEST01",
            "search_term_or_target": "watch term",
            "suggested_action": "观察",
        },
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B000TEST01",
            "search_term_or_target": "bid down term",
            "suggested_action": "降竞价10%-20%",
        },
    ]
    monkeypatch.setattr(
        report_presentation,
        "load_feedback_input",
        lambda *_args, **_kwargs: [
            {
                "marketplace": "US",
                "sku": "SKU-1",
                "asin": "B000TEST01",
                "confirmed_status": "已执行",
                "confirmed_note": "今天广告后台操作都做了",
            }
        ],
    )

    updated = _apply_manual_feedback_to_search_queue(rows)

    assert updated[0]["confirmed_status"] == "待确认"
    assert updated[1]["confirmed_status"] == "待确认"


def test_target_acos_zero_does_not_become_scale_threshold() -> None:
    row = pd.Series(
        {
            "target_acos": 0,
            "profit_before_ads_per_unit": -1,
            "ACOS": 0.01,
            "ad_orders": 3,
        }
    )

    assert _target_acos_value(row) is None
    assert _is_low_acos(row) is False
