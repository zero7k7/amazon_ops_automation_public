from __future__ import annotations

import html
import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH = OUTPUT_DIR / "sellersprite_competitor_discovery_results.json"

SELLERSPRITE_MARKET_IDS = {
    "US": 1,
    "UK": 3,
    "DE": 4,
}

DISCOVERY_SOURCE_PRIORITY = {
    "sellersprite_competitor_direct": 6,
    "sellersprite_reversing_sources": 5,
    "sellersprite_relation_keyword": 4,
    "sellersprite_traffic_extend": 4,
    "sellersprite_keyword_reverse_seed": 2,
}

SUCCESS_STATUSES = {"已抓取", "沿用缓存", "缓存"}


def sellersprite_market_id(marketplace: str) -> int:
    code = str(marketplace or "").strip().upper()
    if code not in SELLERSPRITE_MARKET_IDS:
        raise ValueError(f"unsupported SellerSprite marketplace: {marketplace}")
    return SELLERSPRITE_MARKET_IDS[code]


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def _asin_text(value: object) -> str:
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"B0[A-Z0-9]{8}", text) else ""


def _record_key(record: dict) -> tuple[str, str, str]:
    return (
        str(record.get("marketplace") or "").strip().upper(),
        str(record.get("sku") or "").strip(),
        str(record.get("asin") or "").strip().upper(),
    )


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _latest_date(record: dict) -> str:
    for key in ["data_date", "checked_at", "generated_at"]:
        value = str(record.get(key) or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", value):
            return value[:10]
    return ""


def _is_recent(record: dict, *, max_age_days: int = 7) -> bool:
    data_date = _parse_date(record.get("data_date") or record.get("checked_at"))
    if data_date is None:
        return False
    return (datetime.now().date() - data_date).days <= max_age_days


def _record_success(record: dict) -> bool:
    status = str(record.get("competitor_discovery_status") or record.get("status") or "").strip()
    competitors = record.get("competitors")
    return status in SUCCESS_STATUSES and isinstance(competitors, list) and bool(competitors)


def _is_amazon_search_seed_record(record: dict) -> bool:
    if str(record.get("source_page") or "").strip() == "amazon_search_seed":
        return True
    return any(
        isinstance(item, dict) and str(item.get("source_page") or "").strip() == "amazon_search_seed"
        for item in record.get("competitors") or []
    )


def _with_amazon_search_seed(record: dict, seed_record: dict | None) -> dict:
    if not seed_record or not _record_success(seed_record):
        return dict(record)
    copied = dict(record)
    copied["amazon_search_seed_status"] = seed_record.get("competitor_discovery_status") or ""
    copied["amazon_search_seed_source_page"] = seed_record.get("source_page") or ""
    copied["amazon_search_seed_checked_at"] = seed_record.get("checked_at") or ""
    copied["amazon_search_seed_data_date"] = seed_record.get("data_date") or ""
    copied["amazon_search_seed_competitors"] = list(seed_record.get("competitors") or [])
    return copied


def _source_priority(source: str) -> int:
    return DISCOVERY_SOURCE_PRIORITY.get(str(source or "").strip(), 0)


def _confidence_priority(confidence: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(confidence or "").strip().lower(), 0)


def _competitor_sort_key(item: dict) -> tuple[int, int, int, int]:
    source = str(item.get("competitor_source") or "").strip()
    confidence = str(item.get("confidence") or "").strip().lower()
    overlap = int(float(str(item.get("overlap_keyword_count") or "0") or 0))
    order = int(float(str(item.get("_discovery_order") or "0") or 0))
    return (_source_priority(source), _confidence_priority(confidence), overlap, -order)


def _html_to_text(value: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:td|th|div|span|p|li|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return _norm(html.unescape(text))


def _row_texts_from_html(html_text: str) -> list[str]:
    rows: list[str] = []
    for pattern in [
        r"<tr\b[^>]*>.*?</tr>",
        r"<(?:div|li)\b[^>]*class=[\"'][^\"']*(?:row|item|vxe|table|product|competitor)[^\"']*[\"'][^>]*>.*?</(?:div|li)>",
    ]:
        for match in re.finditer(pattern, html_text, flags=re.I | re.S):
            text = _html_to_text(match.group(0))
            if text and text not in rows:
                rows.append(text)
    full_text = _html_to_text(html_text)
    for line in re.split(r"(?:\n|\s{3,})", full_text):
        text = _norm(line)
        if text and text not in rows:
            rows.append(text)
    return rows


def _infer_empty_reason(text: str) -> str:
    if re.search(r"未登录|游客|login|sign in", text, flags=re.I):
        return "未登录"
    if re.search(r"无权限|权限|升级|购买|套餐|会员|permission|upgrade", text, flags=re.I):
        return "页面无权限"
    if re.search(r"无数据|暂无数据|没有数据|未找到|0\s*条结果|no data|no result", text, flags=re.I):
        return "无竞品数据"
    return "表格解析失败"


def _title_from_context(context: str, asin: str) -> str:
    text = _norm(context.replace(asin, " "))
    text = re.sub(r"\b[A-Z0-9]{10}\b", " ", text)
    text = re.sub(r"\b(?:ASIN|BSR|PPC|SPR)\b[:：]?", " ", text, flags=re.I)
    text = _norm(text)
    if len(text) > 120:
        text = text[:120].rstrip()
    return text


def normalize_competitors(
    competitors: Iterable[dict],
    *,
    marketplace: str,
    sku: str,
    asin: str,
    checked_at: str,
    data_date: str,
    limit: int = 3,
) -> list[dict]:
    own_asin = _asin_text(asin)
    market = str(marketplace or "").strip().upper()
    sku_text = str(sku or "").strip()
    candidates: dict[str, dict] = {}
    for index, raw in enumerate(competitors):
        comp_asin = _asin_text(raw.get("competitor_asin") or raw.get("asin"))
        if not comp_asin or comp_asin == own_asin:
            continue
        item = {
            "marketplace": market,
            "sku": sku_text,
            "asin": own_asin,
            "competitor_asin": comp_asin,
            "competitor_title": _norm(raw.get("competitor_title") or raw.get("title") or ""),
            "competitor_source": str(raw.get("competitor_source") or raw.get("source") or "").strip(),
            "source_page": str(raw.get("source_page") or "").strip(),
            "source_keyword": _norm(raw.get("source_keyword") or ""),
            "overlap_keyword_count": int(float(str(raw.get("overlap_keyword_count") or "0") or 0)),
            "traffic_or_rank_hint": _norm(raw.get("traffic_or_rank_hint") or raw.get("traffic") or ""),
            "confidence": str(raw.get("confidence") or "low").strip().lower(),
            "checked_at": checked_at,
            "data_date": data_date,
            "last_error": str(raw.get("last_error") or "").strip(),
            "_discovery_order": int(float(str(raw.get("discovery_order") or index) or 0)),
        }
        current = candidates.get(comp_asin)
        if current is None or _competitor_sort_key(item) > _competitor_sort_key(current):
            candidates[comp_asin] = item
    limited = sorted(candidates.values(), key=_competitor_sort_key, reverse=True)[:limit]
    for item in limited:
        item.pop("_discovery_order", None)
    return limited


def parse_competitors_from_html(
    html_text: str,
    *,
    marketplace: str,
    sku: str,
    asin: str,
    source_page: str,
    competitor_source: str,
    checked_at: str | None = None,
    limit: int = 3,
) -> tuple[list[dict], str]:
    checked = checked_at or datetime.now().isoformat(timespec="seconds")
    data_date = checked.split("T", 1)[0]
    own_asin = _asin_text(asin)
    text = _html_to_text(html_text)
    raw_competitors: list[dict] = []
    for row_text in _row_texts_from_html(html_text):
        for comp_asin in re.findall(r"\bB0[A-Z0-9]{8}\b", row_text.upper()):
            if comp_asin == own_asin:
                continue
            raw_competitors.append(
                {
                    "competitor_asin": comp_asin,
                    "competitor_title": _title_from_context(row_text, comp_asin),
                    "competitor_source": competitor_source,
                    "source_page": source_page,
                    "confidence": (
                        "medium"
                        if competitor_source
                        in {
                            "sellersprite_competitor_direct",
                            "sellersprite_reversing_sources",
                            "sellersprite_relation_keyword",
                            "sellersprite_traffic_extend",
                        }
                        else "low"
                    ),
                }
            )
    competitors = normalize_competitors(
        raw_competitors,
        marketplace=marketplace,
        sku=sku,
        asin=asin,
        checked_at=checked,
        data_date=data_date,
        limit=limit,
    )
    if competitors:
        return competitors, ""
    return [], _infer_empty_reason(text)


def make_discovery_record(
    row: dict,
    *,
    competitors: list[dict],
    status: str,
    source_page: str = "",
    checked_at: str | None = None,
    last_error: str = "",
) -> dict:
    checked = checked_at or datetime.now().isoformat(timespec="seconds")
    return {
        "marketplace": str(row.get("marketplace") or "").strip().upper(),
        "sku": str(row.get("sku") or "").strip(),
        "asin": str(row.get("asin") or "").strip().upper(),
        "product_name": row.get("product_name") or "",
        "competitor_discovery_status": status,
        "source_page": source_page,
        "checked_at": checked,
        "data_date": checked.split("T", 1)[0],
        "competitor_count": len(competitors),
        "competitors": competitors,
        "last_error": last_error,
    }


def load_competitor_discovery_records(
    path: Path = SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
    *,
    max_age_days: int = 7,
) -> dict[tuple[str, str, str], dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return {}
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for record in raw:
        if not isinstance(record, dict):
            continue
        key = _record_key(record)
        if not key[0] or not key[2]:
            continue
        grouped.setdefault(key, []).append(record)
    latest: dict[tuple[str, str, str], dict] = {}
    for key, records in grouped.items():
        records = sorted(records, key=_latest_date)
        latest_seed = next(
            (
                record
                for record in reversed(records)
                if _is_amazon_search_seed_record(record)
                and _record_success(record)
                and _is_recent(record, max_age_days=max_age_days)
            ),
            None,
        )
        latest_primary_success = next(
            (
                record
                for record in reversed(records)
                if not _is_amazon_search_seed_record(record)
                and _record_success(record)
                and _is_recent(record, max_age_days=max_age_days)
            ),
            None,
        )
        latest_success = latest_primary_success or latest_seed
        if latest_success:
            latest[key] = _with_amazon_search_seed(latest_success, latest_seed)
            continue
        latest_failure = records[-1]
        if _is_recent(latest_failure, max_age_days=max_age_days):
            latest[key] = _with_amazon_search_seed(latest_failure, latest_seed)

    return latest


def merge_competitor_discovery_records(
    records: Iterable[dict],
    path: Path = SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
) -> None:
    existing: list[dict] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("items", payload) if isinstance(payload, dict) else payload
            if isinstance(raw, list):
                existing = [item for item in raw if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            existing = []
    merged: dict[tuple[str, str, str, str, str, str], dict] = {}
    for record in [*existing, *records]:
        key_base = _record_key(record)
        status = str(record.get("competitor_discovery_status") or "").strip()
        source_page = str(record.get("source_page") or "").strip()
        key = (*key_base, _latest_date(record), status, source_page)
        if key[0] and key[2]:
            merged[key] = record
    items = sorted(merged.values(), key=lambda item: (*_record_key(item), _latest_date(item)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": "sellersprite_competitor_discovery",
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def discovery_record_needs_refresh(record: dict | None, *, max_age_days: int = 7) -> bool:
    if not record:
        return True
    return not (_record_success(record) and _is_recent(record, max_age_days=max_age_days))
