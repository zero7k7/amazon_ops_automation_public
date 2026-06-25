from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def write_dashboard_html(shared: Any, results: list[dict], output_path: Path, report_date: str) -> None:
    results = shared._sort_results_by_marketplace(results)
    rows = []
    cards = []
    all_tasks: list[dict[str, str]] = []
    all_search: list[dict[str, str]] = []
    all_review: list[dict[str, str]] = []
    all_listing_reviews: list[dict[str, str]] = []
    all_frontend_checks: list[dict[str, str]] = []
    for result in results:
        summary = result["summary"]
        status, problem = shared._marketplace_status_text(result)
        view = result.get("report_view", {})
        all_tasks.extend(view.get("today_task_queue_rows", []))
        all_search.extend(view.get("html_search_term_processing_queue_rows", []))
        all_search.extend(shared._scale_keywords_as_ad_queue_rows(view.get("scale_keyword_rows", [])))
        all_review.extend(view.get("tomorrow_review_rows", []))
        all_listing_reviews.extend(view.get("listing_price_diagnosis_rows", []))
        all_frontend_checks.extend(view.get("frontend_check_queue_rows", []))
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
    counters = shared._collect_report_counters(all_tasks, all_search, all_review, rows, all_listing_reviews)
    frontend_counts = shared._frontend_queue_counts(all_frontend_checks)
    cost_count = sum(1 for row in all_tasks if row.get("action_group") == "成本 / 利润动作")
    pending_ad_card_class = "metric-card status-warn" if counters["pending_ad"] else "metric-card status-pass"
    frontend_pending_card_class = "metric-card status-warn" if frontend_counts["待前台检查"] else "metric-card"
    cost_card_class = "metric-card status-warn" if cost_count else "metric-card"
    quality_card_class = "metric-card status-warn" if quality_warn_count else "metric-card status-pass"
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
