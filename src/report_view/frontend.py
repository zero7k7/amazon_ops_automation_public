from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _frontend_price_currency_warning(shared: Any, price: object, marketplace: object) -> str:
    text = re.sub(r"\s+", " ", str(price or "")).strip()
    if not text:
        return ""
    upper = text.upper()
    if any(marker in upper for marker in shared.BLOCKED_PRICE_CURRENCY_MARKERS):
        return f"价格币种异常：{text}，已忽略"
    expected_code = shared.EXPECTED_PRICE_CODE.get(str(marketplace or "").strip().upper())
    code_match = re.search(r"\b(USD|GBP|EUR|CAD|AUD|JPY|SGD)\b|^(USD|GBP|EUR|CAD|AUD|JPY|SGD)", upper)
    actual_code = (code_match.group(1) or code_match.group(2)) if code_match else ""
    if actual_code and expected_code and actual_code != expected_code:
        return f"价格币种异常：期望 {expected_code}，实际 {text}，已忽略"
    expected_symbol = shared.EXPECTED_PRICE_SYMBOL.get(str(marketplace or "").strip().upper())
    if expected_symbol:
        symbols = {symbol for symbol in ("£", "$", "€") if symbol in text}
        if symbols and expected_symbol not in symbols:
            return f"价格币种异常：期望 {expected_symbol}，实际 {text}，已忽略"
    return ""


def _frontend_location_note(shared: Any, row: dict[str, object]) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(row.get("frontend_location_note") or row.get("frontend_delivery") or "").strip(),
    )


def _frontend_location_scope(shared: Any, row: dict[str, object]) -> str:
    existing = str(row.get("frontend_location_scope") or "").strip()
    if existing:
        return existing
    text = _frontend_location_note(shared, row)
    if not text:
        return "missing"
    marketplace = str(row.get("marketplace") or "").strip().upper()
    lower = text.lower()
    if "未确认" in text or "无法确认" in text:
        return "missing"
    if "已设置" in text and marketplace in text:
        return "exact"
    for marker in shared.WRONG_LOCATION_MARKERS.get(marketplace, ()):
        if marker in lower:
            return "wrong"
    for marker in shared.MARKETPLACE_LOCATION_MARKERS.get(marketplace, ()):
        if marker in lower:
            return "marketplace"
    return "unknown"


def _frontend_location_warning(shared: Any, row: dict[str, object]) -> str:
    existing = str(row.get("frontend_location_warning") or "").strip()
    if existing:
        return existing
    text = _frontend_location_note(shared, row)
    marketplace = str(row.get("marketplace") or "").strip().upper()
    scope = _frontend_location_scope(shared, row)
    if scope == "exact":
        return ""
    if scope == "marketplace":
        return f"{marketplace} 地区非配置邮编：{text}"
    if scope == "wrong":
        return f"{marketplace} 地区异常：{text}"
    if scope == "missing":
        prefix = f"{marketplace} 地区未确认" if marketplace else "地区未确认"
        return prefix + (f"：{text}" if text else "")
    prefix = f"{marketplace} 地区未确认" if marketplace else "地区未确认"
    return f"{prefix}：{text}" if text else prefix


def _frontend_labeled_value(shared: Any, findings: object, label: str) -> str:
    match = re.search(rf"{re.escape(label)}：([^；;]+)", str(findings or ""))
    return match.group(1).strip() if match else ""


def _frontend_number(shared: Any, value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not match:
        return None
    token = match.group(0)
    if "," in token and "." in token:
        token = token.replace(",", "")
    elif "," in token:
        tail = token.rsplit(",", 1)[-1]
        token = token.replace(",", "") if len(tail) == 3 else token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _frontend_review_count(shared: Any, value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([kK])?", text)
    if not match:
        return None
    if match.group(2):
        try:
            return int(round(float(match.group(1).replace(",", ".")) * 1000))
        except ValueError:
            return None
    value_num = _frontend_number(shared, match.group(1))
    return int(round(value_num)) if value_num is not None else None


def _frontend_grade(shared: Any, score: int) -> str:
    if score >= 75:
        return "strong"
    if score >= 55:
        return "acceptable"
    if score > 0:
        return "weak"
    return "unknown"


def _derive_frontend_display_quality(shared: Any, row: dict[str, object]) -> dict[str, object]:
    existing_score = row.get("frontend_evidence_quality_score")
    if existing_score not in (None, "", 0, "0"):
        return {}
    marketplace = row.get("marketplace")
    findings = row.get("frontend_findings")
    price = row.get("frontend_price") or _frontend_labeled_value(shared, findings, "售价")
    rating_text = row.get("frontend_rating") or _frontend_labeled_value(shared, findings, "评分")
    reviews_text = row.get("frontend_reviews") or _frontend_labeled_value(shared, findings, "评论数")
    coupon = row.get("frontend_coupon") or _frontend_labeled_value(shared, findings, "Coupon")
    buy_box = row.get("frontend_buy_box") or _frontend_labeled_value(shared, findings, "Buy Box")
    warning = row.get("frontend_price_currency_warning") or _frontend_price_currency_warning(shared, price, marketplace)
    rating = _frontend_number(shared, rating_text)
    reviews = _frontend_review_count(shared, reviews_text)
    flags: list[str] = []
    score = 0
    if price and not warning:
        score += 20
    elif warning:
        flags.append("currency_mismatch")
    else:
        flags.append("price_missing")
    if rating is not None and rating >= 4.2:
        score += 20
    elif rating is not None and rating >= 4.0:
        score += 15
    elif rating is not None:
        score += 6
        flags.append("rating_low")
    else:
        flags.append("rating_missing")
    if reviews is not None and reviews >= 100:
        score += 15
    elif reviews is not None and reviews >= 20:
        score += 10
    elif reviews is not None:
        score += 5
        flags.append("reviews_low")
    else:
        flags.append("reviews_missing")
    if coupon and "未稳定识别" not in str(coupon):
        score += 15
    else:
        score += 5
        flags.append("coupon_missing")
    if "识别到购买按钮" in str(buy_box):
        score += 20
    elif buy_box:
        flags.append("buy_box_missing")
    else:
        flags.append("buy_box_unknown")
    if row.get("frontend_delivery"):
        score += 10
    else:
        score += 5
    if warning:
        score = 0
    core_missing = any(flag in flags for flag in ["price_missing", "rating_missing", "reviews_missing", "buy_box_unknown"])
    label = "自动证据不足，不能用于强诊断"
    if warning or core_missing:
        label = "自动证据不足，不能用于强诊断"
    elif any(flag in flags for flag in ["rating_low", "reviews_low", "buy_box_missing"]):
        label = "明确前台劣势"
    elif score >= 75:
        label = "未见明显前台劣势"
    elif score > 0:
        label = "证据冲突"
    conclusion_code = (
        "INSUFFICIENT_EVIDENCE"
        if warning or core_missing or score <= 0
        else "FRONTEND_WEAK"
        if label == "明确前台劣势"
        else "FRONTEND_OK"
        if label == "未见明显前台劣势"
        else "EVIDENCE_CONFLICT"
    )
    failure_category = "currency_mismatch" if warning else "missing_core_fields" if core_missing else ""
    failure_reason = warning
    if core_missing and not failure_reason:
        failure_reason = "缺少价格、评分、评论或购买按钮等核心前台字段"
    return {
        "frontend_price": "" if warning else price,
        "frontend_price_currency_warning": warning,
        "frontend_rating": rating_text,
        "frontend_reviews": reviews_text,
        "frontend_coupon": coupon,
        "frontend_buy_box": buy_box,
        "frontend_product_quality_score": score,
        "frontend_product_quality_grade": _frontend_grade(shared, score),
        "frontend_evidence_quality_score": score,
        "frontend_evidence_quality_grade": _frontend_grade(shared, score),
        "frontend_auto_conclusion_label": label,
        "frontend_auto_conclusion": conclusion_code,
        "frontend_auto_conclusion_reasons": [warning] if warning else [str(item) for item in [price, rating_text, reviews_text, coupon, buy_box] if item][:5],
        "frontend_product_quality_flags": flags,
        "frontend_failure_category": failure_category,
        "frontend_failure_reason": failure_reason,
    }


def _frontend_pct_text(shared: Any, value: object) -> str:
    number = shared._to_float(value)
    if number is None:
        return ""
    return f"{number:+.0%}"


def _frontend_evidence_audit(shared: Any, row: dict[str, object]) -> dict[str, object]:
    status = str(row.get("frontend_check_status") or "")
    search_status = str(row.get("frontend_search_status") or "")
    score = shared._to_float(row.get("frontend_evidence_quality_score")) or 0
    search_score = shared._to_float(row.get("frontend_search_quality_score")) or 0
    competitor_count = int(shared._to_float(row.get("frontend_competitor_count")) or 0)
    warning = str(row.get("frontend_price_currency_warning") or "")
    location_scope = _frontend_location_scope(shared, row)
    location_warning = _frontend_location_warning(shared, row)
    location_verified = shared.boolish_flag(row.get("frontend_location_verified")) or location_scope in {"exact", "marketplace"}
    location_exact = shared.boolish_flag(row.get("frontend_location_exact")) or location_scope == "exact"
    failure = str(row.get("frontend_failure_category") or "")
    partial_search = bool(row.get("frontend_search_partial_evidence")) or search_status == "已读取部分结果"
    cached = status.startswith("沿用")
    live = status == "已自动检查"
    reasons: list[str] = []
    detail_parts: list[str] = []
    if cached:
        reasons.append("沿用缓存")
    if warning:
        reasons.append("币种异常")
    if location_warning:
        reasons.append(location_warning)
    elif status == "已自动检查" and not location_verified:
        reasons.append("地区未确认")
    elif status == "已自动检查" and location_verified and not location_exact:
        reasons.append("地区非配置邮编")
    if failure and failure != "none":
        reasons.append(str(row.get("frontend_failure_reason") or failure))
    if partial_search:
        reasons.append("搜索页仅部分读取")
    if competitor_count and competitor_count < 2:
        reasons.append("可比竞品少于2个")
    if score and score < 55:
        reasons.append(f"证据质量偏低 {int(score)}")
    if search_status == "已自动检查":
        detail_parts.append("搜索页已读")
    elif search_status:
        detail_parts.append(search_status)
    if competitor_count:
        detail_parts.append(f"竞品 {competitor_count} 个")
    if row.get("own_search_position") not in (None, ""):
        detail_parts.append(f"自然位 {row.get('own_search_position')}")
    price_delta = _frontend_pct_text(shared, row.get("frontend_price_delta_pct"))
    if price_delta:
        detail_parts.append(f"价差 {price_delta}")
    rating_delta = shared._to_float(row.get("frontend_rating_delta"))
    if rating_delta is not None:
        detail_parts.append(f"评分差 {rating_delta:+.1f}")
    hard_location_problem = (status == "已自动检查" and not location_verified) or location_scope in {"wrong", "missing", "unknown"}
    if warning or hard_location_problem or (failure and failure != "none") or score <= 0:
        tier = "不可用"
        summary = "前台证据不可用于强诊断"
    elif live and location_exact and score >= 70 and search_status == "已自动检查" and competitor_count >= 2 and not partial_search:
        tier = "强诊断可用"
        summary = "前台证据通过质量门"
    elif score >= 45:
        tier = "仅背景参考"
        summary = "前台证据可辅助判断，不能单独放量"
    else:
        tier = "不可用"
        summary = "前台证据不足"
    if not reasons and tier == "强诊断可用":
        reasons.append("产品页和搜索页均可用")
    elif not reasons and tier == "仅背景参考":
        reasons.append("质量门未完全通过")
    return {
        "frontend_evidence_tier": tier,
        "frontend_evidence_audit_summary": summary,
        "frontend_evidence_audit_reasons": reasons[:5],
        "frontend_evidence_audit_detail": "；".join(detail_parts[:5]),
        "frontend_evidence_is_strong": tier == "强诊断可用",
    }


def _front_product_url(shared: Any, marketplace: object, asin: object) -> str:
    asin_text = str(asin or "").strip().upper()
    if not asin_text or asin_text == "N/A":
        return ""
    marketplace_text = str(marketplace or "").strip().upper()
    if marketplace_text == "UK":
        return f"https://www.amazon.co.uk/dp/{asin_text}?th=1"
    if marketplace_text == "US":
        return f"https://www.amazon.com/dp/{asin_text}"
    if marketplace_text == "DE":
        return f"https://www.amazon.de/dp/{asin_text}"
    return ""


def _front_search_url(shared: Any, marketplace: object, keyword: object) -> str:
    keyword_text = str(keyword or "").strip()
    if not keyword_text:
        return ""
    marketplace_text = str(marketplace or "").strip().upper()
    query = shared.quote_plus(keyword_text)
    if marketplace_text == "UK":
        return f"https://www.amazon.co.uk/s?k={query}"
    if marketplace_text == "US":
        return f"https://www.amazon.com/s?k={query}"
    if marketplace_text == "DE":
        return f"https://www.amazon.de/s?k={query}"
    return ""


def _keyword_config_lines(shared: Any) -> list[dict[str, object]]:
    if not shared.KEYWORD_CONFIG_PATH.exists():
        return []
    try:
        payload = json.loads(shared.KEYWORD_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    lines = payload.get("product_lines", []) if isinstance(payload, dict) else []
    return [line for line in lines if isinstance(line, dict)]


def _frontend_core_keyword(shared: Any, marketplace: str, product_name: str, sku: str, asin: str) -> str:
    text = f"{product_name} {sku} {asin}".lower()
    hint = shared._product_line_hint(product_name, sku, asin)
    matches: list[tuple[int, dict[str, object]]] = []
    for line in _keyword_config_lines(shared):
        patterns = [str(item).lower() for item in line.get("name_patterns", []) or []]
        line_marketplace = str(line.get("marketplace") or "").upper()
        product_line = str(line.get("product_line") or "")
        name = str(line.get("name") or line.get("product_line") or "")
        matched = any(pattern and pattern in text for pattern in patterns)
        matched = matched or hint in {name, product_line}
        if not matched:
            continue
        score = 0 if line_marketplace == marketplace else 1 if not line_marketplace else 2
        matches.append((score, line))
    if not matches:
        fallback = {
            "demo desk lamp": "led desk lamp",
            "demo notebook": "spiral notebook",
            "demo cable ties": "reusable cable ties",
        }
        return fallback.get(hint, "")
    line = sorted(matches, key=lambda item: item[0])[0][1]
    levels = line.get("keyword_levels", {})
    core_terms = levels.get("核心词", []) if isinstance(levels, dict) else []
    if not core_terms:
        core_terms = line.get("core_keywords", []) or []
    return str(core_terms[0]).strip() if core_terms else ""


def _load_frontend_check_results(shared: Any, output_dir: Path | None = None) -> dict[tuple[str, str, str], dict[str, object]]:
    path = (output_dir or shared.OUTPUT_DIR) / "frontend_check_results.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    records = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        return {}
    results: dict[tuple[str, str, str], dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = (
            str(record.get("marketplace") or "").strip().upper(),
            str(record.get("sku") or record.get("SKU") or "").strip(),
            str(record.get("asin") or record.get("ASIN") or "").strip().upper(),
        )
        if key[0] and key[2]:
            results[key] = record
    return results


def _frontend_check_template(shared: Any, reason: str, evidence: str, issue_type: str) -> dict[str, str]:
    text = f"{reason}；{evidence}；{issue_type}"
    if "推荐报价" in text or "Buy Box" in text:
        return {
            "frontend_check_focus": "Buy Box / 推荐报价；价格竞争力；配送时效",
            "suspected_issue": "疑似 Buy Box / 推荐报价不稳定",
            "questions_to_check": "当前是否丢购物车/推荐报价？；售价是否高于同类竞品？；配送时效是否比竞品慢？；是否有跟卖或竞争报价影响？",
            "conservative_action": "先确认推荐报价和价格，不加广告预算。",
            "recommended_next_step": "补前台 Buy Box、价格和配送截图后再决定是否调价或改广告。",
        }
    if "加购" in text and ("购买 0" in text or "购买0" in text or "购 0" in text):
        return {
            "frontend_check_focus": "价格竞争力；Coupon；配送时效；竞品压力",
            "suspected_issue": "疑似价格/Coupon/配送影响购买决策",
            "questions_to_check": "价格是否高于前三竞品？；是否没有 Coupon 而竞品有？；配送是否比竞品慢？；评分或评论数是否弱于竞品？",
            "conservative_action": "先对比前三竞品价格/Coupon/配送，再决定是否调价。",
            "recommended_next_step": "优先补竞品价格、Coupon、配送和评论截图。",
        }
    if "转化率下降" in text or "页面转化" in text or "承接" in text:
        return {
            "frontend_check_focus": "主图首屏；标题与核心词匹配；价格竞争力；Coupon；评分 / 评论数",
            "suspected_issue": "疑似页面承接弱或价格/Coupon竞争力不足",
            "questions_to_check": "主图是否一眼看出规格和卖点？；标题是否覆盖主要核心词？；价格/Coupon/评分/评论数是否弱于竞品？；最近差评集中在哪些问题？",
            "conservative_action": "广告端暂不加预算，只压高花费无单词。",
            "recommended_next_step": "补产品首屏和前三竞品截图后再决定是否动页面。",
        }
    if "广告归因弱" in text or "广告消耗" in text or "广告无单" in text or "点击" in text:
        return {
            "frontend_check_focus": "广告流量相关性；价格竞争力；Coupon；竞品压力",
            "suspected_issue": "疑似广告流量不准或价格竞争力不足",
            "questions_to_check": "搜索词是否和产品强相关？；是否有宽泛词、材质/尺寸不符词？；价格和 Coupon 是否弱于竞品？；是否某个活动带来大量无效点击？",
            "conservative_action": "核心词不直接否；明显不相关词才否定精准；相关高花费 0 单词先降竞价。",
            "recommended_next_step": "先看搜索词队列和前台价格/Coupon，再决定是否改广告结构。",
        }
    return {
        "frontend_check_focus": "价格竞争力；Coupon；评分 / 评论数；配送时效；主图首屏",
        "suspected_issue": "自动证据不足，不能用于强诊断",
        "questions_to_check": "价格是否高于前三竞品？；是否有 Coupon？；评分或评论数是否弱于竞品？；配送时效是否比竞品慢？；主图是否清楚表达规格和卖点？",
        "conservative_action": "自动证据不足时不加预算，先处理明确无效流量。",
        "recommended_next_step": "刷新前台缓存或补齐增强数据后再判断具体问题。",
    }


def _frontend_key_metrics(shared: Any, row: dict) -> str:
    evidence = str(row.get("key_evidence") or row.get("关键证据") or row.get("当前证据") or "").strip()
    if evidence:
        parts = [part.strip() for part in re.split(r"[；;]", evidence) if part.strip()]
        return "；".join(parts[:6]) if parts else evidence
    fragments: list[str] = []
    for label, key in [
        ("近7天点击", "recent_7d_ad_clicks"),
        ("近7天广告订单", "recent_7d_ad_orders"),
        ("近14天点击", "recent_14d_clicks"),
        ("近14天广告订单", "recent_14d_ad_orders"),
        ("近14天花费", "recent_14d_ad_spend"),
        ("总单", "recent_14d_total_orders"),
    ]:
        value = row.get(key)
        if value not in (None, ""):
            fragments.append(f"{label} {value}")
    return "；".join(fragments[:6]) if fragments else "等待前台截图补充"


def _build_frontend_check_queue(
    shared: Any,
    today_rows: list[dict[str, str]],
    listing_rows: list[dict[str, str]],
    marketplace: str,
    output_dir: Path | None = None,
    limit: int = 5,
) -> list[dict[str, str]]:
    frontend_results = _load_frontend_check_results(shared, output_dir or shared.OUTPUT_DIR)
    candidates: list[tuple[int, dict[str, str]]] = []
    strong_priority: dict[tuple[str, str, str], str] = {}
    for row in today_rows:
        priority = str(row.get("priority") or "")
        if priority not in {"P0", "P1"}:
            continue
        market = shared._row_marketplace(row, marketplace)
        sku = shared._row_sku(row)
        asin = shared._row_asin(row)
        if market and asin:
            strong_priority[(market, sku, asin)] = priority
            strong_priority[(market, "", asin)] = priority

    def add_candidate(row: dict[str, str], source: str, rank: int) -> None:
        market = shared._row_marketplace(row, marketplace)
        sku = shared._row_sku(row)
        asin = shared._row_asin(row)
        if not market or not asin or asin == "N/A":
            return
        key = (market, sku, asin)
        priority_text = str(row.get("priority") or strong_priority.get(key) or strong_priority.get((market, "", asin)) or "")
        if priority_text not in {"P0", "P1"}:
            return
        confirmed = shared._confirmed_status(row.get("confirmed_status"), "待确认")
        if confirmed in {"已核查", "已忽略"}:
            return
        issue_type = str(row.get("issue_type") or row.get("诊断类型") or source or "")
        action_group = str(row.get("action_group") or "")
        reason = str(row.get("primary_reason") or row.get("主因") or row.get("最可能异常方向") or row.get("trigger_reason") or issue_type)
        evidence = _frontend_key_metrics(shared, row)
        if issue_type == "数据质量问题":
            return
        if action_group == "成本 / 利润动作" or ("成本" in issue_type and "转化" not in reason) or ("利润" in issue_type and "转化" not in reason):
            return
        weak_text = f"{reason}；{evidence}；{issue_type}"
        if ("点击 0" in weak_text or "点击0" in weak_text) and ("花费 0" in weak_text or "花费0" in weak_text):
            return
        template = _frontend_check_template(shared, reason, evidence, issue_type)
        result = frontend_results.get(key) or frontend_results.get((market, "", asin), {})
        status = str(result.get("frontend_check_status") or "待前台检查")
        if status in {"需要截图确认", "需要截图", "待截图确认"}:
            status = "待前台检查"
        product_name = shared._row_product_name(row)
        core_keyword = _frontend_core_keyword(shared, market, product_name, sku, asin)
        row_out: dict[str, str] = {
            "marketplace": market,
            "product_name": product_name,
            "sku": sku or "N/A",
            "asin": asin,
            "product_url": _front_product_url(shared, market, asin),
            "frontend_core_keyword": core_keyword,
            "frontend_search_url": _front_search_url(shared, market, core_keyword),
            "trigger_reason": reason or source,
            "key_metrics": evidence,
            "frontend_check_status": status,
            "frontend_check_focus": str(result.get("frontend_check_focus") or template["frontend_check_focus"]),
            "frontend_findings": str(
                result.get("frontend_findings")
                or result.get("frontend_check_note")
                or "自动证据不足，不能用于强诊断；尚未读取到可用前台字段。"
            ),
            "suspected_issue": str(result.get("suspected_issue") or template["suspected_issue"]),
            "questions_to_check": str(result.get("questions_to_check") or template["questions_to_check"]),
            "conservative_action": str(result.get("conservative_action") or template["conservative_action"]),
            "recommended_next_step": str(result.get("recommended_next_step") or template["recommended_next_step"]),
            "confirmed_status": confirmed,
            "priority": priority_text,
            "source_section": source,
        }
        for field in [
            "search_term_or_target",
            "search_term",
            "suggested_action",
            "copy_action_line",
            "manual_action_taken",
            "normalized_action",
            "action_scope",
            "action_id",
            "confirmed_at",
            "report_date",
            "confirmed_note",
        ]:
            if row.get(field) not in (None, ""):
                row_out[field] = row.get(field)
        derived_quality = _derive_frontend_display_quality(shared, {**row_out, **result})
        for field, value in derived_quality.items():
            if value not in (None, "", [], {}):
                row_out[field] = value
        for field in [
            "frontend_data_date",
            "frontend_data_freshness",
            "frontend_check_method",
            "frontend_stability_total_attempts",
            "frontend_stability_success_count",
            "frontend_stability_failure_count",
            "frontend_stability_success_rate",
            "frontend_stability_passed",
            "frontend_search_status",
            "frontend_search_keyword",
            "frontend_search_url",
            "frontend_search_findings",
            "frontend_competitor_count",
            "frontend_competitors",
            "own_search_position",
            "frontend_last_error",
            "frontend_price",
            "frontend_price_currency_warning",
            "frontend_rating",
            "frontend_reviews",
            "frontend_coupon",
            "frontend_buy_box",
            "frontend_delivery",
            "frontend_location_note",
            "frontend_location_verified",
            "frontend_location_exact",
            "frontend_location_scope",
            "frontend_location_warning",
            "frontend_product_quality_score",
            "frontend_product_quality_grade",
            "frontend_product_quality_confidence",
            "frontend_product_quality_reasons",
            "frontend_product_quality_flags",
            "frontend_product_quality_components",
            "frontend_search_quality_score",
            "frontend_search_quality_grade",
            "frontend_search_quality_confidence",
            "frontend_search_quality_reasons",
            "frontend_search_quality_flags",
            "frontend_search_quality_components",
            "frontend_evidence_quality_score",
            "frontend_evidence_quality_grade",
            "frontend_evidence_quality_confidence",
            "frontend_auto_conclusion",
            "frontend_auto_conclusion_label",
            "frontend_auto_conclusion_reasons",
            "frontend_auto_conclusion_confidence",
            "frontend_auto_conclusion_basis",
            "frontend_auto_conclusion_blocked_ad_actions",
            "frontend_auto_conclusion_allowed_ad_actions",
            "frontend_evidence_tier",
            "frontend_evidence_audit_summary",
            "frontend_evidence_audit_reasons",
            "frontend_evidence_audit_detail",
            "frontend_evidence_is_strong",
            "frontend_failure_stage",
            "frontend_failure_category",
            "frontend_failure_reason",
            "frontend_failure_recoverability",
            "frontend_price_delta_pct",
            "frontend_rating_delta",
            "frontend_review_delta_pct",
            "frontend_competitor_price_median",
            "frontend_competitor_rating_avg",
            "frontend_competitor_review_median",
        ]:
            if result.get(field) not in (None, ""):
                row_out[field] = result.get(field)
        if row_out.get("frontend_price_currency_warning"):
            row_out["frontend_check_status"] = "待前台检查"
            row_out["frontend_price"] = ""
            row_out["frontend_findings"] = "自动证据不足，不能用于强诊断；" + str(row_out.get("frontend_price_currency_warning"))
        location_scope = _frontend_location_scope(shared, row_out)
        if row_out.get("frontend_location_note") or row_out.get("frontend_delivery"):
            row_out["frontend_location_scope"] = location_scope
            row_out["frontend_location_verified"] = location_scope in {"exact", "marketplace"}
            row_out["frontend_location_exact"] = location_scope == "exact"
            location_warning = _frontend_location_warning(shared, row_out)
            if location_warning:
                row_out["frontend_location_warning"] = location_warning
        row_out.update(_frontend_evidence_audit(shared, row_out))
        candidates.append((rank, row_out))

    for row in today_rows:
        priority = str(row.get("priority") or "")
        if priority not in {"P0", "P1"}:
            continue
        rank = 0 if priority == "P0" else 1
        add_candidate(row, str(row.get("source_section") or row.get("issue_type") or "今日动作"), rank)
    for row in listing_rows:
        add_candidate(row, shared.LISTING_REVIEW_LABEL, 2)

    deduped: dict[tuple[str, str, str], tuple[int, dict[str, str]]] = {}
    for rank, row in candidates:
        key = (row["marketplace"], row["sku"], row["asin"])
        previous = deduped.get(key)
        if previous is None or rank < previous[0]:
            deduped[key] = (rank, row)
    return [
        row
        for _, row in sorted(
            deduped.values(),
            key=lambda item: (item[0], shared.PRIORITY_ORDER.get(str(item[1].get("priority") or "P2"), 9), item[1].get("marketplace"), item[1].get("product_name")),
        )[:limit]
    ]


def _build_frontend_coverage_summary(shared: Any, frontend_rows: list[dict[str, object]]) -> dict[str, object]:
    total = len(frontend_rows)
    usable = 0
    live = 0
    cached = 0
    search_success = 0
    search_partial = 0
    stale_or_pending = 0
    strong = 0
    background = 0
    unusable = 0
    for row in frontend_rows:
        status = str(row.get("frontend_check_status") or "")
        score = shared._to_float(row.get("frontend_evidence_quality_score"))
        warning = str(row.get("frontend_price_currency_warning") or "")
        tier = str(row.get("frontend_evidence_tier") or "")
        is_live = status == "已自动检查"
        is_cached = status.startswith("沿用")
        if is_live:
            live += 1
        if is_cached:
            cached += 1
        if str(row.get("frontend_search_status") or "") == "已自动检查":
            search_success += 1
        if str(row.get("frontend_search_status") or "") == "已读取部分结果" or bool(row.get("frontend_search_partial_evidence")):
            search_partial += 1
        if status in {"待前台检查", "读取失败", ""}:
            stale_or_pending += 1
        if tier == "强诊断可用":
            strong += 1
        elif tier == "仅背景参考":
            background += 1
        elif tier == "不可用":
            unusable += 1
        if tier in {"强诊断可用", "仅背景参考"} or ((is_live or is_cached) and not warning and score is not None and score >= 45):
            usable += 1
    pct = (usable / total) if total else 0
    live_pct = (live / total) if total else 0
    search_pct = (search_success / total) if total else 0
    return {
        "frontend_queue_total": total,
        "frontend_usable_evidence_count": usable,
        "frontend_live_success_count": live,
        "frontend_cached_count": cached,
        "frontend_pending_or_stale_count": stale_or_pending,
        "frontend_search_success_count": search_success,
        "frontend_search_partial_count": search_partial,
        "frontend_strong_evidence_count": strong,
        "frontend_background_evidence_count": background,
        "frontend_unusable_evidence_count": unusable,
        "frontend_usable_evidence_rate": pct,
        "frontend_live_success_rate": live_pct,
        "frontend_search_success_rate": search_pct,
        "frontend_search_observed_rate": ((search_success + search_partial) / total) if total else 0,
        "frontend_coverage_label": f"{usable}/{total} 可用，{pct:.0%}" if total else "无前台队列",
    }
