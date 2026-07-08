from __future__ import annotations

import html
import json
import re
from typing import Any

from ..autoopt_feedback import add_action_identity, is_executable_action


ACTIONABLE_COPY_LINES = {
    "建议加价 10%-15%",
    "建议加价 5%-10%",
    "建议加价 3%-5%",
    "建议否词",
    "建议暂停 ASIN 定向",
    "建议降竞价 10%-20%",
    "建议降竞价 10%-15%",
    "建议降竞价 5%-10%",
}


_ACTION_GATE_LABELS = {
    "bid_up": "加竞价",
    "bid_down": "降竞价",
    "broad_scale": "放量",
    "budget_up": "加预算",
    "create_exact_low_budget": "低预算精准测试",
    "negative_exact": "否定精准",
    "observe": "观察",
    "pause": "暂停",
}

_LOSS_CONTROL_ACTIONS = {"bid_down", "negative_exact", "pause"}


def _action_values(value: object) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[/,，、\s]+", str(value or ""))
    return {str(item).strip() for item in values if str(item).strip()}


def _ad_gate_summary(row: dict[str, str]) -> str:
    allowed = _action_values(row.get("today_allowed_actions") or row.get("final_ad_allowed_actions"))
    blocked = _action_values(row.get("today_blocked_actions") or row.get("final_ad_blocked_actions"))
    if blocked & {"bid_up", "budget_up", "broad_scale"} and not (allowed & {"bid_up", "budget_up", "broad_scale"}):
        if "create_exact_low_budget" in allowed:
            return "只允许精准小测"
        if allowed & _LOSS_CONTROL_ACTIONS:
            return "仅止损"
        return "禁止放量"
    if "create_exact_low_budget" in allowed and blocked & {"budget_up", "broad_scale"}:
        return "允许精准小测"
    if "bid_up" in allowed and blocked & {"budget_up", "broad_scale"}:
        return "允许小幅加竞价"
    if allowed & {"budget_up", "broad_scale"}:
        return "放量前复核"
    conclusion = str(row.get("product_level_conclusion") or row.get("final_decision_label") or "").strip()
    return conclusion or ""


def _ad_gate_detail(row: dict[str, str]) -> str:
    boundary = str(
        row.get("product_ad_boundary")
        or row.get("final_decision_reason")
        or row.get("decision_reason")
        or ""
    ).strip()
    if boundary:
        return boundary
    blocked = _action_values(row.get("today_blocked_actions") or row.get("final_ad_blocked_actions"))
    labels = [_ACTION_GATE_LABELS.get(action, action) for action in sorted(blocked) if action != "observe"]
    if labels:
        return "拦截：" + " / ".join(labels[:3])
    return ""


def _render_search_queue_groups(
    shared: Any,
    rows: list[dict[str, str]],
    limit_per_group: int = 8,
    show_status: bool = True,
) -> str:
    if not rows:
        return '<p class="subtle">当前没有达到 HTML 展示阈值的搜索词/ASIN。</p>'
    action_order = {
        "加价10%-15%": 0,
        "加价5%-10%": 1,
        "加价3%-5%": 2,
        "否定精准": 0,
        "暂停ASIN定向": 1,
        "降竞价10%-20%": 2,
        "观察": 3,
        "保留": 4,
    }
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            action_order.get(str(row.get("suggested_action") or ""), 9),
            -shared._num_from_text(row.get("clicks")),
            str(row.get("search_term_or_target") or ""),
        ),
    )
    groups = [
        ("建议加价 10%-15%", {"建议加价 10%-15%"}),
        ("建议加价 5%-10%", {"建议加价 5%-10%"}),
        ("建议加价 3%-5%", {"建议加价 3%-5%"}),
        ("建议否词", {"建议否词"}),
        ("建议暂停 ASIN 定向", {"建议暂停 ASIN 定向"}),
        ("建议降竞价 10%-20%", {"建议降竞价 10%-20%"}),
        ("建议降竞价 10%-15%", {"建议降竞价 10%-15%"}),
        ("建议降竞价 5%-10%", {"建议降竞价 5%-10%"}),
    ]
    parts: list[str] = []
    visible_actions = {title for title, _ in groups}
    for title, actions in groups:
        group_rows = [
            row for row in sorted_rows if str(row.get("copy_action_line") or "") in actions
        ][:limit_per_group]
        if not group_rows:
            continue
        parts.append(f'<div class="queue-group"><h3>{html.escape(title)}</h3>')
        parts.append('<div class="queue-grid">')
        for row in group_rows:
            status = str(row.get("confirmed_status") or "")
            status_badge = (
                f'<span class="{shared._confirmed_tag(status)} search-term-status">{html.escape(status)}</span>'
                if show_status and status
                else ""
            )
            item_class = (
                "search-term-item has-status" if show_status and status else "search-term-item"
            )
            parts.append(
                "\n".join(
                    [
                        f'<div class="{item_class}">',
                        status_badge,
                        f'<div class="search-term-word">{shared._inline_markup(str(row.get("search_term_or_target") or "N/A"))}</div>',
                        "</div>",
                    ]
                )
            )
        parts.append("</div></div>")
    other_count = sum(
        1 for row in rows if str(row.get("copy_action_line") or "") not in visible_actions
    )
    if other_count:
        parts.append(f'<p class="subtle">另有 {other_count} 条观察/保留词，见 Excel 低优先级明细。</p>')
    return "".join(parts)


def _visible_search_queue_count(
    shared: Any, rows: list[dict[str, str]], limit_per_group: int = 8
) -> int:
    if not rows:
        return 0
    groups = [
        {"建议加价 10%-15%"},
        {"建议加价 5%-10%"},
        {"建议加价 3%-5%"},
        {"建议否词"},
        {"建议暂停 ASIN 定向"},
        {"建议降竞价 10%-20%"},
        {"建议降竞价 10%-15%"},
        {"建议降竞价 5%-10%"},
    ]
    count = 0
    for actions in groups:
        count += min(
            sum(1 for row in rows if str(row.get("copy_action_line") or "") in actions),
            limit_per_group,
        )
    return count


def _render_ad_copy_sections(shared: Any, rows: list[dict[str, str]]) -> str:
    pending_rows = [row for row in rows if str(row.get("confirmed_status") or "") != "已执行"]
    executed_rows = [row for row in rows if str(row.get("confirmed_status") or "") == "已执行"]
    parts = ['<div class="queue-subtitle">待处理广告动作</div>']
    if pending_rows:
        visible_pending_count = _visible_search_queue_count(shared, pending_rows)
        if visible_pending_count:
            parts.append(f'<div class="queue-status-row"><span class="tag tag-yellow">待确认 {visible_pending_count}</span></div>')
        parts.append(_render_search_queue_groups(shared, pending_rows, show_status=False))
    else:
        parts.append('<p class="subtle">当前没有新的待处理广告动作。</p>')
    if executed_rows:
        parts.append('<div class="queue-subtitle">已执行，仅留档</div>')
        parts.append(_render_search_queue_groups(shared, executed_rows, limit_per_group=12))
    return "".join(parts)


def _render_search_queue_evidence_groups(
    shared: Any, rows: list[dict[str, str]], limit_per_group: int = 8
) -> str:
    if not rows:
        return '<p class="subtle">当前没有需要展开的搜索词解释。</p>'
    action_order = {
        "加价10%-15%": 0,
        "加价5%-10%": 1,
        "加价3%-5%": 2,
        "否定精准": 0,
        "暂停ASIN定向": 1,
        "降竞价10%-20%": 2,
        "观察": 3,
        "保留": 4,
    }
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            action_order.get(str(row.get("suggested_action") or ""), 9),
            -shared._num_from_text(row.get("clicks")),
            str(row.get("search_term_or_target") or ""),
        ),
    )
    groups = [
        ("建议加价 10%-15%", {"建议加价 10%-15%"}),
        ("建议加价 5%-10%", {"建议加价 5%-10%"}),
        ("建议加价 3%-5%", {"建议加价 3%-5%"}),
        ("建议否词", {"建议否词"}),
        ("建议暂停 ASIN 定向", {"建议暂停 ASIN 定向"}),
        ("建议降竞价 10%-20%", {"建议降竞价 10%-20%"}),
        ("建议降竞价 10%-15%", {"建议降竞价 10%-15%"}),
        ("建议降竞价 5%-10%", {"建议降竞价 5%-10%"}),
    ]
    parts: list[str] = []
    for title, actions in groups:
        group_rows = [
            row for row in sorted_rows if str(row.get("copy_action_line") or "") in actions
        ][:limit_per_group]
        if not group_rows:
            continue
        parts.append(f'<div class="queue-group"><div class="queue-subtitle">{html.escape(title)}｜证据和解释</div>')
        parts.append('<div class="queue-evidence-list">')
        for row in group_rows:
            head = shared._inline_markup(str(row.get("search_term_or_target") or "N/A"))
            reason = shared._inline_markup(str(row.get("reason") or "N/A"))
            level = str(row.get("manual_level") or row.get("relevance_level") or "待确认")
            classification = str(row.get("classification_reason") or "")
            evidence = f"等级 {level} ｜ 点击 {row.get('clicks')} ｜ 花费 {row.get('spend')} ｜ 订单 {row.get('orders')}"
            detail = f"{classification}；{reason}" if classification else reason
            parts.append(
                "\n".join(
                    [
                        '<div class="queue-evidence-item">',
                        f'<div class="queue-evidence-head">{head}</div>',
                        f'<div class="queue-evidence-body">{shared._inline_markup(detail)}；{shared._inline_markup(evidence)}</div>',
                        "</div>",
                    ]
                )
            )
        parts.append("</div></div>")
    return "".join(parts)


def _scale_keywords_as_ad_queue_rows(
    shared: Any, rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    executed_feedback = {
        (
            str(feedback.get("marketplace") or "").upper(),
            str(feedback.get("sku") or "").strip(),
            str(feedback.get("asin") or "").strip(),
            str(feedback.get("search_term_or_target") or "").strip().lower(),
        )
        for feedback in shared.load_feedback_input()
        if str(feedback.get("confirmed_status") or "") == "已执行"
    }
    for row in rows:
        suggested_from_gate = str(row.get("suggested_action") or "").strip()
        action = str(row.get("scale_action") or "")
        if suggested_from_gate == "观察" or action == "观察":
            copy_action = str(row.get("copy_action_line") or "建议观察")
            suggested = "观察"
        elif "10%-15%" in action:
            copy_action = "建议加价 10%-15%"
            suggested = "加价10%-15%"
        elif "5%-10%" in action:
            copy_action = "建议加价 5%-10%"
            suggested = "加价5%-10%"
        elif "3%-5%" in action:
            copy_action = "建议加价 3%-5%"
            suggested = "加价3%-5%"
        else:
            copy_action = "建议保留"
            suggested = "保留"
        feedback_key = (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip(),
            str(row.get("search_term_or_target") or "").strip().lower(),
        )
        converted_row = {
            "marketplace": row.get("marketplace") or "",
            "product_name": row.get("product_name") or "",
            "sku": row.get("sku") or "",
            "asin": row.get("asin") or "",
            "search_term_or_target": row.get("search_term_or_target") or "N/A",
            "campaign": row.get("campaign") or row.get("campaign_name") or "N/A",
            "campaign_name": row.get("campaign_name") or row.get("campaign") or "N/A",
            "ad_group": row.get("ad_group") or row.get("ad_group_name") or "N/A",
            "ad_group_name": row.get("ad_group_name") or row.get("ad_group") or "N/A",
            "match_type": row.get("match_type") or "",
            "matched_target": row.get("matched_target") or "",
            "targeting": row.get("targeting") or "",
            "match_type_or_targeting": row.get("match_type_or_targeting") or "",
            "copy_action_line": copy_action,
            "suggested_action": suggested,
            "scale_action": row.get("scale_action") or "",
            "confirmed_status": "已执行"
            if feedback_key in executed_feedback
            else (row.get("confirmed_status") or "待确认"),
            "clicks": row.get("clicks") or "0",
            "spend": row.get("spend") or "N/A",
            "orders": row.get("ad_orders") or "0",
            "ad_orders": row.get("ad_orders") or "0",
            "ad_sales": row.get("ad_sales") or "",
            "ACOS": row.get("ACOS") or "",
            "CVR": row.get("CVR") or "",
            "target_acos": row.get("target_acos") or "",
            "reason": f"{row.get('reason') or '14天出单且 ACOS 低于目标'}；ACOS {row.get('ACOS')} / 目标 {row.get('target_acos')}",
            "manual_level": "出单词",
            "classification_reason": f"{row.get('product_scale_level') or '放量候选'}，来自广告搜索词真实出单数据",
            "html_visible": "是",
            "report_date": row.get("report_date") or "",
            "next_review": row.get("next_review") or "",
            "cooldown_days": row.get("cooldown_days") or "",
            "ad_gate_blocked": row.get("ad_gate_blocked") or "",
            "ad_memory_blocked": row.get("ad_memory_blocked") or "",
            "blocked_action_id": row.get("blocked_action_id") or "",
            "blocked_original_action": row.get("blocked_original_action") or "",
            "keyword_memory_summary": row.get("keyword_memory_summary") or "",
            "final_decision": row.get("final_decision") or "",
            "final_decision_label": row.get("final_decision_label") or "",
            "final_decision_reason": row.get("final_decision_reason") or "",
            "today_allowed_actions": row.get("today_allowed_actions") or "",
            "today_blocked_actions": row.get("today_blocked_actions") or "",
        }
        converted.append(add_action_identity(converted_row, suggested))
    return converted


def _ad_action_label(shared: Any, row: dict[str, str]) -> str:
    action = str(
        row.get("suggested_action") or row.get("scale_action") or row.get("copy_action_line") or ""
    ).strip()
    if (
        str(row.get("experiment_type") or "").strip() == "growth_test"
        or "growth_test" in action
        or "推广实验" in action
        or ("小预算" in action and ("试投" in action or "测试" in action))
    ):
        return "小预算试投"
    if "拉精准" in action or "新建精准" in action or "create_exact" in action:
        return "拉精准小预算"
    if "否" in action and "不直接否" not in action:
        return "否定精准"
    if "暂停" in action and "ASIN" in action.upper():
        return "暂停 ASIN 定向"
    if "加价" in action or "提高竞价" in action:
        if "10%-15%" in action:
            return "加价 10%-15%"
        if "3%-5%" in action:
            return "加价 3%-5%"
        return "加价 5%-10%"
    if "降竞价" in action or "降价竞价" in action:
        if "10%-20%" in action:
            return "降竞价 10%-20%"
        if "10%-15%" in action:
            return "降竞价 10%-15%"
        return "降竞价 5%-10%"
    if "降价" in action:
        return "降价"
    if "保留" in action:
        return "保留观察"
    return "观察"


def _ad_action_key(shared: Any, label: str) -> str:
    if "小预算试投" in label or "推广实验" in label:
        return "growth-test"
    if "拉精准" in label:
        return "create-exact"
    if "加价" in label:
        return "bid-up"
    if "降竞价" in label:
        return "bid-down"
    if "否定" in label or "否词" in label:
        return "negative"
    if "暂停" in label:
        return "pause"
    if label == "降价":
        return "price-down"
    return "watch"


def _ad_status_key(shared: Any, row: dict[str, str]) -> str:
    status = str(row.get("confirmed_status") or "待确认")
    if status == "已执行":
        return "done"
    if _ad_action_key(shared, _ad_action_label(shared, row)) == "watch":
        return "watch"
    return "pending"


def _ad_status_label(shared: Any, key: str) -> str:
    return {"done": "已执行", "watch": "观察", "pending": "待确认"}.get(key, "待确认")


def _ad_status_class(shared: Any, key: str) -> str:
    return {
        "done": "status-done",
        "watch": "status-watch",
        "pending": "status-pending",
    }.get(key, "status-pending")


def _ad_action_class(shared: Any, action_key: str) -> str:
    return {
        "bid-up": "action-bid-up",
        "bid-down": "action-bid-down",
        "negative": "action-negative",
        "pause": "action-pause",
        "create-exact": "action-bid-up",
        "growth-test": "action-bid-up",
        "price-down": "action-price-down",
        "watch": "action-watch",
    }.get(action_key, "action-watch")


def _ad_action_badge_class(shared: Any, action_key: str) -> str:
    return {
        "bid-up": "action-badge-bid-up",
        "bid-down": "action-badge-bid-down",
        "negative": "action-badge-negative",
        "pause": "tag-orange",
        "create-exact": "action-badge-bid-up",
        "growth-test": "tag-blue",
        "price-down": "action-badge-price-down",
        "watch": "action-badge-watch",
    }.get(action_key, "action-badge-watch")


def _ad_completion_payload(row: dict[str, str], label: str) -> dict[str, object]:
    action_text = str(
        row.get("suggested_action")
        or row.get("scale_action")
        or row.get("copy_action_line")
        or label
    )
    identified = add_action_identity(row, action_text)
    if not is_executable_action(identified):
        return {}
    payload = {
        "marketplace": str(row.get("marketplace") or "").upper(),
        "sku": row.get("sku") or "",
        "asin": row.get("asin") or "",
        "product_name": row.get("product_name") or "",
        "action_id": identified.get("action_id") or "",
        "action_scope": identified.get("action_scope") or "",
        "normalized_action": identified.get("normalized_action") or "",
        "search_term_or_target": row.get("search_term_or_target") or "",
        "suggested_action": row.get("suggested_action") or label,
        "manual_action_taken": label,
        "confirmed_note": "网页勾选已完成；未满3天不判断，3天初查，7天正式复盘。",
        "report_date": row.get("report_date") or "",
        "next_review": row.get("next_review") or "",
        "cooldown_days": row.get("cooldown_days") or 7,
    }
    for key in [
        "experiment_type",
        "term_source",
        "evidence_level",
        "traffic_origin",
        "operation_label",
        "campaign_name",
        "campaign",
        "ad_group_name",
        "ad_group",
        "match_type",
        "matched_target",
        "targeting",
        "match_type_or_targeting",
        "suggested_daily_budget",
        "suggested_bid_min",
        "suggested_bid_max",
        "test_days",
        "stop_loss_rule",
        "success_rule",
        "reason",
    ]:
        if row.get(key) not in (None, ""):
            payload[key] = row.get(key)
    return payload


def _json_attr(payload: object) -> str:
    return html.escape(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), quote=True)


def _completion_control_html() -> str:
    return (
        '<div class="ad-complete-row">'
        '<label class="ad-complete-control">'
        '<input type="checkbox" data-ad-complete-checkbox>'
        '<span>标记已完成</span>'
        '</label>'
        '<span class="subtle" data-ad-complete-message></span>'
        '</div>'
    )


def _completion_attrs_for_rows(rows: list[dict[str, str]], label: str) -> str:
    payloads: list[dict[str, object]] = []
    for row in rows:
        if _ad_status_key(None, row) != "pending":
            continue
        completion_payload = _ad_completion_payload(row, label)
        if completion_payload:
            payloads.append(completion_payload)
    if not payloads:
        return ""
    first_payload = payloads[0]
    action_label = str(first_payload.get("manual_action_taken") or first_payload.get("suggested_action") or label)
    payload: object = payloads[0] if len(payloads) == 1 else payloads
    return (
        ' data-ad-complete-card="true"'
        f' data-ad-complete-payload="{_json_attr(payload)}"'
        f' data-action-id="{html.escape(str(first_payload.get("action_id") or ""))}"'
        f' data-search-term="{html.escape(str(first_payload.get("search_term_or_target") or ""))}"'
        f' data-action-label="{html.escape(action_label)}"'
    )


def _ad_copy_groups(
    shared: Any, rows: list[dict[str, str]]
) -> dict[tuple[str, str], list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    seen_terms: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        status = _ad_status_key(shared, row)
        if status == "watch":
            continue
        label = _ad_action_label(shared, row)
        term = str(row.get("search_term_or_target") or "").strip()
        if not term:
            continue
        marketplace = str(row.get("marketplace") or "N/A").upper()
        group_key = (label, marketplace)
        groups.setdefault(group_key, [])
        seen_terms.setdefault(group_key, set())
        if term not in seen_terms[group_key]:
            seen_terms[group_key].add(term)
            groups[group_key].append(row)
    order = [
        "加价 10%-15%",
        "加价 5%-10%",
        "加价 3%-5%",
        "拉精准小预算",
        "降竞价 10%-20%",
        "降竞价 10%-15%",
        "降竞价 5%-10%",
        "否定精准",
        "暂停 ASIN 定向",
        "降价",
        "保留观察",
        "观察",
    ]
    ordered: dict[tuple[str, str], list[dict[str, str]]] = {}
    for label in order:
        matching_keys = sorted(
            [group_key for group_key in groups if group_key[0] == label],
            key=lambda group_key: shared._marketplace_sort_key(group_key[1]),
        )
        for group_key in matching_keys:
            ordered[group_key] = groups[group_key]
    return ordered


def _ad_summary(
    shared: Any,
    rows: list[dict[str, str]],
    *,
    all_marketplaces: bool = False,
    marketplace_hint: str = "",
) -> dict[str, str]:
    pending = sum(1 for row in rows if _ad_status_key(shared, row) == "pending")
    done = sum(1 for row in rows if _ad_status_key(shared, row) == "done")
    watch = sum(1 for row in rows if _ad_status_key(shared, row) == "watch")
    spend = sum(shared._num_from_text(row.get("spend")) for row in rows)
    spend_by_market: dict[str, float] = {}
    symbol_by_market: dict[str, str] = {}
    for row in rows:
        marketplace = str(row.get("marketplace") or "N/A").upper()
        value = shared._num_from_text(row.get("spend"))
        spend_by_market[marketplace] = spend_by_market.get(marketplace, 0.0) + value
        spend_text = str(row.get("spend") or "")
        symbol = next((char for char in ["$", "£", "€"] if char in spend_text), "")
        symbol_by_market[marketplace] = symbol or shared.money_symbol_for_marketplace(
            marketplace, row.get("currency")
        )
    if all_marketplaces:
        spend_text = (
            " / ".join(
                f"{market} {symbol_by_market.get(market, '')}{spend_by_market.get(market, 0.0):.2f}"
                for market in sorted(spend_by_market, key=shared._marketplace_sort_key)
                if spend_by_market.get(market, 0.0) > 0
            )
            or "0.00"
        )
    else:
        marketplace = next(
            (
                str(row.get("marketplace") or "").upper()
                for row in rows
                if row.get("marketplace")
            ),
            str(marketplace_hint or "").upper(),
        )
        symbol = symbol_by_market.get(marketplace) or shared.money_symbol_for_marketplace(
            marketplace
        )
        spend_text = f"{symbol}{spend:.2f}" if symbol else f"{spend:.2f}"
    zero_order_click = sum(
        1
        for row in rows
        if shared._num_from_text(row.get("clicks")) > 0
        and shared._num_from_text(row.get("orders") or row.get("ad_orders")) <= 0
    )
    asin_targets = sum(
        1
        for row in rows
        if "ASIN"
        in str(row.get("match_type_or_targeting") or row.get("manual_level") or "").upper()
        or str(row.get("search_term_or_target") or "").upper().startswith("B0")
    )
    return {
        "待处理": str(pending),
        "已执行": str(done),
        "观察": str(watch),
        "队列花费": spend_text,
        "0单点击项": str(zero_order_click),
        "ASIN定向": str(asin_targets),
    }


def _render_ad_copy_boxes(shared: Any, rows: list[dict[str, str]], prefix: str) -> str:
    groups = _ad_copy_groups(shared, rows)
    if not groups:
        return '<p class="subtle">当前没有需要复制执行的广告动作。</p>'
    parts: list[str] = ['<div class="ad-action-group">']
    for index, ((label, marketplace), group_rows) in enumerate(groups.items(), start=1):
        block_id = f"{prefix}-copy-{index}"
        completion_attrs = _completion_attrs_for_rows(group_rows, label)
        completion_control = _completion_control_html() if completion_attrs else ""
        terms: list[str] = []
        visual_rows: list[str] = []
        for row in group_rows:
            term = str(row.get("search_term_or_target") or "").strip()
            if not term:
                continue
            targeting = str(
                row.get("match_type_or_targeting")
                or row.get("manual_level")
                or row.get("keyword_level")
                or ""
            ).strip()
            target_type = "ASIN定向" if re.fullmatch(r"B0[A-Z0-9]{8}", term.upper()) else "关键词"
            campaign = str(row.get("campaign") or row.get("campaign_name") or "").strip()
            terms.append(term)
            chips = [
                f'<span class="market">站点 {html.escape(marketplace)}</span>',
                f'<span class="action">{html.escape(label)}</span>',
                f'<span class="targeting">{html.escape(target_type if not targeting else targeting)}</span>',
            ]
            product_conclusion = str(row.get("product_level_conclusion") or "").strip()
            gate_summary = _ad_gate_summary(row)
            gate_detail = _ad_gate_detail(row)
            if product_conclusion:
                chips.append(f'<span>产品结论 {html.escape(product_conclusion)}</span>')
            if gate_summary:
                chips.append(f'<span>产品门禁 {html.escape(gate_summary)}</span>')
            if gate_detail:
                chips.append(f'<span>边界 {html.escape(gate_detail)}</span>')
            if campaign:
                chips.append(f'<span>Campaign {html.escape(campaign)}</span>')
            visual_rows.append(
                "\n".join(
                    [
                        f'<div class="ad-copy-row" data-ad-copy-row data-marketplace="{html.escape(marketplace)}" data-action-label="{html.escape(label)}" data-search-term="{html.escape(term)}">',
                        f'<div class="ad-copy-target">{html.escape(term)}</div>',
                        f'<div class="ad-copy-context">{"".join(chips)}</div>',
                        "</div>",
                    ]
                )
            )
        parts.append(
            "\n".join(
                [
                    f'<div class="ad-copy-box" data-copy-group="{html.escape(block_id)}" data-marketplace="{html.escape(marketplace)}" data-action-label="{html.escape(label)}"{completion_attrs}>',
                    '<div class="ad-copy-head">',
                    f'<div class="ad-copy-title"><span class="status-badge status-muted ad-copy-market">{html.escape(marketplace)}</span><strong>{html.escape(label)}</strong></div>',
                    f'<button class="copy-button" type="button" data-copy-target="{html.escape(block_id)}">复制</button>',
                    "</div>",
                    f'<div class="ad-copy-visual">{"".join(visual_rows)}</div>',
                    f'<pre class="ad-copy-text copy-source" id="{html.escape(block_id)}">{html.escape(chr(10).join(terms))}</pre>',
                    completion_control,
                    "</div>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _growth_evidence_display(value: object) -> str:
    text = str(value or "").strip()
    return {
        "历史广告订单": "曾有广告单",
        "核心强相关": "主词相关",
        "强意图长尾": "长尾相关",
        "有点击样本不足": "有点击待验证",
    }.get(text, text)


def _growth_copy_line(row: dict[str, str]) -> str:
    term = str(row.get("search_term_or_target") or "").strip()
    return term or "N/A"


def _render_growth_test_copy_boxes(shared: Any, rows: list[dict[str, str]]) -> str:
    pending_rows = [row for row in rows if _ad_status_key(shared, row) == "pending"]
    if not pending_rows:
        return ""
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in pending_rows:
        key = (
            str(row.get("marketplace") or "N/A").upper(),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
            str(row.get("product_name") or "N/A"),
        )
        grouped.setdefault(key, []).append(row)

    parts = ['<div class="ad-action-group growth-copy-group">']
    for index, ((marketplace, sku, asin, product), product_rows) in enumerate(grouped.items(), start=1):
        block_id = f"growth-test-copy-{index}"
        completion_attrs = _completion_attrs_for_rows(product_rows, "小预算试投")
        completion_control = _completion_control_html() if completion_attrs else ""
        terms = [_growth_copy_line(row) for row in product_rows if str(row.get("search_term_or_target") or "").strip()]
        total_budget = sum(shared._num_from_text(row.get("suggested_daily_budget")) for row in product_rows)
        first_budget = str((product_rows[0] if product_rows else {}).get("suggested_daily_budget") or "")
        budget_symbol = first_budget[:1] if first_budget[:1] in {"$", "£", "€"} else _market_symbol(marketplace)
        budget_label = f"总预算 {budget_symbol}{total_budget:.2f}/天" if total_budget else ""
        visual_rows: list[str] = []
        for row in product_rows:
            term = str(row.get("search_term_or_target") or "N/A")
            bid_min = str(row.get("suggested_bid_min") or "N/A")
            bid_max = str(row.get("suggested_bid_max") or "N/A")
            evidence = _growth_evidence_display(row.get("evidence_level")) or "待验证"
            traffic_origin = str(row.get("traffic_origin") or "未识别").strip() or "未识别"
            operation_label = str(row.get("operation_label") or "拉精准").strip() or "拉精准"
            match_type = str(row.get("match_type") or row.get("match_type_or_targeting") or "").strip()
            chips = [
                f'<span class="market">站点 {html.escape(marketplace)}</span>',
                f'<span>来源 {html.escape(traffic_origin)}</span>',
                f'<span>操作 {html.escape(operation_label)}</span>',
                *([f'<span>匹配 {html.escape(match_type)}</span>'] if match_type else []),
                f'<span>竞价 {html.escape(bid_min)}-{html.escape(bid_max)}</span>',
                f'<span>依据 {html.escape(evidence)}</span>',
            ]
            visual_rows.append(
                "\n".join(
                    [
                        f'<div class="ad-copy-row" data-ad-copy-row data-marketplace="{html.escape(marketplace)}" data-action-label="小预算试投" data-search-term="{html.escape(term)}">',
                        f'<div class="ad-copy-target">{html.escape(term)}</div>',
                        f'<div class="ad-copy-context">{"".join(chips)}</div>',
                        "</div>",
                    ]
                )
            )
        title = " ".join(part for part in [marketplace, product, sku, asin] if part)
        title_meta = " ".join(part for part in [title, budget_label] if part)
        parts.append(
            "\n".join(
                [
                    f'<div class="ad-copy-box growth-copy-box" data-copy-group="{html.escape(block_id)}" data-marketplace="{html.escape(marketplace)}" data-action-label="小预算试投"{completion_attrs}>',
                    '<div class="ad-copy-head">',
                    f'<div class="ad-copy-title"><span class="status-badge status-muted ad-copy-market">{html.escape(marketplace)}</span><strong>{html.escape(product or "小预算试投")}</strong><span class="subtle">{html.escape(title_meta)}</span></div>',
                    f'<button class="copy-button" type="button" data-copy-target="{html.escape(block_id)}">复制</button>',
                    "</div>",
                    f'<div class="ad-copy-visual">{"".join(visual_rows)}</div>',
                    f'<pre class="ad-copy-text copy-source" id="{html.escape(block_id)}">{html.escape(chr(10).join(terms))}</pre>',
                    completion_control,
                    "</div>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _render_ad_task_cards(shared: Any, rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="subtle">当前没有可展示广告任务。</p>'
    parts = ['<div class="ad-task-grid">']
    for row in rows:
        label = _ad_action_label(shared, row)
        action_key = _ad_action_key(shared, label)
        status_key = _ad_status_key(shared, row)
        term = str(row.get("search_term_or_target") or "N/A")
        marketplace = str(row.get("marketplace") or "N/A").upper()
        product = str(row.get("product_name") or "N/A")
        campaign = str(row.get("campaign") or row.get("campaign_name") or "N/A")
        ad_group = str(row.get("ad_group") or "N/A")
        targeting = str(
            row.get("match_type_or_targeting")
            or row.get("manual_level")
            or row.get("keyword_level")
            or "N/A"
        )
        orders = (
            row.get("orders") if row.get("orders") not in (None, "") else row.get("ad_orders", "0")
        )
        sales = row.get("sales") if row.get("sales") not in (None, "") else row.get("ad_sales", "N/A")
        clicks = shared._num_from_text(row.get("clicks"))
        spend = shared._num_from_text(row.get("spend"))
        order_num = shared._num_from_text(orders)
        cpc = spend / clicks if clicks else None
        cvr = order_num / clicks if clicks else None
        search_text = " ".join(
            str(row.get(key) or "")
            for key in [
                "search_term_or_target",
                "product_name",
                "sku",
                "asin",
                "campaign",
                "campaign_name",
                "ad_group",
                "match_type_or_targeting",
            ]
        )
        reason = str(row.get("reason") or "N/A")
        classification = str(row.get("classification_reason") or "")
        product_conclusion = str(row.get("product_level_conclusion") or "").strip()
        product_boundary = str(row.get("product_ad_boundary") or "").strip()
        gate_summary = _ad_gate_summary(row)
        gate_detail = _ad_gate_detail(row)
        boundary_chips = "".join(
            f'<span class="ad-metric-chip">{html.escape(label_text)} {html.escape(value)}</span>'
            for label_text, value in [
                ("产品结论", product_conclusion),
                ("产品门禁", gate_summary),
            ]
            if value
        )
        boundary_box = (
            f'<div class="ad-reason-box"><strong>产品级边界</strong><br>{shared._inline_markup(product_boundary or gate_detail or product_conclusion or "N/A")}</div>'
            if product_conclusion or product_boundary or gate_summary or gate_detail
            else ""
        )
        completion_payload = _ad_completion_payload(row, label)
        completion_attrs = ""
        completion_control = ""
        if completion_payload and status_key == "pending":
            completion_attrs = (
                ' data-ad-complete-card="true"'
                f' data-ad-complete-payload="{_json_attr(completion_payload)}"'
                f' data-action-id="{html.escape(str(completion_payload.get("action_id") or ""))}"'
                f' data-search-term="{html.escape(term)}"'
                f' data-action-label="{html.escape(label)}"'
            )
            completion_control = (
                '<div class="ad-complete-row">'
                '<label class="ad-complete-control">'
                '<input type="checkbox" data-ad-complete-checkbox>'
                '<span>标记已完成</span>'
                '</label>'
                '<span class="subtle" data-ad-complete-message></span>'
                '</div>'
            )
        parts.append(
            "\n".join(
                [
                    f'<article class="ad-task-card {_ad_action_class(shared, action_key)}" data-status="{status_key}" data-action="{action_key}" data-marketplace="{html.escape(marketplace)}" data-search-text="{html.escape(search_text)}"{completion_attrs}>',
                    '<div class="ad-card-head">',
                    "<div>",
                    f'<span class="status-badge {_ad_action_badge_class(shared, action_key)}">{html.escape(label)}</span>',
                    f' <span class="status-badge {_ad_status_class(shared, status_key)}" data-ad-complete-status>{html.escape(_ad_status_label(shared, status_key))}</span>',
                    "</div>",
                    f'<span class="status-badge status-muted">{html.escape(marketplace)}</span>',
                    "</div>",
                    f'<div class="ad-task-title">{html.escape(term)}</div>',
                    f'<div class="ad-task-meta">{html.escape(product)} ｜ {shared._product_meta_html(row)}</div>',
                    f'<div class="ad-task-meta">Campaign {html.escape(campaign)} ｜ Ad Group {html.escape(ad_group)} ｜ {html.escape(targeting)}</div>',
                    '<div class="ad-metric-row">',
                    f'<span class="ad-metric-chip">点击 {html.escape(str(row.get("clicks") or "0"))}</span>',
                    f'<span class="ad-metric-chip">花费 {html.escape(str(row.get("spend") or "N/A"))}</span>',
                    f'<span class="ad-metric-chip">订单 {html.escape(str(orders or "0"))}</span>',
                    f'<span class="ad-metric-chip">销售 {html.escape(str(sales or "N/A"))}</span>',
                    f'<span class="ad-metric-chip">CPC {cpc:.2f}</span>' if cpc is not None else "",
                    f'<span class="ad-metric-chip">CVR {cvr:.1%}</span>' if cvr is not None else "",
                    f'<span class="ad-metric-chip">ACOS {html.escape(str(row.get("ACOS") or "N/A"))}</span>' if row.get("ACOS") else "",
                    boundary_chips,
                    "</div>",
                    f'<div class="ad-reason-box"><strong>原因</strong><br>{shared._inline_markup(reason)}{("<br>" + shared._inline_markup(classification)) if classification else ""}</div>',
                    boundary_box,
                    completion_control,
                    "</article>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _render_growth_test_section(shared: Any, rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    pending_rows = [row for row in rows if _ad_status_key(shared, row) == "pending"]
    badge = (
        f'<span class="status-badge status-pending">待确认 {len(pending_rows)}</span>'
        if pending_rows
        else '<span class="status-badge status-muted">无待确认试投词</span>'
    )
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (
            str(row.get("marketplace") or "N/A").upper(),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
            str(row.get("product_name") or "N/A"),
        )
        grouped.setdefault(key, []).append(row)

    def product_budget_text(product_rows: list[dict[str, str]]) -> str:
        total = sum(shared._num_from_text(row.get("suggested_daily_budget")) for row in product_rows)
        first_budget = str((product_rows[0] if product_rows else {}).get("suggested_daily_budget") or "")
        symbol_match = re.search(r"[£$€]", first_budget)
        symbol = symbol_match.group(0) if symbol_match else ""
        return f"{symbol}{total:.2f}/天" if total else "N/A"

    def product_bid_text(product_rows: list[dict[str, str]]) -> str:
        mins = [shared._num_from_text(row.get("suggested_bid_min")) for row in product_rows]
        maxes = [shared._num_from_text(row.get("suggested_bid_max")) for row in product_rows]
        mins = [value for value in mins if value]
        maxes = [value for value in maxes if value]
        first_bid = str((product_rows[0] if product_rows else {}).get("suggested_bid_min") or "")
        symbol_match = re.search(r"[£$€]", first_bid)
        symbol = symbol_match.group(0) if symbol_match else ""
        if not mins or not maxes:
            return "N/A"
        return f"{symbol}{min(mins):.2f} 至 {symbol}{max(maxes):.2f}"

    parts = [
        '<section class="ad-section growth-test-section" id="growth-test-actions">',
        f'<div class="ad-section-header"><h3>小预算试投词</h3>{badge}</div>',
        _render_growth_test_copy_boxes(shared, rows),
    ]
    parts.extend(["</section>"])
    return "".join(parts)


def _render_ad_action_banner(
    shared: Any,
    rows: list[dict[str, str]],
    *,
    anchor_id: str,
    hidden_low_click_count: int = 0,
) -> str:
    pending_rows = [row for row in rows if _ad_status_key(shared, row) == "pending"]
    done_count = sum(1 for row in rows if _ad_status_key(shared, row) == "done")
    watch_count = sum(1 for row in rows if _ad_status_key(shared, row) == "watch")
    counts = {
        "加价": sum(
            1
            for row in pending_rows
            if _ad_action_key(shared, _ad_action_label(shared, row)) == "bid-up"
        ),
        "降竞价": sum(
            1
            for row in pending_rows
            if _ad_action_key(shared, _ad_action_label(shared, row)) == "bid-down"
        ),
        "否词": sum(
            1
            for row in pending_rows
            if _ad_action_key(shared, _ad_action_label(shared, row)) == "negative"
        ),
        "暂停": sum(
            1
            for row in pending_rows
            if _ad_action_key(shared, _ad_action_label(shared, row)) == "pause"
        ),
    }
    total = len(pending_rows)
    if total > 0:
        summary = f"先处理 {total} 条广告动作。"
        chips = "".join(
            f'<span class="metric-badge">{html.escape(label)} {count}</span>'
            for label, count in counts.items()
            if count > 0
        ) or '<span class="metric-badge">待确认 0</span>'
        cta = f'<a class="button-link" href="#{html.escape(anchor_id)}">直接去执行区</a>'
        status = '<span class="status-badge status-pending">今天有广告动作</span>'
    else:
        summary = "今天没有新的广告后台执行动作。观察项只做核对，不复制到后台。"
        chips = "".join(
            [
                '<span class="metric-badge">待执行 0</span>',
                f'<span class="metric-badge">已执行留档 {done_count}</span>' if done_count else "",
                f'<span class="metric-badge">观察项 {watch_count}</span>' if watch_count else "",
                f'<span class="metric-badge">低点击隐藏项 {hidden_low_click_count}</span>' if hidden_low_click_count else "",
            ]
        )
        cta = f'<a class="button-link" href="#{html.escape(anchor_id)}">查看广告区</a>'
        status = '<span class="status-badge status-muted">今天无新广告动作</span>'
    return "\n".join(
        [
            '<section class="section-card">',
            '<div class="ad-section-header">',
            "<h2>广告动作状态</h2>",
            status,
            "</div>",
            f'<p class="subtle">{html.escape(summary)}</p>',
            f'<div class="metric-row">{chips}</div>',
            f'<div class="summary-action">{cta}</div>',
            "</section>",
        ]
    )


def _is_observation_only_summary_row(shared: Any, row: dict[str, str]) -> bool:
    status = str(row.get("confirmed_status") or "")
    gate = str(row.get("fusion_action_gate") or "")
    action_text = " ".join(
        str(row.get(key) or "")
        for key in [
            "today_action",
            "suggested_action",
            "final_action",
            "primary_reason",
            "review_reason",
            "key_evidence",
        ]
    )
    if status in {"仅背景参考", "待复查", "已忽略"}:
        return True
    if gate == "collect_evidence_only":
        return True
    observation_tokens = [
        "只观察",
        "保守跑",
        "不加预算",
        "不输出强运营动作",
        "补足自动证据",
        "先不做强操作",
        "等待",
        "数据不足",
    ]
    return any(token in action_text for token in observation_tokens)


def _render_ad_workbench(
    shared: Any,
    rows: list[dict[str, str]],
    *,
    all_marketplaces: bool,
    hidden_low_click_count: int = 0,
    title: str = "今天广告动作",
    marketplace_hint: str = "",
    anchor_id: str = "today-ad-actions",
    growth_test_rows: list[dict[str, str]] | None = None,
    keyword_review_count: int = 0,
    history_anchor: str = "action-effect-review",
) -> str:
    summary = _ad_summary(
        shared, rows, all_marketplaces=all_marketplaces, marketplace_hint=marketplace_hint
    )
    pending_rows = [row for row in rows if _ad_status_key(shared, row) == "pending"]
    done_rows = [row for row in rows if _ad_status_key(shared, row) == "done"]
    watch_rows = [row for row in rows if _ad_status_key(shared, row) == "watch"]
    pending_growth_rows = [
        row for row in list(growth_test_rows or []) if _ad_status_key(shared, row) == "pending"
    ]
    pending_count = len(pending_rows)
    pending_growth_count = len(pending_growth_rows)
    total_pending_count = pending_count + pending_growth_count
    workbench_status = (
        "".join(
            [
                f'<span class="status-badge status-pending">待处理 {total_pending_count}</span>',
                f'<span class="status-badge status-muted">广告动作 {pending_count}</span>',
                f'<span class="status-badge status-pending">小预算投词 {pending_growth_count}</span>',
                f'<a class="status-badge status-muted" href="#{html.escape(history_anchor)}">历史复盘 {keyword_review_count}</a>',
            ]
        )
        if total_pending_count
        else (
            '<span class="status-badge status-muted">今天无新广告动作</span>'
            f'<a class="status-badge status-muted" href="#{html.escape(history_anchor)}">历史复盘 {keyword_review_count}</a>'
        )
    )
    summary_with_growth = dict(summary)
    summary_with_growth["小预算投词"] = str(pending_growth_count)
    summary_with_growth["历史复盘"] = str(keyword_review_count)
    refresh_control = (
        '<div class="ad-feedback-refresh" data-ad-feedback-refresh>'
        '<button class="button-link secondary" type="button" data-run-report-action="report-refresh" data-run-report-reload-on-done="true">重新生成报告</button>'
        '<span class="subtle" data-run-report-status="report-refresh">已记录完成项后，点击刷新报告进入冷却和复盘。</span>'
        "</div>"
    )
    toolbar = [
        '<div class="ad-toolbar">',
        '<input type="search" placeholder="搜索词 / ASIN / SKU / 产品 / Campaign" data-ad-search>',
        '<select data-ad-status><option value="all">全部状态</option><option value="pending">待确认</option><option value="done">已执行</option><option value="watch">观察</option></select>',
        '<select data-ad-action><option value="all">全部动作</option><option value="bid-up">加价</option><option value="bid-down">降竞价</option><option value="negative">否词</option><option value="pause">暂停</option><option value="create-exact">拉精准</option><option value="growth-test">小预算试投</option><option value="watch">观察</option></select>',
    ]
    if all_marketplaces:
        toolbar.append('<select data-ad-marketplace><option value="all">全部站点</option><option value="US">US</option><option value="UK">UK</option><option value="DE">DE</option></select>')
    toolbar.append("</div>")
    pending_badge = (
        f'<span class="status-badge status-pending">待确认 {html.escape(summary["待处理"])}</span>'
        if int(summary["待处理"]) > 0
        else '<span class="status-badge status-muted">无待确认动作</span>'
    )
    parts: list[str] = [
        f'<div class="ad-workbench" id="{html.escape(anchor_id)}">',
        '<div class="ad-workbench-head">',
        f'<div class="ad-head-left"><h2>{html.escape(title)}</h2><p class="subtle">这里是产品判断卡过滤后的广告动作和小预算投词。先确认产品卡允许范围，再复制到广告后台。</p></div>',
        f'<div class="ad-head-right">{workbench_status}{refresh_control}</div>',
        "</div>",
        '<div class="ad-summary-grid">',
        *(
            f'<div class="ad-summary-card"><span>{html.escape(k)}</span><strong>{html.escape(v)}</strong></div>'
            for k, v in summary_with_growth.items()
        ),
        "</div>",
        "".join(toolbar),
        f'<p class="subtle ad-filter-scope">筛选栏只筛当前工作台和小预算投词；完整词级历史复盘见 <a href="#{html.escape(history_anchor)}">历史复盘 {keyword_review_count} 条</a>。低点击隐藏项 {hidden_low_click_count} 条在 Excel。</p>',
        '<section class="ad-section primary-action"><div class="ad-section-header"><h3>复制到广告后台</h3>'
        + pending_badge
        + "</div>",
        '<p class="ad-boundary-note">执行前核对产品卡允许范围；只复制待确认动作；执行后留档，观察项不操作。</p>',
        _render_ad_copy_boxes(shared, pending_rows, "pending-ad"),
        "</section>",
        _render_growth_test_section(shared, list(growth_test_rows or [])),
    ]
    if done_rows:
        parts.extend(
            [
                '<section class="ad-section is-collapsed"><div class="ad-section-header"><h3>已执行留档</h3><button class="collapsible-toggle" type="button" data-collapse-toggle>展开</button></div><div class="collapsible-body">',
                _render_ad_task_cards(shared, done_rows),
                "</div></section>",
            ]
        )
    if watch_rows:
        parts.extend(
            [
                '<section class="ad-section is-collapsed"><div class="ad-section-header"><h3>仅观察</h3><button class="collapsible-toggle" type="button" data-collapse-toggle>展开</button></div><div class="collapsible-body">',
                _render_ad_task_cards(shared, watch_rows),
                "</div></section>",
            ]
        )
    if hidden_low_click_count:
        parts.append(f'<p class="subtle">低点击隐藏项 {hidden_low_click_count} 条，完整明细见 Excel。</p>')
    parts.append("</div>")
    return "".join(parts)


def _render_ad_workbench_status_only(
    shared: Any,
    rows: list[dict[str, str]],
    *,
    hidden_low_click_count: int = 0,
    marketplace_hint: str = "",
    section_id: str = "",
    show_details: bool = False,
    collapsed: bool = False,
) -> str:
    done_count = sum(1 for row in rows if _ad_status_key(shared, row) == "done")
    watch_count = sum(1 for row in rows if _ad_status_key(shared, row) == "watch")
    done_rows = [row for row in rows if _ad_status_key(shared, row) == "done"]
    watch_rows = [row for row in rows if _ad_status_key(shared, row) == "watch"]
    market_label = str(marketplace_hint or "本站").upper()
    id_attr = f' id="{html.escape(section_id)}"' if section_id else ""
    detail_available = bool(show_details and (done_rows or watch_rows))
    status_note = (
        f"{market_label} 今天没有新的广告后台执行动作。观察项不复制到后台，可展开核对广告线索。"
        if detail_available
        else f"{market_label} 今天没有新的广告后台执行动作。观察项不复制到后台。"
    )
    badges = [
        '<span class="metric-badge">待执行 0</span>',
        f'<span class="metric-badge">已执行留档 {done_count}</span>' if done_count else "",
        f'<span class="metric-badge">观察项 {watch_count}</span>' if watch_count else "",
        f'<span class="metric-badge">低点击隐藏项 {hidden_low_click_count}</span>' if hidden_low_click_count else "",
    ]
    state_class = " is-collapsed" if collapsed else ""
    toggle_html = (
        '<button class="collapsible-toggle" type="button" data-collapse-toggle>展开</button>'
        if collapsed
        else ""
    )
    body_start = '<div class="collapsible-body">' if collapsed else ""
    body_end = "</div>" if collapsed else ""
    parts = [
        f'<section class="section-card{state_class}"{id_attr}>',
        f'<div class="ad-section-header"><h2>广告状态</h2><span class="status-badge status-muted">待确认 0</span>{toggle_html}</div>',
        f'<p class="subtle">{html.escape(status_note)}</p>',
        body_start,
        '<div class="metric-row">',
        "".join(badges),
        "</div>",
    ]
    if section_id:
        parts.append('<div class="summary-action"><a class="button-link" href="#today-ad-actions-all">查看广告区</a></div>')
    if detail_available:
        parts.extend(
            [
                '<details class="ad-zero-details">',
                "<summary>查看观察项和已执行留档</summary>",
            ]
        )
        if watch_rows:
            parts.extend(
                [
                    '<section class="ad-section"><div class="ad-section-header"><h3>观察项，不操作</h3></div>',
                    _render_ad_task_cards(shared, watch_rows),
                    "</section>",
                ]
            )
        if done_rows:
            parts.extend(
                [
                    '<section class="ad-section"><div class="ad-section-header"><h3>已执行留档</h3></div>',
                    _render_ad_task_cards(shared, done_rows),
                    "</section>",
                ]
            )
        parts.append("</details>")
    parts.append(body_end)
    parts.append("</section>")
    return "".join(part for part in parts if part)


def _render_search_queue_by_marketplace(shared: Any, rows: list[dict[str, str]]) -> str:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        marketplace = str(row.get("marketplace") or "N/A").upper()
        grouped.setdefault(marketplace, []).append(row)
    marketplaces = ["US", "UK", "DE"]
    marketplaces.extend(
        sorted(
            (marketplace for marketplace in grouped if marketplace not in marketplaces),
            key=shared._marketplace_sort_key,
        )
    )
    parts: list[str] = []
    for marketplace in marketplaces:
        marketplace_rows = grouped.get(marketplace, [])
        parts.append(
            "\n".join(
                [
                    '<div class="marketplace-queue">',
                    f'<h3 class="marketplace-queue-title">{html.escape(marketplace)}</h3>',
                    '<div class="queue-subtitle">广告复制区（直接复制到 ERP 操作）</div>',
                    _render_ad_copy_sections(shared, marketplace_rows)
                    if marketplace_rows
                    else '<p class="subtle">当前没有达到 HTML 展示阈值的搜索词/ASIN。</p>',
                    '<div class="queue-subtitle">证据和解释区（只解释原因，不重复动作）</div>',
                    _render_search_queue_evidence_groups(shared, marketplace_rows)
                    if marketplace_rows
                    else '<p class="subtle">当前没有需要展开的搜索词解释。</p>',
                    "</div>",
                ]
            )
        )
    return "".join(parts)
