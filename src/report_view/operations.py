from __future__ import annotations

from typing import Any


def _product_metric_lookup(shared: Any, analysis_payload: dict, window: str = "14d") -> dict[tuple[str, str, str], dict[str, object]]:
    marketplace = shared._infer_marketplace(analysis_payload)
    rows = analysis_payload.get("product_window_metrics", {}).get(window, [])
    lookup: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.setdefault("marketplace", marketplace)
        key = (shared._row_marketplace(item, marketplace), shared._row_sku(item), shared._row_asin(item))
        if key[0] and key[2]:
            lookup[key] = item
    return lookup


def _product_rows_by_key(shared: Any, rows: list[dict[str, object]]) -> dict[tuple[str, str, str], list[dict[str, object]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (shared._row_marketplace(row), shared._row_sku(row), shared._row_asin(row))
        if not key[0] or not key[2]:
            continue
        grouped.setdefault(key, []).append(row)
    return grouped


def _first_product_row(shared: Any, rows: list[dict[str, object]]) -> dict[str, object]:
    del shared
    return rows[0] if rows else {}


def _operation_card_sort_key(shared: Any, row: dict[str, object]) -> tuple[int, str, str]:
    del shared
    final = str(row.get("final_decision") or "")
    issue = str(row.get("fusion_issue_type") or "")
    inventory = str(row.get("inventory_constraint") or "")
    has_pending_ad = bool(row.get("ad_action_items"))
    if final == "DATA_INSUFFICIENT" or "cost_blocked" in str(row.get("fusion_action_gate") or ""):
        rank = 0
    elif final == "FRONTEND_FIRST" or "前台" in issue:
        rank = 1
    elif has_pending_ad or final == "EXECUTE_TODAY":
        rank = 2
    elif final == "WAIT_REVIEW":
        rank = 3
    elif inventory in {"OUT_OF_STOCK", "LOW_STOCK", "RESTOCK_RECOVERY"}:
        rank = 4
    else:
        rank = 5
    return rank, str(row.get("marketplace") or ""), str(row.get("product_name") or "")


def _first_present(shared: Any, row: dict[str, object], *fields: str) -> object:
    del shared
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return ""


def _build_ad_diagnostic_summary(shared: Any, card: dict[str, object]) -> str:
    clicks14 = shared._to_float(card.get("ad_clicks")) or 0
    spend14 = shared._to_float(card.get("ad_spend")) or 0
    orders14 = shared._to_float(card.get("ad_orders")) or 0
    total14 = shared._to_float(card.get("total_orders")) or 0
    orders7 = shared._to_float(card.get("recent_7d_orders")) or 0
    action_count = int(shared._to_float(card.get("ad_action_count")) or 0)
    issue = str(card.get("fusion_issue_type") or "")
    gate = str(card.get("fusion_action_gate") or "")

    if "前台" in issue and (clicks14 >= 10 or spend14 >= 5):
        return f"广告有样本，近14天点击 {int(clicks14)}、广告单 {int(orders14)}、总单 {int(total14)}；前台弱势时只做止损，不加价不加预算。"
    if gate == "tighten_ads_first" or action_count:
        return f"广告端优先，近14天点击 {int(clicks14)}、广告单 {int(orders14)}、近7天广告单 {int(orders7)}；卡内 {action_count} 条词级/ASIN 止损项按广告证据执行。"
    if orders14 > 0:
        return f"广告已有成交，近14天广告单 {int(orders14)}、总单 {int(total14)}；加价只看词级真实出单和 ACOS，不用产品级订单直接追高。"
    if clicks14 < 5 and spend14 < 5:
        return f"广告样本不足，近14天点击 {int(clicks14)}、花费 {spend14:.2f}；今天不做强判断。"
    return f"广告需继续观察，近14天点击 {int(clicks14)}、广告单 {int(orders14)}、总单 {int(total14)}；没有词级强证据时不扩大预算。"


def _build_operation_main_reason(shared: Any, card: dict[str, object]) -> str:
    marketplace = str(card.get("marketplace") or "")
    decision = str(card.get("decision_reason_raw") or card.get("decision_reason") or "").strip()
    parts: list[str] = []
    if decision:
        parts.append(decision)

    clicks14 = shared._to_float(card.get("ad_clicks"))
    spend14 = shared._to_float(card.get("ad_spend"))
    ad_orders14 = shared._to_float(card.get("ad_orders"))
    total14 = shared._to_float(card.get("total_orders"))
    natural14 = shared._to_float(card.get("natural_orders"))
    if any(value is not None and value > 0 for value in [clicks14, spend14, ad_orders14, total14, natural14]):
        sales_bits: list[str] = []
        if clicks14 is not None:
            sales_bits.append(f"14天点击 {int(clicks14)}")
        if spend14 is not None:
            sales_bits.append(f"花费 {shared._money(spend14, marketplace)}")
        if ad_orders14 is not None:
            sales_bits.append(f"广告单 {int(ad_orders14)}")
        if total14 is not None:
            sales_bits.append(f"总单 {int(total14)}")
        if natural14 is not None:
            sales_bits.append(f"自然单 {int(natural14)}")
        if sales_bits:
            parts.append("产品窗口：" + "，".join(sales_bits))

    recent_total = shared._to_float(card.get("recent_7d_total_orders"))
    recent_natural = shared._to_float(card.get("recent_7d_natural_orders"))
    if recent_total is not None or recent_natural is not None:
        recent_bits: list[str] = []
        if recent_total is not None:
            recent_bits.append(f"近7天总单 {int(recent_total)}")
        if recent_natural is not None:
            recent_bits.append(f"近7天自然单 {int(recent_natural)}")
        if recent_bits:
            parts.append("近7天：" + "，".join(recent_bits))

    profit = shared._to_float(card.get("profit_before_ads_per_unit"))
    cost_status = str(card.get("cost_status") or "").strip()
    if profit is not None:
        if profit <= 0:
            parts.append("利润：广告前利润<=0，当前不支持放量")
        else:
            parts.append(f"利润：广告前利润约 {shared._money(profit, marketplace)}/件")
    elif cost_status:
        parts.append(f"利润：{cost_status}")

    inventory_constraint = str(card.get("inventory_constraint") or "").strip()
    inventory_reason = str(card.get("inventory_reason") or "").strip()
    if inventory_constraint and inventory_constraint not in {"NONE", "HEALTHY"}:
        inventory_labels = {
            "OUT_OF_STOCK": "断货",
            "LOW_STOCK": "低库存",
            "RESTOCK_RECOVERY": "补货恢复期",
            "REPLENISH_SOON": "进入补货窗口",
        }
        inventory_text = inventory_labels.get(inventory_constraint, inventory_constraint)
        if inventory_reason and inventory_reason not in inventory_text:
            parts.append(f"库存：{inventory_text}；{inventory_reason}")
        else:
            parts.append(f"库存：{inventory_text}")

    frontend_status = str(card.get("frontend_status") or "").strip()
    frontend_label = str(card.get("frontend_auto_conclusion_label") or "").strip()
    frontend_search = str(card.get("frontend_search_findings") or card.get("frontend_search_status") or "").strip()
    frontend_bits: list[str] = []
    if frontend_status:
        frontend_bits.append(frontend_status)
    if frontend_label and frontend_label not in frontend_status:
        frontend_bits.append(frontend_label)
    if frontend_search and any(token in frontend_search for token in ["未稳定", "部分", "缺失", "竞品", "搜索页"]):
        frontend_bits.append(frontend_search)
    if frontend_bits:
        parts.append("前台：" + "；".join(frontend_bits[:2]))

    history = str(card.get("feedback_cooldown_status") or card.get("keyword_memory_summary") or "").strip()
    if history:
        parts.append(f"历史：{history}")

    return "；".join(part for part in parts if part) or "当前没有可用于强判断的产品级证据。"


def _build_product_operation_cards(
    shared: Any,
    analysis_payload: dict,
    *,
    decision_rows: list[dict[str, object]],
    task_rows: list[dict[str, object]],
    search_rows: list[dict[str, object]],
    frontend_rows: list[dict[str, object]],
    inventory_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    metrics14 = _product_metric_lookup(shared, analysis_payload, "14d")
    metric7 = _product_metric_lookup(shared, analysis_payload, "7d")
    tasks_by_key = _product_rows_by_key(shared, task_rows)
    search_by_key = _product_rows_by_key(shared, search_rows)
    frontend_by_key = _product_rows_by_key(shared, frontend_rows)
    inventory_by_key = _product_rows_by_key(shared, inventory_rows)
    keys: set[tuple[str, str, str]] = set()
    for source in [metrics14, metric7]:
        keys.update(source)
    for rows in [decision_rows, task_rows, search_rows, frontend_rows, inventory_rows]:
        for row in rows:
            key = (shared._row_marketplace(row), shared._row_sku(row), shared._row_asin(row))
            if key[0] and key[2]:
                keys.add(key)

    decisions = {
        (shared._row_marketplace(row), shared._row_sku(row), shared._row_asin(row)): row
        for row in decision_rows
        if shared._row_marketplace(row) and shared._row_asin(row)
    }
    cards: list[dict[str, object]] = []
    for key in keys:
        decision = decisions.get(key, {})
        product14 = metrics14.get(key, {})
        product7 = metric7.get(key, {})
        tasks = tasks_by_key.get(key, [])
        ad_items = [
            row
            for row in search_by_key.get(key, [])
            if str(row.get("suggested_action") or row.get("scale_action") or "") not in {"", "观察", "保留", "小样本保留观察"}
        ][:4]
        frontend = _first_product_row(shared, frontend_by_key.get(key, []))
        inventory = _first_product_row(shared, inventory_by_key.get(key, []))
        source = decision or product14 or _first_product_row(shared, tasks) or frontend or inventory
        cost_task = next((row for row in tasks if str(row.get("action_group") or "") == "成本 / 利润动作"), {})
        card = {
            "marketplace": key[0],
            "sku": key[1],
            "asin": key[2],
            "product_name": shared._row_product_name(source),
            "final_decision": decision.get("final_decision") or "",
            "final_decision_label": decision.get("final_decision_label") or "",
            "decision_reason": decision.get("decision_reason") or "",
            "decision_reason_raw": decision.get("decision_reason") or "",
            "fusion_issue_type": decision.get("fusion_issue_type") or "",
            "fusion_confidence": decision.get("fusion_confidence") or "",
            "fusion_action_gate": decision.get("fusion_action_gate") or "",
            "fusion_reason": decision.get("fusion_reason") or "",
            "fusion_today_action": decision.get("fusion_today_action") or decision.get("decision_reason") or "",
            "fusion_do_not_do": decision.get("fusion_do_not_do") or "",
            "fusion_review_window": decision.get("fusion_review_window") or decision.get("next_review_date") or "",
            "today_allowed_actions": decision.get("today_allowed_actions") or [],
            "today_blocked_actions": decision.get("today_blocked_actions") or [],
            "inventory_constraint": decision.get("inventory_constraint") or inventory.get("stock_risk_level") or "",
            "inventory_reason": inventory.get("stock_risk_reason") or "",
            "feedback_cooldown_status": decision.get("feedback_cooldown_status") or "",
            "keyword_memory_summary": decision.get("keyword_memory_summary") or "",
            "frontend_status": frontend.get("frontend_check_status") or "",
            "frontend_freshness": frontend.get("frontend_data_freshness") or frontend.get("frontend_check_status") or "",
            "frontend_auto_conclusion_label": frontend.get("frontend_auto_conclusion_label") or "",
            "frontend_evidence_quality_score": frontend.get("frontend_evidence_quality_score") or "",
            "frontend_findings": frontend.get("frontend_findings") or "",
            "frontend_search_status": frontend.get("frontend_search_status") or "",
            "frontend_search_findings": frontend.get("frontend_search_findings") or "",
            "frontend_search_result_count": frontend.get("frontend_search_result_count") or "",
            "frontend_search_partial_evidence": bool(frontend.get("frontend_search_partial_evidence")),
            "frontend_evidence_tier": frontend.get("frontend_evidence_tier") or "",
            "frontend_evidence_audit_summary": frontend.get("frontend_evidence_audit_summary") or "",
            "frontend_evidence_audit_detail": frontend.get("frontend_evidence_audit_detail") or "",
            "frontend_evidence_audit_reasons": frontend.get("frontend_evidence_audit_reasons") or [],
            "ad_action_items": ad_items,
            "ad_action_count": len(ad_items),
            "cost_status": cost_task.get("primary_reason") or "",
            "cost_key_evidence": cost_task.get("key_evidence") or "",
            "task_priority": min((shared.PRIORITY_ORDER.get(str(row.get("priority") or "P2"), 2) for row in tasks), default=2),
        }
        for metric_name, field in [
            ("ad_clicks", "ad_clicks"),
            ("ad_spend", "ad_spend"),
            ("ad_orders", "ad_orders"),
            ("ad_sales", "ad_sales"),
            ("total_orders", "total_orders"),
            ("natural_orders", "natural_orders"),
            ("acos", "acos"),
            ("target_acos", "target_acos"),
            ("profit_before_ads_per_unit", "profit_before_ads_per_unit"),
        ]:
            card[metric_name] = product14.get(field, "")
        card["acos"] = _first_present(shared, product14, "acos", "ACOS")
        card["tacos"] = _first_present(shared, product14, "tacos", "TACOS")
        card["ad_cvr"] = _first_present(shared, product14, "ad_CVR", "ad_cvr", "CVR")
        card["ad_order_share"] = _first_present(shared, product14, "ad_order_share")
        card["recent_7d_clicks"] = product7.get("ad_clicks", "")
        card["recent_7d_orders"] = product7.get("ad_orders", "")
        card["recent_7d_total_orders"] = product7.get("total_orders", "")
        card["recent_7d_natural_orders"] = product7.get("natural_orders", "")
        card["ad_diagnostic_summary"] = _build_ad_diagnostic_summary(shared, card)
        card["operation_main_reason"] = _build_operation_main_reason(shared, card)
        card["decision_reason"] = card["operation_main_reason"]
        cards.append(card)
    return sorted(cards, key=lambda row: _operation_card_sort_key(shared, row))
