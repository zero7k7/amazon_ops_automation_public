from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from src.sellersprite_competitor_discovery import (
    discovery_record_needs_refresh,
    load_competitor_discovery_records,
    make_discovery_record,
    merge_competitor_discovery_records,
    normalize_competitors,
    parse_competitors_from_html,
    sellersprite_market_id,
)
from src.sellersprite_fusion import build_sellersprite_competitor_pool
from scripts.amazon_search_competitor_seed_fetch import _candidate_keywords, _record_from_search_payload


def test_sellersprite_market_id_mapping_is_explicit() -> None:
    assert sellersprite_market_id("US") == 1
    assert sellersprite_market_id("UK") == 3
    assert sellersprite_market_id("DE") == 4


def test_parse_competitors_from_tr_td_fixture() -> None:
    html = """
    <table>
      <tr><td>1</td><td>B0OWN00001</td><td>Own product</td></tr>
      <tr><td>2</td><td>B0COMP0001</td><td>Premium board competitor</td><td>rank 3</td></tr>
      <tr><td>3</td><td>B0COMP0002</td><td>Large board competitor</td><td>rank 6</td></tr>
    </table>
    """

    competitors, reason = parse_competitors_from_html(
        html,
        marketplace="US",
        sku="SKU-1",
        asin="B0OWN00001",
        source_page="reversing",
        competitor_source="sellersprite_competitor_direct",
        checked_at="2026-07-02T10:00:00",
    )

    assert reason == ""
    assert [item["competitor_asin"] for item in competitors] == ["B0COMP0001", "B0COMP0002"]
    assert competitors[0]["competitor_source"] == "sellersprite_competitor_direct"
    assert competitors[0]["confidence"] == "medium"


def test_amazon_search_seed_record_keeps_source_keyword_and_title() -> None:
    record = _record_from_search_payload(
        {
            "marketplace": "US",
            "sku": "SKU-1",
            "asin": "B0OWN00001",
            "product_name": "Small desk lamp",
        },
        keyword="small wooden desk lamp",
        parsed_search={
            "competitors": [
                {"asin": "B0COMP0001", "title": "Small Metal Desk Lamp", "position": "1"},
                {"asin": "B0OWN00001", "title": "Own product", "position": "2"},
            ]
        },
        checked_at="2026-07-02T12:00:00",
        limit_per_product=3,
    )

    assert record["competitor_discovery_status"] == "已抓取"
    assert record["source_page"] == "amazon_search_seed"
    assert record["competitor_count"] == 1
    competitor = record["competitors"][0]
    assert competitor["competitor_asin"] == "B0COMP0001"
    assert competitor["competitor_title"] == "Small Metal Desk Lamp"
    assert competitor["competitor_source"] == "amazon_search_visible"
    assert competitor["source_keyword"] == "small wooden desk lamp"


def test_amazon_search_seed_keyword_priority_prefers_frontend_then_sellersprite() -> None:
    keywords = _candidate_keywords(
        {
            "frontend_core_keyword": "small wooden desk lamp",
            "frontend_search_keyword": "small wooden desk lamp",
            "own_sellersprite_keywords": "dimmer desk lamp、desk lamp",
        },
        limit=3,
    )

    assert keywords == ["small wooden desk lamp", "dimmer desk lamp", "desk lamp"]


def test_parse_competitors_from_virtual_div_fixture() -> None:
    html = """
    <div class="vxe-table--body-wrapper">
      <div class="vxe-body--row">B0OWN00001 Own</div>
      <div class="vxe-body--row">B0COMP0003 Compact board overlap 8 words</div>
      <div class="vxe-body--row">B0COMP0004 Handle board traffic 2195</div>
    </div>
    """

    competitors, reason = parse_competitors_from_html(
        html,
        marketplace="UK",
        sku="SKU-2",
        asin="B0OWN00001",
        source_page="relation_keyword",
        competitor_source="sellersprite_relation_keyword",
        checked_at="2026-07-02T10:00:00",
    )

    assert reason == ""
    assert [item["competitor_asin"] for item in competitors] == ["B0COMP0003", "B0COMP0004"]
    assert all(item["confidence"] == "medium" for item in competitors)


def test_parse_empty_page_returns_no_competitor_data() -> None:
    competitors, reason = parse_competitors_from_html(
        "<main>暂无数据，0 条结果</main>",
        marketplace="DE",
        sku="SKU-3",
        asin="B0OWN00001",
        source_page="reversing_sources",
        competitor_source="sellersprite_reversing_sources",
        checked_at="2026-07-02T10:00:00",
    )

    assert competitors == []
    assert reason == "无竞品数据"


def test_normalize_competitors_dedupes_excludes_own_and_limits_three() -> None:
    competitors = normalize_competitors(
        [
            {"competitor_asin": "B0OWN00001", "competitor_source": "sellersprite_competitor_direct", "confidence": "high"},
            {"competitor_asin": "B0COMP0001", "competitor_source": "sellersprite_keyword_reverse_seed", "confidence": "low"},
            {"competitor_asin": "B0COMP0001", "competitor_source": "sellersprite_competitor_direct", "confidence": "high"},
            {"competitor_asin": "B0COMP0002", "competitor_source": "sellersprite_reversing_sources", "confidence": "medium"},
            {"competitor_asin": "B0COMP0003", "competitor_source": "sellersprite_relation_keyword", "confidence": "medium"},
            {"competitor_asin": "B0COMP0004", "competitor_source": "sellersprite_traffic_extend", "confidence": "medium"},
        ],
        marketplace="US",
        sku="SKU-1",
        asin="B0OWN00001",
        checked_at="2026-07-02T10:00:00",
        data_date="2026-07-02",
        limit=3,
    )

    assert [item["competitor_asin"] for item in competitors] == ["B0COMP0001", "B0COMP0002", "B0COMP0003"]
    assert competitors[0]["competitor_source"] == "sellersprite_competitor_direct"


def test_competitor_discovery_cache_uses_marketplace_sku_asin_and_preserves_success(tmp_path: Path) -> None:
    path = tmp_path / "sellersprite_competitor_discovery_results.json"
    row = {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "product_name": "Own"}
    success = make_discovery_record(
        row,
        competitors=[
            {
                "marketplace": "US",
                "sku": "SKU-1",
                "asin": "B0OWN00001",
                "competitor_asin": "B0COMP0001",
                "competitor_source": "sellersprite_competitor_direct",
                "confidence": "high",
            }
        ],
        status="已抓取",
        source_page="reversing",
        checked_at="2026-07-02T10:00:00",
    )
    failure = make_discovery_record(
        row,
        competitors=[],
        status="未登录",
        checked_at="2026-07-02T11:00:00",
        last_error="游客状态",
    )

    merge_competitor_discovery_records([success], path)
    merge_competitor_discovery_records([failure], path)
    loaded = load_competitor_discovery_records(path, max_age_days=7)

    assert loaded[("US", "SKU-1", "B0OWN00001")]["competitor_discovery_status"] == "已抓取"
    assert loaded[("US", "SKU-1", "B0OWN00001")]["competitors"][0]["competitor_asin"] == "B0COMP0001"
    assert ("US", "OTHER-SKU", "B0OWN00001") not in loaded


def test_discovery_cache_keeps_amazon_seed_without_replacing_primary(tmp_path: Path) -> None:
    path = tmp_path / "sellersprite_competitor_discovery_results.json"
    row = {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "product_name": "Own"}
    primary = make_discovery_record(
        row,
        competitors=[
            {
                "marketplace": "US",
                "sku": "SKU-1",
                "asin": "B0OWN00001",
                "competitor_asin": "B0COMP0001",
                "competitor_source": "sellersprite_competitor_direct",
                "source_page": "reversing",
                "confidence": "high",
            }
        ],
        status="已抓取",
        source_page="reversing",
        checked_at="2026-07-02T10:00:00",
    )
    amazon_seed = make_discovery_record(
        row,
        competitors=[
            {
                "marketplace": "US",
                "sku": "SKU-1",
                "asin": "B0OWN00001",
                "competitor_asin": "B0COMP0001",
                "competitor_source": "amazon_search_visible",
                "source_page": "amazon_search_seed",
                "source_keyword": "premium board",
                "confidence": "medium",
            }
        ],
        status="已抓取",
        source_page="amazon_search_seed",
        checked_at="2026-07-02T11:00:00",
    )

    merge_competitor_discovery_records([primary], path)
    merge_competitor_discovery_records([amazon_seed], path)
    loaded = load_competitor_discovery_records(path, max_age_days=7)[("US", "SKU-1", "B0OWN00001")]
    stored_sources = {
        item.get("source_page")
        for item in json.loads(path.read_text(encoding="utf-8"))["items"]
        if item.get("marketplace") == "US" and item.get("asin") == "B0OWN00001"
    }

    assert stored_sources == {"reversing", "amazon_search_seed"}
    assert loaded["source_page"] == "reversing"
    assert loaded["competitors"][0]["competitor_source"] == "sellersprite_competitor_direct"
    assert loaded["amazon_search_seed_source_page"] == "amazon_search_seed"
    assert loaded["amazon_search_seed_competitors"][0]["competitor_asin"] == "B0COMP0001"


def test_stale_or_failure_record_needs_refresh() -> None:
    old_day = (datetime.now() - timedelta(days=9)).isoformat(timespec="seconds")
    stale = {
        "competitor_discovery_status": "已抓取",
        "checked_at": old_day,
        "data_date": old_day[:10],
        "competitors": [{"competitor_asin": "B0COMP0001"}],
    }
    failure = {"competitor_discovery_status": "未登录", "checked_at": datetime.now().isoformat(timespec="seconds"), "competitors": []}

    assert discovery_record_needs_refresh(stale, max_age_days=7)
    assert discovery_record_needs_refresh(failure, max_age_days=7)


def test_direct_discovery_cache_overrides_seed_source() -> None:
    row = {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "priority": "P0"}
    own_record = {"marketplace": "US", "asin": "B0OWN00001", "seller_sprite_check_status": "已抓取", "keywords": [{"keyword": "board"}]}
    seed_record = {
        "marketplace": "US",
        "asin": "B0SEED0001",
        "source_role": "competitor",
        "parent_marketplace": "US",
        "parent_sku": "SKU-1",
        "parent_asin": "B0OWN00001",
        "keywords": [{"keyword": "seed term"}],
    }
    discovery_record = {
        "marketplace": "US",
        "sku": "SKU-1",
        "asin": "B0OWN00001",
        "competitor_discovery_status": "已抓取",
        "source_page": "reversing",
        "competitors": [
                {
                    "competitor_asin": "B0DIR00001",
                    "competitor_title": "Direct competitor",
                    "competitor_source": "sellersprite_competitor_direct",
                    "source_keyword": "board",
                    "confidence": "high",
                }
        ],
    }

    pool = build_sellersprite_competitor_pool(
        row,
        own_record,
        {("US", "B0OWN00001"): own_record, ("US", "B0SEED0001"): seed_record},
        competitor_discovery_records={("US", "SKU-1", "B0OWN00001"): discovery_record},
    )

    assert pool["competitor_pool_asins"].split("、")[0] == "B0DIR00001"
    assert "sellersprite_competitor_direct" in pool["competitor_discovery_source"]
    assert pool["competitor_pool_confidence"] == "medium"


def test_discovery_failure_degrades_pool_without_blocking() -> None:
    row = {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "priority": "P0"}
    own_record = {"marketplace": "US", "asin": "B0OWN00001", "seller_sprite_check_status": "已抓取", "keywords": [{"keyword": "board"}]}
    failure_record = {
        "marketplace": "US",
        "sku": "SKU-1",
        "asin": "B0OWN00001",
        "competitor_discovery_status": "未登录",
        "last_error": "游客状态",
        "competitors": [],
    }

    pool = build_sellersprite_competitor_pool(
        row,
        own_record,
        {("US", "B0OWN00001"): own_record},
        competitor_discovery_records={("US", "SKU-1", "B0OWN00001"): failure_record},
    )

    assert pool["competitor_pool_status"] == "卖家精灵竞品发现失败"
    assert pool["competitor_discovery_status"] == "未登录"
    assert pool["competitor_discovery_error"] == "游客状态"


def test_direct_candidate_without_source_or_reverse_is_rejected() -> None:
    row = {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "priority": "P0"}
    own_record = {"marketplace": "US", "asin": "B0OWN00001", "seller_sprite_check_status": "已抓取", "keywords": [{"keyword": "board"}]}
    discovery_record = {
        "marketplace": "US",
        "sku": "SKU-1",
        "asin": "B0OWN00001",
        "competitor_discovery_status": "已抓取",
        "source_page": "reversing",
        "competitors": [
            {
                "competitor_asin": "B0DIR00001",
                "competitor_title": "Direct competitor",
                "competitor_source": "sellersprite_competitor_direct",
                "confidence": "high",
            }
        ],
    }

    pool = build_sellersprite_competitor_pool(
        row,
        own_record,
        {("US", "B0OWN00001"): own_record},
        competitor_discovery_records={("US", "SKU-1", "B0OWN00001"): discovery_record},
    )

    assert pool["competitor_pool_count"] == 0
    assert pool["competitor_pool_status"] == "竞品证据不足"
    assert pool["competitor_rejected_count"] == 1


def test_seed_only_pool_keeps_low_confidence() -> None:
    row = {"marketplace": "US", "sku": "SKU-1", "asin": "B0OWN00001", "priority": "P0"}
    own_record = {"marketplace": "US", "asin": "B0OWN00001", "seller_sprite_check_status": "已抓取", "keywords": [{"keyword": "board"}]}
    seed_record = {
        "marketplace": "US",
        "asin": "B0SEED0001",
        "source_role": "competitor",
        "parent_marketplace": "US",
        "parent_sku": "SKU-1",
        "parent_asin": "B0OWN00001",
        "keywords": [{"keyword": "seed term"}],
    }

    pool = build_sellersprite_competitor_pool(
        row,
        own_record,
        {("US", "B0OWN00001"): own_record, ("US", "B0SEED0001"): seed_record},
        competitor_discovery_records={},
    )

    assert pool["competitor_discovery_source"] == "unknown"
    assert pool["competitor_pool_status"] == "竞品证据不足"
    assert pool["competitor_pool_confidence"] == "unknown"
