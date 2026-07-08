from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]

PRODUCTS = [
    {
        "marketplace": "US",
        "country": "US",
        "marketplace_raw": "AMAZON.COM",
        "sku": "SKU-PUBLIC-US-001",
        "asin": "B0B5HPKZKM",
        "product_name": "Public Amazon.com Barbie travel doll set",
        "currency": "USD",
        "unit_cost": 4.20,
        "shipping_cost": 1.10,
        "handling_fee": 0.40,
        "target_acos": 0.22,
        "profit_before_ads_per_unit": 6.30,
        "current_inventory": 120,
        "sea_inventory": 80,
        "search_terms": ["barbie travel doll", "barbie doll travel set"],
        "frontend_price": 18.99,
        "frontend_rating": 4.4,
        "frontend_reviews": 328,
        "frontend_coupon": "$2 coupon",
        "frontend_delivery": "Prime delivery in 2 days",
        "sellersprite_keywords": [
            {
                "keyword": "barbie travel doll",
                "translation": "barbie travel doll",
                "monthly_searches": 8200,
                "purchases": 410,
                "purchase_rate": 0.050,
                "natural_rank": 18,
                "ad_rank": 7,
                "spr": 18,
                "ppc": 0.72,
                "ad_products": 42,
            },
            {
                "keyword": "barbie doll travel set",
                "translation": "barbie doll travel set",
                "monthly_searches": 12600,
                "purchases": 510,
                "purchase_rate": 0.040,
                "natural_rank": 32,
                "ad_rank": 11,
                "spr": 24,
                "ppc": 0.88,
                "ad_products": 58,
            },
        ],
        "competitors": [
            {
                "asin": "B07GLMHSS8",
                "title": "Barbie travel doll with suitcase and puppy",
                "source_keyword": "barbie travel doll",
                "price": 19.99,
                "rating": 4.5,
                "reviews": 910,
            },
            {
                "asin": "B07MQBJKKY",
                "title": "Public Amazon.com toy sample B07MQBJKKY",
                "source_keyword": "barbie doll travel set",
                "price": 17.49,
                "rating": 4.3,
                "reviews": 265,
            },
            {
                "asin": "B07T8BT5LZ",
                "title": "Public Amazon.com doll accessory sample B07T8BT5LZ",
                "source_keyword": "barbie travel doll",
                "price": 21.99,
                "rating": 4.6,
                "reviews": 580,
            },
        ],
    },
    {
        "marketplace": "UK",
        "country": "UK",
        "marketplace_raw": "AMAZON_CO_UK",
        "sku": "SKU-PUBLIC-UK-001",
        "asin": "B0H73CXQ5J",
        "product_name": "Public Amazon.co.uk Crayola glitter dots set",
        "currency": "GBP",
        "unit_cost": 3.10,
        "shipping_cost": 0.80,
        "handling_fee": 0.30,
        "target_acos": 0.24,
        "profit_before_ads_per_unit": 5.20,
        "current_inventory": 95,
        "sea_inventory": 40,
        "search_terms": ["crayola glitter dots", "kids craft set"],
        "frontend_price": 16.99,
        "frontend_rating": 4.2,
        "frontend_reviews": 214,
        "frontend_coupon": "5% voucher",
        "frontend_delivery": "Prime delivery tomorrow",
        "sellersprite_keywords": [
            {
                "keyword": "crayola glitter dots",
                "translation": "crayola glitter dots",
                "monthly_searches": 5400,
                "purchases": 270,
                "purchase_rate": 0.050,
                "natural_rank": 21,
                "ad_rank": 8,
                "spr": 16,
                "ppc": 0.54,
                "ad_products": 35,
            },
            {
                "keyword": "kids craft set",
                "translation": "kids craft set",
                "monthly_searches": 9100,
                "purchases": 360,
                "purchase_rate": 0.040,
                "natural_rank": 37,
                "ad_rank": 14,
                "spr": 22,
                "ppc": 0.66,
                "ad_products": 47,
            },
        ],
        "competitors": [
            {
                "asin": "B0CBPNVMV2",
                "title": "Airlab wooden kitchen toy sample",
                "source_keyword": "kids craft set",
                "price": 15.49,
                "rating": 4.4,
                "reviews": 430,
            },
            {
                "asin": "B0FTZ2FF48",
                "title": "Chad Valley wooden train set sample",
                "source_keyword": "kids craft set",
                "price": 18.99,
                "rating": 4.1,
                "reviews": 188,
            },
            {
                "asin": "B0DMM42DYQ",
                "title": "Cute capybara sticker sheets sample",
                "source_keyword": "crayola glitter dots",
                "price": 16.25,
                "rating": 4.5,
                "reviews": 612,
            },
        ],
    },
    {
        "marketplace": "DE",
        "country": "DE",
        "marketplace_raw": "AMAZON_DE",
        "sku": "SKU-PUBLIC-DE-001",
        "asin": "B0BPC8WZL8",
        "product_name": "Public Amazon.de LEGO City Arctic Snowmobile",
        "currency": "EUR",
        "unit_cost": 2.40,
        "shipping_cost": 0.70,
        "handling_fee": 0.25,
        "target_acos": 0.20,
        "profit_before_ads_per_unit": 4.10,
        "current_inventory": 150,
        "sea_inventory": 60,
        "search_terms": ["lego arctic snowmobile", "lego city arctic"],
        "frontend_price": 16.99,
        "frontend_rating": 4.3,
        "frontend_reviews": 486,
        "frontend_coupon": "10% coupon",
        "frontend_delivery": "Prime Lieferung morgen",
        "sellersprite_keywords": [
            {
                "keyword": "lego arctic snowmobile",
                "translation": "lego arctic snowmobile",
                "monthly_searches": 6200,
                "purchases": 310,
                "purchase_rate": 0.050,
                "natural_rank": 16,
                "ad_rank": 6,
                "spr": 15,
                "ppc": 0.48,
                "ad_products": 31,
            },
            {
                "keyword": "lego city arctic",
                "translation": "lego city arctic",
                "monthly_searches": 7600,
                "purchases": 290,
                "purchase_rate": 0.038,
                "natural_rank": 29,
                "ad_rank": 10,
                "spr": 20,
                "ppc": 0.57,
                "ad_products": 39,
            },
        ],
        "competitors": [
            {
                "asin": "B0BPCBP5ZV",
                "title": "LEGO Ninjago dragon toy sample",
                "source_keyword": "lego city arctic",
                "price": 15.49,
                "rating": 4.4,
                "reviews": 530,
            },
            {
                "asin": "B09BNTZH9C",
                "title": "LEGO fire truck rescue toy sample",
                "source_keyword": "lego city arctic",
                "price": 17.99,
                "rating": 4.2,
                "reviews": 205,
            },
            {
                "asin": "B08MZY9RV8",
                "title": "Melissa and Doug folding barn sample",
                "source_keyword": "lego arctic snowmobile",
                "price": 14.99,
                "rating": 4.6,
                "reviews": 720,
            },
        ],
    },
]


def _write_workbook(path: Path, sheets: dict[str, list[dict[str, object]]]) -> None:
    wb = Workbook()
    first = True
    for title, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title=title)
        ws.title = title
        first = False
        headers = list(rows[0].keys()) if rows else []
        ws.append(headers)
        for row in rows:
            ws.append([row.get(header, "") for header in headers])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _write_json(path: Path, payload: dict[str, object] | list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def _guard(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(
            f"Refusing to overwrite existing file: {path}. "
            "Run with --force only in a demo clone or after backing up real business files."
        )


def _date_ranges() -> dict[str, tuple[date, date]]:
    recent_end = date.today()
    recent_start = recent_end - timedelta(days=6)
    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=6)
    return {
        "recent": (recent_start, recent_end),
        "prior": (prior_start, prior_end),
    }


def _range_label(start: date, end: date) -> str:
    return f"{start.strftime('%Y/%m/%d')} ~ {end.strftime('%Y/%m/%d')}"


def _custom_data_paths() -> list[Path]:
    periods = _date_ranges()
    prior_start, _ = periods["prior"]
    _, recent_end = periods["recent"]
    paths: list[Path] = []
    for product in PRODUCTS:
        market = product["marketplace"]
        lower = market.lower()
        base = ROOT / "data" / "raw_amazon_custom" / market
        suffix = f"{prior_start.isoformat()}_{recent_end.isoformat()}.xlsx"
        paths.append(base / f"traffic_sales_{lower}_compare_{suffix}")
        paths.append(base / f"search_query_performance_{lower}_compare_{suffix}")
    return paths


def _output_cache_paths() -> list[Path]:
    output = ROOT / "data" / "output"
    return [
        output / "frontend_check_results.json",
        output / "sellersprite_reverse_asin_results.json",
        output / "sellersprite_competitor_discovery_results.json",
        output / "sellersprite_history_snapshots.jsonl",
        output / "autoopt_feedback_input.json",
    ]


def _ads_rows() -> list[dict[str, object]]:
    start = date.today() - timedelta(days=13)
    rows: list[dict[str, object]] = []
    for offset in range(14):
        day = start + timedelta(days=offset)
        for product in PRODUCTS:
            for term_index, term in enumerate(product["search_terms"]):
                clicks = 2 + ((offset + term_index) % 4)
                orders = 1 if offset in {4, 9, 13} and term_index == 0 else 0
                spend = round(clicks * (0.28 + 0.05 * term_index), 2)
                sales = orders * (18.99 if product["marketplace"] == "US" else 16.99)
                rows.append(
                    {
                        "report_date": day.isoformat(),
                        "campaign_name_(informational_only)": f"Demo {product['marketplace']} auto campaign",
                        "campaign_country": product["country"],
                        "ad_group": f"Demo {product['marketplace']} ad group",
                        "advertised_sku": product["sku"],
                        "advertised_asin": product["asin"],
                        "marketplace": product["marketplace_raw"],
                        "customer_search_term": term,
                        "keyword_or_product_targeting": term,
                        "targeting_type": "BROAD" if term_index else "EXACT",
                        "impr.": 100 + offset * 5 + term_index * 10,
                        "click": clicks,
                        "cost": spend,
                        "orders": orders,
                        "sales": round(sales, 2),
                    }
                )
    return rows


def _traffic_sales_rows(product: dict[str, object]) -> list[dict[str, object]]:
    periods = _date_ranges()
    prior_start, prior_end = periods["prior"]
    recent_start, recent_end = periods["recent"]
    prior_label = _range_label(prior_start, prior_end)
    recent_label = _range_label(recent_start, recent_end)
    base_price = float(product["frontend_price"])
    return [
        {
            "ASIN": product["asin"],
            "商品名称": product["product_name"],
            f"转化率 {prior_label}": 0.075,
            f"转化率 {recent_label}": 0.061,
            f"推荐报价浏览量 {prior_label}": 420,
            f"推荐报价浏览量 {recent_label}": 390,
            f"推荐报价率 {prior_label}": 0.94,
            f"推荐报价率 {recent_label}": 0.88,
            f"已订购商品数量 {prior_label}": 22,
            f"已订购商品数量 {recent_label}": 17,
            f"已发货商品数量 {prior_label}": 21,
            f"已发货商品数量 {recent_label}": 16,
            f"销售额 {prior_label}": round(22 * base_price, 2),
            f"销售额 {recent_label}": round(17 * base_price, 2),
        }
    ]


def _search_query_rows(product: dict[str, object]) -> list[dict[str, object]]:
    periods = _date_ranges()
    prior_start, prior_end = periods["prior"]
    recent_start, recent_end = periods["recent"]
    prior_label = _range_label(prior_start, prior_end)
    recent_label = _range_label(recent_start, recent_end)
    primary_term, secondary_term = product["search_terms"]
    return [
        {
            "搜索查询": primary_term,
            "ASIN": product["asin"],
            "商品名称": product["product_name"],
            f"展示次数 {prior_label}": 2400,
            f"展示次数 {recent_label}": 2850,
            f"点击数量 {prior_label}": 92,
            f"点击数量 {recent_label}": 118,
            f"添加购物车 {prior_label}": 14,
            f"添加购物车 {recent_label}": 19,
            f"购买数量 {prior_label}": 3,
            f"购买数量 {recent_label}": 5,
        },
        {
            "搜索查询": secondary_term,
            "ASIN": product["asin"],
            "商品名称": product["product_name"],
            f"展示次数 {prior_label}": 1800,
            f"展示次数 {recent_label}": 2300,
            f"点击数量 {prior_label}": 56,
            f"点击数量 {recent_label}": 74,
            f"添加购物车 {prior_label}": 8,
            f"添加购物车 {recent_label}": 11,
            f"购买数量 {prior_label}": 0,
            f"购买数量 {recent_label}": 0,
        },
    ]


def _erp_rows() -> list[dict[str, object]]:
    start = date.today() - timedelta(days=13)
    rows: list[dict[str, object]] = []
    for offset in range(14):
        day = start + timedelta(days=offset)
        for product in PRODUCTS:
            orders = 1 + ((offset + len(product["sku"])) % 3)
            rows.append(
                {
                    "sales_date": day.isoformat(),
                    "seller_sku": product["sku"],
                    "child_asin": product["asin"],
                    "item_name": product["product_name"],
                    "country": product["country"],
                    "orders": orders,
                    "sales": round(orders * (18.99 if product["marketplace"] == "US" else 16.99), 2),
                    "fba_stock": product["current_inventory"],
                    "available_stock": product["current_inventory"],
                }
            )
    return rows


def _cost_rows() -> list[dict[str, object]]:
    return [
        {
            "marketplace": product["marketplace"],
            "sku": product["sku"],
            "asin": product["asin"],
            "product_name": product["product_name"],
            "currency": product["currency"],
            "unit_cost": product["unit_cost"],
            "shipping_cost": product["shipping_cost"],
            "handling_fee": product["handling_fee"],
            "target_acos": product["target_acos"],
            "profit_before_ads_per_unit": product["profit_before_ads_per_unit"],
        }
        for product in PRODUCTS
    ]


def _inventory_rows() -> list[dict[str, object]]:
    return [
        {
            "marketplace": product["marketplace"],
            "sku": product["sku"],
            "asin": product["asin"],
            "current_inventory": product["current_inventory"],
            "sea_inventory": product["sea_inventory"],
            "inventory_note": "Demo inventory only",
        }
        for product in PRODUCTS
    ]


def _alias_rows() -> list[dict[str, object]]:
    return [
        {
            "marketplace": product["marketplace"],
            "source_sku": product["sku"],
            "canonical_sku": product["sku"],
            "asin": product["asin"],
            "reason": "demo self mapping",
        }
        for product in PRODUCTS
    ]


def _frontend_results_payload() -> dict[str, object]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    items: list[dict[str, object]] = []
    for product in PRODUCTS:
        competitor_asins = [item["asin"] for item in product["competitors"]]
        items.append(
            {
                "marketplace": product["marketplace"],
                "sku": product["sku"],
                "asin": product["asin"],
                "product_name": product["product_name"],
                "frontend_check_status": "沿用缓存",
                "frontend_data_date": date.today().isoformat(),
                "frontend_data_freshness": f"沿用 {date.today().isoformat()} 前台数据",
                "frontend_check_method": "demo_cache",
                "frontend_cache_used": True,
                "frontend_findings": (
                    f"Demo cache: price {product['currency']} {product['frontend_price']}; "
                    f"rating {product['frontend_rating']}; reviews {product['frontend_reviews']}; "
                    f"coupon {product['frontend_coupon']}; Buy Box available."
                ),
                "frontend_price": product["frontend_price"],
                "frontend_rating": product["frontend_rating"],
                "frontend_reviews": product["frontend_reviews"],
                "frontend_coupon": product["frontend_coupon"],
                "frontend_buy_box": "available",
                "frontend_delivery": product["frontend_delivery"],
                "frontend_search_status": "已读取部分结果",
                "frontend_search_partial_evidence": True,
                "frontend_search_keyword": product["search_terms"][1],
                "frontend_search_findings": f"Demo competitors visible: {', '.join(competitor_asins)}",
                "frontend_competitor_count": len(competitor_asins),
                "frontend_competitors": ", ".join(competitor_asins),
                "competitor_comparability": "high",
                "comparable_competitor_count": len(competitor_asins),
                "frontend_location_note": f"{product['marketplace']} demo marketplace location",
                "frontend_location_verified": True,
                "frontend_location_exact": True,
                "frontend_location_scope": "exact",
                "frontend_evidence_quality_score": 72,
                "frontend_search_quality_score": 62,
                "frontend_evidence_tier": "仅背景参考",
                "frontend_decision_evidence_tier": "仅背景参考",
                "frontend_evidence_is_strong": False,
                "frontend_auto_conclusion": "FRONTEND_CACHE_ONLY",
                "frontend_auto_conclusion_label": "缓存样本仅供背景参考",
                "frontend_evidence_audit_summary": "演示缓存，仅背景参考",
                "frontend_evidence_audit_reasons": ["沿用缓存", "搜索页仅部分读取"],
            }
        )
    return {
        "generated_at": generated_at,
        "source": "setup_demo_data",
        "items": items,
    }


def _seller_keyword_items(product: dict[str, object], *, multiplier: float = 1.0) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for keyword in product["sellersprite_keywords"]:
        copied = dict(keyword)
        copied["monthly_searches"] = int(float(copied["monthly_searches"]) * multiplier)
        copied["purchases"] = int(float(copied["purchases"]) * multiplier)
        copied["natural_rank"] = int(float(copied["natural_rank"]) + (1 if multiplier < 1 else 0))
        items.append(copied)
    return items


def _sellersprite_payload() -> dict[str, object]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    today = date.today().isoformat()
    items: list[dict[str, object]] = []
    for product in PRODUCTS:
        items.append(
            {
                "marketplace": product["marketplace"],
                "sku": product["sku"],
                "asin": product["asin"],
                "product_name": product["product_name"],
                "source_role": "own",
                "seller_sprite_check_status": "已抓取",
                "status": "已抓取",
                "checked_at": generated_at,
                "data_date": today,
                "keywords": _seller_keyword_items(product),
            }
        )
        for index, competitor in enumerate(product["competitors"]):
            keyword_source = product["sellersprite_keywords"][index % len(product["sellersprite_keywords"])]
            keyword_item = {
                **keyword_source,
                "monthly_searches": int(float(keyword_source["monthly_searches"]) * 1.15),
                "purchases": int(float(keyword_source["purchases"]) * 1.10),
                "natural_rank": max(int(float(keyword_source["natural_rank"])) - 4, 1),
                "ad_rank": max(int(float(keyword_source["ad_rank"])) - 2, 1),
            }
            items.append(
                {
                    "marketplace": product["marketplace"],
                    "sku": f"{product['sku']}-COMP-{index + 1}",
                    "asin": competitor["asin"],
                    "product_name": competitor["title"],
                    "source_role": "competitor",
                    "parent_marketplace": product["marketplace"],
                    "parent_sku": product["sku"],
                    "parent_asin": product["asin"],
                    "competitor_discovery_source": "sellersprite_keyword_overlap",
                    "competitor_pool_confidence": "high",
                    "seller_sprite_check_status": "已抓取",
                    "status": "已抓取",
                    "checked_at": generated_at,
                    "data_date": today,
                    "keywords": [keyword_item],
                }
            )
    return {
        "generated_at": generated_at,
        "source": "setup_demo_data",
        "items": items,
    }


def _competitor_discovery_payload() -> dict[str, object]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    today = date.today().isoformat()
    items: list[dict[str, object]] = []
    for product in PRODUCTS:
        competitors: list[dict[str, object]] = []
        for index, competitor in enumerate(product["competitors"]):
            competitors.append(
                {
                    "marketplace": product["marketplace"],
                    "sku": product["sku"],
                    "asin": product["asin"],
                    "competitor_asin": competitor["asin"],
                    "competitor_title": competitor["title"],
                    "competitor_source": "sellersprite_competitor_direct",
                    "source_page": "demo_cache",
                    "source_keyword": competitor["source_keyword"],
                    "overlap_keyword_count": 2,
                    "traffic_or_rank_hint": "demo overlap keyword",
                    "confidence": "high",
                    "price": competitor["price"],
                    "rating": competitor["rating"],
                    "reviews": competitor["reviews"],
                    "checked_at": generated_at,
                    "data_date": today,
                    "discovery_order": index,
                }
            )
        items.append(
            {
                "marketplace": product["marketplace"],
                "sku": product["sku"],
                "asin": product["asin"],
                "product_name": product["product_name"],
                "competitor_discovery_status": "已抓取",
                "source_page": "demo_cache",
                "checked_at": generated_at,
                "data_date": today,
                "competitor_count": len(competitors),
                "competitors": competitors,
                "last_error": "",
            }
        )
    return {
        "generated_at": generated_at,
        "source": "setup_demo_data",
        "items": items,
    }


def _sellersprite_history_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    captured_at = datetime.now().isoformat(timespec="seconds")
    for days_ago in range(2, -1, -1):
        report_day = date.today() - timedelta(days=days_ago)
        multiplier = 0.94 + (0.03 * (2 - days_ago))
        for product in PRODUCTS:
            for keyword in _seller_keyword_items(product, multiplier=multiplier):
                rows.append(
                    {
                        "report_date": report_day.isoformat(),
                        "captured_at": captured_at,
                        "marketplace": product["marketplace"],
                        "sku": product["sku"],
                        "asin": product["asin"],
                        "source_role": "own",
                        "parent_marketplace": "",
                        "parent_sku": "",
                        "parent_asin": "",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": report_day.isoformat(),
                        "keyword": keyword["keyword"],
                        "normalized_keyword": str(keyword["keyword"]).lower(),
                        "translation": keyword.get("translation", ""),
                        "monthly_searches": keyword["monthly_searches"],
                        "purchases": keyword["purchases"],
                        "purchase_rate": keyword.get("purchase_rate", ""),
                        "natural_rank": keyword["natural_rank"],
                        "ad_rank": keyword["ad_rank"],
                        "spr": keyword["spr"],
                        "ppc": keyword["ppc"],
                        "ad_products": keyword["ad_products"],
                        "competitor_discovery_source": "",
                        "competitor_pool_confidence": "",
                    }
                )
    return rows


def _feedback_payload() -> dict[str, object]:
    report_day = date.today() - timedelta(days=8)
    next_review = date.today() - timedelta(days=1)
    rows: list[dict[str, object]] = []
    for product in PRODUCTS:
        term = product["search_terms"][1]
        rows.append(
            {
                "marketplace": product["marketplace"],
                "sku": product["sku"],
                "asin": product["asin"],
                "product_name": product["product_name"],
                "diagnosis_type": "搜索词处理",
                "action_scope": "search_term",
                "search_term_or_target": term,
                "today_action": "降竞价",
                "suggested_action": "降竞价",
                "normalized_action": "bid_down",
                "manual_action_taken": "demo bid lowered 10%",
                "confirmed_status": "已执行",
                "confirmed_at": f"{report_day.isoformat()}T09:00:00",
                "report_date": report_day.isoformat(),
                "confirmed_note": "Public demo executed feedback record for review workflow.",
                "next_review": next_review.isoformat(),
                "cooldown_days": 7,
                "action_id": (
                    f"{product['marketplace']}||{product['sku']}||{product['asin']}||"
                    f"search_term||{term}||bid_down"
                ),
            }
        )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "setup_demo_data",
        "rows": rows,
    }


def setup_demo_data(*, force: bool) -> list[Path]:
    targets = [
        ROOT / "config" / "product_cost_config.xlsx",
        ROOT / "config" / "sku_alias_map.xlsx",
        ROOT / "data" / "raw_ads" / "ads_report_all.csv",
        ROOT / "data" / "raw_erp" / "sales_report_all.xlsx",
        *_custom_data_paths(),
        *_output_cache_paths(),
    ]
    for target in targets:
        _guard(target, force=force)

    written: list[Path] = []
    ads_path = ROOT / "data" / "raw_ads" / "ads_report_all.csv"
    ads_path.parent.mkdir(parents=True, exist_ok=True)
    ads_rows = _ads_rows()
    with ads_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ads_rows[0].keys()))
        writer.writeheader()
        writer.writerows(ads_rows)
    written.append(ads_path)

    erp_path = ROOT / "data" / "raw_erp" / "sales_report_all.xlsx"
    _write_workbook(erp_path, {"sales_report_all": _erp_rows()})
    written.append(erp_path)

    cost_path = ROOT / "config" / "product_cost_config.xlsx"
    _write_workbook(
        cost_path,
        {
            "product_cost_config": _cost_rows(),
            "SKU匹配检查": _inventory_rows(),
        },
    )
    written.append(cost_path)

    alias_path = ROOT / "config" / "sku_alias_map.xlsx"
    _write_workbook(alias_path, {"sku_alias_map": _alias_rows()})
    written.append(alias_path)

    custom_paths = _custom_data_paths()
    for product in PRODUCTS:
        market = product["marketplace"]
        traffic_path = next(
            path
            for path in custom_paths
            if path.parent.name == market and path.name.startswith("traffic_sales_")
        )
        query_path = next(
            path
            for path in custom_paths
            if path.parent.name == market and path.name.startswith("search_query_performance_")
        )
        _write_workbook(traffic_path, {"traffic_sales": _traffic_sales_rows(product)})
        written.append(traffic_path)
        _write_workbook(query_path, {"search_query_performance": _search_query_rows(product)})
        written.append(query_path)

    output = ROOT / "data" / "output"
    frontend_path = output / "frontend_check_results.json"
    _write_json(frontend_path, _frontend_results_payload())
    written.append(frontend_path)

    sellersprite_path = output / "sellersprite_reverse_asin_results.json"
    _write_json(sellersprite_path, _sellersprite_payload())
    written.append(sellersprite_path)

    competitor_path = output / "sellersprite_competitor_discovery_results.json"
    _write_json(competitor_path, _competitor_discovery_payload())
    written.append(competitor_path)

    history_path = output / "sellersprite_history_snapshots.jsonl"
    _write_jsonl(history_path, _sellersprite_history_rows())
    written.append(history_path)

    feedback_path = output / "autoopt_feedback_input.json"
    _write_json(feedback_path, _feedback_payload())
    written.append(feedback_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Create public offline demo data for a clean clone.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing demo target files. Do not use in a real business workspace without backups.",
    )
    args = parser.parse_args()
    written = setup_demo_data(force=args.force)
    print("Demo data written:")
    for path in written:
        print(f"- {path.relative_to(ROOT)}")
    print("Next command: python scripts/run_report_window.py --workflow daily")
    print("This starts the local button service and opens http://127.0.0.1:8765/report/latest_recommendations.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
