from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any, Callable, TypeVar

ROOT_DIR = Path(__file__).resolve().parents[2]
_SHARED: Any | None = None
_T = TypeVar("_T")


def with_shared(shared: Any, func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    global _SHARED
    previous = _SHARED
    _SHARED = shared
    try:
        return func(*args, **kwargs)
    finally:
        _SHARED = previous


def _shared() -> Any:
    if _SHARED is None:
        raise RuntimeError("components_review shared context is not bound")
    return _SHARED


def _inline_markup(text: str) -> str:
    return _shared()._inline_markup(text)


def _confirmed_tag(status: object) -> str:
    return _shared()._confirmed_tag(status)


def _product_meta_html(*args: Any, **kwargs: Any) -> str:
    return _shared()._product_meta_html(*args, **kwargs)


def _marketplace_sort_key(value: object) -> tuple[int, str]:
    return _shared()._marketplace_sort_key(value)

def _render_review_list(rows: list[dict[str, str]], limit: int = 5) -> str:
    if not rows:
        return '<p class="subtle">当前没有需要明日复查的对象。</p>'
    parts = ['<div class="review-list">']
    for row in rows[:limit]:
        confirmed = str(row.get("confirmed_status") or "待确认")
        parts.append(
            "\n".join(
                [
                    '<div class="review-item">',
                    f'<strong>{html.escape(str(row.get("product_name") or "N/A"))}</strong> <span class="tag tag-gray">{html.escape(str(row.get("marketplace") or ""))}</span> <span class="{_confirmed_tag(confirmed)}">{html.escape(confirmed)}</span>',
                    f'<div class="card-meta">{_product_meta_html(row)}</div>',
                    f'<div class="search-term-meta">原因：{_inline_markup(str(row.get("review_reason") or "N/A"))}</div>',
                    f'<div class="search-term-meta">当前证据：{_inline_markup(str(row.get("current_evidence") or "N/A"))}</div>',
                    f'<div class="search-term-meta">明日复查：{_inline_markup(str(row.get("tomorrow_check") or "N/A"))}</div>',
                    "</div>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _render_optimization_notes(notes: list[str]) -> str:
    if not notes:
        return '<p class="subtle">当前没有可记录的自我优化建议。</p>'
    return "<ul>" + "".join(f"<li>{_inline_markup(note)}</li>" for note in notes) + "</ul>"


def _latest_json_rows(pattern: str) -> list[dict]:
    output_dir = ROOT_DIR / "data" / "output"
    paths = sorted(output_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        return []
    try:
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
    except Exception:
        return []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _render_action_review_cards(limit: int = 3, marketplace: str | None = None) -> str:
    rows = _latest_json_rows("action_review_*.json")
    if marketplace:
        marketplace_key = str(marketplace).upper()
        rows = [row for row in rows if str(row.get("marketplace") or "").upper() == marketplace_key]
    if not rows:
        return '<p class="subtle">还没有已执行动作复查记录。你确认过动作后，系统会在这里追踪效果。</p>'
    priority = {"暂未改善": 0, "待7天确认": 1, "样本不足": 2, "待观察": 3, "初步有效": 4, "有改善迹象": 5}
    rows = sorted(rows, key=lambda row: (priority.get(str(row.get("outcome") or ""), 9), str(row.get("marketplace") or ""), str(row.get("product_name") or "")))[:limit]
    parts = ['<div class="review-list">']
    for row in rows:
        outcome = str(row.get("outcome") or "待观察")
        tag = "tag-green" if outcome in {"初步有效", "有改善迹象"} else ("tag-yellow" if outcome in {"样本不足", "待观察", "待复查"} else "tag-red")
        title = f"{row.get('marketplace') or ''}｜{row.get('product_name') or ''}"
        parts.append(
            "\n".join(
                [
                    '<div class="review-item">',
                    f'<strong>{html.escape(title)}</strong> <span class="tag {tag}">{html.escape(outcome)}</span>',
                    f'<div class="card-meta">{_product_meta_html(row)}</div>',
                    f'<div class="search-term-meta">已执行：{_inline_markup(str(row.get("action_detail") or ""))}</div>',
                    f'<div class="search-term-meta">效果证据：{_inline_markup(str(row.get("effect_evidence") or row.get("review_status") or ""))}</div>',
                    f'<div class="search-term-meta">规则建议：{_inline_markup(str(row.get("rule_adjustment") or ""))}</div>',
                    "</div>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _render_yesterday_attribution(rows: list[dict[str, str]], limit: int = 6, compact: bool = False) -> str:
    if not rows:
        return '<p class="subtle">暂无昨日异常归因。</p>'
    if compact:
        rows = [row for row in rows if str(row.get("product_name") or "") == "站点整体"]
    else:
        site_rows = [row for row in rows if str(row.get("product_name") or "") == "站点整体"]
        product_rows = [
            row
            for row in rows
            if str(row.get("product_name") or "") != "站点整体"
            and str(row.get("attribution_type") or "") not in {"成本/利润限制", "正常波动"}
        ]
        rows = [*site_rows[:1], *product_rows[:1]]
    priority = {"P0": 0, "P1": 1, "P2": 2}
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            0 if (not compact and str(row.get("product_name") or "") == "站点整体") else 1,
            priority.get(str(row.get("priority") or ""), 9),
            _marketplace_sort_key(row.get("marketplace")),
        ),
    )[:limit]
    if compact:
        def split_evidence(row: dict[str, str]) -> tuple[str, str]:
            evidence = str(row.get("evidence") or "")
            evidence_parts = [part.strip() for part in evidence.split("；") if part.strip()]
            yesterday = (evidence_parts[0] if evidence_parts else "").replace("昨日", "昨天")
            seven_day = evidence_parts[1] if len(evidence_parts) > 1 else ""
            return yesterday, seven_day

        def metric_chips(text: str) -> str:
            if not text:
                return '<span class="metric-badge">暂无</span>'
            text = text.replace("近7天", "").replace("昨天", "")
            chunks = [chunk.strip() for chunk in text.replace("，", ",").split(",") if chunk.strip()]
            return "".join(f'<span class="metric-badge">{html.escape(chunk)}</span>' for chunk in chunks[:6])

        def brief_conclusion(row: dict[str, str]) -> str:
            marketplace = str(row.get("marketplace") or "N/A")
            kind = str(row.get("attribution_type") or "")
            if kind == "流量下降":
                return f"{marketplace} 初步判断为广告流量下降，优先核查预算消耗、活动展示降幅和核心词投放变化。"
            if kind == "点击后不转化":
                return f"{marketplace} 初步判断为点击后未转化，优先核查高花费词/ASIN、前台价格、Coupon、配送时效和前三竞品。"
            if kind == "广告归因弱":
                return f"{marketplace} 初步判断为广告归因偏弱，优先对比有花费未出单活动与自然出单 ASIN。"
            if kind == "数据不足":
                return f"{marketplace} 数据还不够稳，昨天的少单暂时不能拆成流量或转化问题。先补齐 ERP/广告覆盖。"
            return f"{marketplace} 昨天没有单一强异常，先按正常波动看。"

        def brief_card_body(row: dict[str, str]) -> str:
            yesterday, seven_day = split_evidence(row)
            return (
                f'<div class="attribution-brief-conclusion">{_inline_markup(brief_conclusion(row))}</div>'
                '<div class="attribution-metrics">'
                '<div class="attribution-metric-box"><span class="attribution-metric-title">昨天</span>'
                f'<div class="attribution-metric-row">{metric_chips(yesterday)}</div></div>'
                '<div class="attribution-metric-box"><span class="attribution-metric-title">近7天日均</span>'
                f'<div class="attribution-metric-row">{metric_chips(seven_day)}</div></div>'
                "</div>"
            )

        parts = ['<div class="attribution-brief-list">']
        for row in sorted_rows:
            tag_class = "tag-red" if str(row.get("priority") or "P1") == "P0" else "tag-yellow"
            parts.append(
                "\n".join(
                    [
                        '<div class="attribution-brief-item">',
                        f'<div class="attribution-brief-head">{html.escape(str(row.get("marketplace") or "N/A"))} <span class="tag {tag_class}">{html.escape(str(row.get("attribution_type") or "待判断"))}</span></div>',
                        f'<div class="attribution-brief-text">{brief_card_body(row)}</div>',
                        "</div>",
                    ]
                )
            )
        parts.append("</div>")
        return "".join(parts)
    parts = ['<div class="review-list attribution-list compact-attribution">']
    for row in sorted_rows:
        priority_tag = str(row.get("priority") or "P1")
        tag_class = "tag-red" if priority_tag == "P0" else "tag-yellow"
        product = str(row.get("product_name") or "N/A")
        is_site_row = product == "站点整体"
        title = f"站点整体｜{row.get('marketplace') or 'N/A'}" if is_site_row else f"重点产品｜{product}"
        meta = ""
        card_class = "review-item site-attribution" if is_site_row else "review-item product-attribution"
        if not is_site_row:
            meta = f'<div class="card-meta">{_product_meta_html(row)}</div>'
        parts.append(
            "\n".join(
                [
                    f'<div class="{card_class}">',
                    f'<strong>{html.escape(title)}</strong> <span class="tag {tag_class}">{html.escape(str(row.get("attribution_type") or "待判断"))}</span>',
                    meta,
                    f'<div class="search-term-meta"><strong>结论：</strong>{_inline_markup(str(row.get("judgement") or "N/A"))}</div>',
                    f'<div class="search-term-meta"><strong>关键数：</strong>{_inline_markup(str(row.get("evidence") or "N/A"))}</div>',
                    f'<div class="search-term-meta"><strong>先做：</strong>{_inline_markup(str(row.get("next_step") or "N/A"))}</div>',
                    "</div>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _render_yesterday_attribution_strip(rows: list[dict[str, str]]) -> str:
    site_rows = [row for row in rows if str(row.get("product_name") or "") == "站点整体"]
    if not site_rows:
        return '<p class="subtle">昨日异常摘要见摘要页。</p>'
    site_rows = sorted(site_rows, key=lambda row: _marketplace_sort_key(row.get("marketplace")))[:3]
    chips: list[str] = []
    for row in site_rows:
        marketplace = html.escape(str(row.get("marketplace") or "N/A"))
        kind = html.escape(str(row.get("attribution_type") or "待判断"))
        chips.append(f'<span class="attribution-chip">{marketplace}<span class="tag tag-gray">{kind}</span></span>')
    return '<div class="attribution-strip">' + "".join(chips) + '<a class="button-link" href="summary.html">查看昨日摘要</a></div>'


POSITIVE_REVIEW_JUDGEMENTS = {"明确改善", "初步有效", "有改善迹象", "有效", "可保留"}


def _review_display_judgement(row: dict[str, str]) -> str:
    judgement = str(row.get("judgement") or "数据不足")
    if judgement not in POSITIVE_REVIEW_JUDGEMENTS:
        return judgement
    if _is_truthy_flag(row.get("halo_only_conversion")) or _is_truthy_flag(row.get("target_sku_not_converted")):
        return "本 SKU 未验证"
    if not _is_truthy_flag(row.get("promoted_conversion_improved")):
        return "本 SKU 未验证"
    return judgement


def _review_tag_class(judgement: str) -> str:
    if judgement in POSITIVE_REVIEW_JUDGEMENTS:
        return "tag-green"
    if judgement in {"样本不足", "待7天确认", "待观察", "数据不足", "本 SKU 未验证"}:
        return "tag-yellow"
    return "tag-red"


def _action_effect_review_sort_key(row: dict[str, str]) -> tuple[int, str, str]:
    rank = {
        "变差": 0,
        "暂未改善": 1,
        "本 SKU 未验证": 2,
        "待人工复查": 3,
        "无明显变化": 4,
        "待7天确认": 5,
        "样本不足": 6,
        "数据不足": 7,
        "有改善迹象": 8,
        "初步有效": 9,
    }
    return (
        rank.get(_review_display_judgement(row), 99),
        str(row.get("marketplace") or ""),
        str(row.get("product_name") or row.get("asin") or ""),
    )


def _render_action_effect_review_rows(rows: list[dict[str, str]], limit: int = 5) -> str:
    if not rows:
        return '<p class="subtle">还没有可复盘的已执行动作。你确认执行后，系统会在 3 天/7 天窗口复查。</p>'
    sorted_rows = sorted(
        rows,
        key=_action_effect_review_sort_key,
    )[:limit]
    parts = ['<div class="review-list">']
    for row in sorted_rows:
        judgement = _review_display_judgement(row)
        tag = _review_tag_class(judgement)
        title = f"{row.get('marketplace') or ''}｜{row.get('product_name') or ''}"
        parts.append(
            "\n".join(
                [
                    '<div class="review-item">',
                    f'<strong>{html.escape(title)}</strong> <span class="tag {tag}">{html.escape(judgement)}</span> <span class="tag tag-gray">{html.escape(str(row.get("review_window") or ""))}</span>',
                    f'<div class="card-meta">{_product_meta_html(row)}</div>',
                    f'<div class="search-term-meta">执行：{_inline_markup(str(row.get("executed_action") or ""))}｜{html.escape(str(row.get("executed_at") or ""))}</div>',
                    f'<div class="card-block"><strong>复盘结论</strong><p>{_inline_markup(_keyword_review_decision_line(row))}</p></div>',
                    f'<div class="card-block"><strong>触发标准</strong><p>{_inline_markup(_keyword_review_trigger_standard(row))}</p></div>',
                    f'<div class="search-term-meta">复盘口径：{_inline_markup(_keyword_review_policy_note(row))}</div>',
                    f'<div class="search-term-meta">归因判断：{_inline_markup(_keyword_review_attribution_label(row))}</div>',
                    _review_anchor_metric_row(row),
                    _keyword_review_metric_row(row, "current_7d", "7天"),
                    _keyword_review_metric_row(row, "current_14d", "14天"),
                    _keyword_review_missing_metric_note(row),
                    f'<div class="search-term-meta">前后数据：{_inline_markup(str(row.get("effect_metrics") or ""))}</div>',
                    f'<div class="search-term-meta">下一步：{_inline_markup(_keyword_review_next_step(row))}</div>',
                    "</div>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _keyword_review_summary(rows: list[dict[str, str]]) -> str:
    buckets = {
        "有改善迹象": 0,
        "初步有效": 0,
        "待7天确认": 0,
        "样本不足": 0,
        "数据不足": 0,
        "本 SKU 未验证": 0,
        "暂未改善": 0,
    }
    under_three_days = 0
    for row in rows:
        judgement = _review_display_judgement(row)
        if judgement in buckets:
            buckets[judgement] += 1
        if str(row.get("review_window") or "") == "未满3天":
            under_three_days += 1
    ordered = [
        ("有效或改善", buckets["有改善迹象"] + buckets["初步有效"]),
        ("待7天确认", buckets["待7天确认"]),
        ("样本不足", buckets["样本不足"]),
        ("数据不足", buckets["数据不足"]),
        ("本 SKU 未验证", buckets["本 SKU 未验证"]),
        ("暂未改善", buckets["暂未改善"]),
        ("未满3天", under_three_days),
    ]
    cards = [
        f'<div class="ad-summary-card"><span>{html.escape(label)}</span><strong>{value}</strong></div>'
        for label, value in ordered
    ]
    return '<div class="ad-summary-grid keyword-review-summary">' + "".join(cards) + "</div>"


def _keyword_review_decision_bucket(row: dict[str, str]) -> tuple[str, str]:
    judgement = _review_display_judgement(row)
    window = str(row.get("review_window") or "")
    if window == "未满3天":
        return ("等待窗口", "未满 3 天，今天不做二次调整")
    if judgement in {"有改善迹象", "初步有效", "有效", "可保留"}:
        return ("可保留", "保留当前动作，不重复加价或追加预算")
    if judgement == "待7天确认":
        return ("等待确认", "继续等 7 天窗口，今天不做二次动作")
    if judgement == "样本不足":
        return ("停止追加", "不能证明动作有效，今天不追加预算或竞价")
    if judgement == "数据不足":
        return ("查数据", "先查投放对象和数据覆盖，今天不按效果下结论")
    if judgement == "本 SKU 未验证":
        return ("停止追加", "缺少本 SKU 转化证据，今天不追加预算或竞价")
    if judgement == "暂未改善":
        return ("降优先级", "动作未改善，停止追加并降低优先级")
    return ("待判断", "证据不足，先观察")


def _keyword_review_decision_distribution(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    order = ["可保留", "等待确认", "等待窗口", "停止追加", "查数据", "降优先级", "待判断"]
    counts = {label: 0 for label in order}
    examples: dict[str, str] = {}
    for row in rows:
        label, rule = _keyword_review_decision_bucket(row)
        counts[label] = counts.get(label, 0) + 1
        examples.setdefault(label, rule)
    cards = []
    for label in order:
        count = counts.get(label, 0)
        if count <= 0:
            continue
        cards.append(
            "\n".join(
                [
                    '<div class="ad-summary-card">',
                    f'<span>{html.escape(label)}</span>',
                    f'<strong>{count}</strong>',
                    f'<p class="subtle">{_inline_markup(examples.get(label) or "")}</p>',
                    '</div>',
                ]
            )
        )
    return '<div class="ad-summary-grid keyword-review-summary">' + "".join(cards) + "</div>"


def _keyword_review_standard_cards() -> str:
    standards = [
        ("复盘天数", "<3 天：不判有效；3-6 天：初判；>=7 天：正式判断。"),
        ("加竞价有效", "7 天内本 SKU 单 > 0 且销售额 > 0：有改善迹象。风险：销量低仍可能被判有效。"),
        ("加竞价停止", "点击 >= 8 或花费 >= 5 且无本 SKU 单：暂未改善，停止加价。风险：低样本可能误判。"),
        ("加竞价样本不足", "点击 < 8 且花费 < 5：样本不足，不追加预算。"),
        ("降竞价保留", "本 SKU 仍出单：保留；点击 <= 2 且花费 < 3：消耗收敛。风险：低流量 SKU 易误判收敛。"),
        ("否词 / 暂停", "7 天点击 = 0 且花费 = 0：初步有效；否则等 7 天确认或查匹配。风险：流量低时易误判。"),
        ("归因优先级", "有本 SKU 单优先；仅光环单：标记目标 SKU 未验证，不允许加价。"),
        ("ACOS 约束", "本 SKU 有单但 ACOS 高于目标时，只能算有成交，不能继续加价或放量。"),
        ("前后对比", "正式复盘应比较执行前 7 天和执行后 7 天；只有执行后数据时，结论需降级。"),
        ("低流量保护", "低流量 SKU 的消耗收敛只能叫低优先级观察，不能直接叫有效。"),
        ("库存约束", "低库存、断货恢复、新品期不能用同一套加价逻辑；库存不足时禁止放量。"),
        ("前台约束", "价格、评分、评论明显弱于竞品时，广告复盘不能单独判定可放量。"),
    ]
    cards = [
        "\n".join(
            [
                '<div class="ad-summary-card">',
                f'<span>{html.escape(title)}</span>',
                f'<p class="subtle">{_inline_markup(text)}</p>',
                '</div>',
            ]
        )
        for title, text in standards
    ]
    return '<div class="ad-summary-grid keyword-review-summary">' + "".join(cards) + "</div>"


def _keyword_review_sort_key(row: dict[str, str]) -> tuple[int, int, str, str]:
    priority = {
        "暂未改善": 0,
        "本 SKU 未验证": 1,
        "待人工复查": 2,
        "待7天确认": 3,
        "数据不足": 4,
        "样本不足": 5,
        "待观察": 6,
        "有改善迹象": 7,
        "初步有效": 8,
    }
    days_value = row.get("days_since_execution")
    days_text = "" if days_value is None else str(days_value)
    try:
        days = int(float(days_text))
    except ValueError:
        days = -1
    return (
        priority.get(_review_display_judgement(row), 9),
        -days,
        str(row.get("marketplace") or ""),
        str(row.get("search_term_or_target") or ""),
    )


def _is_truthy_flag(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "已是", "已验证"}


def _keyword_review_attribution_label(row: dict[str, str]) -> str:
    status = str(row.get("attribution_effect_status") or "").strip()
    note = str(row.get("attribution_effect_note") or "").strip()
    if _is_truthy_flag(row.get("halo_only_conversion")):
        label = "仅光环成交，不算本 SKU 有效"
    elif _is_truthy_flag(row.get("target_sku_not_converted")):
        label = "本 SKU 未验证成交"
    elif _is_truthy_flag(row.get("promoted_conversion_improved")):
        label = "本 SKU 成交有效"
    elif status:
        label = status
    else:
        label = "归因待观察"
    return label + (f"：{note}" if note else "")


def _review_metric_missing(value: object) -> bool:
    return str(value or "").strip().lower() in {"", "nan", "none", "null"}


def _review_metric_text(value: object, fallback: str = "") -> str:
    return fallback if _review_metric_missing(value) else str(value).strip()


def _keyword_review_metric_row(row: dict[str, str], prefix: str, label: str) -> str:
    days_value = row.get("days_since_execution")
    days_text = "" if days_value is None else str(days_value).strip()
    days = _to_float_for_review(days_text) if days_text else None
    if days is not None and days < 3:
        return ""
    if prefix == "current_14d" and days is not None and days < 7:
        return ""
    metrics = [
        f'{label} 点击 {_review_metric_text(row.get(f"{prefix}_clicks"), "N/A")}',
        f'{label} 花费 {_review_metric_text(row.get(f"{prefix}_spend"), "N/A")}',
        f'{label} 订单 {_review_metric_text(row.get(f"{prefix}_ad_orders"), "N/A")}',
        f'{label} 本 SKU 单 {_review_metric_text(row.get(f"{prefix}_promoted_ad_orders"), "N/A")}',
        f'{label} 光环单 {_review_metric_text(row.get(f"{prefix}_halo_ad_orders"), "N/A")}',
        f'{label} 总单 {_review_metric_text(row.get(f"{prefix}_total_orders"), "N/A")}',
        f'{label} ACOS {_review_metric_text(row.get(f"{prefix}_acos"), "N/A")}',
        f'{label} TACOS {_review_metric_text(row.get(f"{prefix}_tacos"), "N/A")}',
        f'{label} 库存 {_review_metric_text(row.get(f"{prefix}_available_stock"), "N/A")}',
    ]
    if prefix == "current_7d":
        metrics.insert(7, f'{label} 目标 ACOS {_review_metric_text(row.get("current_7d_target_acos"), "N/A")}')
    return '<div class="metric-row">' + "".join(f'<span class="metric-badge">{html.escape(metric)}</span>' for metric in metrics) + "</div>"


def _review_anchor_metric_row(row: dict[str, str]) -> str:
    source = str(row.get("review_data_source") or "").strip()
    if source != "execution_anchored_daily":
        return ""
    days_value = row.get("days_since_execution")
    days_text = "" if days_value is None else str(days_value).strip()
    days = _to_float_for_review(days_text) if days_text else None
    if days is not None and days < 3:
        return ""
    pre_range = f'{row.get("pre_7d_start") or "N/A"} 至 {row.get("pre_7d_end") or "N/A"}'
    post_3d_range = f'{row.get("post_3d_start") or "N/A"} 至 {row.get("post_3d_end") or "N/A"}'
    metrics = [
        f"执行前7天 {pre_range}",
        f'执行前本 SKU 单 {_review_metric_text(row.get("pre_7d_promoted_ad_orders"), "N/A")}',
        f'执行前总单 {_review_metric_text(row.get("pre_7d_total_orders"), "N/A")}',
        f'执行前 TACOS {_review_metric_text(row.get("pre_7d_tacos"), "N/A")}',
        f"执行后3天 {post_3d_range}",
        f'执行后3天覆盖天数 {_review_metric_text(row.get("post_3d_days"), "N/A")}',
        f'执行后3天本 SKU 单 {_review_metric_text(row.get("post_3d_promoted_ad_orders"), "N/A")}',
        f'执行后3天总单 {_review_metric_text(row.get("post_3d_total_orders"), "N/A")}',
        f'执行后3天 ACOS {_review_metric_text(row.get("post_3d_acos"), "N/A")}',
        f'执行后3天 TACOS {_review_metric_text(row.get("post_3d_tacos"), "N/A")}',
        f'执行后3天库存 {_review_metric_text(row.get("post_3d_available_stock"), "N/A")}',
    ]
    if days is None or days >= 7:
        post_range = f'{row.get("post_7d_start") or "N/A"} 至 {row.get("post_7d_end") or "N/A"}'
        metrics.extend(
            [
                f"执行后7天 {post_range}",
                f'执行后覆盖天数 {_review_metric_text(row.get("post_7d_days"), "N/A")}',
                f'执行后本 SKU 单 {_review_metric_text(row.get("post_7d_promoted_ad_orders"), "N/A")}',
                f'执行后总单 {_review_metric_text(row.get("post_7d_total_orders"), "N/A")}',
                f'执行后 ACOS {_review_metric_text(row.get("post_7d_acos"), "N/A")}',
                f'执行后 TACOS {_review_metric_text(row.get("post_7d_tacos"), "N/A")}',
                f'执行后库存 {_review_metric_text(row.get("post_7d_available_stock"), "N/A")}',
            ]
        )
    return '<div class="metric-row review-anchor-row">' + "".join(
        f'<span class="metric-badge">{html.escape(metric)}</span>' for metric in metrics
    ) + "</div>"


def _keyword_review_missing_metric_note(row: dict[str, str]) -> str:
    days = _to_float_for_review(row.get("days_since_execution"))
    if days < 3:
        return ""
    review_outcome = str(row.get("review_outcome") or "").strip()
    judgement = _review_display_judgement(row)
    if review_outcome == "insufficient_sample" or judgement in {"样本不足", "数据不足"}:
        return ""
    required = [
        ("current_7d_promoted_ad_orders", "7天本 SKU 单"),
        ("current_7d_acos", "7天 ACOS"),
        ("current_7d_tacos", "7天 TACOS"),
        ("current_7d_total_orders", "7天总单"),
        ("current_7d_available_stock", "7天库存"),
    ]
    if days >= 7:
        required.extend(
            [
                ("current_14d_promoted_ad_orders", "14天本 SKU 单"),
                ("current_14d_acos", "14天 ACOS"),
                ("current_14d_tacos", "14天 TACOS"),
                ("current_14d_total_orders", "14天总单"),
                ("current_14d_available_stock", "14天库存"),
            ]
        )
    missing = [label for field, label in required if _review_metric_missing(row.get(field))]
    if not missing:
        return ""
    block_reason = str(row.get("block_reason") or "").strip()
    reason_text = f"；原因：{block_reason}" if block_reason else ""
    return (
        '<div class="search-term-meta review-missing-metrics">'
        f'缺失复盘指标：{html.escape("、".join(missing))}{_inline_markup(reason_text)}'
        "</div>"
    )


def _keyword_action_scope_label(row: dict[str, str]) -> str:
    scope = str(row.get("action_scope") or "").strip()
    action = str(row.get("normalized_action") or "").strip()
    scope_labels = {
        "asin_target": "ASIN 定向",
        "search_term": "搜索词",
        "keyword": "关键词",
        "product": "产品级",
    }
    action_labels = {
        "bid_up": "加竞价",
        "bid_down": "降竞价",
        "negative_exact": "否定精准",
        "pause": "暂停",
        "create_exact": "新建精准",
    }
    scope_text = scope_labels.get(scope, scope or "对象")
    action_text = action_labels.get(action, action or "动作")
    return f"{scope_text}｜{action_text}"


def _keyword_review_policy_note(row: dict[str, str]) -> str:
    window = str(row.get("review_window") or "").strip() or "待复查"
    status = str(row.get("review_status") or "").strip()
    judgement = str(row.get("judgement") or "").strip()
    days = _to_float_for_review(row.get("days_since_execution"))
    if window == "未满3天":
        basis = "未满 3 天，只能看是否继续消耗，不能判断有效或失败"
    elif 3 <= days < 7 or window in {"3天后复盘", "3d_check", "day_3_check"}:
        basis = "3 天窗口只做初步判断，低点击或低花费仍按样本不足处理"
    elif window == "7天后复盘":
        basis = "7 天窗口可做效果判断，但本 SKU 成交优先于总订单"
    else:
        basis = "按当前复盘窗口判断"
    parts = [window, basis]
    if status:
        parts.append(status)
    if judgement:
        parts.append(f"当前结论：{judgement}")
    return "；".join(parts)


def _to_float_for_review(value: object) -> float:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(number) else number


def _keyword_review_trigger_standard(row: dict[str, str]) -> str:
    action = str(row.get("normalized_action") or "")
    judgement = str(row.get("judgement") or "")
    window = str(row.get("review_window") or "")
    days = _to_float_for_review(row.get("days_since_execution"))
    missing_click_or_spend = _review_metric_missing(row.get("current_7d_clicks")) or _review_metric_missing(
        row.get("current_7d_spend")
    )
    clicks7 = _to_float_for_review(row.get("current_7d_clicks"))
    spend7 = _to_float_for_review(row.get("current_7d_spend"))
    promoted7 = _to_float_for_review(row.get("current_7d_promoted_ad_orders"))
    sales7 = _to_float_for_review(row.get("current_7d_promoted_ad_sales") or row.get("current_7d_ad_sales"))
    halo7 = _to_float_for_review(row.get("current_7d_halo_ad_orders"))
    if window == "未满3天":
        return "触发标准：执行未满 3 天，禁止判定有效或失败。"
    if 3 <= days < 7 or window in {"3天后复盘", "3d_check", "day_3_check"}:
        return "触发标准：3 天初查，只看是否继续消耗、本 SKU 是否已有初步订单，不给有效结论，不追加预算或竞价。"
    if missing_click_or_spend:
        return "触发标准：7 天点击或花费缺失，不能判断动作效果。"
    if _is_truthy_flag(row.get("halo_only_conversion")) or (halo7 > 0 and promoted7 <= 0):
        return "触发标准：光环单 > 0 且本 SKU 单 = 0，不能作为本 SKU 有效证据。"
    if action == "bid_up":
        if promoted7 > 0 and sales7 > 0:
            return "触发标准：加竞价后 7 天本 SKU 单 > 0 且销售额 > 0，可保留当前竞价。"
        if clicks7 >= 8 or spend7 >= 5:
            return "触发标准：加竞价后 7 天点击 >= 8 或花费 >= 5，但本 SKU 单 = 0，停止继续加价。"
        return "触发标准：加竞价后 7 天点击 < 8 且花费 < 5，样本不足，不能追加预算。"
    if action == "bid_down":
        if promoted7 > 0:
            return "触发标准：降竞价后本 SKU 仍出单，说明降竞价没有打断成交，保留当前竞价。"
        if clicks7 <= 2 and spend7 < 3:
            return "触发标准：降竞价后 7 天点击 <= 2 且花费 < 3，消耗已收敛，低优先级观察。"
        return "触发标准：降竞价后仍有流量或花费，需要等 7 天确认订单和 ACOS。"
    if action in {"negative_exact", "pause"}:
        if clicks7 == 0 and spend7 == 0:
            return "触发标准：否词或暂停后 7 天点击 = 0 且花费 = 0，消耗已停止。"
        return "触发标准：否词或暂停后仍有点击或花费，需查匹配类型、ASIN 定向或数据覆盖。"
    if judgement == "数据不足":
        return "触发标准：当前搜索词窗口未匹配到该词或 ASIN，不能做效果结论。"
    return "触发标准：按复盘窗口、本 SKU 单、光环单、点击和花费共同判断。"


def _keyword_review_detail_lines(row: dict[str, str]) -> str:
    lines = [
        f"执行记录：{row.get('confirmed_note') or '无人工备注'}",
        f"报告日：{row.get('report_date') or 'N/A'}；复盘日：{row.get('review_date') or 'N/A'}",
        f"动作口径：{_keyword_action_scope_label(row)}",
    ]
    action_id = str(row.get("action_id") or "").strip()
    if action_id:
        lines.append(f"追踪 ID：{action_id}")
    return "".join(f'<div class="search-term-meta">{_inline_markup(line)}</div>' for line in lines)


def _keyword_review_decision_line(row: dict[str, str]) -> str:
    label, rule = _keyword_review_decision_bucket(row)
    action = str(row.get("normalized_action") or "")
    attribution = _keyword_review_attribution_label(row)
    if label == "可保留" and action == "bid_up":
        rule = "只保留当前竞价，今天不重复加价，避免用小样本追高"
    elif label == "可保留" and action in {"bid_down", "negative_exact", "pause"}:
        rule = "保留已执行动作，今天不回调，继续看本 SKU 单和 ACOS"
    elif label == "停止追加" and "光环" in attribution:
        rule = "有光环订单也不能证明本 SKU 有效，今天不追加预算或竞价"
    elif label == "查数据":
        rule = "先确认该词或 ASIN 是否仍在投放、是否改名、是否缺少广告窗口"
    return f"{label}：{rule}"


def _keyword_review_next_step(row: dict[str, str]) -> str:
    judgement = _review_display_judgement(row)
    raw_next_step = str(row.get("next_step") or "").strip()
    if judgement == str(row.get("judgement") or "数据不足").strip():
        return raw_next_step
    label, rule = _keyword_review_decision_bucket(row)
    return f"{label}：{rule}"


def _render_keyword_action_effect_review_rows(rows: list[dict[str, str]], limit: int = 5) -> str:
    if not rows:
        return '<p class="subtle">还没有词级动作复盘。你确认加价、降竞价或否词后，系统会按具体词/ASIN 跟踪 3 天和 7 天效果。</p>'
    sorted_rows = sorted(rows, key=_keyword_review_sort_key)[:limit]
    parts = [
        '<h4>判断硬标准</h4>',
        _keyword_review_standard_cards(),
        '<h4>复盘结论分布</h4>',
        _keyword_review_decision_distribution(rows),
        '<h4>复盘证据分布</h4>',
        _keyword_review_summary(rows),
        '<div class="review-list">',
    ]
    for row in sorted_rows:
        judgement = _review_display_judgement(row)
        tag = _review_tag_class(judgement)
        title = f"{row.get('marketplace') or ''}｜{row.get('search_term_or_target') or ''}"
        days_value = row.get("days_since_execution")
        days = "" if days_value is None else str(days_value).strip()
        review_age = f'{html.escape(days)}天' if days else "天数未知"
        parts.append(
            "\n".join(
                [
                    '<div class="review-item">',
                    f'<strong>{_inline_markup(title)}</strong> <span class="tag {tag}">{html.escape(judgement)}</span> <span class="tag tag-gray">{html.escape(str(row.get("review_window") or ""))}</span>',
                    f'<div class="card-meta">{html.escape(str(row.get("product_name") or ""))} ｜ {_product_meta_html(row)}</div>',
                    f'<div class="card-block"><strong>复盘结论</strong><p>{_inline_markup(_keyword_review_decision_line(row))}</p></div>',
                    f'<div class="card-block"><strong>触发标准</strong><p>{_inline_markup(_keyword_review_trigger_standard(row))}</p></div>',
                    f'<div class="search-term-meta">执行：{_inline_markup(str(row.get("executed_action") or ""))}｜{html.escape(str(row.get("executed_at") or ""))}｜已过 {review_age}</div>',
                    _keyword_review_detail_lines(row),
                    f'<div class="search-term-meta">复盘口径：{_inline_markup(_keyword_review_policy_note(row))}</div>',
                    f'<div class="search-term-meta">归因判断：{_inline_markup(_keyword_review_attribution_label(row))}</div>',
                    _review_anchor_metric_row(row),
                    _keyword_review_metric_row(row, "current_7d", "7天"),
                    _keyword_review_metric_row(row, "current_14d", "14天"),
                    _keyword_review_missing_metric_note(row),
                    f'<div class="search-term-meta">原始证据：{_inline_markup(str(row.get("effect_metrics") or ""))}</div>',
                    f'<div class="search-term-meta">下一步：{_inline_markup(_keyword_review_next_step(row))}</div>',
                    "</div>",
                ]
            )
        )
    parts.append("</div>")
    return "".join(parts)


def _render_semicolon_list(text: object) -> str:
    items = [item.strip() for item in str(text or "").split("；") if item.strip()]
    if not items:
        return '<p class="subtle">暂无。</p>'
    return "<ul>" + "".join(f"<li>{_inline_markup(item)}</li>" for item in items) + "</ul>"


def _render_semicolon_list_limited(text: object, limit: int = 2) -> str:
    items = [item.strip() for item in str(text or "").split("；") if item.strip()]
    if not items:
        return '<p class="subtle">暂无。</p>'
    return "<ul>" + "".join(f"<li>{_inline_markup(item)}</li>" for item in items[:limit]) + "</ul>"
