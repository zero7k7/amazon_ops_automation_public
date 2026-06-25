from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def write_marketplace_report_html(shared: Any, result: dict, output_path: Path, report_date: str) -> None:
    marketplace = result["marketplace"]
    nav = shared._render_nav(marketplace)
    if not result.get("has_data"):
        summary = result["summary"]
        if summary["ads_row_count"] > 0 and summary["erp_row_count"] == 0:
            message = f"{marketplace} 有广告数据，但 ERP 销量数据缺失，暂不能计算 TACOS、自然单、利润和库存。"
            followup = f"请确认 sales_report_all.xlsx 是否包含 {marketplace} 数据。"
        elif summary["ads_row_count"] == 0 and summary["erp_row_count"] > 0:
            message = f"{marketplace} 有 ERP 数据，但广告数据缺失，暂不能完成广告诊断。"
            followup = f"请确认 ads_report_all.csv 是否包含 {marketplace} 数据。"
        else:
            message = f"{marketplace} 当前无可分析数据。"
            followup = "请确认总广告表和总 ERP 表是否已包含该站点。"
        body = "\n".join(
            [
                '<div class="report-card hero">',
                "<div>",
                f"<h1>亚马逊运营日报｜{html.escape(marketplace)}｜{html.escape(report_date)}</h1>",
                f'<div class="hero-meta">运行日期：{html.escape(report_date)}</div>',
                nav,
                "</div>",
                "</div>",
                '<div class="section-card alert alert-warning">',
                html.escape(message),
                "<br>",
                html.escape(followup),
                "</div>",
            ]
        )
        shared._write_page(output_path, f"亚马逊运营日报｜{marketplace}｜{report_date}", body)
        return

    payload = result["analysis_payload"]
    view = result["report_view"]
    quality_alert_text = (
        "✅ 数据质量通过，可以用于运营判断"
        if view["quality_pass"]
        else f"⚠️ {view.get('analysis_status', '数据质量存在问题')}：{view.get('issue_summary', '本报告需谨慎使用')}"
    )
    quality_alert_class = "alert-success" if view["quality_pass"] else "alert-warning"
    quality_alert = f'<div class="alert {quality_alert_class}">{html.escape(quality_alert_text)}</div>'
    sections = [
        '<div class="report-card hero">',
        "<div>",
        f"<h1>亚马逊运营日报｜{html.escape(marketplace)}｜{html.escape(report_date)}</h1>",
        f'<div class="hero-meta">运行日期：{html.escape(report_date)}</div>',
        f'<div class="hero-meta">币种：{html.escape(shared._marketplace_currency(result))}</div>',
        nav,
        "</div>",
        "</div>",
        '<div class="section-stack">',
        shared._render_marketplace_status_cards(result, view, report_date),
        '<section class="section-card"><h2>昨日异常归因摘要</h2>'
        + '<p class="subtle">先看站点整体，再看最关键的一个产品异常；成本/利润问题放到利润模块。</p>'
        + shared._render_yesterday_attribution(view.get("yesterday_attribution_rows", []), limit=2)
        + "</section>",
        shared._render_collapsed_section("统一临时处理原则", shared._render_common_principles_body(), "通用规则默认收起；操作前需要统一口径时再展开。"),
    ]

    processing_rows = view.get("html_search_term_processing_queue_rows", []) + shared._scale_keywords_as_ad_queue_rows(view.get("scale_keyword_rows", []))
    growth_test_rows = view.get("growth_test_rows", [])
    hidden_low_click_count = int(view.get("hidden_low_click_search_terms", 0) or 0)
    keyword_review_rows = [
        row
        for row in view.get("keyword_action_effect_review_rows", [])
        if str(row.get("marketplace") or "").upper() == str(marketplace).upper()
    ]
    frontend_lookup = shared._build_frontend_lookup(view.get("frontend_check_queue_rows", []))
    pending_ad_rows = [row for row in processing_rows if shared._ad_status_key(row) == "pending"]
    if pending_ad_rows or growth_test_rows:
        sections.append(
            '<section class="section-card">'
            + shared._render_ad_workbench(
                processing_rows,
                all_marketplaces=False,
                hidden_low_click_count=hidden_low_click_count,
                marketplace_hint=marketplace,
                title="广告状态",
                growth_test_rows=growth_test_rows,
                keyword_review_count=len(keyword_review_rows),
            )
            + "</section>"
        )
    else:
        sections.append(
            shared._render_ad_workbench_status_only(
                processing_rows,
                hidden_low_click_count=hidden_low_click_count,
                marketplace_hint=marketplace,
                collapsed=True,
            )
        )
    sections.append(shared._render_frontend_status_summary(view.get("frontend_check_queue_rows", [])))

    if view["today_task_queue_rows"]:
        non_cost_rows = [row for row in view["today_task_queue_rows"] if row.get("action_group") != "成本 / 利润动作"]
        pending_non_cost_rows = shared._exclude_executed_rows(non_cost_rows)
        executable_p0_rows = [
            row
            for row in pending_non_cost_rows
            if str(row.get("priority") or "") == "P0" and not shared._is_observation_only_summary_row(row)
        ]
        observation_p0_rows = [
            row
            for row in pending_non_cost_rows
            if str(row.get("priority") or "") == "P0" and shared._is_observation_only_summary_row(row)
        ]
        if executable_p0_rows:
            action_parts = ['<section class="section-card"><h2>P0 今日必须执行</h2>']
            action_parts.append(shared._render_task_cards(executable_p0_rows, "P0", frontend_lookup=frontend_lookup))
            action_parts.append("</section>")
            sections.append("".join(action_parts))
        if observation_p0_rows:
            sections.append(
                shared._render_collapsed_section(
                    "P0 待核查 / 观察",
                    shared._render_task_cards(observation_p0_rows, "P0", frontend_lookup=frontend_lookup),
                    "这些对象不应直接执行强动作；需要补证据或等待数据窗口。",
                )
            )

    non_cost_rows = [row for row in view.get("today_task_queue_rows", []) if row.get("action_group") != "成本 / 利润动作"]
    pending_non_cost_rows = shared._exclude_executed_rows(non_cost_rows)
    executed_risk_rows = shared._executed_risk_rows(non_cost_rows)
    p1_non_listing_rows = shared._exclude_listing_tasks(pending_non_cost_rows, view.get("today_task_queue_rows", []))
    listing_rows = shared._exclude_executed_rows(view.get("listing_price_diagnosis_rows", []))
    if any(row.get("priority") == "P1" for row in p1_non_listing_rows):
        sections.append(
            '<section class="section-card"><h2>P1 今日检查</h2>'
            + shared._render_task_cards(p1_non_listing_rows, "P1", empty_message="", frontend_lookup=frontend_lookup)
            + "</section>"
        )
    if executed_risk_rows:
        sections.append(
            shared._render_collapsed_section(
                "已执行但仍需复查",
                shared._render_task_cards(
                    executed_risk_rows,
                    None,
                    empty_message="",
                    frontend_lookup=frontend_lookup,
                ),
                "已执行对象只在复查时展开。",
            )
        )
    visible_listing_rows = shared._filter_listing_rows_for_p0(listing_rows, view.get("today_task_queue_rows", []))
    if visible_listing_rows:
        sections.append(
            shared._render_collapsed_section(
                "Listing 待人工确认",
                shared._render_collapsed_block("通用确认材料", shared._render_common_chatgpt_materials(), "需要人工确认 Listing/价格时再展开。")
                + shared._render_listing_review_cards(visible_listing_rows, limit=5, frontend_lookup=frontend_lookup),
                "Listing 证据默认下沉，避免抢占今天执行入口。",
            )
        )

    if view["tomorrow_review_rows"]:
        sections.append(
            shared._render_collapsed_section(
                "明日复查清单",
                shared._render_review_list(view["tomorrow_review_rows"], limit=5),
                "复查对象默认收起；需要安排明日检查时再展开。",
            )
        )

    sections.append(
        shared._render_collapsed_section(
            "执行后效果复盘",
            "<h3>词 / ASIN 级复盘</h3>"
            + shared._render_keyword_action_effect_review_rows(
                keyword_review_rows,
                limit=10,
            )
            + "<h3>产品级复盘</h3>"
            + shared._render_action_effect_review_rows(
                [
                    row
                    for row in view.get("action_effect_review_rows", [])
                    if str(row.get("marketplace") or "").upper() == str(marketplace).upper()
                ],
                limit=3,
            ),
            "只在复查已执行动作效果时展开。",
            section_id="action-effect-review",
        )
    )

    if view.get("risk_rows"):
        sections.append(
            shared._render_collapsed_section(
                "滞销观察池",
                '<p class="subtle">仅展示高风险 Top 3；中低风险、低样本和低库存对象进入 Excel。</p>'
                + shared._render_watch_pool(view.get("risk_rows", []), limit=3),
                "观察池默认收起，避免抢占今日动作入口。",
            )
        )

    cost_rows = view.get("today_action_groups", {}).get("成本 / 利润动作", [])
    if cost_rows:
        sections.append(
            shared._render_collapsed_section(
                "利润 / 成本待核对",
                shared._render_profit_cost_cards(cost_rows, limit=3),
                "财务类对象保留，但默认不放首屏。",
            )
        )
    sections.append(
        shared._render_collapsed_section(
            "库存补货提醒",
            shared._render_inventory_replenishment_cards(view.get("inventory_replenishment_rows", []), limit=6),
            "库存提醒默认下沉，避免打断广告执行。",
        )
    )

    sections.append(
        shared._render_collapsed_section(
            "数据质量与增强数据",
            shared._render_table(["项目", "结果", "判断"], view["data_quality_rows"]) + quality_alert,
            "默认收起；当报告判断异常或增强数据时效可疑时再展开。",
            open_by_default=not view["quality_pass"],
        )
    )

    status_rows = view.get("enhanced_status_rows", [])
    sections.append(
        shared._render_collapsed_section(
            "增强数据状态",
            shared._render_table(["报表类型", "状态", "周期类型", "日期范围", "文件名", "识别来源", "新鲜度", "是否可比较", "诊断使用类型", "是否参与诊断"], status_rows),
            "完整文件状态默认收起；主页面只展示是否强诊断/背景参考。",
        )
    )

    request_table_rows = view.get("enhanced_request_rows", [])
    if request_table_rows:
        sections.append(shared._render_collapsed_section("增强数据请求", shared._render_table(["报表", "周期", "日期范围", "文件名", "必需"], request_table_rows), "缺文件时再展开查看。"))

    sections.append(
        shared._render_collapsed_section("自我优化记录", shared._render_optimization_notes(view.get("optimization_notes", [])), "保留学习记录，但不占主操作区。")
    )

    sections.append("</div>")
    shared._write_page(output_path, f"亚马逊运营日报｜{marketplace}｜{report_date}", "\n".join(sections))
