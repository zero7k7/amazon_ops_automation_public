from __future__ import annotations

import html
import re
from urllib.parse import urlencode
from typing import Any


PUBLIC_DEMO_REVERSE_LOOKUP_SAMPLE = {
    "marketplace": "US",
    "sku": "PUBLIC-LIVE-ASIN-SMOKE",
    "asin": "B084Z8CXXN",
    "label": "Amazon.com 公开 ASIN B084Z8CXXN",
}


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


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是", "已验证"}


def _int_value(value: object) -> int:
    try:
        return int(float(str(value or "0").replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def _split_keyword_text(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    for segment in re.split(r"[；;]+", text):
        segment = re.sub(r"\bB0[A-Z0-9]{8}\s*[:：]\s*", "", segment.strip(), flags=re.I)
        chunks.extend(re.split(r"[、，,]+", segment))
    seen: set[str] = set()
    results: list[str] = []
    for chunk in chunks:
        keyword = " ".join(str(chunk or "").split()).strip(" .")
        key = keyword.lower()
        if keyword and key not in seen and key not in {"暂无明确机会词", "n/a"}:
            seen.add(key)
            results.append(keyword)
    return results


def _keyword_gallons(text: str) -> set[int]:
    return {
        int(group)
        for match in re.finditer(r"\b(\d{1,3})\s*(?:gallon|gal)\b|(\d{1,3})\s*加仑", text, flags=re.I)
        for group in match.groups()
        if group
    }


def _keyword_is_brand_risk(keyword: str) -> bool:
    lowered = keyword.lower()
    return any(token in lowered for token in ["amazon basics", "amazon", "basics"])


def _keyword_is_size_mismatch(keyword: str, own_gallons: set[int]) -> bool:
    lowered = keyword.lower()
    keyword_gallons = _keyword_gallons(keyword)
    if keyword_gallons and own_gallons and all(abs(size - own) > 2 for size in keyword_gallons for own in own_gallons):
        return True
    if own_gallons and max(own_gallons) >= 18 and any(token in lowered for token in ["small", "kitchen cable", "kitchen bags"]):
        return True
    return False


def _keyword_is_broad(keyword: str) -> bool:
    lowered = keyword.lower()
    generic = {
        "cable ties",
        "wire ties",
        "cleaning supplies",
        "kitchen",
        "bags",
        "cable",
        "wire",
    }
    return lowered in generic or len([token for token in re.split(r"\s+", lowered) if token]) <= 2


def _keyword_list_text(values: list[str], limit: int = 3) -> str:
    return "、".join(values[:limit])


def _seller_sprite_keyword_judgement(row: dict[str, object]) -> str:
    top_opportunities = _split_keyword_text(row.get("seller_sprite_top_opportunities"))
    own_keywords = _split_keyword_text(row.get("own_sellersprite_keywords"))
    missing_keywords = _split_keyword_text(row.get("own_missing_competitor_keywords"))
    if not top_opportunities and not own_keywords and not missing_keywords:
        return ""
    context_text = " ".join(
        str(row.get(key) or "")
        for key in ["product_name", "search_term_or_target", "own_sellersprite_keywords"]
    )
    own_gallons = _keyword_gallons(context_text)
    testable: list[str] = []
    for keyword in top_opportunities:
        if _keyword_is_brand_risk(keyword) or _keyword_is_size_mismatch(keyword, own_gallons):
            continue
        if keyword.lower() not in {item.lower() for item in testable}:
            testable.append(keyword)
    for keyword in own_keywords:
        if _keyword_is_brand_risk(keyword) or _keyword_is_size_mismatch(keyword, own_gallons):
            continue
        gallons = _keyword_gallons(keyword)
        if not own_gallons or not gallons or any(abs(size - own) <= 2 for size in gallons for own in own_gallons):
            if keyword.lower() not in {item.lower() for item in testable}:
                testable.append(keyword)
    broad_control: list[str] = []
    mismatch_or_brand: list[str] = []
    for keyword in missing_keywords:
        if _keyword_is_brand_risk(keyword) or _keyword_is_size_mismatch(keyword, own_gallons):
            mismatch_or_brand.append(keyword)
        elif _keyword_is_broad(keyword):
            broad_control.append(keyword)
    pressure = str(row.get("competitor_keyword_pressure") or "").strip()
    frontend = str(row.get("frontend_competitiveness") or "").strip()
    boundary = str(row.get("product_ad_boundary") or "").strip()
    delayed_test = False
    if frontend == "前台弱" and pressure in {"高", "中"}:
        verdict = "竞品词只证明压力，当前前台弱，不建议新增。"
        delayed_test = True
    elif "停止新增" in boundary:
        verdict = "竞品词只用于解释压力，今天先止损。"
        delayed_test = True
    elif testable:
        verdict = "仅可低预算精准测试，不加预算。"
    else:
        verdict = "证据不足，只观察或控费。"
    parts = [f"竞品词判断：{verdict}"]
    if testable:
        label = "修好后再测" if delayed_test else "可小测"
        parts.append(f"{label}：{_keyword_list_text(testable, 2)}")
    if broad_control:
        parts.append(f"泛词控费：{_keyword_list_text(broad_control, 3)}")
    if mismatch_or_brand:
        parts.append(f"错配或品牌风险：{_keyword_list_text(mismatch_or_brand, 4)}")
    return "；".join(parts)


def _render_seller_sprite_summary_block(row: dict[str, object]) -> str:
    status = str(row.get("seller_sprite_check_status") or "").strip()
    keyword_count = _int_value(row.get("seller_sprite_keyword_count"))
    ad_rows = _int_value(row.get("seller_sprite_ad_rows_count"))
    if not status or status == "无缓存" or (keyword_count <= 0 and ad_rows <= 0):
        return ""
    data_date = str(row.get("seller_sprite_data_date") or "").strip()
    near_count = _int_value(row.get("seller_sprite_ad_near_match_count"))
    exact_count = _int_value(row.get("seller_sprite_ad_exact_match_count"))
    no_match_count = _int_value(row.get("seller_sprite_ad_no_match_count"))
    no_cache_count = _int_value(row.get("seller_sprite_ad_no_cache_count"))
    opportunity_count = _int_value(row.get("seller_sprite_opportunity_count"))
    high_count = _int_value(row.get("seller_sprite_high_competition_count"))
    risk_summary = str(row.get("seller_sprite_risk_summary") or "").strip()
    top_opportunities = str(row.get("seller_sprite_top_opportunities") or "").strip()
    product_conclusion = str(row.get("product_level_conclusion") or "").strip()
    ad_boundary = str(row.get("product_ad_boundary") or "").strip()
    competitor_pressure = str(row.get("competitor_keyword_pressure") or "").strip()
    missing_competitor = str(row.get("own_missing_competitor_keywords") or "").strip()
    no_match_ad_terms = str(row.get("own_ad_terms_not_in_sellersprite") or "").strip()
    today_status = str(row.get("sellersprite_today_status") or "").strip()
    cache_date = str(row.get("sellersprite_cache_date") or "").strip()
    trend_status = str(row.get("sellersprite_trend_status") or "").strip()
    persistent_keywords = str(row.get("sellersprite_persistent_keywords") or "").strip()
    stable_asins = str(row.get("competitor_stable_asins") or "").strip()
    ppc_up = str(row.get("sellersprite_ppc_up_keywords") or "").strip()
    badges = [
        f"状态：{status}",
        f"抓词：{keyword_count}",
    ]
    if today_status:
        cache_part = f" {cache_date}" if today_status == "沿用缓存" and cache_date else ""
        badges.append(f"今日：{today_status}{cache_part}")
    if trend_status:
        badges.append(f"趋势：{trend_status}")
    if data_date:
        badges.append(f"日期：{data_date}")
    if ad_rows:
        badges.extend(
            [
                f"广告词：{ad_rows}",
                f"已命中：{exact_count}",
                f"近似：{near_count}",
                f"未命中：{no_match_count}",
            ]
        )
        if no_cache_count:
            badges.append(f"无缓存：{no_cache_count}")
    badges.extend([f"机会词：{opportunity_count}", f"高竞争：{high_count}"])
    if product_conclusion:
        badges.append(f"产品结论：{product_conclusion}")
    if competitor_pressure:
        badges.append(f"竞品词压力：{competitor_pressure}")
    if stable_asins:
        badges.append(f"稳定竞品：{stable_asins}")
    badge_html = "".join(f'<span class="metric-badge">{html.escape(item)}</span>' for item in badges)
    note_parts = []
    if ad_boundary:
        note_parts.append(f"广告边界：{ad_boundary}")
    keyword_judgement = _seller_sprite_keyword_judgement(row)
    if keyword_judgement:
        note_parts.append(keyword_judgement)
    if risk_summary:
        note_parts.append(f"风险摘要：{risk_summary}")
    if top_opportunities and top_opportunities != "暂无明确机会词":
        note_parts.append(f"机会词：{top_opportunities}")
    if missing_competitor:
        note_parts.append(f"竞品有我方缺口词：{missing_competitor}")
    if no_match_ad_terms:
        note_parts.append(f"广告消耗但自身反查无痕迹：{no_match_ad_terms}")
    if persistent_keywords:
        note_parts.append(f"连续需求词：{persistent_keywords}")
    if ppc_up:
        note_parts.append(f"PPC 上升风险：{ppc_up}")
    note_html = f'<p class="subtle">{html.escape("；".join(note_parts))}</p>' if note_parts else ""
    return '<div class="card-block"><strong>卖家精灵反查</strong><div class="metric-row">' + badge_html + "</div>" + note_html + "</div>"


def _seller_sprite_fusion_text(row: dict[str, object]) -> str:
    conclusion = str(row.get("product_level_conclusion") or "").strip()
    boundary = str(row.get("product_ad_boundary") or "").strip()
    pressure = str(row.get("competitor_keyword_pressure") or "").strip()
    missing = str(row.get("own_missing_competitor_keywords") or "").strip()
    no_match = str(row.get("own_ad_terms_not_in_sellersprite") or "").strip()
    today_status = str(row.get("sellersprite_today_status") or "").strip()
    cache_date = str(row.get("sellersprite_cache_date") or "").strip()
    trend_status = str(row.get("sellersprite_trend_status") or "").strip()
    parts: list[str] = []
    if conclusion:
        parts.append(f"结论 {conclusion}")
    if today_status:
        if today_status == "沿用缓存" and cache_date:
            parts.append(f"沿用缓存 {cache_date}")
        else:
            parts.append(f"今日卖家精灵 {today_status}")
    if trend_status:
        parts.append(f"趋势 {trend_status}")
    if pressure:
        parts.append(f"竞品词压力 {pressure}")
    if missing:
        parts.append(f"缺口词 {missing}")
    if no_match:
        parts.append(f"广告无反查 {no_match}")
    if boundary:
        parts.append(boundary)
    return "；".join(parts)


def _strong_frontend_tier_is_safe(shared: Any, frontend: dict[str, object]) -> bool:
    status = str(frontend.get("frontend_check_status") or "").strip()
    failure = str(frontend.get("frontend_failure_category") or "").strip()
    search_status = str(frontend.get("frontend_search_status") or "").strip()
    location_scope = str(frontend.get("frontend_location_scope") or "").strip().lower()
    comparability = str(frontend.get("competitor_comparability") or "").strip().lower()
    quality_score = shared._num_from_text(frontend.get("frontend_evidence_quality_score"))
    competitor_count = _frontend_competitor_count(shared, frontend)
    return (
        status == "已自动检查"
        and not _truthy(frontend.get("frontend_cache_used"))
        and not str(frontend.get("frontend_price_currency_warning") or "").strip()
        and not str(frontend.get("frontend_location_warning") or "").strip()
        and failure in {"", "none"}
        and (location_scope == "exact" or _truthy(frontend.get("frontend_location_exact")))
        and _truthy(frontend.get("frontend_location_verified"))
        and search_status == "已自动检查"
        and not _truthy(frontend.get("frontend_search_partial_evidence"))
        and competitor_count >= 2
        and comparability == "high"
        and quality_score >= 75
    )


def _frontend_display_tier(shared: Any, frontend: dict[str, object]) -> str:
    tier = str(frontend.get("frontend_evidence_display_tier") or frontend.get("frontend_evidence_tier") or "").strip()
    if tier != "强诊断可用":
        return tier
    return tier if _strong_frontend_tier_is_safe(shared, frontend) else "仅背景参考"


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
    tier = _frontend_display_tier(shared, frontend)
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
    counts = {
        "待前台检查": 0,
        "沿用缓存": 0,
        "已自动检查": 0,
        "读取失败": 0,
        "complete": 0,
        "usable": 0,
        "insufficient": 0,
        "failed": 0,
    }
    for row in rows:
        label = shared._frontend_status_label(str(row.get("frontend_check_status") or "待前台检查"), row)
        if label.startswith("沿用"):
            counts["沿用缓存"] += 1
        elif "读取失败" in label:
            counts["读取失败"] += 1
            counts["待前台检查"] += 1
        elif "待前台检查" in label:
            counts["待前台检查"] += 1
        else:
            counts["已自动检查"] += 1
        level = str(row.get("market_survey_completeness_level") or "").strip()
        if level in {"complete", "usable", "insufficient", "failed"}:
            counts[level] += 1
    return counts


def _has_public_demo_rows(rows: list[dict[str, str]]) -> bool:
    return any(
        str(row.get("sku") or "").startswith("SKU-DEMO-")
        or str(row.get("asin") or "").strip().upper().startswith("B0DEMO")
        for row in rows
    )


def _render_public_demo_reverse_lookup_test(rows: list[dict[str, str]]) -> str:
    if not _has_public_demo_rows(rows):
        return ""
    sample = PUBLIC_DEMO_REVERSE_LOOKUP_SAMPLE
    query = urlencode(
        {
            "marketplace": sample["marketplace"],
            "sku": sample["sku"],
            "asin": sample["asin"],
        }
    )
    product_url = f"https://www.amazon.com/dp/{sample['asin']}"
    return (
        '<div class="frontend-status-card">'
        '<span class="frontend-status-label">公开 ASIN 测试</span>'
        '<div class="summary-action">'
        f'<a class="button-link secondary" href="{html.escape(product_url)}" rel="noopener">打开测试商品</a>'
        f'<button class="button-link secondary" type="button" data-run-report-action="battle-diagnosis-one" data-run-report-query="{html.escape(query)}">测试单品反查</button>'
        "</div>"
        f'<span class="frontend-retry-status subtle" data-run-report-status="battle-diagnosis-one">{html.escape(sample["label"])}。外部站点可能返回验证码或要求登录，结果只用于链路测试。</span>'
        "</div>"
    )


def _render_frontend_status_summary(shared: Any, rows: list[dict[str, str]]) -> str:
    retry_html = (
        '<div class="summary-action frontend-cache-action frontend-refresh-panel">'
        '<div class="frontend-refresh-control">'
        '<button class="button-link secondary" type="button" data-run-report-action="frontend-retry">刷新调查队列</button>'
        '</div>'
        '<div class="frontend-status-stack">'
        '<div class="frontend-status-card frontend-primary-status">'
        '<span class="frontend-status-label">运行状态</span>'
        '<span class="frontend-retry-status subtle" data-run-report-status="frontend-retry">待运行，点击后一次完成商品页和卖家精灵调查。</span>'
        '</div>'
        f'{_render_public_demo_reverse_lookup_test(rows)}'
        '<div class="frontend-sellersprite-slot"></div>'
        '</div>'
        "</div>"
    )
    single_check_status_html = (
        '<p class="frontend-retry-status subtle" data-run-report-status="frontend-check-one">单产品按钮只检查当前 ASIN。</p>'
        if rows
        else ""
    )
    return "\n".join(
        [
            '<section class="section-card is-collapsed" id="frontend-evidence-status">',
            '<div class="ad-section-header"><h2>市场调查</h2><span class="status-badge status-muted">外部证据</span><button class="collapsible-toggle" type="button" data-collapse-toggle>展开</button></div>',
            '<p class="subtle">商品页、搜索页、竞品和卖家精灵的调查质量。缓存可参考，强操作只看完整证据。</p>',
            '<div class="collapsible-body">',
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
        evidence_tier = _frontend_display_tier(shared, row)
        evidence_method = str(row.get("frontend_check_method") or "").strip()
        stability = shared._frontend_stability_badge(row)
        evidence_audit = str(row.get("frontend_evidence_audit_detail") or "").strip()
        failure_reason = str(row.get("frontend_failure_reason") or row.get("frontend_last_error") or "").strip()
        def score_text(value: object) -> str:
            return "" if value is None or value == "" else str(value).strip()

        market_score = score_text(row.get("market_survey_completeness_score"))
        market_level = str(row.get("market_survey_completeness_level") or "").strip()
        market_tier = str(row.get("market_survey_decision_evidence_tier") or "").strip()
        market_missing = str(row.get("market_survey_missing_parts") or "").strip()
        market_steps = str(row.get("market_survey_recommended_fetch_steps") or "").strip()
        market_skip = str(row.get("market_survey_skip_reason") or "").strip()
        level_labels = {
            "complete": "完整",
            "usable": "可用",
            "insufficient": "待补",
            "failed": "失败",
            "strong": "强证据",
            "background": "背景参考",
        }
        market_level_label = level_labels.get(market_level, market_level)
        market_tier_label = level_labels.get(market_tier, market_tier)
        main_count = str(row.get("main_competitor_count") or "").strip()
        reference_count = str(row.get("reference_competitor_count") or "").strip()
        comparability = str(row.get("competitor_comparability_score") or "").strip()
        stability_days = str(row.get("competitor_stability_days") or "").strip()
        scalable_status = str(row.get("scalable_evidence_status") or "").strip()
        scalable_blockers = str(row.get("scalable_blockers") or "").strip()
        market_summary_html = ""
        if market_score or market_level:
            def score_number(value: object) -> int:
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    return 0

            product_score = row.get("amazon_product_page_completeness")
            search_score = row.get("amazon_search_page_completeness")
            own_score = row.get("sellersprite_own_completeness")
            pool_score = row.get("sellersprite_competitor_pool_completeness")
            reverse_score = row.get("sellersprite_competitor_reverse_completeness")
            trend_score = row.get("sellersprite_trend_completeness")
            amazon_total = score_number(product_score) + score_number(search_score)
            competitor_total = score_number(pool_score) + score_number(reverse_score)
            market_badges = [
                f"完整度 {market_score or '0'}/100",
                f"等级 {market_level_label}" if market_level_label else "",
                f"证据 {market_tier_label}" if market_tier_label else "",
                f"主竞品 {main_count or '0'}/3",
                f"参考竞品 {reference_count or '0'}",
                f"可比性 {comparability or '0'}/100",
                f"趋势 {stability_days or '0'}天",
                f"放量证据 {scalable_status}" if scalable_status else "",
                f"Amazon 前台完整度 {amazon_total}/35",
                f"卖家精灵完整度 {score_number(own_score)}/20",
                f"竞品完整度 {competitor_total}/30",
                f"趋势完整度 {score_number(trend_score)}/10",
            ]
            market_summary_html = (
                '<div class="card-block"><strong>市场调查完整度</strong>'
                '<div class="metric-row">'
                + "".join(f'<span class="metric-badge">{html.escape(item)}</span>' for item in market_badges if item)
                + "</div>"
                + (f'<p class="subtle">缺口：{shared._inline_markup(market_missing)}</p>' if market_missing else "")
                + (f'<p class="subtle">放量拦截：{shared._inline_markup(scalable_blockers)}</p>' if scalable_blockers else "")
                + (f'<p class="subtle">补抓：{shared._inline_markup(market_steps)}</p>' if market_steps else "")
                + (f'<p class="subtle">跳过：{shared._inline_markup(market_skip)}</p>' if market_skip and not market_steps else "")
                + "</div>"
            )
        frontend_reasons = shared._value_list(row.get("frontend_auto_conclusion_reasons"))
        frontend_reason_html = (
            "<ul>" + "".join(f"<li>{shared._inline_markup(reason)}</li>" for reason in frontend_reasons[:4]) + "</ul>"
            if frontend_reasons
            else f"<p>{shared._inline_markup(findings)}</p>"
        )
        seller_fusion = _seller_sprite_fusion_text(row)
        seller_fusion_html = (
            f'<p class="subtle"><strong>卖家精灵融合</strong>：{shared._inline_markup(seller_fusion)}</p>'
            if seller_fusion
            else ""
        )
        search_findings = str(row.get("frontend_search_findings") or "").strip()
        search_block = (
            f'<div class="card-block"><strong>核心词搜索页 / 前三竞品</strong><p>{shared._inline_markup(search_findings)}</p></div>'
            if search_findings
            else ""
        )
        frontend_detail_html = "".join(
            [
                '<details class="frontend-card-more">',
                "<summary>展开证据和下一步</summary>",
                '<div class="card-block"><strong>自动前台结论</strong>'
                f'<div class="metric-row"><span class="metric-badge">结论：{html.escape(auto_label)}</span><span class="metric-badge">证据质量：{html.escape(evidence_score)}</span>'
                + (f'<span class="metric-badge">口径：{html.escape(evidence_tier)}</span>' if evidence_tier else "")
                + (f'<span class="metric-badge">来源：{html.escape(evidence_method)}</span>' if evidence_method else "")
                + (f'<span class="metric-badge">{html.escape(stability)}</span>' if stability else "")
                + "</div>"
                + (f'<p class="subtle">证据审计：{shared._inline_markup(evidence_audit)}</p>' if evidence_audit else "")
                + f"{frontend_reason_html}"
                + seller_fusion_html
                + (f'<p class="subtle">失败分类：{shared._inline_markup(failure_reason)}</p>' if failure_reason else "")
                + "</div>",
                _render_frontend_gap_block(shared, row),
                search_block,
                f'<div class="card-block"><strong>系统判断方向</strong><p>{shared._inline_markup(str(row.get("suspected_issue") or auto_label or "N/A"))}</p></div>',
                f'<div class="card-block"><strong>保守动作</strong><p>{shared._inline_markup(str(row.get("conservative_action") or "N/A"))}</p></div>',
                f'<div class="card-block"><strong>下一步</strong><p>{shared._inline_markup(str(row.get("recommended_next_step") or "N/A"))}</p></div>',
                "</details>",
            ]
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
                    _render_seller_sprite_summary_block(row),
                    market_summary_html,
                    frontend_detail_html,
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
            "<h2>市场调查工具</h2>",
            "<p class=\"subtle\">默认不把无浏览器读取当成实时市场事实。这个按钮按运营用途刷新当前调查队列；如果端口不可用或读取失败，就保留已有缓存并提示原因。20次稳定性只用于验收测试。</p>",
            "</div>",
            '<div class="summary-action">',
            '<button class="button-link" type="button" data-run-report-action="frontend-retry">刷新调查队列并刷新报告</button>',
            '<span class="frontend-retry-status subtle" data-run-report-status="frontend-retry">成功后写入 frontend_check_results.json 并刷新报告；稳定性验收结果通过缓存字段展示，但网页按钮不做20次压力测试。</span>',
            "</div>",
            "</section>",
        ]
    )
