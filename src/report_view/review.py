from __future__ import annotations

import json
from typing import Any


def _build_yesterday_attribution_rows(shared: Any, analysis_payload: dict, status: dict[str, object]) -> list[dict[str, str]]:
    marketplace = shared._infer_marketplace(analysis_payload)
    rows_1d = shared._product_rows_for_window(analysis_payload, "1d")
    rows_7d = shared._product_rows_for_window(analysis_payload, "7d")
    rows_14d = shared._product_rows_for_window(analysis_payload, "14d")
    by_key_7d = {
        (str(row.get("marketplace") or marketplace), str(row.get("sku") or ""), str(row.get("asin") or "")): row
        for row in rows_7d
    }
    by_key_14d = {
        (str(row.get("marketplace") or marketplace), str(row.get("sku") or ""), str(row.get("asin") or "")): row
        for row in rows_14d
    }
    if status.get("analysis_status") == "数据不足，仅观察":
        return [
            {
                "marketplace": marketplace,
                "product_name": "站点整体",
                "sku": "N/A",
                "asin": "N/A",
                "attribution_type": "数据不足",
                "judgement": f"{marketplace} ERP/广告共同窗口不足，昨日少单暂不做细分归因。",
                "evidence": str(status.get("issue_summary") or "数据不足"),
                "next_step": "先补齐至少 7 天 ERP/广告覆盖，再判断是流量、转化还是归因问题。",
                "priority": "P1",
            }
        ]

    total_orders_1d = shared._metric_sum(rows_1d, "total_orders")
    ad_orders_1d = shared._metric_sum(rows_1d, "ad_orders")
    clicks_1d = shared._metric_sum(rows_1d, "ad_clicks")
    impressions_1d = shared._metric_sum(rows_1d, "ad_impressions")
    spend_1d = shared._metric_sum(rows_1d, "ad_spend")
    total_orders_7d_avg = shared._metric_sum(rows_7d, "total_orders") / 7 if rows_7d else 0
    ad_orders_7d_avg = shared._metric_sum(rows_7d, "ad_orders") / 7 if rows_7d else 0
    clicks_7d_avg = shared._metric_sum(rows_7d, "ad_clicks") / 7 if rows_7d else 0
    impressions_7d_avg = shared._metric_sum(rows_7d, "ad_impressions") / 7 if rows_7d else 0

    if clicks_7d_avg and clicks_1d < clicks_7d_avg * 0.6:
        site_type = "流量下降"
        site_text = f"{marketplace} 昨日少单更像广告流量下降，不是直接判断 Listing 崩。"
        next_step = "先查预算是否用完、广告是否被限流、核心活动展示是否下降。"
    elif clicks_1d >= 8 and ad_orders_1d == 0:
        site_type = "点击后不转化"
        site_text = f"{marketplace} 昨日有点击但广告单弱，优先查价格/Coupon/配送/竞品。"
        next_step = "广告端先控贵词，不急着加预算；同时核对前台价格和配送。"
    elif total_orders_1d > 0 and ad_orders_1d == 0 and clicks_1d >= 3:
        site_type = "广告归因弱"
        site_text = f"{marketplace} 昨日仍有总单但广告单少，优先查广告归因和搜索词。"
        next_step = "看出单是否来自自然；保留有效广告，压低无转化词/ASIN。"
    elif total_orders_7d_avg and total_orders_1d < total_orders_7d_avg * 0.65:
        site_type = "正常波动"
        site_text = f"{marketplace} 昨日订单低于近7天均值，但暂未看到单一强原因。"
        next_step = "先看 2 天连续性，再决定是否调整广告或页面。"
    else:
        site_type = "正常波动"
        site_text = f"{marketplace} 昨日没有明显异常，按正常波动处理。"
        next_step = "不为了操作而操作，继续跟踪订单和广告效率。"

    result_rows = [
        {
            "marketplace": marketplace,
            "product_name": "站点整体",
            "sku": "N/A",
            "asin": "N/A",
            "attribution_type": site_type,
            "judgement": site_text,
            "evidence": (
                f"昨日总单 {shared._format_count(total_orders_1d)}，广告单 {shared._format_count(ad_orders_1d)}，"
                f"点击 {shared._format_count(clicks_1d)}，展示 {shared._format_count(impressions_1d)}，花费 {shared._money(spend_1d, marketplace)}；"
                f"近7天日均总单 {shared._format_count(total_orders_7d_avg)}，日均广告单 {shared._format_count(ad_orders_7d_avg)}，日均点击 {shared._format_count(clicks_7d_avg)}，日均展示 {shared._format_count(impressions_7d_avg)}"
            ),
            "next_step": next_step,
            "priority": "P0" if site_type in {"流量下降", "点击后不转化"} else "P1",
        }
    ]

    scored: list[tuple[float, dict[str, str]]] = []
    for row in rows_1d:
        key = (str(row.get("marketplace") or marketplace), str(row.get("sku") or ""), str(row.get("asin") or ""))
        row7 = by_key_7d.get(key, {})
        row14 = by_key_14d.get(key, {})
        clicks = shared._row_metric(row, "ad_clicks")
        spend = shared._row_metric(row, "ad_spend")
        ad_orders = shared._row_metric(row, "ad_orders")
        total_orders = shared._row_metric(row, "total_orders")
        avg_clicks = shared._row_metric(row7, "ad_clicks") / 7 if row7 else 0
        avg_orders = shared._row_metric(row7, "total_orders") / 7 if row7 else 0
        orders14 = shared._row_metric(row14, "total_orders")
        ad_orders14 = shared._row_metric(row14, "ad_orders")
        profit = shared._to_float(row.get("profit_before_ads_per_unit"))
        if profit is not None and profit <= 0:
            product_type = "成本/利润限制"
            judgement = f"{marketplace} {row.get('product_name') or row.get('sku')} 利润边界不清，少单不应先靠加广告解决。"
            next_step = "先核对采购成本、头程、FBA、售价；利润未确认前不放量。"
            score = 6
        elif clicks >= 5 and ad_orders == 0 and (ad_orders14 > 0 or orders14 > 0):
            product_type = "点击后不转化"
            judgement = f"{marketplace} {row.get('product_name') or row.get('sku')} 昨日有点击但广告没单，优先查价格/Coupon/配送/竞品。"
            next_step = "核心词不直接否；相关贵词先降竞价，补前台和竞品截图判断。"
            score = clicks + spend
        elif total_orders > 0 and ad_orders == 0 and clicks >= 3:
            product_type = "广告归因弱"
            judgement = f"{marketplace} {row.get('product_name') or row.get('sku')} 仍有总单但广告单弱，像归因或投放结构问题。"
            next_step = "查出单词和花费词是否错位，保留能出单词，压低无效 ASIN/泛词。"
            score = clicks + total_orders * 2
        elif avg_clicks and clicks < avg_clicks * 0.5 and avg_orders and total_orders < avg_orders * 0.7:
            product_type = "流量下降"
            judgement = f"{marketplace} {row.get('product_name') or row.get('sku')} 昨日点击低于近7天均值，少单更像流量不足。"
            next_step = "先查预算、广告状态、核心词展示，不急着改 Listing。"
            score = avg_clicks - clicks
        else:
            continue
        evidence = (
            f"昨日点击 {shared._format_count(clicks)}，广告单 {shared._format_count(ad_orders)}，总单 {shared._format_count(total_orders)}，花费 {shared._money(spend, marketplace)}；"
            f"近7天日均点击 {shared._format_count(avg_clicks)}，日均总单 {shared._format_count(avg_orders)}"
        )
        scored.append(
            (
                score,
                {
                    "marketplace": marketplace,
                    "product_name": str(row.get("product_name") or row.get("sku") or "N/A"),
                    "sku": str(row.get("sku") or "N/A"),
                    "asin": str(row.get("asin") or "N/A"),
                    "attribution_type": product_type,
                    "judgement": judgement,
                    "evidence": evidence,
                    "next_step": next_step,
                    "priority": "P0" if product_type in {"点击后不转化", "流量下降"} else "P1",
                },
            )
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    result_rows.extend(row for _, row in scored[:3])
    return result_rows


def _compact_executed_action(shared: Any, action: str) -> str:
    text = str(action or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    if "加价" in text:
        parts.append("已执行加价")
    if "降竞价" in text or "降价" in text:
        parts.append("已执行降竞价")
    if "否词" in text or "否定" in text:
        parts.append("已执行否词")
    if "Listing" in text or "暂时不加广告预算" in text:
        parts.append("Listing待确认：广告端保守")
    if "观察" in text and not parts:
        parts.append("观察留档")
    if parts:
        return "；".join(dict.fromkeys(parts))
    return text[:48] + ("…" if len(text) > 48 else "")


def _latest_action_review_rows(shared: Any, marketplace: str | None = None, limit: int = 50) -> list[dict[str, str]]:
    paths = sorted(shared.OUTPUT_DIR.glob("action_review_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        return []
    try:
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    marketplace_filter = str(marketplace or "").strip().upper()
    if marketplace_filter and marketplace_filter != "ALL":
        rows = [row for row in rows if str(row.get("marketplace") or "").strip().upper() == marketplace_filter]
    normalized: list[dict[str, str]] = []
    for row in rows[:limit]:
        days = row.get("days_since_execution")
        action_detail = _compact_executed_action(shared, str(row.get("action_detail") or row.get("action_type") or ""))
        normalized.append(
            {
                "marketplace": str(row.get("marketplace") or ""),
                "sku": str(row.get("sku") or ""),
                "asin": str(row.get("asin") or ""),
                "product_name": str(row.get("product_name") or ""),
                "executed_action": action_detail,
                "executed_at": str(row.get("executed_at") or ""),
                "review_window": "7天后复盘" if shared._to_float(days) is not None and (shared._to_float(days) or 0) >= 7 else ("3天后复盘" if shared._to_float(days) is not None and (shared._to_float(days) or 0) >= 3 else "未满3天"),
                "effect_metrics": str(row.get("effect_evidence") or row.get("review_status") or ""),
                "judgement": str(row.get("outcome") or "数据不足"),
                "next_step": str(row.get("rule_adjustment") or "继续观察，等待足够样本。"),
                "days_since_execution": str(row.get("days_since_execution") or ""),
            }
        )
    return normalized


def _latest_keyword_action_review_rows(shared: Any, marketplace: str | None = None, limit: int = 50) -> list[dict[str, str]]:
    paths = sorted(shared.OUTPUT_DIR.glob("keyword_action_review_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        return []
    try:
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    marketplace_filter = str(marketplace or "").strip().upper()
    if marketplace_filter and marketplace_filter != "ALL":
        rows = [row for row in rows if str(row.get("marketplace") or "").strip().upper() == marketplace_filter]
    normalized: list[dict[str, str]] = []

    def display_value(value: object) -> str:
        return "" if value is None else str(value)

    for row in rows[:limit]:
        normalized.append(
            {
                "marketplace": str(row.get("marketplace") or ""),
                "sku": str(row.get("sku") or ""),
                "asin": str(row.get("asin") or ""),
                "product_name": str(row.get("product_name") or ""),
                "search_term_or_target": str(row.get("search_term_or_target") or ""),
                "executed_action": str(row.get("action_detail") or ""),
                "executed_at": str(row.get("executed_at") or ""),
                "confirmed_note": str(row.get("confirmed_note") or ""),
                "report_date": str(row.get("report_date") or ""),
                "review_date": str(row.get("review_date") or ""),
                "review_status": str(row.get("review_status") or ""),
                "normalized_action": str(row.get("normalized_action") or ""),
                "action_detail": str(row.get("action_detail") or ""),
                "cooldown_status": str(row.get("cooldown_status") or ""),
                "review_phase": str(row.get("review_phase") or ""),
                "review_outcome": str(row.get("review_outcome") or ""),
                "days_since_execution": str(row.get("days_since_execution") or ""),
                "action_scope": str(row.get("action_scope") or ""),
                "action_id": str(row.get("action_id") or ""),
                "review_window": str(row.get("review_window") or ""),
                "effect_metrics": str(row.get("effect_evidence") or row.get("review_status") or ""),
                "judgement": str(row.get("outcome") or "数据不足"),
                "next_step": str(row.get("rule_adjustment") or "继续观察，等待足够样本。"),
                "days_since_execution": str(row.get("days_since_execution") or ""),
                "current_7d_clicks": display_value(row.get("current_7d_clicks")),
                "current_7d_spend": display_value(row.get("current_7d_spend")),
                "current_7d_ad_orders": display_value(row.get("current_7d_ad_orders")),
                "current_7d_ad_sales": display_value(row.get("current_7d_ad_sales")),
                "current_7d_promoted_ad_orders": display_value(row.get("current_7d_promoted_ad_orders")),
                "current_7d_promoted_ad_sales": display_value(row.get("current_7d_promoted_ad_sales")),
                "current_7d_halo_ad_orders": display_value(row.get("current_7d_halo_ad_orders")),
                "current_7d_halo_ad_sales": display_value(row.get("current_7d_halo_ad_sales")),
                "current_7d_acos": display_value(row.get("current_7d_acos")),
                "current_14d_clicks": display_value(row.get("current_14d_clicks")),
                "current_14d_spend": display_value(row.get("current_14d_spend")),
                "current_14d_ad_orders": display_value(row.get("current_14d_ad_orders")),
                "current_14d_ad_sales": display_value(row.get("current_14d_ad_sales")),
                "current_14d_promoted_ad_orders": display_value(row.get("current_14d_promoted_ad_orders")),
                "current_14d_promoted_ad_sales": display_value(row.get("current_14d_promoted_ad_sales")),
                "current_14d_halo_ad_orders": display_value(row.get("current_14d_halo_ad_orders")),
                "current_14d_halo_ad_sales": display_value(row.get("current_14d_halo_ad_sales")),
                "current_14d_acos": display_value(row.get("current_14d_acos")),
                "attribution_effect_status": display_value(row.get("attribution_effect_status")),
                "attribution_effect_note": display_value(row.get("attribution_effect_note")),
                "promoted_conversion_improved": display_value(row.get("promoted_conversion_improved")),
                "halo_only_conversion": display_value(row.get("halo_only_conversion")),
                "target_sku_not_converted": display_value(row.get("target_sku_not_converted")),
            }
        )
    return normalized


def _build_tomorrow_review_list(
    shared: Any,
    analysis_payload: dict,
    today_queue: list[dict[str, str]],
    status: dict[str, object],
    blocked_keys: set[tuple[str, str, str]] | None = None,
) -> list[dict[str, str]]:
    if not status.get("strong_recommendation_allowed"):
        return []
    today_keys = {shared._task_key(row) for row in today_queue}
    blocked_keys = blocked_keys or set()
    executed_cooldown_keys = {
        shared._task_key(row)
        for row in today_queue
        if str(row.get("confirmed_status") or "") == "已执行"
        or "冷却" in str(row.get("learning_status") or row.get("review_reason") or "")
    }
    marketplace = shared._infer_marketplace(analysis_payload)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in analysis_payload.get(shared.RECOMMENDATION_KEY, []):
        evidence = item.get("evidence", {})
        clicks = shared._to_float(evidence.get("clicks")) or 0
        key = (str(evidence.get("marketplace") or marketplace), str(evidence.get("sku") or item.get("target") or ""), str(evidence.get("asin") or ""))
        if key in today_keys or key in blocked_keys or key in seen or clicks <= 2:
            continue
        review_reason = ""
        tomorrow_check = ""
        action = str(item.get("action") or "")
        if item.get("category") == "搜索词" and 3 <= clicks <= 5 and "否词" not in action:
            review_reason = "3-5点击无单，未达到强动作阈值"
            tomorrow_check = "复查是否新增点击、花费或订单；未改善再降竞价"
        elif "否词" in action or "暂停" in action:
            continue
        elif "自然有单但广告无流量" in action:
            review_reason = "自然有单但广告无流量"
            tomorrow_check = "复查广告是否有曝光、点击和预算消耗"
        elif "样本量小" in action or "数据量小" in action:
            if key in executed_cooldown_keys or clicks < 5:
                continue
            review_reason = "新品/重启广告样本不足"
            tomorrow_check = "复查是否达到 5 次以上点击或产生首单"
        if not review_reason:
            continue
        seen.add(key)
        trigger_action = "达到阈值后升级今日动作" if review_reason == "3-5点击无单，未达到强动作阈值" else "补导数据" if "数据" in action else "不操作，仅复查"
        rows.append(
            {
                "marketplace": key[0],
                "product_name": evidence.get("product_name") or evidence.get("sku") or item.get("target") or "N/A",
                "sku": key[1] or "N/A",
                "asin": key[2] or "N/A",
                "review_reason": review_reason,
                "current_evidence": f"点击 {shared._format_count(clicks)}；花费 {shared._money(evidence.get('spend'), key[0], evidence.get('currency'))}；订单 {shared._format_count(evidence.get('ad_orders'))}",
                "tomorrow_check": tomorrow_check,
                "trigger_action": trigger_action,
            }
        )

    return rows[:3]


def _self_optimization_notes(shared: Any, analysis_payload: dict, view: dict[str, object]) -> list[str]:
    notes: list[str] = []
    runtime_policy = view.get("runtime_policy", {}) if isinstance(view, dict) else {}
    for note in runtime_policy.get("notes", []) if isinstance(runtime_policy, dict) else []:
        notes.append(str(note))
    hidden_low_click = int(view.get("hidden_low_click_search_terms", 0) or 0)
    if hidden_low_click:
        notes.append(f"低点击观察对象 {hidden_low_click} 条已下沉到 Excel；主页只保留需要处理或留档的广告动作。")
    listing_rows = list(view.get("listing_price_diagnosis_rows", []) or [])
    if listing_rows:
        notes.append("Listing 待人工确认保持差异化材料优先，通用材料固定在板块顶部，只展示一次。")
    risk_rows = list(view.get("risk_rows", []) or [])
    if len(risk_rows) > 3:
        notes.append("滞销观察池当前对象较多，主页仅展示高风险 Top 3，其余继续进 Excel。")
    cost_rows = list(view.get("today_action_groups", {}).get("成本 / 利润动作", []) or [])
    if len(cost_rows) > 3:
        notes.append("利润 / 成本待核对仅展示 Top 3，其余继续进 Excel。")
    task_rows = list(view.get("today_task_queue_rows", []) or [])
    seen_keys: set[tuple[str, str, str]] = set()
    duplicate_count = 0
    for row in task_rows:
        key = (str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
        if key in seen_keys:
            duplicate_count += 1
            continue
        seen_keys.add(key)
    if duplicate_count:
        notes.append(f"同一 marketplace + SKU + ASIN 已合并 {duplicate_count} 次重复对象；后续继续优先保留单卡。")
    status_rows = list(view.get("enhanced_status_rows", []) or [])
    unknown_rows = sum(1 for row in status_rows if str(row.get("新鲜度") or "") in {"unknown", "stale"} or str(row.get("周期类型") or "") == "unknown")
    if unknown_rows:
        notes.append(f"未知或陈旧周期增强数据 {unknown_rows} 条仅作背景参考，不提升为强动作。")
    notes.extend(shared.build_optimization_notes(shared.OUTPUT_DIR, rows=view.get("today_task_queue_rows", []) or []))
    deduped: list[str] = []
    for note in notes:
        note = str(note).replace("搜索词处理队列", "广告处理队列").replace("搜索词处理", "广告处理")
        if note not in deduped:
            deduped.append(note)
    if not deduped:
        deduped.append("当前主页结构已收敛；若后续连续 2 天出现同类重复建议，可继续下调其主页优先级。")
    return deduped[:6]
