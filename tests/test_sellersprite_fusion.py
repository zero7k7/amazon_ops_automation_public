from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from src.html_pages.components_cards import _render_frontend_coverage_strip, _seller_sprite_product_summary
from src.html_pages.components_frontend import _render_seller_sprite_summary_block
from src.report_view import frontend as frontend_view
from src.sellersprite_fusion import (
    _append_summary_to_findings,
    build_sellersprite_competitor_pool,
    enrich_report_view_rows,
    load_sellersprite_records,
)
from src.product_decision_layer import build_product_final_decisions
from scripts import sellersprite_reverse_asin_fetch as fetcher


def test_frontend_priority_keyword_prefers_ad_then_sellersprite_then_product_line(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0OWN00001",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": "2026-07-02",
                        "keywords": [
                            {"keyword": "seller opportunity term", "monthly_searches": "500", "purchases": "30"},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    keyword_config = tmp_path / "product_line_keywords.json"
    keyword_config.write_text(
        json.dumps(
            {
                "product_lines": [
                    {
                        "marketplace": "US",
                        "product_line": "TestLine",
                        "name_patterns": ["test product"],
                        "keyword_levels": {"核心词": ["configured core term"]},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    shared = SimpleNamespace(
        OUTPUT_DIR=tmp_path,
        KEYWORD_CONFIG_PATH=keyword_config,
        _to_float=lambda value: float(str(value or "0").replace(",", "") or 0),
        _product_line_hint=lambda product_name, sku, asin: "TestLine",
    )

    keyword, source = frontend_view._frontend_priority_keyword(
        shared,
        {"search_term_or_target": "paid exact term"},
        marketplace="US",
        product_name="Test Product",
        sku="SKU-1",
        asin="B0OWN00001",
        output_dir=tmp_path,
    )
    assert (keyword, source) == ("paid exact term", "广告词")

    keyword, source = frontend_view._frontend_priority_keyword(
        shared,
        {},
        marketplace="US",
        product_name="Test Product",
        sku="SKU-1",
        asin="B0OWN00001",
        output_dir=tmp_path,
    )
    assert (keyword, source) == ("seller opportunity term", "卖家精灵机会词")

    keyword, source = frontend_view._frontend_priority_keyword(
        shared,
        {},
        marketplace="US",
        product_name="Test Product",
        sku="SKU-1",
        asin="B0NOSELLER",
        output_dir=tmp_path,
    )
    assert (keyword, source) == ("configured core term", "产品线核心词")


def test_sellersprite_competitor_rows_dedupe_exclude_own_and_limit_three() -> None:
    rows = [
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B0OWN00001",
            "priority": "P0",
        }
    ]
    own_record = {
        "marketplace": "US",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
            "keywords": [{"keyword": "premium desk lamp"}],
            "competitors": [
                {"asin": "B0OWN00001", "title": "Own duplicate"},
                {"asin": "B0COMP0001", "title": "Competitor 1", "keyword": "premium desk lamp"},
                {"asin": "B0COMP0001", "title": "Competitor 1 duplicate", "keyword": "premium desk lamp"},
                {"asin": "B0COMP0002", "title": "Competitor 2", "keyword": "premium desk lamp"},
                {"asin": "B0COMP0003", "title": "Competitor 3", "keyword": "premium desk lamp"},
                {"asin": "B0COMP0004", "title": "Competitor 4", "keyword": "premium desk lamp"},
            ],
        }

    competitors = fetcher._competitor_rows(rows, seller_records={("US", "B0OWN00001"): own_record})

    assert [row["asin"] for row in competitors] == ["B0COMP0001", "B0COMP0002", "B0COMP0003"]


def test_sellersprite_own_reverse_record_can_generate_direct_competitor_pool() -> None:
    own_record = {
        "marketplace": "US",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}],
        "competitors": [
            {"asin": "B0OWN00001", "title": "Own"},
            {"asin": "B0COMP0001", "title": "Competitor One", "keyword": "premium desk lamp"},
            {"asin": "B0COMP0002", "title": "Competitor Two", "keyword": "premium desk lamp"},
            {"asin": "B0COMP0003", "title": "Competitor Three", "keyword": "premium desk lamp"},
            {"asin": "B0COMP0004", "title": "Competitor Four", "keyword": "premium desk lamp"},
        ],
    }
    seller_records = {
        ("US", "B0OWN00001"): own_record,
        ("US", "B0COMP0001"): {
            "marketplace": "US",
            "asin": "B0COMP0001",
            "source_role": "competitor",
            "keywords": [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}],
        },
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "US", "asin": "B0OWN00001", "frontend_competitors": [{"asin": "B0COMP0001"}]},
        own_record,
        seller_records,
    )

    assert pool["competitor_discovery_source"] == "sellersprite_direct"
    assert pool["competitor_pool_asins"] == "B0COMP0001、B0COMP0002、B0COMP0003"
    assert pool["competitor_pool_count"] == 3
    assert pool["competitor_pool_confidence"] in {"high", "medium"}
    assert pool["competitor_overlap_keywords"] == "premium desk lamp"


def test_parent_linked_competitor_reverse_seed_is_not_dropped() -> None:
    own_record = {
        "marketplace": "US",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "21 gallon cable ties"}],
    }
    competitor_record = {
        "marketplace": "US",
        "asin": "B0COMP0001",
        "product_name": "13 Gallon Cable Ties",
        "source_role": "competitor",
        "parent_asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "13 gallon cable ties", "monthly_searches": "5000", "purchases": "300"}],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "US", "asin": "B0OWN00001"},
        own_record,
        {("US", "B0OWN00001"): own_record, ("US", "B0COMP0001"): competitor_record},
    )

    assert pool["competitor_discovery_source"] == "sellersprite_reverse_seed"
    assert pool["competitor_pool_asins"] == "B0COMP0001"
    assert pool["competitor_pool_count"] == 1
    assert pool["competitor_pool_confidence"] == "medium"
    assert pool["competitor_overlap_keywords"] == ""
    assert pool["competitor_source_keywords"] == "13 gallon cable ties"


def test_one_overlap_candidate_is_reference_not_main_competitor() -> None:
    own_record = {
        "marketplace": "US",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "wood desk lamp"}, {"keyword": "kitchen board"}],
    }
    competitor_record = {
        "marketplace": "US",
        "asin": "B0COMP0001",
        "product_name": "Wood desk lamp",
        "source_role": "competitor",
        "parent_asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "wood desk lamp"}],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "US", "asin": "B0OWN00001"},
        own_record,
        {("US", "B0OWN00001"): own_record, ("US", "B0COMP0001"): competitor_record},
    )

    assert pool["competitor_pool_asins"] == "B0COMP0001"
    assert pool["main_competitor_count"] == 0
    assert pool["reference_competitor_asins"] == "B0COMP0001"


def test_two_overlap_reverse_candidate_becomes_main_competitor() -> None:
    own_record = {
        "marketplace": "US",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "wood desk lamp"}, {"keyword": "kitchen board"}],
    }
    competitor_record = {
        "marketplace": "US",
        "asin": "B0COMP0001",
        "product_name": "Wood kitchen desk lamp",
        "source_role": "competitor",
        "parent_asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "wood desk lamp"}, {"keyword": "kitchen board"}],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "US", "asin": "B0OWN00001"},
        own_record,
        {("US", "B0OWN00001"): own_record, ("US", "B0COMP0001"): competitor_record},
    )

    assert pool["main_competitor_asins"] == "B0COMP0001"
    assert pool["main_competitor_count"] == 1
    assert int(pool["competitor_comparability_score"]) > 0


def test_price_band_over_thirty_percent_demotes_candidate_to_reference() -> None:
    own_record = {
        "marketplace": "US",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "wood desk lamp"}, {"keyword": "kitchen board"}],
    }
    competitor_record = {
        "marketplace": "US",
        "asin": "B0COMP0001",
        "product_name": "Wood kitchen desk lamp",
        "source_role": "competitor",
        "parent_asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "wood desk lamp"}, {"keyword": "kitchen board"}],
    }

    pool = build_sellersprite_competitor_pool(
        {
            "marketplace": "US",
            "asin": "B0OWN00001",
            "frontend_price": "$10.00",
            "frontend_competitors": [{"asin": "B0COMP0001", "title": "Wood kitchen desk lamp", "price": "$20.00"}],
        },
        own_record,
        {("US", "B0OWN00001"): own_record, ("US", "B0COMP0001"): competitor_record},
    )

    assert pool["main_competitor_count"] == 0
    assert pool["reference_competitor_asins"] == "B0COMP0001"
    assert pool["competitor_price_band_status"] == "价格待确认"


def test_spec_mismatch_demotes_candidate_to_reference() -> None:
    own_record = {
        "marketplace": "US",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "20 gallon cable ties"}, {"keyword": "wire ties"}],
    }
    competitor_record = {
        "marketplace": "US",
        "asin": "B0COMP0001",
        "product_name": "13 gallon cable ties",
        "source_role": "competitor",
        "parent_asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "20 gallon cable ties"}, {"keyword": "wire ties"}, {"keyword": "13 gallon cable ties"}],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "US", "asin": "B0OWN00001", "product_name": "20 gallon cable ties"},
        own_record,
        {("US", "B0OWN00001"): own_record, ("US", "B0COMP0001"): competitor_record},
    )

    assert pool["main_competitor_count"] == 0
    assert pool["reference_competitor_asins"] == "B0COMP0001"
    assert pool["competitor_spec_match_status"] == "规格待确认"


def test_unrelated_water_flosser_candidates_are_rejected_for_board_products() -> None:
    own_record = {
        "marketplace": "UK",
        "asin": "B0FAKEUK01",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "wooden office desk lamp"}, {"keyword": "dimmer desk lamp"}],
    }
    competitor_record = {
        "marketplace": "UK",
        "asin": "B0FAKEUK02",
        "product_name": "|查流量来源|卖家精灵 Group Created with Sketch. SellerSprite",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "water flosser"}, {"keyword": "waterpik water flosser"}],
    }
    discovery_record = {
        "marketplace": "UK",
        "sku": "TEST-BOARD-SKU-01",
        "asin": "B0FAKEUK01",
        "competitor_discovery_status": "已抓取",
        "source_page": "reversing",
        "competitors": [
            {
                "competitor_asin": "B0FAKEUK02",
                "competitor_title": "|查流量来源|卖家精灵 Group Created with Sketch. SellerSprite",
                "competitor_source": "sellersprite_competitor_direct",
                "confidence": "high",
            }
        ],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "UK", "sku": "TEST-BOARD-SKU-01", "asin": "B0FAKEUK01"},
        own_record,
        {("UK", "B0FAKEUK01"): own_record, ("UK", "B0FAKEUK02"): competitor_record},
        competitor_discovery_records={("UK", "TEST-BOARD-SKU-01", "B0FAKEUK01"): discovery_record},
    )

    assert pool["competitor_pool_count"] == 0
    assert pool["competitor_pool_confidence"] == "unknown"
    assert pool["competitor_rejected_count"] == 1
    assert "页面壳文本" in pool["competitor_rejection_reasons"]


def test_socks_and_steam_cleaner_candidates_are_rejected_for_cable_ties() -> None:
    own_record = {
        "marketplace": "US",
        "asin": "B0FAKEUS01",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "21 gallon cable ties"}, {"keyword": "23 gallon cable ties"}],
    }
    seller_records = {
        ("US", "B0FAKEUS01"): own_record,
        (
            "US",
            "B0FAKEUS02",
        ): {
            "marketplace": "US",
            "asin": "B0FAKEUS02",
            "product_name": "Women Ankle Socks",
            "seller_sprite_check_status": "已抓取",
            "keywords": [{"keyword": "socks"}, {"keyword": "ankle socks"}],
        },
        (
            "US",
            "B0FAKEUS03",
        ): {
            "marketplace": "US",
            "asin": "B0FAKEUS03",
            "product_name": "Portable Steam Cleaner",
            "seller_sprite_check_status": "已抓取",
            "keywords": [{"keyword": "steam cleaner"}, {"keyword": "carpet cleaner"}],
        },
    }
    discovery_record = {
        "marketplace": "US",
        "sku": "TEST-CABLE-TIES-SKU-01",
        "asin": "B0FAKEUS01",
        "competitor_discovery_status": "已抓取",
        "source_page": "reversing",
        "competitors": [
            {"competitor_asin": "B0FAKEUS02", "competitor_title": "Women Ankle Socks", "competitor_source": "sellersprite_competitor_direct"},
            {"competitor_asin": "B0FAKEUS03", "competitor_title": "Portable Steam Cleaner", "competitor_source": "sellersprite_competitor_direct"},
        ],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "US", "sku": "TEST-CABLE-TIES-SKU-01", "asin": "B0FAKEUS01"},
        own_record,
        seller_records,
        competitor_discovery_records={("US", "TEST-CABLE-TIES-SKU-01", "B0FAKEUS01"): discovery_record},
    )

    assert pool["competitor_pool_count"] == 0
    assert pool["competitor_rejected_count"] == 2
    assert "无共同关键词" in pool["competitor_rejection_reasons"]


def test_airpods_candidate_is_rejected_for_tea_box() -> None:
    own_record = {
        "marketplace": "DE",
        "asin": "B0FAKEDE01",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "stationery box"}, {"keyword": "stationery aufbewahrung"}],
    }
    competitor_record = {
        "marketplace": "DE",
        "asin": "B0FAKEDE02",
        "product_name": "Bluetooth Kopfhoerer",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "airpods pro 3"}, {"keyword": "bluetooth kopfhörer"}, {"keyword": "ventilator"}],
    }
    discovery_record = {
        "marketplace": "DE",
        "sku": "TEST-NOTEBOOK-SKU-01",
        "asin": "B0FAKEDE01",
        "competitor_discovery_status": "已抓取",
        "source_page": "reversing",
        "competitors": [
            {"competitor_asin": "B0FAKEDE02", "competitor_title": "Bluetooth Kopfhoerer", "competitor_source": "sellersprite_competitor_direct"}
        ],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "DE", "sku": "TEST-NOTEBOOK-SKU-01", "asin": "B0FAKEDE01"},
        own_record,
        {("DE", "B0FAKEDE01"): own_record, ("DE", "B0FAKEDE02"): competitor_record},
        competitor_discovery_records={("DE", "TEST-NOTEBOOK-SKU-01", "B0FAKEDE01"): discovery_record},
    )

    assert pool["competitor_pool_count"] == 0
    assert pool["competitor_pool_status"] == "竞品证据不足"
    assert "B0FAKEDE02" not in pool["competitor_pool_asins"]


def test_sellersprite_frontend_summary_includes_ad_match_counts(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0TEST1234",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": "2026-07-01",
                        "captured_count": 2,
                        "keywords": [
                            {
                                "keyword": "wooden desk lamp with handle",
                                "monthly_searches": "2195",
                                "purchases": "67",
                                "ppc": "0.84",
                            },
                            {
                                "keyword": "small wooden desk lamp",
                                "monthly_searches": "12311",
                                "purchases": "791",
                                "ppc": "1.97",
                                "spr": "18",
                                "products": "15668",
                            },
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    search_rows = [
        {"marketplace": "US", "asin": "B0TEST1234", "search_term_or_target": "wooden desk lamp with handle"},
        {"marketplace": "US", "asin": "B0TEST1234", "search_term_or_target": "single wooden desk lamp with handle"},
        {"marketplace": "US", "asin": "B0TEST1234", "search_term_or_target": "plastic tray"},
    ]
    frontend_rows = [{"marketplace": "US", "asin": "B0TEST1234", "frontend_findings": "售价：$16.69"}]

    _, enriched_frontend, _ = enrich_report_view_rows(search_rows, frontend_rows, cache_path=cache_path)

    summary = enriched_frontend[0]
    assert summary["seller_sprite_check_status"] == "已抓取"
    assert summary["seller_sprite_keyword_count"] == 2
    assert summary["seller_sprite_ad_rows_count"] == 3
    assert summary["seller_sprite_ad_exact_match_count"] == 1
    assert summary["seller_sprite_ad_near_match_count"] == 1
    assert summary["seller_sprite_ad_no_match_count"] == 1
    assert summary["seller_sprite_high_competition_count"] == 1


def test_render_seller_sprite_summary_block_is_lightweight_and_visible() -> None:
    html = _render_seller_sprite_summary_block(
        {
            "seller_sprite_check_status": "已抓取",
            "seller_sprite_data_date": "2026-07-01",
            "seller_sprite_keyword_count": 20,
            "seller_sprite_ad_rows_count": 43,
            "seller_sprite_ad_exact_match_count": 0,
            "seller_sprite_ad_near_match_count": 13,
            "seller_sprite_ad_no_match_count": 30,
            "seller_sprite_opportunity_count": 0,
            "seller_sprite_high_competition_count": 1,
            "seller_sprite_risk_summary": "高竞争：small wooden desk lamp；PPC中位数 0.84",
        }
    )

    assert "卖家精灵反查" in html
    assert "抓词：20" in html
    assert "广告词：43" in html
    assert "近似：13" in html
    assert "未命中：30" in html
    assert "高竞争：1" in html


def test_render_seller_sprite_summary_block_classifies_competitor_keywords() -> None:
    html = _render_seller_sprite_summary_block(
        {
            "product_name": "Demo cable ties 100 count",
            "search_term_or_target": "20 gallon cable holder",
            "seller_sprite_check_status": "已抓取",
            "seller_sprite_data_date": "2026-07-02",
            "seller_sprite_keyword_count": 4,
            "seller_sprite_opportunity_count": 1,
            "seller_sprite_high_competition_count": 0,
            "seller_sprite_top_opportunities": "21 gallon cable ties",
            "own_sellersprite_keywords": "21 gallon cable ties、23 gallon cable ties",
            "own_missing_competitor_keywords": "cable ties、wire ties、cable ties 13 gallon、small cable ties、amazon basics、amazon",
            "competitor_keyword_pressure": "高",
            "frontend_competitiveness": "前台弱",
            "product_ad_boundary": "前台弱且竞品词压力高，停止新增词，优先处理高花费 0 单词。",
        }
    )

    assert "竞品词判断" in html
    assert "当前前台弱，不建议新增" in html
    assert "修好后再测：21 gallon cable ties" in html
    assert "泛词控费：cable ties、wire ties" in html
    assert "错配或品牌风险：cable ties 13 gallon、small cable ties、amazon basics、amazon" in html


def test_product_seller_sprite_summary_does_not_duplicate_pool_count() -> None:
    html = _seller_sprite_product_summary(
        {
            "frontend_status": "已自动检查",
            "seller_sprite_check_status": "已抓取",
            "competitor_discovery_status": "已抓取",
            "competitor_pool_status": "有效 3/3",
            "competitor_pool_count": 3,
            "competitor_pool_confidence": "medium",
            "competitor_source_keywords": "cable ties、wire ties",
            "competitor_sellersprite_status": "已抓 3 个",
            "amazon_search_validation_status": "未验证",
            "product_level_conclusion": "暂停扩张",
            "competitor_keyword_pressure": "高",
        }
    )

    assert "竞品池 有效 3/3" in html
    assert "有效3/3" not in html
    assert "来源词 cable ties、wire ties" in html


def test_product_seller_sprite_summary_shows_trend_evidence() -> None:
    html = _seller_sprite_product_summary(
        {
            "frontend_status": "已自动检查",
            "seller_sprite_check_status": "已抓取",
            "sellersprite_today_status": "今日已抓",
            "sellersprite_history_days": 3,
            "sellersprite_trend_status": "3天趋势可用",
            "sellersprite_persistent_keywords": "stable demand、steady demand",
            "sellersprite_ppc_up_keywords": "stable demand",
            "competitor_stable_asins": "B0COMP0001、B0COMP0002",
            "competitor_pressure_trend": "持续高",
            "product_level_conclusion": "可测试，不放量",
            "competitor_keyword_pressure": "高",
        }
    )

    assert "卖家精灵状态 今日已抓｜3天" in html
    assert "趋势 3天趋势可用" in html
    assert "连续词 stable demand、steady demand" in html
    assert "稳定竞品 B0COMP0001、B0COMP0002" in html
    assert "PPC上升 stable demand" in html


def test_product_seller_sprite_summary_hides_zero_pool_count_when_insufficient() -> None:
    html = _seller_sprite_product_summary(
        {
            "frontend_status": "已自动检查",
            "seller_sprite_check_status": "已抓取",
            "competitor_discovery_status": "已抓取",
            "competitor_pool_status": "竞品证据不足",
            "competitor_pool_count": 0,
            "competitor_rejected_count": 3,
            "competitor_rejection_reasons": "标题为空或页面壳文本 3",
            "competitor_sellersprite_status": "待补",
            "amazon_search_validation_status": "未验证",
            "product_level_conclusion": "只防守",
            "competitor_keyword_pressure": "无缓存",
        }
    )

    assert "竞品池 竞品证据不足" in html
    assert "有效0/3" not in html
    assert "缺口词 待补" in html


def test_frontend_coverage_strip_explains_zero_search_and_scale_counts() -> None:
    html = _render_frontend_coverage_strip(
        {
            "frontend_queue_total": 7,
            "frontend_product_page_success_label": "7/7",
            "frontend_product_page_success_count": 7,
            "frontend_own_sellersprite_label": "7/7",
            "frontend_own_sellersprite_count": 7,
            "frontend_competitor_discovery_label": "7/7",
            "frontend_competitor_discovery_count": 7,
            "frontend_competitor_pool_label": "1/7",
            "frontend_competitor_pool_count": 1,
            "frontend_competitor_sellersprite_label": "1/7，3 ASIN",
            "frontend_competitor_sellersprite_count": 1,
            "frontend_amazon_search_validation_label": "0/7",
            "frontend_amazon_search_validation_count": 0,
            "frontend_scalable_strong_label": "0/7",
            "frontend_scalable_strong_count": 0,
            "frontend_weak_defensive_label": "7/7",
            "frontend_weak_defensive_count": 7,
            "frontend_insufficient_label": "7/7",
            "frontend_insufficient_count": 7,
        }
    )

    assert "Amazon 搜索页辅助验证" in html
    assert "未跑" in html
    assert "0/7，只在重点词补证" in html
    assert "达到放量准入" in html
    assert "暂无" in html
    assert "0/7，不建议放量" in html


def test_render_seller_sprite_summary_block_hides_no_cache_rows() -> None:
    assert (
        _render_seller_sprite_summary_block(
            {
                "seller_sprite_check_status": "无缓存",
                "seller_sprite_keyword_count": 0,
                "seller_sprite_ad_rows_count": 43,
                "seller_sprite_ad_no_cache_count": 43,
            }
        )
        == ""
    )


def test_no_cache_summary_is_not_appended_to_frontend_findings() -> None:
    findings = _append_summary_to_findings(
        {"frontend_findings": "售价：$10.99"},
        {
            "seller_sprite_check_status": "无缓存",
            "seller_sprite_keyword_count": 0,
            "seller_sprite_opportunity_count": 0,
            "seller_sprite_high_competition_count": 0,
        },
    )

    assert findings == "售价：$10.99"


def test_sellersprite_fetch_for_rows_skips_cached_products(monkeypatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0CACHED01",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": date.today().isoformat(),
                        "keywords": [{"keyword": "cached keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_fetch(row, **kwargs):
        calls.append(row)
        return {
            "marketplace": row["marketplace"],
            "asin": row["asin"],
            "seller_sprite_check_status": "已抓取",
            "data_date": "2026-07-01",
            "keywords": [{"keyword": "fresh keyword"}],
        }

    monkeypatch.setattr(fetcher, "SELLERSPRITE_CACHE_PATH", cache_path)
    monkeypatch.setattr(fetcher, "fetch_reverse_asin_record", fake_fetch)

    records = fetcher.fetch_for_rows(
        [
            {"marketplace": "US", "asin": "B0CACHED01"},
            {"marketplace": "US", "asin": "B0MISSING1"},
        ],
        profile=tmp_path / "profile",
        target_count=20,
        visible=False,
    )

    assert [row["asin"] for row in calls] == ["B0MISSING1"]
    assert [record["asin"] for record in records] == ["B0MISSING1"]


def test_sellersprite_fetch_for_rows_refetches_stale_own_cache(monkeypatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0STALEOWN",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": yesterday,
                        "keywords": [{"keyword": "old keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []
    history_calls: list[dict] = []

    def fake_fetch(row, **kwargs):
        calls.append(row)
        return {
            "marketplace": row["marketplace"],
            "asin": row["asin"],
            "seller_sprite_check_status": "已抓取",
            "data_date": date.today().isoformat(),
            "keywords": [{"keyword": "fresh keyword"}],
        }

    monkeypatch.setattr(fetcher, "SELLERSPRITE_CACHE_PATH", cache_path)
    monkeypatch.setattr(fetcher, "fetch_reverse_asin_record", fake_fetch)
    monkeypatch.setattr(fetcher, "upsert_sellersprite_history", lambda records, **kwargs: history_calls.append({"records": list(records), **kwargs}))

    records = fetcher.fetch_for_rows(
        [{"marketplace": "US", "asin": "B0STALEOWN"}],
        profile=tmp_path / "profile",
        visible=False,
    )

    assert [row["asin"] for row in calls] == ["B0STALEOWN"]
    assert records[0]["keywords"][0]["keyword"] == "fresh keyword"
    assert history_calls[-1]["records"][0]["asin"] == "B0STALEOWN"


def test_sellersprite_competitor_cache_reuses_seven_days_and_refetches_stale(monkeypatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    fresh_day = (date.today() - timedelta(days=3)).isoformat()
    stale_day = (date.today() - timedelta(days=10)).isoformat()
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0FRESH001",
                        "source_role": "competitor",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": fresh_day,
                        "keywords": [{"keyword": "fresh competitor keyword"}],
                    },
                    {
                        "marketplace": "US",
                        "asin": "B0STALE001",
                        "source_role": "competitor",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": stale_day,
                        "keywords": [{"keyword": "stale competitor keyword"}],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_fetch(row, **kwargs):
        calls.append(row)
        return {
            "marketplace": row["marketplace"],
            "asin": row["asin"],
            "source_role": row.get("source_role") or "competitor",
            "seller_sprite_check_status": "已抓取",
            "data_date": "2026-07-02",
            "keywords": [{"keyword": "freshened keyword"}],
        }

    monkeypatch.setattr(fetcher, "SELLERSPRITE_CACHE_PATH", cache_path)
    monkeypatch.setattr(fetcher, "fetch_reverse_asin_record", fake_fetch)

    records = fetcher.fetch_for_rows(
        [
            {"marketplace": "US", "asin": "B0FRESH001", "source_role": "competitor"},
            {"marketplace": "US", "asin": "B0STALE001", "source_role": "competitor"},
        ],
        profile=tmp_path / "profile",
        visible=False,
        competitor_cache_days=7,
    )

    assert [row["asin"] for row in calls] == ["B0STALE001"]
    assert [record["asin"] for record in records] == ["B0STALE001"]


def test_sellersprite_p0_competitor_cache_refetches_daily(monkeypatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0P0COMP01",
                        "source_role": "competitor",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": yesterday,
                        "keywords": [{"keyword": "cached competitor keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_fetch(row, **kwargs):
        calls.append(row)
        return {
            "marketplace": row["marketplace"],
            "asin": row["asin"],
            "source_role": "competitor",
            "seller_sprite_check_status": "已抓取",
            "data_date": date.today().isoformat(),
            "keywords": [{"keyword": "fresh p0 competitor keyword"}],
        }

    monkeypatch.setattr(fetcher, "SELLERSPRITE_CACHE_PATH", cache_path)
    monkeypatch.setattr(fetcher, "fetch_reverse_asin_record", fake_fetch)
    monkeypatch.setattr(fetcher, "upsert_sellersprite_history", lambda records, **kwargs: None)

    fetcher.fetch_for_rows(
        [{"marketplace": "US", "asin": "B0P0COMP01", "source_role": "competitor", "priority": "P0"}],
        profile=tmp_path / "profile",
        visible=False,
        competitor_cache_days=7,
    )

    assert [row["asin"] for row in calls] == ["B0P0COMP01"]


def test_sellersprite_cache_does_not_treat_failures_as_cached(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "UK",
                        "asin": "B0FAILED01",
                        "seller_sprite_check_status": "抓取失败",
                        "data_date": "2026-07-01",
                        "keywords": [],
                        "last_error": "missing reverse asin button",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert load_sellersprite_records(cache_path) == {}


def test_sellersprite_records_choose_latest_checked_success_on_same_day(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0CHECKED1",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": "2026-07-03",
                        "checked_at": "2026-07-03T09:00:00",
                        "keywords": [{"keyword": "old keyword"}],
                    },
                    {
                        "marketplace": "US",
                        "asin": "B0CHECKED1",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": "2026-07-03",
                        "checked_at": "2026-07-03T16:00:00",
                        "keywords": [{"keyword": "fresh keyword"}, {"keyword": "second keyword"}],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    records = load_sellersprite_records(cache_path)

    assert records[("US", "B0CHECKED1")]["checked_at"] == "2026-07-03T16:00:00"
    assert records[("US", "B0CHECKED1")]["keywords"][0]["keyword"] == "fresh keyword"


def test_sellersprite_main_soft_passes_when_cached_products_cover_primary_queue(monkeypatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    latest_path = tmp_path / "latest_analysis.json"
    cache_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0OWN00001",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": "2026-07-01",
                        "keywords": [{"keyword": "cached own keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    latest_path.write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "US",
                                    "asin": "B0OWN00001",
                                    "priority": "P0",
                                    "frontend_competitor_count": 2,
                                    "frontend_competitors": [
                                        {"asin": "B0COMP0001", "sponsored": False},
                                    ],
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_fetch(row, **kwargs):
        return {
            "marketplace": row["marketplace"],
            "asin": row["asin"],
            "seller_sprite_check_status": "抓取失败",
            "data_date": "2026-07-01",
            "keywords": [],
            "last_error": "reverse asin hidden",
        }

    monkeypatch.setattr(fetcher, "SELLERSPRITE_CACHE_PATH", cache_path)
    monkeypatch.setattr(fetcher, "LATEST_ANALYSIS", latest_path)
    monkeypatch.setattr(fetcher, "fetch_reverse_asin_record", fake_fetch)
    monkeypatch.setattr(
        fetcher.sys,
        "argv",
        ["sellersprite_reverse_asin_fetch.py", "--include-competitors", "--target-count", "20"],
    )

    assert fetcher.main() == 0


def _write_fusion_cache(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps({"items": records}, ensure_ascii=False), encoding="utf-8")


def _record(marketplace: str, asin: str, keywords: list[dict], *, data_date: str = "2026-07-01") -> dict:
    return {
        "marketplace": marketplace,
        "asin": asin,
        "seller_sprite_check_status": "已抓取",
        "data_date": data_date,
        "captured_count": len(keywords),
        "keywords": keywords,
    }


def _analysis_payload(marketplace: str, sku: str, asin: str) -> dict:
    product_row = {
        "marketplace": marketplace,
        "sku": sku,
        "asin": asin,
        "product_name": "Test Product",
        "ad_clicks": 20,
        "ad_spend": 12,
        "ad_orders": 0,
        "total_orders": 0,
        "target_acos": "30%",
        "profit_before_ads_per_unit": 5,
    }
    return {
        "target_marketplace": marketplace,
        "history_days": 14,
        "summary": {"ads_row_count": 20, "erp_row_count": 20},
        "data_quality": {"validation_messages": []},
        "product_window_metrics": {"14d": [product_row], "7d": [product_row]},
    }


def _frontend_base(*, auto_code: str = "FRONTEND_OK", auto_label: str = "前台可承接") -> dict:
    return {
        "marketplace": "US",
        "sku": "SKU-1",
        "asin": "B0OWN00001",
        "product_name": "Test Product",
        "priority": "P0",
        "frontend_check_status": "已自动检查",
        "frontend_search_status": "已自动检查",
        "frontend_auto_conclusion": auto_code,
        "frontend_auto_conclusion_label": auto_label,
        "frontend_evidence_quality_score": "82",
        "frontend_evidence_tier": "强诊断可用",
        "competitor_comparability": "high",
        "comparable_competitor_count": 2,
        "frontend_location_scope": "exact",
        "frontend_location_verified": True,
        "frontend_location_exact": True,
        "frontend_competitors": [
            {"asin": "B0COMP0001", "title": "Competitor One", "sponsored": False},
            {"asin": "B0COMP0002", "title": "Competitor Two", "sponsored": False},
        ],
    }


def test_frontend_weak_and_competitor_keywords_force_defense_or_pause(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    _write_fusion_cache(
        cache_path,
        [
            {
                **_record("US", "B0OWN00001", [{"keyword": "own desk lamp", "monthly_searches": "300"}]),
                "competitors": [
                    {"asin": "B0COMP0001", "title": "Competitor One"},
                    {"asin": "B0COMP0002", "title": "Competitor Two"},
                ],
            },
            _record("US", "B0COMP0001", [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}]),
            _record("US", "B0COMP0002", [{"keyword": "premium desk lamp", "monthly_searches": "4500", "purchases": "240"}]),
        ],
    )
    search_rows = [
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B0OWN00001",
            "search_term_or_target": "premium desk lamp",
            "suggested_action": "加价5%-10%",
            "copy_action_line": "建议加价 5%-10%",
            "clicks": 10,
            "spend": "$6.00",
            "orders": 0,
        }
    ]
    frontend_rows = [_frontend_base(auto_code="FRONTEND_WEAK", auto_label="明确前台劣势")]

    enriched_search, enriched_frontend, _ = enrich_report_view_rows(search_rows, frontend_rows, cache_path=cache_path)

    assert enriched_frontend[0]["product_level_conclusion"] == "暂停扩张"
    assert enriched_frontend[0]["competitor_frontend_status"] == "部分，已读 2 个"
    assert enriched_frontend[0]["competitor_frontend_asins"] == "B0COMP0001、B0COMP0002"
    assert enriched_frontend[0]["competitor_sellersprite_status"] == "已抓 2 个"
    assert enriched_frontend[0]["competitor_sellersprite_asin_count"] == 2
    assert enriched_frontend[0]["competitor_sellersprite_keyword_count"] == 2
    decisions = build_product_final_decisions(
        _analysis_payload("US", "SKU-1", "B0OWN00001"),
        search_rows=enriched_search,
        frontend_rows=enriched_frontend,
    )
    blocked = set(decisions[0]["today_blocked_actions"])
    assert {"bid_up", "budget_up", "broad_scale", "create_exact_low_budget"} <= blocked


def test_frontend_ok_and_competitor_shared_terms_are_small_budget_only(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    today = date.today().isoformat()
    own_keywords = [
        {"keyword": "own board", "monthly_searches": "300", "ppc": "0.80", "traffic_share": "8%"},
        {"keyword": "kitchen desk lamp", "monthly_searches": "900", "ppc": "0.90", "traffic_share": "7%"},
        {"keyword": "wood desk lamp", "monthly_searches": "700", "ppc": "0.70", "traffic_share": "6%"},
    ]
    competitor_keywords = [
        {"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300", "ppc": "1.10", "traffic_share": "12%"},
        {"keyword": "kitchen desk lamp", "monthly_searches": "4500", "purchases": "240", "ppc": "1.00", "traffic_share": "11%"},
        {"keyword": "wood desk lamp", "monthly_searches": "3500", "purchases": "180", "ppc": "0.95", "traffic_share": "9%"},
    ]
    _write_fusion_cache(
        cache_path,
        [
            {
                **_record("US", "B0OWN00001", own_keywords, data_date=today),
                "competitors": [
                    {"asin": "B0COMP0001", "title": "Competitor One", "keyword": "kitchen desk lamp"},
                    {"asin": "B0COMP0002", "title": "Competitor Two", "keyword": "wood desk lamp"},
                    {"asin": "B0COMP0003", "title": "Competitor Three", "keyword": "premium desk lamp"},
                ],
            },
            _record("US", "B0COMP0001", competitor_keywords, data_date=today),
            _record("US", "B0COMP0002", competitor_keywords, data_date=today),
            _record("US", "B0COMP0003", competitor_keywords, data_date=today),
        ],
    )

    frontend = _frontend_base()
    frontend.update(
        {
            "frontend_price": "$19.99",
            "frontend_rating": "4.6",
            "frontend_reviews": "1234",
            "frontend_buy_box": "已识别",
            "frontend_coupon": "5%",
            "frontend_delivery": "Prime",
            "comparable_competitor_count": 3,
            "frontend_competitors": [
                {"asin": "B0COMP0001", "title": "Competitor One", "sponsored": False},
                {"asin": "B0COMP0002", "title": "Competitor Two", "sponsored": False},
                {"asin": "B0COMP0003", "title": "Competitor Three", "sponsored": False},
            ],
        }
    )

    enriched_search, enriched_frontend, _ = enrich_report_view_rows([], [frontend], cache_path=cache_path)

    assert enriched_search == []
    assert enriched_frontend[0]["product_level_conclusion"] == "可测试，不放量"
    assert "premium desk lamp" in enriched_frontend[0]["own_missing_competitor_keywords"]
    assert enriched_frontend[0]["competitor_keyword_pressure"] == "高"
    assert enriched_frontend[0]["market_survey_decision_evidence_tier"] == "usable"
    assert enriched_frontend[0]["scalable_evidence_status"] == "可小预算测试"
    decisions = build_product_final_decisions(
        _analysis_payload("US", "SKU-1", "B0OWN00001"),
        frontend_rows=enriched_frontend,
    )
    allowed = set(decisions[0]["today_allowed_actions"])
    blocked = set(decisions[0]["today_blocked_actions"])
    assert "create_exact_low_budget" in allowed
    assert {"budget_up", "broad_scale"} <= blocked


def test_full_main_competitor_evidence_allows_cautious_scale(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    today = date.today().isoformat()
    own_keywords = [
        {"keyword": "20 gallon cable ties", "monthly_searches": "5000", "purchases": "300", "ppc": "1.00", "traffic_share": "12%"},
        {"keyword": "wire ties", "monthly_searches": "4000", "purchases": "250", "ppc": "0.90", "traffic_share": "10%"},
        {"keyword": "cable ties 100 count", "monthly_searches": "3000", "purchases": "180", "ppc": "0.85", "traffic_share": "8%"},
    ]
    competitor_keywords = [
        {"keyword": "20 gallon cable ties", "monthly_searches": "5200", "purchases": "320", "ppc": "1.05", "traffic_share": "12%"},
        {"keyword": "wire ties", "monthly_searches": "4100", "purchases": "260", "ppc": "0.95", "traffic_share": "10%"},
        {"keyword": "cable ties 100 count", "monthly_searches": "3100", "purchases": "190", "ppc": "0.90", "traffic_share": "8%"},
    ]
    _write_fusion_cache(
        cache_path,
        [
            {
                **_record("US", "B0OWN00001", own_keywords, data_date=today),
                "competitors": [
                    {"asin": "B0COMP0001", "title": "20 gallon cable ties 100 count", "keyword": "20 gallon cable ties"},
                    {"asin": "B0COMP0002", "title": "20 gallon cable ties drawstring", "keyword": "wire ties"},
                    {"asin": "B0COMP0003", "title": "20 gallon cable ties 100 pack", "keyword": "cable ties 100 count"},
                ],
            },
            _record("US", "B0COMP0001", competitor_keywords, data_date=today),
            _record("US", "B0COMP0002", competitor_keywords, data_date=today),
            _record("US", "B0COMP0003", competitor_keywords, data_date=today),
        ],
    )
    frontend = _frontend_base()
    frontend.update(
        {
            "product_name": "20 gallon cable ties",
            "frontend_price": "$10.99",
            "frontend_rating": "4.6",
            "frontend_reviews": "120",
            "frontend_buy_box": "识别到购买按钮",
            "frontend_coupon": "5%",
            "frontend_delivery": "Prime",
            "frontend_competitors": [
                {"asin": "B0COMP0001", "title": "20 gallon cable ties 100 count", "price": "$11.49", "rating": "4.5", "reviews": "240", "sponsored": False},
                {"asin": "B0COMP0002", "title": "20 gallon cable ties drawstring", "price": "$10.49", "rating": "4.4", "reviews": "220", "sponsored": False},
                {"asin": "B0COMP0003", "title": "20 gallon cable ties 100 pack", "price": "$10.79", "rating": "4.5", "reviews": "180", "sponsored": False},
            ],
        }
    )
    search_rows = [
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B0OWN00001",
            "search_term_or_target": "20 gallon cable ties",
            "clicks": 20,
            "spend": "$12.00",
            "orders": 2,
        }
    ]

    enriched_search, enriched_frontend, _ = enrich_report_view_rows(search_rows, [frontend], cache_path=cache_path)

    row = enriched_frontend[0]
    assert row["main_competitor_count"] >= 2
    assert row["scalable_evidence_status"] == "可谨慎放量"
    assert row["product_level_conclusion"] == "可谨慎放量"
    decisions = build_product_final_decisions(
        {
            **_analysis_payload("US", "SKU-1", "B0OWN00001"),
            "product_window_metrics": {
                "14d": [{**_analysis_payload("US", "SKU-1", "B0OWN00001")["product_window_metrics"]["14d"][0], "ad_orders": 2, "acos": "20%", "target_acos": "30%"}],
                "7d": [{**_analysis_payload("US", "SKU-1", "B0OWN00001")["product_window_metrics"]["7d"][0], "ad_orders": 1}],
            },
        },
        search_rows=enriched_search,
        frontend_rows=enriched_frontend,
    )
    assert "bid_up" in decisions[0]["today_allowed_actions"]
    assert decisions[0]["scalable_evidence_status"] == "可谨慎放量"


def test_low_inventory_blocks_cautious_scale_even_with_main_competitors(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    today = date.today().isoformat()
    keywords = [
        {"keyword": "20 gallon cable ties", "monthly_searches": "5000", "purchases": "300", "ppc": "1.00", "traffic_share": "12%"},
        {"keyword": "wire ties", "monthly_searches": "4000", "purchases": "250", "ppc": "0.90", "traffic_share": "10%"},
    ]
    _write_fusion_cache(
        cache_path,
        [
            {
                **_record("US", "B0OWN00001", keywords, data_date=today),
                "competitors": [
                    {"asin": "B0COMP0001", "title": "20 gallon cable ties 100 count", "keyword": "20 gallon cable ties"},
                    {"asin": "B0COMP0002", "title": "20 gallon cable ties drawstring", "keyword": "wire ties"},
                ],
            },
            _record("US", "B0COMP0001", keywords, data_date=today),
            _record("US", "B0COMP0002", keywords, data_date=today),
        ],
    )
    frontend = _frontend_base()
    frontend.update(
        {
            "product_name": "20 gallon cable ties",
            "frontend_price": "$10.99",
            "frontend_rating": "4.6",
            "frontend_reviews": "120",
            "frontend_buy_box": "识别到购买按钮",
            "frontend_coupon": "5%",
            "frontend_delivery": "Prime",
            "frontend_competitors": [
                {"asin": "B0COMP0001", "title": "20 gallon cable ties 100 count", "price": "$11.49", "rating": "4.5", "reviews": "240", "sponsored": False},
                {"asin": "B0COMP0002", "title": "20 gallon cable ties drawstring", "price": "$10.49", "rating": "4.4", "reviews": "220", "sponsored": False},
            ],
        }
    )
    search_rows = [{"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "search_term_or_target": "20 gallon cable ties", "orders": 2}]
    enriched_search, enriched_frontend, _ = enrich_report_view_rows(search_rows, [frontend], cache_path=cache_path)

    decisions = build_product_final_decisions(
        _analysis_payload("US", "SKU-1", "B0OWN00001"),
        search_rows=enriched_search,
        frontend_rows=enriched_frontend,
        inventory_rows=[{"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "stock_risk_level": "LOW_STOCK", "stock_risk_reason": "低库存"}],
    )

    assert decisions[0]["scalable_evidence_status"] == "只能控费止损"
    assert "库存不支持放量" in decisions[0]["scalable_blockers"]
    assert "bid_up" in decisions[0]["today_blocked_actions"]


def test_amazon_search_failure_does_not_remove_sellersprite_competitor_pool(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    _write_fusion_cache(
        cache_path,
        [
            {
                **_record(
                    "US",
                    "B0OWN00001",
                    [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}],
                ),
                "competitors": [{"asin": "B0COMP0001", "title": "Competitor One", "keyword": "premium desk lamp"}],
            },
            _record(
                "US",
                "B0COMP0001",
                [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}],
            ),
        ],
    )
    frontend = _frontend_base()
    frontend["frontend_search_status"] = "读取失败"
    frontend["frontend_competitors"] = []

    _, enriched_frontend, _ = enrich_report_view_rows([], [frontend], cache_path=cache_path)

    row = enriched_frontend[0]
    assert row["competitor_pool_status"] == "有效 1/3"
    assert row["competitor_pool_asins"] == "B0COMP0001"
    assert row["competitor_sellersprite_status"] == "已抓 1 个"
    assert row["amazon_search_validation_status"] == "失败"


def test_amazon_search_seed_counts_as_search_validation_without_frontend_search_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    discovery_path = tmp_path / "sellersprite_competitor_discovery_results.json"
    _write_fusion_cache(
        cache_path,
        [
            _record(
                "US",
                "B0OWN00001",
                [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}],
            ),
            _record(
                "US",
                "B0COMP0001",
                [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}],
            ),
        ],
    )
    discovery_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "sku": "SKU-1",
                        "asin": "B0OWN00001",
                        "competitor_discovery_status": "已抓取",
                        "source_page": "reversing",
                        "checked_at": "2026-07-02T10:00:00",
                        "data_date": "2026-07-02",
                        "competitors": [
                            {
                                "competitor_asin": "B0COMP0001",
                                "competitor_title": "Competitor One",
                                "competitor_source": "sellersprite_competitor_direct",
                                "source_page": "reversing",
                                "confidence": "high",
                            }
                        ],
                    },
                    {
                        "marketplace": "US",
                        "sku": "SKU-1",
                        "asin": "B0OWN00001",
                        "competitor_discovery_status": "已抓取",
                        "source_page": "amazon_search_seed",
                        "checked_at": "2026-07-02T11:00:00",
                        "data_date": "2026-07-02",
                        "competitors": [
                            {
                                "competitor_asin": "B0COMP0001",
                                "competitor_title": "Competitor One",
                                "competitor_source": "amazon_search_visible",
                                "source_page": "amazon_search_seed",
                                "source_keyword": "premium desk lamp",
                                "confidence": "medium",
                            }
                        ],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    frontend = _frontend_base()
    frontend["frontend_search_status"] = "待前台检查"
    frontend["frontend_competitors"] = []

    _, enriched_frontend, _ = enrich_report_view_rows(
        [],
        [frontend],
        cache_path=cache_path,
        competitor_discovery_cache_path=discovery_path,
    )

    row = enriched_frontend[0]
    assert row["competitor_discovery_source_page"] == "reversing"
    assert row["competitor_pool_status"] == "有效 1/3"
    assert row["amazon_search_validation_status"] == "已验证"
    assert row["amazon_search_visible_competitors"] == "B0COMP0001"


def test_amazon_search_seed_fills_pool_when_direct_candidates_are_shell_text() -> None:
    own_record = {
        "marketplace": "UK",
        "asin": "B0OWN00001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "metal desk mat"}, {"keyword": "desk mat"}],
    }
    competitor_record = {
        "marketplace": "UK",
        "asin": "B0COMP0001",
        "seller_sprite_check_status": "已抓取",
        "keywords": [{"keyword": "desk mat", "monthly_searches": "5000", "purchases": "300"}],
    }
    discovery_record = {
        "marketplace": "UK",
        "sku": "SKU-1",
        "asin": "B0OWN00001",
        "competitor_discovery_status": "已抓取",
        "source_page": "reversing",
        "competitors": [
            {
                "competitor_asin": "B0SHELL001",
                "competitor_title": "|查流量来源|卖家精灵 SellerSprite",
                "competitor_source": "sellersprite_competitor_direct",
                "confidence": "high",
            }
        ],
        "amazon_search_seed_competitors": [
            {
                "competitor_asin": "B0COMP0001",
                "competitor_title": "Metal desk mat for hot dishes",
                "competitor_source": "amazon_search_visible",
                "source_page": "amazon_search_seed",
                "source_keyword": "metal desk mat",
                "confidence": "medium",
            }
        ],
    }

    pool = build_sellersprite_competitor_pool(
        {"marketplace": "UK", "sku": "SKU-1", "asin": "B0OWN00001"},
        own_record,
        {("UK", "B0OWN00001"): own_record, ("UK", "B0COMP0001"): competitor_record},
        competitor_discovery_records={("UK", "SKU-1", "B0OWN00001"): discovery_record},
    )

    assert pool["competitor_pool_status"] == "有效 1/3"
    assert pool["competitor_pool_asins"] == "B0COMP0001"
    assert pool["competitor_rejected_count"] == 1
    assert "页面壳文本" in pool["competitor_rejection_reasons"]
    assert pool["amazon_search_visible_competitors"] == "B0COMP0001"


def test_sellersprite_competitor_discovery_failure_degrades_to_insufficient_evidence(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    _write_fusion_cache(
        cache_path,
        [
            {
                **_record(
                    "US",
                    "B0OWN00001",
                    [{"keyword": "premium desk lamp", "monthly_searches": "5000", "purchases": "300"}],
                ),
                "competitors": [{"asin": "B0COMP0001", "title": "Competitor One", "keyword": "premium desk lamp"}],
            }
        ],
    )

    frontend = _frontend_base()
    frontend["frontend_competitors"] = []

    _, enriched_frontend, _ = enrich_report_view_rows([], [frontend], cache_path=cache_path)

    row = enriched_frontend[0]
    assert row["competitor_pool_count"] == 1
    assert row["competitor_sellersprite_status"] == "竞品反查待补"
    assert row["product_level_conclusion"] != "可放量"


def test_ad_terms_with_clicks_zero_orders_and_no_own_sellersprite_evidence_are_controlled(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    _write_fusion_cache(
        cache_path,
        [_record("US", "B0OWN00001", [{"keyword": "own board", "monthly_searches": "300"}])],
    )
    search_rows = [
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B0OWN00001",
            "search_term_or_target": "irrelevant plastic tray",
            "clicks": 9,
            "spend": "$7.20",
            "orders": 0,
        }
    ]

    enriched_search, enriched_frontend, detail_rows = enrich_report_view_rows(
        search_rows,
        [_frontend_base()],
        cache_path=cache_path,
    )

    assert enriched_search[0]["seller_sprite_ads_fusion_label"] == "无反查匹配需控费"
    assert "优先降竞价或否定精准" in enriched_search[0]["seller_sprite_fusion_reason"]
    assert "irrelevant plastic tray" in enriched_frontend[0]["own_ad_terms_not_in_sellersprite"]
    assert enriched_frontend[0]["competitor_sellersprite_status"] == "待补"
    assert detail_rows[0]["seller_sprite_match_status"] == "未命中"


def test_product_problem_priority_blocks_growth_actions(tmp_path: Path) -> None:
    cache_path = tmp_path / "sellersprite_reverse_asin_results.json"
    _write_fusion_cache(
        cache_path,
        [_record("US", "B0OWN00001", [{"keyword": "own board", "monthly_searches": "300"}])],
    )
    frontend = _frontend_base()
    frontend["frontend_buy_box"] = "无 Buy Box"

    enriched_search, enriched_frontend, _ = enrich_report_view_rows(
        [
            {
                "marketplace": "US",
                "sku": "SKU-1",
                "asin": "B0OWN00001",
                "search_term_or_target": "own board",
                "suggested_action": "加价5%-10%",
                "copy_action_line": "建议加价 5%-10%",
                "clicks": 8,
                "orders": 0,
            }
        ],
        [frontend],
        cache_path=cache_path,
    )

    assert enriched_frontend[0]["product_level_conclusion"] == "产品问题优先"
    decisions = build_product_final_decisions(
        _analysis_payload("US", "SKU-1", "B0OWN00001"),
        search_rows=enriched_search,
        frontend_rows=enriched_frontend,
    )
    blocked = set(decisions[0]["today_blocked_actions"])
    assert {"bid_up", "budget_up", "broad_scale", "create_exact_low_budget"} <= blocked
