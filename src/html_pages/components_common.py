from __future__ import annotations

import html
import re
from typing import Any


def _row_class(shared: Any, cells: list[str]) -> str:
    merged = " ".join(cells)
    if "今日必须处理" in merged or "高优先级" in merged:
        return "table-row-danger"
    if "可以放量" in merged:
        return "table-row-success"
    if "明天观察" in merged or "仅广告数据" in merged or "谨慎使用" in merged:
        return "table-row-warning"
    return ""


def _render_table(shared: Any, headers: list[str], rows: list[dict[str, str]]) -> str:
    parts = ['<div class="table-wrap"><table><thead><tr>']
    for header in headers:
        parts.append(f"<th>{shared._inline_markup(header)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows:
        cells = [str(row.get(header, "N/A")) for header in headers]
        class_name = _row_class(shared, cells)
        class_attr = f' class="{class_name}"' if class_name else ""
        parts.append(f"<tr{class_attr}>")
        for cell in cells:
            parts.append(f"<td>{shared._inline_markup(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_collapsed_section(
    shared: Any,
    title: str,
    content: str,
    intro: str = "",
    *,
    open_by_default: bool = False,
    section_id: str = "",
) -> str:
    state_class = "" if open_by_default else " is-collapsed"
    button_text = "收起" if open_by_default else "展开"
    intro_html = f'<p class="subtle">{html.escape(intro)}</p>' if intro else ""
    id_attr = f' id="{html.escape(section_id)}"' if section_id else ""
    return (
        f'<section class="section-card{state_class}"{id_attr}>'
        f'<div class="ad-section-header"><h2>{html.escape(title)}</h2>'
        f'<button class="collapsible-toggle" type="button" data-collapse-toggle>{button_text}</button></div>'
        f"{intro_html}"
        f'<div class="collapsible-body">{content}</div>'
        "</section>"
    )


def _render_collapsed_block(
    shared: Any,
    title: str,
    content: str,
    intro: str = "",
    *,
    open_by_default: bool = False,
) -> str:
    state_class = "" if open_by_default else " is-collapsed"
    button_text = "收起" if open_by_default else "展开"
    intro_html = f'<p class="subtle">{html.escape(intro)}</p>' if intro else ""
    return (
        f'<div class="ad-section{state_class}">'
        f'<div class="ad-section-header"><h3>{html.escape(title)}</h3>'
        f'<button class="collapsible-toggle" type="button" data-collapse-toggle>{button_text}</button></div>'
        f"{intro_html}"
        f'<div class="collapsible-body">{content}</div>'
        "</div>"
    )


def _render_bullets(shared: Any, items: list[str]) -> str:
    if not items:
        return '<p class="subtle">当前无可展示内容。</p>'
    parts = ["<ul>"]
    for item in items:
        parts.append(f"<li>{shared._inline_markup(item)}</li>")
    parts.append("</ul>")
    return "".join(parts)


def _tag_class(shared: Any, action: str) -> str:
    if action == "否定精准":
        return "tag tag-red"
    if action == "暂停ASIN定向":
        return "tag tag-orange"
    if action == "降竞价10%-20%":
        return "tag tag-yellow"
    if action == "保留":
        return "tag tag-green"
    return "tag tag-gray"


def _confirmed_tag(shared: Any, status: object) -> str:
    value = str(status or "待确认")
    if value == "已执行":
        return "tag tag-green"
    if value == "已忽略":
        return "tag tag-gray"
    if value == "已核查":
        return "tag tag-green"
    return "tag tag-yellow"


def _amazon_product_url(shared: Any, marketplace: object, asin: object) -> str:
    asin_text = str(asin or "").strip().upper()
    if not asin_text or asin_text == "N/A":
        return ""
    marketplace_text = str(marketplace or "").strip().upper()
    if marketplace_text == "UK":
        return f"https://www.amazon.co.uk/dp/{asin_text}?th=1"
    if marketplace_text == "DE":
        return f"https://www.amazon.de/dp/{asin_text}"
    if marketplace_text == "US":
        return f"https://www.amazon.com/dp/{asin_text}"
    return ""


def _asin_link_html(shared: Any, marketplace: object, asin: object) -> str:
    asin_text = str(asin or "N/A").strip().upper() or "N/A"
    url = _amazon_product_url(shared, marketplace, asin_text)
    if not url:
        return f"ASIN {html.escape(asin_text)}"
    return (
        f'ASIN {html.escape(asin_text)}'
        f' <a class="product-link" href="{html.escape(url)}" rel="noopener">打开前台</a>'
    )


def _product_meta_html(
    shared: Any,
    row: dict[str, object],
    *,
    asin_key: str = "asin",
    sku_key: str = "sku",
    marketplace_key: str = "marketplace",
    include_frontend_link: bool = True,
) -> str:
    asin = row.get(asin_key) or row.get("ASIN") or row.get("asin") or "N/A"
    sku = row.get(sku_key) or row.get("SKU") or row.get("sku") or "N/A"
    marketplace = row.get(marketplace_key) or row.get("站点") or row.get("marketplace") or ""
    if include_frontend_link:
        asin_html = _asin_link_html(shared, marketplace, asin)
    else:
        asin_html = f'ASIN {html.escape(str(asin or "N/A").strip().upper() or "N/A")}'
    return f'{asin_html} ｜ SKU {html.escape(str(sku or "N/A"))}'


def _frontend_key(shared: Any, row: dict[str, object]) -> tuple[str, str, str]:
    marketplace = str(row.get("marketplace") or row.get("站点") or "").strip().upper()
    sku = str(row.get("sku") or row.get("SKU") or "").strip()
    asin = str(row.get("asin") or row.get("ASIN") or "").strip().upper()
    return (marketplace, sku, asin)


def _build_frontend_lookup(
    shared: Any, rows: list[dict[str, str]]
) -> dict[tuple[str, str, str], dict[str, str]]:
    lookup: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        key = _frontend_key(shared, row)
        marketplace, sku, asin = key
        if not marketplace or not asin:
            continue
        lookup.setdefault(key, row)
        if asin:
            lookup.setdefault((marketplace, "", asin), row)
        if sku:
            lookup.setdefault((marketplace, sku, ""), row)
    return lookup


def _lookup_frontend_evidence(
    shared: Any,
    row: dict[str, object],
    frontend_lookup: dict[tuple[str, str, str], dict[str, str]] | None,
) -> dict[str, str] | None:
    if not frontend_lookup:
        return None
    marketplace, sku, asin = _frontend_key(shared, row)
    for key in ((marketplace, sku, asin), (marketplace, "", asin), (marketplace, sku, "")):
        if key in frontend_lookup:
            return frontend_lookup[key]
    return None


def _value_list(shared: Any, value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[；;/]", text) if part.strip()]


def _fmt_signed_percent(shared: Any, value: object) -> str:
    if value in (None, ""):
        return "样本不足"
    number = shared._num_from_text(value)
    if number is None:
        return "样本不足"
    return f"{number:+.1%}"


def _fmt_signed_number(shared: Any, value: object, digits: int = 1) -> str:
    if value in (None, ""):
        return "样本不足"
    number = shared._num_from_text(value)
    if number is None:
        return "样本不足"
    return f"{number:+.{digits}f}"


def _frontend_status_label(shared: Any, raw_status: str, row: dict[str, object]) -> str:
    if raw_status in {"需要截图确认", "需要截图", "待截图确认"}:
        return "待前台检查"
    if raw_status == "沿用上次前台数据" or raw_status.startswith("沿用历史前台数据"):
        cached_at = str(row.get("frontend_cache_checked_at") or "")
        if not cached_at:
            findings = str(row.get("frontend_findings") or "")
            match = re.search(r"沿用上次前台数据（(\d{4}-\d{2}-\d{2})", findings)
            cached_at = match.group(1) if match else ""
        cached_date = cached_at.split("T", 1)[0] if cached_at else ""
        return f"沿用 {cached_date} 前台数据" if cached_date else "沿用历史前台数据"
    return raw_status


def _frontend_findings_text(shared: Any, findings: str) -> str:
    return re.sub(
        r"沿用上次前台数据（(\d{4}-\d{2}-\d{2})T[^）]*）",
        r"沿用 \1 前台数据",
        findings,
    )


def _frontend_stability_badge(shared: Any, row: dict[str, object]) -> str:
    attempts = row.get("frontend_stability_total_attempts")
    success = row.get("frontend_stability_success_count")
    if attempts in (None, "") or success in (None, ""):
        return ""
    failure = row.get("frontend_stability_failure_count")
    rate = row.get("frontend_stability_success_rate")
    passed = row.get("frontend_stability_passed")
    parts = [f"{success}/{attempts}"]
    if failure not in (None, ""):
        parts.append(f"失败 {failure}")
    if rate not in (None, ""):
        try:
            parts.append(f"{float(rate):.0%}")
        except (TypeError, ValueError):
            parts.append(str(rate))
    if passed is not None:
        parts.append("通过" if bool(passed) else "未通过")
    return "20次验收：" + "，".join(str(part) for part in parts if str(part))


def _collect_report_counters(
    shared: Any,
    all_tasks: list[dict[str, str]],
    all_search: list[dict[str, str]],
    all_review: list[dict[str, str]],
    quality_rows: list[dict[str, str]],
    all_listing_reviews: list[dict[str, str]] | None = None,
) -> dict[str, int]:
    all_listing_reviews = all_listing_reviews or []

    def is_done(row: dict[str, str]) -> bool:
        return str(row.get("confirmed_status") or "") == "已执行"

    non_cost_tasks = [row for row in all_tasks if row.get("action_group") != "成本 / 利润动作"]
    pending_non_cost = [
        row
        for row in non_cost_tasks
        if not is_done(row) and not shared._is_observation_only_summary_row(row)
    ]
    active_listing = shared._exclude_executed_rows(all_listing_reviews)
    pending_ad_rows = [
        row
        for row in all_search
        if not is_done(row) and shared._ad_status_key(row) == "pending"
    ]
    return {
        "p0": sum(1 for row in pending_non_cost if row.get("priority") == "P0"),
        "p1": sum(1 for row in pending_non_cost if row.get("priority") == "P1") + min(len(active_listing), 6),
        "pending_ad": len(pending_ad_rows),
        "executed": sum(
            1 for row in [*all_tasks, *all_listing_reviews, *all_search] if is_done(row)
        ),
        "review": len(all_review),
        "cost": sum(1 for row in all_tasks if row.get("action_group") == "成本 / 利润动作"),
        "quality_warn": sum(
            1 for row in quality_rows if "正式分析" not in str(row.get("状态") or "")
        ),
    }


def _render_common_principles(shared: Any) -> str:
    return (
        '<section class="section-card"><h2>统一临时处理原则</h2>'
        + _render_bullets(
            shared,
            [
                "暂时不加广告预算",
                "核心词不直接否",
                "明显不相关词才否定精准",
                "相关高花费 0 单词先降竞价",
                "低点击低花费对象先观察",
                "等人工确认价格、主图、评价、Coupon、竞品和广告流量后，再决定是否改 Listing",
            ],
        )
        + "</section>"
    )


def _render_common_principles_body(shared: Any) -> str:
    return _render_bullets(
        shared,
        [
            "暂时不加广告预算",
            "核心词不直接否",
            "明显不相关词才否定精准",
            "相关高花费 0 单词先降竞价",
            "低点击低花费对象先观察",
            "等人工确认价格、主图、评价、Coupon、竞品和广告流量后，再决定是否改 Listing",
        ],
    )


def _render_common_chatgpt_materials(shared: Any) -> str:
    return (
        '<div class="alert alert-warning"><strong>建议发给 ChatGPT 的通用材料：</strong>'
        + _render_bullets(
            shared,
            [
                "自己产品前台首屏截图",
                "主图 / 五点 / A+ 截图",
                "前三竞品截图",
                "自己和竞品的价格、Coupon、评分、评论数",
                "最近差评截图",
                "广告处理队列截图",
            ],
        )
        + "</div>"
    )
