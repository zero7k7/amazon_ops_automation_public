from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _apply_product_card_coverage_fallback(totals: dict[str, int], product_cards: list[dict[str, str]]) -> None:
    if not product_cards:
        return
    total = int(totals.get("frontend_queue_total") or 0)
    if not total:
        return
    if int(totals.get("frontend_own_sellersprite_count") or 0) <= 0:
        totals["frontend_own_sellersprite_count"] = sum(
            1
            for row in product_cards
            if str(row.get("seller_sprite_check_status") or "").strip()
            and str(row.get("seller_sprite_check_status") or "").strip() != "无缓存"
        )
    if int(totals.get("frontend_competitor_discovery_count") or 0) <= 0:
        totals["frontend_competitor_discovery_count"] = sum(
            1
            for row in product_cards
            if str(row.get("competitor_discovery_status") or "").strip() in {"已抓取", "沿用缓存", "缓存"}
        )
    if int(totals.get("frontend_competitor_sellersprite_count") or 0) <= 0:
        competitor_count = 0
        competitor_asins = 0
        for row in product_cards:
            try:
                count = int(float(row.get("competitor_sellersprite_asin_count") or 0))
            except (TypeError, ValueError):
                count = 0
            if count > 0:
                competitor_count += 1
                competitor_asins += count
        totals["frontend_competitor_sellersprite_count"] = competitor_count
        totals["frontend_competitor_sellersprite_asin_count"] = competitor_asins
    if int(totals.get("frontend_competitor_pool_count") or 0) <= 0:
        totals["frontend_competitor_pool_count"] = sum(
            1
            for row in product_cards
            if str(row.get("competitor_pool_status") or "").strip()
            and str(row.get("competitor_pool_status") or "").strip() not in {"待补", "卖家精灵证据不足", "竞品证据不足"}
        )
    if int(totals.get("frontend_amazon_search_validation_count") or 0) <= 0:
        totals["frontend_amazon_search_validation_count"] = sum(
            1
            for row in product_cards
            if str(row.get("amazon_search_validation_status") or "").strip() in {"已验证", "已读，无池内竞品", "部分"}
        )
    if int(totals.get("frontend_weak_defensive_count") or 0) <= 0:
        totals["frontend_weak_defensive_count"] = sum(
            1
            for row in product_cards
            if str(row.get("product_level_conclusion") or "").strip() in {"产品问题优先", "暂停扩张", "只防守"}
        )
    if int(totals.get("frontend_insufficient_count") or 0) <= 0:
        totals["frontend_insufficient_count"] = sum(
            1
            for row in product_cards
            if str(row.get("competitor_pool_status") or "").strip() in {"", "待补", "卖家精灵证据不足", "竞品证据不足"}
            or str(row.get("competitor_sellersprite_status") or "").strip() in {"", "待补", "竞品反查待补", "竞品卖家精灵证据不足"}
        )


def write_dashboard_html(shared: Any, results: list[dict], output_path: Path, report_date: str) -> None:
    results = shared._sort_results_by_marketplace(results)
    rows = []
    cards = []
    all_tasks: list[dict[str, str]] = []
    all_search: list[dict[str, str]] = []
    all_growth_tests: list[dict[str, str]] = []
    all_review: list[dict[str, str]] = []
    all_listing_reviews: list[dict[str, str]] = []
    all_frontend_checks: list[dict[str, str]] = []
    all_product_cards: list[dict[str, str]] = []
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
        "frontend_strong_evidence_count": 0,
        "frontend_background_evidence_count": 0,
        "market_survey_complete_count": 0,
        "market_survey_usable_count": 0,
        "market_survey_insufficient_count": 0,
        "market_survey_failed_count": 0,
    }
    market_survey_score_total = 0.0
    for result in results:
        summary = result["summary"]
        status, problem = shared._marketplace_status_text(result)
        view = result.get("report_view", {})
        all_tasks.extend(view.get("today_task_queue_rows", []))
        all_search.extend(view.get("html_search_term_processing_queue_rows", []))
        all_search.extend(shared._scale_keywords_as_ad_queue_rows(view.get("scale_keyword_rows", [])))
        all_growth_tests.extend(view.get("growth_test_rows", []))
        all_review.extend(view.get("tomorrow_review_rows", []))
        all_listing_reviews.extend(view.get("listing_price_diagnosis_rows", []))
        all_frontend_checks.extend(view.get("frontend_check_queue_rows", []))
        all_product_cards.extend(view.get("product_operation_cards", []))
        all_product_cards.extend(view.get("product_final_decision_rows", []))
        coverage = view.get("frontend_coverage_summary", {})
        if isinstance(coverage, dict):
            queue_total = int(float(coverage.get("frontend_queue_total", 0) or 0))
            market_survey_score_total += float(coverage.get("market_survey_average_score", 0) or 0) * queue_total
            for key in frontend_coverage_totals:
                try:
                    frontend_coverage_totals[key] += int(float(coverage.get(key, 0) or 0))
                except (TypeError, ValueError):
                    continue
        rows.append(
            {
                "站点": summary["marketplace"],
                "广告行数": str(summary["ads_row_count"]),
                "ERP行数": str(summary["erp_row_count"]),
                "SKU数": str(summary["sku_count"]),
                "ASIN数": str(summary["asin_count"]),
                "分析状态": status,
                "问题": problem,
            }
        )
        report_name = f"{summary['marketplace'].lower()}_report.html"
        cards.append(
            "\n".join(
                [
                    '<div class="market-card">',
                    f"<h3>{summary['marketplace']}</h3>",
                    f'<span class="pill {"status-pass" if status == "正式分析" else "status-warn"}">{html.escape(status)}</span>',
                    '<div class="meta-list">',
                    f'<div class="meta-item"><strong>Currency</strong>{html.escape(shared._marketplace_currency(result))}</div>',
                    "</div>",
                    f"<p><strong>主要问题：</strong>{html.escape(problem)}</p>",
                    f'<a class="button-link" href="{report_name}">打开报告</a>',
                    "</div>",
                ]
            )
        )
    quality_table = shared._render_table(["站点", "广告行数", "ERP行数", "SKU数", "ASIN数", "分析状态", "问题"], rows)
    quality_warn_count = sum(1 for row in rows if "正式分析" not in str(row.get("分析状态") or ""))
    all_ad_queue_rows = all_search + all_growth_tests
    counters = shared._collect_report_counters(all_tasks, all_ad_queue_rows, all_review, rows, all_listing_reviews)
    frontend_counts = shared._frontend_queue_counts(all_frontend_checks)
    cost_count = sum(1 for row in all_tasks if row.get("action_group") == "成本 / 利润动作")
    pending_ad_card_class = "metric-card status-warn" if counters["pending_ad"] else "metric-card status-pass"
    frontend_pending_card_class = "metric-card status-warn" if frontend_counts["待前台检查"] else "metric-card"
    cost_card_class = "metric-card status-warn" if cost_count else "metric-card"
    quality_card_class = "metric-card status-warn" if quality_warn_count else "metric-card status-pass"
    _apply_product_card_coverage_fallback(frontend_coverage_totals, all_product_cards)
    frontend_total = frontend_coverage_totals["frontend_queue_total"]
    frontend_coverage_summary: dict[str, object] = {}
    if frontend_total:
        market_survey_average = round(market_survey_score_total / frontend_total, 1)
        frontend_coverage_summary = {
            **frontend_coverage_totals,
            "market_survey_average_score": market_survey_average,
            "market_survey_average_score_label": f"{market_survey_average}/100",
            "market_survey_complete_label": f'{frontend_coverage_totals["market_survey_complete_count"]}/{frontend_total}',
            "market_survey_usable_label": f'{frontend_coverage_totals["market_survey_usable_count"]}/{frontend_total}',
            "market_survey_insufficient_label": f'{frontend_coverage_totals["market_survey_insufficient_count"]}/{frontend_total}',
            "market_survey_failed_label": f'{frontend_coverage_totals["market_survey_failed_count"]}/{frontend_total}',
            "frontend_live_success_rate": frontend_coverage_totals["frontend_live_success_count"] / frontend_total,
            "frontend_search_observed_rate": (
                (
                    frontend_coverage_totals["frontend_search_success_count"]
                    + frontend_coverage_totals["frontend_search_partial_count"]
                )
                / frontend_total
            ),
        }
    frontend_coverage_strip = shared._render_frontend_coverage_strip(frontend_coverage_summary)
    dashboard_ops = "\n".join(
        [
            '<div class="report-card">',
            '<h2>运营状态入口</h2>',
            '<p class="subtle">这里只做展示级总览；执行动作进入 ALL 工作台，管理摘要进入 summary。</p>',
            '<div class="priority-grid">',
            f'<div class="{pending_ad_card_class}">广告待处理<strong>{counters["pending_ad"]}</strong></div>',
            f'<div class="metric-card status-pass">已执行留档<strong>{counters["executed"]}</strong></div>',
            f'<div class="metric-card">明日复查<strong>{counters["review"]}</strong></div>',
            f'<div class="{frontend_pending_card_class}">前台待检查<strong>{frontend_counts["待前台检查"]}</strong></div>',
            f'<div class="metric-card">沿用前台缓存<strong>{frontend_counts["沿用缓存"]}</strong></div>',
            f'<div class="{cost_card_class}">成本/利润核对<strong>{cost_count}</strong></div>',
            f'<div class="{quality_card_class}">数据质量预警<strong>{quality_warn_count}</strong></div>',
            '</div>',
            (
                '<section><h3>前台证据覆盖</h3>'
                + frontend_coverage_strip
                + "</section>"
                if frontend_coverage_strip
                else ""
            ),
            '<div class="summary-action"><a class="button-link" href="summary.html">打开三分钟摘要</a><a class="button-link" href="latest_recommendations.html">打开 ALL 运营控制台</a></div>',
            '</div>',
        ]
    )
    body = "\n".join(
        [
            '<div class="report-card hero">',
            "<div>",
            "<h1>亚马逊运营日报总览</h1>",
            f'<div class="hero-meta">运行日期：{html.escape(report_date)}</div>',
            '<p class="subtle">这里保留展示级状态、站点总览和导航。执行动作进入 ALL 运营控制台。</p>',
            "</div>",
            "</div>",
            dashboard_ops,
            '<div class="report-card">',
            "<h2>数据质量总览</h2>",
            quality_table,
            "</div>",
            '<div class="grid">',
            *cards,
            "</div>",
        ]
    )
    shared._write_page(output_path, "亚马逊运营日报总览", body)
