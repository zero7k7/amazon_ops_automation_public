from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


HISTORY_FILE_NAME = "task_trigger_history.json"


def _task_key(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("marketplace") or "").upper(),
        str(row.get("sku") or "").strip(),
        str(row.get("asin") or "").strip(),
        str(row.get("issue_type") or "").strip(),
    ]
    return "|".join(parts)


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def _load_history(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    return entries if isinstance(entries, dict) else {}


def _write_history(path: Path, report_date: str, entries: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"report_date": report_date, "entries": entries}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _product_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or "").upper(),
        str(row.get("sku") or "").strip(),
        str(row.get("asin") or "").strip(),
    )


def _load_prior_product_days(output_dir: Path, current_date: date) -> dict[tuple[str, str, str], set[date]]:
    days_by_product: dict[tuple[str, str, str], set[date]] = {}
    for path in sorted(output_dir.glob("autoopt_log_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        report_day = _parse_date(payload.get("report_date") if isinstance(payload, dict) else None)
        if report_day is None or report_day >= current_date:
            continue
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or str(row.get("priority") or "") not in {"P0", "P1"}:
                continue
            key = _product_key(row)
            if key == ("", "", ""):
                continue
            days_by_product.setdefault(key, set()).add(report_day)
    return days_by_product


def _prior_consecutive_product_days(
    product_days: dict[tuple[str, str, str], set[date]],
    key: tuple[str, str, str],
    current_date: date,
) -> tuple[int, str | None]:
    days = product_days.get(key, set())
    if not days:
        return 0, None
    count = 0
    cursor = current_date - timedelta(days=1)
    first_seen: date | None = None
    while cursor in days:
        count += 1
        first_seen = cursor
        cursor -= timedelta(days=1)
    return count, first_seen.isoformat() if first_seen else None


def _review_status(row: dict[str, Any], consecutive_days: int) -> str:
    if str(row.get("confirmed_status") or "") == "已执行":
        return "已执行待验证"
    if _is_cost_or_profit_config_issue(row):
        return "配置未修复"
    if consecutive_days > 1:
        return "持续问题"
    return "新问题"


def _downgrade_condition(row: dict[str, Any]) -> str:
    issue_text = f"{row.get('issue_type') or ''} {row.get('primary_reason') or ''} {row.get('action_group') or ''}"
    if _is_cost_or_profit_config_issue(row):
        return "修正成本/售价/target_acos 后，广告前利润恢复为正。"
    if "广告消耗无转化" in issue_text or "广告归因弱" in issue_text:
        return "近7天广告订单恢复，且 ACOS 回到目标附近。"
    if "滞销" in issue_text or "无单" in issue_text:
        return "近7天恢复出单，或库存/广告花费不再达到风险阈值。"
    if "Listing" in issue_text or "ACOS" in issue_text:
        return "ACOS 回到目标附近，或点击、订单、页面转化恢复。"
    return "连续新数据不再触发当前规则。"


def _why_still_active(row: dict[str, Any], status: str) -> str:
    if status == "已执行待验证":
        return "动作已记录，等待 3 天/7 天效果复盘。"
    if status == "配置未修复":
        return "成本/利润配置仍触发风险，未确认前不应放量。"
    reason = str(row.get("primary_reason") or "").strip()
    if status == "持续问题":
        return f"最新窗口仍命中：{reason}" if reason else "最新窗口仍命中同一类规则。"
    return f"今天首次命中：{reason}" if reason else "今天首次进入 P0/P1。"


def _is_cost_or_profit_config_issue(row: dict[str, Any]) -> bool:
    issue_type = str(row.get("issue_type") or "")
    action_group = str(row.get("action_group") or "")
    reason = str(row.get("primary_reason") or "")
    return (
        action_group == "成本 / 利润动作"
        or "成本 / 利润压力" in issue_type
        or "库存 / 利润压力" in issue_type
        or "广告前利润<=0" in reason
        or "target_acos=0" in reason
    )


def annotate_task_history(
    results: list[dict[str, Any]],
    output_dir: Path,
    report_date: str,
) -> None:
    """Annotate P0/P1 rows with trigger history without changing rule decisions."""
    history_path = output_dir / HISTORY_FILE_NAME
    entries = _load_history(history_path)
    current_date = _parse_date(report_date) or date.today()
    prior_product_days = _load_prior_product_days(output_dir, current_date)
    seen_keys: set[str] = set()

    for result in results:
        view = result.get("report_view", {})
        rows = view.get("today_task_queue_rows", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = _task_key(row)
            if not key.replace("|", ""):
                continue
            previous = entries.get(key, {})
            last_seen = _parse_date(previous.get("last_seen"))
            first_seen = str(previous.get("first_seen") or report_date)
            previous_days = int(previous.get("consecutive_days") or 0)
            prior_days, prior_first_seen = _prior_consecutive_product_days(prior_product_days, _product_key(row), current_date)
            if last_seen == current_date:
                consecutive_days = max(previous_days, prior_days + 1 if prior_days else 1)
                if prior_first_seen and consecutive_days > previous_days:
                    first_seen = prior_first_seen
            elif last_seen == current_date - timedelta(days=1):
                consecutive_days = previous_days + 1
            else:
                consecutive_days = prior_days + 1 if prior_days else 1
                first_seen = prior_first_seen or report_date

            status = _review_status(row, consecutive_days)
            row["first_triggered_at"] = first_seen
            row["last_triggered_at"] = report_date
            row["consecutive_trigger_days"] = str(consecutive_days)
            row["review_status"] = status
            row["why_still_active"] = _why_still_active(row, status)
            row["downgrade_condition"] = _downgrade_condition(row)

            entries[key] = {
                "first_seen": first_seen,
                "last_seen": report_date,
                "consecutive_days": consecutive_days,
                "marketplace": row.get("marketplace"),
                "sku": row.get("sku"),
                "asin": row.get("asin"),
                "product_name": row.get("product_name"),
                "issue_type": row.get("issue_type"),
                "priority": row.get("priority"),
                "review_status": status,
            }
            seen_keys.add(key)

    # Keep old entries for context, but mark absence so future reappearance starts fresh.
    for key, entry in list(entries.items()):
        if key not in seen_keys and entry.get("last_seen") != report_date:
            entry["last_absent"] = report_date

    _write_history(history_path, report_date, entries)
