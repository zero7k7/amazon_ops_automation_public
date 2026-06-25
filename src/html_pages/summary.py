from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def write_summary_html(shared: Any, results: list[dict], output_path: Path, report_date: str) -> None:
    results = shared._sort_results_by_marketplace(results)
    all_tasks: list[dict[str, str]] = []
    all_reviews: list[dict[str, str]] = []
    all_search: list[dict[str, str]] = []
    all_listing_reviews: list[dict[str, str]] = []
    all_yesterday_attribution: list[dict[str, str]] = []
    all_action_effect_reviews: list[dict[str, str]] = []
    all_keyword_action_effect_reviews: list[dict[str, str]] = []
    all_inventory_replenishment: list[dict[str, str]] = []
    all_product_cards: list[dict[str, str]] = []
    quality_rows: list[dict[str, str]] = []
    for result in results:
        if not result.get("has_data"):
            continue
        view = result.get("report_view", {})
        all_tasks.extend(view.get("today_task_queue_rows", []))
        all_reviews.extend(view.get("tomorrow_review_rows", []))
        all_search.extend(view.get("html_search_term_processing_queue_rows", []))
        all_inventory_replenishment.extend(view.get("inventory_replenishment_rows", []))
        for row in view.get("listing_price_diagnosis_rows", []):
            all_listing_reviews.append(dict(row))
        all_yesterday_attribution.extend(view.get("yesterday_attribution_rows", []))
        all_product_cards.extend(view.get("product_operation_cards", []))
        for row in view.get("action_effect_review_rows", []):
            if row not in all_action_effect_reviews:
                all_action_effect_reviews.append(row)
        for row in view.get("keyword_action_effect_review_rows", []):
            if row not in all_keyword_action_effect_reviews:
                all_keyword_action_effect_reviews.append(row)
        quality_rows.append(
            {
                "站点": result.get("marketplace", "N/A"),
                "状态": view.get("analysis_status", "N/A"),
                "摘要": view.get("issue_summary", "N/A"),
            }
        )

    def is_done(row: dict[str, str]) -> bool:
        return str(row.get("confirmed_status") or "") == "已执行"

    def clean_text(value: object, limit: int = 64) -> str:
        text = str(value or "").replace("搜索词处理", "广告处理").strip()
        replacements = {
            "暂时不加广告预算；核心词不直接否；明显不相关词才否定精准；相关高花费 0 单词先降竞价；等人工确认价格、主图、评价、Coupon、竞品和广告流量后再决定是否改 Listing。": "广告端先保守，不加预算；只处理明确无效流量。",
            "等人工确认价格、主图、评价、Coupon、竞品和广告流量后再决定是否改 Listing": "先看价格/Coupon/配送/竞品，再决定是否动页面。",
            "执行未满3天，不判断该词效果。": "未满3天，先不评价效果。",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        if len(text) > limit:
            return text[:limit].rstrip() + "..."
        return text or "N/A"

    def item_title(row: dict[str, str]) -> str:
        marketplace = str(row.get("marketplace") or "").upper()
        product = str(row.get("product_name") or row.get("产品") or row.get("search_term_or_target") or "N/A")
        return f"{marketplace}｜{product}" if marketplace else product

    def item_key(row: dict[str, str]) -> tuple[str, str, str]:
        return (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").upper(),
        )

    product_card_lookup = {
        item_key(row): row
        for row in all_product_cards
        if any(part for part in item_key(row))
    }

    def matching_product_card(row: dict[str, str]) -> dict[str, str]:
        return product_card_lookup.get(item_key(row), {})

    def summary_risk_brief(row: dict[str, str], card: dict[str, str]) -> str:
        reasons: list[str] = []
        if card:
            profit = shared._optional_num_from_text(card.get("profit_before_ads_per_unit"))
            if profit is not None and profit <= 0:
                reasons.append("利润不支持放量")
            inventory = str(card.get("inventory_constraint") or "")
            if inventory in {"LOW_STOCK", "OUT_OF_STOCK", "RESTOCK_RECOVERY", "REPLENISH_SOON"}:
                inventory_labels = {
                    "LOW_STOCK": "低库存",
                    "OUT_OF_STOCK": "断货",
                    "RESTOCK_RECOVERY": "补货恢复期",
                    "REPLENISH_SOON": "进入补货窗口",
                }
                reasons.append(inventory_labels.get(inventory, inventory))
            frontend_text = " ".join(
                str(card.get(field) or "")
                for field in ["frontend_status", "frontend_auto_conclusion_label", "frontend_search_findings"]
            )
            if any(token in frontend_text for token in ["自动证据不足", "待前台检查", "沿用", "读取失败", "拦截"]):
                reasons.append("前台证据不足")
            elif any(token in frontend_text for token in ["弱势", "评分", "评论", "Coupon", "Buy Box", "竞品"]):
                reasons.append("前台有弱项")
            natural_orders = shared._optional_num_from_text(card.get("natural_orders"))
            ad_orders = shared._optional_num_from_text(card.get("ad_orders"))
            total_orders = shared._optional_num_from_text(card.get("total_orders"))
            if total_orders is not None and total_orders > 0 and natural_orders is not None and ad_orders is not None:
                if natural_orders >= max(ad_orders, 1) and ad_orders <= 0:
                    reasons.append("总单主要靠自然单")
            history = str(card.get("feedback_cooldown_status") or card.get("keyword_memory_summary") or "")
            if history:
                reasons.append("有历史执行记录")
        fallback = str(row.get("primary_reason") or row.get("review_reason") or row.get("key_evidence") or "").strip()
        return "；".join(reasons[:3]) or clean_text(fallback, 40)

    def summary_item(title: str, reason: object, action: object = "", status: str = "") -> str:
        status_html = f' <span class="{shared._confirmed_tag(status)}">{html.escape(status)}</span>' if status else ""
        return (
            '<div class="summary-item">'
            f"<strong>{html.escape(title)}{status_html}</strong>"
            f'<div class="subtle">{shared._inline_markup(clean_text(reason))}</div>'
            + (f"<div>{shared._inline_markup(clean_text(action))}</div>" if action else "")
            + "</div>"
        )

    counters = shared._collect_report_counters(all_tasks, all_search, all_reviews, quality_rows, all_listing_reviews)
    non_cost_tasks = [row for row in all_tasks if row.get("action_group") != "成本 / 利润动作"]
    cost_rows = [
        row
        for row in all_tasks
        if row.get("action_group") == "成本 / 利润动作"
        and not is_done(row)
        and not shared._is_observation_only_summary_row(row)
    ]
    pending_tasks = [row for row in non_cost_tasks if not is_done(row)]
    executable_pending_tasks = [row for row in pending_tasks if not shared._is_observation_only_summary_row(row)]
    pending_p0_rows = [row for row in executable_pending_tasks if row.get("priority") == "P0"]
    pending_p1_rows = [row for row in executable_pending_tasks if row.get("priority") == "P1"]
    pending_ad_rows = [
        row
        for row in all_search
        if not is_done(row) and str(row.get("copy_action_line") or "") in shared.ACTIONABLE_COPY_LINES
    ]
    executed_rows = [row for row in [*all_tasks, *all_search] if is_done(row)]

    if pending_p0_rows:
        lead = pending_p0_rows[0]
        card = matching_product_card(lead)
        action = clean_text(lead.get("today_action") or card.get("fusion_today_action") or "先处理今日动作", 28)
        conclusion = f"今天先处理 {item_title(lead)}。{summary_risk_brief(lead, card)}；{action}"
    elif pending_p1_rows:
        lead = pending_p1_rows[0]
        card = matching_product_card(lead)
        conclusion = f"今天没有新的 P0，先查 {item_title(lead)}。{summary_risk_brief(lead, card)}；先补关键证据，再决定是否放量。"
    elif pending_ad_rows:
        conclusion = "今天先做广告止损。产品级没有明确放量条件，优先处理有证据的降竞价、否词和暂停项。"
    elif executed_rows:
        conclusion = "今天先看复盘。已执行对象仍在 3 天或 7 天观察窗口，先看结果，避免重复改同一批动作。"
    else:
        conclusion = "今天没有明确强动作。先看补货、前台证据缺口和复盘对象，避免在低样本上做强判断。"

    today_do_items: list[str] = []
    today_do_candidates = [*pending_p0_rows, *pending_p1_rows, *cost_rows]
    for row in today_do_candidates[:3]:
        card = matching_product_card(row)
        reason = card.get("decision_reason") or row.get("primary_reason") or row.get("review_reason") or row.get("key_evidence") or "N/A"
        action = row.get("today_action") or card.get("fusion_today_action") or row.get("tomorrow_check") or "先看详细报告"
        today_do_items.append(summary_item(item_title(row), reason, action, str(row.get("confirmed_status") or "")))
    if not today_do_items and pending_ad_rows:
        by_market: dict[str, int] = {}
        for row in pending_ad_rows:
            market = str(row.get("marketplace") or "N/A").upper()
            by_market[market] = by_market.get(market, 0) + 1
        today_do_items.append(
            summary_item(
                "ALL｜广告工作台",
                "；".join(f"{k} {v} 条待执行" for k, v in sorted(by_market.items())),
                "优先处理最有价值的待执行广告动作，不要全量机械执行。",
            )
        )

    dont_do_items: list[str] = []
    cooldown_rows = [row for row in all_reviews if "冷却" in str(row.get("review_reason") or "")][:3]
    for row in cooldown_rows:
        dont_do_items.append(
            summary_item(
                item_title(row),
                "已执行动作冷却中",
                row.get("tomorrow_check") or "先等3天/7天数据，不重复操作。",
                str(row.get("confirmed_status") or "已执行"),
            )
        )
    keyword_wait_rows = [
        row for row in all_keyword_action_effect_reviews
        if str(row.get("review_window") or "") == "未满3天" or str(row.get("judgement") or "") == "样本不足"
    ]
    for row in keyword_wait_rows[: max(0, 3 - len(dont_do_items))]:
        target = str(row.get("search_term_or_target") or item_title(row) or "N/A")
        dont_do_items.append(
            summary_item(
                f"{str(row.get('marketplace') or '').upper()}｜{target}",
                row.get("judgement") or row.get("review_window") or "样本不足",
                "今天先别重复加码，等窗口够了再判断。",
            )
        )
    observation_rows = [row for row in all_tasks if not is_done(row) and shared._is_observation_only_summary_row(row)]
    for row in observation_rows[: max(0, 3 - len(dont_do_items))]:
        dont_do_items.append(
            summary_item(
                item_title(row),
                row.get("primary_reason") or row.get("review_reason") or "仅观察或补证据",
                row.get("today_action") or "今天不做强操作，等数据窗口或前台证据补齐。",
                str(row.get("confirmed_status") or "观察"),
            )
        )
    listing_block_rows = [
        row
        for row in pending_tasks
        if "Listing" in str(row.get("issue_type") or "") or "暂时不加广告预算" in str(row.get("today_action") or "")
    ]
    for row in listing_block_rows[: max(0, 3 - len(dont_do_items))]:
        dont_do_items.append(
            summary_item(
                item_title(row),
                row.get("primary_reason") or "待人工确认",
                "先看价格/Coupon/配送/竞品，不要继续堆广告动作。",
            )
        )

    def review_value_score(row: dict[str, str]) -> tuple[int, int, int, str]:
        judgement = str(row.get("judgement") or "")
        next_step = str(row.get("next_step") or "")
        window = str(row.get("review_window") or "")
        product = str(row.get("product_name") or row.get("search_term_or_target") or "")
        score = 0
        if judgement in {"暂未改善", "初步有效", "有改善迹象"}:
            score += 5
        if judgement in {"待7天确认", "待人工判定有效/无效"}:
            score += 4
        if "不要继续加价" in next_step or "回到原竞价" in next_step or "保留当前竞价" in next_step:
            score += 4
        if "优先要求补竞品/页面证据" in next_step or "确认是否否词匹配类型" in next_step:
            score += 3
        if window == "3天后复盘":
            score += 2
        days = shared._num_from_text(row.get("days_since_execution")) or 0
        return (-score, -int(days), 0 if str(row.get("search_term_or_target") or "") else 1, product)

    review_watch_items: list[str] = []
    review_candidates = sorted([*all_keyword_action_effect_reviews, *all_action_effect_reviews], key=review_value_score)
    for row in review_candidates[:3]:
        label_target = str(row.get("search_term_or_target") or row.get("product_name") or "N/A")
        title = f"{str(row.get('marketplace') or '').upper()}｜{label_target}"
        reason = f"{row.get('review_window') or row.get('judgement') or '待复查'}｜{clean_text(row.get('effect_metrics') or '', 72)}"
        action = row.get("next_step") or "继续观察，等待足够样本。"
        review_watch_items.append(summary_item(title, reason, action, str(row.get("judgement") or "")))

    def inventory_priority(row: dict[str, str]) -> tuple[int, float, float, str]:
        status = str(row.get("stock_status_label") or "")
        level = str(row.get("stock_risk_level") or "")
        coverage_source = row.get("days_of_cover")
        if coverage_source in ("", None):
            coverage_source = row.get("coverage_days")
        qty_source = row.get("recommended_reorder_qty")
        if qty_source in ("", None):
            qty_source = row.get("recommended_replenishment_qty")
        coverage = shared._optional_num_from_text(coverage_source)
        qty = shared._optional_num_from_text(qty_source) or 0
        if level == "OUT_OF_STOCK":
            priority = 0
        elif level == "LOW_STOCK" or "低库存" in status:
            priority = 1
        elif level == "REPLENISH_SOON" or "进入补货窗口" in status:
            priority = 2
        else:
            priority = 9
        return (priority, coverage if coverage is not None else 99999, -qty, str(row.get("product_name") or ""))

    replenishment_items: list[str] = []
    actionable_inventory_levels = {"OUT_OF_STOCK", "LOW_STOCK", "REPLENISH_SOON"}

    def is_actionable_inventory_row(row: dict[str, str]) -> bool:
        level = str(row.get("stock_risk_level") or "")
        status = str(row.get("stock_status_label") or "")
        if level in actionable_inventory_levels:
            return True
        if not level and any(token in status for token in ["断货", "低库存", "进入补货窗口"]):
            return True
        return False

    replenishment_rows = [
        row for row in sorted(all_inventory_replenishment, key=inventory_priority)
        if "暂不需要" not in str(row.get("replenishment_advice") or "")
        and is_actionable_inventory_row(row)
    ]
    for row in replenishment_rows[:3]:
        market = str(row.get("marketplace") or "").upper()
        product = str(row.get("product_name") or "N/A")
        title = f"{market}｜{product}" if market else product
        coverage = row.get("days_of_cover")
        if coverage in ("", None):
            coverage = row.get("coverage_days")
        qty = row.get("recommended_reorder_qty")
        if qty in ("", None):
            qty = row.get("recommended_replenishment_qty")
        available_value = row.get("available_stock")
        if available_value in ("", None):
            available_value = row.get("current_inventory")
        reason_parts = [
            str(row.get("stock_status_label") or "补货提醒"),
            f"可用库存 {available_value}" if available_value not in ("", None) else "可用库存缺失",
            f"覆盖 {coverage} 天" if coverage not in ("", None) else "",
        ]
        if qty not in ("", None):
            reason_parts.append(f"建议补 {qty}")
        replenishment_items.append(
            summary_item(
                title,
                "；".join(str(part) for part in reason_parts if str(part).strip()),
                row.get("replenishment_advice") or "先核对在途和本地库存，再决定采购量。",
                str(row.get("stock_status_label") or ""),
            )
        )

    site_attribution_rows = [
        row for row in all_yesterday_attribution
        if str(row.get("product_name") or "") == "站点整体"
    ]
    site_attribution_rows = sorted(site_attribution_rows, key=lambda row: shared._marketplace_sort_key(row.get("marketplace")))[:3]
    yesterday_items: list[str] = []
    for row in site_attribution_rows:
        market = str(row.get("marketplace") or "N/A")
        kind = str(row.get("attribution_type") or "待判断")
        evidence_parts = [part.strip() for part in str(row.get("evidence") or "").split("；") if part.strip()]
        compact_evidence = "；".join(evidence_parts[:2]) if evidence_parts else "暂无异常摘要"
        if kind == "流量下降":
            action = "先核查预算、活动状态和核心词展示。"
        elif kind == "点击后不转化":
            action = "先看高花费词、价格/Coupon和配送。"
        elif kind == "广告归因弱":
            action = "对比自然出单和广告活动结构。"
        else:
            action = "按当前节奏观察。"
        yesterday_items.append(summary_item(f"{market}｜{kind}", compact_evidence, action))

    p0_card_class = "metric-card status-danger" if counters["p0"] else "metric-card"
    p1_card_class = "metric-card status-warn" if counters["p1"] else "metric-card"
    cost_card_class = "metric-card status-warn" if counters["cost"] else "metric-card"
    body = [
        '<div class="report-card hero">',
        "<div>",
        f"<h1>三分钟摘要｜{html.escape(report_date)}</h1>",
        '<div class="hero-meta">运营开工版：先做什么、先别做什么、昨天动作今天重点盯什么。</div>',
        shared._render_nav("summary"),
        "</div>",
        "</div>",
        '<section class="section-card"><h2>今日开工结论</h2>',
        f'<div class="compact-note"><p>{html.escape(conclusion)}</p></div>',
        "</section>",
        '<section class="section-card"><h2>今日优先级概览</h2><div class="priority-grid">',
        f'<div class="{p0_card_class}">P0 待判断<strong>{counters["p0"]}</strong></div>',
        f'<div class="{p1_card_class}">P1 今日检查<strong>{counters["p1"]}</strong></div>',
        f'<div class="metric-card status-pass">已执行待复盘<strong>{counters["executed"]}</strong></div>',
        f'<div class="{cost_card_class}">成本/利润核对<strong>{counters["cost"]}</strong></div>',
        "</div></section>",
        '<section class="section-card"><h2>今天先做</h2>',
        '<div class="summary-list">' + "".join(today_do_items) + "</div>" if today_do_items else '<p class="subtle">当前没有新的强动作，优先看下方复盘和观察。</p>',
        "</section>",
        '<section class="section-card"><h2>今天先别做</h2>',
        '<div class="summary-list">' + "".join(dont_do_items) + "</div>" if dont_do_items else '<p class="subtle">当前没有明显需要刻意暂停的对象，但仍应避免重复操作。</p>',
        "</section>",
        '<section class="section-card"><h2>昨天动作今天要盯</h2>',
        '<div class="summary-list">' + "".join(review_watch_items) + "</div>" if review_watch_items else '<p class="subtle">当前没有高价值复盘对象；已执行动作继续按 3 天 / 7 天窗口观察。</p>',
        "</section>",
        '<section class="section-card"><h2>补货先看</h2>',
        '<div class="summary-list">' + "".join(replenishment_items) + "</div>" if replenishment_items else '<p class="subtle">当前没有需要放在三分钟摘要里的补货项；完整库存表在 ALL 工作台和 Excel。</p>',
        "</section>",
        '<section class="section-card"><h2>昨日异常简版</h2>',
        '<div class="summary-list">' + "".join(yesterday_items) + "</div>" if yesterday_items else '<p class="subtle">暂无昨日异常摘要。</p>',
        "</section>",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shared._write_page(output_path, f"三分钟摘要｜{report_date}", "\n".join(body))
