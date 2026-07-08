from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
SELLERSPRITE_HISTORY_PATH = OUTPUT_DIR / "sellersprite_history_snapshots.jsonl"

HISTORY_TREND_FIELDS = [
    "sellersprite_today_status",
    "sellersprite_cache_date",
    "sellersprite_history_days",
    "sellersprite_trend_status",
    "sellersprite_new_keywords",
    "sellersprite_persistent_keywords",
    "sellersprite_lost_keywords",
    "sellersprite_rank_improved_keywords",
    "sellersprite_rank_declined_keywords",
    "sellersprite_ppc_up_keywords",
    "sellersprite_ppc_down_keywords",
    "competitor_stable_asins",
    "competitor_stable_keyword_overlap",
    "competitor_pressure_trend",
    "own_missing_competitor_keywords_trend",
    "sellersprite_evidence_tier",
]

KEYWORD_FIELDS = {
    "keyword": ("keyword", "流量词"),
    "translation": ("translation", "翻译"),
    "traffic_share": ("traffic_share", "流量占比"),
    "keyword_type": ("keyword_type", "流量词类型"),
    "natural_rank": ("natural_rank", "自然排名"),
    "ad_rank": ("ad_rank", "广告排名"),
    "aba_rank": ("aba_rank", "ABA周排名"),
    "monthly_searches": ("monthly_searches", "月搜索量"),
    "spr": ("spr", "SPR"),
    "title_density": ("title_density", "标题密度"),
    "purchases": ("purchases", "购买量"),
    "impressions_clicks": ("impressions_clicks", "展示量点击量", "展示量/点击量"),
    "product_supply": ("product_supply", "需供比商品数", "商品数"),
    "ad_products": ("ad_products", "广告竞品数"),
    "concentration": ("concentration", "ABA集中度"),
    "ppc": ("ppc", "PPC价格", "PPC竞价"),
}


def normalize_keyword(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _date_text(value: object) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""


def _parse_date(value: object) -> date | None:
    text = _date_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _today_text(report_date: str | date | None = None) -> str:
    if isinstance(report_date, date):
        return report_date.isoformat()
    if report_date:
        parsed = _date_text(report_date)
        if parsed:
            return parsed
    return date.today().isoformat()


def _effective_report_day(report_date: str | date | None, own_record: dict | None = None) -> str:
    report_day = _today_text(report_date)
    record_day = _record_data_date(own_record or {})
    if record_day and record_day > report_day:
        return record_day
    return report_day


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None
    match = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _value_from(item: dict, aliases: tuple[str, ...]) -> object:
    for key in aliases:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return ""


def _record_data_date(record: dict) -> str:
    for key in ("data_date", "checked_at", "generated_at", "captured_at"):
        text = _date_text(record.get(key))
        if text:
            return text
    return ""


def _record_status(record: dict, snapshot_status: str | None = None) -> str:
    if snapshot_status:
        return snapshot_status
    return str(record.get("seller_sprite_check_status") or record.get("status") or "").strip() or "待补"


def _successful_status(value: object) -> bool:
    return str(value or "").strip() in {"已抓取", "沿用缓存"}


def _row_with_context(record: dict, context_row: dict | None = None) -> dict:
    item = dict(record)
    if not context_row:
        return item
    for field in [
        "marketplace",
        "sku",
        "asin",
        "source_role",
        "parent_marketplace",
        "parent_sku",
        "parent_asin",
        "competitor_discovery_source",
        "competitor_pool_confidence",
    ]:
        value = context_row.get(field)
        if value not in (None, ""):
            item[field] = value
    return item


def history_rows_from_records(
    records: Iterable[dict],
    *,
    report_date: str | date | None = None,
    snapshot_status: str | None = None,
    context_by_key: dict[tuple[str, str], dict] | None = None,
) -> list[dict[str, object]]:
    report_day = _today_text(report_date)
    captured_at = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, object]] = []
    for raw_record in records:
        if not isinstance(raw_record, dict):
            continue
        market = str(raw_record.get("marketplace") or "").strip().upper()
        asin = str(raw_record.get("asin") or "").strip().upper()
        context = (context_by_key or {}).get((market, asin))
        record = _row_with_context(raw_record, context)
        market = str(record.get("marketplace") or "").strip().upper()
        asin = str(record.get("asin") or "").strip().upper()
        if not market or not asin:
            continue
        keywords = [item for item in record.get("keywords") or [] if isinstance(item, dict)]
        if not keywords:
            keywords = [{}]
        source_role = str(record.get("source_role") or "own").strip() or "own"
        data_date = _record_data_date(record)
        status = _record_status(record, snapshot_status=snapshot_status)
        for keyword_item in keywords:
            keyword = str(_value_from(keyword_item, KEYWORD_FIELDS["keyword"])).strip()
            row = {
                "report_date": report_day,
                "captured_at": captured_at,
                "marketplace": market,
                "sku": str(record.get("sku") or "").strip(),
                "asin": asin,
                "source_role": source_role,
                "parent_marketplace": str(record.get("parent_marketplace") or "").strip().upper(),
                "parent_sku": str(record.get("parent_sku") or "").strip(),
                "parent_asin": str(record.get("parent_asin") or "").strip().upper(),
                "seller_sprite_check_status": status,
                "data_date": data_date,
                "keyword": keyword,
                "normalized_keyword": normalize_keyword(keyword),
                "competitor_discovery_source": str(record.get("competitor_discovery_source") or "").strip(),
                "competitor_pool_confidence": str(record.get("competitor_pool_confidence") or "").strip(),
            }
            for output_key, aliases in KEYWORD_FIELDS.items():
                if output_key == "keyword":
                    continue
                row[output_key] = _value_from(keyword_item, aliases)
            rows.append(row)
    return rows


def _history_key(row: dict[str, object]) -> tuple[str, str, str, str, str, str]:
    return (
        str(row.get("report_date") or "").strip(),
        str(row.get("marketplace") or "").strip().upper(),
        str(row.get("asin") or "").strip().upper(),
        normalize_keyword(row.get("keyword") or row.get("normalized_keyword")),
        str(row.get("source_role") or "").strip(),
        str(row.get("parent_asin") or "").strip().upper(),
    )


def load_sellersprite_history(path: Path = SELLERSPRITE_HISTORY_PATH) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            if isinstance(item, dict):
                rows.append(item)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def write_sellersprite_history(rows: Iterable[dict[str, object]], path: Path = SELLERSPRITE_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(
        [dict(row) for row in rows if isinstance(row, dict)],
        key=lambda row: (
            str(row.get("report_date") or ""),
            str(row.get("marketplace") or ""),
            str(row.get("asin") or ""),
            str(row.get("source_role") or ""),
            str(row.get("parent_asin") or ""),
            str(row.get("normalized_keyword") or normalize_keyword(row.get("keyword"))),
        ),
    )
    payload = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items)
    path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def upsert_sellersprite_history(
    records: Iterable[dict],
    *,
    path: Path = SELLERSPRITE_HISTORY_PATH,
    report_date: str | date | None = None,
    snapshot_status: str | None = None,
    context_by_key: dict[tuple[str, str], dict] | None = None,
) -> list[dict[str, object]]:
    new_rows = history_rows_from_records(
        records,
        report_date=report_date,
        snapshot_status=snapshot_status,
        context_by_key=context_by_key,
    )
    if not new_rows:
        return []
    merged = {_history_key(row): row for row in load_sellersprite_history(path)}
    for row in new_rows:
        merged[_history_key(row)] = row
    write_sellersprite_history(merged.values(), path)
    return new_rows


def sellersprite_cache_max_age_days_for_row(row: dict, *, competitor_cache_days: int = 7) -> int:
    source_role = str(row.get("source_role") or "own").strip()
    if source_role != "competitor":
        return 0
    priority = str(row.get("priority") or row.get("parent_priority") or "").strip().upper()
    if priority in {"P0", "P1"}:
        return 0
    action_text = " ".join(
        str(row.get(field) or "")
        for field in ["suggested_action", "copy_action_line", "fusion_today_action", "parent_ad_action"]
    )
    if any(token in action_text for token in ["加价", "降竞价", "否定", "暂停", "小预算", "预算"]):
        return 0
    spend = _num(row.get("ad_spend") or row.get("spend") or row.get("parent_ad_spend"))
    if spend is not None and spend >= 20:
        return 0
    return max(0, int(competitor_cache_days))


def _keywords_by_day(rows: list[dict[str, object]]) -> dict[str, dict[str, dict[str, object]]]:
    by_day: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        keyword = normalize_keyword(row.get("keyword") or row.get("normalized_keyword"))
        day = str(row.get("report_date") or "").strip()
        if not keyword or not day:
            continue
        by_day.setdefault(day, {})[keyword] = row
    return by_day


def _display_keywords(rows: Iterable[dict[str, object]], norms: Iterable[str], *, limit: int = 8) -> str:
    lookup: dict[str, str] = {}
    for row in rows:
        norm = normalize_keyword(row.get("keyword") or row.get("normalized_keyword"))
        keyword = str(row.get("keyword") or "").strip()
        if norm and keyword:
            lookup.setdefault(norm, keyword)
    values = [lookup.get(norm, norm) for norm in norms if norm]
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return "、".join(unique[:limit])


def _latest_prior_day(by_day: dict[str, dict[str, dict[str, object]]], report_day: str) -> str:
    days = sorted(day for day in by_day if day < report_day)
    return days[-1] if days else ""


def _metric_changes(
    today_rows: dict[str, dict[str, object]],
    prior_rows: dict[str, dict[str, object]],
    metric: str,
    *,
    lower_is_better: bool,
) -> tuple[list[str], list[str]]:
    improved: list[str] = []
    declined: list[str] = []
    for norm, today_row in today_rows.items():
        prior_row = prior_rows.get(norm)
        if not prior_row:
            continue
        current = _num(today_row.get(metric))
        previous = _num(prior_row.get(metric))
        if current is None or previous is None or current == previous:
            continue
        if lower_is_better:
            if current < previous:
                improved.append(norm)
            else:
                declined.append(norm)
        else:
            if current > previous:
                improved.append(norm)
            else:
                declined.append(norm)
    return improved, declined


def _own_status_for_report(record: dict | None, own_rows: list[dict[str, object]], report_day: str) -> tuple[str, str]:
    today_rows = [row for row in own_rows if str(row.get("report_date") or "") == report_day]
    latest_data_date = ""
    if record:
        latest_data_date = _record_data_date(record)
    if not latest_data_date:
        latest_data_date = max((str(row.get("data_date") or "") for row in own_rows), default="")

    if record and latest_data_date == report_day and _successful_status(_record_status(record)):
        return "今日已抓", latest_data_date

    today_success_dates = {
        str(row.get("data_date") or "")
        for row in today_rows
        if _successful_status(row.get("seller_sprite_check_status")) and str(row.get("data_date") or "")
    }
    if report_day in today_success_dates:
        return "今日已抓", latest_data_date or report_day

    statuses = {str(row.get("seller_sprite_check_status") or "") for row in today_rows}
    if any("失败" in status for status in statuses):
        return "失败", latest_data_date
    if today_rows:
        data_dates = {str(row.get("data_date") or "") for row in today_rows if str(row.get("data_date") or "")}
        if "沿用缓存" in statuses or (data_dates and report_day not in data_dates):
            return "沿用缓存", latest_data_date
        if any(status == "已抓取" for status in statuses):
            return "今日已抓", latest_data_date
    if record:
        if latest_data_date == report_day:
            return "今日已抓", latest_data_date
        return "沿用缓存", latest_data_date
    return "待补", latest_data_date


def build_sellersprite_history_summary(
    product_row: dict,
    *,
    own_record: dict | None = None,
    target_asins: Iterable[str] | None = None,
    history_rows: list[dict[str, object]] | None = None,
    report_date: str | date | None = None,
) -> dict[str, object]:
    report_day = _effective_report_day(report_date, own_record)
    report_dt = _parse_date(report_day) or date.today()
    window_start = (report_dt - timedelta(days=6)).isoformat()
    market = str(product_row.get("marketplace") or "").strip().upper()
    asin = str(product_row.get("asin") or "").strip().upper()
    history = history_rows if history_rows is not None else load_sellersprite_history()
    own_rows = [
        row
        for row in history
        if str(row.get("marketplace") or "").strip().upper() == market
        and str(row.get("asin") or "").strip().upper() == asin
        and str(row.get("source_role") or "own") == "own"
        and window_start <= str(row.get("report_date") or "") <= report_day
    ]
    by_day = _keywords_by_day(own_rows)
    today_keywords = by_day.get(report_day, {})
    prior_day = _latest_prior_day(by_day, report_day)
    prior_keywords = by_day.get(prior_day, {})
    historical_keyword_days: dict[str, set[str]] = {}
    for day, rows_by_keyword in by_day.items():
        for norm in rows_by_keyword:
            historical_keyword_days.setdefault(norm, set()).add(day)
    persistent_norms = sorted(norm for norm, days in historical_keyword_days.items() if len(days) >= 3)
    previous_norms = set(prior_keywords)
    today_norms = set(today_keywords)
    new_norms = sorted(today_norms - set().union(*(set(rows) for day, rows in by_day.items() if day < report_day), set()))
    lost_norms = sorted(previous_norms - today_norms) if today_keywords else []
    rank_improved, rank_declined = _metric_changes(today_keywords, prior_keywords, "natural_rank", lower_is_better=True)
    ppc_up, ppc_down = _metric_changes(today_keywords, prior_keywords, "ppc", lower_is_better=False)
    status, cache_date = _own_status_for_report(own_record, own_rows, report_day)
    history_days = len({str(row.get("report_date") or "") for row in own_rows if normalize_keyword(row.get("keyword"))})
    if history_days >= 7:
        trend_status = "7天趋势可用"
    elif history_days >= 3:
        trend_status = "3天趋势可用"
    elif status == "沿用缓存":
        trend_status = "沿用缓存"
    elif history_days == 1:
        trend_status = "仅当日"
    else:
        trend_status = "无历史"
    if status == "今日已抓" and history_days >= 3:
        evidence_tier = "今日趋势证据"
    elif status == "今日已抓":
        evidence_tier = "今日单日证据"
    elif status == "沿用缓存":
        evidence_tier = "历史缓存参考"
    else:
        evidence_tier = "证据不足"

    target_set = {str(asin_item or "").strip().upper() for asin_item in target_asins or [] if str(asin_item or "").strip()}
    competitor_rows = [
        row
        for row in history
        if str(row.get("marketplace") or "").strip().upper() == market
        and str(row.get("source_role") or "") == "competitor"
        and str(row.get("parent_asin") or "").strip().upper() == asin
        and window_start <= str(row.get("report_date") or "") <= report_day
    ]
    if target_set:
        competitor_rows = [
            row for row in competitor_rows if str(row.get("asin") or "").strip().upper() in target_set
        ]
    competitor_days_by_asin: dict[str, set[str]] = {}
    competitor_keyword_days: dict[str, set[str]] = {}
    for row in competitor_rows:
        comp_asin = str(row.get("asin") or "").strip().upper()
        day = str(row.get("report_date") or "").strip()
        keyword = normalize_keyword(row.get("keyword") or row.get("normalized_keyword"))
        if comp_asin and day:
            competitor_days_by_asin.setdefault(comp_asin, set()).add(day)
        if keyword and day:
            competitor_keyword_days.setdefault(keyword, set()).add(day)
    stable_asins = sorted(asin_item for asin_item, days in competitor_days_by_asin.items() if len(days) >= 3)
    stable_overlap_norms = sorted(norm for norm, days in competitor_keyword_days.items() if len(days) >= 3)
    own_known_norms = set(today_keywords) | set(persistent_norms)
    missing_trend_norms = [norm for norm in stable_overlap_norms if norm not in own_known_norms]
    if stable_asins and missing_trend_norms:
        pressure_trend = "持续高"
    elif stable_asins:
        pressure_trend = "稳定"
    elif competitor_rows:
        pressure_trend = "观察"
    else:
        pressure_trend = "无趋势"
    return {
        "sellersprite_today_status": status,
        "sellersprite_cache_date": cache_date,
        "sellersprite_history_days": history_days,
        "sellersprite_trend_status": trend_status,
        "sellersprite_new_keywords": _display_keywords(own_rows, new_norms, limit=8),
        "sellersprite_persistent_keywords": _display_keywords(own_rows, persistent_norms, limit=8),
        "sellersprite_lost_keywords": _display_keywords(own_rows, lost_norms, limit=8),
        "sellersprite_rank_improved_keywords": _display_keywords(own_rows, rank_improved, limit=8),
        "sellersprite_rank_declined_keywords": _display_keywords(own_rows, rank_declined, limit=8),
        "sellersprite_ppc_up_keywords": _display_keywords(own_rows, ppc_up, limit=8),
        "sellersprite_ppc_down_keywords": _display_keywords(own_rows, ppc_down, limit=8),
        "competitor_stable_asins": "、".join(stable_asins[:3]),
        "competitor_stable_keyword_overlap": _display_keywords(competitor_rows, stable_overlap_norms, limit=8),
        "competitor_pressure_trend": pressure_trend,
        "own_missing_competitor_keywords_trend": _display_keywords(competitor_rows, missing_trend_norms, limit=8),
        "sellersprite_evidence_tier": evidence_tier,
    }
