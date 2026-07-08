from __future__ import annotations

from src.html_pages.components_cards import _seller_sprite_product_summary
from src.market_survey_completeness import (
    build_market_survey_fetch_plan,
    compute_market_survey_completeness,
)


REPORT_DATE = "2026-07-03"


def _complete_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "marketplace": "US",
        "sku": "SKU-1",
        "asin": "B0OWN00001",
        "product_name": "Test Product",
        "priority": "P2",
        "frontend_check_status": "已自动检查",
        "frontend_price": "$19.99",
        "frontend_rating": "4.6",
        "frontend_reviews": "1234",
        "frontend_buy_box": "已识别",
        "frontend_coupon": "5%",
        "frontend_delivery": "Prime",
        "amazon_search_validation_status": "已验证",
        "competitor_frontend_count": 3,
        "comparable_competitor_count": 3,
        "seller_sprite_check_status": "已抓取",
        "sellersprite_today_status": "今日已抓",
        "seller_sprite_data_date": REPORT_DATE,
        "seller_sprite_keyword_count": 8,
        "competitor_pool_status": "有效",
        "competitor_pool_count": 3,
        "competitor_pool_confidence": "high",
        "main_competitor_count": 2,
        "main_competitor_asins": "B0COMP0001、B0COMP0002",
        "reference_competitor_count": 1,
        "competitor_comparability_score": 78,
        "competitor_spec_match_status": "可比",
        "competitor_price_band_status": "可比",
        "competitor_review_tier_status": "可比",
        "scalable_evidence_status": "可谨慎放量",
        "competitor_overlap_keywords": "cable ties; wire ties",
        "competitor_sellersprite_status": "已抓取",
        "competitor_sellersprite_asin_count": 3,
        "competitor_sellersprite_keyword_count": 18,
        "sellersprite_trend_status": "3天趋势可用",
        "sellersprite_history_days": 3,
    }
    row.update(overrides)
    return row


def test_product_page_success_without_sellersprite_cannot_be_complete() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            seller_sprite_check_status="待补",
            sellersprite_today_status="",
            seller_sprite_keyword_count=0,
        ),
        report_date=REPORT_DATE,
    )

    assert result["market_survey_completeness_level"] != "complete"
    assert result["market_survey_decision_evidence_tier"] != "strong"
    assert "卖家精灵自己 ASIN" in result["market_survey_missing_parts"]


def test_own_sellersprite_without_competitor_pool_cannot_be_complete() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            competitor_pool_status="待补",
            competitor_pool_count=0,
            competitor_pool_confidence="",
            competitor_overlap_keywords="",
            competitor_sellersprite_status="待补",
            competitor_sellersprite_asin_count=0,
            competitor_sellersprite_keyword_count=0,
        ),
        report_date=REPORT_DATE,
    )

    assert result["market_survey_completeness_level"] != "complete"
    assert "卖家精灵竞品池" in result["market_survey_missing_parts"]
    assert "补抓卖家精灵竞品池" in result["market_survey_recommended_fetch_steps"]


def test_shell_title_competitor_pool_is_penalized_and_marked_missing() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            competitor_rejected_count=3,
            competitor_rejection_reasons="标题为空或页面壳文本 3",
            competitor_shell_title_count=3,
        ),
        report_date=REPORT_DATE,
    )

    assert result["market_survey_completeness_level"] != "complete"
    assert int(result["sellersprite_data_quality_penalty"]) >= 5
    assert "页面壳" in result["market_survey_missing_parts"]


def test_high_confidence_pool_with_zero_overlap_is_not_strong() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            competitor_overlap_keywords="",
            competitor_source_keywords="",
            competitor_overlap_zero_count=3,
        ),
        report_date=REPORT_DATE,
    )

    assert result["market_survey_completeness_level"] != "complete"
    assert result["market_survey_decision_evidence_tier"] != "strong"
    assert "overlap" in result["market_survey_missing_parts"]


def test_competitor_reverse_below_two_of_three_downgrades_completeness() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            competitor_sellersprite_asin_count=1,
            competitor_sellersprite_keyword_count=5,
        ),
        report_date=REPORT_DATE,
    )

    assert result["market_survey_completeness_level"] != "complete"
    assert "竞品 ASIN 反查至少 2" in result["market_survey_missing_parts"]


def test_history_below_three_days_has_low_trend_score() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            sellersprite_trend_status="趋势不足",
            sellersprite_history_days=1,
        ),
        report_date=REPORT_DATE,
    )

    assert result["sellersprite_trend_completeness"] == 3
    assert "卖家精灵至少 3 天趋势" in result["market_survey_missing_parts"]


def test_old_cache_is_not_strong_evidence() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            sellersprite_today_status="沿用缓存",
            seller_sprite_data_date="2026-07-01",
            sellersprite_cache_date="2026-07-01",
        ),
        report_date=REPORT_DATE,
    )

    assert result["market_survey_decision_evidence_tier"] == "usable"
    assert "卖家精灵自己 ASIN 今日快照" in result["market_survey_missing_parts"]


def test_sellersprite_snapshot_after_report_date_counts_as_current_evidence() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            sellersprite_today_status="今日已抓",
            seller_sprite_data_date="2026-07-03",
            sellersprite_cache_date="2026-07-03",
        ),
        report_date="2026-07-02",
    )

    assert result["sellersprite_own_completeness"] == 20
    assert "卖家精灵自己 ASIN 今日快照" not in result["market_survey_missing_parts"]


def test_keyword_field_quality_gap_recommends_parser_review_not_refetch() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            seller_sprite_ppc_missing_count=7,
            competitor_sellersprite_ppc_missing_count=12,
        ),
        report_date=REPORT_DATE,
    )

    assert "复核卖家精灵自己 ASIN 字段解析" in result["market_survey_recommended_fetch_steps"]
    assert "复核竞品反查字段解析" in result["market_survey_recommended_fetch_steps"]
    assert "补抓卖家精灵自己 ASIN" not in result["market_survey_recommended_fetch_steps"]
    assert "补抓竞品 ASIN 反查" not in result["market_survey_recommended_fetch_steps"]


def test_partial_keyword_field_gaps_do_not_block_market_survey_analysis() -> None:
    result = compute_market_survey_completeness(
        _complete_row(
            seller_sprite_keyword_count=8,
            seller_sprite_ppc_missing_count=1,
            seller_sprite_monthly_searches_missing_count=2,
            competitor_sellersprite_keyword_count=18,
            competitor_sellersprite_ppc_missing_count=3,
            competitor_sellersprite_monthly_searches_missing_count=4,
        ),
        report_date=REPORT_DATE,
    )

    assert "自己 ASIN 关键词字段质量" not in result["market_survey_missing_parts"]
    assert "竞品反查字段质量" not in result["market_survey_missing_parts"]
    assert "PPC 字段缺失过半" not in result["market_survey_missing_parts"]
    assert "月搜索字段缺失过半" not in result["market_survey_missing_parts"]


def test_p0_missing_today_sellersprite_snapshot_gets_own_asin_fetch_step() -> None:
    plan = build_market_survey_fetch_plan(
        [
            _complete_row(
                priority="P0",
                sellersprite_today_status="沿用缓存",
                seller_sprite_data_date="2026-07-02",
                sellersprite_cache_date="2026-07-02",
            )
        ],
        report_date=REPORT_DATE,
    )

    assert plan[0]["fetch_priority"] == "P0"
    assert "补抓卖家精灵自己 ASIN" in plan[0]["recommended_fetch_steps"]


def test_complete_ordinary_product_is_skipped() -> None:
    plan = build_market_survey_fetch_plan([_complete_row()], report_date=REPORT_DATE)

    assert plan[0]["completeness_level"] == "complete"
    assert plan[0]["skip_reason"] == "今日市场调查完整，普通产品跳过补抓"
    assert plan[0]["recommended_fetch_steps"] == ""


def test_product_card_displays_market_survey_quality_gap_and_fetch_step() -> None:
    row = _complete_row(
        **compute_market_survey_completeness(
            _complete_row(
                competitor_pool_status="待补",
                competitor_pool_count=0,
                competitor_pool_confidence="",
                competitor_overlap_keywords="",
                competitor_sellersprite_status="待补",
                competitor_sellersprite_asin_count=0,
                competitor_sellersprite_keyword_count=0,
            ),
            report_date=REPORT_DATE,
        )
    )

    html = _seller_sprite_product_summary(row)

    assert "市场调查完整度" in html
    assert "Amazon 前台完整度" in html
    assert "卖家精灵完整度" in html
    assert "竞品完整度" in html
    assert "趋势完整度" in html
    assert "缺口" in html
    assert "补抓卖家精灵竞品池" in html
