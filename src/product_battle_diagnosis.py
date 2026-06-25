from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .product_decision_layer import (
    competitor_comparability,
    frontend_constraints,
    parse_coupon,
    product_key_text,
)


BATTLE_DECISIONS = {
    "EXECUTE_AD_ACTION",
    "FRONTEND_FIX_FIRST",
    "HOLD_AND_REVIEW",
    "CONSERVATIVE_RUN",
    "SMALL_EXACT_TEST",
    "INVENTORY_BLOCKED",
    "DATA_INSUFFICIENT",
    "DO_NOT_TOUCH",
}

BATTLE_LABELS = {
    "EXECUTE_AD_ACTION": "今天执行",
    "FRONTEND_FIX_FIRST": "先修前台",
    "HOLD_AND_REVIEW": "先等复盘",
    "CONSERVATIVE_RUN": "保守跑",
    "SMALL_EXACT_TEST": "小预算精准测试",
    "INVENTORY_BLOCKED": "库存拦截",
    "DATA_INSUFFICIENT": "数据不足",
    "DO_NOT_TOUCH": "今天不动",
}


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _num(value: object) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").strip()
    if text in {"", "N/A", "None", "nan"}:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def _product_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        _clean(row.get("marketplace") or row.get("站点")).upper(),
        _clean(row.get("sku") or row.get("SKU")),
        _clean(row.get("asin") or row.get("ASIN")).upper(),
    )


def _lookup(rows: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        if not item.get("sku") and item.get("SKU"):
            item["sku"] = item.get("SKU")
        if not item.get("asin") and item.get("ASIN"):
            item["asin"] = item.get("ASIN")
        if not item.get("marketplace") and item.get("站点"):
            item["marketplace"] = item.get("站点")
        key = product_key_text(item)
        if key == "||":
            continue
        result.setdefault(key, item)
        marketplace, sku, asin = _product_key(item)
        if asin:
            result.setdefault("||".join((marketplace, "", asin)), item)
        if sku:
            result.setdefault("||".join((marketplace, sku, "")), item)
    return result


def _lookup_one(lookup: dict[str, dict[str, object]], row: dict[str, object]) -> dict[str, object]:
    marketplace, sku, asin = _product_key(row)
    for key in (
        "||".join((marketplace, sku, asin)),
        "||".join((marketplace, "", asin)),
        "||".join((marketplace, sku, "")),
    ):
        if key in lookup:
            return lookup[key]
    return {}


def _product_name(row: dict[str, object]) -> str:
    return _clean(row.get("product_name") or row.get("产品") or row.get("product") or row.get("asin") or row.get("ASIN"))


def _metric(row: dict[str, object], *names: str) -> float:
    for name in names:
        if name in row and _clean(row.get(name)):
            return _num(row.get(name))
    return 0.0


def _collect_candidate_products(
    analysis_payload: dict,
    report_view: dict | None,
    *,
    target: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if report_view:
        for key in [
            "today_task_queue_rows",
            "listing_price_diagnosis_rows",
            "frontend_check_queue_rows",
        ]:
            rows.extend(row for row in report_view.get(key, []) or [] if isinstance(row, dict))
    if target:
        rows.insert(0, dict(target))

    metric_rows: dict[str, dict[str, object]] = {}
    marketplace = _clean(analysis_payload.get("target_marketplace")).upper()
    metrics = analysis_payload.get("product_window_metrics", {})
    if isinstance(metrics, dict):
        for window in ["14d", "30d", "7d"]:
            for row in metrics.get(window, []) or []:
                if not isinstance(row, dict):
                    continue
                item = dict(row)
                item.setdefault("marketplace", marketplace)
                metric_rows.setdefault(product_key_text(item), item)

    seen: set[str] = set()
    products: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item.setdefault("marketplace", marketplace)
        if not item.get("sku") and item.get("SKU"):
            item["sku"] = item.get("SKU")
        if not item.get("asin") and item.get("ASIN"):
            item["asin"] = item.get("ASIN")
        if not item.get("product_name") and item.get("产品"):
            item["product_name"] = item.get("产品")
        key = product_key_text(item)
        if key == "||" or key in seen:
            continue
        seen.add(key)
        base = dict(metric_rows.get(key, {}))
        base.update({field: value for field, value in item.items() if _clean(value)})
        products.append(base)
    return products


def _has_recent_frontend(frontend: dict[str, object]) -> bool:
    status = _clean(frontend.get("frontend_check_status"))
    freshness = _clean(frontend.get("frontend_data_freshness"))
    return bool(status in {"已自动检查", "已核查"} or status.startswith("沿用") or freshness in {"今日读取", "recent"})


def _demand_layer(analysis_payload: dict, product: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    marketplace, _, asin = _product_key(product)
    rows = []
    for key in ["custom_search_query_performance", "custom_traffic_sales", "search_query_opportunities"]:
        for row in analysis_payload.get(key, []) or []:
            if not isinstance(row, dict):
                continue
            row_marketplace = _clean(row.get("marketplace") or marketplace).upper()
            if row_marketplace == marketplace and _clean(row.get("asin") or row.get("ASIN")).upper() == asin:
                rows.append(row)
    if not rows:
        return {
            "demand_status": "unknown",
            "evidence": [],
            "interpretation": "搜索查询/流量销售增强数据不足，不能判断市场需求是否冷却。",
        }, ["demand_enhanced_data"]
    impressions = sum(_metric(row, "query_impressions", "impressions", "page_views") for row in rows)
    purchases = sum(_metric(row, "query_purchases", "purchases", "ordered_units") for row in rows)
    status = "stable" if impressions > 0 else "unknown"
    interpretation = "需求未明显消失，重点看本品是否拿得到点击和转化。" if impressions > 0 else "增强数据有记录但缺少搜索量，需求仍需观察。"
    return {
        "demand_status": status,
        "evidence": [f"增强数据记录 {len(rows)} 条", f"搜索/浏览量 {impressions:.0f}", f"购买量 {purchases:.0f}"],
        "interpretation": interpretation,
    }, []


def _traffic_layer(product: dict[str, object], search_rows: list[dict[str, object]]) -> dict[str, object]:
    clicks = _metric(product, "clicks", "ad_clicks", "近14天广告点击")
    spend = _metric(product, "spend", "ad_spend", "广告花费")
    ad_orders = _metric(product, "ad_orders", "广告订单")
    promoted_orders = _metric(product, "promoted_ad_orders", "promoted_click_orders")
    halo_orders = _metric(product, "halo_ad_orders", "halo_click_orders")
    total_orders = _metric(product, "total_orders", "近14天总单")
    impressions = _metric(product, "impressions", "ad_impressions", "展示")
    cpc = spend / clicks if clicks else 0.0
    cvr = ad_orders / clicks if clicks else 0.0
    ctr = clicks / impressions if impressions else 0.0
    if impressions <= 0 and clicks <= 0:
        problem = "缺少曝光和点击样本，不能先判 Listing 或前台承接。"
        status = "traffic_absent"
    elif clicks >= 20 and ad_orders == 0:
        problem = "点击有量但广告单断，优先判断为点击后承接失败或流量结构错误。"
        status = "conversion_broken"
    elif impressions > 0 and clicks <= 2:
        problem = "曝光有但点击弱，先看主图/价格/标题匹配。"
        status = "click_weak"
    elif clicks <= 2 and spend <= 1:
        problem = "广告样本偏小，不足以判断。"
        status = "sample_low"
    else:
        problem = "广告端有样本，需结合前台和历史动作判断。"
        status = "mixed"
    wasted_terms = []
    broken_terms = []
    winners = []
    product_key = product_key_text(product)
    for row in search_rows:
        if product_key_text(row) != product_key:
            continue
        term = _clean(row.get("search_term_or_target") or row.get("搜索词/ASIN") or row.get("targeting"))
        row_clicks = _metric(row, "clicks", "点击")
        row_orders = _metric(row, "ad_orders", "订单")
        row_spend = _metric(row, "spend", "花费")
        if term and row_clicks >= 8 and row_orders == 0:
            wasted_terms.append({"term": term, "clicks": row_clicks, "spend": row_spend})
        if term and row_clicks >= 3 and row_orders == 0:
            broken_terms.append({"term": term, "clicks": row_clicks, "spend": row_spend})
        if term and row_orders > 0:
            winners.append({"term": term, "orders": row_orders, "spend": row_spend})
    return {
        "traffic_status": status,
        "main_ad_problem": problem,
        "metrics": {
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "ad_orders": ad_orders,
            "promoted_ad_orders": promoted_orders,
            "halo_ad_orders": halo_orders,
            "total_orders": total_orders,
            "CPC": round(cpc, 4) if cpc else 0,
            "CTR": round(ctr, 4) if ctr else 0,
            "CVR": round(cvr, 4) if cvr else 0,
        },
        "wasted_spend_terms": wasted_terms[:5],
        "broken_conversion_terms": broken_terms[:5],
        "lost_winner_terms": winners[:5],
        "evidence": [
            f"曝光 {impressions:.0f}",
            f"点击 {clicks:.0f}",
            f"广告单 {ad_orders:.0f}",
            f"推广商品单 {promoted_orders:.0f}",
            f"光环单 {halo_orders:.0f}",
            f"总单 {total_orders:.0f}",
            f"花费 {spend:.2f}",
        ],
    }


def _conversion_layer(product: dict[str, object], frontend: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    missing: list[str] = []
    if not frontend:
        missing.append("frontend_product_page")
    price = frontend.get("frontend_price") or frontend.get("price") or product.get("frontend_price")
    coupon_raw = frontend.get("frontend_coupon") or frontend.get("coupon") or product.get("coupon")
    coupon = parse_coupon(coupon_raw, price)
    constraints = frontend_constraints(frontend, _product_name(product))
    if coupon.get("coupon_confidence") == "low" and coupon.get("coupon_raw"):
        missing.append("coupon_final_price")
    if not _has_recent_frontend(frontend):
        missing.append("fresh_frontend_data")
    buy_box = _clean(frontend.get("frontend_buy_box") or frontend.get("buy_box"))
    rating = _clean(frontend.get("frontend_rating") or frontend.get("rating"))
    reviews = _clean(frontend.get("frontend_reviews") or frontend.get("reviews"))
    reasons = list(constraints.get("frontend_blocking_reasons") or [])
    status = "blocked" if constraints.get("blocked_ad_actions") else ("unknown" if missing else "ok")
    return {
        "conversion_status": status,
        "frontend_blocking_reasons": reasons,
        "listing_trust_gap": "、".join(reason for reason in reasons if "评分" in reason or "评论" in reason) or "",
        "coupon_confidence": coupon.get("coupon_confidence"),
        "coupon": coupon,
        "buy_box_status": buy_box or "待确认",
        "price": price or "",
        "rating": rating,
        "reviews": reviews,
        "evidence": [item for item in [f"售价 {price}" if price else "", f"Coupon {coupon.get('coupon_raw')}" if coupon.get("coupon_raw") else "", f"评分 {rating}" if rating else "", f"评论 {reviews}" if reviews else "", f"Buy Box {buy_box}" if buy_box else ""] if item],
    }, missing


def _competition_layer(frontend: dict[str, object], product_name: str) -> tuple[dict[str, object], list[str]]:
    missing: list[str] = []
    raw = frontend.get("frontend_competitors")
    competitors = raw if isinstance(raw, list) else []
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            competitors = [row for row in parsed if isinstance(row, dict)]
    if not competitors:
        missing.append("competitor_search_top3")
    comp = competitor_comparability(frontend, product_name)
    prices = [_clean(row.get("price")) for row in competitors[:3] if isinstance(row, dict) and _clean(row.get("price"))]
    ratings = [_clean(row.get("rating")) for row in competitors[:3] if isinstance(row, dict) and _clean(row.get("rating"))]
    reviews = [_clean(row.get("reviews")) for row in competitors[:3] if isinstance(row, dict) and _clean(row.get("reviews"))]
    return {
        **comp,
        "competitor_advantages": {
            "prices": prices,
            "ratings": ratings,
            "reviews": reviews,
        },
        "price_position": "仅参考" if comp.get("comparable_competitor_count", 0) < 2 else "可比较",
        "review_position": "仅参考" if comp.get("comparable_competitor_count", 0) < 2 else "可比较",
        "rating_position": "仅参考" if comp.get("comparable_competitor_count", 0) < 2 else "可比较",
        "evidence": [f"前三竞品 {len(competitors[:3])} 个", f"可比竞品 {comp.get('comparable_competitor_count', 0)} 个"],
    }, missing


def _inventory_layer(product: dict[str, object], inventory: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    missing: list[str] = []
    level = _clean(inventory.get("stock_risk_level"))
    current = inventory.get("current_inventory")
    if not _clean(current):
        missing.append("fba_inventory")
    can_scale = level not in {"OUT_OF_STOCK", "LOW_STOCK", "RESTOCK_RECOVERY", "UNKNOWN"}
    return {
        "inventory_status": level or "UNKNOWN",
        "inventory_constraint": _clean(inventory.get("stock_risk_reason")) or ("缺少 FBA 库存" if missing else ""),
        "can_scale": can_scale,
        "current_inventory": current if _clean(current) else "N/A",
        "days_of_cover": inventory.get("days_of_cover") if _clean(inventory.get("days_of_cover")) else "N/A",
        "total_lead_time_days": inventory.get("total_lead_time_days") or "",
        "reason": _clean(inventory.get("replenishment_advice") or inventory.get("stock_risk_reason")),
    }, missing


def _profit_layer(product: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    target_acos = _metric(product, "target_acos", "目标 ACOS")
    profit = _metric(product, "profit_before_ads_per_unit", "广告前利润/件")
    acos = _metric(product, "ACOS", "acos")
    cpc = _metric(product, "CPC")
    missing: list[str] = []
    if target_acos <= 0:
        missing.append("target_acos")
    if profit <= 0:
        missing.append("profit_boundary")
    status = "unknown" if missing else ("tight" if acos and target_acos and acos > target_acos else "ok")
    return {
        "profit_status": status,
        "max_safe_acos": target_acos if target_acos else "待确认",
        "bid_budget_safety": "利润边界待确认" if missing else ("当前 ACOS 超目标，不能加预算" if status == "tight" else "可按目标 ACOS 小步测试"),
        "CPC": cpc,
        "reason": "成本/目标 ACOS 缺失，不强推加预算。" if missing else "",
    }, missing


def _history_layer(product: dict[str, object], runtime_policy: dict[str, object] | None, final_decisions: list[dict[str, object]]) -> dict[str, object]:
    runtime_policy = runtime_policy or {}
    key = product_key_text(product)
    memory_rows = [
        row for row in runtime_policy.get("keyword_strategy_memory", []) or []
        if isinstance(row, dict) and product_key_text(row) == key
    ]
    cooldowns = []
    for row in list((runtime_policy.get("action_cooldowns", {}) or {}).values()) + list((runtime_policy.get("product_cooldowns", {}) or {}).values()):
        if isinstance(row, dict) and product_key_text(row) == key:
            cooldowns.append(row)
    effective = [row for row in memory_rows if _num(row.get("effectiveness_score")) > 0]
    failed = [row for row in memory_rows if _num(row.get("effectiveness_score")) < 0]
    final = next((row for row in final_decisions if isinstance(row, dict) and product_key_text(row) == key), {})
    blocked = list(final.get("today_blocked_actions") or [])
    return {
        "active_cooldowns": cooldowns[:5],
        "effective_past_actions": effective[:5],
        "failed_past_actions": failed[:5],
        "reusable_success_patterns": [row.get("recommended_future_policy") for row in effective[:5] if row.get("recommended_future_policy")],
        "blocked_by_memory": blocked,
        "evidence": [final.get("keyword_memory_summary") or "", final.get("decision_reason") or ""],
    }


def _frontend_root_cause(
    *,
    traffic: dict[str, object],
    conversion: dict[str, object],
    competition: dict[str, object],
    data_missing: list[str],
) -> str:
    missing = set(data_missing)
    metrics = traffic.get("metrics") if isinstance(traffic.get("metrics"), dict) else {}
    traffic_status = _clean(traffic.get("traffic_status"))
    impressions = _num(metrics.get("impressions"))
    clicks = _num(metrics.get("clicks"))
    ad_orders = _num(metrics.get("ad_orders"))
    promoted_orders = _num(metrics.get("promoted_ad_orders"))
    halo_orders = _num(metrics.get("halo_ad_orders"))
    reasons = [_clean(reason) for reason in conversion.get("frontend_blocking_reasons") or [] if _clean(reason)]
    buy_box = _clean(conversion.get("buy_box_status"))
    coupon = conversion.get("coupon") if isinstance(conversion.get("coupon"), dict) else {}
    coupon_raw = _clean(coupon.get("coupon_raw"))
    comparable_count = int(_num(competition.get("comparable_competitor_count")))

    if traffic_status in {"traffic_absent", "sample_low"} or (impressions <= 10 and clicks <= 2):
        return "广告曝光/点击样本不足，前台弱项只能作为约束，不能作为唯一主因。"
    if ad_orders > 0 and promoted_orders <= 0 and halo_orders > 0:
        return "广告有点击归因订单，但本 SKU 未成交，仅有光环成交；不能按本 SKU 广告有效处理。"
    if halo_orders > 0 and promoted_orders < ad_orders:
        return "广告主要带动光环成交，需要检查该广告是否真的在推目标 SKU。"
    if traffic_status == "click_weak":
        return "曝光有但点击弱，先拆 CTR、主图、价格和广告词相关性；前台不是唯一主因。"
    if "frontend_product_page" in missing or "fresh_frontend_data" in missing:
        if clicks and ad_orders <= 0:
            return f"近14天约 {clicks:.0f} 次点击但无广告单，缺少最新前台证据，先补商品页读取。"
        return "缺少最新前台证据，不能直接判断 Listing 或继续放量。"
    if any("Buy Box" in reason or "购买按钮" in reason for reason in reasons):
        return "购买按钮/Buy Box 不稳会直接截断转化，先处理购买入口。"
    if any("Coupon" in reason for reason in reasons) or ("coupon_final_price" in missing and coupon_raw):
        return "Coupon 有展示但到手价未读准，不能把 Coupon 当作转化优势。"
    if any("评分" in reason or "评论" in reason for reason in reasons):
        return "信任差距是主要瓶颈：评分/评论弱于竞品，点击进来后更容易流失。"
    if any("价格" in reason for reason in reasons):
        return "价格带处于弱势，当前点击需要先验证到手价和竞品可比性。"
    if comparable_count < 2:
        return "核心词前三可比竞品不足，价格/评分结论只能参考，先保守跑。"
    if clicks and ad_orders <= 0:
        return f"近14天约 {clicks:.0f} 次点击但无广告单，问题更像点击后承接而不是曝光不足。"
    if buy_box and buy_box not in {"识别到购买按钮", "有 Buy Box", "有Buy Box"}:
        return "购买入口状态不够明确，先保守跑，避免无效放量。"
    return "广告和前台都存在约束，当前更适合保守承接而不是继续放量。"


def _battle_decision(
    *,
    traffic: dict[str, object],
    conversion: dict[str, object],
    competition: dict[str, object],
    inventory: dict[str, object],
    profit: dict[str, object],
    history: dict[str, object],
    data_missing: list[str],
) -> tuple[str, str, list[str], list[str], str, str, str]:
    blocked: set[str] = set()
    allowed: set[str] = {"observe"}
    review = "3天看点击、CVR、广告单；7天看总单和 ACOS 是否恢复。"
    confidence = "medium"

    if "fba_inventory" in data_missing and traffic.get("traffic_status") == "sample_low":
        return (
            "DATA_INSUFFICIENT",
            "样本和库存边界不足，先补数据，不判断广告效果。",
            ["bid_up", "budget_up", "broad_scale"],
            ["observe"],
            "先确认 FBA 库存、成本和前台，再判断。",
            "补齐库存/成本/前台数据后重新跑报告。",
            "medium",
        )

    inventory_status = _clean(inventory.get("inventory_status"))
    if inventory_status == "OUT_OF_STOCK":
        return (
            "INVENTORY_BLOCKED",
            "库存断货，广告只控损，不把无单归因为 Listing。",
            ["bid_up", "budget_up", "broad_scale", "create_exact"],
            ["pause", "bid_down", "observe"],
            "暂停扩量，只保留必要品牌/精准低预算。",
            "补货恢复后 3天看曝光点击，7天看订单恢复。",
            "high",
        )
    if inventory_status in {"LOW_STOCK", "RESTOCK_RECOVERY"}:
        return (
            "CONSERVATIVE_RUN",
            "库存低或刚到货恢复期，不适合大幅放量。",
            ["bid_up", "budget_up", "broad_scale"],
            ["create_exact_low_budget", "bid_down", "negative_exact", "observe"],
            "小预算保留高相关精准词，先不推大词放量。",
            review,
            "high",
        )

    if history.get("active_cooldowns"):
        return (
            "HOLD_AND_REVIEW",
            "历史动作仍在冷却期，不重复操作。",
            ["bid_up", "bid_down", "budget_up", "broad_scale", "pause"],
            ["observe"],
            "不重复动广告，等待复盘窗口。",
            "未满3天不判断；3-6天看3天复盘；7天形成结论。",
            "high",
        )

    conversion_status = _clean(conversion.get("conversion_status"))
    coupon_confidence = _clean(conversion.get("coupon_confidence"))
    comparable_count = int(_num(competition.get("comparable_competitor_count")))
    if conversion_status == "blocked" or coupon_confidence == "low":
        missing = set(data_missing)
        if "frontend_product_page" in missing or "fresh_frontend_data" in missing:
            today_action = "补前台证据后再判断；广告先不加预算。"
        elif "coupon_final_price" in missing:
            today_action = "前台已查，Coupon 到手价待确认；广告先保守跑，不加预算。"
        elif "competitor_search_top3" in missing or comparable_count < 2:
            today_action = "前台已查，竞品可比性不足；广告先保守跑，不加预算。"
        else:
            today_action = "前台已查，按价格/Coupon/评分评论弱项保守跑；不加预算，只保留高相关精准词和必要降竞价/否词。"
        return (
            "FRONTEND_FIX_FIRST",
            _frontend_root_cause(
                traffic=traffic,
                conversion=conversion,
                competition=competition,
                data_missing=data_missing,
            ),
            ["bid_up", "budget_up", "broad_scale"],
            ["bid_down", "negative_exact", "observe"],
            today_action,
            review,
            "medium",
        )
    if comparable_count and comparable_count < 2:
        blocked.update({"bid_up", "budget_up", "broad_scale"})

    if history.get("failed_past_actions"):
        return (
            "CONSERVATIVE_RUN",
            "历史同类动作暂未改善，今天不继续加价或扩量。",
            ["bid_up", "budget_up", "broad_scale"],
            ["bid_down", "negative_exact", "observe"],
            "收紧无效流量，保留高相关长尾。",
            review,
            "medium",
        )

    if traffic.get("traffic_status") == "conversion_broken":
        return (
            "CONSERVATIVE_RUN",
            "点击没少但广告单断，先控大词和无效流量。",
            ["bid_up", "budget_up", "broad_scale"],
            ["bid_down", "negative_exact", "create_exact_low_budget", "observe"],
            "收紧大词/泛词，只保留高相关长尾和少量复测。",
            review,
            "medium",
        )

    if history.get("effective_past_actions"):
        return (
            "SMALL_EXACT_TEST",
            "历史有效动作可作为模板，但今天不重复加价。",
            ["budget_up", "broad_scale"],
            ["create_exact_low_budget", "observe"],
            "保留已有效词，少量精准测试，不扩大泛词。",
            review,
            "medium",
        )

    if profit.get("profit_status") == "unknown":
        return (
            "HOLD_AND_REVIEW",
            "利润边界待确认，不强推广告动作。",
            ["bid_up", "budget_up", "broad_scale"],
            ["observe", "bid_down"],
            "先核对成本/目标 ACOS，再决定是否放量。",
            "补齐利润边界后复查。",
            "medium",
        )

    return (
        "EXECUTE_AD_ACTION",
        "数据完整且未命中库存/前台/历史拦截，可执行轻量广告动作。",
        sorted(blocked),
        sorted(allowed | {"bid_down", "negative_exact", "create_exact_low_budget"}),
        "按搜索词明细执行轻量动作，不做全账户加预算。",
        review,
        confidence,
    )


def build_product_battle_diagnoses(
    analysis_payload: dict,
    report_view: dict | None = None,
    *,
    diagnosis_level: str = "quick",
    target: dict[str, object] | None = None,
    output_dir: Path | None = None,
) -> list[dict[str, object]]:
    runtime_policy = (report_view or {}).get("runtime_policy") if isinstance(report_view, dict) else None
    if not isinstance(runtime_policy, dict):
        runtime_policy = {}
    marketplace = _clean(analysis_payload.get("target_marketplace")).upper()
    products = _collect_candidate_products(analysis_payload, report_view, target=target)
    inventory_lookup = _lookup((report_view or {}).get("inventory_replenishment_rows", []) if report_view else analysis_payload.get("inventory_replenishment", {}).get("rows", []))
    frontend_lookup = _lookup((report_view or {}).get("frontend_check_queue_rows", []) if report_view else [])
    final_decisions = (report_view or {}).get("product_final_decision_rows", []) if report_view else []
    search_rows = []
    if report_view:
        search_rows.extend(report_view.get("search_term_processing_queue_rows", []) or [])
        search_rows.extend(report_view.get("scale_keyword_rows", []) or [])
    rows: list[dict[str, object]] = []
    now = datetime.now().replace(microsecond=0).isoformat()
    for product in products:
        product.setdefault("marketplace", marketplace)
        frontend = _lookup_one(frontend_lookup, product)
        inventory = _lookup_one(inventory_lookup, product)
        demand, demand_missing = _demand_layer(analysis_payload, product)
        traffic = _traffic_layer(product, search_rows)
        conversion, conversion_missing = _conversion_layer(product, frontend)
        competition, competition_missing = _competition_layer(frontend, _product_name(product))
        inventory_layer, inventory_missing = _inventory_layer(product, inventory)
        profit, profit_missing = _profit_layer(product)
        history = _history_layer(product, runtime_policy, final_decisions)
        data_missing = sorted(set(demand_missing + conversion_missing + competition_missing + inventory_missing + profit_missing))
        data_used = [
            "ads_7_14_30d",
            "erp_sales",
            "inventory_replenishment" if inventory else "",
            "frontend_cache" if frontend else "",
            "keyword_memory" if history.get("effective_past_actions") or history.get("failed_past_actions") else "",
        ]
        decision, root_cause, blocked, allowed, today_action, review_plan, confidence = _battle_decision(
            traffic=traffic,
            conversion=conversion,
            competition=competition,
            inventory=inventory_layer,
            profit=profit,
            history=history,
            data_missing=data_missing,
        )
        status = "success"
        if data_missing:
            status = "partial"
        if frontend and _clean(frontend.get("frontend_check_status")).startswith("沿用"):
            status = "cached"
        if not frontend and diagnosis_level == "battle":
            status = "partial"
        secondary = []
        if conversion.get("frontend_blocking_reasons"):
            secondary.extend(conversion.get("frontend_blocking_reasons")[:3])
        if traffic.get("main_ad_problem"):
            secondary.append(str(traffic.get("main_ad_problem")))
        evidence = [
            *traffic.get("evidence", []),
            *conversion.get("evidence", [])[:4],
            *competition.get("evidence", []),
        ]
        marketplace_key, sku, asin = _product_key(product)
        rows.append(
            {
                "marketplace": marketplace_key,
                "sku": sku,
                "asin": asin,
                "product_name": _product_name(product),
                "diagnosis_level": diagnosis_level if diagnosis_level in {"quick", "battle"} else "quick",
                "diagnosis_status": status,
                "data_used": [item for item in data_used if item],
                "data_missing": data_missing,
                "main_root_cause": root_cause,
                "secondary_causes": [item for item in secondary if item][:5],
                "demand_layer": demand,
                "traffic_layer": traffic,
                "conversion_layer": conversion,
                "competition_layer": competition,
                "inventory_layer": inventory_layer,
                "profit_layer": profit,
                "history_learning_layer": history,
                "allowed_actions": allowed,
                "blocked_actions": blocked,
                "today_action": today_action,
                "review_plan": review_plan,
                "confidence": confidence,
                "final_battle_decision": decision if decision in BATTLE_DECISIONS else "DATA_INSUFFICIENT",
                "final_battle_decision_label": BATTLE_LABELS.get(decision, decision),
                "evidence_summary": "；".join(str(item) for item in evidence if item)[:320],
                "last_updated": now,
            }
        )
    return rows


def battle_lookup(rows: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {product_key_text(row): row for row in rows if isinstance(row, dict) and product_key_text(row) != "||"}


def apply_battle_to_rows(rows: Iterable[dict[str, object]], battle_rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    lookup = battle_lookup(battle_rows)
    updated: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        battle = lookup.get(product_key_text(item))
        if battle:
            item["battle_decision"] = battle.get("final_battle_decision")
            item["battle_decision_label"] = battle.get("final_battle_decision_label")
            item["battle_main_root_cause"] = battle.get("main_root_cause")
            item["battle_today_action"] = battle.get("today_action")
            item["battle_blocked_actions"] = " / ".join(str(action) for action in battle.get("blocked_actions") or [])
            item["battle_review_plan"] = battle.get("review_plan")
            decision = _clean(battle.get("final_battle_decision"))
            if decision not in {"EXECUTE_AD_ACTION", "SMALL_EXACT_TEST"} and item.get("copy_action_line"):
                item["copy_action_line"] = "建议观察"
        updated.append(item)
    return updated


def write_product_battle_diagnosis(output_dir: Path, report_date: str, rows: Iterable[dict[str, object]]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    date_token = report_date.replace("-", "")
    rows_list = [row for row in rows if isinstance(row, dict)]
    json_path = output_dir / f"product_battle_diagnosis_{date_token}.json"
    md_path = output_dir / "product_battle_diagnosis.md"
    json_path.write_text(json.dumps(rows_list, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 产品作战诊断", ""]
    for row in rows_list:
        lines.append(
            f"- {row.get('marketplace') or ''}｜{row.get('product_name') or row.get('asin') or ''}："
            f"{row.get('final_battle_decision_label') or row.get('final_battle_decision')}；"
            f"主因：{row.get('main_root_cause') or ''}；今天做：{row.get('today_action') or ''}"
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path


def battle_summary(rows: Iterable[dict[str, object]]) -> dict[str, object]:
    rows_list = [row for row in rows if isinstance(row, dict)]
    counts = Counter(_clean(row.get("final_battle_decision")) for row in rows_list)
    root_counts = Counter(_clean(row.get("main_root_cause"))[:80] for row in rows_list if _clean(row.get("main_root_cause")))
    return {
        "battle_diagnosis_summary": dict(counts),
        "battle_root_cause_counts": dict(root_counts.most_common(10)),
        "battle_blocked_actions": [
            {
                "marketplace": row.get("marketplace"),
                "product_name": row.get("product_name"),
                "asin": row.get("asin"),
                "blocked_actions": row.get("blocked_actions"),
                "reason": row.get("main_root_cause"),
            }
            for row in rows_list
            if row.get("blocked_actions")
        ][:50],
        "battle_allowed_actions": [
            {
                "marketplace": row.get("marketplace"),
                "product_name": row.get("product_name"),
                "asin": row.get("asin"),
                "allowed_actions": row.get("allowed_actions"),
                "decision": row.get("final_battle_decision"),
            }
            for row in rows_list
        ][:50],
        "battle_data_missing": [
            {
                "marketplace": row.get("marketplace"),
                "product_name": row.get("product_name"),
                "asin": row.get("asin"),
                "data_missing": row.get("data_missing"),
            }
            for row in rows_list
            if row.get("data_missing")
        ][:50],
        "battle_diagnosis_failures": [row for row in rows_list if row.get("diagnosis_status") == "failed"],
        "battle_reused_success_patterns": [
            {
                "marketplace": row.get("marketplace"),
                "product_name": row.get("product_name"),
                "asin": row.get("asin"),
                "patterns": (row.get("history_learning_layer") or {}).get("reusable_success_patterns"),
            }
            for row in rows_list
            if (row.get("history_learning_layer") or {}).get("reusable_success_patterns")
        ][:50],
    }


def update_self_optimization_log(output_dir: Path, report_date: str, rows: Iterable[dict[str, object]]) -> None:
    date_token = report_date.replace("-", "")
    path = output_dir / f"self_optimization_log_{date_token}.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    payload.update(battle_summary(rows))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
