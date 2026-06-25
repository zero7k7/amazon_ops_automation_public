from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable


RecordKeyFunc = Callable[[dict], tuple[str, str, str]]
SuccessFunc = Callable[[dict], bool]


def record_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or "").strip().upper(),
        str(row.get("sku") or row.get("SKU") or "").strip(),
        str(row.get("asin") or row.get("ASIN") or "").strip().upper(),
    )


def today_iso() -> str:
    return datetime.now().date().isoformat()


def record_data_date(row: dict) -> str:
    for key in ("frontend_data_date", "checked_at", "generated_at"):
        value = str(row.get(key) or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", value):
            return value[:10]
    freshness = str(row.get("frontend_data_freshness") or row.get("frontend_check_status") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", freshness)
    return match.group(0) if match else ""


def load_previous_frontend_state(
    results_path: Path,
    *,
    is_success_record: SuccessFunc,
    record_key: RecordKeyFunc,
) -> tuple[list[dict], dict[tuple[str, str, str], dict]]:
    if not results_path.exists():
        return [], {}
    try:
        raw = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], {}
    if isinstance(raw, dict):
        records = raw.get("items", [])
        cache_raw = raw.get("cache", [])
    else:
        records = raw
        cache_raw = []
    if not isinstance(records, list):
        records = []
    if not isinstance(cache_raw, list):
        cache_raw = []
    cache: dict[tuple[str, str, str], dict] = {}
    for record in [*cache_raw, *records]:
        if not isinstance(record, dict) or not is_success_record(record):
            continue
        key = record_key(record)
        if key[0] and key[2]:
            cache[key] = record
            cache[(key[0], "", key[2])] = record
    return [record for record in records if isinstance(record, dict)], cache


def cached_record_for(
    row: dict,
    cache: dict[tuple[str, str, str], dict],
    *,
    record_key: RecordKeyFunc,
) -> dict | None:
    marketplace, sku, asin = record_key(row)
    for key in ((marketplace, sku, asin), (marketplace, "", asin)):
        cached = cache.get(key)
        if cached:
            return cached
    return None


def refresh_summary(rows: list[dict]) -> dict[str, object]:
    live_checked = 0
    skipped = 0
    cache_used = 0
    failed = 0
    checked_labels: list[str] = []
    skipped_labels: list[str] = []
    cache_labels: list[str] = []
    failed_labels: list[str] = []
    for row in rows:
        label = " ".join(
            part
            for part in [
                str(row.get("marketplace") or "").strip().upper(),
                str(row.get("asin") or "").strip().upper(),
            ]
            if part
        )
        action = str(row.get("frontend_refresh_action") or "")
        if action == "skipped_fresh":
            skipped += 1
            if label:
                skipped_labels.append(label)
        elif action == "cache_fallback" or bool(row.get("frontend_cache_used")):
            cache_used += 1
            if label:
                cache_labels.append(label)
        elif action == "live_checked" and str(row.get("frontend_check_status") or "") == "已自动检查":
            live_checked += 1
            if label:
                checked_labels.append(label)
        else:
            failed += 1
            if label:
                failed_labels.append(label)
    return {
        "frontend_refresh_total": len(rows),
        "frontend_refresh_live_checked": live_checked,
        "frontend_refresh_skipped": skipped,
        "frontend_refresh_cache_used": cache_used,
        "frontend_refresh_failed": failed,
        "frontend_refresh_live_checked_labels": checked_labels,
        "frontend_refresh_skipped_labels": skipped_labels,
        "frontend_refresh_cache_labels": cache_labels,
        "frontend_refresh_failed_labels": failed_labels,
    }


def print_progress(current: int, total: int, row: dict, action: str) -> None:
    label = " ".join(
        part
        for part in [
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("asin") or "").strip().upper(),
        ]
        if part
    )
    print(f"[frontend-progress] {current}/{total} {action}: {label}", flush=True)


def cache_items(
    rows: list[dict],
    results_path: Path,
    *,
    is_success_record: SuccessFunc,
    record_key: RecordKeyFunc,
) -> list[dict]:
    cache: dict[tuple[str, str, str], dict] = {}
    _, previous_cache = load_previous_frontend_state(
        results_path,
        is_success_record=is_success_record,
        record_key=record_key,
    )
    cache.update(previous_cache)
    for row in rows:
        if is_success_record(row):
            key = record_key(row)
            if key[0] and key[2]:
                cache[key] = row
                cache[(key[0], "", key[2])] = row
    unique: dict[tuple[str, str, str], dict] = {}
    for key, row in cache.items():
        if key[1]:
            unique[key] = row
    return list(unique.values())


def merged_items(
    rows: list[dict],
    results_path: Path,
    *,
    is_success_record: SuccessFunc,
    record_key: RecordKeyFunc,
) -> list[dict]:
    merged: dict[tuple[str, str, str], dict] = {}
    previous_rows, _ = load_previous_frontend_state(
        results_path,
        is_success_record=is_success_record,
        record_key=record_key,
    )
    for row in previous_rows:
        if not is_success_record(row):
            continue
        key = record_key(row)
        if key[0] and key[1] and key[2]:
            merged[key] = row
    for row in rows:
        key = record_key(row)
        if key[0] and key[1] and key[2]:
            if not is_success_record(row) and key in merged:
                continue
            merged[key] = row
    return list(merged.values())


def write_results_payload(
    rows: list[dict],
    results_path: Path,
    *,
    is_success_record: SuccessFunc,
    record_key: RecordKeyFunc,
) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fallback_policy": "live_fetch -> retry -> last_success_cache -> manual_first_check",
        "refresh_summary": refresh_summary(rows),
        "items": merged_items(rows, results_path, is_success_record=is_success_record, record_key=record_key),
        "cache": cache_items(rows, results_path, is_success_record=is_success_record, record_key=record_key),
    }
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
