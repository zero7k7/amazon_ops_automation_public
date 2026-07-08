from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable


MARKET_SURVEY_COMPLETENESS_FIELDS = [
    "market_survey_completeness_score",
    "market_survey_completeness_level",
    "market_survey_missing_parts",
    "market_survey_recommended_fetch_steps",
    "market_survey_skip_reason",
    "amazon_product_page_completeness",
    "amazon_search_page_completeness",
    "sellersprite_own_completeness",
    "sellersprite_competitor_pool_completeness",
    "sellersprite_competitor_reverse_completeness",
    "sellersprite_trend_completeness",
    "sellersprite_data_quality_penalty",
    "market_survey_decision_evidence_tier",
]

SHELL_TITLE_MARKERS = (
    "sellersprite",
    "sellersprite_logo",
    "group created with sketch",
    "查流量来源",
    "卖家精灵",
    "traffic source",
)


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _num(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean(value).replace(",", "")
    if not text:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {"1", "true", "yes", "y", "是", "已验证", "已确认"}


def _date_text(value: object) -> str:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", _clean(value))
    return match.group(1) if match else ""


def _parse_date(value: object) -> date | None:
    text = _date_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _report_day(report_date: str | date | None) -> date:
    if isinstance(report_date, date):
        return report_date
    parsed = _parse_date(report_date)
    return parsed or date.today()


def _days_old(value: object, report_date: str | date | None) -> int | None:
    parsed = _parse_date(value)
    if not parsed:
        return None
    delta = (_report_day(report_date) - parsed).days
    # SellerSprite can be refreshed after the ads/ERP report date. That is current
    # market evidence for the operations run, so it must not be penalized as stale.
    return max(0, delta)


def _split_values(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = re.split(r"[；;、,|/]+", _clean(value))
    seen: set[str] = set()
    items: list[str] = []
    for raw in raw_items:
        item = " ".join(str(raw or "").split()).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            items.append(item)
    return items


def is_shell_title(value: object) -> bool:
    text = _clean(value)
    if not text:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in SHELL_TITLE_MARKERS)


def _keyword_count(row: dict[str, object]) -> int:
    for field in ["seller_sprite_keyword_count", "captured_count", "keyword_count"]:
        value = row.get(field)
        if _clean(value):
            return int(_num(value))
    return len(_split_values(row.get("own_sellersprite_keywords")))


def _seller_cache_days(row: dict[str, object], report_date: str | date | None) -> int | None:
    for field in ["seller_sprite_data_date", "sellersprite_cache_date", "data_date", "checked_at"]:
        days = _days_old(row.get(field), report_date)
        if days is not None:
            return days
    return None


def _missing_ratio(row: dict[str, object], missing_field: str, total_field: str) -> float:
    total = int(_num(row.get(total_field)) or 0)
    missing = int(_num(row.get(missing_field)) or 0)
    if missing <= 0:
        return 0.0
    if total <= 0:
        return 1.0
    return min(1.0, missing / total)


def _field_quality_gaps(
    row: dict[str, object],
    *,
    total_field: str,
    ppc_missing_field: str,
    monthly_missing_field: str,
) -> list[str]:
    gaps: list[str] = []
    if _missing_ratio(row, ppc_missing_field, total_field) > 0.5:
        gaps.append("PPC 字段缺失过半")
    if _missing_ratio(row, monthly_missing_field, total_field) > 0.5:
        gaps.append("月搜索字段缺失过半")
    return gaps


def _amazon_product_page_score(row: dict[str, object]) -> tuple[int, list[str]]:
    status = _clean(row.get("frontend_check_status") or row.get("frontend_status"))
    cache_used = _boolish(row.get("frontend_cache_used")) or status.startswith("沿用")
    warning = _clean(row.get("frontend_price_currency_warning"))
    failure = _clean(row.get("frontend_failure_category"))
    score = 0
    missing: list[str] = []
    if status == "已自动检查" and not warning and failure not in {"missing_core_fields", "currency_mismatch"}:
        score = 12 if cache_used else 14
        if _clean(row.get("frontend_price")):
            score += 1
        else:
            missing.append("产品页价格")
        if _clean(row.get("frontend_rating")):
            score += 1
        else:
            missing.append("产品页评分")
        if _clean(row.get("frontend_reviews")):
            score += 1
        else:
            missing.append("产品页评论数")
        if _clean(row.get("frontend_buy_box")):
            score += 1
        else:
            missing.append("Buy Box")
        if _clean(row.get("frontend_coupon")):
            score += 1
        else:
            missing.append("Coupon")
        if _clean(row.get("frontend_delivery")):
            score += 1
        score = min(score, 20)
        if cache_used:
            missing.append("产品页今日快照")
    elif cache_used:
        score = 8
        missing.append("产品页今日快照")
    else:
        missing.append("Amazon 产品页")
    return score, missing


def _amazon_search_score(row: dict[str, object]) -> tuple[int, list[str]]:
    status = _clean(row.get("amazon_search_validation_status") or row.get("frontend_search_status"))
    search_status = _clean(row.get("frontend_search_status"))
    competitor_count = int(_num(row.get("competitor_frontend_count") or row.get("frontend_competitor_count")))
    comparable_count = int(_num(row.get("comparable_competitor_count")))
    missing: list[str] = []
    if status == "已验证" or (search_status == "已自动检查" and competitor_count >= 3):
        score = 12
        if competitor_count >= 3:
            score += 2
        else:
            missing.append("前三竞品可见性")
        if comparable_count >= 2:
            score += 1
        else:
            missing.append("竞品价格评分评论对比")
        return min(score, 15), missing
    if status in {"部分", "已读，无池内竞品"} or search_status == "已读取部分结果" or competitor_count:
        return 7, ["Amazon 搜索页完整验证"]
    return 0, ["Amazon 搜索页"]


def _own_sellersprite_score(row: dict[str, object], report_date: str | date | None) -> tuple[int, list[str]]:
    status = _clean(row.get("seller_sprite_check_status"))
    today_status = _clean(row.get("sellersprite_today_status"))
    count = _keyword_count(row)
    cache_days = _seller_cache_days(row, report_date)
    missing: list[str] = []
    if status in {"", "无缓存", "待补", "失败"}:
        return 0, ["卖家精灵自己 ASIN"]
    if today_status == "今日已抓" or cache_days == 0:
        score = 20
    elif cache_days is not None and 0 <= cache_days <= 7:
        score = 13
        missing.append("卖家精灵自己 ASIN 今日快照")
    else:
        score = 5
        missing.append("卖家精灵自己 ASIN 有效缓存")
    if count < 3:
        score = max(0, score - 7)
        missing.append("自己 ASIN 关键词>=3")
    quality_gaps = _field_quality_gaps(
        row,
        total_field="seller_sprite_keyword_count",
        ppc_missing_field="seller_sprite_ppc_missing_count",
        monthly_missing_field="seller_sprite_monthly_searches_missing_count",
    )
    if quality_gaps:
        score = max(0, score - min(6, len(quality_gaps) * 3))
        missing.append("自己 ASIN 关键词字段质量")
    return score, missing


def _competitor_pool_score(row: dict[str, object]) -> tuple[int, list[str]]:
    count = int(_num(row.get("competitor_pool_count")))
    main_count = int(_num(row.get("main_competitor_count")))
    comparability_score = int(_num(row.get("competitor_comparability_score")))
    status = _clean(row.get("competitor_pool_status"))
    confidence = _clean(row.get("competitor_pool_confidence")).lower()
    rejected_reasons = _clean(row.get("competitor_rejection_reasons"))
    overlap = _clean(row.get("competitor_overlap_keywords") or row.get("competitor_source_keywords"))
    missing: list[str] = []
    if count <= 0 or status in {"", "待补", "竞品证据不足", "卖家精灵证据不足", "卖家精灵竞品发现失败"}:
        return 0, ["卖家精灵竞品池"]
    score = min(8, count * 2 + 1)
    if main_count >= 2:
        score += 4
    else:
        missing.append("主竞品至少 2 个")
    if comparability_score >= 65:
        score += 2
    else:
        missing.append("主竞品可比性")
    if count >= 3:
        score += 2
    else:
        missing.append("竞品池 3 个候选竞品")
    if confidence == "high" and overlap:
        score += 2
    elif confidence == "medium":
        score += 1
    else:
        missing.append("竞品池置信度")
    if overlap:
        score += 1
    else:
        missing.append("竞品共同关键词或来源词")
    if "标题为空" in rejected_reasons or "页面壳文本" in rejected_reasons or _num(row.get("competitor_shell_title_count")) > 0:
        score = max(0, score - 4)
        missing.append("竞品池页面壳文本清理")
    if _num(row.get("competitor_overlap_zero_count")) > 0 and not overlap:
        score = max(0, score - 3)
        missing.append("竞品池 overlap>0")
    return min(score, 15), missing


def _competitor_reverse_score(row: dict[str, object]) -> tuple[int, list[str]]:
    main_count = int(_num(row.get("main_competitor_count")))
    pool_count = int(_num(row.get("competitor_pool_count"))) or 0
    target_count = main_count if main_count >= 2 else max(3, pool_count)
    asin_count = int(_num(row.get("competitor_sellersprite_asin_count")))
    keyword_count = int(_num(row.get("competitor_sellersprite_keyword_count")))
    status = _clean(row.get("competitor_sellersprite_status"))
    if target_count <= 0:
        target_count = 3
    missing: list[str] = []
    if asin_count <= 0 or status in {"", "待补", "竞品反查待补", "竞品卖家精灵证据不足"}:
        return 0, ["竞品 ASIN 反查"]
    score = min(12, round(12 * min(asin_count, 3) / 3))
    if asin_count >= 2:
        score += 2
    else:
        missing.append("竞品 ASIN 反查至少 2/3")
    if keyword_count >= max(asin_count, 1) * 3:
        score += 1
    else:
        missing.append("竞品关键词字段")
    if asin_count < min(max(target_count, 2), 3):
        missing.append("主竞品 ASIN 反查齐全")
    quality_gaps = _field_quality_gaps(
        row,
        total_field="competitor_sellersprite_keyword_count",
        ppc_missing_field="competitor_sellersprite_ppc_missing_count",
        monthly_missing_field="competitor_sellersprite_monthly_searches_missing_count",
    )
    if quality_gaps:
        score = max(0, score - min(5, len(quality_gaps) * 3))
        missing.append("竞品反查字段质量")
    return min(score, 15), missing


def _trend_score(row: dict[str, object]) -> tuple[int, list[str]]:
    status = _clean(row.get("sellersprite_trend_status"))
    days = int(_num(row.get("sellersprite_history_days")))
    if status in {"7天趋势可用", "3天趋势可用"} and days >= 3:
        return (10 if days >= 7 else 8), []
    if days > 0:
        return 3, ["卖家精灵至少 3 天趋势"]
    return 0, ["卖家精灵历史趋势"]


def _quality_penalty(row: dict[str, object], report_date: str | date | None) -> tuple[int, list[str]]:
    penalties: list[tuple[int, str]] = []
    rejection = _clean(row.get("competitor_rejection_reasons"))
    if "标题为空" in rejection or "页面壳文本" in rejection or _num(row.get("competitor_shell_title_count")) > 0:
        penalties.append((5, "页面壳标题"))
    own_quality_gaps = _field_quality_gaps(
        row,
        total_field="seller_sprite_keyword_count",
        ppc_missing_field="seller_sprite_ppc_missing_count",
        monthly_missing_field="seller_sprite_monthly_searches_missing_count",
    )
    competitor_quality_gaps = _field_quality_gaps(
        row,
        total_field="competitor_sellersprite_keyword_count",
        ppc_missing_field="competitor_sellersprite_ppc_missing_count",
        monthly_missing_field="competitor_sellersprite_monthly_searches_missing_count",
    )
    quality_gaps = set(own_quality_gaps + competitor_quality_gaps)
    if "PPC 字段缺失过半" in quality_gaps:
        penalties.append((3, "PPC 字段缺失过半"))
    if "月搜索字段缺失过半" in quality_gaps:
        penalties.append((3, "月搜索字段缺失过半"))
    confidence = _clean(row.get("competitor_pool_confidence")).lower()
    overlap_count = _num(row.get("competitor_overlap_zero_count"))
    overlap_text = _clean(row.get("competitor_overlap_keywords") or row.get("competitor_source_keywords"))
    if overlap_count > 0 or (confidence == "high" and not overlap_text):
        penalties.append((4, "overlap_keyword_count=0"))
    cache_days = _seller_cache_days(row, report_date)
    if cache_days is None and _clean(row.get("seller_sprite_check_status")) not in {"", "无缓存", "待补"}:
        penalties.append((2, "卖家精灵日期缺失"))
    elif cache_days is not None and cache_days > 7:
        penalties.append((5, "卖家精灵缓存超过 7 天"))
    if any("失败" in _clean(row.get(field)) for field in ["seller_sprite_check_status", "competitor_discovery_status", "competitor_sellersprite_status"]):
        penalties.append((4, "抓取失败被展示"))
    total = min(20, sum(score for score, _ in penalties))
    return total, [reason for _, reason in penalties]


def _level(score: int, row: dict[str, object], missing: list[str], penalty_reasons: list[str]) -> str:
    product_page = int(_num(row.get("amazon_product_page_completeness")))
    own_score = int(_num(row.get("sellersprite_own_completeness")))
    pool_score = int(_num(row.get("sellersprite_competitor_pool_completeness")))
    reverse_count = int(_num(row.get("competitor_sellersprite_asin_count")))
    main_count = int(_num(row.get("main_competitor_count")))
    comparability_score = int(_num(row.get("competitor_comparability_score")))
    overlap_text = _clean(row.get("competitor_overlap_keywords") or row.get("competitor_source_keywords"))
    severe_shell = any("页面壳" in reason or "标题" in reason for reason in penalty_reasons + missing)
    complete_gate = (
        score >= 80
        and product_page >= 14
        and own_score >= 13
        and pool_score >= 10
        and main_count >= 2
        and comparability_score >= 65
        and bool(overlap_text)
        and reverse_count >= 2
        and not severe_shell
    )
    if complete_gate:
        return "complete"
    if score >= 60:
        return "usable"
    if score >= 30:
        return "insufficient"
    return "failed"


def _tier(level: str, row: dict[str, object], report_date: str | date | None) -> str:
    if level == "complete":
        if _clean(row.get("scalable_evidence_status")) != "可谨慎放量":
            return "usable"
        today_status = _clean(row.get("sellersprite_today_status"))
        cache_days = _seller_cache_days(row, report_date)
        if today_status == "沿用缓存" or (cache_days is not None and cache_days > 0):
            return "usable"
        return "strong"
    if level == "usable":
        return "usable"
    if level == "insufficient":
        return "weak"
    return "insufficient"


def _recommended_steps(missing: list[str]) -> list[str]:
    steps: list[str] = []
    missing_set = set(missing)
    text = "；".join(missing)
    if "产品页" in text or "价格" in text or "Buy Box" in text or "Coupon" in text:
        steps.append("补抓 Amazon 产品页")
    if "搜索页" in text or "前三竞品" in text or "竞品价格评分评论" in text:
        steps.append("补抓 Amazon 搜索页")
    if missing_set.intersection({"卖家精灵自己 ASIN", "卖家精灵自己 ASIN 今日快照", "卖家精灵自己 ASIN 有效缓存", "自己 ASIN 关键词>=3"}):
        steps.append("补抓卖家精灵自己 ASIN")
    if "自己 ASIN 关键词字段质量" in missing_set:
        steps.append("复核卖家精灵自己 ASIN 字段解析")
    if "竞品池" in text or "主竞品" in text:
        steps.append("补抓卖家精灵竞品池")
    if missing_set.intersection({"竞品 ASIN 反查", "竞品 ASIN 反查至少 2/3", "竞品 ASIN 反查齐全", "主竞品 ASIN 反查齐全", "竞品关键词字段"}):
        steps.append("补抓竞品 ASIN 反查")
    if "竞品反查字段质量" in missing_set:
        steps.append("复核竞品反查字段解析")
    if "历史趋势" in text or "至少 3 天趋势" in text:
        steps.append("积累卖家精灵历史趋势")
    if not steps and missing:
        steps.append("复核市场调查字段质量")
    return steps


def _fetch_priority(row: dict[str, object], score: int, missing: list[str]) -> str:
    priority = _clean(row.get("priority"))
    spend = _num(row.get("ad_spend") or row.get("recent_14d_ad_spend") or row.get("spend"))
    has_ad_action = bool(_clean(row.get("suggested_action") or row.get("copy_action_line"))) or bool(row.get("ad_action_items"))
    if priority == "P0" or score < 30:
        return "P0"
    if priority == "P1" or spend >= 20 or has_ad_action:
        return "P1"
    if missing:
        return "P2"
    return "P3"


def compute_market_survey_completeness(
    row: dict[str, object],
    *,
    report_date: str | date | None = None,
) -> dict[str, object]:
    product_score, product_missing = _amazon_product_page_score(row)
    search_score, search_missing = _amazon_search_score(row)
    own_score, own_missing = _own_sellersprite_score(row, report_date)
    pool_score, pool_missing = _competitor_pool_score(row)
    reverse_score, reverse_missing = _competitor_reverse_score(row)
    trend_score, trend_missing = _trend_score(row)
    penalty, penalty_reasons = _quality_penalty(row, report_date)

    raw_score = product_score + search_score + own_score + pool_score + reverse_score + trend_score
    score = max(0, min(100, int(raw_score - penalty)))
    missing = _split_values(
        [
            *product_missing,
            *search_missing,
            *own_missing,
            *pool_missing,
            *reverse_missing,
            *trend_missing,
            *penalty_reasons,
        ]
    )
    result: dict[str, object] = {
        "amazon_product_page_completeness": product_score,
        "amazon_search_page_completeness": search_score,
        "sellersprite_own_completeness": own_score,
        "sellersprite_competitor_pool_completeness": pool_score,
        "sellersprite_competitor_reverse_completeness": reverse_score,
        "sellersprite_trend_completeness": trend_score,
        "sellersprite_data_quality_penalty": penalty,
    }
    level = _level(score, {**row, **result}, missing, penalty_reasons)
    steps = _recommended_steps(missing)
    skip_reason = ""
    if level == "complete" and _clean(row.get("priority")) not in {"P0", "P1"}:
        skip_reason = "今日市场调查完整，普通产品跳过补抓"
    elif not steps:
        skip_reason = "暂无明确补抓缺口"
    result.update(
        {
            "market_survey_completeness_score": score,
            "market_survey_completeness_level": level,
            "market_survey_missing_parts": "；".join(missing),
            "market_survey_recommended_fetch_steps": "；".join(steps),
            "market_survey_skip_reason": skip_reason,
            "market_survey_decision_evidence_tier": _tier(level, row, report_date),
        }
    )
    return result


def enrich_market_survey_completeness(
    row: dict[str, object],
    *,
    report_date: str | date | None = None,
) -> dict[str, object]:
    enriched = dict(row)
    enriched.update(compute_market_survey_completeness(enriched, report_date=report_date))
    return enriched


def build_market_survey_fetch_plan(
    rows: Iterable[dict[str, object]],
    *,
    report_date: str | date | None = None,
) -> list[dict[str, object]]:
    plan: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        enriched = enrich_market_survey_completeness(row, report_date=report_date)
        missing = _split_values(enriched.get("market_survey_missing_parts"))
        steps = _split_values(enriched.get("market_survey_recommended_fetch_steps"))
        score = int(_num(enriched.get("market_survey_completeness_score")))
        level = _clean(enriched.get("market_survey_completeness_level"))
        priority = _fetch_priority(enriched, score, missing)
        skip_reason = _clean(enriched.get("market_survey_skip_reason"))
        if not skip_reason and level == "complete":
            skip_reason = "今日市场调查完整，跳过补抓"
        if not skip_reason and not steps:
            skip_reason = "暂无明确补抓缺口"
        plan.append(
            {
                "marketplace": _clean(enriched.get("marketplace")).upper(),
                "sku": _clean(enriched.get("sku")),
                "asin": _clean(enriched.get("asin")).upper(),
                "product_name": _clean(enriched.get("product_name")),
                "current_score": score,
                "completeness_level": level,
                "missing_parts": "；".join(missing),
                "recommended_fetch_steps": "；".join(steps),
                "fetch_priority": priority,
                "skip_reason": skip_reason if level == "complete" or not steps else "",
            }
        )
    return sorted(plan, key=lambda item: (str(item.get("fetch_priority") or "P3"), int(item.get("current_score") or 0)))
