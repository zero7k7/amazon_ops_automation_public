from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def write_recommendations_workbench_html(shared: Any, results: list[dict], output_path: Path, report_date: str) -> None:
    results = shared._sort_results_by_marketplace(results)
    quality_rows: list[dict[str, str]] = []
    all_tasks: list[dict[str, str]] = []
    all_review: list[dict[str, str]] = []
    all_search: list[dict[str, str]] = []
    all_listing_reviews: list[dict[str, str]] = []
    all_yesterday_attribution: list[dict[str, str]] = []
    all_action_effect_reviews: list[dict[str, str]] = []
    all_keyword_action_effect_reviews: list[dict[str, str]] = []
    all_scale_candidates: list[dict[str, str]] = []
    all_scale_keywords: list[dict[str, str]] = []
    all_growth_tests: list[dict[str, str]] = []
    all_frontend_checks: list[dict[str, str]] = []
    all_inventory_replenishment: list[dict[str, str]] = []
    all_product_final_decisions: list[dict[str, str]] = []
    all_product_operation_cards: list[dict[str, str]] = []
    quality_rows: list[dict[str, str]] = []
    frontend_coverage_totals = {
        "frontend_queue_total": 0,
        "frontend_usable_evidence_count": 0,
        "frontend_decision_ready_count": 0,
        "frontend_reference_evidence_count": 0,
        "frontend_live_success_count": 0,
        "frontend_cached_count": 0,
        "frontend_pending_or_stale_count": 0,
        "frontend_search_success_count": 0,
        "frontend_search_partial_count": 0,
        "frontend_product_page_success_count": 0,
        "frontend_competitor_search_success_count": 0,
        "frontend_own_sellersprite_count": 0,
        "frontend_own_sellersprite_today_count": 0,
        "frontend_own_sellersprite_cache_count": 0,
        "frontend_own_sellersprite_pending_count": 0,
        "frontend_own_sellersprite_failed_count": 0,
        "frontend_sellersprite_trend_ready_count": 0,
        "frontend_competitor_discovery_count": 0,
        "frontend_competitor_pool_count": 0,
        "frontend_competitor_pool_today_count": 0,
        "frontend_competitor_pool_cache_count": 0,
        "frontend_competitor_pool_pending_count": 0,
        "frontend_competitor_pool_failed_count": 0,
        "frontend_competitor_sellersprite_count": 0,
        "frontend_competitor_sellersprite_today_count": 0,
        "frontend_competitor_sellersprite_cache_count": 0,
        "frontend_competitor_sellersprite_pending_count": 0,
        "frontend_competitor_sellersprite_asin_count": 0,
        "frontend_amazon_search_validation_count": 0,
        "frontend_scalable_strong_count": 0,
        "frontend_weak_defensive_count": 0,
        "frontend_insufficient_count": 0,
        "market_survey_complete_count": 0,
        "market_survey_usable_count": 0,
        "market_survey_insufficient_count": 0,
        "market_survey_failed_count": 0,
    }
    market_survey_score_total = 0.0
    for result in results:
        if not result.get("has_data"):
            continue
        view = result.get("report_view", {})
        all_tasks.extend(view.get("today_task_queue_rows", []))
        all_review.extend(view.get("tomorrow_review_rows", []))
        all_search.extend(view.get("html_search_term_processing_queue_rows", []))
        all_yesterday_attribution.extend(view.get("yesterday_attribution_rows", []))
        all_scale_candidates.extend(view.get("scale_rows", []))
        all_scale_keywords.extend(view.get("scale_keyword_rows", []))
        all_growth_tests.extend(view.get("growth_test_rows", []))
        all_frontend_checks.extend(view.get("frontend_check_queue_rows", []))
        all_inventory_replenishment.extend(view.get("inventory_replenishment_rows", []))
        all_product_final_decisions.extend(view.get("product_final_decision_rows", []))
        all_product_operation_cards.extend(view.get("product_operation_cards", []))
        coverage = view.get("frontend_coverage_summary", {})
        if isinstance(coverage, dict):
            for key in frontend_coverage_totals:
                frontend_coverage_totals[key] += int(float(coverage.get(key, 0) or 0))
            market_survey_score_total += float(coverage.get("market_survey_average_score", 0) or 0) * int(float(coverage.get("frontend_queue_total", 0) or 0))
        for row in view.get("action_effect_review_rows", []):
            if row not in all_action_effect_reviews:
                all_action_effect_reviews.append(row)
        for row in view.get("keyword_action_effect_review_rows", []):
            if row not in all_keyword_action_effect_reviews:
                all_keyword_action_effect_reviews.append(row)
        for row in view.get("listing_price_diagnosis_rows", []):
            row = dict(row)
            row["产品"] = f"{result.get('marketplace', 'N/A')}｜{row.get('产品', 'N/A')}"
            all_listing_reviews.append(row)
        quality_rows.append(
            {
                "站点": result.get("marketplace", "N/A"),
                "状态": view.get("analysis_status", "N/A"),
                "摘要": view.get("issue_summary", "N/A"),
            }
        )

    total_hidden_low_click = 0
    has_listing_reviews = False
    unknown_or_stale_enhanced = 0
    for result in results:
        if not result.get("has_data"):
            continue
        view = result.get("report_view", {})
        total_hidden_low_click += int(view.get("hidden_low_click_search_terms", 0) or 0)
        has_listing_reviews = has_listing_reviews or bool(view.get("listing_price_diagnosis_rows", []))
        unknown_or_stale_enhanced += sum(
            1
            for row in view.get("enhanced_status_rows", [])
            if str(row.get("新鲜度") or "") in {"unknown", "stale"} or str(row.get("周期类型") or "") == "unknown"
        )
    optimization_notes: list[str] = []
    for result in results:
        if not result.get("has_data"):
            continue
        for note in result.get("report_view", {}).get("runtime_policy_notes", []) or []:
            note = str(note)
            if note and note not in optimization_notes:
                optimization_notes.append(note)
    if total_hidden_low_click:
        optimization_notes.append(f"低点击观察对象合计 {total_hidden_low_click} 条已下沉到 Excel；主页只保留需要处理或留档的广告动作。")
    if has_listing_reviews:
        optimization_notes.append("Listing 待确认只保留计数和 Excel 明细，工作台不再展示通用材料块。")
    if unknown_or_stale_enhanced:
        optimization_notes.append(f"未知或陈旧周期增强数据 {unknown_or_stale_enhanced} 条仅作背景参考，不提升为强动作。")
    if not optimization_notes:
        optimization_notes.append("当前主页结构已收敛；若后续连续 2 天出现同类重复建议，可继续下调其主页优先级。")

    all_ad_queue_rows = all_search + shared._scale_keywords_as_ad_queue_rows(all_scale_keywords) + all_growth_tests
    counters = shared._collect_report_counters(all_tasks, all_ad_queue_rows, all_review, quality_rows, all_listing_reviews)
    review_count = counters["review"]
    quality_warn_count = counters["quality_warn"]
    cost_rows = [row for row in all_tasks if row.get("action_group") == "成本 / 利润动作"][:3]
    non_cost_tasks = [row for row in all_tasks if row.get("action_group") != "成本 / 利润动作"]
    pending_non_cost_tasks = shared._exclude_executed_rows(non_cost_tasks)
    executed_risk_tasks = shared._executed_risk_rows(non_cost_tasks)
    p1_non_listing_tasks = shared._exclude_listing_tasks(pending_non_cost_tasks, all_tasks)
    active_listing_reviews = shared._exclude_executed_rows(all_listing_reviews)
    p0_count = counters["p0"]
    listing_count = len(active_listing_reviews)
    p1_count = sum(1 for row in p1_non_listing_tasks if str(row.get("priority") or "") == "P1") + listing_count
    frontend_lookup = shared._build_frontend_lookup(all_frontend_checks)
    frontend_total = frontend_coverage_totals["frontend_queue_total"]
    market_survey_average = round(market_survey_score_total / frontend_total, 1) if frontend_total else 0
    frontend_coverage_summary = {
        **frontend_coverage_totals,
        "frontend_usable_evidence_rate": (frontend_coverage_totals["frontend_usable_evidence_count"] / frontend_total) if frontend_total else 0,
        "frontend_decision_ready_rate": (frontend_coverage_totals["frontend_decision_ready_count"] / frontend_total) if frontend_total else 0,
        "frontend_reference_evidence_rate": (frontend_coverage_totals["frontend_reference_evidence_count"] / frontend_total) if frontend_total else 0,
        "frontend_live_success_rate": (frontend_coverage_totals["frontend_live_success_count"] / frontend_total) if frontend_total else 0,
        "frontend_search_success_rate": (frontend_coverage_totals["frontend_search_success_count"] / frontend_total) if frontend_total else 0,
        "frontend_search_observed_rate": ((frontend_coverage_totals["frontend_search_success_count"] + frontend_coverage_totals["frontend_search_partial_count"]) / frontend_total) if frontend_total else 0,
        "market_survey_average_score": market_survey_average,
        "market_survey_average_score_label": f"{market_survey_average}/100" if frontend_total else "无市场调查队列",
        "market_survey_complete_label": (
            f'{frontend_coverage_totals["market_survey_complete_count"]}/{frontend_total}'
            if frontend_total
            else "无市场调查队列"
        ),
        "market_survey_usable_label": (
            f'{frontend_coverage_totals["market_survey_usable_count"]}/{frontend_total}'
            if frontend_total
            else "无市场调查队列"
        ),
        "market_survey_insufficient_label": (
            f'{frontend_coverage_totals["market_survey_insufficient_count"]}/{frontend_total}'
            if frontend_total
            else "无市场调查队列"
        ),
        "market_survey_failed_label": (
            f'{frontend_coverage_totals["market_survey_failed_count"]}/{frontend_total}'
            if frontend_total
            else "无市场调查队列"
        ),
        "frontend_decision_ready_label": (
            f'{frontend_coverage_totals["frontend_decision_ready_count"]}/{frontend_total} 强证据，{frontend_coverage_totals["frontend_decision_ready_count"] / frontend_total:.0%}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_reference_evidence_label": (
            f'{frontend_coverage_totals["frontend_reference_evidence_count"]}/{frontend_total} 背景参考，{frontend_coverage_totals["frontend_reference_evidence_count"] / frontend_total:.0%}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_coverage_label": (
            f'{frontend_coverage_totals["frontend_usable_evidence_count"]}/{frontend_total} 可用，{frontend_coverage_totals["frontend_usable_evidence_count"] / frontend_total:.0%}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_product_page_success_label": (
            f'{frontend_coverage_totals["frontend_product_page_success_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_competitor_search_success_label": (
            f'{frontend_coverage_totals["frontend_competitor_search_success_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_own_sellersprite_label": (
            f'{frontend_coverage_totals["frontend_own_sellersprite_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_competitor_discovery_label": (
            f'{frontend_coverage_totals["frontend_competitor_discovery_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_competitor_pool_label": (
            f'{frontend_coverage_totals["frontend_competitor_pool_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_competitor_sellersprite_label": (
            f'{frontend_coverage_totals["frontend_competitor_sellersprite_count"]}/{frontend_total}，'
            f'{frontend_coverage_totals["frontend_competitor_sellersprite_asin_count"]} ASIN'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_amazon_search_validation_label": (
            f'{frontend_coverage_totals["frontend_amazon_search_validation_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_scalable_strong_label": (
            f'{frontend_coverage_totals["frontend_scalable_strong_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_weak_defensive_label": (
            f'{frontend_coverage_totals["frontend_weak_defensive_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
        "frontend_insufficient_label": (
            f'{frontend_coverage_totals["frontend_insufficient_count"]}/{frontend_total}'
            if frontend_total
            else "无前台队列"
        ),
    }

    body = [
        '<div class="report-card hero">',
        "<div>",
        f"<h1>亚马逊运营工作台｜{html.escape(report_date)}</h1>",
        '<div class="hero-meta">先看产品级判断，再执行卡内广告动作。</div>',
        shared._render_nav("recommendations"),
        "</div>",
        "</div>",
        shared._render_boss_summary(
            report_date,
            p0_count,
            p1_count,
            listing_count,
            review_count,
            quality_warn_count,
            all_tasks,
            all_listing_reviews,
            all_ad_queue_rows,
            show_p1_link=bool(p1_non_listing_tasks),
        ),
        shared._render_local_data_submit_tool(),
        shared._render_ad_action_banner(all_ad_queue_rows, anchor_id="today-ad-actions-all", hidden_low_click_count=total_hidden_low_click),
        shared._render_product_operation_cards(all_product_operation_cards or all_product_final_decisions, frontend_coverage_summary, limit=4),
        shared._render_collapsed_section(
            "P0 明细",
            shared._render_task_cards(pending_non_cost_tasks, "P0", frontend_lookup=frontend_lookup),
            "首屏以产品级结论为准；需要查看长证据时再展开。",
            section_id="p0-actions",
        ),
        (
            '<section class="section-card">'
            + shared._render_ad_workbench(
                all_ad_queue_rows,
                all_marketplaces=True,
                hidden_low_click_count=total_hidden_low_click,
                title="今天广告动作",
                anchor_id="today-ad-actions-all",
                growth_test_rows=all_growth_tests,
                keyword_review_count=len(all_keyword_action_effect_reviews),
            )
            + "</section>"
            if any(shared._ad_status_key(row) == "pending" for row in all_ad_queue_rows) or all_growth_tests
            else shared._render_ad_workbench_status_only(
                all_ad_queue_rows,
                hidden_low_click_count=total_hidden_low_click,
                marketplace_hint="ALL",
                section_id="today-ad-actions-all",
                show_details=True,
                collapsed=True,
            )
        ),
        shared._render_frontend_status_summary(all_frontend_checks),
        shared._render_collapsed_section(
            "已执行但仍需复查",
            shared._render_task_cards(
                executed_risk_tasks,
                None,
                empty_message="当前没有已执行后仍保持 P0/P1 的风险项。",
                frontend_lookup=frontend_lookup,
            ),
            "已执行对象只在复查时展开。",
        ),
        (
            '<section class="section-card" id="p1-check"><h2>P1 今日检查</h2>'
            + shared._render_task_cards(p1_non_listing_tasks, "P1", empty_message="", frontend_lookup=frontend_lookup)
            + "</section>"
            if p1_non_listing_tasks
            else ""
        ),
        shared._render_collapsed_section("明日复查", shared._render_review_list(all_review, limit=5), "非今天执行项默认下沉。"),
        shared._render_collapsed_section(
            "库存补货提醒",
            shared._render_inventory_replenishment_cards(all_inventory_replenishment, limit=6),
            "库存先下沉，避免打断今天广告动作。",
            section_id="inventory-replenishment",
        ),
        shared._render_collapsed_section(
            "昨日异常归因摘要",
            '<p class="subtle">这里只看站点级方向；产品证据放在单站报告。</p>' + shared._render_yesterday_attribution(all_yesterday_attribution, limit=3, compact=True),
            "需要回看昨天异常方向时再展开。",
        ),
        shared._render_collapsed_section(
            "产品广告门禁",
            shared._render_product_final_decision_cards(all_product_final_decisions, limit=6),
            "这里保留产品级放行和拦截原因明细，首屏产品判断卡给今日主结论。",
        ),
        shared._render_collapsed_section(
            "执行后效果复盘",
            '<h3>词 / ASIN 级复盘</h3>'
            + shared._render_keyword_action_effect_review_rows(all_keyword_action_effect_reviews, limit=50)
            + '<h3>产品级复盘</h3>'
            + shared._render_action_effect_review_rows(all_action_effect_reviews, limit=5),
            "只在复查已执行动作效果时展开。",
            section_id="action-effect-review",
        ),
        shared._render_collapsed_section(
            "滞销观察池",
            '<p class="subtle">汇总页请进入单站报告查看滞销观察池明细。</p>',
            "中低风险和低样本对象默认下沉到 Excel。",
        ),
        shared._render_collapsed_section(
            "利润 / 成本待核对",
            shared._render_profit_cost_cards(cost_rows, limit=3),
            "财务类对象保留，但默认不放首屏。",
            section_id="cost-review",
        ),
        shared._render_collapsed_section(
            "数据质量总览",
            shared._render_table(["站点", "状态", "摘要"], quality_rows),
            "这里看 ALL 汇总状态；单站详细质量说明在各站点页面。",
        ),
        shared._render_collapsed_section(
            "统一临时处理原则",
            shared._render_common_principles_body(),
            "通用规则默认收起，避免每天重复占用主页面。",
        ),
        shared._render_collapsed_section("自我优化记录", shared._render_optimization_notes(optimization_notes), "保留学习记录，但不占主操作区。"),
    ]
    shared._write_page(output_path, f"亚马逊运营工作台｜{report_date}", "\n".join(body))
