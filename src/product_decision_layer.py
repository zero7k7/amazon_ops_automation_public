from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from src.market_survey_completeness import MARKET_SURVEY_COMPLETENESS_FIELDS
from src.sellersprite_history import HISTORY_TREND_FIELDS


FINAL_DECISIONS = {
    "EXECUTE_TODAY",
    "DO_NOT_TOUCH",
    "FRONTEND_FIRST",
    "WAIT_REVIEW",
    "CONSERVATIVE_RUN",
    "SMALL_SCALE_ALLOWED",
    "DATA_INSUFFICIENT",
}
FRONTEND_GATED_GROWTH_ACTIONS = {"bid_up", "budget_up", "broad_scale", "create_exact_low_budget"}
PRODUCT_IDENTITY_FIELDS = ["marketplace", "sku", "asin"]
FRONTEND_EVIDENCE_DECISION_FIELDS = [
    "frontend_evidence_tier",
    "frontend_evidence_display_tier",
    "frontend_decision_evidence_tier",
    "frontend_evidence_is_strong",
]

DECISION_LABELS = {
    "EXECUTE_TODAY": "今天执行",
    "DO_NOT_TOUCH": "今天不动",
    "FRONTEND_FIRST": "先查前台",
    "WAIT_REVIEW": "等复盘",
    "CONSERVATIVE_RUN": "保守跑",
    "SMALL_SCALE_ALLOWED": "可小放量",
    "DATA_INSUFFICIENT": "数据不足",
}

MARKET_SURVEY_LEVEL_LABELS = {
    "complete": "完整",
    "strong": "强证据",
    "usable": "可用",
    "insufficient": "待补",
    "failed": "失败",
    "unknown": "未知",
}

EXECUTABLE_DECISIONS = {"EXECUTE_TODAY", "SMALL_SCALE_ALLOWED"}
INVENTORY_BLOCKING = {"OUT_OF_STOCK", "LOW_STOCK", "RESTOCK_RECOVERY"}
PRODUCT_FINAL_DECISION_REQUIRED_FIELDS = [
    *PRODUCT_IDENTITY_FIELDS,
    "product_name",
    "final_decision",
    "final_decision_label",
    "decision_priority",
    "decision_reason",
    "today_allowed_actions",
    "today_blocked_actions",
    "frontend_required",
    "frontend_posture",
    "frontend_evidence_state",
    "frontend_blocking_reasons",
    *FRONTEND_EVIDENCE_DECISION_FIELDS,
    "frontend_check_status",
    "frontend_cache_used",
    "frontend_failure_category",
    "frontend_price_currency_warning",
    "frontend_location_warning",
    "frontend_search_status",
    "frontend_search_partial_evidence",
    "frontend_auto_conclusion",
    "frontend_auto_conclusion_label",
    "frontend_evidence_quality_score",
    "frontend_evidence_audit_summary",
    "frontend_evidence_audit_detail",
    "inventory_constraint",
    "feedback_cooldown_status",
    "keyword_memory_summary",
    "ad_action_summary",
    "next_review_date",
    "evidence_used",
    "confidence",
    "coupon",
    "competitor_comparability",
    "comparable_competitor_count",
    "competitor_mismatch_reason",
    "frontend_location_scope",
    "frontend_location_verified",
    "frontend_location_exact",
    "frontend_location_uncertain",
    "frontend_location_block_reason",
    "last_updated",
    "fusion_issue_type",
    "fusion_confidence",
    "fusion_action_gate",
    "fusion_reason",
    "fusion_today_action",
    "fusion_do_not_do",
    "fusion_review_window",
    "fusion_evidence_flags",
    "fusion_missing_evidence",
    "product_level_conclusion",
    "product_ad_boundary",
    "final_ad_allowed_actions",
    "final_ad_blocked_actions",
    "own_sellersprite_keywords",
    "competitor_discovery_status",
    "competitor_discovery_error",
    "competitor_discovery_source_page",
    "competitor_discovery_source",
    "competitor_pool_status",
    "competitor_pool_asins",
    "competitor_pool_count",
    "competitor_pool_confidence",
    "main_competitor_asins",
    "main_competitor_count",
    "reference_competitor_asins",
    "reference_competitor_count",
    "competitor_comparability_score",
    "competitor_spec_match_status",
    "competitor_price_band_status",
    "competitor_review_tier_status",
    "competitor_stability_days",
    "scalable_evidence_status",
    "scalable_blockers",
    "scalable_allowed_actions",
    "competitor_overlap_keywords",
    "competitor_source_keywords",
    "competitor_rejected_count",
    "competitor_rejection_reasons",
    "competitor_sellersprite_keywords",
    "competitor_shared_keywords",
    "own_missing_competitor_keywords",
    "own_ad_terms_not_in_sellersprite",
    "competitor_frontend_status",
    "competitor_frontend_asins",
    "competitor_frontend_count",
    "amazon_search_validation_status",
    "amazon_search_visible_competitors",
    "competitor_sellersprite_status",
    "competitor_sellersprite_asin_count",
    "competitor_sellersprite_keyword_count",
    "competitor_keyword_pressure",
    "frontend_competitiveness",
    *MARKET_SURVEY_COMPLETENESS_FIELDS,
    *HISTORY_TREND_FIELDS,
]


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _market_survey_label(value: object) -> str:
    text = _clean(value)
    return MARKET_SURVEY_LEVEL_LABELS.get(text, text)


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = _clean(value).lower()
    return text in {"1", "true", "yes", "y", "是", "已确认", "已验证"}


def _num(value: object) -> float:
    text = _clean(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def _ratio_num(value: object) -> float:
    text = _clean(value).replace(",", "")
    if not text:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        number = float(match.group(0))
    except ValueError:
        return 0.0
    if "%" in text:
        return number / 100
    return number / 100 if number > 5 else number


def _product_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        _clean(row.get("marketplace")).upper(),
        _clean(row.get("sku")),
        _clean(row.get("asin")).upper(),
    )


def product_key_text(row: dict[str, object]) -> str:
    return "||".join(_product_key(row))


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _parse_price(value: object) -> float | None:
    text = _clean(value)
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_coupon(coupon_raw: object, price: object = None) -> dict[str, object]:
    raw = _clean(coupon_raw)
    price_value = _parse_price(price)
    if not raw:
        return {
            "coupon_raw": "",
            "coupon_type": "unknown",
            "coupon_value": "",
            "final_price_estimate": price_value,
            "coupon_confidence": "low",
        }
    lower = raw.lower()
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", lower)
    amount_match = re.search(r"[$£€]\s*(\d+(?:\.\d+)?)", raw)
    if percent_match:
        value = float(percent_match.group(1))
        final_price = price_value * (1 - value / 100) if price_value is not None else None
        return {
            "coupon_raw": raw,
            "coupon_type": "percent",
            "coupon_value": value,
            "final_price_estimate": round(final_price, 2) if final_price is not None else "",
            "coupon_confidence": "high",
        }
    if amount_match:
        value = float(amount_match.group(1))
        final_price = max(price_value - value, 0) if price_value is not None else None
        return {
            "coupon_raw": raw,
            "coupon_type": "amount",
            "coupon_value": value,
            "final_price_estimate": round(final_price, 2) if final_price is not None else "",
            "coupon_confidence": "high",
        }
    if any(token in lower for token in ["coupon", "优惠", "savings"]):
        return {
            "coupon_raw": raw,
            "coupon_type": "unknown",
            "coupon_value": "",
            "final_price_estimate": price_value,
            "coupon_confidence": "low",
        }
    return {
        "coupon_raw": raw,
        "coupon_type": "unknown",
        "coupon_value": "",
        "final_price_estimate": price_value,
        "coupon_confidence": "low",
    }


def _competitor_list(frontend: dict[str, object]) -> list[dict[str, object]]:
    raw = frontend.get("frontend_competitors")
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [row for row in parsed if isinstance(row, dict)]
    return []


def competitor_comparability(frontend: dict[str, object], product_name: str = "") -> dict[str, object]:
    explicit_level = _clean(frontend.get("competitor_comparability")).lower()
    explicit_count_source = frontend.get("comparable_competitor_count")
    if _clean(explicit_count_source) == "":
        explicit_count_source = frontend.get("frontend_competitor_count")
    explicit_count_text = _clean(explicit_count_source)
    explicit_count = int(_num(explicit_count_text)) if explicit_count_text else None
    explicit_reason = _clean(frontend.get("competitor_mismatch_reason"))
    if explicit_level in {"low", "unknown"} or (explicit_count is not None and explicit_count < 2):
        level = explicit_level or "low"
        return {
            "competitor_comparability": level,
            "comparable_competitor_count": explicit_count or 0,
            "competitor_mismatch_reason": explicit_reason or "可比竞品少于2个，价格/评分结论仅参考",
        }
    if explicit_level in {"medium", "high"} and explicit_count is not None and explicit_count >= 2:
        return {
            "competitor_comparability": explicit_level,
            "comparable_competitor_count": explicit_count,
            "competitor_mismatch_reason": explicit_reason,
        }
    competitors = _competitor_list(frontend)
    if not competitors:
        return {
            "competitor_comparability": "unknown",
            "comparable_competitor_count": 0,
            "competitor_mismatch_reason": "未稳定读取竞品标题，价格结论仅参考",
        }
    product_text = product_name.lower()
    useful_tokens = [token for token in re.split(r"[^a-z0-9]+", product_text) if len(token) >= 4]
    if not useful_tokens:
        return {
            "competitor_comparability": "unknown",
            "comparable_competitor_count": 0,
            "competitor_mismatch_reason": "产品名缺少可比关键词，竞品价格/评分结论仅参考",
        }
    comparable = 0
    mismatch: list[str] = []
    for comp in competitors[:3]:
        title = _clean(comp.get("title") or comp.get("name") or comp.get("asin")).lower()
        if any(token in title for token in useful_tokens):
            comparable += 1
        else:
            mismatch.append(_clean(comp.get("asin") or comp.get("title") or "竞品"))
    if comparable >= 2:
        return {
            "competitor_comparability": "medium",
            "comparable_competitor_count": comparable,
            "competitor_mismatch_reason": "",
        }
    return {
        "competitor_comparability": "low",
        "comparable_competitor_count": comparable,
        "competitor_mismatch_reason": "可比竞品少于2个，价格/评分结论仅参考",
    }


def frontend_location_constraint(frontend: dict[str, object]) -> dict[str, object]:
    scope = _clean(frontend.get("frontend_location_scope")).lower()
    warning = _clean(frontend.get("frontend_location_warning"))
    note = _clean(frontend.get("frontend_location_note") or frontend.get("frontend_delivery") or frontend.get("visible_location"))
    verified_raw = frontend.get("frontend_location_verified")
    exact_raw = frontend.get("frontend_location_exact")
    verified = _boolish(verified_raw) if verified_raw is not None else False
    exact = _boolish(exact_raw) if exact_raw is not None else scope == "exact"
    text = " ".join(item for item in [scope, warning, note] if item).lower()
    if warning:
        reason = warning
    elif verified and exact:
        return {
            "frontend_location_scope": scope or "exact",
            "frontend_location_verified": True,
            "frontend_location_exact": True,
            "frontend_location_uncertain": False,
            "frontend_location_block_reason": "",
        }
    elif exact and not verified:
        reason = "地区待确认，当前前台证据不能用于放量"
    elif scope in {"wrong", "missing", "unknown"}:
        reason = "地区待确认，当前前台证据不能用于放量"
    elif scope == "marketplace" or (verified and not exact):
        reason = "地区非配置邮编，当前前台证据仅背景参考"
    elif any(token in text for token in ["未确认", "无法确认", "not confirmed", "unknown"]):
        reason = "地区待确认，当前前台证据不能用于放量"
    elif note and not verified:
        reason = "地区待确认，当前前台证据不能用于放量"
    else:
        reason = ""
    return {
        "frontend_location_scope": scope,
        "frontend_location_verified": bool(verified),
        "frontend_location_exact": False,
        "frontend_location_uncertain": bool(reason),
        "frontend_location_block_reason": reason,
    }


def frontend_constraints(frontend: dict[str, object] | None, product_name: str = "") -> dict[str, object]:
    if not frontend:
        return {
            "frontend_posture": "unknown",
            "frontend_blocking_reasons": [],
            "allowed_ad_actions": ["observe", "bid_down", "negative_exact"],
            "blocked_ad_actions": [],
            "frontend_required": False,
            "frontend_check_status": "",
            "frontend_cache_used": False,
            "frontend_evidence_is_strong": False,
            "frontend_decision_evidence_tier": "",
            **{field: "" for field in MARKET_SURVEY_COMPLETENESS_FIELDS},
            "frontend_failure_category": "",
            "frontend_price_currency_warning": "",
            "frontend_search_status": "",
            "frontend_search_partial_evidence": False,
            "frontend_auto_conclusion": "",
            "frontend_auto_conclusion_label": "",
            "frontend_evidence_quality_score": "",
            "coupon": parse_coupon(""),
            **competitor_comparability({}, product_name),
            **frontend_location_constraint({}),
        }
    findings = "；".join(
        _clean(frontend.get(key))
        for key in ["frontend_findings", "frontend_search_findings", "suspected_issue", "frontend_check_focus"]
        if _clean(frontend.get(key))
    )
    price = _first_non_empty(frontend.get("frontend_price"), frontend.get("price"))
    coupon = parse_coupon(_first_non_empty(frontend.get("frontend_coupon"), frontend.get("coupon")), price)
    buy_box_text = _first_non_empty(frontend.get("frontend_buy_box"), frontend.get("buy_box"))
    auto_code = _clean(frontend.get("frontend_auto_conclusion"))
    auto_label = _clean(frontend.get("frontend_auto_conclusion_label"))
    score = _num(frontend.get("frontend_evidence_quality_score"))
    has_quality_score = _clean(frontend.get("frontend_evidence_quality_score")) != ""
    evidence_tier = _clean(frontend.get("frontend_evidence_tier"))
    check_status = _clean(frontend.get("frontend_check_status"))
    search_status = _clean(frontend.get("frontend_search_status"))
    partial_search = _boolish(frontend.get("frontend_search_partial_evidence")) or search_status == "已读取部分结果"
    search_unreliable = partial_search or search_status != "已自动检查"
    cache_used = _boolish(frontend.get("frontend_cache_used"))
    cache_or_failed = (
        check_status != "已自动检查"
        or check_status.startswith("沿用")
        or cache_used
        or check_status in {"待前台检查", "读取失败"}
        or "失败" in check_status
    )
    audit_summary = _clean(frontend.get("frontend_evidence_audit_summary"))
    audit_detail = _clean(frontend.get("frontend_evidence_audit_detail"))
    audit_reasons_raw = frontend.get("frontend_evidence_audit_reasons")
    if isinstance(audit_reasons_raw, list):
        audit_reasons = [_clean(item) for item in audit_reasons_raw if _clean(item)]
    else:
        audit_reasons = [_clean(item) for item in str(audit_reasons_raw or "").split("；") if _clean(item)]
    comp = competitor_comparability(frontend, product_name)
    competitor_level = comp["competitor_comparability"]
    competitor_strong_comparable = competitor_level == "high"
    competitor_not_comparable = competitor_level in {"low", "unknown"}
    competitor_not_strong = not competitor_strong_comparable
    location = frontend_location_constraint(frontend)
    location_uncertain = bool(location.get("frontend_location_uncertain"))
    frontend_ok_high = (
        evidence_tier == "强诊断可用"
        and auto_code == "FRONTEND_OK"
        and score >= 75
        and competitor_strong_comparable
        and not location_uncertain
        and not search_unreliable
        and not cache_or_failed
    )
    frontend_weak = auto_code == "FRONTEND_WEAK" or auto_label == "明确前台劣势"
    failure_category = _clean(frontend.get("frontend_failure_category"))
    evidence_insufficient = (
        bool(_clean(frontend.get("frontend_price_currency_warning")))
        or bool(failure_category and failure_category != "none")
        or evidence_tier == "不可用"
        or auto_code == "INSUFFICIENT_EVIDENCE"
        or auto_label == "自动证据不足，不能用于强诊断"
        or (has_quality_score and score <= 0)
    )
    background_only = evidence_tier == "仅背景参考" or cache_or_failed
    reasons: list[str] = []
    blocked: set[str] = set()
    allowed: set[str] = {"observe", "bid_down", "negative_exact", "create_exact_low_budget"}
    text = findings.lower()
    if evidence_insufficient:
        reasons.append("前台证据不足，需刷新后再放量")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    elif background_only:
        reasons.append("前台缓存或读取失败待确认，仅背景参考，不能单独支持放量" if cache_or_failed else "前台证据仅背景参考，不能单独支持放量")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    for reason in audit_reasons[:3]:
        if reason and reason not in reasons and not frontend_ok_high:
            reasons.append(reason)
    if frontend_weak:
        reasons.append("自动前台结论明确弱势")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    if (
        not frontend_ok_high
        and not evidence_insufficient
        and evidence_tier == "强诊断可用"
        and auto_code != "FRONTEND_OK"
    ):
        reasons.append("缺少明确 FRONTEND_OK 结论，当前前台证据不能用于放量")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    if coupon["coupon_confidence"] == "low" and coupon["coupon_raw"] and not frontend_ok_high and not evidence_insufficient:
        reasons.append("Coupon 到手价待确认")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    buy_box_uncertain = (
        bool(buy_box_text)
        and "识别到购买按钮" not in buy_box_text
        and any(token in buy_box_text for token in ["未", "待确认", "异常", "不稳定", "丢", "无"])
    )
    if not frontend_ok_high and not evidence_insufficient and (
        buy_box_uncertain or any(token in text for token in ["推荐报价不稳定", "丢购物车", "无 buy box", "无buy box"])
    ):
        reasons.append("Buy Box/购买按钮待确认")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    if not evidence_insufficient and any(token in findings for token in ["价格带弱势", "价格不占", "价格高", "售价高", "价格明显", "价格没有优势"]):
        reasons.append("价格竞争力待确认")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    if not evidence_insufficient and any(token in findings for token in ["评分信任弱", "评论量弱", "评分低", "评分偏弱", "评论明显落后", "评论弱", "评价拖累"]):
        reasons.append("评分/评论弱于竞品")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    if competitor_not_comparable and not evidence_insufficient:
        reasons.append("竞品可比性不足")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    elif competitor_not_strong and not evidence_insufficient:
        reasons.append("竞品可比性未达强诊断，前台证据仅背景参考")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    if search_unreliable and not evidence_insufficient:
        if partial_search:
            reasons.append("搜索页仅部分读取，竞品证据仅背景参考")
        else:
            reasons.append("搜索页未完整检查，竞品证据仅背景参考")
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    if location_uncertain and not evidence_insufficient:
        reason = _clean(location.get("frontend_location_block_reason")) or "地区待确认，当前前台证据不能用于放量"
        if reason not in reasons:
            reasons.append(reason)
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    seller_conclusion = _clean(frontend.get("product_level_conclusion"))
    seller_boundary = _clean(frontend.get("product_ad_boundary"))
    seller_pressure = _clean(frontend.get("competitor_keyword_pressure"))
    seller_frontend_level = _clean(frontend.get("frontend_competitiveness"))
    market_level = _clean(frontend.get("market_survey_completeness_level"))
    market_tier = _clean(frontend.get("market_survey_decision_evidence_tier"))
    market_score = _clean(frontend.get("market_survey_completeness_score"))
    market_missing = _clean(frontend.get("market_survey_missing_parts"))
    if seller_conclusion == "产品问题优先":
        if seller_boundary:
            reasons.append(seller_boundary)
        blocked.update({"bid_up", "budget_up", "broad_scale", "create_exact_low_budget"})
        allowed.discard("create_exact_low_budget")
    elif seller_conclusion == "暂停扩张":
        if seller_boundary:
            reasons.append(seller_boundary)
        blocked.update({"bid_up", "budget_up", "broad_scale", "create_exact_low_budget"})
        allowed.discard("create_exact_low_budget")
    elif seller_conclusion == "只防守":
        if seller_boundary:
            reasons.append(seller_boundary)
        blocked.update({"bid_up", "budget_up", "broad_scale"})
    elif seller_conclusion == "可测试，不放量":
        blocked.update({"budget_up", "broad_scale"})
        allowed.add("create_exact_low_budget")
        if seller_boundary and seller_pressure in {"高", "中"}:
            reasons.append(seller_boundary)
    elif seller_conclusion in {"可谨慎放量", "可放量"}:
        allowed.update({"bid_up", "create_exact_low_budget"})
        blocked.update({"budget_up", "broad_scale"})
    if market_tier and market_tier != "strong":
        market_reason = f"市场调查完整度 {market_score or '未知'}/100，{_market_survey_label(market_level or market_tier)}证据不能支持强操作"
        if market_missing:
            market_reason += f"，缺口：{market_missing}"
        reasons.append(market_reason)
        blocked.update(FRONTEND_GATED_GROWTH_ACTIONS)
        if not (market_tier == "usable" and seller_conclusion in {"可测试，不放量", "可谨慎放量"}):
            blocked.add("create_exact_low_budget")
            allowed.discard("create_exact_low_budget")
    small_budget_evidence_only = (
        seller_conclusion in {"可测试，不放量", "可谨慎放量"}
        and frontend_ok_high
        and market_tier in {"usable", "strong"}
        and not evidence_insufficient
        and not background_only
        and not competitor_not_comparable
        and not competitor_not_strong
        and not search_unreliable
        and not location_uncertain
        and not frontend_weak
    )
    if small_budget_evidence_only:
        blocked.discard("create_exact_low_budget")
        allowed.add("create_exact_low_budget")
    hard_boundary_blocks = {"bid_up", "budget_up", "broad_scale"} if small_budget_evidence_only else {"budget_up", "broad_scale"}
    hard_frontend_blocks = blocked - hard_boundary_blocks
    hard_reasons = [] if small_budget_evidence_only else reasons
    if evidence_insufficient:
        posture = "insufficient_evidence"
    elif hard_frontend_blocks:
        posture = "frontend_blocked"
    else:
        posture = "needs_confirmation" if hard_reasons else "ok"
    if hard_frontend_blocks:
        blocked.update(FRONTEND_GATED_GROWTH_ACTIONS)
    if small_budget_evidence_only:
        blocked.discard("create_exact_low_budget")
        allowed.add("create_exact_low_budget")
    if seller_conclusion in {"可测试，不放量", "可谨慎放量", "可放量"} and frontend_ok_high and market_tier == "strong":
        blocked.discard("create_exact_low_budget")
        allowed.add("create_exact_low_budget")
    if evidence_insufficient:
        display_tier = "不可用"
    elif background_only or competitor_not_strong or search_unreliable or location_uncertain:
        display_tier = "仅背景参考"
    elif evidence_tier == "强诊断可用" and auto_code != "FRONTEND_OK" and not frontend_weak:
        display_tier = "仅背景参考"
    else:
        display_tier = evidence_tier
    return {
        "frontend_posture": posture,
        "frontend_blocking_reasons": reasons,
        "allowed_ad_actions": sorted(allowed),
        "blocked_ad_actions": sorted(blocked),
        "frontend_required": bool(hard_frontend_blocks or hard_reasons),
        "frontend_evidence_state": "insufficient" if evidence_insufficient else "ok_high" if frontend_ok_high else "background" if background_only else "weak" if frontend_weak else "mixed",
        "frontend_evidence_tier": evidence_tier,
        "frontend_evidence_display_tier": display_tier,
        "frontend_decision_evidence_tier": display_tier,
        "frontend_evidence_is_strong": frontend_ok_high,
        "frontend_check_status": check_status,
        "frontend_cache_used": cache_used,
        "frontend_failure_category": failure_category,
        "frontend_price_currency_warning": _clean(frontend.get("frontend_price_currency_warning")),
        "frontend_location_warning": _clean(frontend.get("frontend_location_warning")),
        "frontend_search_status": search_status,
        "frontend_search_partial_evidence": partial_search,
        "frontend_auto_conclusion": auto_code,
        "frontend_auto_conclusion_label": auto_label,
        "frontend_evidence_quality_score": _clean(frontend.get("frontend_evidence_quality_score")),
        "frontend_evidence_audit_summary": audit_summary,
        "frontend_evidence_audit_detail": audit_detail,
        "product_level_conclusion": seller_conclusion,
        "product_ad_boundary": seller_boundary,
        "final_ad_allowed_actions": frontend.get("final_ad_allowed_actions") or [],
        "final_ad_blocked_actions": frontend.get("final_ad_blocked_actions") or [],
        "own_sellersprite_keywords": _clean(frontend.get("own_sellersprite_keywords")),
        "competitor_discovery_status": _clean(frontend.get("competitor_discovery_status")),
        "competitor_discovery_error": _clean(frontend.get("competitor_discovery_error")),
        "competitor_discovery_source_page": _clean(frontend.get("competitor_discovery_source_page")),
        "competitor_discovery_source": _clean(frontend.get("competitor_discovery_source")),
        "competitor_pool_status": _clean(frontend.get("competitor_pool_status")),
        "competitor_pool_asins": _clean(frontend.get("competitor_pool_asins")),
        "competitor_pool_count": _clean(frontend.get("competitor_pool_count")),
        "competitor_pool_confidence": _clean(frontend.get("competitor_pool_confidence")),
        "main_competitor_asins": _clean(frontend.get("main_competitor_asins")),
        "main_competitor_count": _clean(frontend.get("main_competitor_count")),
        "reference_competitor_asins": _clean(frontend.get("reference_competitor_asins")),
        "reference_competitor_count": _clean(frontend.get("reference_competitor_count")),
        "competitor_comparability_score": _clean(frontend.get("competitor_comparability_score")),
        "competitor_spec_match_status": _clean(frontend.get("competitor_spec_match_status")),
        "competitor_price_band_status": _clean(frontend.get("competitor_price_band_status")),
        "competitor_review_tier_status": _clean(frontend.get("competitor_review_tier_status")),
        "competitor_stability_days": _clean(frontend.get("competitor_stability_days")),
        "scalable_evidence_status": _clean(frontend.get("scalable_evidence_status")),
        "scalable_blockers": _clean(frontend.get("scalable_blockers")),
        "scalable_allowed_actions": frontend.get("scalable_allowed_actions") or "",
        "competitor_overlap_keywords": _clean(frontend.get("competitor_overlap_keywords")),
        "competitor_source_keywords": _clean(frontend.get("competitor_source_keywords")),
        "competitor_rejected_count": _clean(frontend.get("competitor_rejected_count")),
        "competitor_rejection_reasons": _clean(frontend.get("competitor_rejection_reasons")),
        "competitor_sellersprite_keywords": _clean(frontend.get("competitor_sellersprite_keywords")),
        "competitor_shared_keywords": _clean(frontend.get("competitor_shared_keywords")),
        "own_missing_competitor_keywords": _clean(frontend.get("own_missing_competitor_keywords")),
        "own_ad_terms_not_in_sellersprite": _clean(frontend.get("own_ad_terms_not_in_sellersprite")),
        "competitor_frontend_status": _clean(frontend.get("competitor_frontend_status")),
        "competitor_frontend_asins": _clean(frontend.get("competitor_frontend_asins")),
        "competitor_frontend_count": _clean(frontend.get("competitor_frontend_count")),
        "amazon_search_validation_status": _clean(frontend.get("amazon_search_validation_status")),
        "amazon_search_visible_competitors": _clean(frontend.get("amazon_search_visible_competitors")),
        "competitor_sellersprite_status": _clean(frontend.get("competitor_sellersprite_status")),
        "competitor_sellersprite_asin_count": _clean(frontend.get("competitor_sellersprite_asin_count")),
        "competitor_sellersprite_keyword_count": _clean(frontend.get("competitor_sellersprite_keyword_count")),
        "competitor_keyword_pressure": seller_pressure,
        "frontend_competitiveness": seller_frontend_level,
        **{field: frontend.get(field) for field in MARKET_SURVEY_COMPLETENESS_FIELDS},
        **{field: frontend.get(field) for field in HISTORY_TREND_FIELDS},
        "coupon": coupon,
        **comp,
        **location,
    }


def _quality_gate(analysis_payload: dict) -> tuple[bool, str]:
    data_quality = analysis_payload.get("data_quality", {}) if isinstance(analysis_payload, dict) else {}
    messages = data_quality.get("validation_messages", []) if isinstance(data_quality, dict) else []
    actionable_messages = [
        _clean(msg)
        for msg in messages
        if _clean(msg) and "已按 0 单补齐" not in _clean(msg) and "已按0单补齐" not in _clean(msg)
    ]
    text = "；".join(actionable_messages)
    severe_tokens = ["ERP", "日期", "缺最近", "缺失", "未覆盖", "行数异常", "关键字段"]
    if text and any(token in text for token in severe_tokens):
        return True, text[:180]
    summary = analysis_payload.get("summary", {}) if isinstance(analysis_payload, dict) else {}
    ads_rows = _num(summary.get("ads_row_count"))
    erp_rows = _num(summary.get("erp_row_count"))
    if ads_rows >= 20 and erp_rows == 0:
        return True, "广告有数据但 ERP 行数为 0，先确认销售数据覆盖。"
    return False, ""


def _collect_products(
    analysis_payload: dict,
    rows: Iterable[dict[str, object]],
    inventory_rows: Iterable[dict[str, object]],
    frontend_rows: Iterable[dict[str, object]],
) -> dict[str, dict[str, object]]:
    products: dict[str, dict[str, object]] = {}
    marketplace = _clean(analysis_payload.get("target_marketplace")).upper()
    metrics = analysis_payload.get("product_window_metrics", {}) if isinstance(analysis_payload, dict) else {}
    if isinstance(metrics, dict):
        for window in ["30d", "14d", "7d"]:
            for row in metrics.get(window, []) or []:
                if isinstance(row, dict):
                    item = dict(row)
                    item.setdefault("marketplace", marketplace)
                    products.setdefault(product_key_text(item), item)
    for source_row in list(rows) + list(inventory_rows) + list(frontend_rows):
        if not isinstance(source_row, dict):
            continue
        item = dict(source_row)
        item.setdefault("marketplace", marketplace)
        key = product_key_text(item)
        if key == "||" or not _product_key(item)[2]:
            continue
        base = products.setdefault(key, {})
        for field in ["marketplace", "sku", "asin", "product_name"]:
            if not base.get(field) and item.get(field):
                base[field] = item.get(field)
    return products


def _lookup_by_product(rows: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if isinstance(row, dict):
            key = product_key_text(row)
            if key != "||":
                result[key] = row
    return result


def _rows_by_product(rows: Iterable[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if isinstance(row, dict):
            key = product_key_text(row)
            if key != "||":
                result[key].append(row)
    return result


def _metric_lookup(analysis_payload: dict, window: str) -> dict[str, dict[str, object]]:
    metrics = analysis_payload.get("product_window_metrics", {}) if isinstance(analysis_payload, dict) else {}
    rows = metrics.get(window, []) if isinstance(metrics, dict) else []
    marketplace = _clean(analysis_payload.get("target_marketplace")).upper()
    lookup: dict[str, dict[str, object]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.setdefault("marketplace", marketplace)
        key = product_key_text(item)
        if key != "||":
            lookup[key] = item
    return lookup


def _frontend_issue_flags(frontend: dict[str, object], frontend_rule: dict[str, object]) -> list[str]:
    flags: list[str] = []
    auto_code = _clean(frontend.get("frontend_auto_conclusion"))
    auto_label = _clean(frontend.get("frontend_auto_conclusion_label"))
    posture = _clean(frontend_rule.get("frontend_posture"))
    evidence_state = _clean(frontend_rule.get("frontend_evidence_state"))
    blocking = "；".join(str(item) for item in frontend_rule.get("frontend_blocking_reasons") or [])
    score = _num(frontend.get("frontend_evidence_quality_score"))
    evidence_insufficient = posture == "insufficient_evidence" or auto_code == "INSUFFICIENT_EVIDENCE" or (
        frontend and _clean(frontend.get("frontend_evidence_quality_score")) != "" and score <= 0
    )
    if evidence_insufficient:
        flags.append("no_fresh_frontend")
        return list(dict.fromkeys(flags))
    if evidence_state == "background":
        flags.append("weak_frontend_evidence")
        return list(dict.fromkeys(flags))
    strong_frontend_tokens = ["自动前台结论明确弱势", "价格竞争力", "评分/评论"]
    if auto_code == "FRONTEND_WEAK" or auto_label == "明确前台劣势" or any(token in blocking for token in strong_frontend_tokens):
        flags.append("frontend_competitiveness")
    if any(token in blocking for token in ["Buy Box", "购买按钮", "推荐报价"]):
        flags.append("buy_box_risk")
        flags.append("frontend_competitiveness")
    if any(token in blocking for token in ["价格竞争力", "评分", "评论"]):
        flags.append("price_or_trust_gap")
    if frontend and score <= 0:
        flags.append("no_fresh_frontend")
    elif frontend and score < 45:
        flags.append("weak_frontend_evidence")
    return flags


def _ad_issue_flags(
    product14: dict[str, object],
    product7: dict[str, object],
    action_rows: list[dict[str, object]],
) -> list[str]:
    flags: list[str] = []
    clicks14 = _num(product14.get("ad_clicks"))
    spend14 = _num(product14.get("ad_spend"))
    orders14 = _num(product14.get("ad_orders"))
    total14 = _num(product14.get("total_orders"))
    profit = _num(product14.get("profit_before_ads_per_unit"))
    clicks7 = _num(product7.get("ad_clicks"))
    orders7 = _num(product7.get("ad_orders"))
    spend7 = _num(product7.get("ad_spend"))
    if orders14 <= 0 and clicks14 >= 20:
        flags.append("ad_no_order_clicks")
    if orders14 <= 0 and spend14 >= max(10, profit):
        flags.append("ad_no_order_spend")
    if total14 > 0 and orders14 <= 0 and spend14 >= 5:
        flags.append("organic_only_ad_waste")
    if orders7 <= 0 and (clicks7 >= 10 or spend7 >= 5) and orders14 > 0:
        flags.append("recent_ad_conversion_drop")
    for row in action_rows:
        action = _clean(row.get("suggested_action") or row.get("copy_action_line"))
        relevance = _clean(row.get("relevance_level") or row.get("keyword_level") or row.get("classification_reason"))
        clicks = _num(row.get("clicks"))
        spend = _num(row.get("spend"))
        if action == "否定精准" and (clicks >= 3 or spend >= 1.5):
            flags.append("irrelevant_traffic")
        if "ASIN" in relevance and (action == "暂停ASIN定向" or clicks >= 6 or spend >= 5):
            flags.append("asin_target_no_order")
        if "降竞价" in action and (clicks >= 5 or spend >= 5):
            flags.append("related_traffic_unverified")
    return list(dict.fromkeys(flags))


def _has_verified_scale_action(
    product14: dict[str, object],
    frontend_rule: dict[str, object],
    action_rows: list[dict[str, object]],
) -> bool:
    if "bid_up" in set(frontend_rule.get("blocked_ad_actions") or []):
        return False
    if _num(product14.get("profit_before_ads_per_unit")) <= 0:
        return False
    if _clean(frontend_rule.get("frontend_evidence_state")) != "ok_high":
        return False
    target_acos = _ratio_num(product14.get("target_acos"))
    for row in action_rows:
        if _ad_action_bucket(row) != "bid_up":
            continue
        orders = _num(_first_non_empty(row.get("ad_orders"), row.get("orders")))
        promoted_orders = _num(
            _first_non_empty(
                row.get("promoted_ad_orders"),
                row.get("promoted_click_orders"),
                row.get("current_7d_promoted_ad_orders"),
            )
        )
        if promoted_orders <= 0 or _boolish(row.get("halo_only_conversion")):
            continue
        sales = _num(_first_non_empty(row.get("ad_sales"), row.get("sales")))
        acos = _ratio_num(_first_non_empty(row.get("ACOS"), row.get("acos")))
        row_target = _ratio_num(row.get("target_acos")) or target_acos
        if orders > 0 and sales > 0 and row_target > 0 and acos > 0 and acos <= row_target:
            return True
    return False


def _fusion_diagnosis(
    analysis_payload: dict,
    *,
    product: dict[str, object],
    product14: dict[str, object],
    product7: dict[str, object],
    frontend: dict[str, object],
    frontend_rule: dict[str, object],
    action_rows: list[dict[str, object]],
    data_bad: bool,
    data_reason: str,
) -> dict[str, object]:
    missing: list[str] = []
    evidence_flags: list[str] = []
    if data_bad:
        missing.append(data_reason or "数据窗口不足")
    history_days = _num(analysis_payload.get("history_days"))
    if history_days < 7:
        missing.append("data_window_lt_7d")
    if not product14:
        missing.append("no_14d_product_window")
    if not frontend:
        missing.append("no_fresh_frontend")

    frontend_flags = _frontend_issue_flags(frontend, frontend_rule)
    ad_flags = _ad_issue_flags(product14, product7, action_rows)
    evidence_flags.extend(frontend_flags)
    evidence_flags.extend(ad_flags)

    frontend_strong = any(flag in frontend_flags for flag in ["frontend_competitiveness", "buy_box_risk", "price_or_trust_gap"])
    ad_strong = any(
        flag in ad_flags
        for flag in [
            "ad_no_order_clicks",
            "ad_no_order_spend",
            "organic_only_ad_waste",
            "recent_ad_conversion_drop",
            "irrelevant_traffic",
            "asin_target_no_order",
        ]
    )
    clicks14 = _num(product14.get("ad_clicks"))
    spend14 = _num(product14.get("ad_spend"))
    profit_raw = _clean(product14.get("profit_before_ads_per_unit"))
    profit = _num(profit_raw)
    if profit_raw and profit <= 0 and product14:
        evidence_flags.append("cost_blocked")
        action_gate = "cost_blocked"
        issue_type = "自动证据不足"
    elif data_bad or (not ad_strong and not frontend_strong and clicks14 < 5 and spend14 < 5):
        action_gate = "collect_evidence_only"
        issue_type = "自动证据不足"
    elif ad_strong and frontend_strong and (clicks14 >= 10 or spend14 >= 5):
        action_gate = "fix_both"
        issue_type = "前台和广告共同问题"
    elif frontend_strong:
        action_gate = "fix_frontend_first"
        issue_type = "前台竞争力问题"
    elif ad_strong:
        action_gate = "tighten_ads_first"
        issue_type = "广告流量问题"
    else:
        action_gate = "collect_evidence_only"
        issue_type = "自动证据不足"

    source_count = 0
    if product14:
        source_count += 1
    if action_rows:
        source_count += 1
    if frontend:
        source_count += 1
    if issue_type != "自动证据不足" and source_count >= 2 and (clicks14 >= 10 or spend14 >= 5):
        confidence = "高"
    elif issue_type != "自动证据不足" and source_count >= 1:
        confidence = "中"
    else:
        confidence = "低"

    reason_parts: list[str] = []
    if ad_flags:
        reason_parts.append("广告证据：" + "、".join(ad_flags[:3]))
    seller_conclusion = _clean(frontend_rule.get("product_level_conclusion"))
    seller_boundary = _clean(frontend_rule.get("product_ad_boundary"))
    seller_pressure = _clean(frontend_rule.get("competitor_keyword_pressure"))
    seller_missing = _clean(frontend_rule.get("own_missing_competitor_keywords"))
    seller_no_match = _clean(frontend_rule.get("own_ad_terms_not_in_sellersprite"))
    seller_today_status = _clean(frontend_rule.get("sellersprite_today_status"))
    seller_cache_date = _clean(frontend_rule.get("sellersprite_cache_date"))
    seller_trend_status = _clean(frontend_rule.get("sellersprite_trend_status"))
    seller_persistent = _clean(frontend_rule.get("sellersprite_persistent_keywords"))
    seller_stable_competitors = _clean(frontend_rule.get("competitor_stable_asins"))
    if seller_conclusion:
        seller_bits = [f"产品结论 {seller_conclusion}"]
        if seller_today_status:
            cache_part = f" {seller_cache_date}" if seller_today_status == "沿用缓存" and seller_cache_date else ""
            seller_bits.append(f"{seller_today_status}{cache_part}")
        if seller_trend_status:
            seller_bits.append(f"趋势 {seller_trend_status}")
        if seller_persistent:
            seller_bits.append(f"连续词 {seller_persistent}")
        if seller_stable_competitors:
            seller_bits.append(f"稳定竞品 {seller_stable_competitors}")
        if seller_pressure:
            seller_bits.append(f"竞品词压力 {seller_pressure}")
        if seller_missing:
            seller_bits.append(f"缺口词 {seller_missing}")
        if seller_no_match:
            seller_bits.append(f"广告无反查证据 {seller_no_match}")
        if seller_boundary:
            seller_bits.append(seller_boundary)
        reason_parts.append("卖家精灵：" + "，".join(seller_bits[:6]))
    market_score = _clean(frontend_rule.get("market_survey_completeness_score"))
    market_level = _clean(frontend_rule.get("market_survey_completeness_level"))
    market_tier = _clean(frontend_rule.get("market_survey_decision_evidence_tier"))
    market_missing = _clean(frontend_rule.get("market_survey_missing_parts"))
    if market_score or market_level or market_tier:
        market_reason = f"市场调查：完整度 {market_score or '未知'}/100"
        if market_level:
            market_reason += f"，等级 {_market_survey_label(market_level)}"
        if market_tier:
            market_reason += f"，证据层级 {_market_survey_label(market_tier)}"
        if market_missing:
            market_reason += f"，缺口 {market_missing}"
        reason_parts.append(market_reason)
    if frontend:
        frontend_label = _clean(frontend.get("frontend_auto_conclusion_label"))
        frontend_score = _clean(frontend.get("frontend_evidence_quality_score"))
        frontend_tier = _clean(frontend_rule.get("frontend_evidence_display_tier") or frontend_rule.get("frontend_evidence_tier"))
        frontend_audit = _clean(frontend_rule.get("frontend_evidence_audit_detail"))
        frontend_reason = f"前台证据：{frontend_label or '未形成强结论'}"
        if frontend_tier:
            frontend_reason += f"，{frontend_tier}"
        if frontend_score:
            frontend_reason += f"，质量 {frontend_score}"
        if frontend_audit:
            frontend_reason += f"，{frontend_audit}"
        reason_parts.append(frontend_reason)
    if product14:
        reason_parts.append(
            f"产品窗口：14天点击 {int(clicks14)}，花费 {_num(product14.get('ad_spend')):.2f}，广告单 {int(_num(product14.get('ad_orders')))}，总单 {int(_num(product14.get('total_orders')))}"
        )
    if not reason_parts:
        reason_parts.append("自动证据不足，不能用于强诊断")

    if action_gate == "fix_frontend_first":
        today_action = "先处理价格、Coupon、Buy Box、评分评论等前台弱项；广告只允许降竞价、否明显无关词，不加预算。"
        do_not_do = "不加预算；不提高泛词竞价；不因广告无单直接大改页面。"
        review_window = "前台修正后 3-7 天复查广告点击、CVR、订单。"
    elif action_gate == "tighten_ads_first":
        today_action = "优先处理广告搜索词/ASIN：否明显不相关词，相关高花费 0 单词降竞价，暂停无效 ASIN 定向。"
        do_not_do = "不要先降价；不要先改主图；不要加预算掩盖流量不准。"
        review_window = "广告动作执行后 3 天看点击和花费，7 天看订单和 ACOS。"
    elif action_gate == "fix_both":
        today_action = "同时收紧广告流量并修正前台弱项；先止损，再等新数据验证转化。"
        do_not_do = "不扩预算；不推大词；不把单一截图当成唯一结论。"
        review_window = "3 天复查广告浪费是否下降，7 天复查转化和订单。"
    elif action_gate == "cost_blocked":
        today_action = "成本或利润口径阻断强动作，先核对成本和售价。"
        do_not_do = "成本未确认前不加广告预算。"
        review_window = "成本确认当天重新跑报告。"
    else:
        today_action = "只观察或补足自动证据，不输出强运营动作。"
        do_not_do = "不要基于低样本、旧缓存或缺失前台字段做加预算、降价、否核心词。"
        review_window = "补齐 7 天窗口或刷新前台后再判断。"

    return {
        "fusion_issue_type": issue_type,
        "fusion_confidence": confidence,
        "fusion_evidence_flags": list(dict.fromkeys(str(flag) for flag in evidence_flags if flag))[:10],
        "fusion_missing_evidence": list(dict.fromkeys(str(item) for item in missing if item))[:8],
        "fusion_action_gate": action_gate,
        "fusion_reason": "；".join(reason_parts[:4]),
        "fusion_today_action": today_action,
        "fusion_do_not_do": do_not_do,
        "fusion_review_window": review_window,
    }


def _sellersprite_decision_context(frontend_rule: dict[str, object]) -> str:
    conclusion = _clean(frontend_rule.get("product_level_conclusion"))
    today_status = _clean(frontend_rule.get("sellersprite_today_status"))
    cache_date = _clean(frontend_rule.get("sellersprite_cache_date"))
    trend_status = _clean(frontend_rule.get("sellersprite_trend_status"))
    evidence_tier = _clean(frontend_rule.get("sellersprite_evidence_tier"))
    persistent = _clean(frontend_rule.get("sellersprite_persistent_keywords"))
    stable_asins = _clean(frontend_rule.get("competitor_stable_asins"))
    main_count = _clean(frontend_rule.get("main_competitor_count"))
    comparability = _clean(frontend_rule.get("competitor_comparability_score"))
    scalable_status = _clean(frontend_rule.get("scalable_evidence_status"))
    scalable_blockers = _clean(frontend_rule.get("scalable_blockers"))
    market_score = _clean(frontend_rule.get("market_survey_completeness_score"))
    market_level = _clean(frontend_rule.get("market_survey_completeness_level"))
    market_tier = _clean(frontend_rule.get("market_survey_decision_evidence_tier"))
    if not any([conclusion, today_status, trend_status, evidence_tier, persistent, stable_asins, main_count, comparability, scalable_status, scalable_blockers, market_score, market_level, market_tier]):
        return ""
    bits: list[str] = []
    if conclusion:
        bits.append(f"产品结论 {conclusion}")
    if today_status == "沿用缓存":
        bits.append(f"沿用缓存日期 {cache_date or '未知'}")
    elif today_status:
        bits.append(f"今日卖家精灵 {today_status}")
    if trend_status:
        bits.append(f"趋势 {trend_status}")
    if evidence_tier:
        bits.append(f"证据层级 {evidence_tier}")
    if persistent:
        bits.append(f"连续词 {persistent}")
    if stable_asins:
        bits.append(f"稳定竞品 {stable_asins}")
    if main_count:
        bits.append(f"主竞品 {main_count} 个")
    if comparability:
        bits.append(f"可比性 {comparability}/100")
    if scalable_status:
        bits.append(f"放量证据 {scalable_status}")
    if scalable_blockers:
        bits.append(f"拦截 {scalable_blockers}")
    if market_score or market_level:
        bits.append(f"市场调查完整度 {market_score or '未知'}/100 {_market_survey_label(market_level or market_tier)}")
    return "卖家精灵：" + "，".join(bits[:5])


def _cooldown_for_product(runtime_policy: dict[str, object] | None, product: dict[str, object]) -> dict[str, object] | None:
    if not runtime_policy:
        return None
    cooldowns = runtime_policy.get("product_cooldowns", {})
    if isinstance(cooldowns, dict):
        tuple_key = _product_key(product)
        cooldown = cooldowns.get(tuple_key)
        if isinstance(cooldown, dict):
            return cooldown
    action_cooldowns = runtime_policy.get("action_cooldowns", {})
    if isinstance(action_cooldowns, dict):
        key = product_key_text(product)
        for cooldown in action_cooldowns.values():
            if isinstance(cooldown, dict) and product_key_text(cooldown) == key:
                return cooldown
    return None


def _keyword_memory_summary(runtime_policy: dict[str, object] | None, product: dict[str, object]) -> tuple[str, list[str], list[str]]:
    if not runtime_policy:
        return "", [], []
    memory = runtime_policy.get("keyword_strategy_memory", [])
    if not isinstance(memory, list):
        return "", [], []
    key = product_key_text(product)
    positive: list[str] = []
    negative: list[str] = []
    for row in memory:
        if not isinstance(row, dict) or product_key_text(row) != key:
            continue
        score = int(_num(row.get("effectiveness_score")))
        label = f"{row.get('search_term_or_target') or ''} {row.get('recommended_future_policy') or ''}".strip()
        if score > 0 and label:
            positive.append(label)
        elif score < 0 and label:
            negative.append(label)
    parts = []
    if positive:
        parts.append(f"有效记忆 {len(positive)} 条")
    if negative:
        parts.append(f"无效/降级记忆 {len(negative)} 条")
    return "；".join(parts), positive[:5], negative[:5]


def build_product_final_decisions(
    analysis_payload: dict,
    *,
    today_rows: Iterable[dict[str, object]] | None = None,
    search_rows: Iterable[dict[str, object]] | None = None,
    scale_rows: Iterable[dict[str, object]] | None = None,
    inventory_rows: Iterable[dict[str, object]] | None = None,
    frontend_rows: Iterable[dict[str, object]] | None = None,
    runtime_policy: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    today_rows = list(today_rows or [])
    search_rows = list(search_rows or [])
    scale_rows = list(scale_rows or [])
    inventory_rows = list(inventory_rows or [])
    frontend_rows = list(frontend_rows or [])
    all_action_rows = [*today_rows, *search_rows, *scale_rows]
    products = _collect_products(analysis_payload, all_action_rows, inventory_rows, frontend_rows)
    inventory_lookup = _lookup_by_product(inventory_rows)
    frontend_lookup = _lookup_by_product(frontend_rows)
    action_rows_by_product = _rows_by_product(all_action_rows)
    metrics14_lookup = _metric_lookup(analysis_payload, "14d")
    metrics7_lookup = _metric_lookup(analysis_payload, "7d")
    data_bad, data_reason = _quality_gate(analysis_payload)

    decisions: list[dict[str, object]] = []
    today = datetime.now().date().isoformat()
    for key, product in products.items():
        product_name = _first_non_empty(product.get("product_name"), product.get("product"), product.get("asin"))
        inventory = inventory_lookup.get(key, {})
        frontend = frontend_lookup.get(key, {})
        frontend_rule = frontend_constraints(frontend, product_name)
        product14 = metrics14_lookup.get(key, product)
        product7 = metrics7_lookup.get(key, {})
        action_rows = action_rows_by_product.get(key, [])
        fusion = _fusion_diagnosis(
            analysis_payload,
            product=product,
            product14=product14,
            product7=product7,
            frontend=frontend,
            frontend_rule=frontend_rule,
            action_rows=action_rows,
            data_bad=data_bad,
            data_reason=data_reason,
        )
        cooldown = _cooldown_for_product(runtime_policy, product)
        keyword_summary, positive_memory, negative_memory = _keyword_memory_summary(runtime_policy, product)
        stock_level = _clean(inventory.get("stock_risk_level") or product.get("inventory_stock_risk_level"))
        blocked_actions: set[str] = set(frontend_rule.get("blocked_ad_actions") or [])
        allowed_actions: set[str] = set(frontend_rule.get("allowed_ad_actions") or ["observe"])
        evidence: list[str] = []
        reason = ""
        final = "EXECUTE_TODAY"
        priority = 90
        confidence = "medium"
        next_review = ""

        if data_bad:
            final = "DATA_INSUFFICIENT"
            priority = 1
            reason = "数据不完整，先确认数据，不判断广告效果。"
            blocked_actions.update({"bid_up", "bid_down", "negative_exact", "pause", "budget_up", "broad_scale"})
            allowed_actions = {"observe"}
            evidence.append(data_reason)
            confidence = "high"
        elif cooldown:
            final = "WAIT_REVIEW"
            priority = 2
            reason = _clean(cooldown.get("status") or "已执行动作冷却中，不重复操作。")
            blocked_actions.update({"bid_up", "bid_down", "negative_exact", "pause", "budget_up", "broad_scale"})
            allowed_actions = {"observe"}
            days_since = _num(cooldown.get("days_since"))
            if days_since < 3:
                next_review = (datetime.now().date() + timedelta(days=max(1, int(3 - days_since)))).isoformat()
            elif days_since < 7:
                next_review = (datetime.now().date() + timedelta(days=max(1, int(7 - days_since)))).isoformat()
            evidence.append(_clean(cooldown.get("reason")))
            confidence = "high"
        elif stock_level == "OUT_OF_STOCK":
            final = "DO_NOT_TOUCH"
            priority = 3
            reason = "库存断货，广告先停扩量/控预算，不把无单归因为 Listing。"
            blocked_actions.update({"bid_up", "budget_up", "broad_scale", "create_exact"})
            allowed_actions = {"observe", "pause", "bid_down"}
            evidence.append(_clean(inventory.get("stock_risk_reason") or "FBA库存为0"))
            confidence = "high"
        elif stock_level in {"LOW_STOCK", "RESTOCK_RECOVERY"}:
            final = "CONSERVATIVE_RUN"
            priority = 4
            reason = "刚到货恢复期，小预算恢复核心精准词。" if stock_level == "RESTOCK_RECOVERY" else "低库存，提醒补货，广告不要大幅放量。"
            blocked_actions.update({"bid_up", "budget_up", "broad_scale"})
            allowed_actions.update({"observe", "bid_down", "negative_exact", "create_exact_low_budget"})
            evidence.append(_clean(inventory.get("stock_risk_reason") or stock_level))
            confidence = "high"
        elif (
            frontend_rule.get("frontend_required")
            and frontend_rule.get("blocked_ad_actions")
            and fusion.get("fusion_action_gate") != "tighten_ads_first"
        ):
            reasons = frontend_rule.get("frontend_blocking_reasons") or ["前台证据待确认"]
            frontend_state = _clean(frontend_rule.get("frontend_evidence_state"))
            uncertainty_reasons = [
                str(item)
                for item in reasons
                if any(token in str(item) for token in ["待确认", "Buy Box", "购买按钮", "Coupon", "可比性不足"])
            ]
            final = "FRONTEND_FIRST" if uncertainty_reasons and frontend_state != "insufficient" else "CONSERVATIVE_RUN"
            priority = 5
            if frontend_state == "insufficient":
                reason = "前台自动证据不足，今天只允许广告止损动作，不加预算。"
            elif uncertainty_reasons:
                reason = "先确认" + "、".join(uncertainty_reasons[:3]) + "，不直接加预算。"
            else:
                reason = "前台已查，" + "、".join(str(item) for item in reasons[:3]) + "；今天保守跑，不加预算。"
            blocked_actions.update({"bid_up", "budget_up", "broad_scale"})
            allowed_actions.update({"observe", "bid_down", "negative_exact"})
            evidence.extend(str(item) for item in reasons[:4])
            confidence = "medium"
        elif fusion.get("fusion_action_gate") == "tighten_ads_first":
            final = "EXECUTE_TODAY"
            priority = 6
            reason = str(fusion.get("fusion_reason") or "广告流量问题，先处理广告端。")
            allowed_actions.update({"bid_down", "negative_exact", "pause", "create_exact_low_budget"})
            blocked_actions.update({"budget_up", "broad_scale"})
            evidence.extend(str(item) for item in fusion.get("fusion_evidence_flags") or [])
            confidence = "high" if fusion.get("fusion_confidence") == "高" else "medium"
        elif fusion.get("fusion_action_gate") == "fix_both":
            final = "CONSERVATIVE_RUN"
            priority = 6
            reason = str(fusion.get("fusion_reason") or "前台和广告共同问题，先止损。")
            allowed_actions.update({"observe", "bid_down", "negative_exact", "pause"})
            blocked_actions.update({"bid_up", "budget_up", "broad_scale"})
            evidence.extend(str(item) for item in fusion.get("fusion_evidence_flags") or [])
            confidence = "high" if fusion.get("fusion_confidence") == "高" else "medium"
        elif negative_memory:
            final = "CONSERVATIVE_RUN"
            priority = 6
            reason = "历史同类动作暂未改善，不继续加价/扩量。"
            blocked_actions.update({"bid_up", "budget_up", "broad_scale"})
            allowed_actions.update({"observe", "bid_down", "negative_exact"})
            evidence.extend(negative_memory[:3])
            confidence = "medium"
        elif positive_memory:
            final = "SMALL_SCALE_ALLOWED"
            priority = 7
            reason = "历史有效动作可保留，但不重复加价；只允许小预算精准测试。"
            blocked_actions.update({"budget_up", "broad_scale"})
            allowed_actions.update({"observe", "create_exact_low_budget"})
            evidence.extend(positive_memory[:3])
            confidence = "medium"
        elif frontend_rule.get("product_level_conclusion") == "可测试，不放量":
            final = "SMALL_SCALE_ALLOWED"
            priority = 8
            reason = str(frontend_rule.get("product_ad_boundary") or "前台可承接且竞品共同词存在，只允许精准小预算测试。")
            blocked_actions.update({"budget_up", "broad_scale"})
            allowed_actions.update({"observe", "create_exact_low_budget", "bid_down", "negative_exact"})
            evidence.append(str(frontend_rule.get("own_missing_competitor_keywords") or "竞品共同词仅可小预算验证"))
            confidence = "medium"
        elif frontend_rule.get("product_level_conclusion") in {"可谨慎放量", "可放量"}:
            final = "SMALL_SCALE_ALLOWED"
            priority = 8
            reason = str(frontend_rule.get("product_ad_boundary") or "主竞品、前台和广告证据达标，只允许小幅核心词动作。")
            blocked_actions.update({"budget_up", "broad_scale"})
            allowed_actions.update({"observe", "bid_up", "create_exact_low_budget", "bid_down", "negative_exact"})
            evidence.append("主竞品、卖家精灵和前台证据支持谨慎动作，预算仍需复核账号成交。")
            confidence = "medium"
        else:
            actionable = [row for row in all_action_rows if product_key_text(row) == key]
            if actionable:
                final = "EXECUTE_TODAY"
                priority = 8
                reason = "数据完整且未命中库存/前台/历史拦截，可执行今日动作。"
                allowed_actions.update({"bid_down", "negative_exact", "pause", "create_exact_low_budget"})
                if _has_verified_scale_action(product14, frontend_rule, action_rows):
                    allowed_actions.add("bid_up")
                    blocked_actions.discard("bid_up")
                elif any(_ad_action_bucket(row) == "bid_up" for row in action_rows):
                    blocked_actions.add("bid_up")
            else:
                final = "DO_NOT_TOUCH"
                priority = 9
                reason = "今天没有明确强动作，保持观察。"
                allowed_actions = {"observe"}
            evidence.append(f"待处理动作 {len(actionable)} 条")

        seller_context_reason = _sellersprite_decision_context(frontend_rule)
        if seller_context_reason and seller_context_reason not in reason:
            reason = f"{reason}；{seller_context_reason}" if reason else seller_context_reason

        frontend_supports_growth = (
            frontend_rule.get("frontend_evidence_state") == "ok_high"
            and frontend_rule.get("frontend_evidence_display_tier") == "强诊断可用"
            and frontend_rule.get("frontend_auto_conclusion") == "FRONTEND_OK"
            and not frontend_rule.get("frontend_cache_used")
            and frontend_rule.get("market_survey_decision_evidence_tier") == "strong"
        )
        if not frontend_supports_growth:
            blocked_actions.update(FRONTEND_GATED_GROWTH_ACTIONS)
        small_budget_evidence_only = (
            frontend_rule.get("product_level_conclusion") in {"可测试，不放量", "可谨慎放量"}
            and frontend_rule.get("frontend_evidence_state") == "ok_high"
            and frontend_rule.get("market_survey_decision_evidence_tier") in {"usable", "strong"}
            and not frontend_rule.get("frontend_required")
        )
        if small_budget_evidence_only:
            blocked_actions.discard("create_exact_low_budget")
            allowed_actions.add("create_exact_low_budget")

        scalable_status = _clean(frontend_rule.get("scalable_evidence_status"))
        scalable_blockers = [
            item.strip()
            for item in re.split(r"[；;、,]+", _clean(frontend_rule.get("scalable_blockers")))
            if item.strip()
        ]
        product14_orders = _num(product14.get("ad_orders"))
        product14_acos = _ratio_num(product14.get("acos") or product14.get("ACOS"))
        product14_target_acos = _ratio_num(product14.get("target_acos"))
        ad_window_valid = product14_orders > 0 or (
            product14_acos > 0 and product14_target_acos > 0 and product14_acos <= product14_target_acos
        )
        if ad_window_valid:
            scalable_blockers = [item for item in scalable_blockers if item != "广告未验证成交"]
        if stock_level in INVENTORY_BLOCKING:
            scalable_blockers.append("库存不支持放量")
        if data_bad:
            scalable_blockers.append("基础数据不完整")
        if cooldown:
            scalable_blockers.append("动作冷却中")
        scalable_blockers = list(dict.fromkeys(scalable_blockers))
        decision_scalable_status = scalable_status
        if stock_level in INVENTORY_BLOCKING or data_bad:
            decision_scalable_status = "只能控费止损"
        elif scalable_status == "可谨慎放量" and not frontend_supports_growth:
            decision_scalable_status = "可小预算测试"
        elif scalable_status in {"可谨慎放量", "可小预算测试"} and not scalable_blockers and frontend_supports_growth:
            decision_scalable_status = "可谨慎放量"
        elif scalable_status == "可谨慎放量" and scalable_blockers:
            decision_scalable_status = "可小预算测试"

        decision = {
            "marketplace": _product_key(product)[0],
            "sku": _product_key(product)[1],
            "asin": _product_key(product)[2],
            "product_name": product_name,
            "final_decision": final if final in FINAL_DECISIONS else "DATA_INSUFFICIENT",
            "final_decision_label": DECISION_LABELS.get(final, final),
            "decision_priority": priority,
            "decision_reason": reason,
            "today_allowed_actions": sorted(allowed_actions - blocked_actions) or ["observe"],
            "today_blocked_actions": sorted(blocked_actions),
            "frontend_required": bool(frontend_rule.get("frontend_required")),
            "frontend_posture": frontend_rule.get("frontend_posture"),
            "frontend_evidence_state": frontend_rule.get("frontend_evidence_state"),
            "frontend_blocking_reasons": frontend_rule.get("frontend_blocking_reasons"),
            "frontend_evidence_tier": frontend_rule.get("frontend_evidence_tier"),
            "frontend_evidence_display_tier": frontend_rule.get("frontend_evidence_display_tier"),
            "frontend_decision_evidence_tier": frontend_rule.get("frontend_decision_evidence_tier"),
            "frontend_evidence_is_strong": frontend_rule.get("frontend_evidence_is_strong"),
            "frontend_check_status": frontend_rule.get("frontend_check_status"),
            "frontend_cache_used": frontend_rule.get("frontend_cache_used"),
            "frontend_failure_category": frontend_rule.get("frontend_failure_category"),
            "frontend_price_currency_warning": frontend_rule.get("frontend_price_currency_warning"),
            "frontend_location_warning": frontend_rule.get("frontend_location_warning"),
            "frontend_search_status": frontend_rule.get("frontend_search_status"),
            "frontend_search_partial_evidence": frontend_rule.get("frontend_search_partial_evidence"),
            "frontend_auto_conclusion": frontend_rule.get("frontend_auto_conclusion"),
            "frontend_auto_conclusion_label": frontend_rule.get("frontend_auto_conclusion_label"),
            "frontend_evidence_quality_score": frontend_rule.get("frontend_evidence_quality_score"),
            "frontend_evidence_audit_summary": frontend_rule.get("frontend_evidence_audit_summary"),
            "frontend_evidence_audit_detail": frontend_rule.get("frontend_evidence_audit_detail"),
            "product_level_conclusion": frontend_rule.get("product_level_conclusion"),
            "product_ad_boundary": frontend_rule.get("product_ad_boundary"),
            "final_ad_allowed_actions": frontend_rule.get("final_ad_allowed_actions"),
            "final_ad_blocked_actions": frontend_rule.get("final_ad_blocked_actions"),
            "own_sellersprite_keywords": frontend_rule.get("own_sellersprite_keywords"),
            "competitor_discovery_status": frontend_rule.get("competitor_discovery_status"),
            "competitor_discovery_error": frontend_rule.get("competitor_discovery_error"),
            "competitor_discovery_source_page": frontend_rule.get("competitor_discovery_source_page"),
            "competitor_discovery_source": frontend_rule.get("competitor_discovery_source"),
            "competitor_pool_status": frontend_rule.get("competitor_pool_status"),
            "competitor_pool_asins": frontend_rule.get("competitor_pool_asins"),
            "competitor_pool_count": frontend_rule.get("competitor_pool_count"),
            "competitor_pool_confidence": frontend_rule.get("competitor_pool_confidence"),
            "main_competitor_asins": frontend_rule.get("main_competitor_asins"),
            "main_competitor_count": frontend_rule.get("main_competitor_count"),
            "reference_competitor_asins": frontend_rule.get("reference_competitor_asins"),
            "reference_competitor_count": frontend_rule.get("reference_competitor_count"),
            "competitor_comparability_score": frontend_rule.get("competitor_comparability_score"),
            "competitor_spec_match_status": frontend_rule.get("competitor_spec_match_status"),
            "competitor_price_band_status": frontend_rule.get("competitor_price_band_status"),
            "competitor_review_tier_status": frontend_rule.get("competitor_review_tier_status"),
            "competitor_stability_days": frontend_rule.get("competitor_stability_days"),
            "scalable_evidence_status": decision_scalable_status,
            "scalable_blockers": "；".join(scalable_blockers[:6]),
            "scalable_allowed_actions": frontend_rule.get("scalable_allowed_actions"),
            "competitor_overlap_keywords": frontend_rule.get("competitor_overlap_keywords"),
            "competitor_source_keywords": frontend_rule.get("competitor_source_keywords"),
            "competitor_rejected_count": frontend_rule.get("competitor_rejected_count"),
            "competitor_rejection_reasons": frontend_rule.get("competitor_rejection_reasons"),
            "competitor_sellersprite_keywords": frontend_rule.get("competitor_sellersprite_keywords"),
            "competitor_shared_keywords": frontend_rule.get("competitor_shared_keywords"),
            "own_missing_competitor_keywords": frontend_rule.get("own_missing_competitor_keywords"),
            "own_ad_terms_not_in_sellersprite": frontend_rule.get("own_ad_terms_not_in_sellersprite"),
            "competitor_frontend_status": frontend_rule.get("competitor_frontend_status"),
            "competitor_frontend_asins": frontend_rule.get("competitor_frontend_asins"),
            "competitor_frontend_count": frontend_rule.get("competitor_frontend_count"),
            "amazon_search_validation_status": frontend_rule.get("amazon_search_validation_status"),
            "amazon_search_visible_competitors": frontend_rule.get("amazon_search_visible_competitors"),
            "competitor_sellersprite_status": frontend_rule.get("competitor_sellersprite_status"),
            "competitor_sellersprite_asin_count": frontend_rule.get("competitor_sellersprite_asin_count"),
            "competitor_sellersprite_keyword_count": frontend_rule.get("competitor_sellersprite_keyword_count"),
            "competitor_keyword_pressure": frontend_rule.get("competitor_keyword_pressure"),
            "frontend_competitiveness": frontend_rule.get("frontend_competitiveness"),
            **{field: frontend_rule.get(field) for field in MARKET_SURVEY_COMPLETENESS_FIELDS},
            **{field: frontend_rule.get(field) for field in HISTORY_TREND_FIELDS},
            "inventory_constraint": stock_level or "NONE",
            "feedback_cooldown_status": _clean(cooldown.get("status")) if cooldown else "",
            "keyword_memory_summary": keyword_summary,
            "ad_action_summary": reason,
            "next_review_date": next_review,
            "evidence_used": [item for item in evidence if item][:6],
            "confidence": confidence,
            "coupon": frontend_rule.get("coupon"),
            "competitor_comparability": frontend_rule.get("competitor_comparability"),
            "comparable_competitor_count": frontend_rule.get("comparable_competitor_count"),
            "competitor_mismatch_reason": frontend_rule.get("competitor_mismatch_reason"),
            "frontend_location_scope": frontend_rule.get("frontend_location_scope"),
            "frontend_location_verified": frontend_rule.get("frontend_location_verified"),
            "frontend_location_exact": frontend_rule.get("frontend_location_exact"),
            "frontend_location_uncertain": frontend_rule.get("frontend_location_uncertain"),
            "frontend_location_block_reason": frontend_rule.get("frontend_location_block_reason"),
            "last_updated": today,
            **fusion,
        }
        decisions.append(decision)
    return sorted(decisions, key=lambda row: (int(row.get("decision_priority") or 99), str(row.get("marketplace") or ""), str(row.get("product_name") or "")))


def decision_lookup(decisions: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {product_key_text(row): row for row in decisions if isinstance(row, dict)}


def apply_decisions_to_rows(rows: Iterable[dict[str, object]], decisions: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    lookup = decision_lookup(decisions)
    updated_rows: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        decision = lookup.get(product_key_text(item))
        if not decision:
            updated_rows.append(item)
            continue
        final = _clean(decision.get("final_decision"))
        item["final_decision"] = final
        item["final_decision_label"] = decision.get("final_decision_label") or DECISION_LABELS.get(final, final)
        item["final_decision_reason"] = decision.get("decision_reason") or ""
        item["final_decision_next_review"] = decision.get("next_review_date") or ""
        item["today_blocked_actions"] = " / ".join(str(action) for action in decision.get("today_blocked_actions") or [])
        item["today_allowed_actions"] = " / ".join(str(action) for action in decision.get("today_allowed_actions") or [])
        for field in [
            "fusion_issue_type",
            "fusion_confidence",
            "fusion_action_gate",
            "fusion_reason",
            "fusion_today_action",
            "fusion_do_not_do",
            "fusion_review_window",
        ]:
            item[field] = decision.get(field) or ""
        for field in [
            "product_level_conclusion",
            "product_ad_boundary",
            "own_sellersprite_keywords",
            "competitor_discovery_status",
            "competitor_discovery_error",
            "competitor_discovery_source_page",
            "competitor_discovery_source",
            "competitor_pool_status",
            "competitor_pool_asins",
            "competitor_pool_count",
            "competitor_pool_confidence",
            "competitor_overlap_keywords",
            "competitor_source_keywords",
            "competitor_rejected_count",
            "competitor_rejection_reasons",
            "competitor_sellersprite_keywords",
            "competitor_shared_keywords",
            "own_missing_competitor_keywords",
            "own_ad_terms_not_in_sellersprite",
            "competitor_frontend_status",
            "competitor_frontend_asins",
            "competitor_frontend_count",
            "amazon_search_validation_status",
            "amazon_search_visible_competitors",
            "competitor_sellersprite_status",
            "competitor_sellersprite_asin_count",
            "competitor_sellersprite_keyword_count",
            "competitor_keyword_pressure",
            "frontend_competitiveness",
            *MARKET_SURVEY_COMPLETENESS_FIELDS,
            *HISTORY_TREND_FIELDS,
        ]:
            item[field] = decision.get(field) or ""
        item["final_ad_allowed_actions"] = " / ".join(str(action) for action in decision.get("final_ad_allowed_actions") or [])
        item["final_ad_blocked_actions"] = " / ".join(str(action) for action in decision.get("final_ad_blocked_actions") or [])
        item["fusion_evidence_flags"] = " / ".join(str(flag) for flag in decision.get("fusion_evidence_flags") or [])
        item["fusion_missing_evidence"] = " / ".join(str(flag) for flag in decision.get("fusion_missing_evidence") or [])
        if final in {"WAIT_REVIEW", "DATA_INSUFFICIENT", "DO_NOT_TOUCH"}:
            item["priority"] = "P2"
            if final == "WAIT_REVIEW":
                item["confirmed_status"] = "待复查"
        elif final == "FRONTEND_FIRST":
            item["today_action"] = "前台优先：若已查到弱项，广告先保守跑，不加预算、不放大泛词。"
        elif final == "CONSERVATIVE_RUN":
            item["today_action"] = "保守跑：不加预算，不推大词放量，只保留高相关精准词和必要降竞价/否词。"
        bucket = _ad_action_bucket(item)
        if bucket not in {"unknown", "observe", "keep"} and not _action_allowed_by_decision(bucket, final, decision):
            _mark_ad_action_as_observation(item, row)
        updated_rows.append(item)
    return updated_rows


def _ad_action_bucket(row: dict[str, object]) -> str:
    text = " ".join(
        _clean(row.get(field))
        for field in ["suggested_action", "scale_action", "copy_action_line", "copy_block", "today_action", "normalized_action"]
    ).lower()
    if not text:
        return "unknown"
    if "否定精准" in text or "建议否词" in text or "negative exact" in text:
        return "negative_exact"
    if "降竞价" in text or "降低竞价" in text or "bid down" in text:
        return "bid_down"
    if "暂停" in text or "关闭" in text or "pause" in text:
        return "pause"
    if "加价" in text or "提高竞价" in text or "bid up" in text:
        return "bid_up"
    if "加预算" in text or "提高预算" in text or "budget" in text:
        return "budget_up"
    if "小预算" in text or "创建精准" in text or "精准测试" in text:
        return "create_exact_low_budget"
    if "观察" in text:
        return "observe"
    if "保留" in text or "无需操作" in text:
        return "keep"
    return "unknown"


def _action_allowed_by_decision(bucket: str, final: str, decision: dict[str, object]) -> bool:
    allowed = {str(action) for action in decision.get("today_allowed_actions") or []}
    blocked = {str(action) for action in decision.get("today_blocked_actions") or []}
    if bucket in {"observe", "keep"}:
        return True
    if bucket in blocked:
        return False
    if bucket in allowed:
        return True
    if bucket in FRONTEND_GATED_GROWTH_ACTIONS:
        return False
    return final in EXECUTABLE_DECISIONS and bucket in {"bid_down", "negative_exact", "pause"}


def _mark_ad_action_as_observation(item: dict[str, object], original: dict[str, object]) -> None:
    original_action = _first_non_empty(
        original.get("suggested_action"),
        original.get("scale_action"),
        original.get("copy_action_line"),
        original.get("manual_action_taken"),
        original.get("action_detail"),
        original.get("today_action"),
    )
    target = _action_identity_target(original)
    scope = str(original.get("action_scope") or "").strip()
    if not scope:
        scope = "asin_target" if str(target or "").upper().startswith("B0") else ("search_term" if target else "product")
    if original_action:
        item["blocked_original_action"] = original_action
    if original.get("manual_action_taken"):
        item["blocked_original_manual_action_taken"] = original.get("manual_action_taken")
    if original.get("action_detail"):
        item["blocked_original_action_detail"] = original.get("action_detail")
    if original.get("action_id"):
        item["blocked_original_action_id"] = original.get("action_id")
    item["action_id"] = _observation_action_id(original)
    item["action_scope"] = scope
    if target and not item.get("search_term_or_target"):
        item["search_term_or_target"] = target
    item["suggested_action"] = "观察"
    item["manual_action_taken"] = "观察"
    item["action_detail"] = "观察"
    item["copy_action_line"] = "建议观察"
    item["copy_block"] = f"建议观察\n{target or 'N/A'}"
    item["scale_action"] = "观察"
    item["normalized_action"] = "observe"
    item["ad_gate_blocked"] = True
    item["confirmed_status"] = item.get("confirmed_status") or "待复查"


def _observation_action_id(row: dict[str, object]) -> str:
    existing = str(row.get("action_id") or "").strip()
    target = _action_identity_target(row)
    scope = str(row.get("action_scope") or "").strip()
    if not scope:
        scope = "asin_target" if str(target).upper().startswith("B0") else ("search_term" if target else "product")
    identity_target = target.lower()
    parts = existing.split("||")
    if len(parts) >= 6:
        parts[-3] = scope
        parts[-2] = identity_target
        parts[-1] = "observe"
        return "||".join(parts)
    marketplace = str(row.get("marketplace") or row.get("站点") or "").strip().upper()
    sku = str(row.get("sku") or row.get("SKU") or "").strip()
    asin = str(row.get("asin") or row.get("ASIN") or "").strip().upper()
    if not marketplace or not asin:
        return existing
    return "||".join([marketplace, sku, asin, scope, identity_target, "observe"])


def _action_identity_target(row: dict[str, object]) -> str:
    target = _first_non_empty(
        row.get("search_term_or_target"),
        row.get("search_term"),
        row.get("targeting"),
        row.get("target"),
    )
    text = str(target or "").strip()
    if text.upper() in {"N/A", "NA", "NONE", "NULL", "NAN"}:
        return ""
    return text


def filter_ad_queue_by_decision(rows: Iterable[dict[str, object]], decisions: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    lookup = decision_lookup(decisions)
    filtered: list[dict[str, object]] = []
    for row in rows:
        decision = lookup.get(product_key_text(row))
        item = dict(row)
        if decision:
            item["suggested_action"] = "观察"
            item["final_decision"] = decision.get("final_decision")
            item["final_decision_label"] = decision.get("final_decision_label")
            item["final_decision_reason"] = decision.get("decision_reason")
            item["today_allowed_actions"] = " / ".join(str(action) for action in decision.get("today_allowed_actions") or [])
            item["today_blocked_actions"] = " / ".join(str(action) for action in decision.get("today_blocked_actions") or [])
            final = _clean(decision.get("final_decision"))
            bucket = _ad_action_bucket(row)
            action_allowed = _action_allowed_by_decision(bucket, final, decision)
            if not action_allowed:
                _mark_ad_action_as_observation(item, row)
            else:
                item["suggested_action"] = row.get("suggested_action")
                item["copy_action_line"] = row.get("copy_action_line")
            filtered.append(item)
        else:
            filtered.append(item)
    return filtered


def decision_summary(decisions: Iterable[dict[str, object]]) -> dict[str, object]:
    rows = [row for row in decisions if isinstance(row, dict)]
    counts = Counter(_clean(row.get("final_decision")) for row in rows)
    return {
        "final_decision_summary": dict(counts),
        "decision_gate_counts": dict(counts),
        "blocked_by_data_quality": [row for row in rows if row.get("final_decision") == "DATA_INSUFFICIENT"],
        "blocked_by_frontend": [row for row in rows if row.get("final_decision") == "FRONTEND_FIRST"],
        "blocked_by_inventory": [row for row in rows if row.get("inventory_constraint") in INVENTORY_BLOCKING],
        "blocked_by_cooldown": [row for row in rows if row.get("final_decision") == "WAIT_REVIEW"],
        "blocked_by_keyword_memory": [row for row in rows if row.get("keyword_memory_summary")],
        "executable_today_count": counts.get("EXECUTE_TODAY", 0) + counts.get("SMALL_SCALE_ALLOWED", 0),
        "wait_review_count": counts.get("WAIT_REVIEW", 0),
    }


def write_product_final_decisions(output_dir: Path, report_date: str, decisions: Iterable[dict[str, object]]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    date_token = report_date.replace("-", "")
    rows = [row for row in decisions if isinstance(row, dict)]
    json_path = output_dir / f"product_final_decisions_{date_token}.json"
    md_path = output_dir / "product_final_decisions.md"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 产品最终决策", ""]
    for row in rows:
        lines.append(
            f"- {row.get('marketplace') or ''}｜{row.get('product_name') or row.get('asin') or ''}："
            f"{row.get('final_decision_label') or row.get('final_decision')}；"
            f"{row.get('decision_reason') or ''}"
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path
