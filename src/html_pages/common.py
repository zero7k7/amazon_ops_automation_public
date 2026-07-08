from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _render_boss_summary(
    shared: Any,
    report_date: str,
    p0_count: int,
    p1_count: int,
    listing_count: int,
    review_count: int,
    quality_warn_count: int,
    all_tasks: list[dict[str, str]],
    all_listing_reviews: list[dict[str, str]],
    all_search: list[dict[str, str]] | None = None,
    show_p1_link: bool = True,
) -> str:
    all_search = all_search or []
    executed_count = sum(
        1
        for row in [*all_tasks, *all_listing_reviews, *all_search]
        if str(row.get("confirmed_status") or "") == "已执行"
    )
    confirm_count = sum(
        1
        for row in [*all_tasks, *all_listing_reviews, *all_search]
        if str(row.get("confirmed_status") or "待确认") == "待确认"
    )
    pending_ad_count = sum(1 for row in all_search if shared._ad_status_key(row) == "pending")
    pending_listing_count = sum(
        1
        for row in all_listing_reviews
        if str(row.get("confirmed_status") or "待确认") == "待确认"
    )
    pending_product_count = max(0, confirm_count - pending_ad_count - pending_listing_count)
    if p0_count:
        conclusion = "先看产品级结论；需要长证据时再展开 P0 明细。"
    elif p1_count and show_p1_link:
        conclusion = "今日无可执行 P0，先看 P1 检查；广告只按待执行数处理。"
    elif listing_count:
        conclusion = "今日无可执行 P0，P1 集中在 Listing 待确认对象；广告只按待执行数处理。"
    elif p1_count:
        conclusion = "今日无可执行 P0，先核对 P1 检查对象；广告只按待执行数处理。"
    else:
        conclusion = "今日无明显强动作，按广告状态和明日复查推进。"
    if quality_warn_count:
        conclusion += f" 有 {quality_warn_count} 个数据质量预警，相关站点只做轻动作。"
    jump_links = [
        '<a href="#p0-actions">P0 明细</a>',
        '<a href="#today-ad-actions-all">广告动作</a>',
        '<a href="#inventory-replenishment">补货提醒</a>',
        '<a href="#cost-review">成本核对</a>',
    ]
    if show_p1_link:
        jump_links.append('<a href="#p1-check">P1 检查</a>')
    return "\n".join(
        [
            '<section class="section-card"><h2>今日运营摘要</h2>',
            f'<p class="subtle">{html.escape(report_date)}｜{html.escape(conclusion)}</p>',
            '<div class="priority-grid">',
            f'<div class="metric-card status-danger">P0 待判断<strong>{p0_count}</strong></div>',
            f'<div class="metric-card status-warn">P1 合计<strong>{p1_count}</strong></div>',
            f'<div class="metric-card status-warn">广告待执行<strong>{pending_ad_count}</strong></div>',
            f'<div class="metric-card">产品待判断<strong>{pending_product_count}</strong></div>',
            f'<div class="metric-card">Listing 待确认<strong>{listing_count}</strong></div>',
            f'<div class="metric-card status-pass">已执行<strong>{executed_count}</strong></div>',
            "</div>",
            '<div class="daily-jump-grid">',
            *jump_links,
            "</div>",
            "</section>",
        ]
    )


def _page_shell(shared: Any, title: str, body_html: str) -> str:
    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{html.escape(title)}</title>",
            '<link rel="stylesheet" href="assets/report.css">',
            f"<style>{shared.CSS}{shared.REPORT_UI_CSS}</style>",
            "</head>",
            "<body>",
            '<div class="page">',
            body_html,
            "</div>",
            '<button class="back-to-top" type="button" data-back-to-top>↑</button>',
            '<script src="assets/report.js"></script>',
            "</body>",
            "</html>",
        ]
    )


def _ensure_report_assets(shared: Any, output_dir: Path) -> None:
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "report.css").write_text(shared.CSS + shared.REPORT_UI_CSS, encoding="utf-8")
    (assets_dir / "report.js").write_text(shared.REPORT_JS, encoding="utf-8")


def _write_page(shared: Any, output_path: Path, title: str, body_html: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_report_assets(shared, output_path.parent)
    output_path.write_text(_page_shell(shared, title, body_html), encoding="utf-8")


def _render_nav(shared: Any, current: str) -> str:
    links = [
        ("dashboard.html", "返回总览", current == "dashboard"),
        ("summary.html", "摘要", current == "summary"),
        ("latest_recommendations.html", "ALL 汇总建议", current == "recommendations"),
        ("us_report.html", "US", current == "US"),
        ("uk_report.html", "UK", current == "UK"),
        ("de_report.html", "DE", current == "DE"),
    ]
    parts = ['<div class="nav">']
    for href, label, active in links:
        class_attr = ' class="active"' if active else ""
        parts.append(f'<a href="{href}"{class_attr}>{html.escape(label)}</a>')
    parts.append("</div>")
    return "".join(parts)


def _render_marketplace_status_cards(shared: Any, result: dict, view: dict, report_date: str) -> str:
    summary = result.get("summary", {})
    status = str(view.get("analysis_status") or ("正常" if view.get("quality_pass") else "警告"))
    quality_class = "status-pass" if view.get("quality_pass") else "status-warn"
    status_rows = view.get("enhanced_status_rows", [])
    imported_count = sum(1 for row in status_rows if str(row.get("状态") or "") == "已导入")
    strong_count = sum(1 for row in status_rows if str(row.get("诊断使用类型") or "") == "强诊断使用")
    background_count = sum(1 for row in status_rows if str(row.get("诊断使用类型") or "") == "仅背景参考")
    hidden_count = int(view.get("hidden_low_click_search_terms", 0) or 0)
    cards = [
        ("站点", result.get("marketplace", "N/A"), ""),
        ("报告日期", report_date, ""),
        ("数据质量", status, quality_class),
        ("广告日期范围", summary.get("ads_date_range", "N/A"), ""),
        ("ERP 报表覆盖范围", summary.get("erp_report_coverage_date_range") or summary.get("erp_date_range", "N/A"), ""),
        ("增强数据状态", f"已导入 {imported_count} 个｜强诊断 {strong_count} 个｜背景参考 {background_count} 个", ""),
        ("低优先级隐藏项", f"{hidden_count} 条", ""),
    ]
    parts = ['<section class="section-card"><h2>站点状态</h2><div class="status-grid">']
    for label, value, css in cards:
        class_attr = f" metric-card {css}".strip()
        parts.append(
            "\n".join(
                [
                    f'<div class="{class_attr}">',
                    f'<span class="label">{html.escape(str(label))}</span>',
                    f'<span class="value">{html.escape(str(value))}</span>',
                    "</div>",
                ]
            )
        )
    parts.append("</div></section>")
    return "".join(parts)


def markdown_to_html(shared: Any, markdown_text: str, title: str = "Amazon Daily Report") -> str:
    lines = markdown_text.splitlines()
    html_parts = ['<div class="report-card">']
    index = 0
    in_list = False
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            index += 1
            continue
        if stripped.startswith("|"):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
            rows = []
            for raw in table_lines[2:]:
                cells = [cell.strip() for cell in raw.strip("|").split("|")]
                cells += [""] * (len(headers) - len(cells))
                rows.append({headers[i]: cells[i] for i in range(len(headers))})
            html_parts.append(shared._render_table(headers, rows))
            continue
        if stripped.startswith("# "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h1>{shared._inline_markup(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h2>{shared._inline_markup(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h3>{shared._inline_markup(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            content = stripped[2:]
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{shared._inline_markup(content)}</li>")
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            css_class = "alert alert-success" if stripped.startswith("✅") else "alert alert-warning" if stripped.startswith("⚠️") else ""
            if css_class:
                html_parts.append(f'<div class="{css_class}">{shared._inline_markup(stripped)}</div>')
            else:
                html_parts.append(f"<p>{shared._inline_markup(stripped)}</p>")
        index += 1
    if in_list:
        html_parts.append("</ul>")
    html_parts.append("</div>")
    return _page_shell(shared, title, "".join(html_parts))


def write_html_report(shared: Any, markdown_text: str, output_path: Path, title: str = "Amazon Daily Report") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_report_assets(shared, output_path.parent)
    output_path.write_text(markdown_to_html(shared, markdown_text, title=title), encoding="utf-8")


def _marketplace_currency(shared: Any, result: dict) -> str:
    if result.get("has_data"):
        records = result.get("analysis_payload", {}).get("产品汇总", {}).get("1d", [])
        currencies = sorted({str(row.get("currency") or "").strip() for row in records if str(row.get("currency") or "").strip()})
        if currencies:
            return ", ".join(
                f"{currency} ({shared.money_symbol_for_marketplace(result.get('marketplace'), currency)})"
                for currency in currencies
            )
    defaults = {"UK": "GBP", "US": "USD", "DE": "EUR"}
    currency = defaults.get(result.get("marketplace"), "N/A")
    if currency == "N/A":
        return currency
    return f"{currency} ({shared.money_symbol_for_marketplace(result.get('marketplace'), currency)})"


def _marketplace_status_text(shared: Any, result: dict) -> tuple[str, str]:
    summary = result["summary"]
    status = shared.data_quality_status_from_summary(summary, has_data=bool(result.get("has_data")))
    return str(status["analysis_status"]), str(status["issue_summary"])
