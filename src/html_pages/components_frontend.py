from __future__ import annotations

import html
from urllib.parse import urlencode
from typing import Any


def _short_status_text(value: object, limit: int = 42) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _executed_action_status(row: dict[str, str], confirmed: str) -> tuple[str, str]:
    if confirmed != "已执行":
        return confirmed, confirmed
    term = str(row.get("search_term_or_target") or row.get("search_term") or "").strip()
    action = str(
        row.get("suggested_action")
        or row.get("action_detail")
        or row.get("copy_action_line")
        or row.get("today_action")
        or row.get("manual_action_taken")
        or row.get("normalized_action")
        or ""
    ).strip()
    action = action.replace("建议", "").strip()
    if action == "已执行广告调整":
        action = ""
    prefix = "广告" if term or "竞价" in action or str(row.get("action_scope") or "") == "search_term" else "已执行"
    if term and action:
        full = f"{prefix}：{term} {action}"
    elif term:
        full = f"{prefix}：{term}"
    elif action:
        full = f"{prefix}：{action}"
    else:
        note = str(row.get("confirmed_note") or "").replace("用户反馈：", "").strip()
        full = f"已执行：{note}" if note else "已执行"
    return _short_status_text(full), full


def _frontend_competitor_count(shared: Any, frontend: dict[str, object]) -> int:
    count = int(shared._num_from_text(frontend.get("frontend_competitor_count")) or 0)
    competitors = frontend.get("frontend_competitors") or []
    if isinstance(competitors, list):
        count = max(count, len([item for item in competitors if isinstance(item, dict)]))
    return count


def _frontend_gap_value(
    shared: Any,
    frontend: dict[str, object],
    field: str,
    *,
    formatter: str,
    own_field: str,
    own_missing_label: str,
) -> str:
    value = frontend.get(field)
    if value not in (None, ""):
        if formatter == "percent":
            return shared._fmt_signed_percent(value)
        return shared._fmt_signed_number(value)
    search_status = str(frontend.get("frontend_search_status") or "").strip()
    if search_status == "按广告信号跳过":
        return "搜索页未读取"
    if _frontend_competitor_count(shared, frontend) < 2:
        own_value = str(frontend.get(own_field) or "").strip()
        return "竞品样本不足" if own_value else own_missing_label
    return "样本不足"


def _render_frontend_evidence_block(
    shared: Any,
    row: dict[str, object],
    frontend_lookup: dict[tuple[str, str, str], dict[str, str]] | None,
) -> str:
    frontend = shared._lookup_frontend_evidence(row, frontend_lookup)
    if not frontend:
        return ""
    raw_status = str(frontend.get("frontend_check_status") or "待前台检查")
    status = shared._frontend_status_label(raw_status, frontend)
    findings = str(frontend.get("frontend_findings") or "").strip()
    suspected = str(frontend.get("suspected_issue") or "").strip()
    if not findings and not suspected:
        return ""
    findings = (
        shared._frontend_findings_text(findings)
        .replace("请提供前台截图确认", "自动证据不足，不能用于强诊断")
        .replace("请提供截图确认", "自动证据不足，不能用于强诊断")
        .replace("页面信息不完整，请提供截图确认", "自动证据不足，不能用于强诊断")
        .replace("请打开前台人工查看", "自动证据不足，不能用于强诊断")
    )
    quality_score = str(frontend.get("frontend_evidence_quality_score") or "").strip()
    conclusion = str(frontend.get("frontend_auto_conclusion_label") or "").strip()
    lines: list[str] = [f'<span class="{shared._confirmed_tag(status)}">{html.escape(status)}</span>']
    if conclusion:
        lines.append(f'<span class="metric-badge">自动结论：{html.escape(conclusion)}</span>')
    if quality_score:
        lines.append(f'<span class="metric-badge">前台证据质量 {html.escape(quality_score)}</span>')
    method = str(frontend.get("frontend_check_method") or "").strip()
    if method:
        lines.append(f'<span class="metric-badge">来源：{html.escape(method)}</span>')
    stability = shared._frontend_stability_badge(frontend)
    if stability:
        lines.append(f'<span class="metric-badge">{html.escape(stability)}</span>')
    tier = str(frontend.get("frontend_evidence_tier") or "").strip()
    audit_detail = str(frontend.get("frontend_evidence_audit_detail") or "").strip()
    if tier:
        lines.append(
            f'<p class="subtle">证据口径：{html.escape(tier)}'
            + (f"；{shared._inline_markup(audit_detail)}" if audit_detail else "")
            + "</p>"
        )
    if findings:
        lines.append(f"<p>{shared._inline_markup(findings)}</p>")
    last_error = str(frontend.get("frontend_last_error") or "").strip()
    if last_error:
        lines.append(f'<p class="subtle">自动读取失败原因：{shared._inline_markup(last_error)}</p>')
    search_findings = str(frontend.get("frontend_search_findings") or "").strip()
    if search_findings:
        lines.append(f'<p class="subtle">核心词搜索页：{shared._inline_markup(search_findings)}</p>')
    if _frontend_competitor_count(shared, frontend) < 2:
        lines.append('<p class="subtle">差距计算需要至少 2 个可比竞品样本。</p>')
    if suspected:
        lines.append(f'<p class="subtle">前台修正判断：{shared._inline_markup(suspected)}</p>')
    return '<div class="card-block frontend-evidence"><strong>前台证据</strong>' + "".join(lines) + "</div>"


def _render_frontend_gap_block(shared: Any, frontend: dict[str, object] | None) -> str:
    if not frontend:
        return ""
    metrics = [
        (
            "价格差距",
            _frontend_gap_value(
                shared,
                frontend,
                "frontend_price_delta_pct",
                formatter="percent",
                own_field="frontend_price",
                own_missing_label="产品售价未读取",
            ),
        ),
        (
            "评分差距",
            _frontend_gap_value(
                shared,
                frontend,
                "frontend_rating_delta",
                formatter="number",
                own_field="frontend_rating",
                own_missing_label="产品评分未读取",
            ),
        ),
        (
            "评论差距",
            _frontend_gap_value(
                shared,
                frontend,
                "frontend_review_delta_pct",
                formatter="percent",
                own_field="frontend_reviews",
                own_missing_label="产品评论未读取",
            ),
        ),
        (
            "Coupon / Buy Box",
            " / ".join(
                part
                for part in [
                    str(frontend.get("frontend_coupon") or "Coupon 未稳定识别"),
                    str(frontend.get("frontend_buy_box") or "Buy Box 未稳定识别"),
                ]
                if part
            ),
        ),
    ]
    chips = "".join(
        f'<span class="metric-badge">{html.escape(label)}：{html.escape(value)}</span>'
        for label, value in metrics
    )
    return f'<div class="card-block frontend-gap"><strong>前台差距</strong><div class="metric-row">{chips}</div></div>'


def _frontend_queue_counts(shared: Any, rows: list[dict[str, str]]) -> dict[str, int]:
    counts = {"待前台检查": 0, "沿用缓存": 0, "已自动检查": 0}
    for row in rows:
        label = shared._frontend_status_label(str(row.get("frontend_check_status") or "待前台检查"), row)
        if label.startswith("沿用"):
            counts["沿用缓存"] += 1
        elif "待前台检查" in label:
            counts["待前台检查"] += 1
        else:
            counts["已自动检查"] += 1
    return counts


def _render_frontend_status_summary(shared: Any, rows: list[dict[str, str]]) -> str:
    counts = _frontend_queue_counts(shared, rows)
    total = len(rows)
    retry_html = (
        '<div class="summary-action frontend-cache-action">'
        '<button class="button-link secondary" type="button" data-run-report-action="frontend-retry">刷新当前前台队列</button>'
        '<span class="frontend-retry-status subtle" data-run-report-status="frontend-retry">按运营用途读取当前需要看前台的产品。使用本机真实 Chrome CDP；失败时保留缓存，不用 urllib 冒充实时前台。</span>'
        "</div>"
    )
    single_check_status_html = (
        '<p class="frontend-retry-status subtle" data-run-report-status="frontend-check-one">单产品按钮只检查当前卡片对应 ASIN，完成后自动刷新报告。</p>'
        if rows
        else ""
    )
    return "\n".join(
        [
            '<section class="section-card is-collapsed" id="frontend-evidence-status">',
            '<div class="ad-section-header"><h2>前台证据状态</h2><span class="status-badge status-muted">辅助证据</span><button class="collapsible-toggle" type="button" data-collapse-toggle>展开</button></div>',
            '<p class="subtle">这里集中展示前台读取状态。待前台检查和缓存沿用不能当成当天实时前台事实；按钮按运营用途刷新当前队列，失败时保留缓存。20次稳定性只用于验收测试。</p>',
            '<div class="collapsible-body">',
            '<div class="priority-grid">',
            f'<div class="metric-card status-warn">待前台检查<strong>{counts["待前台检查"]}</strong></div>',
            f'<div class="metric-card">沿用缓存<strong>{counts["沿用缓存"]}</strong></div>',
            f'<div class="metric-card status-pass">已自动检查<strong>{counts["已自动检查"]}</strong></div>',
            f'<div class="metric-card">队列合计<strong>{total}</strong></div>',
            "</div>",
            retry_html,
            single_check_status_html,
            shared._render_frontend_check_cards(rows, limit=6),
            "</div>",
            "</section>",
        ]
    )


def _render_frontend_check_cards(shared: Any, rows: list[dict[str, str]], limit: int = 5) -> str:
    if not rows:
        return '<p class="subtle">当前没有需要放到前台检查队列的产品。</p>'
    parts = ['<div class="action-grid">']
    for row in rows[:limit]:
        priority = str(row.get("priority") or "P1")
        css = "p0" if priority == "P0" else "p1"
        confirmed = str(row.get("confirmed_status") or "待确认")
        confirmed_label, confirmed_title = _executed_action_status(row, confirmed)
        raw_status = str(row.get("frontend_check_status") or "待前台检查")
        status = shared._frontend_status_label(raw_status, row)
        url = str(row.get("product_url") or shared._amazon_product_url(row.get("marketplace"), row.get("asin")))
        open_button_html = (
            f'<a class="button-link" href="{html.escape(url)}" rel="noopener">打开前台</a>'
            if url
            else ""
        )
        query = urlencode(
            {
                "marketplace": str(row.get("marketplace") or "").strip().upper(),
                "sku": str(row.get("sku") or "").strip(),
                "asin": str(row.get("asin") or "").strip().upper(),
            }
        )
        single_check_button_html = (
            f'<button class="button-link secondary" type="button" data-run-report-action="frontend-check-one" data-run-report-query="{html.escape(query)}" data-run-report-reload-on-done="true">检查这个产品前台</button>'
            if str(row.get("marketplace") or "").strip() and str(row.get("asin") or "").strip()
            else ""
        )
        action_html = "".join(
            part for part in [open_button_html, single_check_button_html] if part
        )
        findings = str(
            row.get("frontend_findings") or "自动证据不足，不能用于强诊断；尚未读取到可用前台字段。"
        )
        findings = (
            shared._frontend_findings_text(findings)
            .replace("请提供前台截图确认", "自动证据不足，不能用于强诊断")
            .replace("请提供截图确认", "自动证据不足，不能用于强诊断")
            .replace("页面信息不完整，请提供截图确认", "自动证据不足，不能用于强诊断")
            .replace("请打开前台人工查看", "自动证据不足，不能用于强诊断")
        )
        auto_label = str(row.get("frontend_auto_conclusion_label") or "自动证据不足，不能用于强诊断")
        evidence_score = str(row.get("frontend_evidence_quality_score") or "0")
        evidence_tier = str(row.get("frontend_evidence_tier") or "").strip()
        evidence_method = str(row.get("frontend_check_method") or "").strip()
        stability = shared._frontend_stability_badge(row)
        evidence_audit = str(row.get("frontend_evidence_audit_detail") or "").strip()
        failure_reason = str(row.get("frontend_failure_reason") or row.get("frontend_last_error") or "").strip()
        frontend_reasons = shared._value_list(row.get("frontend_auto_conclusion_reasons"))
        frontend_reason_html = (
            "<ul>" + "".join(f"<li>{shared._inline_markup(reason)}</li>" for reason in frontend_reasons[:4]) + "</ul>"
            if frontend_reasons
            else f"<p>{shared._inline_markup(findings)}</p>"
        )
        search_findings = str(row.get("frontend_search_findings") or "").strip()
        search_block = (
            f'<div class="card-block"><strong>核心词搜索页 / 前三竞品</strong><p>{shared._inline_markup(search_findings)}</p></div>'
            if search_findings
            else ""
        )
        parts.append(
            "\n".join(
                [
                    f'<article class="work-card {css} frontend-check-card">',
                    '<div class="card-head">',
                    "<div>",
                    f'<h3 class="card-title">{html.escape(priority)}｜{html.escape(str(row.get("marketplace") or "N/A"))}｜{html.escape(str(row.get("product_name") or "N/A"))}</h3>',
                    f'<div class="card-meta">{shared._product_meta_html(row, include_frontend_link=False)}</div>',
                    "</div>",
                    f'<div><span class="tag tag-blue">{html.escape(status)}</span> <span class="{shared._confirmed_tag(confirmed)}" title="{html.escape(confirmed_title)}">{html.escape(confirmed_label)}</span></div>',
                    "</div>",
                    f'<div class="summary-action">{action_html}</div>' if action_html else "",
                    f'<div class="card-block"><strong>触发原因</strong><p>{shared._inline_markup(str(row.get("trigger_reason") or "N/A"))}</p></div>',
                    '<div class="card-block"><strong>关键指标</strong><div class="metric-row">'
                    + shared._metric_badges_from_evidence(str(row.get("key_metrics") or ""), limit=6)
                    + "</div></div>",
                    '<div class="card-block"><strong>自动前台结论</strong>'
                    f'<div class="metric-row"><span class="metric-badge">结论：{html.escape(auto_label)}</span><span class="metric-badge">证据质量：{html.escape(evidence_score)}</span>'
                    + (f'<span class="metric-badge">口径：{html.escape(evidence_tier)}</span>' if evidence_tier else "")
                    + (f'<span class="metric-badge">来源：{html.escape(evidence_method)}</span>' if evidence_method else "")
                    + (f'<span class="metric-badge">{html.escape(stability)}</span>' if stability else "")
                    + "</div>"
                    + (f'<p class="subtle">证据审计：{shared._inline_markup(evidence_audit)}</p>' if evidence_audit else "")
                    + f"{frontend_reason_html}"
                    + (f'<p class="subtle">失败分类：{shared._inline_markup(failure_reason)}</p>' if failure_reason else "")
                    + "</div>",
                    _render_frontend_gap_block(shared, row),
                    search_block,
                    f'<div class="card-block"><strong>系统判断方向</strong><p>{shared._inline_markup(str(row.get("suspected_issue") or auto_label or "N/A"))}</p></div>',
                    f'<div class="card-block"><strong>保守动作</strong><p>{shared._inline_markup(str(row.get("conservative_action") or "N/A"))}</p></div>',
                    f'<div class="card-block"><strong>下一步</strong><p>{shared._inline_markup(str(row.get("recommended_next_step") or "N/A"))}</p></div>',
                    "</article>",
                ]
            )
        )
    parts.append("</div>")
    if len(rows) > limit:
        parts.append(f'<p class="subtle">另有 {len(rows) - limit} 个前台检查对象，见单站报告或 Excel 明细。</p>')
    return "".join(parts)


def _render_frontend_retry_tool(shared: Any) -> str:
    return "\n".join(
        [
            '<section class="section-card frontend-retry-strip is-collapsed">',
            "<div>",
            "<h2>前台缓存工具</h2>",
            "<p class=\"subtle\">默认不把无浏览器读取当成实时前台事实。这个按钮按运营用途刷新当前队列；如果端口不可用或读取失败，就保留已有缓存并提示原因。20次稳定性只用于验收测试。</p>",
            "</div>",
            '<div class="summary-action">',
            '<button class="button-link" type="button" data-run-report-action="frontend-retry">刷新当前前台队列并刷新报告</button>',
            '<span class="frontend-retry-status subtle" data-run-report-status="frontend-retry">成功后写入 frontend_check_results.json 并刷新报告；稳定性验收结果通过缓存字段展示，但网页按钮不做20次压力测试。</span>',
            "</div>",
            "</section>",
        ]
    )
