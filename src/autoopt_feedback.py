from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
import re

import pandas as pd

from .product_decision_layer import decision_summary, write_product_final_decisions

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
FEEDBACK_INPUT_PATH = OUTPUT_DIR / "autoopt_feedback_input.json"
DEFAULT_REVIEW_TARGET_ACOS = 0.10


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _iso_day_text(value: object) -> str:
    if isinstance(value, dict):
        start = value.get("start")
        end = value.get("end")
        if start and end:
            return f"{start} ~ {end}"
    if value:
        return str(value)
    return datetime.now().date().isoformat()


def _normalize_status(value: object, default: str = "待确认") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if text in {"已执行", "已核查", "已忽略", "仅背景参考", "待确认", "待复查"}:
        return text
    lower = text.lower()
    if lower in {"executed", "done", "confirmed"}:
        return "已执行"
    if lower in {"ignored", "skip", "skipped"}:
        return "已忽略"
    if lower in {"background", "reference"}:
        return "仅背景参考"
    return text


def _task_key(row: dict[str, object]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("marketplace") or "").upper(),
        str(row.get("sku") or "").strip(),
        str(row.get("asin") or "").strip(),
        str(row.get("diagnosis_type") or row.get("issue_type") or "").strip(),
        str(row.get("today_action") or "").strip(),
    )


def _product_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or "").upper(),
        str(row.get("sku") or "").strip(),
        str(row.get("asin") or "").strip(),
    )


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


ACTIONABLE_NORMALIZED_ACTIONS = {"bid_up", "bid_down", "negative_exact", "pause", "create_exact", "growth_test"}


def normalize_ad_action(value: object) -> str:
    text = _clean_text(value).lower().replace(" ", "").replace("_", "").replace("-", "")
    if not text:
        return "observe"
    if any(token in text for token in ["growthtest", "推广实验", "推广测试", "小预算推广", "小预算试投"]):
        return "growth_test"
    if "保守跑" in text and "观察" in text:
        return "observe"
    if any(token in text for token in ["否定精准", "否词", "negativeexact"]):
        return "negative_exact"
    if any(token in text for token in ["暂停", "关闭", "pause"]):
        return "pause"
    if any(token in text for token in ["拉精准", "新建精准", "createexact"]):
        return "create_exact"
    if any(token in text for token in ["降竞价", "降bid", "降低竞价", "biddown"]):
        return "bid_down"
    if any(token in text for token in ["加价", "提高竞价", "提高bid", "bidup"]):
        return "bid_up"
    if any(token in text for token in ["保留", "观察", "无需操作", "observe"]):
        return "observe"
    return "observe"


def action_scope_for(row: dict[str, object]) -> str:
    term = _clean_text(row.get("search_term_or_target") or row.get("search_term") or row.get("targeting"))
    if term:
        return "asin_target" if re.match(r"^B0[A-Z0-9]{8,}$", term, re.IGNORECASE) else "search_term"
    if _clean_text(row.get("campaign") or row.get("campaign_name")) and not _clean_text(row.get("asin")):
        return "campaign"
    return "product"


def make_action_id(row: dict[str, object], action: object | None = None, scope: str | None = None) -> str:
    normalized_action = normalize_ad_action(
        action
        if action is not None
        else row.get("normalized_action")
        or row.get("suggested_action")
        or row.get("today_action")
        or row.get("scale_action")
        or row.get("copy_action_line")
        or row.get("manual_action_taken")
    )
    action_scope = scope or _clean_text(row.get("action_scope")) or action_scope_for(row)
    term = _clean_text(row.get("search_term_or_target") or row.get("search_term") or row.get("targeting")).lower()
    parts = [
        _clean_text(row.get("marketplace")).upper(),
        _clean_text(row.get("sku")),
        _clean_text(row.get("asin")).upper(),
        action_scope,
        term,
        normalized_action,
    ]
    return "||".join(parts)


def add_action_identity(row: dict[str, object], action: object | None = None, scope: str | None = None) -> dict[str, object]:
    updated = dict(row)
    normalized_action = normalize_ad_action(
        action
        if action is not None
        else updated.get("normalized_action")
        or updated.get("suggested_action")
        or updated.get("today_action")
        or updated.get("scale_action")
        or updated.get("copy_action_line")
        or updated.get("manual_action_taken")
    )
    updated["normalized_action"] = normalized_action
    updated["action_scope"] = scope or _clean_text(updated.get("action_scope")) or action_scope_for(updated)
    updated["action_id"] = make_action_id(updated, normalized_action, updated["action_scope"])
    return updated


def is_executable_action(row: dict[str, object]) -> bool:
    normalized = _clean_text(row.get("normalized_action")) or normalize_ad_action(
        row.get("suggested_action") or row.get("today_action") or row.get("scale_action") or row.get("copy_action_line")
    )
    return normalized in ACTIONABLE_NORMALIZED_ACTIONS


def _normalize_label_text(value: object) -> str:
    return _clean_text(value).replace("搜索词处理队列", "广告处理队列").replace("搜索词处理", "广告处理")


def _source_file_text(analysis_payload: dict) -> str:
    source_files = analysis_payload.get("source_files", {}) or {}
    candidates = [
        source_files.get("ads_raw"),
        source_files.get("erp_raw"),
        source_files.get("ads_report"),
        source_files.get("erp_report"),
    ]
    candidates = [str(item) for item in candidates if item]
    if candidates:
        return "；".join(dict.fromkeys(candidates[:3]))
    return "N/A"


def _file_period_text(analysis_payload: dict) -> str:
    common = analysis_payload.get("common_date_range", {}) or {}
    start = common.get("start")
    end = common.get("end")
    if start and end:
        return f"{start} ~ {end}"
    return str(analysis_payload.get("report_date") or datetime.now().date().isoformat())


def _build_action_rows_from_view(analysis_payload: dict, report_view: dict, marketplace: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    aggregated: dict[tuple[str, str, str], dict[str, object]] = {}
    file_period = _file_period_text(analysis_payload)
    source_file = _source_file_text(analysis_payload)
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}

    def ensure_row(base: dict[str, str]) -> dict[str, object]:
        key = _product_key(base)
        current = aggregated.get(key)
        if current is None:
            current = {
                "marketplace": base["marketplace"],
                "sku": base["sku"],
                "asin": base["asin"],
                "product_name": base.get("product_name", "N/A"),
                "diagnosis_types": [],
                "today_actions": [],
                "confirmed_statuses": [],
                "priority": base.get("priority", "P2"),
                "primary_reasons": [],
                "key_evidence": [],
                "source_sections": [],
                "source_file": base["source_file"],
                "file_period": base["file_period"],
                "search_terms": [],
                "search_term_actions": [],
            }
            aggregated[key] = current
        return current

    def append_unique(container: list[str], value: object) -> None:
        text = _clean_text(value)
        if text and text not in container:
            container.append(text)

    for row in report_view.get("today_task_queue_rows", []) or []:
        confirmed_status = _normalize_status(row.get("confirmed_status"), default="待确认")
        base = {
            "marketplace": _clean_text(row.get("marketplace") or marketplace),
            "sku": _clean_text(row.get("sku") or "N/A"),
            "asin": _clean_text(row.get("asin") or "N/A"),
            "today_action": _clean_text(row.get("today_action") or "N/A"),
            "diagnosis_type": _clean_text(row.get("issue_type") or "N/A"),
            "confirmed_status": confirmed_status,
            "file_period": file_period,
            "source_file": source_file,
            "priority": _clean_text(row.get("priority") or "N/A"),
            "primary_reason": _clean_text(row.get("primary_reason") or "N/A"),
            "key_evidence": _clean_text(row.get("key_evidence") or "N/A"),
            "source_section": _clean_text(row.get("source_section") or "N/A"),
            "product_name": _clean_text(row.get("product_name") or "N/A"),
        }
        base.update(add_action_identity(base, base["today_action"], "product"))
        current = ensure_row(base)
        append_unique(current["diagnosis_types"], base["diagnosis_type"])
        append_unique(current["today_actions"], base["today_action"])
        append_unique(current["confirmed_statuses"], confirmed_status)
        append_unique(current["primary_reasons"], base["primary_reason"])
        append_unique(current["key_evidence"], base["key_evidence"])
        append_unique(current["source_sections"], base["source_section"])
        if priority_rank.get(base["priority"], 9) < priority_rank.get(current["priority"], 9):
            current["priority"] = base["priority"]
        if confirmed_status == "已执行":
            current["confirmed_status"] = "已执行"
        elif current.get("confirmed_status") != "已执行" and confirmed_status == "已忽略":
            current["confirmed_status"] = "已忽略"

    for row in report_view.get("search_term_processing_queue_rows", []) or []:
        clicks = _clean_text(row.get("clicks") or "0")
        spend = _clean_text(row.get("spend") or "0")
        orders = _clean_text(row.get("orders") or "0")
        suggested_action = _clean_text(row.get("suggested_action") or "观察")
        confirmed_status = "仅背景参考" if suggested_action == "观察" or _clean_text(row.get("html_visible")) == "否" else "待确认"
        base = {
            "marketplace": _clean_text(row.get("marketplace") or marketplace),
            "sku": _clean_text(row.get("sku") or "N/A"),
            "asin": _clean_text(row.get("asin") or "N/A"),
            "today_action": suggested_action,
            "diagnosis_type": "搜索词处理",
            "confirmed_status": confirmed_status,
            "file_period": file_period,
            "source_file": source_file,
            "priority": "P1" if suggested_action != "观察" else "P2",
            "primary_reason": _clean_text(row.get("reason") or "N/A"),
            "key_evidence": f"{_clean_text(row.get('search_term_or_target') or 'N/A')}｜点击{clicks}｜花费{spend}｜订单{orders}",
            "source_section": "广告处理队列",
            "product_name": _clean_text(row.get("product_name") or "N/A"),
            "search_term_or_target": _clean_text(row.get("search_term_or_target") or "N/A"),
        }
        base.update(add_action_identity(base, suggested_action))
        current = ensure_row(base)
        append_unique(current["diagnosis_types"], base["diagnosis_type"])
        append_unique(current["today_actions"], base["today_action"])
        append_unique(current["confirmed_statuses"], confirmed_status)
        append_unique(current["primary_reasons"], base["primary_reason"])
        append_unique(current["source_sections"], base["source_section"])
        append_unique(current["search_terms"], _clean_text(row.get("search_term_or_target") or "N/A"))
        append_unique(
            current["search_term_actions"],
            f"{_clean_text(row.get('search_term_or_target') or 'N/A')}｜{suggested_action}｜{_clean_text(row.get('reason') or 'N/A')}",
        )
        append_unique(current["key_evidence"], base["key_evidence"])
        if priority_rank.get(base["priority"], 9) < priority_rank.get(current["priority"], 9):
            current["priority"] = base["priority"]
        if confirmed_status == "已执行":
            current["confirmed_status"] = "已执行"
        elif current.get("confirmed_status") != "已执行" and confirmed_status == "已忽略":
            current["confirmed_status"] = "已忽略"

    for row in aggregated.values():
        diagnosis_types = [str(item) for item in row.pop("diagnosis_types", []) if item]
        today_actions = [str(item) for item in row.pop("today_actions", []) if item]
        confirmed_statuses = [str(item) for item in row.pop("confirmed_statuses", []) if item]
        primary_reasons = [str(item) for item in row.pop("primary_reasons", []) if item]
        key_evidence = [str(item) for item in row.pop("key_evidence", []) if item]
        source_sections = [str(item) for item in row.pop("source_sections", []) if item]
        search_terms = [str(item) for item in row.pop("search_terms", []) if item]
        search_term_actions = [str(item) for item in row.pop("search_term_actions", []) if item]
        row["diagnosis_type"] = " / ".join(diagnosis_types[:4]) or "N/A"
        row["today_action"] = "；".join(today_actions[:3]) or "N/A"
        row["confirmed_status"] = "已执行" if "已执行" in confirmed_statuses else ("已忽略" if "已忽略" in confirmed_statuses else ("仅背景参考" if confirmed_statuses and all(status == "仅背景参考" for status in confirmed_statuses) else "待确认"))
        row["primary_reason"] = "；".join(primary_reasons[:3]) or "N/A"
        row["key_evidence"] = "；".join(key_evidence[:3]) or "N/A"
        row["source_section"] = "；".join(dict.fromkeys(source_sections[:3])) or "N/A"
        if search_terms:
            row["search_term_summary"] = "；".join(search_term_actions[:3])
            row["search_term_count"] = str(len(search_terms))
            if row["today_action"] == "N/A" and row["search_term_summary"]:
                row["today_action"] = row["search_term_summary"]
        if len(search_terms) > 3:
            row["search_term_summary_more"] = f"另有 {len(search_terms) - 3} 条搜索词处理记录"
        row.update(add_action_identity(row, row.get("today_action"), "product"))
        if row.get("normalized_action") == "observe" and row.get("confirmed_status") == "已执行":
            row["confirmed_status"] = "仅背景参考"
        rows.append(row)

    rows.sort(key=lambda item: (priority_rank.get(str(item.get("priority") or "P2"), 9), item.get("marketplace", ""), item.get("sku", ""), item.get("asin", "")))
    return rows


def load_feedback_input(output_dir: Path | None = None) -> list[dict[str, object]]:
    path = (output_dir or OUTPUT_DIR) / "autoopt_feedback_input.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [add_action_identity(row) for row in _expand_feedback_rows([row for row in payload if isinstance(row, dict)])]
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [add_action_identity(row) for row in _expand_feedback_rows([row for row in rows if isinstance(row, dict)])]
    return []


def _expand_feedback_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    expanded = list(rows)
    seen = {
        (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
            _clean_text(row.get("search_term_or_target") or "").lower(),
            _clean_text(row.get("today_action") or row.get("manual_action_taken") or ""),
            _clean_text(row.get("confirmed_at") or ""),
        )
        for row in expanded
    }
    for row in rows:
        if _normalize_status(row.get("confirmed_status")) != "已执行":
            continue
        if _clean_text(row.get("search_term_or_target")):
            continue
        text = "；".join(
            part
            for part in [
                _clean_text(row.get("confirmed_note")),
                _clean_text(row.get("manual_action_taken")),
                _clean_text(row.get("today_action")),
            ]
            if part
        )
        for term, action in _extract_term_actions(text):
            key = (
                str(row.get("marketplace") or "").upper(),
                str(row.get("sku") or ""),
                str(row.get("asin") or ""),
                term.lower(),
                action,
                _clean_text(row.get("confirmed_at") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            expanded.append(
                {
                    **row,
                    "diagnosis_type": "搜索词处理",
                    "search_term_or_target": term,
                    "today_action": action,
                    "suggested_action": action,
                    "copy_action_line": f"{term} {action}",
                    "manual_action_taken": action,
                    "confirmed_note": f"由产品级反馈自动拆分：{term} {action}",
                }
            )
    return expanded


def _extract_term_actions(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    results: list[tuple[str, str]] = []
    chunks = [chunk.strip() for chunk in re.split(r"[；;\n,，]", text) if chunk.strip()]
    action_pattern = re.compile(
        r"(?P<term>B0[A-Z0-9]{8}|[A-Za-z][A-Za-z0-9 /&'+.-]{2,}?)\s*"
        r"(?P<action>加价|加|降竞价|降|拉精准小预算|拉精准|否定精准|否词|暂停)"
        r"\s*(?P<amount>\d+\s*%-\s*\d+\s*%|\d+\s*%)?",
        re.IGNORECASE,
    )
    for chunk in chunks:
        for match in action_pattern.finditer(chunk):
            term = _clean_text(match.group("term"))
            verb = _clean_text(match.group("action"))
            amount = _clean_text(match.group("amount"))
            if not term or term.lower() in {"用户反馈", "已执行", "已调整"}:
                continue
            if verb == "加":
                verb = "加价"
            elif verb == "降":
                verb = "降竞价"
            action = f"{verb}{amount}" if amount else verb
            if verb == "拉精准":
                action = "拉精准小预算" if "小预算" in chunk else "拉精准"
            results.append((term, action))
    return results


def apply_feedback_override(rows: list[dict[str, str]], feedback_rows: Iterable[dict[str, object]]) -> list[dict[str, str]]:
    feedback_lookup: dict[tuple[str, str, str, str, str], dict[str, object]] = {}
    loose_lookup: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for row in feedback_rows:
        key = (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip(),
            str(row.get("diagnosis_type") or row.get("issue_type") or "").strip(),
            str(row.get("today_action") or "").strip(),
        )
        feedback_lookup[key] = row
        loose_lookup[key[:4]] = row

    resolved: list[dict[str, str]] = []
    for row in rows:
        key = _task_key(row)
        feedback = feedback_lookup.get(key) or loose_lookup.get(key[:4])
        if feedback:
            row = {
                **row,
                "confirmed_status": _normalize_status(feedback.get("confirmed_status"), default=row.get("confirmed_status", "待确认")),
                "confirmed_note": _clean_text(feedback.get("confirmed_note") or feedback.get("note") or ""),
                "confirmed_at": _clean_text(feedback.get("confirmed_at") or ""),
                "report_date": _clean_text(feedback.get("report_date") or row.get("report_date") or ""),
                "manual_root_cause": _clean_text(feedback.get("manual_root_cause") or ""),
                "manual_action_taken": _clean_text(feedback.get("manual_action_taken") or ""),
            }
        resolved.append(row)
    return resolved


def build_autoopt_rows(analysis_payload: dict, report_view: dict, marketplace: str, output_dir: Path | None = None) -> list[dict[str, str]]:
    rows = _build_action_rows_from_view(analysis_payload, report_view, marketplace)
    feedback_rows = load_feedback_input(output_dir)
    if feedback_rows:
        rows = apply_feedback_override(rows, feedback_rows)
    return rows


def load_autoopt_history(output_dir: Path | None = None, limit: int = 60) -> list[dict[str, object]]:
    directory = output_dir or OUTPUT_DIR
    if not directory.exists():
        return []
    paths = sorted(directory.glob("autoopt_log_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    history: list[dict[str, object]] = []
    for path in paths[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            history.extend([row for row in rows if isinstance(row, dict)])
        elif isinstance(payload, list):
            history.extend([row for row in payload if isinstance(row, dict)])
    return history


def load_action_review_history(output_dir: Path | None = None, limit: int = 30) -> list[dict[str, object]]:
    directory = output_dir or OUTPUT_DIR
    if not directory.exists():
        return []
    rows: list[dict[str, object]] = []
    paths = sorted(directory.glob("action_review_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, list):
            rows.extend([row for row in payload if isinstance(row, dict)])
    return rows


def load_keyword_action_review_history(output_dir: Path | None = None, limit: int = 30) -> list[dict[str, object]]:
    directory = output_dir or OUTPUT_DIR
    if not directory.exists():
        return []
    rows: list[dict[str, object]] = []
    paths = sorted(directory.glob("keyword_action_review_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, list):
            rows.extend([row for row in payload if isinstance(row, dict)])
    return rows


def load_learned_rules_history(output_dir: Path | None = None, limit: int = 30) -> list[dict[str, object]]:
    directory = output_dir or OUTPUT_DIR
    if not directory.exists():
        return []
    rows: list[dict[str, object]] = []
    paths = sorted(directory.glob("learned_rules_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, list):
            rows.extend([row for row in payload if isinstance(row, dict)])
    return rows


OUTCOME_SCORES = {
    "明确改善": 3,
    "有改善迹象": 2,
    "初步有效": 1,
    "待7天确认": 0,
    "待观察": 0,
    "样本不足": 0,
    "数据不足": -1,
    "暂未改善": -2,
    "重复无效": -3,
}

STANDARD_REVIEW_OUTCOME_SCORES: dict[str, int | None] = {
    "not_ready": None,
    "insufficient_sample": 0,
    "effective": 2,
    "ineffective": -2,
    "needs_manual_review": -1,
}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = _clean_text(value).lower()
    return text in {"1", "true", "yes", "y", "是", "已是"}


def _learning_term_key(row: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row.get("marketplace") or "").strip().upper(),
        str(row.get("sku") or "").strip(),
        str(row.get("asin") or "").strip(),
        _clean_text(row.get("search_term_or_target") or row.get("search_term") or "").lower(),
    )


def _learning_product_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or "").strip().upper(),
        str(row.get("sku") or "").strip(),
        str(row.get("asin") or "").strip(),
    )


def _learning_key_text(key: tuple[object, ...]) -> str:
    return "||".join(str(part) for part in key)


def _short_effect_text(row: dict[str, object]) -> str:
    text = _clean_text(row.get("effect_evidence") or row.get("review_status") or "")
    if len(text) > 160:
        return text[:157].rstrip() + "..."
    return text


def _learning_item(row: dict[str, object], scope: str, score: int) -> dict[str, object]:
    term = _clean_text(row.get("search_term_or_target") or "")
    title = f"{row.get('marketplace') or ''}｜{row.get('product_name') or row.get('asin') or ''}"
    if term:
        title = f"{title}｜{term}"
    return {
        "scope": scope,
        "marketplace": str(row.get("marketplace") or ""),
        "sku": str(row.get("sku") or ""),
        "asin": str(row.get("asin") or ""),
        "product_name": str(row.get("product_name") or ""),
        "search_term_or_target": term,
        "action_detail": _clean_text(row.get("action_detail") or row.get("action_type") or ""),
        "outcome": _clean_text(row.get("outcome") or ""),
        "score": score,
        "title": title,
        "effect_evidence": _short_effect_text(row),
        "next_step": _clean_text(row.get("rule_adjustment") or ""),
        "executed_at": _clean_text(row.get("executed_at") or ""),
        "review_window": _clean_text(row.get("review_window") or row.get("review_status") or ""),
        "promoted_conversion_improved": bool(row.get("promoted_conversion_improved")),
        "halo_only_conversion": bool(row.get("halo_only_conversion")),
        "target_sku_not_converted": bool(row.get("target_sku_not_converted")),
        "attribution_effect_status": _clean_text(row.get("attribution_effect_status") or ""),
        "attribution_effect_note": _clean_text(row.get("attribution_effect_note") or ""),
    }


def build_action_learning_policy(
    output_dir: Path | None = None,
    *,
    current_action_reviews: Iterable[dict[str, object]] | None = None,
    current_keyword_reviews: Iterable[dict[str, object]] | None = None,
) -> dict[str, object]:
    action_rows = list(current_action_reviews or []) + load_action_review_history(output_dir, limit=12)
    keyword_rows = list(current_keyword_reviews or []) + load_keyword_action_review_history(output_dir, limit=12)

    product_scores: dict[tuple[str, str, str], int] = defaultdict(int)
    term_scores: dict[tuple[str, str, str, str], int] = defaultdict(int)
    best_product_rows: dict[tuple[str, str, str], dict[str, object]] = {}
    best_term_rows: dict[tuple[str, str, str, str], dict[str, object]] = {}
    positive: list[dict[str, object]] = []
    negative: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []

    seen_product: set[tuple[str, str, str, str]] = set()
    for row in action_rows:
        key = _learning_product_key(row)
        if key == ("", "", ""):
            continue
        outcome = _clean_text(row.get("outcome") or "")
        score = OUTCOME_SCORES.get(outcome, 0)
        fingerprint = (*key, _clean_text(row.get("action_detail") or row.get("action_type") or ""))
        if fingerprint in seen_product:
            continue
        seen_product.add(fingerprint)
        product_scores[key] += score
        best_product_rows.setdefault(key, row)
        item = _learning_item(row, "product", score)
        if score > 0:
            positive.append(item)
        elif score < 0:
            negative.append(item)
        else:
            pending.append(item)

    seen_term: set[tuple[str, str, str, str, str]] = set()
    for row in keyword_rows:
        key = _learning_term_key(row)
        if key == ("", "", "", "") or not key[3]:
            continue
        outcome = _clean_text(row.get("outcome") or "")
        score = OUTCOME_SCORES.get(outcome, 0)
        fingerprint = (*key, _clean_text(row.get("action_detail") or ""))
        if fingerprint in seen_term:
            continue
        seen_term.add(fingerprint)
        term_scores[key] += score
        best_term_rows.setdefault(key, row)
        item = _learning_item(row, "keyword_or_target", score)
        if score > 0:
            positive.append(item)
        elif score < 0:
            negative.append(item)
        else:
            pending.append(item)

    positive = sorted(positive, key=lambda item: (-int(item.get("score") or 0), str(item.get("title") or "")))[:12]
    negative = sorted(negative, key=lambda item: (int(item.get("score") or 0), str(item.get("title") or "")))[:12]
    pending = sorted(pending, key=lambda item: (str(item.get("review_window") or ""), str(item.get("title") or "")))[:16]
    policy_adjustments: list[str] = []
    if positive:
        policy_adjustments.append("有改善迹象的词/产品后续以保留和复查为主，不重复要求同类加价或重做。")
    if negative:
        policy_adjustments.append("暂未改善或数据不足的对象降低推荐优先级，优先补前台/竞品/词证据，不继续加价或扩量。")
    if pending:
        policy_adjustments.append("未满3天或待7天确认的动作进入复盘窗口，冷却期内不重复进入 P0/P1 主动作。")

    return {
        "term_scores": {_learning_key_text(key): score for key, score in term_scores.items()},
        "product_scores": {_learning_key_text(key): score for key, score in product_scores.items()},
        "term_score_rows": {
            _learning_key_text(key): _learning_item(best_term_rows[key], "keyword_or_target", term_scores[key])
            for key in best_term_rows
        },
        "product_score_rows": {
            _learning_key_text(key): _learning_item(best_product_rows[key], "product", product_scores[key])
            for key in best_product_rows
        },
        "action_learning_summary": {
            "positive_count": len(positive),
            "negative_count": len(negative),
            "pending_count": len(pending),
            "term_score_count": len(term_scores),
            "product_score_count": len(product_scores),
        },
        "positive_action_patterns": positive,
        "negative_action_patterns": negative,
        "pending_review_objects": pending,
        "recommendation_policy_adjustments": policy_adjustments,
    }


def _load_latest_json_payload(directory: Path, pattern: str) -> object:
    if not directory.exists():
        return []
    paths = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return []


def _strategy_product_key(row: dict[str, object]) -> str:
    return _learning_key_text(
        (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip().upper(),
        )
    )


def _strategy_term_key(row: dict[str, object]) -> str:
    return _learning_key_text(
        (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip().upper(),
            _clean_text(row.get("search_term_or_target") or row.get("search_term") or row.get("targeting")).lower(),
        )
    )


def _future_policy(normalized_action: str, score: int, outcome: str) -> str:
    if score >= 2 and normalized_action == "bid_up":
        return "keep_current_bid"
    if score >= 1 and normalized_action == "bid_down":
        return "keep_current_bid"
    if score >= 1:
        return "allow_small_exact_test"
    if score <= -2 and normalized_action == "bid_up":
        return "do_not_bid_up_again"
    if score <= -2:
        return "lower_priority_until_new_data"
    if score <= -1:
        return "recheck_frontend_before_action"
    if outcome in {"样本不足", "待观察", "待7天确认"}:
        return "review_after_7_days"
    return "block_duplicate_action"


def _standard_outcome_from_legacy(outcome: str) -> str:
    if outcome in {"明确改善", "有改善迹象", "初步有效"}:
        return "effective"
    if outcome in {"暂未改善", "重复无效"}:
        return "ineffective"
    if outcome in {"数据不足", "样本不足", "待观察"}:
        return "insufficient_sample"
    if outcome == "待7天确认":
        return "not_ready"
    return "needs_manual_review" if outcome else "insufficient_sample"


def _review_timing_fields(days_since: int | None) -> dict[str, object]:
    if days_since is None:
        return {
            "cooldown_status": "cooldown_active",
            "review_phase": "missing_execution_date",
            "review_status": "缺执行日期，暂不判断效果",
            "review_outcome": "not_ready",
            "effectiveness_score": None,
            "block_reason": "已执行，冷却中",
        }
    if days_since < 3:
        return {
            "cooldown_status": "cooldown_active",
            "review_phase": "under_3_days",
            "review_status": "未满3天，暂不判断效果",
            "review_outcome": "not_ready",
            "effectiveness_score": None,
            "block_reason": "已执行，冷却中",
        }
    if days_since < 7:
        return {
            "cooldown_status": "review_pending",
            "review_phase": "day_3_check",
            "review_status": "可做3天复查，7天结论待补",
            "review_outcome": "not_ready",
            "effectiveness_score": None,
            "block_reason": "等待7天复盘",
        }
    return {
        "cooldown_status": "review_ready",
        "review_phase": "day_7_review",
        "review_status": "可做7天复盘",
        "block_reason": "",
    }


def _standard_keyword_review_outcome(
    recent7: dict[str, object],
    recent14: dict[str, object],
    days_since: int | None,
) -> tuple[str, int | None, str]:
    timing = _review_timing_fields(days_since)
    if timing.get("review_outcome") == "not_ready":
        return "not_ready", None, str(timing.get("block_reason") or "")
    attr7 = _attribution_effect_flags(recent7)
    clicks7 = _to_number(recent7.get("clicks") or recent7.get("ad_clicks"))
    spend7 = _to_number(recent7.get("spend") or recent7.get("ad_spend"))
    if attr7["halo_only_conversion"]:
        return "needs_manual_review", STANDARD_REVIEW_OUTCOME_SCORES["needs_manual_review"], "只有光环成交，需人工复查"
    if attr7["promoted_conversion_improved"]:
        acos7 = _ratio_number(recent7.get("ACOS") or recent7.get("acos"))
        target_acos = _review_target_acos(recent7)
        if acos7 is None:
            return "needs_manual_review", STANDARD_REVIEW_OUTCOME_SCORES["needs_manual_review"], "本 SKU 有单但 ACOS 缺失，需人工复查"
        if acos7 > target_acos:
            return "needs_manual_review", STANDARD_REVIEW_OUTCOME_SCORES["needs_manual_review"], "本 SKU 有单但 ACOS 高于目标，需人工复查"
        return "effective", STANDARD_REVIEW_OUTCOME_SCORES["effective"], ""
    if not recent7 and not recent14:
        return "insufficient_sample", STANDARD_REVIEW_OUTCOME_SCORES["insufficient_sample"], ""
    if clicks7 >= 8 or spend7 >= 5:
        return "ineffective", STANDARD_REVIEW_OUTCOME_SCORES["ineffective"], "历史效果差，不重复推送"
    return "insufficient_sample", STANDARD_REVIEW_OUTCOME_SCORES["insufficient_sample"], ""


def _cooldown_until(row: dict[str, object]) -> str:
    executed_at = _clean_text(row.get("executed_at") or row.get("confirmed_at") or row.get("report_date") or "")
    if not executed_at:
        return ""
    try:
        day = datetime.fromisoformat(executed_at[:10]).date()
    except Exception:
        return ""
    days_since = _to_number(row.get("days_since_execution"))
    if days_since < 3:
        return (day + timedelta(days=3)).isoformat()
    if days_since < 7:
        return (day + timedelta(days=7)).isoformat()
    return ""


def build_keyword_strategy_memory(
    output_dir: Path | None = None,
    *,
    current_keyword_reviews: Iterable[dict[str, object]] | None = None,
    feedback_rows: Iterable[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    rows = list(current_keyword_reviews or []) + load_keyword_action_review_history(output_dir, limit=20)
    feedback_lookup: dict[str, list[dict[str, object]]] = defaultdict(list)
    for feedback in feedback_rows or []:
        term = _clean_text(feedback.get("search_term_or_target") or "")
        if not term:
            continue
        identified = add_action_identity(feedback)
        feedback_lookup[str(identified.get("action_id") or "")].append(feedback)

    memory_by_action: dict[str, dict[str, object]] = {}
    for row in rows:
        identified = add_action_identity(row, row.get("action_detail") or row.get("manual_action_taken"))
        action_id = str(identified.get("action_id") or "")
        if not action_id:
            continue
        outcome = _clean_text(row.get("outcome") or row.get("judgement") or row.get("review_status") or "待观察")
        review_outcome = _clean_text(row.get("review_outcome") or "") or _standard_outcome_from_legacy(outcome)
        if row.get("effectiveness_score") in (None, ""):
            score = STANDARD_REVIEW_OUTCOME_SCORES.get(review_outcome)
        else:
            score = int(_to_number(row.get("effectiveness_score")))
        halo_only = _truthy(row.get("halo_only_conversion")) or _clean_text(row.get("attribution_effect_status")) == "halo_only_conversion"
        target_not_converted = _truthy(row.get("target_sku_not_converted")) or halo_only
        if halo_only:
            score = min(score if score is not None else 0, 0)
            review_outcome = "needs_manual_review"
        existing = memory_by_action.get(action_id)
        existing_score = existing.get("effectiveness_score") if existing else -99
        if existing and score is not None and existing_score is not None and int(existing_score or 0) >= score:
            history = existing.setdefault("historical_actions", [])
            if isinstance(history, list) and len(history) < 6:
                history.append(_clean_text(row.get("action_detail") or ""))
            continue
        normalized_action = str(identified.get("normalized_action") or normalize_ad_action(row.get("action_detail")))
        policy = _future_policy(normalized_action, int(score or 0), outcome)
        if halo_only:
            policy = "do_not_bid_up_again" if normalized_action == "bid_up" else "lower_priority_until_new_data"
        should_keep = bool(score is not None and score >= 1) or policy == "keep_current_bid"
        should_block = bool(review_outcome == "ineffective" or halo_only or policy in {"do_not_bid_up_again", "keep_current_bid"})
        memory_by_action[action_id] = {
            "action_id": action_id,
            "marketplace": row.get("marketplace") or "",
            "sku": row.get("sku") or "",
            "asin": row.get("asin") or "",
            "product_name": row.get("product_name") or "",
            "search_term_or_target": row.get("search_term_or_target") or "",
            "target_type": identified.get("action_scope") or action_scope_for(row),
            "normalized_action": normalized_action,
            "historical_actions": [_clean_text(row.get("action_detail") or "")],
            "latest_effect_status": outcome,
            "review_outcome": review_outcome,
            "effectiveness_score": score,
            "recommended_future_policy": policy,
            "cooldown_until": _cooldown_until(row),
            "cooldown_status": row.get("cooldown_status") or "",
            "review_phase": row.get("review_phase") or "",
            "review_status": row.get("review_status") or "",
            "block_reason": row.get("block_reason") or "",
            "should_keep": should_keep,
            "should_block_repeating": should_block,
            "should_recheck_frontend": policy == "recheck_frontend_before_action" or review_outcome in {"ineffective", "needs_manual_review"},
            "evidence_summary": _short_effect_text(row),
            "last_seen_date": _clean_text(row.get("review_date") or row.get("executed_at") or row.get("report_date") or ""),
            "promoted_conversion_improved": bool(row.get("promoted_conversion_improved")),
            "halo_only_conversion": halo_only,
            "target_sku_not_converted": target_not_converted,
            "attribution_effect_status": _clean_text(row.get("attribution_effect_status") or ""),
            "attribution_effect_note": _clean_text(row.get("attribution_effect_note") or ""),
        }

    for action_id, feedback_items in feedback_lookup.items():
        if action_id in memory_by_action:
            continue
        feedback = feedback_items[-1]
        identified = add_action_identity(feedback)
        normalized_action = str(identified.get("normalized_action") or "")
        memory_by_action[action_id] = {
            "action_id": action_id,
            "marketplace": feedback.get("marketplace") or "",
            "sku": feedback.get("sku") or "",
            "asin": feedback.get("asin") or "",
            "product_name": feedback.get("product_name") or "",
            "search_term_or_target": feedback.get("search_term_or_target") or "",
            "target_type": identified.get("action_scope") or action_scope_for(feedback),
            "normalized_action": normalized_action,
            "historical_actions": [_clean_text(feedback.get("manual_action_taken") or feedback.get("today_action") or "")],
            "latest_effect_status": "待观察",
            "review_outcome": "not_ready",
            "effectiveness_score": None,
            "recommended_future_policy": "review_after_7_days",
            "cooldown_until": _clean_text(feedback.get("next_review") or ""),
            "cooldown_status": "cooldown_active",
            "review_phase": "under_3_days",
            "review_status": "未满3天，暂不判断效果",
            "block_reason": "已执行，冷却中",
            "should_keep": False,
            "should_block_repeating": False,
            "should_recheck_frontend": False,
            "evidence_summary": _clean_text(feedback.get("confirmed_note") or "已执行，等待3天/7天复盘。"),
            "last_seen_date": _clean_text(feedback.get("confirmed_at") or feedback.get("report_date") or ""),
        }

    return sorted(
        memory_by_action.values(),
        key=lambda item: (
            str(item.get("marketplace") or ""),
            str(item.get("product_name") or ""),
            str(item.get("search_term_or_target") or ""),
            str(item.get("normalized_action") or ""),
        ),
    )


def _collect_product_metric_rows(results: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    collected: dict[str, dict[str, object]] = {}
    for result in results:
        payload = result.get("analysis_payload") or {}
        marketplace = str(result.get("marketplace") or payload.get("target_marketplace") or "").upper()
        metrics = payload.get("product_window_metrics", {}) if isinstance(payload, dict) else {}
        if isinstance(metrics, dict):
            for window in ["30d", "14d", "7d"]:
                for row in metrics.get(window, []) or []:
                    if not isinstance(row, dict):
                        continue
                    enriched = dict(row)
                    enriched.setdefault("marketplace", marketplace)
                    key = _strategy_product_key(enriched)
                    if not key.endswith("||||") and key not in collected:
                        collected[key] = enriched
        inventory = payload.get("inventory_replenishment", {}) if isinstance(payload, dict) else {}
        if isinstance(inventory, dict):
            for row in inventory.get("rows", []) or []:
                if not isinstance(row, dict):
                    continue
                enriched = dict(row)
                enriched.setdefault("marketplace", marketplace)
                key = _strategy_product_key(enriched)
                if key.endswith("||||"):
                    continue
                base = collected.setdefault(key, enriched)
                base.update({f"inventory_{k}": v for k, v in enriched.items()})
    return collected


def build_product_strategy_profiles(
    results: list[dict[str, object]],
    *,
    keyword_memory: Iterable[dict[str, object]] | None = None,
    current_action_reviews: Iterable[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    products = _collect_product_metric_rows(results)
    memory_by_product: dict[str, list[dict[str, object]]] = defaultdict(list)
    for memory in keyword_memory or []:
        memory_by_product[_strategy_product_key(memory)].append(memory)
    for review in current_action_reviews or []:
        products.setdefault(_strategy_product_key(review), dict(review))

    profiles: list[dict[str, object]] = []
    for key, row in products.items():
        marketplace = str(row.get("marketplace") or "").upper()
        tags: list[str] = []
        blocked: set[str] = set()
        allowed: set[str] = {"bid_down", "negative_exact", "pause", "create_exact", "observe"}
        preferred_keywords: set[str] = {"高相关长尾", "精准词"}
        risky_keywords: set[str] = set()
        memories = memory_by_product.get(key, [])
        positive = [m for m in memories if int(m.get("effectiveness_score") or 0) > 0]
        negative = [m for m in memories if int(m.get("effectiveness_score") or 0) < 0]

        clicks14 = _to_number(row.get("ad_clicks") or row.get("clicks"))
        ad_orders14 = _to_number(row.get("ad_orders"))
        total_orders14 = _to_number(row.get("total_orders"))
        reviews = _to_number(row.get("reviews") or row.get("frontend_reviews"))
        rating = _to_number(row.get("rating") or row.get("frontend_rating"))
        stock_status = _clean_text(row.get("inventory_stock_risk_level") or row.get("stock_risk_level") or row.get("inventory_status") or "")
        stock_reason = _clean_text(row.get("inventory_stock_risk_reason") or row.get("stock_risk_reason") or "")

        if clicks14 >= 20 and ad_orders14 == 0:
            tags.extend(["广告有点击无单", "大词承接弱"])
            risky_keywords.add("宽泛大词")
            blocked.update({"bid_up", "budget_up", "broad_scale"})
        if total_orders14 <= 1 and clicks14 >= 10:
            tags.append("转化承接弱")
        if rating and rating < 4.2:
            tags.append("新品低评分" if reviews <= 20 else "评分信任弱")
            blocked.add("broad_scale")
        if reviews and reviews < 50:
            tags.append("评论量弱")
        if any(token in stock_status for token in ["OUT_OF_STOCK", "LOW_STOCK", "断货", "低库存"]):
            tags.append("低库存保守跑")
            blocked.update({"bid_up", "budget_up", "broad_scale"})
        if any(token in stock_status for token in ["RESTOCK_RECOVERY", "刚到货", "恢复"]):
            tags.append("刚到货恢复期")
            blocked.update({"budget_up", "broad_scale"})
        if "Coupon" in stock_reason or "前台" in stock_reason:
            tags.append("前台待确认")
        if positive:
            tags.append("历史动作有效")
        if negative:
            tags.append("历史动作暂未改善")
            blocked.update({"bid_up", "budget_up", "broad_scale"})

        frontend_first = bool({"大词承接弱", "转化承接弱", "前台待确认", "评分信任弱", "新品低评分"} & set(tags))
        if frontend_first:
            blocked.update({"budget_up", "broad_scale"})
        if "低库存保守跑" in tags:
            product_stage = "INVENTORY_LIMITED"
            mode = "inventory_safe_mode"
        elif "刚到货恢复期" in tags:
            product_stage = "RESTOCK_RECOVERY"
            mode = "restock_recovery_mode"
        elif frontend_first:
            product_stage = "NEEDS_MANUAL_CONFIRMATION"
            mode = "frontend_first"
        elif positive and not negative:
            product_stage = "ACTIVE_SCALABLE"
            mode = "scale_carefully"
            allowed.add("bid_up")
        elif negative:
            product_stage = "CONSERVATIVE_RUN"
            mode = "suppress_broad"
        else:
            product_stage = "CONSERVATIVE_RUN"
            mode = "hold_and_review"

        if "宽泛大词" in risky_keywords:
            mode = "suppress_broad" if mode not in {"inventory_safe_mode", "restock_recovery_mode"} else mode
        tag_list = []
        for tag in tags:
            if tag and tag not in tag_list:
                tag_list.append(tag)
        if not tag_list:
            tag_list = ["常规观察"]

        profiles.append(
            {
                "marketplace": marketplace,
                "sku": row.get("sku") or "",
                "asin": row.get("asin") or "",
                "product_name": row.get("product_name") or row.get("product") or "",
                "profile_tags": tag_list,
                "product_stage": product_stage,
                "traffic_posture": "大词需收紧" if "大词承接弱" in tag_list else "常规流量",
                "conversion_posture": "转化弱，先查前台" if frontend_first else "常规转化",
                "inventory_posture": stock_status or "未识别库存限制",
                "frontend_posture": "需先核查价格/Coupon/Buy Box/竞品" if frontend_first else "未要求前台优先",
                "ad_strategy_mode": mode,
                "allowed_actions": sorted(allowed - blocked) or ["observe"],
                "blocked_actions": sorted(blocked),
                "preferred_keyword_types": sorted(preferred_keywords),
                "risky_keyword_types": sorted(risky_keywords) or ["低相关大词"],
                "frontend_check_required_before_action": frontend_first,
                "conservative_reason": "；".join(tag_list[:3]),
                "reusable_success_patterns": [
                    f"{m.get('search_term_or_target')}：{m.get('recommended_future_policy')}" for m in positive[:5]
                ],
                "failed_action_patterns": [
                    f"{m.get('search_term_or_target')}：{m.get('recommended_future_policy')}" for m in negative[:5]
                ],
                "last_updated": datetime.now().date().isoformat(),
            }
        )
    return sorted(profiles, key=lambda item: (str(item.get("marketplace") or ""), str(item.get("product_name") or "")))


def build_recommendation_guard(
    product_profiles: Iterable[dict[str, object]],
    keyword_memory: Iterable[dict[str, object]],
    runtime_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    blocked: list[dict[str, object]] = []
    downgraded: list[dict[str, object]] = []
    allowed: list[dict[str, object]] = []
    reused: list[dict[str, object]] = []
    runtime_policy = runtime_policy or {}
    action_cooldowns = runtime_policy.get("action_cooldowns", {}) if isinstance(runtime_policy, dict) else {}
    if isinstance(action_cooldowns, dict):
        for action_id, cooldown in action_cooldowns.items():
            blocked.append({"action_id": action_id, "reason": "已执行动作冷却中，不进入 P0/P1 或复制区", **(cooldown if isinstance(cooldown, dict) else {})})
    for memory in keyword_memory:
        score = int(memory.get("effectiveness_score") or 0)
        if memory.get("should_block_repeating"):
            blocked.append(
                {
                    "action_id": memory.get("action_id"),
                    "marketplace": memory.get("marketplace"),
                    "product_name": memory.get("product_name"),
                    "search_term_or_target": memory.get("search_term_or_target"),
                    "normalized_action": memory.get("normalized_action"),
                    "reason": memory.get("recommended_future_policy"),
                }
            )
        if score < 0:
            downgraded.append(memory)
        elif score > 0:
            allowed.append(memory)
            reused.append(memory)
    for profile in product_profiles:
        blocked_actions = profile.get("blocked_actions") or []
        if blocked_actions:
            downgraded.append(
                {
                    "marketplace": profile.get("marketplace"),
                    "sku": profile.get("sku"),
                    "asin": profile.get("asin"),
                    "product_name": profile.get("product_name"),
                    "blocked_actions": blocked_actions,
                    "reason": profile.get("conservative_reason"),
                    "ad_strategy_mode": profile.get("ad_strategy_mode"),
                }
            )
    return {
        "recommendation_guard_summary": {
            "blocked_count": len(blocked),
            "downgraded_count": len(downgraded),
            "allowed_with_memory_count": len(allowed),
            "reused_success_pattern_count": len(reused),
            "product_profile_count": len(list(product_profiles)) if not isinstance(product_profiles, list) else len(product_profiles),
            "keyword_memory_count": len(list(keyword_memory)) if not isinstance(keyword_memory, list) else len(keyword_memory),
        },
        "blocked_recommendations": blocked[:80],
        "downgraded_recommendations": downgraded[:80],
        "allowed_recommendations_with_memory": allowed[:80],
        "reused_success_patterns": reused[:40],
        "product_profile_updates": list(product_profiles)[:80] if isinstance(product_profiles, list) else [],
        "keyword_memory_updates": list(keyword_memory)[:80] if isinstance(keyword_memory, list) else [],
    }


def load_manual_learning_history(output_dir: Path | None = None, limit: int = 30) -> list[dict[str, object]]:
    directory = output_dir or OUTPUT_DIR
    if not directory.exists():
        return []
    rows: list[dict[str, object]] = []
    paths = sorted(directory.glob("manual_learning_log_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, list):
            rows.extend([row for row in payload if isinstance(row, dict)])
    return rows


def build_manual_learning_rows(feedback_rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    learned: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in feedback_rows:
        status = _normalize_status(row.get("confirmed_status"))
        if status not in {"已执行", "已核查"}:
            continue
        root_cause = _clean_text(row.get("manual_root_cause") or "")
        action_taken = _clean_text(row.get("manual_action_taken") or "")
        note = _clean_text(row.get("confirmed_note") or row.get("note") or "")
        search_term = _clean_text(row.get("search_term_or_target") or "")
        if not (root_cause or action_taken):
            continue
        key = (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
            search_term.lower(),
            root_cause,
            action_taken,
        )
        if key in seen:
            continue
        seen.add(key)
        learned.append(
            {
                "marketplace": key[0],
                "sku": key[1],
                "asin": key[2],
                "product_name": row.get("product_name") or "",
                "search_term_or_target": search_term,
                "manual_root_cause": root_cause,
                "manual_action_taken": action_taken,
                "confirmed_note": note,
                "confirmed_at": _clean_text(row.get("confirmed_at") or row.get("report_date") or ""),
                "next_review": _clean_text(row.get("next_review") or ("复查该词/ASIN执行后3天和7天点击、花费、订单、ACOS" if search_term else "复查执行后7天点击、订单、ACOS和页面成交率")),
                "learning_type": "词级动作执行" if search_term else "人工确认原因",
            }
        )
    return learned


def _policy_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or "").strip().upper(),
        str(row.get("sku") or "").strip(),
        str(row.get("asin") or "").strip(),
    )


def build_runtime_policy(output_dir: Path | None = None) -> dict[str, object]:
    """Build lightweight policy hints used by the report view.

    This intentionally does not mutate raw data or metric calculation. It only
    tells the presentation layer which already-executed objects should cool down
    before being promoted again.
    """
    directory = output_dir or OUTPUT_DIR
    today = datetime.now().date().isoformat()
    product_cooldowns: dict[tuple[str, str, str], dict[str, object]] = {}
    action_cooldowns: dict[str, dict[str, object]] = {}
    product_lessons: dict[tuple[str, str, str], dict[str, object]] = {}
    notes: list[str] = []
    manual_learning_rows = build_manual_learning_rows(load_feedback_input(output_dir)) + load_manual_learning_history(output_dir, limit=10)
    for lesson in manual_learning_rows:
        key = _policy_key(lesson)
        if key == ("", "", ""):
            continue
        product_lessons[key] = lesson

    for row in load_feedback_input(output_dir):
        if _normalize_status(row.get("confirmed_status")) != "已执行":
            continue
        identified = add_action_identity(row)
        if not is_executable_action(identified):
            continue
        key = _policy_key(row)
        if key == ("", "", ""):
            continue
        is_term_level = bool(_clean_text(row.get("search_term_or_target") or row.get("search_term") or ""))
        confirmed_at = _clean_text(row.get("confirmed_at") or row.get("report_date") or today)
        days_since = _days_between(confirmed_at, today)
        if days_since is not None and days_since < 0:
            days_since = 0
        has_manual_learning = bool(_clean_text(row.get("manual_root_cause")) or _clean_text(row.get("manual_action_taken")))
        cooldown_days = int(_to_number(row.get("cooldown_days")) or (7 if has_manual_learning else 3))
        if days_since is None or days_since <= cooldown_days:
            timing_fields = _review_timing_fields(days_since)
            if days_since is None:
                status = "已执行冷却"
            elif days_since < 3:
                status = "已执行，未满3天，不重复操作"
            elif days_since < 7:
                status = "等待7天复盘"
            else:
                status = "进入7天复盘"
            cooldown = {
                "action_id": identified.get("action_id"),
                "normalized_action": identified.get("normalized_action"),
                "action_scope": identified.get("action_scope"),
                "days_since": "" if days_since is None else days_since,
                "status": status,
                **timing_fields,
                "reason": _clean_text(timing_fields.get("block_reason") or row.get("confirmed_note") or row.get("manual_action_taken") or "已执行，短期不重复推送为今日强动作"),
                "confirmed_at": confirmed_at,
                "cooldown_days": cooldown_days,
                "cooldown_until": _date_after(confirmed_at, cooldown_days),
                "marketplace": row.get("marketplace"),
                "sku": row.get("sku"),
                "asin": row.get("asin"),
                "product_name": row.get("product_name"),
                "search_term_or_target": row.get("search_term_or_target"),
                "manual_action_taken": row.get("manual_action_taken") or row.get("today_action"),
            }
            action_cooldowns[str(identified.get("action_id"))] = cooldown
            if not is_term_level:
                product_cooldowns[key] = cooldown

    for row in load_action_review_history(output_dir, limit=10):
        key = _policy_key(row)
        if key == ("", "", "") or key in product_cooldowns:
            continue
        outcome = _clean_text(row.get("outcome"))
        executed_at = _clean_text(row.get("executed_at") or "")
        if not executed_at:
            continue
        days_since = _days_between(executed_at, today)
        if days_since is None:
            continue
        if days_since < 0:
            days_since = 0
        if outcome in {"样本不足", "待观察", "待7天确认"} and days_since <= 3:
            cooldown = {
                "status": "复查冷却",
                "days_since": int(days_since),
                "reason": _clean_text(row.get("rule_adjustment") or "样本未满，不重复升级为强动作"),
                "confirmed_at": executed_at,
            }
            product_cooldowns[key] = cooldown

    learned_rules = load_learned_rules_history(output_dir, limit=10)
    latest_product_profiles = _load_latest_json_payload(directory, "product_strategy_profiles_*.json")
    latest_keyword_memory = _load_latest_json_payload(directory, "keyword_strategy_memory_*.json")
    product_profiles = latest_product_profiles if isinstance(latest_product_profiles, list) else []
    keyword_memory = latest_keyword_memory if isinstance(latest_keyword_memory, list) else []
    product_profiles_by_key = {
        _strategy_product_key(row): row for row in product_profiles if isinstance(row, dict)
    }
    keyword_memory_by_action_id = {
        str(row.get("action_id") or ""): row for row in keyword_memory if isinstance(row, dict) and row.get("action_id")
    }
    keyword_memory_by_term_key: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in keyword_memory:
        if isinstance(row, dict):
            keyword_memory_by_term_key[_strategy_term_key(row)].append(row)
    action_learning = build_action_learning_policy(output_dir)
    if product_cooldowns:
        notes.append(f"已执行冷却对象 {len(product_cooldowns)} 个：已执行对象短期不重复占用 P0/P1 主动作位，只进入复查或留档。")
    if product_lessons:
        notes.append(f"人工确认经验 {len(product_lessons)} 条：同一产品再次触发时优先引用人工确认原因，而不是泛化成 Listing 问题。")
    learning_summary = action_learning.get("action_learning_summary", {}) if isinstance(action_learning, dict) else {}
    if learning_summary:
        notes.append(
            "动作效果学习："
            f"改善 {learning_summary.get('positive_count', 0)} 条，"
            f"暂未改善/数据不足 {learning_summary.get('negative_count', 0)} 条，"
            f"待复查 {learning_summary.get('pending_count', 0)} 条。"
        )
    useful_learned = [row for row in learned_rules if _clean_text(row.get("outcome")) in {"初步有效", "有改善迹象", "暂未改善"}]
    if useful_learned:
        notes.append(f"已沉淀有效/无效规则 {len(useful_learned)} 条：同类对象会优先参考历史效果再排序。")
    else:
        notes.append("尚无满3天以上的有效性结论，先执行冷却和复查，不自动改动硬阈值。")
    if product_profiles:
        notes.append(f"产品策略画像 {len(product_profiles)} 个：报告会按画像拦截重复放量、前台优先和库存保守对象。")
    if keyword_memory:
        notes.append(f"词级策略记忆 {len(keyword_memory)} 条：同一词/ASIN会优先参考历史有效性和冷却状态。")
    return {
        "product_cooldowns": product_cooldowns,
        "action_cooldowns": action_cooldowns,
        "blocked_action_ids": sorted(action_cooldowns),
        "product_lessons": product_lessons,
        "learned_rules": learned_rules,
        "manual_learning_rows": manual_learning_rows,
        "action_learning": action_learning,
        "product_strategy_profiles": product_profiles,
        "keyword_strategy_memory": keyword_memory,
        "product_profiles_by_key": product_profiles_by_key,
        "keyword_memory_by_action_id": keyword_memory_by_action_id,
        "keyword_memory_by_term_key": dict(keyword_memory_by_term_key),
        "notes": notes,
    }


def derive_rule_adjustments(rows: list[dict[str, object]]) -> dict[str, object]:
    counters: dict[str, Counter] = defaultdict(Counter)
    action_counters: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        diagnosis = _normalize_label_text(row.get("diagnosis_type") or "N/A")
        if diagnosis in {"", "N/A"}:
            continue
        status = _normalize_status(row.get("confirmed_status"), default="待确认")
        action = _normalize_label_text(row.get("today_action") or "N/A")
        counters[diagnosis][status] += 1
        if action and action != "N/A":
            action_counters[f"{diagnosis}｜{action}"][status] += 1

    adjustments: list[dict[str, str]] = []
    for diagnosis, counter in sorted(counters.items(), key=lambda item: (-sum(item[1].values()), item[0])):
        total = sum(counter.values())
        if not total:
            continue
        executed = counter.get("已执行", 0)
        ignored = counter.get("已忽略", 0)
        background = counter.get("仅背景参考", 0)
        executed_rate = executed / total
        ignored_rate = ignored / total
        if total >= 3 and ignored_rate >= 0.5:
            adjustments.append(
                {
                    "rule_scope": diagnosis,
                    "observed_status": f"已忽略 {ignored}/{total}",
                    "suggested_adjustment": "降低该类建议曝光优先级，或提高触发阈值，减少低价值提醒。",
                }
            )
        elif total >= 3 and executed_rate >= 0.6:
            adjustments.append(
                {
                    "rule_scope": diagnosis,
                    "observed_status": f"已执行 {executed}/{total}",
                    "suggested_adjustment": "保留并前置该类建议；可继续维持当前阈值。",
                }
            )
        elif background >= max(total // 2, 1):
            adjustments.append(
                {
                    "rule_scope": diagnosis,
                    "observed_status": f"仅背景参考 {background}/{total}",
                    "suggested_adjustment": "继续将该类内容下沉到 Excel 或背景区，不占主页动作位。",
                }
            )

    top_actions = []
    for key, counter in sorted(action_counters.items(), key=lambda item: (-sum(item[1].values()), item[0]))[:8]:
        diagnosis, action = key.split("｜", 1)
        total = sum(counter.values())
        if total < 2:
            continue
        if counter.get("已忽略", 0) >= 2:
            top_actions.append(
                {
                    "rule_scope": f"{diagnosis} / {action}",
                    "observed_status": f"已忽略 {counter.get('已忽略', 0)}/{total}",
                    "suggested_adjustment": "这类动作容易被忽略，下一版优先级应下调或改写为更具体的执行口径。",
                }
            )
        elif counter.get("已执行", 0) >= 2:
            top_actions.append(
                {
                    "rule_scope": f"{diagnosis} / {action}",
                    "observed_status": f"已执行 {counter.get('已执行', 0)}/{total}",
                    "suggested_adjustment": "这类动作执行率较高，可继续保留为默认推荐。",
                }
            )

    summary = {
        "total_rows": len(rows),
        "diagnosis_type_count": len(counters),
        "action_pattern_count": len(action_counters),
        "executed_rows": sum(1 for row in rows if _normalize_status(row.get("confirmed_status")) == "已执行"),
        "ignored_rows": sum(1 for row in rows if _normalize_status(row.get("confirmed_status")) == "已忽略"),
        "background_rows": sum(1 for row in rows if _normalize_status(row.get("confirmed_status")) == "仅背景参考"),
    }
    return {"summary": summary, "adjustments": adjustments, "action_adjustments": top_actions}


def _metric_lookup(results: list[dict[str, object]]) -> dict[tuple[str, str, str], dict[str, dict[str, object]]]:
    lookup: dict[tuple[str, str, str], dict[str, dict[str, object]]] = {}
    asin_key_counts: dict[tuple[str, str], set[str]] = {}
    for result in results:
        payload = result.get("analysis_payload") or {}
        metrics = payload.get("product_window_metrics", {}) if isinstance(payload, dict) else {}
        if not isinstance(metrics, dict):
            continue
        for window in ["7d", "14d", "30d"]:
            for row in metrics.get(window, []) or []:
                marketplace = str(row.get("marketplace") or "").upper()
                sku = str(row.get("sku") or "").strip()
                asin = str(row.get("asin") or "")
                key = (marketplace, sku, asin)
                if key == ("", "", ""):
                    continue
                asin_key_counts.setdefault((marketplace, asin), set()).add(sku)
                lookup.setdefault(key, {})[window] = row
    for (marketplace, asin), skus in asin_key_counts.items():
        non_empty_skus = {sku for sku in skus if sku}
        if len(non_empty_skus) != 1:
            continue
        sku = next(iter(non_empty_skus))
        exact = lookup.get((marketplace, sku, asin))
        if exact:
            lookup.setdefault((marketplace, "", asin), exact)
    return lookup


def _keyword_metric_lookup(results: list[dict[str, object]]) -> dict[tuple[str, str, str, str], dict[str, dict[str, object]]]:
    lookup: dict[tuple[str, str, str, str], dict[str, dict[str, object]]] = {}
    for result in results:
        payload = result.get("analysis_payload") or {}
        search_payload = payload.get("搜索词分析", {}) if isinstance(payload, dict) else {}
        if not isinstance(search_payload, dict):
            continue
        for window in ["7d", "14d", "30d"]:
            for row in search_payload.get(window, []) or []:
                if not isinstance(row, dict):
                    continue
                marketplace = str(row.get("marketplace") or result.get("marketplace") or "").upper()
                sku = str(row.get("sku") or "").strip()
                asin = str(row.get("asin") or "").strip()
                term = _clean_text(row.get("search_term") or row.get("targeting") or row.get("search_term_or_target")).lower()
                if not marketplace or not asin or not term:
                    continue
                key = (marketplace, sku, asin, term)
                lookup.setdefault(key, {})[window] = row
    return lookup


def _days_between(start: object, end: object) -> int | None:
    try:
        start_day = datetime.fromisoformat(str(start)[:10]).date()
        end_day = datetime.fromisoformat(str(end)[:10]).date()
    except Exception:
        return None
    return (end_day - start_day).days


def _date_after(start: object, days: int) -> str:
    try:
        start_day = datetime.fromisoformat(str(start)[:10]).date()
    except Exception:
        start_day = datetime.now().date()
    return (start_day + timedelta(days=days)).isoformat()


def _to_number(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(result):
        return 0.0
    return result


def _ratio_number(value: object) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        if text.endswith("%"):
            result = float(text[:-1].strip()) / 100
        else:
            result = float(text)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    if result > 1:
        result = result / 100
    return result


def _review_target_acos(row: dict[str, object]) -> float:
    target = _ratio_number(row.get("target_acos") or row.get("suggested_target_acos"))
    if target is None or target <= 0:
        return DEFAULT_REVIEW_TARGET_ACOS
    return target


def _attribution_numbers(row: dict[str, object]) -> dict[str, float]:
    ad_orders = _to_number(row.get("ad_orders") or row.get("orders"))
    ad_sales = _to_number(row.get("ad_sales") or row.get("sales"))
    promoted_orders = _to_number(row.get("promoted_ad_orders") or row.get("promoted_click_orders"))
    promoted_sales = _to_number(row.get("promoted_ad_sales") or row.get("promoted_click_sales"))
    halo_orders = _to_number(row.get("halo_ad_orders") or row.get("halo_click_orders"))
    halo_sales = _to_number(row.get("halo_ad_sales") or row.get("halo_click_sales"))
    return {
        "ad_orders": ad_orders,
        "ad_sales": ad_sales,
        "promoted_orders": promoted_orders,
        "promoted_sales": promoted_sales,
        "halo_orders": halo_orders,
        "halo_sales": halo_sales,
    }


def _attribution_effect_flags(row: dict[str, object]) -> dict[str, object]:
    numbers = _attribution_numbers(row)
    promoted_orders = numbers["promoted_orders"]
    halo_orders = numbers["halo_orders"]
    ad_orders = numbers["ad_orders"]
    promoted_sales = numbers["promoted_sales"]
    halo_sales = numbers["halo_sales"]
    halo_only = ad_orders > 0 and promoted_orders <= 0 and halo_orders > 0
    halo_dominant = halo_orders > promoted_orders or halo_sales > promoted_sales
    promoted_improved = promoted_orders > 0
    target_not_converted = ad_orders > 0 and promoted_orders <= 0
    if halo_only:
        status = "halo_only_conversion"
        note = "带来光环成交，目标 SKU 未验证；不能判定该 SKU 广告动作有效。"
    elif promoted_improved and halo_dominant:
        status = "promoted_with_halo_dominant"
        note = "本 SKU 有成交，但光环成交更高；保留观察，不因光环成交继续放量。"
    elif promoted_improved:
        status = "promoted_conversion_improved"
        note = "广告带动本 SKU 成交，可作为该 SKU 广告效果证据。"
    else:
        status = "target_sku_not_converted"
        note = "目标 SKU 暂未验证成交。"
    return {
        "promoted_conversion_improved": promoted_improved,
        "halo_only_conversion": halo_only,
        "target_sku_not_converted": target_not_converted or (ad_orders <= 0 and promoted_orders <= 0),
        "halo_dominant_conversion": halo_dominant,
        "attribution_effect_status": status,
        "attribution_effect_note": note,
        **numbers,
    }


def _review_effect(row: dict[str, str], recent7: dict[str, object], recent14: dict[str, object], days_since: int | None) -> tuple[str, str, str]:
    action_text = _normalize_label_text(row.get("today_action") or "")
    note_text = _clean_text(row.get("confirmed_note") or "")
    clicks7 = _to_number(recent7.get("ad_clicks"))
    spend7 = _to_number(recent7.get("ad_spend"))
    attr7 = _attribution_effect_flags(recent7)
    attr14 = _attribution_effect_flags(recent14)
    ad_orders7 = _to_number(recent7.get("ad_orders"))
    total_orders7 = _to_number(recent7.get("total_orders"))
    acos7 = recent7.get("ACOS")
    ad_orders14 = _to_number(recent14.get("ad_orders"))
    total_orders14 = _to_number(recent14.get("total_orders"))

    evidence = (
        f"近7天点击 {clicks7:.0f}，广告单 {ad_orders7:.0f}，总单 {total_orders7:.0f}，"
        f"本 SKU 单 {attr7['promoted_orders']:.0f}，光环单 {attr7['halo_orders']:.0f}，"
        f"花费 {spend7:.2f}；近14天广告单 {ad_orders14:.0f}，"
        f"本 SKU 单 {attr14['promoted_orders']:.0f}，光环单 {attr14['halo_orders']:.0f}，总单 {total_orders14:.0f}"
    )
    if days_since is None:
        return "待观察", evidence, "缺少执行日期，先补确认时间。"
    if days_since < 3:
        return "样本不足", evidence, "执行未满3天，不调整规则。"
    if clicks7 < 5 and spend7 < 3:
        return "样本不足", evidence, "执行后流量样本不足，继续观察。"
    if attr7["halo_only_conversion"]:
        return "待观察", evidence, "带来光环成交，目标 SKU 未验证；不判定为动作有效，下次不因光环成交加价或放量。"
    if attr7["promoted_conversion_improved"] or total_orders7 > 0:
        if "调价" in note_text or "价格" in action_text or "降竞价" in action_text:
            return "初步有效", evidence, "类似动作保留；下次同类问题优先提示复查价格/竞价效果。"
        return "有改善迹象", evidence, "继续累计到7天，再决定是否提高该类建议优先级。"
    if clicks7 >= 10 or spend7 >= 5:
        return "暂未改善", evidence, "同类动作不要自动升级；下次优先要求补竞品/页面证据。"
    return "待观察", evidence, "样本未到强结论，保持原规则。"


def _review_keyword_effect(
    row: dict[str, object],
    recent7: dict[str, object],
    recent14: dict[str, object],
    days_since: int | None,
) -> tuple[str, str, str]:
    action_text = _normalize_label_text(row.get("today_action") or row.get("manual_action_taken") or "")
    clicks7 = _to_number(recent7.get("clicks"))
    spend7 = _to_number(recent7.get("spend"))
    attr7 = _attribution_effect_flags(recent7)
    attr14 = _attribution_effect_flags(recent14)
    orders7 = _to_number(recent7.get("ad_orders") or recent7.get("orders"))
    sales7 = _to_number(recent7.get("ad_sales") or recent7.get("sales"))
    clicks14 = _to_number(recent14.get("clicks"))
    spend14 = _to_number(recent14.get("spend"))
    orders14 = _to_number(recent14.get("ad_orders") or recent14.get("orders"))
    sales14 = _to_number(recent14.get("ad_sales") or recent14.get("sales"))
    acos7_raw = recent7.get("ACOS")
    acos14_raw = recent14.get("ACOS")
    cvr7 = (orders7 / clicks7) if clicks7 else 0.0
    cvr14 = (orders14 / clicks14) if clicks14 else 0.0

    evidence = (
        f"7天：点击 {clicks7:.0f}，花费 {spend7:.2f}，订单 {orders7:.0f}，本 SKU 单 {attr7['promoted_orders']:.0f}，光环单 {attr7['halo_orders']:.0f}，销售 {sales7:.2f}，CVR {cvr7:.1%}，ACOS {acos7_raw or 'N/A'}；"
        f"14天：点击 {clicks14:.0f}，花费 {spend14:.2f}，订单 {orders14:.0f}，本 SKU 单 {attr14['promoted_orders']:.0f}，光环单 {attr14['halo_orders']:.0f}，销售 {sales14:.2f}，CVR {cvr14:.1%}，ACOS {acos14_raw or 'N/A'}"
    )
    if days_since is None:
        return "待观察", evidence, "缺少执行日期，先补确认时间。"
    if days_since < 3:
        return "样本不足", evidence, "执行未满3天，不判断该词效果。"
    if not recent7 and not recent14:
        return "数据不足", evidence, "当前搜索词窗口没有匹配到该词/ASIN，先确认是否改名、暂停或数据未覆盖。"
    is_scale = any(token in action_text for token in ["加价", "提高竞价", "放量"])
    is_bid_down = "降竞价" in action_text or "降价" in action_text
    is_negative = "否" in action_text or "暂停" in action_text
    if attr7["halo_only_conversion"]:
        return "待观察", evidence, "带来光环成交，目标 SKU 未验证；不作为该词/ASIN动作有效，不继续加价或放量。"
    if is_scale:
        if attr7["promoted_conversion_improved"] and sales7 > 0:
            return "有改善迹象", evidence, "该词/ASIN加价后仍能出单，继续观察到7天；若 ACOS 仍低于目标，可保留当前竞价。"
        if clicks7 >= 8 or spend7 >= 5:
            return "暂未改善", evidence, "加价后有流量但未出单，先不要继续加价，回到原竞价或改为观察。"
        return "样本不足", evidence, "加价后样本不足，暂不追加预算。"
    if is_bid_down:
        if attr7["promoted_conversion_improved"]:
            return "有改善迹象", evidence, "降竞价后仍有订单，保留当前竞价并继续观察 ACOS。"
        if clicks7 <= 2 and spend7 < 3:
            return "初步有效", evidence, "降竞价后消耗已收敛，低优先级观察即可。"
        return "待7天确认", evidence, "降竞价后还需要看7天消耗和订单是否稳定。"
    if is_negative:
        if clicks7 == 0 and spend7 == 0:
            return "初步有效", evidence, "否词/暂停后该对象已停止消耗，保留处理结果。"
        return "待7天确认", evidence, "仍有消耗，需确认是否否词匹配类型或 ASIN 定向仍在投放。"
    if attr7["promoted_conversion_improved"]:
        return "有改善迹象", evidence, "执行后有订单，继续观察。"
    return "待观察", evidence, "样本未到强结论，保持观察。"


def build_action_review_rows(results: list[dict[str, object]], action_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    metrics = _metric_lookup(results)
    review_rows: list[dict[str, object]] = []
    review_date = datetime.now().date().isoformat()
    for row in action_rows:
        if _normalize_status(row.get("confirmed_status")) != "已执行":
            continue
        key = (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or ""),
        )
        current = metrics.get(key, {})
        recent7 = current.get("7d", {})
        recent14 = current.get("14d", {})
        attr7 = _attribution_effect_flags(recent7)
        attr14 = _attribution_effect_flags(recent14)
        confirmed_at = _clean_text(row.get("confirmed_at") or "")
        report_date = _clean_text(row.get("report_date") or "")
        days_since = _days_between(confirmed_at, review_date) if confirmed_at else None
        if days_since is not None and days_since < 0:
            days_since = 0
        effect_outcome, effect_evidence, rule_adjustment = _review_effect(row, recent7, recent14, days_since)
        timing_fields = _review_timing_fields(days_since)
        if days_since is None:
            review_status = "待下次数据复查"
            outcome = "待复查"
        elif days_since < 3:
            review_status = "未满3天，暂不判断效果"
            outcome = "样本不足"
        elif days_since < 7:
            review_status = "可做3天复查，7天结论待补"
            outcome = "待7天确认"
        else:
            review_status = "可做7天复查"
            outcome = "待人工判定有效/无效"
        review_outcome, effectiveness_score, outcome_block_reason = _standard_keyword_review_outcome(
            recent7,
            recent14,
            days_since,
        )
        timing_fields["review_status"] = review_status
        timing_fields["review_outcome"] = review_outcome
        timing_fields["effectiveness_score"] = effectiveness_score
        if days_since is None or days_since < 3:
            timing_fields["cooldown_until"] = _date_after(confirmed_at or review_date, 3)
        elif days_since < 7:
            timing_fields["cooldown_until"] = _date_after(confirmed_at or review_date, 7)
        else:
            timing_fields["cooldown_until"] = ""
        if outcome_block_reason:
            timing_fields["block_reason"] = outcome_block_reason
        review_rows.append(
            {
                "action_id": add_action_identity(row, row.get("today_action"), "product").get("action_id"),
                "normalized_action": add_action_identity(row, row.get("today_action"), "product").get("normalized_action"),
                "action_scope": "product",
                "marketplace": row.get("marketplace"),
                "sku": row.get("sku"),
                "asin": row.get("asin"),
                "product_name": row.get("product_name"),
                "action_type": row.get("diagnosis_type"),
                "action_detail": row.get("today_action"),
                "confirmed_note": row.get("confirmed_note", ""),
                "executed_at": confirmed_at,
                "report_date": report_date,
                "review_date": review_date,
                "days_since_execution": "" if days_since is None else days_since,
                "current_7d_clicks": recent7.get("ad_clicks", ""),
                "current_7d_spend": recent7.get("ad_spend", ""),
                "current_7d_ad_orders": recent7.get("ad_orders", ""),
                "current_7d_promoted_ad_orders": attr7["promoted_orders"],
                "current_7d_promoted_ad_sales": attr7["promoted_sales"],
                "current_7d_halo_ad_orders": attr7["halo_orders"],
                "current_7d_halo_ad_sales": attr7["halo_sales"],
                "current_7d_total_orders": recent7.get("total_orders", ""),
                "current_7d_acos": recent7.get("ACOS", ""),
                "current_14d_clicks": recent14.get("ad_clicks", ""),
                "current_14d_spend": recent14.get("ad_spend", ""),
                "current_14d_ad_orders": recent14.get("ad_orders", ""),
                "current_14d_promoted_ad_orders": attr14["promoted_orders"],
                "current_14d_promoted_ad_sales": attr14["promoted_sales"],
                "current_14d_halo_ad_orders": attr14["halo_orders"],
                "current_14d_halo_ad_sales": attr14["halo_sales"],
                "current_14d_total_orders": recent14.get("total_orders", ""),
                "current_14d_acos": recent14.get("ACOS", ""),
                "promoted_conversion_improved": attr7["promoted_conversion_improved"],
                "halo_only_conversion": attr7["halo_only_conversion"],
                "target_sku_not_converted": attr7["target_sku_not_converted"],
                "attribution_effect_status": attr7["attribution_effect_status"],
                "attribution_effect_note": attr7["attribution_effect_note"],
                "outcome": effect_outcome if outcome in {"待人工判定有效/无效", "待7天确认"} else outcome,
                "effect_evidence": effect_evidence,
                "review_status": review_status,
                **timing_fields,
                "rule_adjustment": rule_adjustment,
            }
        )
    return review_rows


def build_keyword_action_review_rows(
    results: list[dict[str, object]],
    feedback_rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    metrics = _keyword_metric_lookup(results)
    review_rows: list[dict[str, object]] = []
    review_date = datetime.now().date().isoformat()
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in feedback_rows:
        if _normalize_status(row.get("confirmed_status")) != "已执行":
            continue
        term = _clean_text(row.get("search_term_or_target"))
        if not term:
            continue
        marketplace = str(row.get("marketplace") or "").upper()
        sku = str(row.get("sku") or "").strip()
        asin = str(row.get("asin") or "").strip()
        action_detail = _clean_text(row.get("today_action") or row.get("manual_action_taken") or "")
        key = (marketplace, sku, asin, term.lower(), action_detail)
        if key in seen:
            continue
        seen.add(key)
        current = metrics.get((marketplace, sku, asin, term.lower())) or metrics.get((marketplace, "", asin, term.lower())) or {}
        recent7 = current.get("7d", {})
        recent14 = current.get("14d", {})
        attr7 = _attribution_effect_flags(recent7)
        attr14 = _attribution_effect_flags(recent14)
        confirmed_at = _clean_text(row.get("confirmed_at") or "")
        report_date = _clean_text(row.get("report_date") or "")
        days_since = _days_between(confirmed_at, review_date) if confirmed_at else None
        if days_since is not None and days_since < 0:
            days_since = 0
        effect_outcome, effect_evidence, rule_adjustment = _review_keyword_effect(row, recent7, recent14, days_since)
        timing_fields = _review_timing_fields(days_since)
        if days_since is None:
            review_status = "待下次数据复查"
            review_window = "缺执行日期"
        elif days_since < 3:
            review_status = "未满3天，暂不判断效果"
            review_window = "未满3天"
        elif days_since < 7:
            review_status = "可做3天复查，7天结论待补"
            review_window = "3天后复盘"
        else:
            review_status = "可做7天复查"
            review_window = "7天后复盘"
        review_outcome, effectiveness_score, outcome_block_reason = _standard_keyword_review_outcome(
            recent7,
            recent14,
            days_since,
        )
        timing_fields["review_status"] = review_status
        timing_fields["review_outcome"] = review_outcome
        timing_fields["effectiveness_score"] = effectiveness_score
        if days_since is None or days_since < 3:
            timing_fields["cooldown_until"] = _date_after(confirmed_at or review_date, 3)
        elif days_since < 7:
            timing_fields["cooldown_until"] = _date_after(confirmed_at or review_date, 7)
        else:
            timing_fields["cooldown_until"] = ""
        if outcome_block_reason:
            timing_fields["block_reason"] = outcome_block_reason
        review_rows.append(
            {
                "action_id": add_action_identity(row, action_detail).get("action_id"),
                "normalized_action": add_action_identity(row, action_detail).get("normalized_action"),
                "action_scope": add_action_identity(row, action_detail).get("action_scope"),
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": row.get("product_name") or "",
                "search_term_or_target": term,
                "action_detail": action_detail,
                "confirmed_note": row.get("confirmed_note", ""),
                "executed_at": confirmed_at,
                "report_date": report_date,
                "review_date": review_date,
                "days_since_execution": "" if days_since is None else days_since,
                "review_window": review_window,
                "current_7d_clicks": recent7.get("clicks", ""),
                "current_7d_spend": recent7.get("spend", ""),
                "current_7d_ad_orders": recent7.get("ad_orders", ""),
                "current_7d_ad_sales": recent7.get("ad_sales", ""),
                "current_7d_promoted_ad_orders": attr7["promoted_orders"],
                "current_7d_promoted_ad_sales": attr7["promoted_sales"],
                "current_7d_halo_ad_orders": attr7["halo_orders"],
                "current_7d_halo_ad_sales": attr7["halo_sales"],
                "current_7d_acos": recent7.get("ACOS", ""),
                "current_14d_clicks": recent14.get("clicks", ""),
                "current_14d_spend": recent14.get("spend", ""),
                "current_14d_ad_orders": recent14.get("ad_orders", ""),
                "current_14d_ad_sales": recent14.get("ad_sales", ""),
                "current_14d_promoted_ad_orders": attr14["promoted_orders"],
                "current_14d_promoted_ad_sales": attr14["promoted_sales"],
                "current_14d_halo_ad_orders": attr14["halo_orders"],
                "current_14d_halo_ad_sales": attr14["halo_sales"],
                "current_14d_acos": recent14.get("ACOS", ""),
                "promoted_conversion_improved": attr7["promoted_conversion_improved"],
                "halo_only_conversion": attr7["halo_only_conversion"],
                "target_sku_not_converted": attr7["target_sku_not_converted"],
                "attribution_effect_status": attr7["attribution_effect_status"],
                "attribution_effect_note": attr7["attribution_effect_note"],
                "outcome": effect_outcome,
                "effect_evidence": effect_evidence,
                "review_status": review_status,
                **timing_fields,
                "rule_adjustment": rule_adjustment,
                "learning_scope": "keyword_or_target",
            }
        )
    return review_rows


def build_learned_rules(action_review_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    learned: list[dict[str, object]] = []
    for row in action_review_rows:
        outcome = _clean_text(row.get("outcome"))
        if outcome not in {"初步有效", "有改善迹象", "暂未改善"}:
            continue
        learned.append(
            {
                "marketplace": row.get("marketplace"),
                "sku": row.get("sku"),
                "asin": row.get("asin"),
                "product_name": row.get("product_name"),
                "action_type": row.get("action_type"),
                "manual_note": row.get("confirmed_note", ""),
                "outcome": outcome,
                "effect_evidence": row.get("effect_evidence", ""),
                "promoted_conversion_improved": row.get("promoted_conversion_improved", False),
                "halo_only_conversion": row.get("halo_only_conversion", False),
                "target_sku_not_converted": row.get("target_sku_not_converted", False),
                "attribution_effect_status": row.get("attribution_effect_status", ""),
                "attribution_effect_note": row.get("attribution_effect_note", ""),
                "next_rule": row.get("rule_adjustment", ""),
                "updated_at": row.get("review_date", ""),
            }
        )
    return learned


def _attribution_learning_summary(
    action_review_rows: Iterable[dict[str, object]],
    keyword_action_review_rows: Iterable[dict[str, object]],
    keyword_strategy_memory: Iterable[dict[str, object]],
) -> dict[str, object]:
    combined = list(action_review_rows or []) + list(keyword_action_review_rows or [])
    halo_only_rows = [row for row in combined if bool(row.get("halo_only_conversion"))]
    promoted_rows = [row for row in combined if bool(row.get("promoted_conversion_improved"))]
    target_not_converted_rows = [row for row in combined if bool(row.get("target_sku_not_converted"))]
    memory_halo_rows = [row for row in keyword_strategy_memory or [] if bool(row.get("halo_only_conversion"))]
    def _brief(row: dict[str, object]) -> dict[str, object]:
        return {
            "marketplace": row.get("marketplace"),
            "sku": row.get("sku"),
            "asin": row.get("asin"),
            "product_name": row.get("product_name"),
            "search_term_or_target": row.get("search_term_or_target", ""),
            "action_detail": row.get("action_detail") or row.get("normalized_action", ""),
            "status": row.get("attribution_effect_status") or row.get("latest_effect_status") or "",
            "note": row.get("attribution_effect_note") or row.get("evidence_summary") or row.get("effect_evidence") or "",
        }

    return {
        "promoted_conversion_improved_count": len(promoted_rows),
        "halo_only_conversion_count": len(halo_only_rows),
        "target_sku_not_converted_count": len(target_not_converted_rows),
        "keyword_memory_halo_only_count": len(memory_halo_rows),
        "halo_only_conversion_objects": [_brief(row) for row in halo_only_rows[:20]],
        "target_sku_not_converted_objects": [_brief(row) for row in target_not_converted_rows[:20]],
        "policy_note": "仅光环成交不作为目标 SKU 动作有效证据；后续不因 halo-only 继续加价或放量。",
    }


def build_autoopt_payload(
    results: list[dict[str, object]],
    output_dir: Path | None = None,
) -> dict[str, object]:
    rows: list[dict[str, str]] = []
    for result in results:
        if not result.get("has_data"):
            continue
        analysis_payload = result.get("analysis_payload") or {}
        report_view = result.get("report_view") or {}
        marketplace = str(result.get("marketplace") or analysis_payload.get("target_marketplace") or "N/A")
        rows.extend(build_autoopt_rows(analysis_payload, report_view, marketplace, output_dir=output_dir))

    rows = apply_feedback_override(rows, load_feedback_input(output_dir))
    for row in rows:
        for key in ["diagnosis_type", "today_action", "source_section", "search_term_summary", "search_term_summary_more"]:
            if key in row:
                row[key] = _normalize_label_text(row.get(key))
    history_rows = load_autoopt_history(output_dir)
    adjustment_payload = derive_rule_adjustments(history_rows + rows)
    report_date = (
        next(
            (
                str(result.get("summary", {}).get("report_date"))
                for result in results
                if result.get("summary", {}).get("report_date")
            ),
            None,
        )
        or datetime.now().date().isoformat()
    )
    action_review_rows = build_action_review_rows(results, rows)
    keyword_action_review_rows = build_keyword_action_review_rows(results, load_feedback_input(output_dir))
    learned_rules = build_learned_rules(action_review_rows)
    manual_learning_rows = build_manual_learning_rows(load_feedback_input(output_dir))
    action_learning = build_action_learning_policy(
        output_dir,
        current_action_reviews=action_review_rows,
        current_keyword_reviews=keyword_action_review_rows,
    )
    runtime_policy = build_runtime_policy(output_dir)
    feedback_rows = load_feedback_input(output_dir)
    keyword_strategy_memory = build_keyword_strategy_memory(
        output_dir,
        current_keyword_reviews=keyword_action_review_rows,
        feedback_rows=feedback_rows,
    )
    product_strategy_profiles = build_product_strategy_profiles(
        results,
        keyword_memory=keyword_strategy_memory,
        current_action_reviews=action_review_rows,
    )
    attribution_learning = _attribution_learning_summary(
        action_review_rows,
        keyword_action_review_rows,
        keyword_strategy_memory,
    )
    recommendation_guard = build_recommendation_guard(
        product_strategy_profiles,
        keyword_strategy_memory,
        runtime_policy,
    )
    product_final_decisions: list[dict[str, object]] = []
    seen_decision_keys: set[tuple[str, str, str]] = set()
    for result in results:
        report_view = result.get("report_view") or {}
        for row in report_view.get("product_final_decision_rows", []) or []:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("marketplace") or "").upper(),
                str(row.get("sku") or "").strip(),
                str(row.get("asin") or "").strip().upper(),
            )
            if key in seen_decision_keys:
                continue
            seen_decision_keys.add(key)
            product_final_decisions.append(row)
    final_decision_payload = decision_summary(product_final_decisions)
    return {
        "report_date": report_date,
        "generated_at": _now_str(),
        "rows": rows,
        "action_review_rows": action_review_rows,
        "keyword_action_review_rows": keyword_action_review_rows,
        "learned_rules": learned_rules,
        "manual_learning_rows": manual_learning_rows,
        "action_learning_summary": action_learning.get("action_learning_summary", {}),
        "positive_action_patterns": action_learning.get("positive_action_patterns", []),
        "negative_action_patterns": action_learning.get("negative_action_patterns", []),
        "cooldown_objects": list((runtime_policy.get("product_cooldowns", {}) or {}).values()),
        "action_cooldown_objects": list((runtime_policy.get("action_cooldowns", {}) or {}).values()),
        "blocked_action_ids": runtime_policy.get("blocked_action_ids", []),
        "pending_review_objects": action_learning.get("pending_review_objects", []),
        "recommendation_policy_adjustments": action_learning.get("recommendation_policy_adjustments", []),
        "product_strategy_profiles": product_strategy_profiles,
        "keyword_strategy_memory": keyword_strategy_memory,
        "attribution_learning_summary": attribution_learning,
        "product_final_decisions": product_final_decisions,
        **final_decision_payload,
        **recommendation_guard,
        "summary": adjustment_payload["summary"],
        "rule_adjustments": adjustment_payload["adjustments"],
        "action_adjustments": adjustment_payload["action_adjustments"],
    }


def write_autoopt_outputs(
    output_dir: Path | None,
    report_date: str,
    payload: dict[str, object],
) -> tuple[Path, Path]:
    directory = output_dir or OUTPUT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    date_token = report_date.replace("-", "")
    json_path = directory / f"autoopt_log_{date_token}.json"
    xlsx_path = directory / f"autoopt_{date_token}.xlsx"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    frame = pd.DataFrame(rows)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="autoopt_log", index=False)
        pd.DataFrame([payload.get("summary", {})] if isinstance(payload, dict) else [{}]).to_excel(
            writer, sheet_name="summary", index=False
        )
        pd.DataFrame(payload.get("rule_adjustments", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="rule_adjustments", index=False
        )
        pd.DataFrame(payload.get("action_adjustments", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="action_adjustments", index=False
        )
        pd.DataFrame(payload.get("action_review_rows", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="action_review", index=False
        )
        pd.DataFrame(payload.get("keyword_action_review_rows", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="keyword_action_review", index=False
        )
        pd.DataFrame(payload.get("learned_rules", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="learned_rules", index=False
        )
        pd.DataFrame(payload.get("manual_learning_rows", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="manual_learning", index=False
        )
        pd.DataFrame(payload.get("positive_action_patterns", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="positive_actions", index=False
        )
        pd.DataFrame(payload.get("negative_action_patterns", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="negative_actions", index=False
        )
        pd.DataFrame(payload.get("pending_review_objects", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="pending_reviews", index=False
        )
        pd.DataFrame(payload.get("product_strategy_profiles", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="product_profiles", index=False
        )
        pd.DataFrame(payload.get("keyword_strategy_memory", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="keyword_memory", index=False
        )
        pd.DataFrame([payload.get("attribution_learning_summary", {})] if isinstance(payload, dict) else [{}]).to_excel(
            writer, sheet_name="attribution_learning", index=False
        )
        pd.DataFrame(payload.get("product_final_decisions", []) if isinstance(payload, dict) else []).to_excel(
            writer, sheet_name="final_decisions", index=False
        )

    review_json_path = directory / f"action_review_{date_token}.json"
    review_json_path.write_text(
        json.dumps(payload.get("action_review_rows", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    keyword_review_json_path = directory / f"keyword_action_review_{date_token}.json"
    keyword_review_json_path.write_text(
        json.dumps(payload.get("keyword_action_review_rows", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    learned_json_path = directory / f"learned_rules_{date_token}.json"
    learned_json_path.write_text(
        json.dumps(payload.get("learned_rules", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manual_learning_json_path = directory / f"manual_learning_log_{date_token}.json"
    manual_learning_json_path.write_text(
        json.dumps(payload.get("manual_learning_rows", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    product_profiles_json_path = directory / f"product_strategy_profiles_{date_token}.json"
    product_profiles = payload.get("product_strategy_profiles", []) if isinstance(payload, dict) else []
    product_profiles_json_path.write_text(
        json.dumps(product_profiles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    product_profiles_md_path = directory / "product_strategy_profiles.md"
    product_profile_lines = ["# 产品策略画像", ""]
    for row in (product_profiles if isinstance(product_profiles, list) else []):
        if not isinstance(row, dict):
            continue
        tags = "、".join(str(item) for item in row.get("profile_tags", []) if item) if isinstance(row.get("profile_tags"), list) else str(row.get("profile_tags") or "")
        product_profile_lines.append(
            f"- {row.get('marketplace') or ''}｜{row.get('product_name') or row.get('asin') or ''}：{row.get('ad_strategy_mode') or ''}；标签：{tags or '常规观察'}；拦截：{', '.join(row.get('blocked_actions') or []) if isinstance(row.get('blocked_actions'), list) else row.get('blocked_actions') or '无'}"
        )
    product_profiles_md_path.write_text("\n".join(product_profile_lines).rstrip() + "\n", encoding="utf-8")

    keyword_memory_json_path = directory / f"keyword_strategy_memory_{date_token}.json"
    keyword_memory = payload.get("keyword_strategy_memory", []) if isinstance(payload, dict) else []
    keyword_memory_json_path.write_text(
        json.dumps(keyword_memory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    keyword_memory_md_path = directory / "keyword_strategy_memory.md"
    keyword_memory_lines = ["# 词级策略记忆", ""]
    for row in (keyword_memory if isinstance(keyword_memory, list) else []):
        if not isinstance(row, dict):
            continue
        keyword_memory_lines.append(
            f"- {row.get('marketplace') or ''}｜{row.get('product_name') or row.get('asin') or ''}｜{row.get('search_term_or_target') or ''}：{row.get('recommended_future_policy') or ''}；效果分 {row.get('effectiveness_score')}; {row.get('evidence_summary') or ''}"
        )
    keyword_memory_md_path.write_text("\n".join(keyword_memory_lines).rstrip() + "\n", encoding="utf-8")

    write_product_final_decisions(
        directory,
        report_date,
        payload.get("product_final_decisions", []) if isinstance(payload, dict) else [],
    )

    self_optimization_log_path = directory / f"self_optimization_log_{date_token}.json"
    self_optimization_log_path.write_text(
        json.dumps(
            {
                "report_date": report_date,
                "generated_at": payload.get("generated_at") if isinstance(payload, dict) else _now_str(),
                "summary": payload.get("summary", {}) if isinstance(payload, dict) else {},
                "rule_adjustments": payload.get("rule_adjustments", []) if isinstance(payload, dict) else [],
                "action_adjustments": payload.get("action_adjustments", []) if isinstance(payload, dict) else [],
                "keyword_action_review_rows": payload.get("keyword_action_review_rows", []) if isinstance(payload, dict) else [],
                "learned_rules": payload.get("learned_rules", []) if isinstance(payload, dict) else [],
                "manual_learning_rows": payload.get("manual_learning_rows", []) if isinstance(payload, dict) else [],
                "action_learning_summary": payload.get("action_learning_summary", {}) if isinstance(payload, dict) else {},
                "positive_action_patterns": payload.get("positive_action_patterns", []) if isinstance(payload, dict) else [],
                "negative_action_patterns": payload.get("negative_action_patterns", []) if isinstance(payload, dict) else [],
                "cooldown_objects": payload.get("cooldown_objects", []) if isinstance(payload, dict) else [],
                "action_cooldown_objects": payload.get("action_cooldown_objects", []) if isinstance(payload, dict) else [],
                "blocked_action_ids": payload.get("blocked_action_ids", []) if isinstance(payload, dict) else [],
                "pending_review_objects": payload.get("pending_review_objects", []) if isinstance(payload, dict) else [],
                "recommendation_policy_adjustments": payload.get("recommendation_policy_adjustments", []) if isinstance(payload, dict) else [],
                "recommendation_guard_summary": payload.get("recommendation_guard_summary", {}) if isinstance(payload, dict) else {},
                "blocked_recommendations": payload.get("blocked_recommendations", []) if isinstance(payload, dict) else [],
                "downgraded_recommendations": payload.get("downgraded_recommendations", []) if isinstance(payload, dict) else [],
                "allowed_recommendations_with_memory": payload.get("allowed_recommendations_with_memory", []) if isinstance(payload, dict) else [],
                "reused_success_patterns": payload.get("reused_success_patterns", []) if isinstance(payload, dict) else [],
                "product_profile_updates": payload.get("product_profile_updates", []) if isinstance(payload, dict) else [],
                "keyword_memory_updates": payload.get("keyword_memory_updates", []) if isinstance(payload, dict) else [],
                "attribution_learning_summary": payload.get("attribution_learning_summary", {}) if isinstance(payload, dict) else {},
                "final_decision_summary": payload.get("final_decision_summary", {}) if isinstance(payload, dict) else {},
                "decision_gate_counts": payload.get("decision_gate_counts", {}) if isinstance(payload, dict) else {},
                "blocked_by_data_quality": payload.get("blocked_by_data_quality", []) if isinstance(payload, dict) else [],
                "blocked_by_frontend": payload.get("blocked_by_frontend", []) if isinstance(payload, dict) else [],
                "blocked_by_inventory": payload.get("blocked_by_inventory", []) if isinstance(payload, dict) else [],
                "blocked_by_cooldown": payload.get("blocked_by_cooldown", []) if isinstance(payload, dict) else [],
                "blocked_by_keyword_memory": payload.get("blocked_by_keyword_memory", []) if isinstance(payload, dict) else [],
                "executable_today_count": payload.get("executable_today_count", 0) if isinstance(payload, dict) else 0,
                "wait_review_count": payload.get("wait_review_count", 0) if isinstance(payload, dict) else 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return json_path, xlsx_path


def _short_scope(text: object) -> str:
    raw = _clean_text(text)
    if not raw or raw == "N/A":
        return ""
    raw = raw.replace("搜索词处理队列", "广告处理队列").replace("搜索词处理", "广告处理")
    parts = [part.strip() for part in raw.replace("/", "；").split("；") if part.strip()]
    generic = {
        "暂时不加广告预算",
        "核心词不直接否",
        "明显不相关词才否定精准",
        "相关高花费 0 单词先降竞价",
        "等人工确认价格、主图、评价、Coupon、竞品和广告流量后再决定是否改 Listing。",
        "观察",
    }
    useful = [part for part in parts if part not in generic and part != "N/A"]
    if not useful:
        useful = parts
    return " / ".join(useful[:2])


def build_optimization_notes(output_dir: Path | None, rows: list[dict[str, object]] | None = None) -> list[str]:
    history_rows = load_autoopt_history(output_dir)
    if rows:
        history_rows.extend(rows)
    payload = derive_rule_adjustments(history_rows)
    notes: list[str] = []
    for item in payload["adjustments"][:3]:
        scope = _short_scope(item.get("rule_scope"))
        if not scope:
            continue
        notes.append(
            f"{scope}：{item['observed_status']}，{item['suggested_adjustment']}"
        )
    for item in payload["action_adjustments"][:2]:
        scope = _short_scope(item.get("rule_scope"))
        if not scope:
            continue
        notes.append(
            f"{scope}：{item['observed_status']}，{item['suggested_adjustment']}"
        )
    if not notes:
        notes.append("当前没有足够的反馈历史来调整规则，先继续积累已执行 / 已忽略样本。")
    return notes[:5]
