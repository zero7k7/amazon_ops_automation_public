from __future__ import annotations

import re
from typing import Any


def _normalize_today_action(shared: Any, text: object, issue_type: str = "") -> str:
    value = str(text or "")
    if "数据" in value or issue_type == "数据质量问题":
        return "补导数据"
    if "利润" in value or "成本" in value or issue_type == "库存 / 利润压力":
        return "检查利润"
    if "否" in value:
        return "否词"
    if "暂停" in value:
        return "暂停广告"
    if "降竞价" in value or "竞价" in value:
        return "降竞价"
    if "价格" in value:
        return "检查价格"
    if "小预算" in value or "测试" in value:
        return "小预算测试"
    if "Listing" in value or "主图" in value or "评价" in value or "转化" in value or issue_type in {"无单原因诊断", "广告消耗无转化", "滞销 / 持续无单"}:
        return "检查Listing"
    return "不操作，仅复查"


def _with_action_identity(shared: Any, row: dict[str, object], action: object) -> dict[str, object]:
    add_identity = getattr(shared, "add_action_identity", None)
    if callable(add_identity):
        return add_identity(row, action)
    return row


def _search_term_action_from_item(shared: Any, item: dict, marketplace: str) -> dict[str, str]:
    evidence = item.get("evidence", {}) or {}
    target = str(item.get("target") or evidence.get("search_term") or "")
    clicks = shared._to_float(evidence.get("clicks")) or 0
    spend = shared._to_float(evidence.get("spend")) or 0
    orders = shared._to_float(evidence.get("ad_orders")) or 0
    is_asin = bool(evidence.get("is_asin_term")) or target.upper().startswith("B0")
    intent = str(evidence.get("intent") or "unknown")
    keyword_level = str(evidence.get("keyword_level") or "")
    matched_keyword = str(evidence.get("matched_keyword") or "")
    classification_reason = str(evidence.get("classification_reason") or "")
    is_core = bool(evidence.get("is_core_term")) or intent in {"core_relevant", "testable_relevant"}
    note = str(item.get("note") or "")
    action_text = str(item.get("action") or "")

    def manual_level() -> str:
        if keyword_level:
            return keyword_level
        if orders > 0:
            return "核心词"
        if intent == "irrelevant" or "明显不相关" in note or "明显不相关" in action_text:
            return "禁词"
        if is_core or intent in {"core_relevant", "testable_relevant"}:
            return "核心词"
        if is_asin:
            return "低质词" if clicks >= 6 or spend >= 5 else "可测词"
        if intent == "broad_generic":
            return "泛词"
        if intent == "competitor_or_brand":
            return "可测词"
        if clicks >= 8 or spend >= 5:
            return "低质词"
        return "可测词"

    def bid_adjustment_line() -> str:
        if clicks >= 15 or spend >= 10:
            return "建议降竞价 10%-20%"
        if clicks >= 10 or spend >= 5:
            return "建议降竞价 10%-15%"
        return "建议降竞价 5%-10%"

    def evidence_reason(label: str) -> str:
        spend_text = shared._money(spend, evidence.get("marketplace") or marketplace, evidence.get("currency"))
        base = f"{int(clicks)} 次点击 0 单，花费 {spend_text}"
        if label == "samples":
            return f"{base}，样本还小，先放低优先级"
        if label == "asin":
            return f"{base}，ASIN 定向未转化，优先控投放"
        if label == "irrelevant":
            return f"{base}，和产品线不匹配"
        if label == "core":
            return f"{base}，属于核心/强相关词，不直接否"
        if label == "broad":
            return f"{base}，偏泛词或待确认词，先控竞价"
        return f"{base}，先观察"

    if orders > 0:
        suggested_action = "保留"
        reason = f"已产生 {int(orders)} 单，先保留"
        relevance = "已转化"
    elif clicks <= 2:
        suggested_action = "观察"
        reason = evidence_reason("samples")
        relevance = "样本不足"
    elif is_asin and (clicks >= 3 or spend >= 5):
        if clicks < 5 and spend < 2:
            suggested_action = "观察"
        else:
            suggested_action = "暂停ASIN定向" if clicks >= 6 or spend >= 5 else "降竞价10%-20%"
        reason = evidence_reason("asin")
        relevance = "ASIN定向"
    elif intent == "irrelevant" or "明显不相关" in note or "明显不相关" in action_text:
        suggested_action = "否定精准"
        reason = evidence_reason("irrelevant")
        relevance = "明显不相关"
    elif intent in {"core_relevant", "testable_relevant"}:
        suggested_action = "降竞价10%-20%" if clicks >= 5 or spend >= 5 else "观察"
        reason = evidence_reason("core")
        relevance = "核心相关"
    elif intent in {"broad_generic", "competitor_or_brand", "unknown"} and (clicks >= 5 or spend >= 5):
        suggested_action = "降竞价10%-20%"
        reason = evidence_reason("broad")
        relevance = "泛词/竞品/待确认"
    else:
        suggested_action = "观察"
        reason = f"{int(clicks)} 次点击 {int(orders)} 单，暂未达到强动作阈值"
        relevance = intent or "待确认"

    if suggested_action == "否定精准":
        copy_action_line = "建议否词"
    elif suggested_action == "降竞价10%-20%":
        copy_action_line = bid_adjustment_line()
    elif suggested_action == "暂停ASIN定向":
        copy_action_line = "建议暂停 ASIN 定向"
    elif suggested_action == "保留":
        copy_action_line = "建议无需操作"
    else:
        copy_action_line = "建议观察"

    copy_block = f"{copy_action_line}\n{target or 'N/A'}"

    return _with_action_identity(shared, {
        "marketplace": evidence.get("marketplace") or marketplace,
        "product_name": evidence.get("product_name") or evidence.get("sku") or "N/A",
        "sku": evidence.get("sku") or "N/A",
        "asin": evidence.get("asin") or "N/A",
        "search_term_or_target": target or "N/A",
        "campaign": evidence.get("campaign_name") or "N/A",
        "campaign_name": evidence.get("campaign_name") or "N/A",
        "ad_group": evidence.get("ad_group_name") or "N/A",
        "ad_group_name": evidence.get("ad_group_name") or "N/A",
        "match_type": evidence.get("match_type") or "",
        "matched_target": evidence.get("matched_target") or "",
        "targeting": evidence.get("targeting") or "",
        "match_type_or_targeting": evidence.get("match_type") or evidence.get("targeting") or ("ASIN定向" if is_asin else "N/A"),
        "clicks": shared._format_count(clicks),
        "spend": shared._money(spend, evidence.get("marketplace") or marketplace, evidence.get("currency")),
        "orders": shared._format_count(orders),
        "sales": shared._money(evidence.get("ad_sales"), evidence.get("marketplace") or marketplace, evidence.get("currency")),
        "relevance_level": relevance,
        "manual_level": manual_level(),
        "keyword_level": manual_level(),
        "matched_keyword": matched_keyword,
        "classification_reason": classification_reason or f"未命中明确词库，按 {manual_level()} 保守处理",
        "suggested_action": suggested_action,
        "copy_action_line": copy_action_line,
        "copy_block": copy_block,
        "reason": reason,
        "html_visible": "否" if clicks <= 2 and orders == 0 else "是",
    }, suggested_action)


def _build_search_term_processing_queue(shared: Any, analysis_payload: dict) -> list[dict[str, str]]:
    marketplace = shared._infer_marketplace(analysis_payload)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in analysis_payload.get(shared.RECOMMENDATION_KEY, []):
        if item.get("category") != "搜索词":
            continue
        row = _search_term_action_from_item(shared, item, marketplace)
        key = (
            str(row.get("marketplace") or ""),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
            str(row.get("search_term_or_target") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    action_order = {"否定精准": 0, "暂停ASIN定向": 1, "降竞价10%-20%": 2, "观察": 3, "保留": 4}
    return sorted(
        rows,
        key=lambda row: (
            99 if row.get("html_visible") == "否" else action_order.get(str(row.get("suggested_action") or ""), 9),
            -(shared._to_float(row.get("点击")) or shared._to_float(row.get("clicks")) or 0),
            str(row.get("search_term_or_target") or ""),
        ),
    )


def _search_terms_for_task(shared: Any, task: dict[str, str], queue: list[dict[str, str]], limit: int = 5) -> str:
    task_key = (str(task.get("marketplace") or ""), str(task.get("sku") or ""), str(task.get("asin") or ""))
    action_order = {"否定精准": 0, "暂停ASIN定向": 1, "降竞价10%-20%": 2, "观察": 3, "保留": 4}
    matches = [
        row
        for row in queue
        if (str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or "")) == task_key
    ]
    matches = sorted(
        matches,
        key=lambda row: (
            1 if row.get("html_visible") == "否" else 0,
            action_order.get(str(row.get("suggested_action") or ""), 9),
            -(shared._to_float(row.get("clicks")) or 0),
        ),
    )[:limit]
    if not matches:
        return "N/A"
    return "；".join(f"{row.get('copy_action_line')}\n{row.get('search_term_or_target')}" for row in matches)


def _parse_percent_text(shared: Any, value: object) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        number = shared._to_float(text[:-1].strip())
        return None if number is None else number / 100
    return shared._to_float(value)


def _scale_keyword_action(shared: Any, term: str, ad_orders: float, acos: float, target_acos: float, clicks: float = 0) -> str:
    is_asin_target = bool(re.match(r"^B0[A-Z0-9]{8,}$", str(term or "").strip(), re.IGNORECASE))
    margin = target_acos - acos
    if ad_orders == 1 and clicks >= 4 and margin >= 0.05 and acos <= target_acos * 0.5:
        return "试探提高竞价 3%-5%"
    if ad_orders < 2:
        return "小样本保留观察"
    if is_asin_target:
        return "ASIN 定向提高竞价 5%-10%" if margin >= 0.02 else "保留 ASIN 定向"
    if margin >= 0.02:
        return "提高竞价 5%-10%"
    return "保留出单词，预算优先给该 Campaign"


def _build_scale_keyword_rows(shared: Any, analysis_payload: dict, scale_rows: list[dict[str, str]], marketplace: str) -> list[dict[str, str]]:
    if not scale_rows:
        return []

    scale_lookup: dict[tuple[str, str], dict[str, object]] = {}
    for row in scale_rows:
        key = (str(row.get("SKU") or ""), str(row.get("ASIN") or ""))
        if key == ("", ""):
            continue
        scale_lookup[key] = {
            "level": row.get("放量等级") or "谨慎放量候选",
            "target_acos": _parse_percent_text(shared, row.get("目标 ACOS")) or 0.10,
            "product": row.get("产品") or "N/A",
            "marketplace": row.get("站点") or marketplace,
        }

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in analysis_payload.get("搜索词分析", {}).get("14d", []) or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("sku") or ""), str(item.get("asin") or ""))
        product_scale = scale_lookup.get(key)
        if not product_scale:
            continue
        term = str(item.get("search_term") or item.get("targeting") or "").strip()
        campaign = str(item.get("campaign_name") or "")
        row_key = (key[0], key[1], term.lower(), campaign)
        if not term or row_key in seen:
            continue
        seen.add(row_key)

        ad_orders = shared._to_float(item.get("ad_orders")) or 0
        ad_sales = shared._to_float(item.get("ad_sales")) or 0
        acos = shared._to_float(item.get("ACOS"))
        target_acos = float(product_scale["target_acos"] or 0.10)
        clicks = shared._to_float(item.get("clicks")) or 0
        spend = shared._to_float(item.get("spend")) or 0
        if ad_orders <= 0 or ad_sales <= 0 or acos is None or target_acos <= 0 or acos > target_acos:
            continue

        action = _scale_keyword_action(shared, term, ad_orders, acos, target_acos, clicks)
        if "3%-5%" in action:
            reason = "14天有 1 个广告单且点击达到 4 次，ACOS 低于目标一半；只允许试探加价，避免直接按标准放量。"
        elif "小样本" in action:
            reason = "14天有广告单且 ACOS 低于目标，但点击/订单样本不足；仅保留观察，避免用 1 次成交追高。"
        else:
            reason = "14天有广告单且 ACOS 低于产品目标；词级放量依据来自广告搜索词真实出单数据。"
        rows.append(_with_action_identity(
            shared,
            {
                "marketplace": str(product_scale["marketplace"] or marketplace),
                "product_name": str(item.get("product_name") or product_scale["product"] or "N/A"),
                "sku": key[0] or "N/A",
                "asin": key[1] or "N/A",
                "search_term_or_target": term,
                "campaign_name": campaign or "N/A",
                "campaign": campaign or "N/A",
                "ad_group_name": item.get("ad_group_name") or "N/A",
                "ad_group": item.get("ad_group_name") or "N/A",
                "match_type": item.get("match_type") or "",
                "matched_target": item.get("matched_target") or "",
                "targeting": item.get("targeting") or "",
                "match_type_or_targeting": item.get("match_type") or item.get("targeting") or "",
                "clicks": shared._format_count(clicks),
                "spend": shared._money(spend, item.get("marketplace") or marketplace, item.get("currency")),
                "ad_orders": shared._format_count(ad_orders),
                "ad_sales": shared._money(ad_sales, item.get("marketplace") or marketplace, item.get("currency")),
                "ACOS": shared._format_percent(acos),
                "CVR": shared._format_percent(item.get("CVR")),
                "target_acos": shared._format_percent(target_acos),
                "scale_action": action,
                "reason": reason,
                "product_scale_level": str(product_scale["level"] or "谨慎放量候选"),
            },
            action,
        ))

    return sorted(
        rows,
        key=lambda row: (
            str(row.get("marketplace") or ""),
            str(row.get("product_name") or ""),
            -(shared._to_float(row.get("ad_orders")) or 0),
            _parse_percent_text(shared, row.get("ACOS")) or 99,
            -(shared._to_float(row.get("clicks")) or 0),
        ),
    )


def _specific_today_action(shared: Any, issue_type: str, reason: object = "", suggestion: object = "") -> str:
    text = f"{issue_type}；{reason}；{suggestion}"
    if issue_type == "近期转化断崖诊断" and ("风险未达 P0" in text or "先观察或小幅降竞价" in text):
        return "近7天广告未出单但风险未达 P0：先检查价格、Coupon、主图、配送、Buy Box/推荐报价率；广告端先观察或小幅降竞价，不直接否核心词。"
    if issue_type == "近期转化断崖诊断" or "近7天转化断崖" in text or "近7天广告无单" in text:
        return "近7天转化断崖：先检查价格、Coupon、主图、配送、Buy Box/推荐报价率；广告端暂停扩量，核心词降竞价10%-20%，不直接否核心词。"
    if issue_type in {"真无单 / 滞销诊断", "滞销 / 持续无单"}:
        return "先查价格、主图、评价、竞品和库存；确认利润允许后再小预算测试"
    if issue_type in {"成本 / 利润压力", "成本 / 利润压力诊断"} and any(token in text for token in ["广告前利润<=0", "利润不允许", "利润为负"]):
        return "核对采购成本、头程、FBA、售价；利润未修正前不放量；目标 ACOS 未填或为 0 时默认按 10%"
    if issue_type in {shared.LISTING_REVIEW_LABEL, "Listing / 价格转化诊断"} or any(token in text for token in ["点击后不转化", "加购后不购买", "Listing", "转化", "主图", "Coupon", "评价"]):
        return shared.LISTING_TEMP_ACTION
    if "明显不相关" in text or "irrelevant" in text:
        return "明显不相关词否定精准"
    if "核心" in text or "core_relevant" in text:
        return "核心词降竞价 10%-20%，不直接否"
    if "泛词" in text or "竞品" in text or "暂停" in text:
        return "泛词暂停或降竞价"
    if issue_type in {"广告消耗无转化", "广告归因弱诊断", "广告消耗无转化诊断", "搜索词处理"}:
        return "核心词降竞价 10%-20%，泛词暂停或降竞价，明显不相关词否定精准"
    if issue_type in {"成本 / 利润压力", "成本 / 利润压力诊断"}:
        return "检查库存、订单和利润结构；确认利润允许后再决定是否投放"
    return _normalize_today_action(shared, suggestion or reason, issue_type)


def _action_group_for(shared: Any, action: object, issue_type: object = "") -> str:
    text = f"{action}；{issue_type}"
    if "成本 / 利润" in str(issue_type or "") or any(
        token in text for token in ["广告前利润<=0", "广告前利润为负", "利润为负", "利润不允许"]
    ):
        return "成本 / 利润动作"
    if "近7天转化断崖" in text:
        return "广告动作"
    if any(token in text for token in ["Listing", "价格", "主图", "Coupon", "评价", "A+", "疑点"]):
        return "Listing / 价格动作"
    return "广告动作"


def _group_today_actions(shared: Any, rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped = {group: [] for group in shared.ACTION_GROUPS}
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        group = row.get("action_group") or _action_group_for(shared, row.get("today_action"), row.get("issue_type"))
        key = (group, str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
        if key in seen or len(grouped.get(group, [])) >= 3:
            continue
        seen.add(key)
        grouped.setdefault(group, []).append(row)
    return grouped
