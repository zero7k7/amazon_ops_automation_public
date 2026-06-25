from __future__ import annotations

import sys
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from .analyze_rules import (
    SECTION_LIMITS,
    _format_count,
    _format_money,
    _format_percent,
    _infer_marketplace,
    _select_markdown_items,
    _target_acos_value,
    _to_float,
)
from .autoopt_feedback import add_action_identity, build_optimization_notes, build_runtime_policy, load_feedback_input
from .product_decision_layer import apply_decisions_to_rows, build_product_final_decisions, decision_summary, filter_ad_queue_by_decision
from .report_view import ad_workbench as ad_workbench_view
from .report_view import frontend as frontend_view
from .report_view import listing_review as listing_review_view
from .report_view import operations as operations_view
from .report_view import review as review_view

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "output"
KEYWORD_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "product_line_keywords.json"
EXPECTED_PRICE_SYMBOL = {"UK": "£", "US": "$", "DE": "€"}
EXPECTED_PRICE_CODE = {"UK": "GBP", "US": "USD", "DE": "EUR"}
BLOCKED_PRICE_CURRENCY_MARKERS = (
    "TWD",
    "NT$",
    "NTD",
    "HK$",
    "HKD",
    "RMB",
    "CNY",
    "CN¥",
    "￥",
    "¥",
    "CAD",
    "CA$",
    "AUD",
    "A$",
    "JPY",
    "JP¥",
    "円",
    "SGD",
    "S$",
)
WRONG_LOCATION_MARKERS = {
    "UK": ("united states", "canada", "australia", "japan", "germany", "deutschland"),
    "US": ("united kingdom", "great britain", "germany", "deutschland", "canada", "australia", "japan"),
    "DE": ("united states", "united kingdom", "great britain", "canada", "australia", "japan"),
}
MARKETPLACE_LOCATION_MARKERS = {
    "UK": ("united kingdom", "uk", "ireland", "aberdeen", "london", "manchester", "birmingham", "glasgow", "edinburgh"),
    "US": ("united states", "new york", "california", "texas", "florida", "washington"),
    "DE": ("germany", "deutschland", "berlin", "hamburg", "munich", "münchen", "frankfurt"),
}


PRODUCT_SUMMARY_KEY = "产品汇总"
ANOMALY_KEY = "异常提醒"
RECOMMENDATION_KEY = "操作建议"
LISTING_REVIEW_LABEL = "Listing 待人工确认"
LISTING_TEMP_ACTION = "暂时不加广告预算；核心词不直接否；明显不相关词才否定精准；相关高花费 0 单词先降竞价；等人工确认价格、主图、评价、Coupon、竞品和广告流量后再决定是否改 Listing。"
CONFIRMED_STATUS_VALUES = {"待确认", "已执行", "已核查", "已忽略", "仅背景参考", "待复查"}


def _confirmed_status(value: object, default: str = "待确认") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if text in CONFIRMED_STATUS_VALUES:
        return text
    lower = text.lower()
    if lower in {"executed", "done", "confirmed"}:
        return "已执行"
    if lower in {"ignored", "skip", "skipped"}:
        return "已忽略"
    if lower in {"background", "reference"}:
        return "仅背景参考"
    return default


def _is_observation_like_action(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text in {"观察", "保留", "保留观察", "无需操作", "仅背景参考"}:
        return True
    return any(token in text for token in ("观察", "保留", "无需操作"))


def _normalize_observation_feedback_statuses(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        if _confirmed_status(item.get("confirmed_status")) == "已执行" and _is_observation_like_action(
            item.get("suggested_action") or item.get("normalized_action") or item.get("today_action") or item.get("action")
        ):
            item["confirmed_status"] = "仅背景参考"
        normalized_rows.append(item)
    return normalized_rows


def required_flag(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "是"}


def boolish_flag(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "是", "已提供", "provided", "fresh"}


def _frontend_price_currency_warning(price: object, marketplace: object) -> str:
    return frontend_view._frontend_price_currency_warning(sys.modules[__name__], price, marketplace)


def _frontend_location_note(row: dict[str, object]) -> str:
    return frontend_view._frontend_location_note(sys.modules[__name__], row)


def _frontend_location_scope(row: dict[str, object]) -> str:
    return frontend_view._frontend_location_scope(sys.modules[__name__], row)


def _frontend_location_warning(row: dict[str, object]) -> str:
    return frontend_view._frontend_location_warning(sys.modules[__name__], row)


def _frontend_labeled_value(findings: object, label: str) -> str:
    return frontend_view._frontend_labeled_value(sys.modules[__name__], findings, label)


def _frontend_number(value: object) -> float | None:
    return frontend_view._frontend_number(sys.modules[__name__], value)


def _frontend_review_count(value: object) -> int | None:
    return frontend_view._frontend_review_count(sys.modules[__name__], value)


def _frontend_grade(score: int) -> str:
    return frontend_view._frontend_grade(sys.modules[__name__], score)


def _derive_frontend_display_quality(row: dict[str, object]) -> dict[str, object]:
    return frontend_view._derive_frontend_display_quality(sys.modules[__name__], row)


def _frontend_pct_text(value: object) -> str:
    return frontend_view._frontend_pct_text(sys.modules[__name__], value)


def _frontend_evidence_audit(row: dict[str, object]) -> dict[str, object]:
    return frontend_view._frontend_evidence_audit(sys.modules[__name__], row)


def common_date_range_days(value: object) -> int:
    if not value:
        return 0
    if isinstance(value, dict):
        start = value.get("start")
        end = value.get("end")
    else:
        parts = str(value).replace("~", " ").split()
        start = parts[0] if parts else None
        end = parts[-1] if len(parts) >= 2 else None
    if not start or not end:
        return 0
    try:
        start_date = datetime.fromisoformat(str(start)[:10]).date()
        end_date = datetime.fromisoformat(str(end)[:10]).date()
    except ValueError:
        return 0
    return max((end_date - start_date).days + 1, 0)


def data_quality_status_from_summary(summary: dict, has_data: bool = True) -> dict[str, object]:
    marketplace = summary.get("marketplace") or "N/A"
    if not has_data:
        if int(summary.get("ads_row_count", 0) or 0) > 0 and int(summary.get("erp_row_count", 0) or 0) == 0:
            return {
                "analysis_status": "仅广告数据",
                "issue_summary": f"{marketplace} 有广告数据，但 ERP 无数据",
                "strong_recommendation_allowed": False,
            }
        if int(summary.get("ads_row_count", 0) or 0) == 0 and int(summary.get("erp_row_count", 0) or 0) > 0:
            return {
                "analysis_status": "仅 ERP 数据",
                "issue_summary": f"{marketplace} 有 ERP 数据，但广告无数据",
                "strong_recommendation_allowed": False,
            }
        return {
            "analysis_status": "无数据",
            "issue_summary": f"{marketplace} 当前无可分析数据",
            "strong_recommendation_allowed": False,
        }

    erp_row_count = int(summary.get("erp_row_count", 0) or 0)
    history_days = int(summary.get("history_days", 0) or 0)
    common_days = common_date_range_days(summary.get("common_date_range"))
    zero_fill_applied = bool(summary.get("zero_fill_applied"))
    coverage_warning = str(summary.get("coverage_warning") or "").strip()
    coverage_confirmed = (
        zero_fill_applied
        and history_days >= 7
        and common_days >= 7
        and ("已按 0 单补齐" in coverage_warning or not coverage_warning)
    )
    if history_days < 7 or common_days < 7 or (erp_row_count < 7 and not coverage_confirmed):
        reasons: list[str] = []
        if history_days < 7:
            reasons.append(f"历史天数仅 {history_days} 天")
        if common_days < 7:
            reasons.append(f"共同日期范围仅 {common_days} 天")
        if erp_row_count < 7 and not coverage_confirmed:
            reasons.append(f"ERP 行数仅 {erp_row_count} 行")
        return {
            "analysis_status": "数据不足，仅观察",
            "issue_summary": "；".join(reasons) if reasons else "ERP 历史数据不足，暂不输出强运营建议",
            "strong_recommendation_allowed": False,
        }

    problems = []
    for key, label in [
        ("missing_sku_asin_map", "SKU映射失败"),
        ("missing_cost_config", "成本缺失"),
        ("missing_target_acos", "target_acos缺失"),
        ("missing_first_leg_cost", "头程成本缺失"),
    ]:
        if int(summary.get(key, 0) or 0) > 0:
            problems.append(f"{label} {summary.get(key)}")
    status_summary = "正常" if not problems else "；".join(problems)
    if coverage_confirmed and erp_row_count < 7:
        status_summary = f"ERP 覆盖完整，缺失日期已按 0 单补齐；当前仅 {erp_row_count} 个有销量日期"
    return {
        "analysis_status": "正式分析",
        "issue_summary": status_summary,
        "strong_recommendation_allowed": True,
    }


def data_quality_status_from_payload(analysis_payload: dict) -> dict[str, object]:
    common_range = analysis_payload.get("common_date_range", {})
    summary = {
        "marketplace": _infer_marketplace(analysis_payload),
        "erp_row_count": analysis_payload.get("erp_row_count", analysis_payload.get("import_summary", {}).get("erp_imported_rows", 0)),
        "history_days": analysis_payload.get("history_days", 0),
        "common_date_range": common_range,
        "zero_fill_applied": analysis_payload.get("zero_fill_applied", False),
        "coverage_warning": analysis_payload.get("coverage_warning", ""),
        "erp_report_coverage_date_range": analysis_payload.get("erp_report_coverage_date_range", {}),
        "erp_observed_sales_date_range": analysis_payload.get("erp_observed_sales_date_range", {}),
        **analysis_payload.get("data_quality_issue_summary", {}),
    }
    return data_quality_status_from_summary(summary, has_data=True)


def _money(value: object, marketplace: object = None, currency: object = None) -> str:
    return _format_money(value, marketplace=marketplace, currency=currency)


def _enhanced_status_rows(analysis_payload: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    status = analysis_payload.get("enhanced_data_status", {})

    def diagnosis_usage(used: str, period: str, freshness: str) -> str:
        if used == "否":
            return "未参与诊断"
        if freshness in {"unknown", "stale"} or period == "unknown" or used == "仅背景参考":
            return "仅背景参考"
        return "强诊断使用"

    def diagnosis_participation(value: object) -> str:
        text = str(value or "").strip()
        if text == "仅背景参考":
            return "仅背景参考"
        return "是" if boolish_flag(value) else "否"

    for report_type, files_key, comparable_key in [
        ("traffic_sales", "traffic_sales_files", "traffic_sales_comparable"),
        ("search_query_performance", "search_query_files", "search_query_comparable"),
    ]:
        comparable = boolish_flag(status.get(comparable_key))
        for item in status.get(files_key, []) or []:
            if isinstance(item, dict):
                filename = item.get("filename") or item.get("source_file") or item.get("file_name") or "N/A"
                period = item.get("period") or item.get("period_hint") or "N/A"
                detected_range = item.get("detected_date_range") or ""
                start = item.get("start_date") or item.get("date_start") or item.get("recent_start") or "N/A"
                end = item.get("end_date") or item.get("date_end") or item.get("recent_end") or "N/A"
                used_raw = item.get("used_in_diagnosis")
                freshness = str(item.get("freshness") or "unknown")
            else:
                filename = str(item)
                period = "N/A"
                detected_range = ""
                start = "N/A"
                end = "N/A"
                used_raw = True
                freshness = "unknown"
            used_in_diagnosis = diagnosis_participation(used_raw)
            usage_type = diagnosis_usage(used_in_diagnosis, str(period), freshness)
            rows.append(
                {
                    "报表类型": report_type,
                    "状态": "已导入",
                    "周期类型": str(period),
                    "日期范围": str(detected_range or f"{start} ~ {end}"),
                    "文件名": str(filename),
                    "是否可比较": "是" if comparable else "否",
                    "诊断使用类型": usage_type,
                    "是否参与诊断": used_in_diagnosis,
                    "识别来源": str(item.get("detected_from") or "fallback") if isinstance(item, dict) else "fallback",
                    "新鲜度": freshness,
                }
            )
    if not rows:
        rows.append(
            {
                "报表类型": "traffic_sales / search_query_performance",
                "状态": "未导入",
                "周期类型": "N/A",
                "日期范围": "N/A",
                "文件名": "N/A",
                "是否可比较": "否",
                "诊断使用类型": "未参与诊断",
                "是否参与诊断": "否",
            }
        )
    return rows


def _enhanced_required_request_rows(analysis_payload: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in analysis_payload.get("enhanced_data_requests", []):
        if not required_flag(row.get("required")):
            continue
        if str(row.get("status") or "").strip() == "已导入":
            continue
        rows.append(
            {
                "报表": row.get("report_type") or "N/A",
                "周期": row.get("period") or "N/A",
                "日期范围": f"{row.get('start_date') or 'N/A'} ~ {row.get('end_date') or 'N/A'}",
                "文件名": row.get("expected_filename") or "N/A",
                "必需": "是",
            }
        )
    return rows


def _enhanced_freshness_warning(analysis_payload: dict) -> str:
    status = analysis_payload.get("enhanced_data_status", {}) or {}
    marketplace = str(analysis_payload.get("target_marketplace") or _infer_marketplace(analysis_payload) or "").upper()
    warnings: list[str] = []
    for label, files_key in [("traffic_sales", "traffic_sales_files"), ("search_query_performance", "search_query_files")]:
        for item in status.get(files_key, []) or []:
            if not isinstance(item, dict):
                continue
            used = boolish_flag(item.get("used_in_diagnosis"))
            freshness = str(item.get("freshness") or "unknown")
            period = str(item.get("period") or item.get("period_hint") or "")
            detected_range = str(item.get("detected_date_range") or "")
            if not used:
                continue
            if label == "traffic_sales" and freshness not in {"fresh"}:
                warnings.append(f"{label} 当前为 {freshness} / {period}（{detected_range}），只作辅助，不作为强结论。")
            elif label == "search_query_performance" and freshness in {"unknown", "stale"}:
                warnings.append(f"{label} 周期不清（{detected_range or period}），只作辅助。")
    if marketplace == "US" and not warnings:
        traffic_files = [
            item
            for item in status.get("traffic_sales_files", []) or []
            if isinstance(item, dict) and boolish_flag(item.get("used_in_diagnosis"))
        ]
        query_files = [
            item
            for item in status.get("search_query_files", []) or []
            if isinstance(item, dict) and boolish_flag(item.get("used_in_diagnosis"))
        ]
        if traffic_files and query_files:
            traffic_periods = " ".join(str(item.get("period") or item.get("period_hint") or "") for item in traffic_files)
            query_periods = " ".join(str(item.get("period") or item.get("period_hint") or "") for item in query_files)
            if "week19" not in f"{traffic_periods} {query_periods}".lower():
                warnings.append("US 增强数据不是最新 Week19 周期；可用于背景判断，但强动作优先看广告/ERP 产品级指标。")
    return "；".join(dict.fromkeys(warnings))


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}
ACTION_GROUPS = ["广告动作", "Listing / 价格动作", "成本 / 利润动作"]


def _task_key(row: dict) -> tuple[str, str, str]:
    return (str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))


def _row_marketplace(row: dict, fallback: object = "") -> str:
    return str(row.get("marketplace") or row.get("站点") or fallback or "").strip().upper()


def _row_sku(row: dict) -> str:
    return str(row.get("sku") or row.get("SKU") or "").strip()


def _row_asin(row: dict) -> str:
    return str(row.get("asin") or row.get("ASIN") or "").strip().upper()


def _row_product_name(row: dict) -> str:
    return str(row.get("product_name") or row.get("产品") or row.get("产品名") or "N/A").strip() or "N/A"


def _front_product_url(marketplace: object, asin: object) -> str:
    return frontend_view._front_product_url(sys.modules[__name__], marketplace, asin)


def _front_search_url(marketplace: object, keyword: object) -> str:
    return frontend_view._front_search_url(sys.modules[__name__], marketplace, keyword)


def _keyword_config_lines() -> list[dict[str, object]]:
    return frontend_view._keyword_config_lines(sys.modules[__name__])


def _frontend_core_keyword(marketplace: str, product_name: str, sku: str, asin: str) -> str:
    return frontend_view._frontend_core_keyword(sys.modules[__name__], marketplace, product_name, sku, asin)


def _load_frontend_check_results(output_dir: Path = OUTPUT_DIR) -> dict[tuple[str, str, str], dict[str, object]]:
    return frontend_view._load_frontend_check_results(sys.modules[__name__], output_dir)


def _frontend_check_template(reason: str, evidence: str, issue_type: str) -> dict[str, str]:
    return frontend_view._frontend_check_template(sys.modules[__name__], reason, evidence, issue_type)


def _frontend_key_metrics(row: dict) -> str:
    return frontend_view._frontend_key_metrics(sys.modules[__name__], row)


def _build_frontend_check_queue(
    today_rows: list[dict[str, str]],
    listing_rows: list[dict[str, str]],
    marketplace: str,
    output_dir: Path = OUTPUT_DIR,
    limit: int = 5,
) -> list[dict[str, str]]:
    return frontend_view._build_frontend_check_queue(sys.modules[__name__], today_rows, listing_rows, marketplace, output_dir, limit)


def _append_unique_text(existing: str, addition: str, limit: int = 3) -> str:
    parts = [part for part in str(existing or "").split("；") if part and part != "N/A"]
    for part in str(addition or "").split("；"):
        part = part.strip()
        if part and part != "N/A" and part not in parts:
            parts.append(part)
    return "；".join(parts[:limit]) if parts else "N/A"


def _normalize_today_action(text: object, issue_type: str = "") -> str:
    return ad_workbench_view._normalize_today_action(sys.modules[__name__], text, issue_type)


def _search_term_action_from_item(item: dict, marketplace: str) -> dict[str, str]:
    return ad_workbench_view._search_term_action_from_item(sys.modules[__name__], item, marketplace)


def _build_search_term_processing_queue(analysis_payload: dict) -> list[dict[str, str]]:
    return ad_workbench_view._build_search_term_processing_queue(sys.modules[__name__], analysis_payload)


def _search_terms_for_task(task: dict[str, str], queue: list[dict[str, str]], limit: int = 5) -> str:
    return ad_workbench_view._search_terms_for_task(sys.modules[__name__], task, queue, limit)


def _parse_percent_text(value: object) -> float | None:
    return ad_workbench_view._parse_percent_text(sys.modules[__name__], value)


def _scale_keyword_action(term: str, ad_orders: float, acos: float, target_acos: float, clicks: float = 0) -> str:
    return ad_workbench_view._scale_keyword_action(sys.modules[__name__], term, ad_orders, acos, target_acos, clicks)


def _build_scale_keyword_rows(analysis_payload: dict, scale_rows: list[dict[str, str]], marketplace: str) -> list[dict[str, str]]:
    return ad_workbench_view._build_scale_keyword_rows(sys.modules[__name__], analysis_payload, scale_rows, marketplace)


def _specific_today_action(issue_type: str, reason: object = "", suggestion: object = "") -> str:
    return ad_workbench_view._specific_today_action(sys.modules[__name__], issue_type, reason, suggestion)


def _action_group_for(action: object, issue_type: object = "") -> str:
    return ad_workbench_view._action_group_for(sys.modules[__name__], action, issue_type)


def _product_metric(row: dict, *names: str) -> float:
    for name in names:
        value = _to_float(row.get(name))
        if value is not None:
            return value
    return 0.0


def _is_true_unsold_candidate(row: dict) -> bool:
    stock = _product_metric(row, "available_stock")
    recent_7 = _product_metric(row, "recent_7d_total_orders", "近7天订单")
    recent_14 = _product_metric(row, "recent_14d_total_orders", "近14天订单")
    recent_30 = _product_metric(row, "recent_30d_total_orders")
    return stock > 0 and (recent_7 == 0 or recent_14 == 0 or (recent_30 <= 1 and stock >= 20))


def _diagnosis_category(row: dict) -> str:
    primary = str(row.get("primary_reason") or row.get("reason") or "")
    total_14 = _product_metric(row, "recent_14d_total_orders")
    ad_orders = _product_metric(row, "recent_14d_ad_orders")
    natural_orders = _product_metric(row, "recent_14d_natural_orders")
    clicks = _product_metric(row, "recent_14d_clicks")
    spend = _product_metric(row, "recent_14d_ad_spend")
    profit = _to_float(row.get("profit_before_ads_per_unit"))
    if (profit is not None and profit <= 0) or primary == "利润不允许加广告":
        return "成本 / 利润压力诊断"
    if total_14 > 0 and natural_orders > 0 and ad_orders == 0 and (clicks > 0 or spend > 0):
        return "广告归因弱诊断"
    if _is_true_unsold_candidate(row):
        return "真无单 / 滞销诊断"
    if ad_orders == 0 and (clicks >= 6 or spend >= 3):
        return "广告消耗无转化诊断"
    if primary in {"点击后不转化", "加购后不购买", "搜索结果点击弱", "Listing 转化问题"}:
        return LISTING_REVIEW_LABEL
    return "真无单 / 滞销诊断"


def _listing_review_details(reason: object, evidence: object, action: object = "") -> dict[str, str]:
    return listing_review_view._listing_review_details(sys.modules[__name__], reason, evidence, action)


def _extract_number_after(text: str, label: str) -> float | None:
    return listing_review_view._extract_number_after(sys.modules[__name__], text, label)


def _compact_money_from_evidence(text: str, label: str) -> str:
    return listing_review_view._compact_money_from_evidence(sys.modules[__name__], text, label)


def _recent_7d_listing_metrics(evidence: str) -> tuple[float | None, float | None, str]:
    return listing_review_view._recent_7d_listing_metrics(sys.modules[__name__], evidence)


def _product_line_hint(product_name: object, sku: object = "", asin: object = "") -> str:
    return listing_review_view._product_line_hint(sys.modules[__name__], product_name, sku, asin)


def _group_records_by_asin(records: list[dict]) -> dict[str, list[dict]]:
    return listing_review_view._group_records_by_asin(sys.modules[__name__], records)


def _sum_record_metric(records: list[dict], key: str) -> float:
    return listing_review_view._sum_record_metric(sys.modules[__name__], records, key)


def _first_record_metric(records: list[dict], key: str) -> float | None:
    return listing_review_view._first_record_metric(sys.modules[__name__], records, key)


def _enhanced_listing_signals(traffic_records: list[dict], query_records: list[dict]) -> dict[str, list[str]]:
    return listing_review_view._enhanced_listing_signals(sys.modules[__name__], traffic_records, query_records)


def _unique_limited(items: list[str], limit: int) -> list[str]:
    return listing_review_view._unique_limited(sys.modules[__name__], items, limit)


def _rewrite_listing_review_copy(rows: list[dict[str, str]], search_queue: list[dict[str, str]], analysis_payload: dict | None = None) -> list[dict[str, str]]:
    return listing_review_view._rewrite_listing_review_copy(sys.modules[__name__], rows, search_queue, analysis_payload)


def _has_background_enhanced_data(analysis_payload: dict) -> bool:
    status = analysis_payload.get("enhanced_data_status", {})
    if not status.get("provided"):
        return False
    return not (status.get("traffic_sales_recent_exists") or status.get("search_query_recent_exists"))


def _diagnosis_view_rows(analysis_payload: dict) -> dict[str, list[dict[str, str]]]:
    categories = {
        "true_unsold_diagnosis_rows": [],
        "recent_conversion_cliff_diagnosis_rows": [],
        "ad_no_conversion_diagnosis_rows": [],
        "ad_attribution_weak_diagnosis_rows": [],
        "listing_price_diagnosis_rows": [],
        "cost_profit_diagnosis_rows": [],
    }

    def append_row(source: dict, category: str, source_section: str) -> None:
        marketplace = source.get("marketplace") or _infer_marketplace(analysis_payload)
        reason = source.get("primary_reason") or source.get("reason") or source.get("risk_level") or "N/A"
        evidence = source.get("evidence")
        if not evidence:
            evidence = (
                f"近14天总单 {_format_count(source.get('recent_14d_total_orders'))}；"
                f"广告订单 {_format_count(source.get('recent_14d_ad_orders'))}；"
                f"点击 {_format_count(source.get('recent_14d_clicks'))}；"
                f"花费 {_money(source.get('recent_14d_ad_spend'), marketplace, source.get('currency'))}"
            )
        action = _specific_today_action(category, reason, source.get("recommended_action") or source.get("suggestion"))
        row = {
            "产品": source.get("product_name") or "N/A",
            "SKU": source.get("sku") or "N/A",
            "ASIN": source.get("asin") or "N/A",
            "诊断类型": category,
            "主因": reason,
            "关键证据": evidence,
            "建议动作": action,
            "confirmed_status": _confirmed_status(source.get("confirmed_status")),
            "priority": source.get("priority") or source.get("优先级") or "",
            "source_section": source_section,
        }
        for cost_key in [
            "selling_price",
            "purchase_cost",
            "first_leg_cost",
            "fba_fee",
            "referral_fee",
            "vat",
            "digital_tax",
            "break_even_acos",
            "cost_status",
            "profit_before_ads_per_unit",
            "target_acos",
            "currency",
            "marketplace",
        ]:
            if cost_key in source:
                row[cost_key] = source.get(cost_key)
        if category == LISTING_REVIEW_LABEL:
            row.update(_listing_review_details(reason, evidence, action))
        key_map = {
            "真无单 / 滞销诊断": "true_unsold_diagnosis_rows",
            "近期转化断崖诊断": "recent_conversion_cliff_diagnosis_rows",
            "广告消耗无转化诊断": "ad_no_conversion_diagnosis_rows",
            "广告归因弱诊断": "ad_attribution_weak_diagnosis_rows",
            LISTING_REVIEW_LABEL: "listing_price_diagnosis_rows",
            "成本 / 利润压力诊断": "cost_profit_diagnosis_rows",
        }
        categories[key_map[category]].append(row)

    seen: set[tuple[str, str, str, str]] = set()
    for row in analysis_payload.get("无单原因诊断", []):
        category = _diagnosis_category(row)
        if category == "真无单 / 滞销诊断" and not _is_true_unsold_candidate(row):
            continue
        key = (category, str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
        if key in seen:
            continue
        seen.add(key)
        append_row(row, category, "诊断")

    for row in analysis_payload.get("广告消耗无转化风险", []):
        category = "广告归因弱诊断" if _product_metric(row, "recent_14d_total_orders") > 0 and _product_metric(row, "recent_14d_natural_orders") > 0 else "广告消耗无转化诊断"
        key = (category, str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
        if key not in seen:
            seen.add(key)
            append_row(row, category, "广告消耗无转化风险")

    for row in analysis_payload.get("滞销风险", []):
        if not _is_true_unsold_candidate(row):
            continue
        key = ("真无单 / 滞销诊断", str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
        if key not in seen:
            seen.add(key)
            append_row(row, "真无单 / 滞销诊断", "滞销 / 持续无单风险")

    for row in analysis_payload.get("库存 / 利润压力风险", []):
        profit = _to_float(row.get("profit_before_ads_per_unit"))
        if not (profit is not None and profit <= 0):
            continue
        key = ("成本 / 利润压力诊断", str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
        if key not in seen:
            seen.add(key)
            append_row(row, "成本 / 利润压力诊断", "库存 / 利润压力风险")

    metrics14 = {
        (
            str(row.get("marketplace") or _infer_marketplace(analysis_payload)),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
        ): row
        for row in analysis_payload.get("product_window_metrics", {}).get("14d", [])
    }
    metrics7 = {
        (
            str(row.get("marketplace") or _infer_marketplace(analysis_payload)),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
        ): row
        for row in analysis_payload.get("product_window_metrics", {}).get("7d", [])
    }
    for key_base, row14 in metrics14.items():
        marketplace, sku, asin = key_base
        clicks14 = _to_float(row14.get("ad_clicks")) or 0
        orders14 = _to_float(row14.get("ad_orders")) or 0
        spend14 = _to_float(row14.get("ad_spend")) or 0
        sales14 = _to_float(row14.get("ad_sales")) or 0
        total14 = _to_float(row14.get("total_orders")) or 0
        row7 = metrics7.get(key_base, {})
        clicks7 = _to_float(row7.get("ad_clicks")) or 0
        orders7 = _to_float(row7.get("ad_orders")) or 0
        spend7 = _to_float(row7.get("ad_spend")) or 0
        sales7 = _to_float(row7.get("ad_sales")) or 0
        total7 = _to_float(row7.get("total_orders")) or 0
        cvr14 = None if clicks14 == 0 else orders14 / clicks14
        cvr7 = None if clicks7 == 0 else orders7 / clicks7

        has_recent_cliff_history = total14 > 0 or orders14 > 0
        has_recent_cliff_sample = clicks7 >= 10 or spend7 >= 5
        recent_orders_dropped = total7 == 0 or orders7 == 0
        cvr_cliff = cvr14 is not None and cvr7 is not None and cvr7 < cvr14 * 0.5
        ad_orders_cliff = orders7 == 0 and orders14 > 0
        if has_recent_cliff_history and recent_orders_dropped and has_recent_cliff_sample and (cvr_cliff or ad_orders_cliff):
            is_p0_cliff = total7 == 0 and orders7 == 0 and (clicks7 >= 20 or spend7 >= 5)
            priority = "P0" if is_p0_cliff else "P1"
            cliff_action = (
                "近7天转化断崖：先检查价格、Coupon、主图、配送、Buy Box/推荐报价率；广告端暂停扩量，核心词降竞价10%-20%，不直接否核心词。"
                if is_p0_cliff
                else "近7天广告未出单但风险未达 P0：先检查价格、Coupon、主图、配送、Buy Box/推荐报价率；广告端先观察或小幅降竞价，不直接否核心词。"
            )
            reasons = []
            if total7 == 0 and total14 > 0:
                reasons.append("近7天转化断崖")
            if orders7 == 0 and orders14 > 0:
                reasons.append("近7天广告无单")
            if not reasons:
                reasons.append("近7天转化断崖 / 近7天广告无单")
            dedupe_key = ("近期转化断崖诊断", marketplace, sku, asin)
            if dedupe_key not in seen:
                seen.add(dedupe_key)
                evidence = (
                    f"近7天点击 {_format_count(clicks7)}；订单 {_format_count(orders7)}；"
                    f"总单 {_format_count(total7)}；花费 {_money(spend7, marketplace)}；"
                    f"近14天广告订单 {_format_count(orders14)}；近14天总单 {_format_count(total14)}"
                )
                if cvr14 is not None:
                    evidence += f"；14天广告CVR {_format_percent(cvr14)}"
                if cvr7 is not None:
                    evidence += f"；7天广告CVR {_format_percent(cvr7)}"
                if _has_background_enhanced_data(analysis_payload):
                    evidence += "；增强数据仅作背景参考"
                append_row(
                    {
                        "marketplace": marketplace,
                        "sku": sku,
                        "asin": asin,
                        "product_name": row14.get("product_name"),
                        "primary_reason": " / ".join(reasons),
                        "evidence": evidence,
                        "recommended_action": cliff_action,
                        "priority": priority,
                    },
                    "近期转化断崖诊断",
                    "product_window_metrics",
                )

        if orders14 <= 0 or clicks14 < 20:
            continue
        acos14 = None if sales14 == 0 else spend14 / sales14
        acos7 = None if sales7 == 0 else spend7 / sales7
        target_acos = _target_acos_value(row14)
        reasons: list[str] = []
        if target_acos is not None and target_acos > 0 and acos14 is not None and acos14 > target_acos:
            reasons.append("14天 ACOS 高于目标")
        if cvr14 is not None and cvr7 is not None and clicks7 >= 20 and cvr7 < cvr14 * 0.75:
            reasons.append("近7天转化恶化")
        if acos14 is not None and acos7 is not None and clicks7 >= 20 and acos7 > acos14 * 1.25:
            reasons.append("近7天 ACOS 升高")
        if not reasons:
            continue
        dedupe_key = (LISTING_REVIEW_LABEL, marketplace, sku, asin)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        evidence = (
            f"近14天产品级广告点击 {_format_count(clicks14)}；广告订单 {_format_count(orders14)}；"
            f"广告花费 {_money(spend14, marketplace)}；广告销售 {_money(sales14, marketplace)}；"
            f"总单 {_format_count(total14)}"
        )
        if clicks7:
            evidence += (
                f"；近7天点击 {_format_count(clicks7)}；订单 {_format_count(orders7)}；"
                f"花费 {_money(spend7, marketplace)}"
            )
        append_row(
            {
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": row14.get("product_name"),
                "primary_reason": " / ".join(reasons),
                "evidence": evidence,
                "recommended_action": LISTING_TEMP_ACTION,
            },
            LISTING_REVIEW_LABEL,
            "product_window_metrics",
        )

    return categories


def _merge_task(tasks: dict[tuple[str, str, str], dict[str, str]], row: dict[str, str]) -> None:
    key = _task_key(row)
    existing = tasks.get(key)
    if existing is None:
        tasks[key] = row
        return
    existing["issue_type"] = _append_unique_text(existing.get("issue_type", ""), row.get("issue_type", ""), limit=6)
    existing["key_evidence"] = _append_unique_text(existing.get("key_evidence", ""), row.get("key_evidence", ""), limit=3)
    existing["source_section"] = _append_unique_text(existing.get("source_section", ""), row.get("source_section", ""), limit=6)
    if PRIORITY_ORDER.get(row.get("priority", "P2"), 9) < PRIORITY_ORDER.get(existing.get("priority", "P2"), 9):
        existing["priority"] = row.get("priority", existing.get("priority", "P2"))
        existing["primary_reason"] = row.get("primary_reason", existing.get("primary_reason", "N/A"))
        existing["today_action"] = row.get("today_action", existing.get("today_action", "N/A"))
        existing["action_group"] = row.get("action_group", existing.get("action_group", "广告动作"))
        existing["tomorrow_check"] = row.get("tomorrow_check", existing.get("tomorrow_check", "N/A"))


def _apply_manual_feedback_to_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    feedback_rows = load_feedback_input(OUTPUT_DIR)
    if not feedback_rows:
        return [{**row, "confirmed_status": _confirmed_status(row.get("confirmed_status"), default="待确认")} for row in rows]
    lookup: dict[tuple[str, str, str], dict[str, object]] = {}
    sku_asin_lookup: dict[tuple[str, str], dict[str, object]] = {}
    for feedback in feedback_rows:
        key = (
            str(feedback.get("marketplace") or "").upper(),
            str(feedback.get("sku") or "").strip(),
            str(feedback.get("asin") or "").strip(),
        )
        if key != ("", "", ""):
            lookup[key] = feedback
        sku_asin_key = (key[1], key[2])
        if sku_asin_key != ("", ""):
            sku_asin_lookup[sku_asin_key] = feedback
    updated_rows: list[dict[str, str]] = []
    for row in rows:
        key = (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or row.get("SKU") or "").strip(),
            str(row.get("asin") or row.get("ASIN") or "").strip(),
        )
        feedback = lookup.get(key)
        if not feedback and not key[0]:
            feedback = sku_asin_lookup.get((key[1], key[2]))
        if not feedback:
            updated_rows.append({**row, "confirmed_status": _confirmed_status(row.get("confirmed_status"), default="待确认")})
            continue
        updated = dict(row)
        status = _confirmed_status(feedback.get("confirmed_status"), default=_confirmed_status(updated.get("confirmed_status")))
        if status == "已执行" and _is_observation_like_action(
            updated.get("suggested_action") or updated.get("normalized_action") or updated.get("today_action") or updated.get("action")
        ):
            status = "仅背景参考"
        updated["confirmed_status"] = status
        note = str(feedback.get("confirmed_note") or feedback.get("note") or "").strip()
        if note:
            updated["confirmed_note"] = note
        if status == "已执行":
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
            ]:
                value = feedback.get(field)
                if value not in (None, "") and updated.get(field) in (None, ""):
                    updated[field] = value
        updated_rows.append(updated)
    return updated_rows


def _apply_manual_feedback_to_search_queue(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    feedback_rows = load_feedback_input(OUTPUT_DIR)
    if not feedback_rows:
        return [{**row, "confirmed_status": _confirmed_status(row.get("confirmed_status"), default="待确认")} for row in rows]
    executed_term_keys: set[tuple[str, str, str, str, str]] = set()
    executed_product_keys: set[tuple[str, str, str]] = set()
    for feedback in feedback_rows:
        if str(feedback.get("confirmed_status") or "") != "已执行":
            continue
        product_key = (
            str(feedback.get("marketplace") or "").upper(),
            str(feedback.get("sku") or "").strip(),
            str(feedback.get("asin") or "").strip(),
        )
        term = str(feedback.get("search_term_or_target") or feedback.get("search_term") or "").strip().lower()
        action = str(feedback.get("suggested_action") or feedback.get("copy_action_line") or feedback.get("action") or "").strip()
        if term:
            executed_term_keys.add((*product_key, term, action))
            executed_term_keys.add((*product_key, term, ""))
        else:
            executed_product_keys.add(product_key)
    if not executed_term_keys and not executed_product_keys:
        return rows
    updated_rows: list[dict[str, str]] = []
    for row in rows:
        product_key = (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip(),
        )
        term = str(row.get("search_term_or_target") or "").strip().lower()
        action = str(row.get("suggested_action") or row.get("copy_action_line") or "").strip()
        updated = dict(row)
        term_matched = (*product_key, term, action) in executed_term_keys or (*product_key, term, "") in executed_term_keys
        product_matched = product_key in executed_product_keys and not term
        if (term_matched or product_matched) and str(updated.get("suggested_action") or "") != "观察":
            updated["confirmed_status"] = "已执行"
        else:
            updated["confirmed_status"] = _confirmed_status(updated.get("confirmed_status"), default="待确认")
        updated_rows.append(updated)
    return updated_rows


def _ad_memory_action_text(row: dict[str, object]) -> str:
    for field in ["suggested_action", "scale_action", "copy_action_line", "copy_block", "today_action", "normalized_action"]:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _memory_block_reason(row: dict[str, object], runtime_policy: dict[str, object]) -> tuple[str, str]:
    identified = add_action_identity(dict(row), _ad_memory_action_text(row))
    action_id = str(identified.get("action_id") or "").strip()
    blocked_ids = {
        str(item).strip()
        for item in (runtime_policy.get("blocked_action_ids") or [])
        if str(item).strip()
    }
    if action_id and action_id in blocked_ids:
        cooldown = (runtime_policy.get("action_cooldowns") or {}).get(action_id) if isinstance(runtime_policy.get("action_cooldowns"), dict) else {}
        if isinstance(cooldown, dict):
            reason = str(
                cooldown.get("block_reason")
                or cooldown.get("reason")
                or cooldown.get("status")
                or "已执行冷却中"
            ).strip()
            return action_id, reason
        return action_id, "已执行冷却中"

    memories = runtime_policy.get("keyword_strategy_memory") or []
    if not isinstance(memories, list):
        return "", ""
    for memory in memories:
        if not isinstance(memory, dict):
            continue
        memory_action_id = str(memory.get("action_id") or "").strip()
        if not action_id or memory_action_id != action_id:
            continue
        try:
            score = int(memory.get("effectiveness_score") or 0)
        except (TypeError, ValueError):
            score = 0
        review_outcome = str(memory.get("review_outcome") or "").strip()
        halo_text = str(memory.get("halo_only_conversion") or "").strip().lower()
        halo_only = halo_text in {"1", "true", "yes", "是"} or str(memory.get("attribution_effect_status") or "") == "halo_only_conversion"
        should_block = bool(memory.get("should_block_repeating")) and review_outcome != "not_ready"
        if halo_only:
            return action_id, "只有光环成交，需人工复查"
        if review_outcome == "ineffective":
            return action_id, "历史效果差，不重复推送"
        if should_block or (score < 0 and review_outcome not in {"not_ready", "insufficient_sample"}):
            reason = str(memory.get("block_reason") or memory.get("recommended_future_policy") or memory.get("evidence_summary") or "历史效果不支持重复推送").strip()
            return action_id, reason
    return "", ""


def _apply_ad_memory_hard_gate(
    rows: list[dict[str, object]],
    runtime_policy: dict[str, object],
) -> list[dict[str, object]]:
    if not isinstance(runtime_policy, dict):
        return rows
    updated_rows: list[dict[str, object]] = []
    for row in rows:
        action_id, reason = _memory_block_reason(row, runtime_policy)
        if not action_id:
            updated_rows.append(row)
            continue
        item = dict(row)
        original_action = _ad_memory_action_text(row)
        target = str(
            item.get("search_term_or_target")
            or item.get("search_term")
            or item.get("targeting")
            or item.get("target")
            or "N/A"
        ).strip()
        item["suggested_action"] = "观察"
        item["scale_action"] = "观察"
        item["copy_action_line"] = "建议观察"
        item["copy_block"] = f"建议观察\n{target or 'N/A'}"
        item["ad_memory_blocked"] = True
        item["blocked_action_id"] = action_id
        item["blocked_original_action"] = original_action
        item["keyword_memory_summary"] = reason
        existing_classification = str(item.get("classification_reason") or "").strip()
        block_line = f"自我优化拦截：{reason}"
        item["classification_reason"] = (
            f"{existing_classification}；{block_line}" if existing_classification else block_line
        )
        item["confirmed_status"] = item.get("confirmed_status") or "仅背景参考"
        updated_rows.append(item)
    return updated_rows


def _numeric_value(value: object) -> float | None:
    numeric = _to_float(value)
    if numeric is not None:
        return numeric
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _ratio_value(value: object, default: float | None = None) -> float | None:
    numeric = _numeric_value(value)
    if numeric is None:
        return default
    return numeric / 100 if numeric > 1 else numeric


def _growth_product_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or row.get("站点") or "").strip().upper(),
        str(row.get("sku") or row.get("SKU") or "").strip(),
        str(row.get("asin") or row.get("ASIN") or "").strip().upper(),
    )


def _growth_market_symbol(marketplace: object) -> str:
    return EXPECTED_PRICE_SYMBOL.get(str(marketplace or "").upper(), "$")


def _growth_text(row: dict[str, object], *fields: str) -> str:
    return " ".join(str(row.get(field) or "") for field in fields).strip()


def _growth_is_low_relevance(row: dict[str, object]) -> bool:
    text = _growth_text(
        row,
        "suggested_action",
        "confirmed_status",
        "manual_level",
        "keyword_level",
        "relevance_level",
        "classification_reason",
        "reason",
    )
    if str(row.get("confirmed_status") or "") in {"仅背景参考", "已忽略"}:
        return True
    hard_excluded = ["明显不相关", "低相关", "低质", "泛词", "无需操作", "仅背景参考", "不相关"]
    if any(token in text for token in hard_excluded):
        return True
    term = str(row.get("search_term_or_target") or row.get("search_term") or "").strip().lower()
    if not term or re.match(r"^B0[A-Z0-9]{8,}$", term, re.IGNORECASE):
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", term) if token]
    if len(tokens) <= 1:
        return True
    if term in {"bread board", "cutting board", "chopping board"} and (_numeric_value(row.get("orders") or row.get("ad_orders")) or 0) <= 0:
        return True
    return False


def _growth_is_broad_core_without_conversion(row: dict[str, object]) -> bool:
    term = str(row.get("search_term_or_target") or row.get("search_term") or "").strip().lower()
    if not term:
        return True
    orders = _numeric_value(row.get("orders") if row.get("orders") not in (None, "") else row.get("ad_orders")) or 0
    if orders > 0:
        return False
    tokens = [token for token in re.split(r"[^a-z0-9]+", term) if token]
    if len(tokens) > 3:
        return False
    if not {"bread", "board"}.issubset(set(tokens)):
        return False
    intent_modifiers = {
        "crumb",
        "catcher",
        "tray",
        "chopping",
        "wooden",
        "bamboo",
        "slicer",
        "slicing",
        "holder",
        "box",
        "kitchen",
    }
    return not any(token in intent_modifiers for token in tokens)


def _growth_evidence_level(row: dict[str, object]) -> str:
    orders = _numeric_value(row.get("orders") if row.get("orders") not in (None, "") else row.get("ad_orders")) or 0
    clicks = _numeric_value(row.get("clicks") or row.get("ad_clicks")) or 0
    text = _growth_text(row, "manual_level", "keyword_level", "relevance_level", "classification_reason", "reason")
    if orders > 0 or any(token in text for token in ["历史出单", "出单词", "已转化"]):
        return "历史广告订单"
    if any(token in text for token in ["核心词", "强相关", "高相关", "core"]):
        return "核心强相关"
    term = str(row.get("search_term_or_target") or row.get("search_term") or "").lower()
    if "bread" in term and "board" in term and any(token in term for token in ["crumb", "catcher", "tray", "chopping", "cutting", "wooden", "bamboo", "slicer"]):
        return "强意图长尾"
    if clicks > 0:
        return "有点击样本不足"
    return ""


def _growth_term_allowed(row: dict[str, object]) -> bool:
    if _growth_is_low_relevance(row):
        return False
    if _growth_is_broad_core_without_conversion(row):
        return False
    if _growth_is_existing_exact(row):
        return False
    return bool(_growth_evidence_level(row))


def _growth_budget_and_bid(
    row: dict[str, object],
    product: dict[str, object],
) -> tuple[str, str, str, str]:
    marketplace = str(row.get("marketplace") or product.get("marketplace") or product.get("站点") or "").upper()
    symbol = _growth_market_symbol(marketplace)
    clicks = _numeric_value(row.get("clicks") or row.get("ad_clicks")) or 0
    spend = _numeric_value(row.get("spend") or row.get("ad_spend")) or 0
    orders = _numeric_value(row.get("orders") if row.get("orders") not in (None, "") else row.get("ad_orders")) or 0
    recent_cpc = spend / clicks if clicks > 0 and spend > 0 else None
    product_clicks = _numeric_value(product.get("recent_7d_clicks") or product.get("clicks")) or 0
    product_orders = _numeric_value(product.get("recent_7d_orders") or product.get("ad_orders")) or 0
    product_cvr = product_orders / product_clicks if product_clicks > 0 and product_orders > 0 else None
    row_cvr = orders / clicks if clicks > 0 and orders > 0 else None
    cvr = row_cvr or product_cvr or _ratio_value(product.get("ad_cvr") or product.get("CVR"), 0.05) or 0.05
    target_acos = _ratio_value(product.get("target_acos") or product.get("目标 ACOS"), 0.12) or 0.12
    price = (
        _numeric_value(product.get("selling_price"))
        or _numeric_value(product.get("price"))
        or _numeric_value(product.get("售价"))
        or ((_numeric_value(product.get("ad_sales")) or 0) / (_numeric_value(product.get("ad_orders")) or 1) if _numeric_value(product.get("ad_orders")) else None)
        or (19.99 if marketplace in {"UK", "DE"} else 24.99)
    )
    affordable_cpc = max(0.08, price * target_acos * cvr)
    market_bid_cap = 0.45 if marketplace == "UK" else 0.60
    if recent_cpc:
        bid_min = max(0.08, min(recent_cpc * 0.85, affordable_cpc * 0.9))
        if orders > 0:
            allowed_high = min(market_bid_cap, max(affordable_cpc * 1.10, recent_cpc))
        else:
            allowed_high = min(market_bid_cap, affordable_cpc)
        bid_max = max(bid_min + 0.03, allowed_high)
    else:
        bid_min = max(0.08, affordable_cpc * 0.75)
        bid_max = max(bid_min + 0.03, min(affordable_cpc, market_bid_cap))
    evidence_level = _growth_evidence_level(row)
    base_budget = 2.0 if evidence_level == "历史广告订单" else min(2.0, max(1.0, (recent_cpc or bid_max) * 5))
    product_7d_spend = (
        _numeric_value(product.get("recent_7d_ad_spend"))
        or _numeric_value(product.get("recent_7d_spend"))
        or _numeric_value(product.get("ad_spend_7d"))
        or _numeric_value(product.get("spend_7d"))
    )
    if product_7d_spend and evidence_level != "历史广告订单":
        base_budget = min(base_budget, max(0.5, product_7d_spend * 0.30 / 7))
    stop_loss_rule = (
        f"7天点击达到 12 次仍无本 SKU 订单则停；ACOS 超过目标 ACOS 1.5 倍或 CPC 高于 {symbol}{affordable_cpc:.2f} 则降回。"
    )
    return (
        f"{symbol}{base_budget:.2f}/天",
        f"{symbol}{bid_min:.2f}",
        f"{symbol}{bid_max:.2f}",
        stop_loss_rule,
    )


def _growth_review_date(report_date: object) -> str:
    text = str(report_date or "").strip()[:10]
    try:
        day = datetime.fromisoformat(text).date()
    except Exception:
        day = datetime.now().date()
    return (day + timedelta(days=3)).isoformat()


def _growth_text_from_fields(row: dict[str, object], *fields: str) -> str:
    return " ".join(str(row.get(field) or "") for field in fields).strip().lower()


def _growth_traffic_origin(row: dict[str, object]) -> str:
    match_text = _growth_text_from_fields(row, "match_type", "match_type_or_targeting", "matched_target", "targeting")
    if any(token in match_text for token in ["auto", "close-match", "loose-match", "substitutes", "complements", "close match", "loose match"]):
        return "自动广告"
    if any(token in match_text for token in ["exact", "phrase", "broad", "精准", "词组", "广泛"]):
        return "手动广告"

    term = str(row.get("search_term_or_target") or row.get("search_term") or row.get("targeting") or "").strip()
    targeting_text = _growth_text_from_fields(row, "targeting", "match_type_or_targeting")
    if re.match(r"^B0[A-Z0-9]{8,}$", term, re.IGNORECASE) or any(
        token in targeting_text for token in ["asin定向", "asin 定向", "product targeting", "product-targeting", "商品投放", "商品定向"]
    ):
        return "ASIN定向"

    campaign_text = _growth_text_from_fields(row, "campaign_name", "campaign")
    if any(token in campaign_text for token in ["自动", "auto"]):
        return "自动广告"
    if any(token in campaign_text for token in ["手动", "manual", "精准", "exact", "词组", "phrase", "广泛", "broad"]):
        return "手动广告"

    review_text = _growth_text_from_fields(row, "confirmed_note", "manual_action_taken", "action_detail", "normalized_action")
    if any(token in review_text for token in ["自动出单词", "自动广告", "auto"]):
        return "自动广告"
    if "泛核心词" in review_text and "降竞价" in review_text:
        return "手动广告"
    if "bid_down" in review_text and any(token in review_text for token in ["核心词", "泛核心"]):
        return "手动广告"
    return "未识别"


def _growth_match_text(row: dict[str, object]) -> str:
    return _growth_text_from_fields(row, "match_type", "match_type_or_targeting", "targeting", "matched_target")


def _growth_is_existing_exact(row: dict[str, object]) -> bool:
    match_text = _growth_match_text(row)
    if not any(token in match_text for token in ["exact", "精准"]):
        return False
    if any(token in match_text for token in ["targeting_expression_predefined", "close-match", "loose-match", "substitutes", "complements"]):
        return False
    return _growth_traffic_origin(row) == "手动广告"


def _growth_operation_label(row: dict[str, object]) -> str:
    if _growth_is_existing_exact(row):
        return "已在精准，管理原广告"
    origin = _growth_traffic_origin(row)
    match_text = _growth_match_text(row)
    if origin == "自动广告":
        return "自动出词，拉精准"
    if "phrase" in match_text or "词组" in match_text:
        return "词组出词，拉精准"
    if "broad" in match_text or "广泛" in match_text:
        return "广泛出词，拉精准"
    if origin == "ASIN定向":
        return "ASIN定向，单独评估"
    if origin == "手动广告":
        return "手动出词，拉精准"
    return "来源待核对，暂不盲开"


def _growth_source_fields(row: dict[str, object]) -> dict[str, object]:
    campaign_name = row.get("campaign_name") or row.get("campaign") or ""
    ad_group_name = row.get("ad_group_name") or row.get("ad_group") or ""
    match_type = row.get("match_type") or ""
    targeting = row.get("targeting") or row.get("match_type_or_targeting") or ""
    matched_target = row.get("matched_target") or ""
    return {
        "campaign_name": campaign_name,
        "campaign": campaign_name,
        "ad_group_name": ad_group_name,
        "ad_group": ad_group_name,
        "match_type": match_type,
        "targeting": targeting,
        "matched_target": matched_target,
        "match_type_or_targeting": row.get("match_type_or_targeting") or match_type or targeting or ("ASIN定向" if _growth_traffic_origin(row) == "ASIN定向" else ""),
        "traffic_origin": _growth_traffic_origin(row),
        "operation_label": _growth_operation_label(row),
    }


def _growth_history_key(row: dict[str, object]) -> tuple[str, str, str, str]:
    return (*_growth_product_key(row), str(row.get("search_term_or_target") or row.get("search_term") or "").strip().lower())


def _growth_history_lookup(rows: list[dict[str, object]]) -> dict[tuple[str, str, str, str], list[dict[str, object]]]:
    lookup: dict[tuple[str, str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _growth_history_key(row)
        if key[3]:
            lookup.setdefault(key, []).append(row)
    return lookup


def _growth_active_product_tests(rows: list[dict[str, object]]) -> set[tuple[str, str, str]]:
    active: set[tuple[str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = str(row.get("normalized_action") or "").strip()
        detail = _growth_text_from_fields(row, "action_detail", "manual_action_taken", "confirmed_note", "suggested_action")
        if normalized != "growth_test" and not any(token in detail for token in ["小预算", "growth_test"]):
            continue
        cooldown = str(row.get("cooldown_status") or "").strip()
        phase = str(row.get("review_phase") or "").strip()
        outcome = str(row.get("review_outcome") or "").strip()
        days_since = _numeric_value(row.get("days_since_execution"))
        is_active = (
            cooldown == "cooldown_active"
            or phase == "under_3_days"
            or outcome == "not_ready"
            or (days_since is not None and days_since < 7)
        )
        if is_active:
            active.add(_growth_product_key(row))
    return active


def _growth_blocked_by_history(row: dict[str, object], history_rows: list[dict[str, object]]) -> bool:
    if not history_rows:
        return False
    orders = _numeric_value(row.get("orders") if row.get("orders") not in (None, "") else row.get("ad_orders")) or 0
    if orders > 0:
        return False
    executable_actions = {"bid_up", "bid_down", "create_exact", "growth_test", "negative_exact", "pause"}
    for history in history_rows:
        normalized = str(history.get("normalized_action") or "").strip()
        detail = _growth_text_from_fields(history, "action_detail", "manual_action_taken", "confirmed_note")
        outcome = str(history.get("review_outcome") or "").strip()
        score = _numeric_value(history.get("effectiveness_score"))
        if normalized in executable_actions:
            return True
        if any(token in detail for token in ["加价", "降竞价", "拉精准", "小预算", "否定", "暂停"]):
            return True
        if outcome in {"ineffective", "needs_manual_review", "halo_only_conversion", "insufficient_sample"} and (score or 0) <= 0:
            return True
    return False


def _build_growth_test_rows(
    search_rows: list[dict[str, object]],
    scale_rows: list[dict[str, object]],
    product_cards: list[dict[str, object]],
    keyword_review_rows: list[dict[str, object]],
    runtime_policy: dict[str, object],
    *,
    report_date: object = "",
) -> list[dict[str, object]]:
    product_lookup = {_growth_product_key(card): card for card in product_cards if isinstance(card, dict)}
    candidates: list[tuple[int, dict[str, object]]] = []
    history_lookup = _growth_history_lookup(keyword_review_rows)
    active_growth_products = _growth_active_product_tests(keyword_review_rows)
    source_rows: list[tuple[str, dict[str, object]]] = []
    source_rows.extend(("search_term_report", row) for row in search_rows if isinstance(row, dict))
    source_rows.extend(("search_term_report", row) for row in scale_rows if isinstance(row, dict))

    seen: set[tuple[str, str, str, str]] = set()
    for term_source, row in source_rows:
        if not _growth_term_allowed(row):
            continue
        key = _growth_product_key(row)
        if key in active_growth_products:
            continue
        product = product_lookup.get(key, {})
        if not product:
            product = {
                "marketplace": row.get("marketplace"),
                "sku": row.get("sku") or row.get("SKU"),
                "asin": row.get("asin") or row.get("ASIN"),
                "product_name": row.get("product_name") or row.get("产品"),
            }
        term = str(row.get("search_term_or_target") or row.get("search_term") or "").strip()
        dedupe_key = (*key, term.lower())
        if dedupe_key in seen:
            continue
        if _growth_blocked_by_history(row, history_lookup.get(dedupe_key, [])):
            continue
        seen.add(dedupe_key)
        base = {
            "marketplace": key[0],
            "sku": key[1],
            "asin": key[2],
            "product_name": row.get("product_name") or product.get("product_name") or product.get("产品") or "",
            "search_term_or_target": term,
            "suggested_action": "小预算试投",
            "manual_action_taken": "小预算试投",
            "experiment_type": "growth_test",
            "term_source": term_source,
            "evidence_level": _growth_evidence_level(row),
            "test_days": "7",
            "report_date": str(report_date or row.get("report_date") or ""),
            "next_review": _growth_review_date(report_date or row.get("report_date") or ""),
            "cooldown_days": 7,
            "clicks": row.get("clicks") or row.get("ad_clicks") or "0",
            "spend": row.get("spend") or row.get("ad_spend") or "",
            "orders": row.get("orders") if row.get("orders") not in (None, "") else row.get("ad_orders") or "0",
            **_growth_source_fields(row),
        }
        budget, bid_min, bid_max, stop_loss = _growth_budget_and_bid(base | row, product)
        item = add_action_identity(
            {
                **base,
                "suggested_daily_budget": budget,
                "suggested_bid_min": bid_min,
                "suggested_bid_max": bid_max,
                "stop_loss_rule": stop_loss,
                "success_rule": "7天内至少出现本 SKU 订单；ACOS 接近或低于目标 ACOS；点击、自然单或搜索排名有改善。",
                "reason": f"{base['evidence_level']}，只建议小预算测试，7天复盘本 SKU 订单和 ACOS。",
                "confirmed_status": "待确认",
                "html_visible": "是",
            },
            "小预算试投",
        )
        action_id, _reason = _memory_block_reason(item, runtime_policy) if isinstance(runtime_policy, dict) else ("", "")
        if action_id:
            continue
        score = 0
        if item["evidence_level"] == "历史广告订单":
            score -= 3
        elif item["evidence_level"] == "核心强相关":
            score -= 2
        elif item["evidence_level"] == "强意图长尾":
            score -= 1
        score -= int(_numeric_value(item.get("orders")) or 0)
        score += len(candidates)
        candidates.append((score, item))

    selected: list[dict[str, object]] = []
    product_counts: dict[tuple[str, str, str], int] = {}
    for _, row in sorted(candidates, key=lambda item: item[0]):
        product_key = _growth_product_key(row)
        if product_counts.get(product_key, 0) >= 2:
            continue
        selected.append(row)
        product_counts[product_key] = product_counts.get(product_key, 0) + 1
        if len(selected) >= 8:
            break
    return selected


def _learning_policy_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or "").upper(),
        str(row.get("sku") or row.get("SKU") or "").strip(),
        str(row.get("asin") or row.get("ASIN") or "").strip(),
    )


def _apply_runtime_policy_to_today_queue(
    rows: list[dict[str, str]],
    runtime_policy: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    cooldowns = runtime_policy.get("product_cooldowns", {}) if isinstance(runtime_policy, dict) else {}
    if not isinstance(cooldowns, dict) or not cooldowns:
        return rows, []
    active_rows: list[dict[str, str]] = []
    cooled_rows: list[dict[str, str]] = []
    seen_review: set[tuple[str, str, str]] = set()
    for row in rows:
        key = _learning_policy_key(row)
        cooldown = cooldowns.get(key)
        if not cooldown or str(row.get("issue_type") or "") == "数据质量问题":
            active_rows.append(row)
            continue
        updated = dict(row)
        updated["confirmed_status"] = "已执行"
        updated["learning_status"] = str(cooldown.get("status") or "已执行冷却")
        updated["cooldown_reason"] = str(cooldown.get("reason") or "已执行，短期不重复推送为今日强动作")
        if key not in seen_review:
            seen_review.add(key)
            cooled_rows.append(
                {
                    "marketplace": updated.get("marketplace", "N/A"),
                    "product_name": updated.get("product_name", "N/A"),
                    "sku": updated.get("sku", "N/A"),
                    "asin": updated.get("asin", "N/A"),
                    "review_reason": "已执行动作冷却期",
                    "current_evidence": updated.get("key_evidence", "N/A"),
                    "tomorrow_check": str(cooldown.get("reason") or "等新数据复查效果，不重复执行同一动作"),
                    "trigger_action": "不操作，仅复查",
                    "confirmed_status": "已执行",
                }
            )
        # Do not keep the row in active P0/P1. It will be visible in action review
        # and tomorrow review instead of reappearing as a fresh task.
    return active_rows, cooled_rows


def _apply_product_lessons_to_listing_rows(
    rows: list[dict[str, str]],
    runtime_policy: dict[str, object],
    marketplace: str,
) -> list[dict[str, str]]:
    lessons = runtime_policy.get("product_lessons", {}) if isinstance(runtime_policy, dict) else {}
    if not isinstance(lessons, dict) or not lessons:
        return rows
    updated_rows: list[dict[str, str]] = []
    for row in rows:
        key = (
            str(row.get("marketplace") or marketplace or "").upper(),
            str(row.get("SKU") or row.get("sku") or "").strip(),
            str(row.get("ASIN") or row.get("asin") or "").strip(),
        )
        lesson = lessons.get(key)
        if not lesson and key[0]:
            lesson = lessons.get(("", key[1], key[2]))
        if not lesson:
            updated_rows.append(row)
            continue
        if str(lesson.get("learning_type") or "") == "词级动作执行" or str(lesson.get("search_term_or_target") or "").strip():
            updated_rows.append(row)
            continue
        root_cause = str(lesson.get("manual_root_cause") or "").strip()
        action_taken = str(lesson.get("manual_action_taken") or "").strip()
        next_review = str(lesson.get("next_review") or "").strip()
        learned_note = "；".join(part for part in [root_cause, action_taken, next_review] if part)
        updated = dict(row)
        updated["历史人工确认"] = learned_note or str(lesson.get("confirmed_note") or "")
        if root_cause:
            updated["初步方向"] = f"历史已确认：{root_cause}"
        if action_taken:
            updated["产品专属下一步"] = f"复查已执行动作：{action_taken}；{next_review or '暂不重复改动，等新数据验证'}"
        updated_rows.append(updated)
    return updated_rows


def _self_optimization_notes(analysis_payload: dict, view: dict[str, object]) -> list[str]:
    return review_view._self_optimization_notes(sys.modules[__name__], analysis_payload, view)


def _build_today_task_queue(analysis_payload: dict, status: dict[str, object], search_term_queue: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    marketplace = _infer_marketplace(analysis_payload)
    if not status.get("strong_recommendation_allowed"):
        return [
                {
                    "marketplace": marketplace,
                    "product_name": "全站点",
                    "sku": "N/A",
                    "asin": "N/A",
                    "confirmed_status": "待确认",
                    "priority": "P0",
                    "issue_type": "数据质量问题",
                "primary_reason": str(status.get("issue_summary") or "数据不足"),
                "key_evidence": "ERP 历史数据不足，暂不输出细分运营动作",
                "today_action": "补导数据",
                "action_group": "广告动作",
                "tomorrow_check": "补齐至少 7 天 ERP 数据后重新运行报告",
                "source_section": "数据质量",
            }
        ]

    tasks: dict[tuple[str, str, str], dict[str, str]] = {}
    diagnosis_rows = _diagnosis_view_rows(analysis_payload)
    for view_key, issue_type in [
        ("recent_conversion_cliff_diagnosis_rows", "近期转化断崖诊断"),
        ("ad_no_conversion_diagnosis_rows", "广告消耗无转化诊断"),
        ("ad_attribution_weak_diagnosis_rows", "广告归因弱诊断"),
        ("listing_price_diagnosis_rows", LISTING_REVIEW_LABEL),
        ("cost_profit_diagnosis_rows", "成本 / 利润压力诊断"),
        ("true_unsold_diagnosis_rows", "真无单 / 滞销诊断"),
    ]:
        for row in diagnosis_rows.get(view_key, []):
            action = _specific_today_action(issue_type, row.get("主因"), row.get("建议动作"))
            _merge_task(
                tasks,
                {
                    "marketplace": marketplace,
                    "product_name": row.get("产品") or "N/A",
                    "sku": row.get("SKU") or "N/A",
                    "asin": row.get("ASIN") or "N/A",
                    "confirmed_status": row.get("confirmed_status") or "待确认",
                    "priority": row.get("priority") or ("P0" if issue_type in {"近期转化断崖诊断", "广告消耗无转化诊断", "成本 / 利润压力诊断"} else "P1"),
                    "issue_type": issue_type,
                    "primary_reason": row.get("主因") or "N/A",
                    "key_evidence": row.get("关键证据") or "N/A",
                    "today_action": action,
                    "action_group": _action_group_for(action, issue_type),
                    "tomorrow_check": "复查点击、花费、订单、转化和利润约束是否改善",
                    "source_section": row.get("source_section") or issue_type,
                    "selling_price": row.get("selling_price"),
                    "purchase_cost": row.get("purchase_cost"),
                    "first_leg_cost": row.get("first_leg_cost"),
                    "fba_fee": row.get("fba_fee"),
                    "referral_fee": row.get("referral_fee"),
                    "vat": row.get("vat"),
                    "digital_tax": row.get("digital_tax"),
                    "break_even_acos": row.get("break_even_acos"),
                    "cost_status": row.get("cost_status"),
                    "profit_before_ads_per_unit": row.get("profit_before_ads_per_unit"),
                    "target_acos": row.get("target_acos"),
                    "currency": row.get("currency"),
                },
            )

    for source_key, issue_type, section in [
        ("广告消耗无转化风险", "广告消耗无转化", "广告消耗无转化风险"),
        ("滞销风险", "滞销 / 持续无单", "滞销 / 持续无单风险"),
        ("库存 / 利润压力风险", "库存 / 利润压力", "库存 / 利润压力风险"),
    ]:
        for row in analysis_payload.get(source_key, []):
            priority = "P0" if str(row.get("risk_level") or "") == "严重风险" else "P1"
            evidence = (
                f"{row.get('reason') or 'N/A'}；近14天点击 {_format_count(row.get('recent_14d_clicks'))}；"
                f"近14天花费 {_money(row.get('recent_14d_ad_spend'), row.get('marketplace') or marketplace, row.get('currency'))}"
            )
            _merge_task(
                tasks,
                {
                    "marketplace": row.get("marketplace") or marketplace,
                    "product_name": row.get("product_name") or "N/A",
                    "sku": row.get("sku") or "N/A",
                    "asin": row.get("asin") or "N/A",
                    "confirmed_status": row.get("confirmed_status") or "待确认",
                    "priority": priority,
                    "issue_type": issue_type,
                    "primary_reason": row.get("reason") or row.get("risk_level") or "N/A",
                    "key_evidence": evidence,
                    "today_action": _specific_today_action(issue_type, row.get("reason"), row.get("suggestion")),
                    "action_group": _action_group_for(_specific_today_action(issue_type, row.get("reason"), row.get("suggestion")), issue_type),
                    "tomorrow_check": "复查广告花费、点击、订单和库存/利润变化",
                    "source_section": section,
                    "selling_price": row.get("selling_price"),
                    "purchase_cost": row.get("purchase_cost"),
                    "first_leg_cost": row.get("first_leg_cost"),
                    "fba_fee": row.get("fba_fee"),
                    "referral_fee": row.get("referral_fee"),
                    "vat": row.get("vat"),
                    "digital_tax": row.get("digital_tax"),
                    "break_even_acos": row.get("break_even_acos"),
                    "cost_status": row.get("cost_status"),
                    "profit_before_ads_per_unit": row.get("profit_before_ads_per_unit"),
                    "target_acos": row.get("target_acos"),
                    "currency": row.get("currency"),
                },
            )

    for item in analysis_payload.get(RECOMMENDATION_KEY, []):
        if item.get("category") != "搜索词" or item.get("markdown_section") != "建议否词/暂停":
            continue
        evidence = item.get("evidence", {})
        _merge_task(
            tasks,
            {
                "marketplace": evidence.get("marketplace") or marketplace,
                "product_name": evidence.get("product_name") or evidence.get("sku") or "N/A",
                "sku": evidence.get("sku") or "N/A",
                "asin": evidence.get("asin") or "N/A",
                "confirmed_status": item.get("confirmed_status") or "待确认",
                "priority": "P1",
                "issue_type": "搜索词处理",
                "primary_reason": item.get("note") or item.get("action") or "N/A",
                "key_evidence": f"{item.get('target')}；点击 {_format_count(evidence.get('clicks'))}；花费 {_money(evidence.get('spend'), evidence.get('marketplace') or marketplace, evidence.get('currency'))}",
                "today_action": _specific_today_action("搜索词处理", item.get("note"), item.get("action")),
                "action_group": "广告动作",
                "tomorrow_check": "复查该词/ASIN 是否继续消耗无单",
                "source_section": "搜索词建议",
            },
        )

    grouped_counts = {group: 0 for group in ACTION_GROUPS}
    selected: list[dict[str, str]] = []
    for row in sorted(tasks.values(), key=lambda item: (PRIORITY_ORDER.get(item.get("priority", "P2"), 9), item.get("marketplace", ""), item.get("sku", ""))):
        group = row.get("action_group") or _action_group_for(row.get("today_action"), row.get("issue_type"))
        row["action_group"] = group
        if grouped_counts.get(group, 0) >= 3:
            continue
        grouped_counts[group] = grouped_counts.get(group, 0) + 1
        row["search_term_top5"] = _search_terms_for_task(row, search_term_queue or [])
        selected.append(row)
    return selected


def _group_today_actions(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    return ad_workbench_view._group_today_actions(sys.modules[__name__], rows)


def _build_tomorrow_review_list(
    analysis_payload: dict,
    today_queue: list[dict[str, str]],
    status: dict[str, object],
    blocked_keys: set[tuple[str, str, str]] | None = None,
) -> list[dict[str, str]]:
    return review_view._build_tomorrow_review_list(sys.modules[__name__], analysis_payload, today_queue, status, blocked_keys)


def _cost_issue_lookup(analysis_payload: dict) -> dict[str, dict[str, object]]:
    lookup: dict[str, dict[str, object]] = {}
    for record in analysis_payload.get(PRODUCT_SUMMARY_KEY, {}).get("1d", []):
        sku = str(record.get("sku") or "")
        profit = record.get("profit_before_ads_per_unit")
        target_acos = _target_acos_value(record)
        problems: list[str] = []
        try:
            if profit not in (None, "") and float(profit) < 0:
                problems.append("广告前利润为负")
        except (TypeError, ValueError):
            pass
        if problems:
            lookup[sku] = {
                "profit_before_ads_per_unit": profit,
                "target_acos": target_acos,
                "problems": problems,
            }
    return lookup




def _unsold_risk_view_rows(risk_rows: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in risk_rows:
        marketplace = row.get("marketplace")
        currency = row.get("currency")
        rows.append(
            {
                "风险等级": row.get("risk_level") or "N/A",
                "产品": row.get("product_name") or "N/A",
                "SKU": row.get("sku") or "N/A",
                "ASIN": row.get("asin") or "N/A",
                "库存": _format_count(row.get("available_stock")),
                "近7天订单": _format_count(row.get("recent_7d_total_orders")),
                "近14天订单": _format_count(row.get("recent_14d_total_orders")),
                "连续无单天数": _format_count(row.get("consecutive_no_order_days")),
                "近14天广告花费": _money(row.get("recent_14d_ad_spend"), marketplace, currency),
                "近14天点击": _format_count(row.get("recent_14d_clicks")),
                "建议动作": row.get("suggestion") or "N/A",
                "last_order_date": row.get("last_order_date") or "N/A",
                "recent_30d_total_orders": _format_count(row.get("recent_30d_total_orders")),
                "recent_14d_ad_orders": _format_count(row.get("recent_14d_ad_orders")),
                "recent_14d_natural_orders": _format_count(row.get("recent_14d_natural_orders")),
                "profit_before_ads_per_unit": _money(row.get("profit_before_ads_per_unit"), marketplace, currency),
                "target_acos": _format_percent(row.get("target_acos")),
                "selling_price": _money(row.get("selling_price"), marketplace, currency),
                "purchase_cost": _money(row.get("purchase_cost"), marketplace, currency),
                "first_leg_cost": _money(row.get("first_leg_cost"), marketplace, currency),
                "fba_fee": _money(row.get("fba_fee"), marketplace, currency),
                "referral_fee": _money(row.get("referral_fee"), marketplace, currency),
                "vat": _money(row.get("vat"), marketplace, currency),
                "digital_tax": _money(row.get("digital_tax"), marketplace, currency),
                "break_even_acos": _format_percent(row.get("break_even_acos")),
                "cost_status": row.get("cost_status") or "N/A",
                "reason": row.get("reason") or "N/A",
            }
        )
    return rows


def _quality_rows(analysis_payload: dict, hidden_count: int) -> tuple[list[dict[str, str]], bool]:
    quality_counts = analysis_payload.get("data_quality_issue_summary", {})
    enhanced_status = analysis_payload.get("enhanced_data_status", {})
    cost_missing_total = sum(
        int(quality_counts.get(key, 0) or 0)
        for key in ["missing_cost_config", "missing_product_cost", "missing_target_acos", "missing_first_leg_cost"]
    )

    traffic_files = enhanced_status.get("traffic_sales_files", []) or []
    query_files = enhanced_status.get("search_query_files", []) or []
    traffic_status = "未提供"
    query_status = "未提供"
    if traffic_files:
        traffic_status = "已导入（WOW，可比较）" if enhanced_status.get("traffic_sales_comparable") else "已导入（单周期）"
    if query_files:
        query_status = "已导入（WOW，可比较）" if enhanced_status.get("search_query_comparable") else "已导入（单周期）"
    freshness_warning = _enhanced_freshness_warning(analysis_payload)

    status = data_quality_status_from_payload(analysis_payload)
    data_window_ok = bool(status.get("strong_recommendation_allowed"))
    erp_coverage = analysis_payload.get("erp_report_coverage_date_range") or analysis_payload.get("erp_date_range", {})
    erp_observed = analysis_payload.get("erp_observed_sales_date_range") or {}
    erp_zero_fill_note = analysis_payload.get("coverage_warning") or ("ERP 缺失日期已按 0 单补齐" if analysis_payload.get("zero_fill_applied") else "无需补零")
    erp_zero_fill_judgement = "已按 0 单补齐" if analysis_payload.get("zero_fill_applied") else "正常"
    if data_window_ok and analysis_payload.get("zero_fill_applied") and analysis_payload.get("erp_row_count", 0) and int(analysis_payload.get("erp_row_count", 0) or 0) < 7:
        erp_zero_fill_note = f"{erp_zero_fill_note}；当前仅 {int(analysis_payload.get('erp_row_count', 0) or 0)} 个有销量日期，其余日期为真实 0 单"
        erp_zero_fill_judgement = "覆盖完整，可正式分析"
    rows = [
        {
            "项目": "广告日期范围",
            "结果": f"{analysis_payload['ads_date_range']['start']} ~ {analysis_payload['ads_date_range']['end']}",
            "判断": "正常",
        },
        {
            "项目": "ERP 报表覆盖范围",
            "结果": f"{erp_coverage.get('start')} ~ {erp_coverage.get('end')}",
            "判断": "正常",
        },
        {
            "项目": "ERP 实际有销量日期",
            "结果": f"{erp_observed.get('start') or '无'} ~ {erp_observed.get('end') or '无'}",
            "判断": "已观察" if erp_observed.get("end") else "无销量行",
        },
        {
            "项目": "共同日期范围",
            "结果": f"{analysis_payload['common_date_range']['start']} ~ {analysis_payload['common_date_range']['end']}",
            "判断": "使用",
        },
        {
            "项目": "历史天数",
            "结果": str(analysis_payload["history_days"]),
            "判断": "正常" if analysis_payload["history_days"] >= 7 else "不足，仅观察",
        },
        {
            "项目": "ERP 补零说明",
            "结果": erp_zero_fill_note,
            "判断": erp_zero_fill_judgement,
        },
        {
            "项目": "SKU 映射失败",
            "结果": str(int(quality_counts.get("missing_sku_asin_map", 0) or 0)),
            "判断": "正常" if int(quality_counts.get("missing_sku_asin_map", 0) or 0) == 0 else "异常",
        },
        {
            "项目": "成本缺失",
            "结果": str(cost_missing_total),
            "判断": "正常" if cost_missing_total == 0 else "异常",
        },
        {
            "项目": "增强数据是否提供",
            "结果": "是" if boolish_flag(enhanced_status.get("provided")) else "否",
            "判断": "可增强诊断" if boolish_flag(enhanced_status.get("provided")) else "可选",
        },
        {
            "项目": "traffic_sales",
            "结果": traffic_status,
            "判断": "正常" if traffic_files else "缺失",
        },
        {
            "项目": "search_query_performance",
            "结果": query_status,
            "判断": "正常" if query_files else "缺失",
        },
        {
            "项目": "增强数据时效提醒",
            "结果": freshness_warning or "当前参与诊断的增强数据时效可用",
            "判断": "需谨慎" if freshness_warning else "正常",
        },
        {
            "项目": "旧目录增强文件",
            "结果": str(len(enhanced_status.get("legacy_root_files", []) or [])),
            "判断": "建议迁移" if enhanced_status.get("legacy_root_files_detected") else "正常",
        },
        {"项目": "低优先级隐藏项", "结果": str(hidden_count), "判断": "见 Excel"},
    ]
    quality_pass = (
        data_window_ok
        and
        int(quality_counts.get("missing_sku_asin_map", 0) or 0) == 0
        and cost_missing_total == 0
        and int(quality_counts.get("missing_sku", 0) or 0) == 0
    )
    return rows, quality_pass


def _product_rows_for_window(analysis_payload: dict, window: str) -> list[dict]:
    payload = analysis_payload.get(PRODUCT_SUMMARY_KEY, {})
    rows = payload.get(window, []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _metric_sum(rows: list[dict], key: str) -> float:
    return sum(_row_metric(row, key) for row in rows)


def _row_metric(row: dict, key: str) -> float:
    aliases = {
        "ad_clicks": ["ad_clicks", "clicks", "recent_1d_ad_clicks"],
        "ad_spend": ["ad_spend", "spend", "recent_1d_ad_spend"],
        "ad_impressions": ["ad_impressions", "impressions", "recent_1d_ad_impressions"],
        "ad_orders": ["ad_orders", "recent_1d_ad_orders"],
        "ad_sales": ["ad_sales", "recent_1d_ad_sales"],
        "total_orders": ["total_orders", "recent_1d_total_orders"],
        "total_sales": ["total_sales", "recent_1d_total_sales"],
    }
    for candidate in aliases.get(key, [key]):
        value = _to_float(row.get(candidate))
        if value is not None:
            return value
    return 0


def _build_yesterday_attribution_rows(analysis_payload: dict, status: dict[str, object]) -> list[dict[str, str]]:
    return review_view._build_yesterday_attribution_rows(sys.modules[__name__], analysis_payload, status)


def _latest_action_review_rows(marketplace: str | None = None, limit: int = 50) -> list[dict[str, str]]:
    return review_view._latest_action_review_rows(sys.modules[__name__], marketplace, limit)


def _compact_executed_action(action: str) -> str:
    return review_view._compact_executed_action(sys.modules[__name__], action)


def _latest_keyword_action_review_rows(marketplace: str | None = None, limit: int = 50) -> list[dict[str, str]]:
    return review_view._latest_keyword_action_review_rows(sys.modules[__name__], marketplace, limit)


def _product_metric_lookup(analysis_payload: dict, window: str = "14d") -> dict[tuple[str, str, str], dict[str, object]]:
    return operations_view._product_metric_lookup(sys.modules[__name__], analysis_payload, window)


def _product_rows_by_key(rows: list[dict[str, object]]) -> dict[tuple[str, str, str], list[dict[str, object]]]:
    return operations_view._product_rows_by_key(sys.modules[__name__], rows)


def _first_product_row(rows: list[dict[str, object]]) -> dict[str, object]:
    return operations_view._first_product_row(sys.modules[__name__], rows)


def _operation_card_sort_key(row: dict[str, object]) -> tuple[int, str, str]:
    return operations_view._operation_card_sort_key(sys.modules[__name__], row)


def _first_present(row: dict[str, object], *fields: str) -> object:
    return operations_view._first_present(sys.modules[__name__], row, *fields)


def _build_ad_diagnostic_summary(card: dict[str, object]) -> str:
    return operations_view._build_ad_diagnostic_summary(sys.modules[__name__], card)


def _build_operation_main_reason(card: dict[str, object]) -> str:
    return operations_view._build_operation_main_reason(sys.modules[__name__], card)


def _build_frontend_coverage_summary(frontend_rows: list[dict[str, object]]) -> dict[str, object]:
    return frontend_view._build_frontend_coverage_summary(sys.modules[__name__], frontend_rows)


def _build_product_operation_cards(
    analysis_payload: dict,
    *,
    decision_rows: list[dict[str, object]],
    task_rows: list[dict[str, object]],
    search_rows: list[dict[str, object]],
    frontend_rows: list[dict[str, object]],
    inventory_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return operations_view._build_product_operation_cards(
        sys.modules[__name__],
        analysis_payload,
        decision_rows=decision_rows,
        task_rows=task_rows,
        search_rows=search_rows,
        frontend_rows=frontend_rows,
        inventory_rows=inventory_rows,
    )


def build_report_view(analysis_payload: dict) -> dict:
    recommendations = analysis_payload.get(RECOMMENDATION_KEY, [])
    anomalies = analysis_payload.get(ANOMALY_KEY, [])
    validation_messages = [
        str(message)
        for message in analysis_payload.get("data_quality", {}).get("validation_messages", [])
        if "映射失败或成本缺失" not in str(message)
    ]
    section_items = {section: _select_markdown_items(section, recommendations) for section in SECTION_LIMITS}
    risk_source_rows = analysis_payload.get("滞销风险", [])
    risk_summary = analysis_payload.get("滞销风险汇总", {})
    risk_rows = _unsold_risk_view_rows(risk_source_rows)
    ad_no_conversion_rows = _unsold_risk_view_rows(analysis_payload.get("广告消耗无转化风险", []))
    inventory_profit_pressure_rows = _unsold_risk_view_rows(analysis_payload.get("库存 / 利润压力风险", []))
    displayed_count = sum(len(items) for items in section_items.values()) + len(risk_rows)
    full_count = len(recommendations) + len(anomalies) + len(risk_rows)
    hidden_count = max(full_count - displayed_count, 0)
    quality_rows, quality_pass = _quality_rows(analysis_payload, hidden_count)
    marketplace = _infer_marketplace(analysis_payload)
    enhanced_status = analysis_payload.get("enhanced_data_status", {})
    status = data_quality_status_from_payload(analysis_payload)
    yesterday_attribution_rows = _build_yesterday_attribution_rows(analysis_payload, status)
    runtime_policy = build_runtime_policy(OUTPUT_DIR)
    inventory_replenishment_rows = list((analysis_payload.get("inventory_replenishment") or {}).get("rows") or [])

    summary_lines: list[str] = []
    today_items = section_items["今日必须处理"]
    if today_items:
        summary_lines.append(f"今天有 {len(today_items)} 条需要优先处理的问题，主要集中在无转化消耗或 ACOS 偏高对象。")
    else:
        summary_lines.append("今天没有高优先级必须立即处理的问题，当前广告风险整体可控。")

    scale_items = section_items["可以放量"]
    if scale_items:
        top_scale = scale_items[0]
        evidence = top_scale.get("evidence", {})
        product_name = evidence.get("product_name") or top_scale.get("target") or "N/A"
        summary_lines.append(
            f"{product_name} 表现最好，广告销售额 {_money(evidence.get('ad_sales'), evidence.get('marketplace') or marketplace, evidence.get('currency'))}，ACOS {_format_percent(evidence.get('ACOS'))}，低于目标 {_format_percent(evidence.get('target_acos'))}。"
        )
    else:
        summary_lines.append("今天没有明确可放量的产品，建议继续观察样本积累。")

    watch_items = section_items["明天观察"]
    if watch_items:
        names = [
            str(item.get("evidence", {}).get("product_name") or item.get("target") or "")
            for item in watch_items[:3]
        ]
        summary_lines.append(f"需要继续观察的产品主要有：{'、'.join([name for name in names if name])}。")

    if status["analysis_status"] == "数据不足，仅观察":
        summary_lines.append(str(status["issue_summary"]))
    else:
        summary_lines.append(
            "数据质量通过，可以用于运营判断。"
            if quality_pass
            else "数据质量存在问题，本报告需谨慎使用，并优先修复映射或成本配置。"
        )
    if not boolish_flag(enhanced_status.get("provided")):
        summary_lines.append("未提供亚马逊定制分析增强数据，无法进一步拆分流量、转化或搜索查询原因。")
    elif boolish_flag(enhanced_status.get("traffic_sales_recent_exists")) or boolish_flag(enhanced_status.get("search_query_recent_exists")):
        summary_lines.append("已检测到部分增强数据，本报告已补充自然单下降和搜索查询机会诊断。")
    if risk_rows:
        serious_count = sum(1 for row in risk_source_rows if str(row.get("risk_level") or "") == "严重风险")
        summary_lines.append(f"当前有 {len(risk_rows)} 条滞销 / 持续无单风险，其中 {serious_count} 条为严重风险。")

    summary_lines = summary_lines[:5]

    today_rows: list[dict[str, str]] = []
    for item in today_items:
        evidence = item.get("evidence", {})
        today_rows.append(
            {
                "优先级": item.get("level", "N/A"),
                "类型": item.get("category", "N/A"),
                "对象": item.get("target", "N/A"),
                "产品": evidence.get("product_name") or evidence.get("sku") or "N/A",
                "证据": f"点击 {_format_count(evidence.get('clicks'))}，花费 {_money(evidence.get('spend'), evidence.get('marketplace') or marketplace, evidence.get('currency'))}，订单 {_format_count(evidence.get('ad_orders'))}，ACOS {_format_percent(evidence.get('ACOS'))}",
                "建议动作": item.get("action", "N/A"),
            }
        )

    negative_rows: list[dict[str, str]] = []
    for item in section_items["建议否词/暂停"]:
        evidence = item.get("evidence", {})
        negative_rows.append(
            {
                "类型": "ASIN 定向" if evidence.get("is_asin_term") else "关键词",
                "搜索词/ASIN": item.get("target", "N/A"),
                "产品": evidence.get("product_name") or evidence.get("sku") or "N/A",
                "Campaign": evidence.get("campaign_name") or "N/A",
                "点击": _format_count(evidence.get("clicks")),
                "花费": _money(evidence.get("spend"), evidence.get("marketplace") or marketplace, evidence.get("currency")),
                "订单": _format_count(evidence.get("ad_orders")),
                "CVR": _format_percent(evidence.get("CVR")),
                "原因": item.get("note") or "未出单且消耗偏高",
                "建议": item.get("action", "N/A"),
            }
        )

    scale_rows: list[dict[str, str]] = []
    for item in section_items["可以放量"]:
        evidence = item.get("evidence", {})
        clicks = float(evidence.get("clicks", 0) or 0)
        tail = "点击数仍偏小，建议小幅测试。" if clicks < 10 else "表现稳定，可逐步加预算或提竞价。"
        scale_rows.append(
            {
                "产品": evidence.get("product_name") or item.get("target") or "N/A",
                "SKU": evidence.get("sku") or item.get("target") or "N/A",
                "点击": _format_count(evidence.get("clicks")),
                "花费": _money(evidence.get("spend"), evidence.get("marketplace") or marketplace, evidence.get("currency")),
                "订单": _format_count(evidence.get("ad_orders")),
                "销售额": _money(evidence.get("ad_sales"), evidence.get("marketplace") or marketplace, evidence.get("currency")),
                "ACOS": _format_percent(evidence.get("ACOS")),
                "目标 ACOS": _format_percent(evidence.get("target_acos")),
                "建议": f"ACOS {_format_percent(evidence.get('ACOS'))}，低于目标 {_format_percent(evidence.get('target_acos'))}，{tail}",
            }
        )

    cost_issue_lookup = _cost_issue_lookup(analysis_payload)
    cost_rows: list[dict[str, str]] = []
    for sku, issue in cost_issue_lookup.items():
        record = next(
            (row for row in analysis_payload.get(PRODUCT_SUMMARY_KEY, {}).get("1d", []) if str(row.get("sku") or "") == sku),
            {},
        )
        advice = "先核对售价、采购成本、头程成本、FBA费用。"
        if any(problem == "目标 ACOS 为 0%" for problem in issue["problems"]):
            advice = "目标 ACOS 为 0 通常表示广告前利润为负或成本配置异常，不代表建议 ACOS 真的是 0。"
        cost_rows.append(
            {
                "SKU": sku or "N/A",
                "产品": record.get("product_name") or "N/A",
                "广告前利润/件": _money(issue.get("profit_before_ads_per_unit"), marketplace),
                "target_acos": _format_percent(issue.get("target_acos")),
                "问题": "；".join(issue["problems"]),
                "建议": advice,
            }
        )

    watch_rows: list[dict[str, str]] = []
    for item in section_items["明天观察"]:
        evidence = item.get("evidence", {})
        sku = str(evidence.get("sku") or item.get("target") or "")
        cost_issue = cost_issue_lookup.get(sku)
        if all(key in evidence for key in ["recent_period_days", "recent_period_natural_orders", "prior_period_natural_orders"]):
            recent_days = int(float(evidence.get("recent_period_days", 7) or 7))
            recent_natural = float(evidence.get("recent_period_natural_orders", 0) or 0)
            prior_natural = float(evidence.get("prior_period_natural_orders", 0) or 0)
            drop_abs = float(evidence.get("natural_order_drop_abs", max(prior_natural - recent_natural, 0)) or 0)
            drop_pct = evidence.get("natural_order_drop_pct")
            if drop_pct in (None, "") and prior_natural:
                drop_pct = drop_abs / prior_natural
            evidence_text = (
                f"近{recent_days}天自然单 {_format_count(recent_natural)}，前{recent_days}天自然单 {_format_count(prior_natural)}，"
                f"下降 {_format_count(drop_abs)} 单，降幅 {_format_percent(drop_pct)}。"
            )
            if cost_issue:
                tomorrow = "先核对售价、采购成本、头程成本、FBA费用。如果利润为负属实，不建议加广告放量，只保留高相关低价精准词，暂停泛词和无转化商品投放。"
            else:
                tomorrow = "先检查价格、Coupon、库存、主图、评价、自然排名是否变化；广告不要盲目加预算；如果核心词/ASIN 曝光不足，可以小幅提高精准词或商品投放竞价 10%-15%，观察 2-3 天。"
            watch_rows.append(
                {
                    "产品": evidence.get("product_name") or item.get("target") or "N/A",
                    "状态": item.get("action", "N/A"),
                    "证据": evidence_text,
                    "明天看什么": tomorrow,
                }
            )
            continue

        fragments: list[str] = []
        if "natural_orders" in evidence:
            fragments.append(f"自然单 {_format_count(evidence.get('natural_orders'))}")
        if "total_orders" in evidence:
            fragments.append(f"总单 {_format_count(evidence.get('total_orders'))}")
        if "ad_orders" in evidence:
            fragments.append(f"广告单 {_format_count(evidence.get('ad_orders'))}")
        if "spend" in evidence:
            fragments.append(f"花费 {_money(evidence.get('spend'), evidence.get('marketplace') or marketplace, evidence.get('currency'))}")
        if "clicks" in evidence:
            fragments.append(f"点击 {_format_count(evidence.get('clicks'))}")
        if not fragments and cost_issue:
            fragments.append(
                f"广告前利润 {_money(cost_issue.get('profit_before_ads_per_unit'), marketplace)}，target_acos {_format_percent(cost_issue.get('target_acos'))}"
            )
        watch_rows.append(
            {
                "产品": evidence.get("product_name") or item.get("target") or "N/A",
                "状态": item.get("action", "N/A"),
                "证据": "，".join(fragments) if fragments else "N/A",
                "明天看什么": (
                    "先核对售价、采购成本、头程成本、FBA费用。如果利润为负属实，不建议加广告放量，先调价或修成本。"
                    if cost_issue
                    else (
                        "检查广告是否开启、预算是否用完、竞价是否过低。"
                        if "广告无流量" in str(item.get("action", ""))
                        else "继续观察是否稳定出单；如核心词/ASIN 曝光不足，可小幅提高精准词或商品投放竞价 10%-15%，观察 2-3 天。"
                    )
                ),
            }
        )

    natural_decline_rows: list[dict[str, str]] = []
    for row in analysis_payload.get("natural_decline_enhanced_diagnostics", []):
        natural_decline_rows.append(
            {
                "SKU": row.get("sku") or "N/A",
                "ASIN": row.get("asin") or "N/A",
                "产品": row.get("product_name") or row.get("sku") or "N/A",
                "证据": (
                    f"近7天推荐报价浏览量 {_format_count(row.get('recent_featured_offer_page_views'))}，前7天 {_format_count(row.get('prior_featured_offer_page_views'))}，"
                    f"流量变化 {_format_percent(row.get('featured_offer_page_views_change_pct'))}；近7天转化率 {_format_percent(row.get('recent_conversion_rate'))}，"
                    f"前7天 {_format_percent(row.get('prior_conversion_rate'))}，转化率变化 {_format_percent(row.get('conversion_rate_change_pct'))}；"
                    f"推荐报价率 {_format_percent(row.get('recent_featured_offer_rate'))}"
                ),
                "最终判断": row.get("diagnosis") or "数据不足",
                "建议": row.get("recommendation") or "N/A",
            }
        )

    query_rows: list[dict[str, str]] = []
    for row in analysis_payload.get("search_query_opportunities", []):
        query_rows.append(
            {
                "类型": row.get("type") or "N/A",
                "搜索查询": row.get("search_query") or "N/A",
                "ASIN": row.get("asin") or "N/A",
                "产品": row.get("product_name") or "N/A",
                "展示": _format_count(row.get("query_impressions")),
                "点击": _format_count(row.get("query_clicks")),
                "加购": _format_count(row.get("query_cart_adds")),
                "购买": _format_count(row.get("query_purchases")),
                "建议": row.get("suggestion") or "N/A",
            }
        )

    search_term_suggestion_rows: list[dict[str, str]] = []
    hidden_low_click_search_terms = 0
    for item in [item for item in recommendations if item.get("category") == "搜索词"]:
        evidence = item.get("evidence", {})
        clicks_value = _to_float(evidence.get("clicks")) or 0
        if clicks_value <= 2:
            hidden_low_click_search_terms += 1
        search_term_suggestion_rows.append(
            {
                "层级": item.get("level", "N/A"),
                "搜索词/ASIN": item.get("target", "N/A"),
                "意图分类": evidence.get("intent") or ("ASIN 定向" if evidence.get("is_asin_term") else "unknown"),
                "Campaign": evidence.get("campaign_name") or "N/A",
                "产品": evidence.get("product_name") or evidence.get("sku") or "N/A",
                "点击": _format_count(evidence.get("clicks")),
                "花费": _money(evidence.get("spend"), evidence.get("marketplace") or marketplace, evidence.get("currency")),
                "订单": _format_count(evidence.get("ad_orders")),
                "建议": item.get("action", "N/A"),
                "原因": item.get("note") or "N/A",
            }
        )
    html_search_term_suggestion_rows = [
        row
        for row in search_term_suggestion_rows
        if not (_to_float(row.get("点击")) is not None and (_to_float(row.get("点击")) or 0) <= 2 and str(row.get("订单") or "0") in {"0", "0.0"})
    ]

    def fallback_scale_rows(existing_rows: list[dict[str, str]]) -> list[dict[str, str]]:
        existing_keys = {(str(row.get("SKU") or ""), str(row.get("ASIN") or "")) for row in existing_rows}
        candidates: list[dict[str, str]] = []
        for row in analysis_payload.get(PRODUCT_SUMMARY_KEY, {}).get("14d", []) or []:
            if not isinstance(row, dict):
                continue
            sku = str(row.get("sku") or "")
            asin = str(row.get("asin") or "")
            if (sku, asin) in existing_keys:
                continue
            ad_orders = _to_float(row.get("ad_orders")) or 0
            total_orders = _to_float(row.get("total_orders")) or 0
            clicks = _to_float(row.get("clicks")) or _to_float(row.get("ad_clicks")) or 0
            acos = _to_float(row.get("ACOS"))
            target_acos = _to_float(row.get("target_acos")) or 0.10
            profit = _to_float(row.get("profit_before_ads_per_unit"))
            if (
                ad_orders < 3
                or total_orders < 3
                or clicks < 10
                or acos is None
                or target_acos <= 0
                or acos >= target_acos
                or profit is None
                or profit <= 0
            ):
                continue
            gap = target_acos - acos
            if ad_orders >= 5 and gap >= 0.03:
                action = "可小幅放量：只加出单词/强相关 ASIN，预算或竞价提高 5%-10%，观察 3 天。"
                level = "可小幅放量"
            else:
                action = "谨慎恢复流量：ACOS 低于目标但优势不大，只恢复核心词展示，不做全账户加预算。"
                level = "谨慎放量候选"
            candidates.append(
                {
                    "站点": row.get("marketplace") or marketplace,
                    "产品": row.get("product_name") or sku or "N/A",
                    "SKU": sku or "N/A",
                    "ASIN": asin or "N/A",
                    "点击": _format_count(clicks),
                    "花费": _money(row.get("spend") or row.get("ad_spend"), row.get("marketplace") or marketplace, row.get("currency")),
                    "订单": _format_count(ad_orders),
                    "总单": _format_count(total_orders),
                    "ACOS": _format_percent(acos),
                    "目标 ACOS": _format_percent(target_acos),
                    "放量等级": level,
                    "建议": action,
                }
            )
        return sorted(
            candidates,
            key=lambda row: (
                0 if row.get("放量等级") == "可小幅放量" else 1,
                -(_to_float(row.get("订单")) or 0),
                str(row.get("产品") or ""),
            ),
        )

    no_order_diagnosis_rows: list[dict[str, str]] = []
    for row in analysis_payload.get("无单原因诊断", []):
        no_order_diagnosis_rows.append(
            {
                "产品": row.get("product_name") or "N/A",
                "SKU": row.get("sku") or "N/A",
                "ASIN": row.get("asin") or "N/A",
                "主因": row.get("primary_reason") or "N/A",
                "次要原因": row.get("secondary_reasons") or "N/A",
                "关键证据": row.get("evidence") or "N/A",
                "建议动作": row.get("recommended_action") or "N/A",
            }
        )

    search_term_processing_queue_rows = _apply_manual_feedback_to_search_queue(
        _build_search_term_processing_queue(analysis_payload)
    )
    scale_rows.extend(fallback_scale_rows(scale_rows))
    scale_keyword_rows = _build_scale_keyword_rows(analysis_payload, scale_rows, marketplace)
    search_term_processing_queue_rows = _apply_ad_memory_hard_gate(search_term_processing_queue_rows, runtime_policy)
    scale_keyword_rows = _apply_ad_memory_hard_gate(scale_keyword_rows, runtime_policy)
    html_search_term_processing_queue_rows = [row for row in search_term_processing_queue_rows if row.get("html_visible") != "否"]
    today_task_queue_rows_raw = _apply_manual_feedback_to_rows(
        _build_today_task_queue(analysis_payload, status, search_term_processing_queue_rows)
    )
    today_task_queue_rows, cooled_review_rows = _apply_runtime_policy_to_today_queue(
        today_task_queue_rows_raw,
        runtime_policy,
    )
    today_action_groups = _group_today_actions(today_task_queue_rows)
    cooled_review_keys = {_task_key(row) for row in cooled_review_rows}
    tomorrow_review_rows = cooled_review_rows + _build_tomorrow_review_list(
        analysis_payload,
        today_task_queue_rows,
        status,
        blocked_keys=cooled_review_keys,
    )
    diagnosis_rows = _diagnosis_view_rows(analysis_payload)
    diagnosis_rows["listing_price_diagnosis_rows"] = _rewrite_listing_review_copy(
        diagnosis_rows.get("listing_price_diagnosis_rows", []),
        search_term_processing_queue_rows,
        analysis_payload,
    )
    diagnosis_rows["listing_price_diagnosis_rows"] = [
        {**row, "marketplace": str(row.get("marketplace") or marketplace or "").upper()}
        for row in diagnosis_rows.get("listing_price_diagnosis_rows", [])
    ]
    diagnosis_rows["listing_price_diagnosis_rows"] = _apply_manual_feedback_to_rows(
        diagnosis_rows.get("listing_price_diagnosis_rows", [])
    )
    diagnosis_rows["listing_price_diagnosis_rows"] = _apply_product_lessons_to_listing_rows(
        diagnosis_rows.get("listing_price_diagnosis_rows", []),
        runtime_policy,
        marketplace,
    )
    frontend_check_queue_rows = _build_frontend_check_queue(
        today_task_queue_rows,
        diagnosis_rows.get("listing_price_diagnosis_rows", []),
        marketplace,
    )
    product_final_decision_rows = build_product_final_decisions(
        analysis_payload,
        today_rows=today_task_queue_rows,
        search_rows=search_term_processing_queue_rows,
        scale_rows=scale_keyword_rows,
        inventory_rows=inventory_replenishment_rows,
        frontend_rows=frontend_check_queue_rows,
        runtime_policy=runtime_policy,
    )
    final_decision_summary = decision_summary(product_final_decision_rows)
    search_term_processing_queue_rows = filter_ad_queue_by_decision(search_term_processing_queue_rows, product_final_decision_rows)
    scale_keyword_rows = filter_ad_queue_by_decision(scale_keyword_rows, product_final_decision_rows)
    search_term_processing_queue_rows = _apply_ad_memory_hard_gate(search_term_processing_queue_rows, runtime_policy)
    scale_keyword_rows = _apply_ad_memory_hard_gate(scale_keyword_rows, runtime_policy)
    html_search_term_processing_queue_rows = [row for row in search_term_processing_queue_rows if row.get("html_visible") != "否"]
    today_task_queue_rows = apply_decisions_to_rows(today_task_queue_rows, product_final_decision_rows)
    today_task_queue_rows = _normalize_observation_feedback_statuses(today_task_queue_rows)
    today_action_groups = _group_today_actions(today_task_queue_rows)
    frontend_coverage_summary = _build_frontend_coverage_summary(frontend_check_queue_rows)
    product_operation_cards = _build_product_operation_cards(
        analysis_payload,
        decision_rows=product_final_decision_rows,
        task_rows=today_task_queue_rows,
        search_rows=html_search_term_processing_queue_rows + scale_keyword_rows,
        frontend_rows=frontend_check_queue_rows,
        inventory_rows=inventory_replenishment_rows,
    )
    action_effect_review_rows = _latest_action_review_rows(marketplace)
    keyword_action_effect_review_rows = _latest_keyword_action_review_rows(marketplace, limit=500)
    growth_test_rows = _build_growth_test_rows(
        html_search_term_processing_queue_rows,
        scale_keyword_rows,
        product_operation_cards,
        keyword_action_effect_review_rows,
        runtime_policy,
        report_date=analysis_payload.get("report_date") or datetime.now().date().isoformat(),
    )
    optimization_notes = _self_optimization_notes(
        analysis_payload,
        {
            "hidden_low_click_search_terms": hidden_count,
            "listing_price_diagnosis_rows": diagnosis_rows.get("listing_price_diagnosis_rows", []),
            "risk_rows": risk_rows,
            "today_action_groups": today_action_groups,
            "today_task_queue_rows": today_task_queue_rows,
            "enhanced_status_rows": _enhanced_status_rows(analysis_payload),
            "runtime_policy": runtime_policy,
        },
    )

    return {
        "marketplace": marketplace,
        "analysis_status": status["analysis_status"],
        "issue_summary": status["issue_summary"],
        "strong_recommendation_allowed": status["strong_recommendation_allowed"],
        "summary_lines": summary_lines,
        "data_quality_rows": quality_rows,
        "yesterday_attribution_rows": yesterday_attribution_rows,
        "action_effect_review_rows": action_effect_review_rows,
        "keyword_action_effect_review_rows": keyword_action_effect_review_rows,
        "quality_pass": quality_pass,
        "enhanced_status_rows": _enhanced_status_rows(analysis_payload),
        "enhanced_request_rows": _enhanced_required_request_rows(analysis_payload),
        "sections": section_items,
        "today_rows": today_rows,
        "negative_rows": negative_rows,
        "scale_rows": scale_rows,
        "scale_keyword_rows": scale_keyword_rows,
        "growth_test_rows": growth_test_rows,
        "watch_rows": watch_rows,
        "risk_rows": risk_rows,
        "ad_no_conversion_rows": ad_no_conversion_rows,
        "inventory_profit_pressure_rows": inventory_profit_pressure_rows,
        "search_term_suggestion_rows": search_term_suggestion_rows,
        "html_search_term_suggestion_rows": html_search_term_suggestion_rows,
        "search_term_processing_queue_rows": search_term_processing_queue_rows,
        "html_search_term_processing_queue_rows": html_search_term_processing_queue_rows,
        "hidden_low_click_search_terms": hidden_low_click_search_terms,
        "no_order_diagnosis_rows": no_order_diagnosis_rows,
        **diagnosis_rows,
        "frontend_check_queue_rows": frontend_check_queue_rows,
        "inventory_replenishment_rows": inventory_replenishment_rows,
        "product_final_decision_rows": product_final_decision_rows,
        "product_operation_cards": product_operation_cards,
        "frontend_coverage_summary": frontend_coverage_summary,
        "final_decision_summary": final_decision_summary.get("final_decision_summary", {}),
        "decision_gate_counts": final_decision_summary.get("decision_gate_counts", {}),
        "today_task_queue_rows": today_task_queue_rows,
        "today_action_groups": today_action_groups,
        "tomorrow_review_rows": tomorrow_review_rows,
        "today_task_queue_rows_raw": today_task_queue_rows_raw,
        "learning_cooldown_review_rows": cooled_review_rows,
        "risk_summary": risk_summary,
        "cost_rows": cost_rows,
        "natural_decline_rows": natural_decline_rows,
        "query_rows": query_rows,
        "displayed_count": displayed_count,
        "full_count": full_count,
        "hidden_count": hidden_count,
        "validation_messages": validation_messages,
        "optimization_notes": optimization_notes,
        "runtime_policy_notes": runtime_policy.get("notes", []) if isinstance(runtime_policy, dict) else [],
    }


def _append_table(lines: list[str], headers: list[str], rows: list[dict[str, str]]) -> None:
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(header, "N/A")) for header in headers) + " |")


def build_recommendations_markdown(analysis_payload: dict) -> str:
    view = build_report_view(analysis_payload)
    quality_counts = analysis_payload.get("data_quality_issue_summary", {})
    enhanced_status = analysis_payload.get("enhanced_data_status", {})
    report_date = analysis_payload.get("report_date", "N/A")

    lines: list[str] = [
        f"# 亚马逊运营日报｜{view['marketplace']}｜{report_date}",
        "",
        "## 1. 今日总判断",
    ]
    today_count = len(view["today_rows"])
    scale_count = len(view["scale_rows"])
    watch_count = len(view["watch_rows"])
    risk_count = len(view["risk_rows"])
    if today_count:
        lines.append(f"- 今天有 {today_count} 条需要优先处理的问题。")
    else:
        lines.append("- 今天没有高优先级必须立即处理的问题。")
    if scale_count:
        lines.append(f"- 当前有 {scale_count} 个可以放量的产品，优先关注表现最好的品类。")
    else:
        lines.append("- 当前没有明确可以放量的产品。")
    if watch_count:
        lines.append(f"- 有 {watch_count} 个产品需要继续观察。")
    if risk_count:
        serious_count = sum(1 for row in analysis_payload.get("滞销风险", []) if str(row.get("risk_level") or "") == "严重风险")
        lines.append(f"- 当前有 {risk_count} 个滞销 / 持续无单风险产品，其中 {serious_count} 个属于严重风险。")
    lines.append("- 数据质量已纳入检查，请结合下方表格一起判断。")

    lines.extend(["", "## 2. 数据质量"])
    _append_table(lines, ["项目", "结果", "判断"], view["data_quality_rows"])
    lines.append("")
    lines.append("✅ 数据质量通过，可以用于运营判断" if view["quality_pass"] else "⚠️ 数据质量存在问题，本报告需谨慎使用")
    for message in view["validation_messages"]:
        lines.append(f"- {message}")
    if any(item.get("evidence", {}).get("TACOS") is None for item in analysis_payload.get(RECOMMENDATION_KEY, [])):
        lines.append("- TACOS=None 表示 ERP 销售额为 0 或未匹配，不参与 TACOS 判断。")
    if any(int(quality_counts.get(key, 0) or 0) for key in ["missing_cost_config", "missing_product_cost", "missing_target_acos", "missing_first_leg_cost"]):
        lines.append("- 成本缺失，不影响广告数据，但影响利润判断。")

    markdown_sections = [
        ("3. 今日必须处理", ["优先级", "类型", "对象", "产品", "证据", "建议动作"], view["today_rows"], "✅ 今日没有高优先级必须处理项"),
        ("4. 滞销 / 持续无单风险", ["风险等级", "产品", "SKU", "ASIN", "库存", "近7天订单", "近14天订单", "连续无单天数", "近14天广告花费", "近14天点击", "建议动作"], view["risk_rows"], "当前没有达到滞销 / 持续无单风险阈值的产品。"),
        ("5. 建议否词 / 暂停", ["类型", "搜索词/ASIN", "产品", "Campaign", "点击", "花费", "订单", "CVR", "原因", "建议"], view["negative_rows"], "当前没有需要进入主报告的否词 / 暂停建议。"),
        ("6. 可以放量", ["产品", "SKU", "点击", "花费", "订单", "销售额", "ACOS", "目标 ACOS", "建议"], view["scale_rows"], "当前没有明确可以放量的产品。"),
        ("7. 明天观察", ["产品", "状态", "证据", "明天看什么"], view["watch_rows"], "当前没有重点观察项。"),
        ("8. 成本/定价异常", ["SKU", "产品", "广告前利润/件", "target_acos", "问题", "建议"], view["cost_rows"], "当前没有需要单独处理的成本/定价异常。"),
    ]
    for title, headers, rows, empty_text in markdown_sections:
        lines.extend(["", f"## {title}"])
        if rows:
            _append_table(lines, headers, rows)
        else:
            lines.append(empty_text)

    lines.extend(["", "## 9. 自然单下降增强诊断"])
    if not analysis_payload.get("natural_decline_enhanced_diagnostics"):
        lines.append("当前没有触发自然单下降增强诊断。")
    elif not enhanced_status.get("provided"):
        lines.append("未提供增强数据，当前只能判断自然单下降，无法拆分流量/转化/推荐报价原因。已生成 enhanced_data_requests.md。")
    else:
        _append_table(lines, ["SKU", "ASIN", "产品", "证据", "最终判断", "建议"], view["natural_decline_rows"])

    lines.extend(["", "## 10. 搜索查询机会"])
    if view["query_rows"]:
        _append_table(lines, ["类型", "搜索查询", "ASIN", "产品", "展示", "点击", "加购", "购买", "建议"], view["query_rows"][:15])
    else:
        lines.append("当前没有可展示的搜索查询机会。")

    lines.extend(["", "## 11. 完整明细"])
    lines.append(f"完整 {view['full_count']} 条异常与低优先级记录已保留在 Excel 明细中。")
    lines.append(f"Markdown 仅展示 {view['displayed_count']} 条高价值建议，避免噪音过多。")
    if enhanced_status.get("provided"):
        lines.append("增强数据已提供，已同步用于自然单下降诊断与搜索查询机会分析。")
    return "\n".join(lines).rstrip() + "\n"


def build_marketplace_overview_block(result: dict) -> tuple[str, str]:
    summary = result["summary"]
    marketplace = result["marketplace"]
    if result.get("has_data"):
        return marketplace, "正式分析"
    if summary["ads_row_count"] > 0 and summary["erp_row_count"] == 0:
        return marketplace, "广告有数据，ERP 无数据"
    if summary["ads_row_count"] == 0 and summary["erp_row_count"] > 0:
        return marketplace, "ERP 有数据，广告无数据"
    return marketplace, "该站点无数据"


def build_marketplace_summary_markdown(results: list[dict], report_date: str) -> str:
    lines = [
        f"# Marketplace Summary｜{report_date}",
        "",
        "| 站点 | 广告行数 | ERP行数 | SKU数 | ASIN数 | 状态 | 说明 |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for result in results:
        summary = result["summary"]
        if result.get("has_data"):
            status = "正式分析"
            note = summary.get("common_date_range", "N/A")
        elif summary["ads_row_count"] > 0 and summary["erp_row_count"] == 0:
            status = "仅广告数据"
            note = "ERP 缺失"
        elif summary["ads_row_count"] == 0 and summary["erp_row_count"] > 0:
            status = "仅 ERP 数据"
            note = "广告缺失"
        else:
            status = "无数据"
            note = "无可分析数据"
        lines.append(
            f"| {summary['marketplace']} | {summary['ads_row_count']} | {summary['erp_row_count']} | {summary['sku_count']} | {summary['asin_count']} | {status} | {note} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def build_all_marketplace_markdown(results: list[dict], report_date: str) -> str:
    lines: list[str] = [f"# 亚马逊运营日报汇总建议｜{report_date}", "", "## 1. 各站点状态摘要"]
    for result in results:
        summary = result["summary"]
        quality = data_quality_status_from_summary(summary, has_data=bool(result.get("has_data")))
        lines.append(f"- {result['marketplace']}：{quality['analysis_status']}；{quality['issue_summary']}")

    def add_top_section(title: str, row_key: str, headers: list[str], limit: int) -> None:
        rows: list[dict[str, str]] = []
        for result in results:
            if not result.get("has_data"):
                continue
            rows.extend(result["report_view"].get(row_key, [])[:limit])
        lines.extend(["", f"## {title}"])
        if rows:
            _append_table(lines, headers, rows[:limit])
        else:
            lines.append("当前没有可展示内容。")

    def add_round_robin_section(title: str, row_key: str, headers: list[str], limit: int) -> None:
        rows: list[dict[str, str]] = []
        views = [result["report_view"].get(row_key, []) for result in results if result.get("has_data")]
        index = 0
        while len(rows) < limit:
            added = False
            for view_rows in views:
                if index < len(view_rows):
                    rows.append(view_rows[index])
                    added = True
                    if len(rows) >= limit:
                        break
            if not added:
                break
            index += 1
        lines.extend(["", f"## {title}"])
        if rows:
            _append_table(lines, headers, rows[:limit])
        else:
            lines.append("当前没有可展示内容。")

    def add_action_groups() -> None:
        headers = [
            "marketplace",
            "product_name",
            "sku",
            "asin",
            "priority",
            "issue_type",
            "primary_reason",
            "key_evidence",
            "today_action",
            "tomorrow_check",
            "source_section",
        ]
        lines.extend(["", "## 2. 今日动作清单"])
        any_rows = False
        for group in ["广告动作", "Listing / 价格动作", "成本 / 利润动作"]:
            rows: list[dict[str, str]] = []
            per_market = [
                result["report_view"].get("today_action_groups", {}).get(group, [])
                for result in results
                if result.get("has_data")
            ]
            index = 0
            while len(rows) < 3:
                added = False
                for view_rows in per_market:
                    if index < len(view_rows):
                        rows.append(view_rows[index])
                        added = True
                        if len(rows) >= 3:
                            break
                if not added:
                    break
                index += 1
            lines.extend(["", f"### {group}"])
            if rows:
                any_rows = True
                _append_table(lines, headers, rows)
            else:
                lines.append("当前没有可展示内容。")
        if not any_rows:
            lines.append("当前没有必须处理项。")

    review_headers = ["marketplace", "product_name", "sku", "asin", "review_reason", "current_evidence", "tomorrow_check", "trigger_action"]
    diagnosis_headers = ["产品", "SKU", "ASIN", "诊断类型", "主因", "关键证据", "建议动作"]
    risk_headers = [
        "风险等级",
        "产品",
        "SKU",
        "ASIN",
        "库存",
        "近7天订单",
        "近14天订单",
        "连续无单天数",
        "近14天广告花费",
        "近14天点击",
        "建议动作",
        "last_order_date",
        "recent_30d_total_orders",
        "recent_14d_ad_orders",
        "recent_14d_natural_orders",
        "profit_before_ads_per_unit",
        "target_acos",
        "reason",
    ]
    add_action_groups()
    add_round_robin_section("3. 明日复查清单 Top 3", "tomorrow_review_rows", review_headers, 3)
    add_top_section("4. 真无单 / 滞销诊断 Top 5", "true_unsold_diagnosis_rows", diagnosis_headers, 5)
    add_top_section("5. 广告消耗无转化诊断 Top 5", "ad_no_conversion_diagnosis_rows", diagnosis_headers, 5)
    add_top_section("6. 广告归因弱诊断 Top 5", "ad_attribution_weak_diagnosis_rows", diagnosis_headers, 5)
    add_top_section("7. Listing 待人工确认 Top 5", "listing_price_diagnosis_rows", diagnosis_headers, 5)
    add_top_section("8. 成本 / 利润压力诊断 Top 5", "cost_profit_diagnosis_rows", diagnosis_headers, 5)
    add_top_section("9. 广告消耗无转化风险 Top 5", "ad_no_conversion_rows", risk_headers, 5)
    add_top_section("10. 滞销 / 持续无单风险 Top 5", "risk_rows", risk_headers, 5)
    add_top_section("11. 库存 / 利润压力风险 Top 5", "inventory_profit_pressure_rows", risk_headers, 5)
    add_round_robin_section(
        "12. 搜索词建议 Top 10",
        "html_search_term_suggestion_rows",
        ["层级", "搜索词/ASIN", "意图分类", "Campaign", "产品", "点击", "花费", "订单", "建议", "原因"],
        10,
    )

    lines.extend(["", "## 13. 增强数据状态 / 请求"])
    status_rows: list[dict[str, str]] = []
    for result in results:
        if not result.get("has_data"):
            continue
        for row in result["report_view"].get("enhanced_status_rows", []):
            status_rows.append({"站点": result["marketplace"], **row})
    if status_rows:
        _append_table(lines, ["站点", "报表类型", "状态", "周期类型", "日期范围", "文件名", "是否可比较", "诊断使用类型", "是否参与诊断", "识别来源", "新鲜度"], status_rows)

    request_rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for result in results:
        for row in result.get("analysis_payload", {}).get("enhanced_data_requests", []):
            if not required_flag(row.get("required")) or str(row.get("status") or "").strip() == "已导入":
                continue
            key = (
                str(row.get("marketplace") or result["marketplace"]),
                str(row.get("report_type") or ""),
                str(row.get("period") or ""),
                str(row.get("expected_filename") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            request_rows.append(
                {
                    "站点": row.get("marketplace") or result["marketplace"],
                    "报表类型": row.get("report_type") or "N/A",
                    "周期": row.get("period") or "N/A",
                    "导出文件名": row.get("expected_filename") or "N/A",
                    "目标文件夹": row.get("target_folder") or row.get("target_path") or "N/A",
                    "必需": "是",
                }
            )
    if request_rows:
        _append_table(lines, ["站点", "报表类型", "周期", "导出文件名", "目标文件夹", "必需"], request_rows)
    else:
        lines.append("当前没有真正缺失且必需的增强数据请求。")

    return "\n".join(lines).rstrip() + "\n"


def build_all_enhanced_requests_markdown(results: list[dict], report_date: str) -> str:
    lines = [
        f"# 需要补充导出的增强数据｜{report_date}",
        "",
        "请把文件放入对应站点文件夹，而不是直接放在 raw_amazon_custom 根目录。",
        "",
    ]
    all_rows: list[dict] = []
    seen: set[tuple[object, ...]] = set()
    for result in results:
        for row in result.get("analysis_payload", {}).get("enhanced_data_requests", []):
            key = (
                row.get("marketplace"),
                row.get("report_type"),
                row.get("period"),
                row.get("expected_filename"),
            )
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(row)
    if not all_rows:
        lines.append("当前没有需要额外导出的增强数据请求。")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend([
        "| 站点 | 状态 | 报表类型 | 周期 | 日期范围 | 导出后文件名 | 目标文件夹 | 必需 |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for row in all_rows:
        required_value = str(row.get("required") or "").strip().lower()
        required_text = "是" if required_value in {"1", "true", "yes", "是"} else "否"
        target_folder = row.get("target_folder") or row.get("target_path") or "N/A"
        lines.append(
            f"| {row.get('marketplace') or 'N/A'} | {row.get('status') or 'N/A'} | {row.get('report_type') or 'N/A'} | {row.get('period') or 'N/A'} | "
            f"{row.get('start_date') or 'N/A'} ~ {row.get('end_date') or 'N/A'} | {row.get('expected_filename') or 'N/A'} | {target_folder} | {required_text} |"
        )
    return "\n".join(lines).rstrip() + "\n"
