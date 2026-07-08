from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Iterable

from src.sellersprite_competitor_discovery import (
    SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
    load_competitor_discovery_records,
)
from src.sellersprite_history import (
    HISTORY_TREND_FIELDS,
    SELLERSPRITE_HISTORY_PATH,
    build_sellersprite_history_summary,
    load_sellersprite_history,
)
from src.market_survey_completeness import (
    MARKET_SURVEY_COMPLETENESS_FIELDS,
    enrich_market_survey_completeness,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
SELLERSPRITE_CACHE_PATH = OUTPUT_DIR / "sellersprite_reverse_asin_results.json"

FUSION_COLUMNS = [
    "marketplace",
    "sku",
    "asin",
    "keyword",
    "normalized_keyword",
    "ad_clicks",
    "ad_spend",
    "ad_orders",
    "ad_sales",
    "ad_acos",
    "campaign_name",
    "ad_group_name",
    "match_type",
    "targeting",
    "seller_sprite_match_status",
    "seller_sprite_data_date",
    "seller_sprite_traffic_share",
    "seller_sprite_monthly_searches",
    "seller_sprite_purchases",
    "seller_sprite_purchase_rate",
    "seller_sprite_natural_rank",
    "seller_sprite_spr",
    "seller_sprite_ppc",
    "seller_sprite_competition_level",
    "seller_sprite_keyword_bucket",
    "seller_sprite_ads_fusion_label",
    "seller_sprite_fusion_reason",
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
    "comparable_competitor_count",
    "amazon_search_validation_status",
    "amazon_search_visible_competitors",
    "competitor_sellersprite_status",
    "competitor_sellersprite_asin_count",
    "competitor_sellersprite_keyword_count",
    "competitor_keyword_pressure",
    "frontend_competitiveness",
    "seller_sprite_ppc_missing_count",
    "seller_sprite_monthly_searches_missing_count",
    "seller_sprite_traffic_share_placeholder_count",
    "competitor_sellersprite_ppc_missing_count",
    "competitor_sellersprite_monthly_searches_missing_count",
    "competitor_sellersprite_traffic_share_placeholder_count",
    *MARKET_SURVEY_COMPLETENESS_FIELDS,
    *HISTORY_TREND_FIELDS,
]


def normalize_keyword(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text or text in {"--", "-", "N/A"}:
        return None
    pct = "%" in text
    match = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    return number / 100 if pct else number


def _money(value: object) -> float | None:
    return _num(value)


def _latest_data_date(record: dict) -> str:
    for key in ("data_date", "checked_at", "generated_at"):
        value = str(record.get(key) or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", value):
            return value[:10]
    return ""


def _record_freshness_key(record: dict) -> tuple[str, str, int]:
    timestamp = ""
    for key in ("checked_at", "generated_at", "captured_at"):
        value = str(record.get(key) or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", value):
            timestamp = value
            break
    keyword_count = len([item for item in record.get("keywords") or [] if isinstance(item, dict) and _keyword_text(item)])
    return (_latest_data_date(record), timestamp, keyword_count)


def _record_success(record: dict) -> bool:
    status = str(record.get("seller_sprite_check_status") or record.get("status") or "").strip()
    if status not in {"已抓取", "沿用缓存"}:
        return False
    return bool(record.get("keywords"))


def _record_key(record: dict) -> tuple[str, str]:
    return (
        str(record.get("marketplace") or "").strip().upper(),
        str(record.get("asin") or "").strip().upper(),
    )


def _asin_text(value: object) -> str:
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"[A-Z0-9]{10}", text) else ""


def load_sellersprite_records(path: Path = SELLERSPRITE_CACHE_PATH) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    records = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return {}
    latest: dict[tuple[str, str], dict] = {}
    for record in records:
        if not isinstance(record, dict) or not _record_success(record):
            continue
        key = _record_key(record)
        if not key[0] or not key[1]:
            continue
        current = latest.get(key)
        if current is None or _record_freshness_key(record) >= _record_freshness_key(current):
            latest[key] = record
    return latest


def merge_sellersprite_records(records: Iterable[dict], path: Path = SELLERSPRITE_CACHE_PATH) -> None:
    existing: list[dict] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("items", payload) if isinstance(payload, dict) else payload
            if isinstance(raw, list):
                existing = [item for item in raw if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            existing = []
    merged: dict[tuple[str, str, str], dict] = {}
    for record in [*existing, *records]:
        key = (*_record_key(record), _latest_data_date(record))
        if key[0] and key[1]:
            previous = merged.get(key)
            if previous and _record_success(previous) and not _record_success(record):
                continue
            merged[key] = record
    items = sorted(
        merged.values(),
        key=lambda item: (_record_key(item)[0], _record_key(item)[1], _latest_data_date(item)),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": "sellersprite_reverse_asin",
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _keywords_by_normalized(record: dict) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for item in record.get("keywords") or []:
        if not isinstance(item, dict):
            continue
        keyword = normalize_keyword(item.get("keyword") or item.get("流量词"))
        if keyword:
            lookup[keyword] = item
    return lookup


def _keyword_tokens(value: str) -> list[str]:
    return [token for token in normalize_keyword(value).split() if token]


def _match_seller_keyword(normalized: str, record: dict) -> tuple[dict | None, str]:
    if not normalized:
        return None, "未命中"
    lookup = _keywords_by_normalized(record)
    exact = lookup.get(normalized)
    if exact:
        return exact, "已命中"
    term_tokens = _keyword_tokens(normalized)
    if len(term_tokens) < 3:
        return None, "未命中"
    candidates: list[tuple[int, dict]] = []
    normalized_with_spaces = f" {normalized} "
    for seller_normalized, item in lookup.items():
        seller_tokens = _keyword_tokens(seller_normalized)
        if len(seller_tokens) < 3:
            continue
        seller_with_spaces = f" {seller_normalized} "
        if seller_with_spaces in normalized_with_spaces or normalized_with_spaces in seller_with_spaces:
            candidates.append((len(seller_tokens), item))
    if not candidates:
        return None, "未命中"
    return sorted(candidates, key=lambda pair: pair[0], reverse=True)[0][1], "近似命中"


def _seller_number(item: dict, *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        number = _num(value)
        if number is not None:
            return number
    return None


def _competition_level(item: dict) -> str:
    ppc = _seller_number(item, "ppc", "seller_sprite_ppc", "PPC价格")
    spr = _seller_number(item, "spr", "seller_sprite_spr", "SPR")
    products = _seller_number(item, "products", "product_count", "商品数")
    ad_products = _seller_number(item, "ad_products", "广告竞品数")
    concentration = _seller_number(item, "conversion_share", "转化总占比")
    high_signals = 0
    if ppc is not None and ppc >= 1.5:
        high_signals += 1
    if spr is not None and spr >= 10:
        high_signals += 1
    if products is not None and products >= 10000:
        high_signals += 1
    if ad_products is not None and ad_products >= 80:
        high_signals += 1
    if concentration is not None and concentration >= 0.5:
        high_signals += 1
    if high_signals >= 2:
        return "高竞争"
    if high_signals == 1:
        return "中竞争"
    return "低竞争"


def _keyword_bucket(item: dict, competition: str) -> str:
    monthly = _seller_number(item, "monthly_searches", "月搜索量")
    purchases = _seller_number(item, "purchases", "购买量")
    purchase_rate = _seller_number(item, "purchase_rate", "购买率")
    if monthly is None and purchases is None:
        return "样本不足"
    if (monthly or 0) < 300 and (purchases or 0) < 10:
        return "低质量"
    if competition == "高竞争":
        return "相关高竞争"
    if (monthly or 0) >= 500 and ((purchases or 0) >= 20 or (purchase_rate or 0) >= 0.02):
        return "可测核心词"
    return "样本不足"


def _fusion_label(row: dict, matched: dict | None, bucket: str, competition: str) -> tuple[str, str]:
    clicks = _num(row.get("clicks") or row.get("ad_clicks")) or 0
    spend = _money(row.get("spend") or row.get("ad_spend")) or 0
    orders = _num(row.get("orders") or row.get("ad_orders")) or 0
    if orders > 0:
        return "已验证有效", "账号广告已有订单，按账号成交证据优先。"
    if not matched:
        if clicks >= 5 or spend >= 5:
            return "无反查匹配需控费", "账号内有消耗但未命中卖家精灵反查词，先按广告表现保守控费。"
        return "无反查匹配", "未命中卖家精灵反查词，不能用市场反查证明机会。"
    if clicks >= 8 or spend >= 5:
        if bucket in {"低质量", "样本不足"}:
            return "低质量需控费", f"广告已有点击或花费但无单，卖家精灵归类为{bucket}。"
        if competition in {"高竞争", "中竞争"}:
            return "相关但需降竞价", f"市场有需求但竞争为{competition}，账号内暂无订单。"
        return "相关但需降竞价", "市场需求存在，但账号内点击或花费未验证成交。"
    if bucket == "可测核心词":
        return "可小预算测试", "卖家精灵显示有需求，账号内样本不足，只能小预算精准测试。"
    if bucket == "相关高竞争":
        return "高竞争观察", "市场需求存在但竞争成本偏高，先观察或低竞价测试。"
    if bucket == "低质量":
        return "低质量", "市场搜索或购买证据弱。"
    return "样本不足", "卖家精灵关键字段不足，作为背景参考。"


def _seller_value(item: dict, *keys: str) -> object:
    for key in keys:
        if item.get(key) not in (None, ""):
            return item.get(key)
    return ""


def _keyword_text(item: dict) -> str:
    return str(item.get("keyword") or item.get("流量词") or "").strip()


def _keyword_sort_key(item: dict) -> tuple[float, float, float]:
    return (
        _seller_number(item, "purchases", "购买量") or 0,
        _seller_number(item, "monthly_searches", "月搜索量") or 0,
        _seller_number(item, "traffic_share", "流量占比") or 0,
    )


def _top_keyword_items(record: dict, *, limit: int = 8) -> list[dict]:
    keywords = [item for item in record.get("keywords") or [] if isinstance(item, dict) and _keyword_text(item)]
    return sorted(keywords, key=_keyword_sort_key, reverse=True)[:limit]


def _keyword_quality_counts(record: dict | None) -> dict[str, int]:
    keywords = [item for item in (record or {}).get("keywords") or [] if isinstance(item, dict) and _keyword_text(item)]
    ppc_missing = 0
    monthly_missing = 0
    traffic_placeholder = 0
    for item in keywords:
        if _seller_number(item, "ppc", "PPC价格", "PPC竞价") is None:
            ppc_missing += 1
        if _seller_number(item, "monthly_searches", "月搜索量") is None:
            monthly_missing += 1
        traffic = str(_seller_value(item, "traffic_share", "流量占比") or "").strip()
        if not traffic or traffic in {"-", "--", "N/A", "0", "0.00%", "0%"}:
            traffic_placeholder += 1
    return {
        "ppc_missing_count": ppc_missing,
        "monthly_searches_missing_count": monthly_missing,
        "traffic_share_placeholder_count": traffic_placeholder,
    }


def _combined_keyword_quality_counts(records: Iterable[dict]) -> dict[str, int]:
    total = {
        "ppc_missing_count": 0,
        "monthly_searches_missing_count": 0,
        "traffic_share_placeholder_count": 0,
    }
    for record in records:
        counts = _keyword_quality_counts(record)
        for key in total:
            total[key] += counts.get(key, 0)
    return total


def _top_keywords_text(record: dict, *, limit: int = 8) -> str:
    return "、".join(_keyword_text(item) for item in _top_keyword_items(record, limit=limit))


def _strong_keyword(item: dict) -> bool:
    monthly = _seller_number(item, "monthly_searches", "月搜索量") or 0
    purchases = _seller_number(item, "purchases", "购买量") or 0
    purchase_rate = _seller_number(item, "purchase_rate", "购买率") or 0
    spr = _seller_number(item, "spr", "SPR") or 0
    return monthly >= 500 or purchases >= 20 or purchase_rate >= 0.02 or spr >= 8


NOISE_KEYWORD_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "best",
    "by",
    "for",
    "from",
    "home",
    "house",
    "in",
    "item",
    "items",
    "kitchen",
    "large",
    "new",
    "of",
    "on",
    "pack",
    "premium",
    "product",
    "products",
    "set",
    "small",
    "supplies",
    "the",
    "to",
    "tool",
    "tools",
    "with",
}

SELLERSPRITE_SHELL_TITLE_MARKERS = (
    "sellersprite",
    "sellersprite_logo",
    "group created with sketch",
    "查流量来源",
    "卖家精灵",
)


def _meaningful_tokens(value: object) -> set[str]:
    tokens: set[str] = set()
    for token in normalize_keyword(value).split():
        if len(token) < 3 or token.isdigit() or token in NOISE_KEYWORD_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _own_product_tokens(own_keywords: dict[str, dict]) -> set[str]:
    tokens: set[str] = set()
    for item in own_keywords.values():
        tokens.update(_meaningful_tokens(_keyword_text(item)))
    return tokens


def _invalid_competitor_title(title: object) -> bool:
    text = str(title or "").strip()
    if not text:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in SELLERSPRITE_SHELL_TITLE_MARKERS)


def _candidate_keyword_sample(record: dict, *, limit: int = 8) -> list[str]:
    if not record:
        return []
    return [_keyword_text(item) for item in _top_keyword_items(record, limit=limit) if _keyword_text(item)]


def _candidate_related_tokens(candidate: dict[str, object], own_tokens: set[str]) -> set[str]:
    text_parts: list[str] = [
        str(candidate.get("title") or ""),
        str(candidate.get("source_keyword") or ""),
        str(candidate.get("traffic") or ""),
    ]
    text_parts.extend(str(item) for item in candidate.get("candidate_keywords") or [] if str(item).strip())
    tokens: set[str] = set()
    for text in text_parts:
        tokens.update(_meaningful_tokens(text))
    return own_tokens.intersection(tokens)


def _candidate_rejection_reason(candidate: dict[str, object], own_tokens: set[str]) -> str:
    title = str(candidate.get("title") or "")
    if _invalid_competitor_title(title):
        return "标题为空或页面壳文本"
    overlap_count = int(_num(candidate.get("overlap_count")) or 0)
    amazon_visible = bool(candidate.get("amazon_visible"))
    has_reverse = bool(candidate.get("has_reverse"))
    source_keyword = str(candidate.get("source_keyword") or "").strip()
    related_tokens = _candidate_related_tokens(candidate, own_tokens)
    if overlap_count <= 0 and not amazon_visible and not related_tokens:
        return "无共同关键词且 Amazon 未验证"
    if has_reverse and overlap_count <= 0 and not related_tokens:
        return "竞品反查词属于其他类目"
    if source_keyword and not _meaningful_tokens(source_keyword).intersection(own_tokens) and overlap_count <= 0:
        return "来源词与本产品核心词不相关"
    if amazon_visible and not related_tokens and overlap_count <= 0:
        return "Amazon 可见但标题/反查词不相关"
    return ""


def _candidate_effective_confidence(candidate: dict[str, object], own_tokens: set[str]) -> str:
    overlap_count = int(_num(candidate.get("overlap_count")) or 0)
    amazon_visible = bool(candidate.get("amazon_visible"))
    if overlap_count >= 2 or amazon_visible:
        return "high"
    if overlap_count >= 1:
        return "medium"
    if _candidate_related_tokens(candidate, own_tokens):
        return "medium"
    return "low"


def _rejection_summary(rejected: list[dict[str, object]]) -> str:
    counts: dict[str, int] = {}
    for item in rejected:
        reason = str(item.get("rejection_reason") or "").strip()
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    parts = [
        f"{reason} {count}"
        for reason, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    return "；".join(parts[:3])


def _value_list_text(values: Iterable[str], *, limit: int = 8) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "、".join(seen)


def _parse_competitors(row: dict) -> list[dict]:
    raw = row.get("frontend_competitors")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _competitor_is_ad(item: dict) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ["sponsored", "is_sponsored", "ad", "badge", "label"]).lower()
    return any(token in text for token in ["sponsored", "广告", "ad", "true", "是"])


def _competitor_asins(row: dict, *, limit: int = 3) -> list[str]:
    asins: list[str] = []
    own_asin = str(row.get("asin") or "").strip().upper()
    for item in _parse_competitors(row):
        asin = _asin_text(item.get("asin") or item.get("ASIN") or "")
        if not asin or asin == own_asin or _competitor_is_ad(item):
            continue
        if asin not in asins:
            asins.append(asin)
        if len(asins) >= limit:
            break
    return asins


def _dedupe_asins(values: Iterable[object], *, own_asin: str = "", limit: int = 10) -> list[str]:
    asins: list[str] = []
    own = _asin_text(own_asin)
    for value in values:
        asin = _asin_text(value)
        if not asin or asin == own or asin in asins:
            continue
        asins.append(asin)
        if len(asins) >= limit:
            break
    return asins


def _asins_from_text(value: object, *, own_asin: str = "", limit: int = 10) -> list[str]:
    return _dedupe_asins(re.findall(r"\bB0[A-Z0-9]{8}\b", str(value or "").upper()), own_asin=own_asin, limit=limit)


def _amazon_search_seed_asins(discovery_record: dict, *, own_asin: str = "", limit: int = 10) -> list[str]:
    raw_competitors = discovery_record.get("amazon_search_seed_competitors")
    if not isinstance(raw_competitors, list) and str(discovery_record.get("source_page") or "").strip() == "amazon_search_seed":
        raw_competitors = discovery_record.get("competitors")
    if not isinstance(raw_competitors, list):
        return []
    return _dedupe_asins(
        (
            item.get("competitor_asin") or item.get("asin")
            for item in raw_competitors
            if isinstance(item, dict)
        ),
        own_asin=own_asin,
        limit=limit,
    )


def _discovery_competitor_items(discovery_record: dict) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source_items in [discovery_record.get("competitors"), discovery_record.get("amazon_search_seed_competitors")]:
        if not isinstance(source_items, list):
            continue
        for item in source_items:
            if not isinstance(item, dict):
                continue
            asin = _asin_text(item.get("competitor_asin") or item.get("asin"))
            source = str(item.get("competitor_source") or item.get("source") or "").strip()
            key = (asin, source)
            if not asin or key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def _direct_competitor_entries(record: dict) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    if not record:
        return entries
    for field in ["competitor_pool", "competitors", "related_competitors", "competitor_asins"]:
        raw = record.get(field)
        if not raw:
            continue
        values: list[object]
        if isinstance(raw, list):
            values = raw
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            values = parsed if isinstance(parsed, list) else re.findall(r"[A-Z0-9]{10}", raw.upper())
        else:
            continue
        for item in values:
            if isinstance(item, dict):
                asin = _asin_text(item.get("asin") or item.get("ASIN") or item.get("competitor_asin"))
                if not asin:
                    continue
                entries.append(
                    {
                        "asin": asin,
                        "title": item.get("title") or item.get("product_name") or item.get("name") or "",
                        "source_keyword": item.get("keyword") or item.get("source_keyword") or item.get("来源词") or "",
                        "traffic": item.get("traffic") or item.get("traffic_share") or item.get("流量") or "",
                    }
                )
            else:
                asin = _asin_text(item)
                if asin:
                    entries.append({"asin": asin, "title": "", "source_keyword": "", "traffic": ""})
    return entries


def _candidate_source_priority(source: str) -> int:
    if source == "sellersprite_competitor_direct":
        return 6
    if source == "sellersprite_reversing_sources":
        return 5
    if source in {"sellersprite_relation_keyword", "sellersprite_traffic_extend"}:
        return 4
    if source == "sellersprite_direct":
        return 4
    if source == "sellersprite_keyword_overlap":
        return 3
    if source in {"sellersprite_reverse_seed", "sellersprite_keyword_reverse_seed"}:
        return 2
    if source == "amazon_search_visible":
        return 1
    return 0


def _candidate_confidence(source: str, overlap_count: int, has_record: bool, visible: bool) -> str:
    if source == "sellersprite_competitor_direct":
        return "high" if has_record or overlap_count >= 1 else "medium"
    if source in {"sellersprite_reversing_sources", "sellersprite_relation_keyword", "sellersprite_traffic_extend"}:
        return "medium" if has_record or overlap_count >= 1 else "low"
    if source == "sellersprite_direct" and (has_record or overlap_count >= 1):
        return "high"
    if source == "sellersprite_keyword_overlap" and has_record and overlap_count >= 2:
        return "high"
    if source == "sellersprite_direct":
        return "medium"
    if source == "sellersprite_keyword_overlap" and overlap_count >= 1:
        return "medium"
    if source in {"sellersprite_reverse_seed", "sellersprite_keyword_reverse_seed"} and has_record:
        return "low"
    if has_record and overlap_count >= 1:
        return "medium"
    if visible:
        return "low"
    return "unknown"


def _pool_confidence(candidates: list[dict[str, object]]) -> str:
    confidences = [str(item.get("confidence") or "") for item in candidates]
    if confidences.count("high") >= 1 and len(candidates) >= 2:
        return "high"
    if "high" in confidences or "medium" in confidences:
        return "medium"
    if candidates:
        return "low"
    return "unknown"


def _record_title(record: dict) -> str:
    return str(record.get("product_name") or record.get("title") or record.get("parent_product_name") or "").strip()


def _candidate_sort_key(candidate: dict[str, object]) -> tuple[int, int, int, float, int, str]:
    overlap_count = int(_num(candidate.get("overlap_count")) or 0)
    has_reverse = 1 if candidate.get("has_reverse") else 0
    top_strength = _num(candidate.get("top_strength")) or 0
    discovery_order = int(_num(candidate.get("discovery_order")) or 0)
    return (
        _candidate_source_priority(str(candidate.get("source") or "")),
        has_reverse,
        overlap_count,
        top_strength,
        -discovery_order,
        str(candidate.get("asin") or ""),
    )


def _first_present_value(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return ""


SPEC_MATERIAL_TOKENS = {
    "wood": "wood",
    "wooden": "wood",
    "metal": "metal",
    "plastic": "plastic",
    "metal": "metal",
    "stainless": "metal",
    "steel": "metal",
    "silicone": "silicone",
    "glass": "glass",
    "paper": "paper",
    "木": "wood",
    "竹": "metal",
    "塑料": "plastic",
    "不锈钢": "metal",
    "硅胶": "silicone",
    "玻璃": "glass",
    "纸": "paper",
}


def _spec_text(*values: object) -> str:
    return " ".join(str(value or "").lower() for value in values if str(value or "").strip())


def _spec_profile(*values: object) -> dict[str, object]:
    text = _spec_text(*values)
    capacities: list[float] = []
    packs: list[float] = []
    sizes: list[float] = []
    materials: set[str] = set()
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(gallon|gal|litre|liter|l|ml|oz)\b", text):
        value = float(number)
        unit_lower = unit.lower()
        if unit_lower == "ml":
            value = value / 1000
        capacities.append(value)
    for number in re.findall(r"(\d+(?:\.\d+)?)\s*(?:pcs?|pieces?|count|pack|bags?|sheets?|片|只|个|包)\b", text):
        packs.append(float(number))
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(cm|mm|inch|inches|in|厘米|毫米)\b", text):
        value = float(number)
        unit_lower = unit.lower()
        if unit_lower in {"mm", "毫米"}:
            value = value / 10
        sizes.append(value)
    for token, label in SPEC_MATERIAL_TOKENS.items():
        if token in text:
            materials.add(label)
    return {
        "capacity": capacities[0] if capacities else None,
        "pack": packs[0] if packs else None,
        "size": sizes[0] if sizes else None,
        "materials": materials,
        "has_spec": bool(capacities or packs or sizes or materials),
    }


def _within_ratio(left: float | None, right: float | None, *, lower: float = 0.7, upper: float = 1.3) -> bool | None:
    if left is None or right is None or left <= 0 or right <= 0:
        return None
    ratio = right / left
    return lower <= ratio <= upper


def _spec_match_status(own_profile: dict[str, object], candidate_profile: dict[str, object]) -> str:
    own_has = bool(own_profile.get("has_spec"))
    candidate_has = bool(candidate_profile.get("has_spec"))
    if not own_has or not candidate_has:
        return "规格待确认"
    checks: list[bool] = []
    for field in ("capacity", "pack", "size"):
        check = _within_ratio(own_profile.get(field), candidate_profile.get(field))  # type: ignore[arg-type]
        if check is not None:
            checks.append(check)
    own_materials = own_profile.get("materials") or set()
    candidate_materials = candidate_profile.get("materials") or set()
    if own_materials and candidate_materials:
        checks.append(bool(set(own_materials).intersection(set(candidate_materials))))
    if checks and not all(checks):
        return "规格错位"
    return "可比" if checks else "规格待确认"


def _price_band_status(own_price: float | None, candidate_price: float | None) -> str:
    check = _within_ratio(own_price, candidate_price, lower=0.7, upper=1.3)
    if check is None:
        return "价格待确认"
    return "可比" if check else "价格错位"


def _review_tier_status(own_rating: float | None, own_reviews: float | None, candidate_rating: float | None, candidate_reviews: float | None) -> str:
    if own_rating is None or own_reviews is None or candidate_rating is None or candidate_reviews is None:
        return "评论层级待确认"
    if candidate_rating - own_rating > 1.0:
        return "评论层级差异"
    if own_reviews > 0 and candidate_reviews / own_reviews > 10:
        return "评论层级差异"
    return "可比"


def _candidate_market_profile(row: dict, candidate: dict[str, object], own_keywords: dict[str, dict]) -> dict[str, object]:
    own_keyword_text = " ".join(_keyword_text(item) for item in own_keywords.values() if _keyword_text(item))
    own_profile = _spec_profile(row.get("product_name"), row.get("product"), row.get("sku"), own_keyword_text)
    candidate_profile = _spec_profile(
        candidate.get("title"),
        candidate.get("source_keyword"),
        " ".join(str(item) for item in candidate.get("candidate_keywords") or []),
    )
    own_price = _money(row.get("frontend_price") or row.get("price") or row.get("sale_price"))
    candidate_price = _money(candidate.get("price"))
    own_rating = _num(row.get("frontend_rating") or row.get("rating"))
    own_reviews = _num(row.get("frontend_reviews") or row.get("reviews") or row.get("review_count"))
    candidate_rating = _num(candidate.get("rating"))
    candidate_reviews = _num(candidate.get("reviews"))
    return {
        "spec_status": _spec_match_status(own_profile, candidate_profile),
        "price_status": _price_band_status(own_price, candidate_price),
        "review_status": _review_tier_status(own_rating, own_reviews, candidate_rating, candidate_reviews),
    }


def _candidate_can_be_main(candidate: dict[str, object], own_tokens: set[str]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    overlap_count = int(_num(candidate.get("overlap_count")) or 0)
    has_reverse = bool(candidate.get("has_reverse"))
    related_tokens = _candidate_related_tokens(candidate, own_tokens)
    source = str(candidate.get("source") or "")
    if not has_reverse:
        blockers.append("缺竞品反查")
    if overlap_count < 2:
        blockers.append("共同词不足2个")
    if not related_tokens and overlap_count < 2:
        blockers.append("用途待确认")
    if str(candidate.get("spec_status") or "") == "规格错位":
        blockers.append("规格错位")
    if str(candidate.get("price_status") or "") == "价格错位":
        blockers.append("价格带错位")
    if str(candidate.get("review_status") or "") == "评论层级差异":
        blockers.append("评论层级差异")
    if source == "amazon_search_visible" and overlap_count < 2:
        blockers.append("仅搜索页可见")
    return not blockers, blockers


def _pool_common_status(values: Iterable[object], *, pending_label: str) -> str:
    labels = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not labels:
        return pending_label
    if "规格错位" in labels:
        return "规格错位"
    if "价格错位" in labels:
        return "价格错位"
    if "评论层级差异" in labels:
        return "评论层级差异"
    if all(label == "可比" for label in labels):
        return "可比"
    return pending_label


def _pool_comparability_score(main_pool: list[dict[str, object]], reference_pool: list[dict[str, object]]) -> int:
    score = min(30, len(main_pool) * 15)
    score += min(20, sum(1 for item in main_pool if item.get("has_reverse")) * 10)
    shared_terms = {
        str(term)
        for item in main_pool
        for term in (item.get("overlap_keywords") or [])
        if str(term).strip()
    }
    score += min(15, len(shared_terms) * 8)
    statuses = [str(item.get("spec_status") or "") for item in main_pool]
    if "可比" in statuses:
        score += 15
    elif any("待确认" in status for status in statuses):
        score += 7
    price_statuses = [str(item.get("price_status") or "") for item in main_pool]
    if "可比" in price_statuses:
        score += 10
    elif any("待确认" in status for status in price_statuses):
        score += 5
    review_statuses = [str(item.get("review_status") or "") for item in main_pool]
    if "可比" in review_statuses:
        score += 10
    elif any("待确认" in status for status in review_statuses):
        score += 5
    if not main_pool and reference_pool:
        score = min(score, 35)
    return max(0, min(100, score))


def _upsert_candidate(candidates: dict[str, dict[str, object]], candidate: dict[str, object]) -> None:
    asin = _asin_text(candidate.get("asin"))
    if not asin:
        return
    current = candidates.get(asin)
    if "discovery_order" not in candidate:
        candidate = {**candidate, "discovery_order": current.get("discovery_order") if current else len(candidates)}
    if current is None or _candidate_sort_key(candidate) > _candidate_sort_key(current):
        candidates[asin] = {**candidate, "asin": asin}


def build_sellersprite_competitor_pool(
    row: dict,
    own_record: dict,
    seller_records: dict[tuple[str, str], dict],
    *,
    limit: int = 3,
    competitor_discovery_records: dict[tuple[str, str, str], dict] | None = None,
) -> dict[str, object]:
    market = str(row.get("marketplace") or "").strip().upper()
    sku = str(row.get("sku") or "").strip()
    own_asin = _asin_text(row.get("asin"))
    discovery_records = competitor_discovery_records if competitor_discovery_records is not None else load_competitor_discovery_records()
    discovery_record = discovery_records.get((market, sku, own_asin), {}) if own_asin and sku else {}
    visible_asins = _dedupe_asins(
        [*_competitor_asins(row, limit=10), *_amazon_search_seed_asins(discovery_record, own_asin=own_asin, limit=10)],
        own_asin=own_asin,
        limit=10,
    )
    visible_set = set(visible_asins)
    visible_info = {
        _asin_text(item.get("asin") or item.get("ASIN")): item
        for item in _parse_competitors(row)
        if _asin_text(item.get("asin") or item.get("ASIN"))
    }
    own_keywords = _keywords_by_normalized(own_record) if own_record else {}
    own_tokens = _own_product_tokens(own_keywords)
    own_display = {
        norm: _keyword_text(item)
        for norm, item in own_keywords.items()
        if _keyword_text(item)
    }
    candidates: dict[str, dict[str, object]] = {}
    discovery_status = str(discovery_record.get("competitor_discovery_status") or "").strip()
    discovery_error = str(discovery_record.get("last_error") or "").strip()
    discovery_source_page = str(discovery_record.get("source_page") or "").strip()

    for item in _discovery_competitor_items(discovery_record):
        asin = _asin_text(item.get("competitor_asin"))
        if not asin or asin == own_asin:
            continue
        record = seller_records.get((market, asin), {})
        comp_keywords = _keywords_by_normalized(record) if record else {}
        overlap_norms = [norm for norm in comp_keywords if norm in own_keywords]
        source = str(item.get("competitor_source") or "").strip() or "sellersprite_keyword_reverse_seed"
        top_strength = max((_keyword_sort_key(keyword_item)[0] for keyword_item in comp_keywords.values()), default=0)
        visible_detail = visible_info.get(asin, {})
        visible_title = str(visible_detail.get("title") or visible_detail.get("name") or "")
        title = item.get("competitor_title") or _record_title(record) or visible_title
        _upsert_candidate(
            candidates,
            {
                "asin": asin,
                "title": title,
                "source": source,
                "source_keyword": item.get("source_keyword") or "",
                "overlap_count": int(_num(item.get("overlap_keyword_count")) or len(overlap_norms)),
                "overlap_keywords": [own_display.get(norm, norm) for norm in overlap_norms[:5]],
                "traffic": item.get("traffic_or_rank_hint") or "",
                "amazon_visible": asin in visible_set,
                "has_reverse": bool(record),
                "confidence": _candidate_confidence(source, len(overlap_norms), bool(record), asin in visible_set),
                "top_strength": top_strength,
                "candidate_keywords": _candidate_keyword_sample(record),
                "seller_sprite_reverse_status": record.get("seller_sprite_check_status") or record.get("status") or "",
                "competitor_category_hint": _value_list_text(_candidate_keyword_sample(record), limit=3),
                "price": _first_present_value(item.get("price"), visible_detail.get("price"), visible_detail.get("price_text")),
                "rating": _first_present_value(item.get("rating"), visible_detail.get("rating"), visible_detail.get("stars")),
                "reviews": _first_present_value(item.get("reviews"), visible_detail.get("reviews"), visible_detail.get("review_count")),
            },
        )

    for entry in _direct_competitor_entries(own_record):
        asin = _asin_text(entry.get("asin"))
        if not asin or asin == own_asin:
            continue
        record = seller_records.get((market, asin), {})
        comp_keywords = _keywords_by_normalized(record) if record else {}
        overlap_norms = [norm for norm in comp_keywords if norm in own_keywords]
        top_strength = max((_keyword_sort_key(item)[0] for item in comp_keywords.values()), default=0)
        visible_detail = visible_info.get(asin, {})
        visible_title = str(visible_detail.get("title") or visible_detail.get("name") or "")
        title = entry.get("title") or _record_title(record) or visible_title
        confidence = _candidate_confidence(
            "sellersprite_direct",
            len(overlap_norms),
            bool(record),
            asin in visible_set,
        )
        _upsert_candidate(
            candidates,
            {
                "asin": asin,
                "title": title,
                "source": "sellersprite_direct",
                "source_keyword": entry.get("source_keyword") or "",
                "overlap_count": len(overlap_norms),
                "overlap_keywords": [own_display.get(norm, norm) for norm in overlap_norms[:5]],
                "traffic": entry.get("traffic") or "",
                "amazon_visible": asin in visible_set,
                "has_reverse": bool(record),
                "confidence": confidence,
                "top_strength": top_strength,
                "candidate_keywords": _candidate_keyword_sample(record),
                "seller_sprite_reverse_status": record.get("seller_sprite_check_status") or record.get("status") or "",
                "competitor_category_hint": _value_list_text(_candidate_keyword_sample(record), limit=3),
                "price": _first_present_value(entry.get("price"), visible_detail.get("price"), visible_detail.get("price_text")),
                "rating": _first_present_value(entry.get("rating"), visible_detail.get("rating"), visible_detail.get("stars")),
                "reviews": _first_present_value(entry.get("reviews"), visible_detail.get("reviews"), visible_detail.get("review_count")),
            },
        )

    for (record_market, asin), record in seller_records.items():
        if record_market != market or asin == own_asin:
            continue
        source_role = str(record.get("source_role") or "").strip()
        parent_asin = _asin_text(record.get("parent_asin"))
        parent_linked = source_role == "competitor" and parent_asin == own_asin
        if not parent_linked and parent_asin != own_asin:
            continue
        comp_keywords = _keywords_by_normalized(record)
        overlap_norms = [norm for norm in comp_keywords if norm in own_keywords]
        visible = asin in visible_set
        record_source = str(record.get("competitor_discovery_source") or record.get("discovery_source") or "").strip()
        if not overlap_norms and record_source not in {"sellersprite_direct", "sellersprite_keyword_overlap"} and not parent_linked:
            continue
        if record_source in {"sellersprite_direct", "sellersprite_keyword_overlap"}:
            source = record_source
        elif overlap_norms:
            source = "sellersprite_keyword_overlap"
        else:
            source = "sellersprite_reverse_seed"
        top_strength = max((_keyword_sort_key(item)[0] for item in comp_keywords.values()), default=0)
        visible_detail = visible_info.get(asin, {})
        visible_title = str(visible_detail.get("title") or visible_detail.get("name") or "")
        title = _record_title(record) or visible_title
        _upsert_candidate(
            candidates,
            {
                "asin": asin,
                "title": title,
                "source": source,
                "source_keyword": (own_display.get(overlap_norms[0], overlap_norms[0]) if overlap_norms else ""),
                "overlap_count": len(overlap_norms),
                "overlap_keywords": [own_display.get(norm, norm) for norm in overlap_norms[:5]],
                "traffic": "",
                "amazon_visible": visible,
                "has_reverse": True,
                "confidence": _candidate_confidence(source, len(overlap_norms), True, visible),
                "top_strength": top_strength,
                "candidate_keywords": _candidate_keyword_sample(record),
                "seller_sprite_reverse_status": record.get("seller_sprite_check_status") or record.get("status") or "",
                "competitor_category_hint": _value_list_text(_candidate_keyword_sample(record), limit=3),
                "price": _first_present_value(visible_detail.get("price"), visible_detail.get("price_text")),
                "rating": _first_present_value(visible_detail.get("rating"), visible_detail.get("stars")),
                "reviews": _first_present_value(visible_detail.get("reviews"), visible_detail.get("review_count")),
            },
        )

    for comp in _parse_competitors(row):
        asin = _asin_text(comp.get("asin") or comp.get("ASIN"))
        if not asin or asin == own_asin or _competitor_is_ad(comp):
            continue
        record = seller_records.get((market, asin), {})
        comp_keywords = _keywords_by_normalized(record) if record else {}
        overlap_norms = [norm for norm in comp_keywords if norm in own_keywords]
        if not overlap_norms:
            continue
        top_strength = max((_keyword_sort_key(item)[0] for item in comp_keywords.values()), default=0)
        title = comp.get("title") or comp.get("name") or _record_title(record)
        _upsert_candidate(
            candidates,
            {
                "asin": asin,
                "title": title,
                "source": "sellersprite_keyword_overlap",
                "source_keyword": (own_display.get(overlap_norms[0], overlap_norms[0]) if overlap_norms else ""),
                "overlap_count": len(overlap_norms),
                "overlap_keywords": [own_display.get(norm, norm) for norm in overlap_norms[:5]],
                "traffic": "",
                "amazon_visible": True,
                "has_reverse": bool(record),
                "confidence": _candidate_confidence("sellersprite_keyword_overlap", len(overlap_norms), bool(record), True),
                "top_strength": top_strength,
                "candidate_keywords": _candidate_keyword_sample(record),
                "seller_sprite_reverse_status": record.get("seller_sprite_check_status") or record.get("status") or "",
                "competitor_category_hint": _value_list_text(_candidate_keyword_sample(record), limit=3),
                "price": _first_present_value(comp.get("price"), comp.get("price_text")),
                "rating": _first_present_value(comp.get("rating"), comp.get("stars")),
                "reviews": _first_present_value(comp.get("reviews"), comp.get("review_count")),
            },
        )

    valid_candidates: list[dict[str, object]] = []
    rejected_candidates: list[dict[str, object]] = []
    for candidate in candidates.values():
        reason = _candidate_rejection_reason(candidate, own_tokens)
        if reason:
            rejected_candidates.append({**candidate, "rejection_reason": reason})
            continue
        profile = _candidate_market_profile(row, candidate, own_keywords)
        enriched_candidate = {
            **candidate,
            **profile,
            "confidence": _candidate_effective_confidence(candidate, own_tokens),
            "rejection_reason": "",
        }
        is_main, blockers = _candidate_can_be_main(enriched_candidate, own_tokens)
        valid_candidates.append(
            {
                **enriched_candidate,
                "competitor_role": "main" if is_main else "reference",
                "main_blockers": blockers,
            }
        )

    pool = sorted(valid_candidates, key=_candidate_sort_key, reverse=True)[:limit]
    main_pool = sorted(
        [item for item in valid_candidates if item.get("competitor_role") == "main"],
        key=_candidate_sort_key,
        reverse=True,
    )[:limit]
    reference_pool = [
        item
        for item in sorted(valid_candidates, key=_candidate_sort_key, reverse=True)
        if item.get("asin") not in {main.get("asin") for main in main_pool}
    ]
    pool_asins = [str(item.get("asin") or "") for item in pool if item.get("asin")]
    main_asins = [str(item.get("asin") or "") for item in main_pool if item.get("asin")]
    reference_asins = [str(item.get("asin") or "") for item in reference_pool if item.get("asin")]
    sources = _value_list_text((str(item.get("source") or "") for item in pool), limit=3)
    overlap_terms: list[str] = []
    source_terms: list[str] = []
    for item in pool:
        overlap_terms.extend(str(term) for term in item.get("overlap_keywords") or [] if str(term).strip())
        if str(item.get("source_keyword") or "").strip():
            source_terms.append(str(item.get("source_keyword") or "").strip())
        for term in item.get("candidate_keywords") or []:
            text = str(term or "").strip()
            if text and _meaningful_tokens(text).intersection(own_tokens):
                source_terms.append(text)
    confidence = _pool_confidence(pool)
    comparability_score = _pool_comparability_score(main_pool, reference_pool)
    spec_status = _pool_common_status((item.get("spec_status") for item in main_pool), pending_label="规格待确认")
    price_status = _pool_common_status((item.get("price_status") for item in main_pool), pending_label="价格待确认")
    review_status = _pool_common_status((item.get("review_status") for item in main_pool), pending_label="评论层级待确认")
    if len(pool) >= limit:
        status = f"有效 {len(pool)}/{limit}"
    elif pool:
        status = f"有效 {len(pool)}/{limit}"
    elif discovery_status and discovery_status not in {"已抓取", "沿用缓存", "缓存", "无竞品数据"}:
        status = "卖家精灵竞品发现失败"
    elif own_record:
        status = "竞品证据不足"
    else:
        status = "卖家精灵证据不足"
    return {
        "competitor_discovery_status": discovery_status or ("待补" if own_record else "卖家精灵证据不足"),
        "competitor_discovery_error": discovery_error,
        "competitor_discovery_source_page": discovery_source_page,
        "competitor_discovery_source": sources or "unknown",
        "competitor_pool_status": status,
        "competitor_pool_asins": "、".join(pool_asins),
        "competitor_pool_count": len(pool_asins),
        "competitor_pool_confidence": confidence,
        "main_competitor_asins": "、".join(main_asins),
        "main_competitor_count": len(main_asins),
        "reference_competitor_asins": "、".join(reference_asins[:5]),
        "reference_competitor_count": len(reference_asins),
        "competitor_comparability_score": comparability_score,
        "competitor_spec_match_status": spec_status,
        "competitor_price_band_status": price_status,
        "competitor_review_tier_status": review_status,
        "competitor_overlap_keywords": _value_list_text(overlap_terms, limit=8),
        "competitor_source_keywords": _value_list_text(source_terms, limit=8),
        "competitor_rejected_count": len(rejected_candidates),
        "competitor_rejection_reasons": _rejection_summary(rejected_candidates),
        "competitor_pool_items": pool,
        "competitor_pool_asin_list": pool_asins,
        "amazon_search_visible_competitors": "、".join(visible_asins),
    }


def _amazon_search_validation_summary(row: dict, pool_asins: list[str], visible_asins: list[str]) -> dict[str, object]:
    search_status = str(row.get("frontend_search_status") or "").strip()
    raw_count = _num(row.get("frontend_competitor_count"))
    count = int(raw_count) if raw_count is not None else len(visible_asins)
    count = max(count, len(visible_asins))
    comparable_raw = _num(row.get("comparable_competitor_count"))
    comparable = int(comparable_raw) if comparable_raw is not None else count
    pool_visible = [asin for asin in pool_asins if asin in set(visible_asins)]
    if pool_visible and (search_status == "已自动检查" or visible_asins):
        validation = "已验证"
    elif search_status == "已自动检查" and visible_asins:
        validation = "已读，无池内竞品"
    elif search_status == "已读取部分结果" or visible_asins:
        validation = "部分"
    elif search_status in {"读取失败", "失败"}:
        validation = "失败"
    else:
        validation = "未验证"
    if (search_status == "已自动检查" or visible_asins) and count >= 3:
        status = "已读 3 个"
    elif (search_status == "已自动检查" or visible_asins) and count > 0:
        status = f"部分，已读 {count} 个"
    elif search_status == "已读取部分结果" or count > 0:
        status = "部分"
    else:
        status = "待补"
    return {
        "competitor_frontend_status": status,
        "competitor_frontend_asins": "、".join(visible_asins),
        "competitor_frontend_count": count,
        "comparable_competitor_count": comparable,
        "amazon_search_validation_status": validation,
        "amazon_search_visible_competitors": "、".join(visible_asins),
    }


def _competitor_sellersprite_summary(competitor_records: list[tuple[str, dict]], target_asins: list[str]) -> dict[str, object]:
    asin_count = len(competitor_records)
    keyword_count = sum(
        len([item for item in (record.get("keywords") or []) if isinstance(item, dict) and _keyword_text(item)])
        for _, record in competitor_records
    )
    target_count = len(target_asins)
    if asin_count >= target_count and target_count:
        status = f"已抓 {asin_count} 个"
    elif asin_count > 0:
        status = f"部分，已抓 {asin_count}/{target_count or asin_count} 个"
    elif target_count:
        status = "竞品反查待补"
    else:
        status = "待补"
    quality = _combined_keyword_quality_counts(record for _, record in competitor_records)
    return {
        "competitor_sellersprite_status": status,
        "competitor_sellersprite_asin_count": asin_count,
        "competitor_sellersprite_keyword_count": keyword_count,
        "competitor_sellersprite_ppc_missing_count": quality["ppc_missing_count"],
        "competitor_sellersprite_monthly_searches_missing_count": quality["monthly_searches_missing_count"],
        "competitor_sellersprite_traffic_share_placeholder_count": quality["traffic_share_placeholder_count"],
    }


def _frontend_competitiveness(row: dict) -> str:
    auto_code = str(row.get("frontend_auto_conclusion") or "").strip()
    auto_label = str(row.get("frontend_auto_conclusion_label") or "").strip()
    findings = "；".join(
        str(row.get(key) or "")
        for key in ["frontend_findings", "frontend_search_findings", "suspected_issue"]
    )
    buy_box = str(row.get("frontend_buy_box") or row.get("buy_box") or "").strip()
    delivery = str(row.get("frontend_delivery") or "").strip()
    score = _num(row.get("frontend_evidence_quality_score")) or 0
    if any(token in buy_box for token in ["无", "丢", "异常", "未稳定"]) or any(token in delivery for token in ["不可", "异常", "未确认"]):
        return "产品问题"
    if auto_code == "FRONTEND_WEAK" or auto_label == "明确前台劣势":
        return "前台弱"
    if any(token in findings for token in ["价格带弱势", "价格不占", "价格高", "评分低", "评论弱", "Buy Box"]):
        return "前台弱"
    if auto_code == "FRONTEND_OK" and score >= 60:
        return "可承接"
    return "未知"


def _competitive_fusion_summary(
    row: dict,
    own_record: dict,
    seller_records: dict[tuple[str, str], dict],
    ad_detail_rows: list[dict],
    competitor_discovery_records: dict[tuple[str, str, str], dict] | None = None,
    history_rows: list[dict[str, object]] | None = None,
    report_date: str | None = None,
) -> dict[str, object]:
    market = str(row.get("marketplace") or "").strip().upper()
    own_asin = _asin_text(row.get("asin"))
    own_keywords = _keywords_by_normalized(own_record) if own_record else {}
    own_keyword_text_by_norm = {
        normalize_keyword(_keyword_text(item)): _keyword_text(item)
        for item in own_record.get("keywords") or []
        if isinstance(item, dict) and _keyword_text(item)
    } if own_record else {}
    pool_summary = build_sellersprite_competitor_pool(
        row,
        own_record,
        seller_records,
        competitor_discovery_records=competitor_discovery_records,
    )
    visible_asins = _asins_from_text(pool_summary.get("amazon_search_visible_competitors"), own_asin=own_asin, limit=10)
    if not visible_asins:
        visible_asins = _competitor_asins(row, limit=10)
    target_asins = list(pool_summary.get("competitor_pool_asin_list") or [])
    main_target_asins = _asins_from_text(pool_summary.get("main_competitor_asins"), own_asin=own_asin, limit=3)
    competitor_records: list[tuple[str, dict]] = []
    for comp_asin in target_asins:
        record = seller_records.get((market, comp_asin))
        if record:
            competitor_records.append((comp_asin, record))
    main_competitor_records: list[tuple[str, dict]] = []
    for comp_asin in main_target_asins:
        record = seller_records.get((market, comp_asin))
        if record:
            main_competitor_records.append((comp_asin, record))
    history_summary = build_sellersprite_history_summary(
        row,
        own_record=own_record,
        target_asins=target_asins,
        history_rows=history_rows,
        report_date=report_date,
    )

    competitor_keyword_counts: dict[str, int] = {}
    competitor_keyword_display: dict[str, str] = {}
    strong_competitor_norms: set[str] = set()
    competitor_text_parts: list[str] = []
    for comp_asin, record in competitor_records:
        top_items = _top_keyword_items(record, limit=8)
        top_terms = [_keyword_text(item) for item in top_items if _keyword_text(item)]
        if top_terms:
            competitor_text_parts.append(f"{comp_asin}: " + "、".join(top_terms[:5]))
        for item in top_items:
            term = _keyword_text(item)
            norm = normalize_keyword(term)
            if not norm:
                continue
            competitor_keyword_counts[norm] = competitor_keyword_counts.get(norm, 0) + 1
            competitor_keyword_display.setdefault(norm, term)
            if _strong_keyword(item):
                strong_competitor_norms.add(norm)
    main_keyword_counts: dict[str, int] = {}
    main_keyword_display: dict[str, str] = {}
    for _, record in main_competitor_records:
        for item in _top_keyword_items(record, limit=8):
            term = _keyword_text(item)
            norm = normalize_keyword(term)
            if not norm:
                continue
            main_keyword_counts[norm] = main_keyword_counts.get(norm, 0) + 1
            main_keyword_display.setdefault(norm, term)

    shared_norms = [
        norm
        for norm, count in sorted(
            competitor_keyword_counts.items(),
            key=lambda pair: (pair[1], pair[0]),
            reverse=True,
        )
        if count >= 2 or (len(competitor_records) == 1 and norm in strong_competitor_norms)
    ]
    main_shared_norms = [
        norm
        for norm, count in sorted(
            main_keyword_counts.items(),
            key=lambda pair: (pair[1], pair[0]),
            reverse=True,
        )
        if count >= 2
    ]
    missing_norms = [norm for norm in shared_norms if norm not in own_keywords]
    ad_norms = {
        normalize_keyword(str(detail.get("keyword") or ""))
        for detail in ad_detail_rows
        if normalize_keyword(str(detail.get("keyword") or ""))
    }
    ad_gap_norms = [norm for norm in shared_norms if norm not in ad_norms]
    no_match_ad_terms = [
        str(detail.get("keyword") or "").strip()
        for detail in ad_detail_rows
        if str(detail.get("seller_sprite_match_status") or "") == "未命中"
        and normalize_keyword(str(detail.get("keyword") or "")) not in competitor_keyword_counts
        and (_num(detail.get("ad_orders")) or 0) <= 0
        and ((_num(detail.get("ad_clicks")) or 0) >= 5 or (_money(detail.get("ad_spend")) or 0) >= 5)
    ]
    pressure = "无缓存"
    if competitor_records:
        strong_count = len(strong_competitor_norms)
        shared_count = len(shared_norms)
        if strong_count >= 4 or shared_count >= 3 or len(competitor_records) >= 2:
            pressure = "高"
        elif strong_count >= 1 or shared_count >= 1:
            pressure = "中"
        else:
            pressure = "低"
    frontend_level = _frontend_competitiveness(row)
    has_ad_orders = any((_num(detail.get("ad_orders")) or 0) > 0 for detail in ad_detail_rows)
    direct_sources = {
        "sellersprite_competitor_direct",
        "sellersprite_reversing_sources",
        "sellersprite_relation_keyword",
        "sellersprite_traffic_extend",
        "sellersprite_direct",
        "sellersprite_keyword_overlap",
    }
    has_direct_competitor_pool = any(
        str(item.get("source") or "") in direct_sources
        for item in pool_summary.get("competitor_pool_items") or []
    )
    sellersprite_current_for_growth = history_summary.get("sellersprite_evidence_tier") in {
        "今日趋势证据",
        "今日单日证据",
    }
    sellersprite_cache_only = history_summary.get("sellersprite_evidence_tier") == "历史缓存参考"
    amazon_summary = _amazon_search_validation_summary(row, target_asins, visible_asins)
    main_visible = [asin for asin in main_target_asins if asin in set(visible_asins)]
    trend_days = int(_num(history_summary.get("sellersprite_history_days")) or 0)
    trend_ok = trend_days >= 3 or history_summary.get("sellersprite_evidence_tier") == "今日趋势证据"
    spec_status = str(pool_summary.get("competitor_spec_match_status") or "")
    price_status = str(pool_summary.get("competitor_price_band_status") or "")
    review_status = str(pool_summary.get("competitor_review_tier_status") or "")
    scalable_blockers: list[str] = []
    if frontend_level != "可承接":
        scalable_blockers.append("自己产品页不可承接")
    if len(main_target_asins) < 2:
        scalable_blockers.append("主竞品不足2个")
    if len(main_competitor_records) < 2:
        scalable_blockers.append("主竞品反查不足")
    if len(main_shared_norms) < 2:
        scalable_blockers.append("主竞品共同词不足")
    if not main_visible and not trend_ok:
        scalable_blockers.append("缺搜索验证或3天趋势")
    if spec_status != "可比":
        scalable_blockers.append(spec_status or "规格待确认")
    if price_status != "可比":
        scalable_blockers.append(price_status or "价格待确认")
    if review_status == "评论层级差异":
        scalable_blockers.append(review_status)
    if not has_ad_orders:
        scalable_blockers.append("广告未验证成交")
    if sellersprite_cache_only:
        scalable_blockers.append("卖家精灵仅旧缓存")
    scalable_blockers = list(dict.fromkeys(item for item in scalable_blockers if item))
    if frontend_level in {"产品问题", "前台弱"}:
        scalable_status = "只能控费止损"
    elif not scalable_blockers:
        scalable_status = "可谨慎放量"
    elif frontend_level == "可承接" and (main_target_asins or shared_norms or target_asins):
        scalable_status = "可小预算测试"
    else:
        scalable_status = "证据不足"
    scalable_allowed = ["bid_up", "create_exact_low_budget"] if scalable_status == "可谨慎放量" else ["create_exact_low_budget"] if scalable_status == "可小预算测试" else []
    if frontend_level == "产品问题":
        conclusion = "产品问题优先"
        allowed = ["observe", "bid_down", "negative_exact", "pause"]
        blocked = ["bid_up", "budget_up", "broad_scale", "create_exact_low_budget"]
        boundary = "广告只做止损，优先修价格、评分、评论、Buy Box、配送、库存或 listing。"
    elif frontend_level == "前台弱" and pressure in {"高", "中"}:
        conclusion = "暂停扩张"
        allowed = ["observe", "bid_down", "negative_exact", "pause"]
        blocked = ["bid_up", "budget_up", "broad_scale", "create_exact_low_budget"]
        boundary = "前台弱且竞品词压力高，停止新增词，优先处理高花费 0 单词。"
    elif frontend_level == "前台弱":
        conclusion = "只防守"
        allowed = ["observe", "bid_down", "negative_exact", "pause"]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        boundary = "只保留已验证成交词，相关未验证词降竞价。"
    elif scalable_status == "可谨慎放量":
        conclusion = "可谨慎放量"
        allowed = ["observe", "bid_up", "create_exact_low_budget", "bid_down", "negative_exact"]
        blocked = ["budget_up", "broad_scale"]
        boundary = "主竞品、前台、卖家精灵和广告成交均达标，只允许核心成交词小幅加竞价和精准小预算测试。"
    elif frontend_level == "可承接" and competitor_records and shared_norms and ad_gap_norms:
        conclusion = "可测试，不放量"
        allowed = ["observe", "create_exact_low_budget", "bid_down", "negative_exact"]
        blocked = ["budget_up", "broad_scale"]
        boundary = "卖家精灵竞品共同词存在且账号广告未覆盖，只能精准小预算测试，不允许 broad 和预算上调。"
    elif sellersprite_cache_only and frontend_level == "可承接":
        conclusion = "可测试，不放量"
        allowed = ["observe", "create_exact_low_budget", "bid_down", "negative_exact"]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        cache_date = str(history_summary.get("sellersprite_cache_date") or "")
        boundary = f"卖家精灵沿用 {cache_date or '旧'} 缓存，只能做背景判断，不能作为放量依据。"
    elif frontend_level == "可承接" and has_ad_orders and own_record and competitor_records and has_direct_competitor_pool and sellersprite_current_for_growth:
        conclusion = "可测试，不放量"
        allowed = ["observe", "create_exact_low_budget", "bid_down", "negative_exact"]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        boundary = "卖家精灵和广告有基础证据，但主竞品放量门槛未全达标，只允许精准小预算测试。"
    elif frontend_level == "可承接" and (target_asins or shared_norms):
        conclusion = "可测试，不放量"
        allowed = ["observe", "create_exact_low_budget", "bid_down", "negative_exact"]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        boundary = "竞品池或反查证据不足以支持放量，只允许低预算精准验证。"
    else:
        conclusion = "只防守"
        allowed = ["observe", "bid_down", "negative_exact"]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        boundary = "证据不足时只允许防守和止损，不能用卖家精灵单独支持放量。"
    pool_public = {
        key: value
        for key, value in pool_summary.items()
        if key not in {"competitor_pool_items", "competitor_pool_asin_list"}
    }
    return {
        "own_sellersprite_keywords": _top_keywords_text(own_record, limit=8) if own_record else "",
        **pool_public,
        "competitor_sellersprite_keywords": "；".join(competitor_text_parts),
        "competitor_shared_keywords": _value_list_text((competitor_keyword_display.get(norm, norm) for norm in shared_norms), limit=10),
        "own_missing_competitor_keywords": _value_list_text((competitor_keyword_display.get(norm, norm) for norm in missing_norms), limit=10),
        "own_ad_terms_not_in_sellersprite": _value_list_text(no_match_ad_terms, limit=10),
        **amazon_summary,
        **_competitor_sellersprite_summary(competitor_records, target_asins),
        "competitor_stability_days": trend_days,
        "scalable_evidence_status": scalable_status,
        "scalable_blockers": "；".join(scalable_blockers[:5]),
        "scalable_allowed_actions": "、".join(scalable_allowed),
        "competitor_keyword_pressure": pressure,
        "frontend_competitiveness": frontend_level,
        **history_summary,
        "product_level_conclusion": conclusion,
        "product_ad_boundary": boundary,
        "final_ad_allowed_actions": allowed,
        "final_ad_blocked_actions": blocked,
        "seller_sprite_competitor_cache_count": len(competitor_records),
        "seller_sprite_competitor_target_asins": "、".join(target_asins),
        "seller_sprite_competitor_data_dates": "、".join(
            f"{asin}:{_latest_data_date(record)}" for asin, record in competitor_records if _latest_data_date(record)
        ),
    }


def _enrich_ad_row(row: dict, seller_records: dict[tuple[str, str], dict]) -> tuple[dict, dict]:
    market = str(row.get("marketplace") or "").strip().upper()
    asin = str(row.get("asin") or "").strip().upper()
    keyword = str(row.get("search_term_or_target") or row.get("search_term") or "").strip()
    normalized = normalize_keyword(keyword)
    record = seller_records.get((market, asin), {})
    matched, status = _match_seller_keyword(normalized, record) if record else (None, "无缓存")
    competition = _competition_level(matched or {}) if matched else ""
    bucket = _keyword_bucket(matched or {}, competition) if matched else ""
    label, reason = _fusion_label(row, matched, bucket, competition)
    data_date = _latest_data_date(record) if record else ""
    enriched = dict(row)
    enriched.update(
        {
            "seller_sprite_match_status": status if record else "无缓存",
            "seller_sprite_ads_fusion_label": label,
            "seller_sprite_fusion_reason": reason,
        }
    )
    detail = {
        "marketplace": market,
        "sku": row.get("sku") or "",
        "asin": asin,
        "keyword": keyword,
        "normalized_keyword": normalized,
        "ad_clicks": _num(row.get("clicks") or row.get("ad_clicks")) or 0,
        "ad_spend": _money(row.get("spend") or row.get("ad_spend")) or 0,
        "ad_orders": _num(row.get("orders") or row.get("ad_orders")) or 0,
        "ad_sales": _money(row.get("sales") or row.get("ad_sales")) or 0,
        "ad_acos": _num(row.get("ACOS") or row.get("acos")),
        "campaign_name": row.get("campaign_name") or row.get("campaign") or "",
        "ad_group_name": row.get("ad_group_name") or row.get("ad_group") or "",
        "match_type": row.get("match_type") or "",
        "targeting": row.get("targeting") or "",
        "seller_sprite_match_status": enriched["seller_sprite_match_status"],
        "seller_sprite_data_date": data_date,
        "seller_sprite_traffic_share": _seller_value(matched or {}, "traffic_share", "流量占比"),
        "seller_sprite_monthly_searches": _seller_value(matched or {}, "monthly_searches", "月搜索量"),
        "seller_sprite_purchases": _seller_value(matched or {}, "purchases", "购买量"),
        "seller_sprite_purchase_rate": _seller_value(matched or {}, "purchase_rate", "购买率"),
        "seller_sprite_natural_rank": _seller_value(matched or {}, "natural_rank", "自然排名"),
        "seller_sprite_spr": _seller_value(matched or {}, "spr", "SPR"),
        "seller_sprite_ppc": _seller_value(matched or {}, "ppc", "PPC价格"),
        "seller_sprite_competition_level": competition,
        "seller_sprite_keyword_bucket": bucket,
        "seller_sprite_ads_fusion_label": label,
        "seller_sprite_fusion_reason": reason,
        "product_level_conclusion": "",
        "product_ad_boundary": "",
        "final_ad_allowed_actions": "",
        "final_ad_blocked_actions": "",
        "own_sellersprite_keywords": "",
        "competitor_discovery_source": "",
        "competitor_pool_status": "",
        "competitor_pool_asins": "",
        "competitor_pool_count": "",
        "competitor_pool_confidence": "",
        "main_competitor_asins": "",
        "main_competitor_count": "",
        "reference_competitor_asins": "",
        "reference_competitor_count": "",
        "competitor_comparability_score": "",
        "competitor_spec_match_status": "",
        "competitor_price_band_status": "",
        "competitor_review_tier_status": "",
        "competitor_stability_days": "",
        "scalable_evidence_status": "",
        "scalable_blockers": "",
        "scalable_allowed_actions": "",
        "competitor_overlap_keywords": "",
        "competitor_source_keywords": "",
        "competitor_rejected_count": "",
        "competitor_rejection_reasons": "",
        "competitor_sellersprite_keywords": "",
        "competitor_shared_keywords": "",
        "own_missing_competitor_keywords": "",
        "own_ad_terms_not_in_sellersprite": "",
        "competitor_frontend_status": "",
        "competitor_frontend_asins": "",
        "competitor_frontend_count": "",
        "comparable_competitor_count": "",
        "amazon_search_validation_status": "",
        "amazon_search_visible_competitors": "",
        "competitor_sellersprite_status": "",
        "competitor_sellersprite_asin_count": "",
        "competitor_sellersprite_keyword_count": "",
        "competitor_keyword_pressure": "",
        "frontend_competitiveness": "",
        **{field: "" for field in HISTORY_TREND_FIELDS},
    }
    return enriched, detail


def _product_summary(record: dict) -> dict[str, object]:
    keywords = [item for item in record.get("keywords") or [] if isinstance(item, dict)]
    buckets: dict[str, int] = {}
    opportunities: list[str] = []
    risks: list[str] = []
    ppcs: list[float] = []
    quality = _keyword_quality_counts(record)
    for item in keywords:
        competition = _competition_level(item)
        bucket = _keyword_bucket(item, competition)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        ppc = _seller_number(item, "ppc", "PPC价格")
        if ppc is not None:
            ppcs.append(ppc)
        keyword = str(item.get("keyword") or item.get("流量词") or "").strip()
        if bucket == "可测核心词" and keyword and len(opportunities) < 5:
            opportunities.append(keyword)
        if competition == "高竞争" and keyword and len(risks) < 5:
            risks.append(keyword)
    risk_parts: list[str] = []
    if risks:
        risk_parts.append("高竞争：" + "、".join(risks[:3]))
    if ppcs:
        risk_parts.append(f"PPC中位数 {median(ppcs):.2f}")
    return {
        "seller_sprite_check_status": record.get("seller_sprite_check_status") or record.get("status") or "已抓取",
        "seller_sprite_data_date": _latest_data_date(record),
        "seller_sprite_keyword_count": record.get("captured_count") or len(keywords),
        "seller_sprite_top_opportunities": "、".join(opportunities[:5]) if opportunities else "暂无明确机会词",
        "seller_sprite_risk_summary": "；".join(risk_parts) if risk_parts else "未见明显高竞争摘要",
        "seller_sprite_opportunity_count": buckets.get("可测核心词", 0),
        "seller_sprite_high_competition_count": buckets.get("相关高竞争", 0),
        "seller_sprite_ppc_missing_count": quality["ppc_missing_count"],
        "seller_sprite_monthly_searches_missing_count": quality["monthly_searches_missing_count"],
        "seller_sprite_traffic_share_placeholder_count": quality["traffic_share_placeholder_count"],
    }


def _empty_product_summary() -> dict[str, object]:
    return {
        "seller_sprite_check_status": "无缓存",
        "seller_sprite_data_date": "",
        "seller_sprite_keyword_count": 0,
        "seller_sprite_top_opportunities": "",
        "seller_sprite_risk_summary": "",
        "seller_sprite_opportunity_count": 0,
        "seller_sprite_high_competition_count": 0,
        "seller_sprite_ppc_missing_count": 0,
        "seller_sprite_monthly_searches_missing_count": 0,
        "seller_sprite_traffic_share_placeholder_count": 0,
    }


def _empty_ad_match_summary() -> dict[str, int]:
    return {
        "seller_sprite_ad_rows_count": 0,
        "seller_sprite_ad_exact_match_count": 0,
        "seller_sprite_ad_near_match_count": 0,
        "seller_sprite_ad_no_match_count": 0,
        "seller_sprite_ad_no_cache_count": 0,
    }


def _ad_match_summary_by_product(detail_rows: list[dict]) -> dict[tuple[str, str], dict[str, int]]:
    summaries: dict[tuple[str, str], dict[str, int]] = {}
    for row in detail_rows:
        key = (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("asin") or "").strip().upper(),
        )
        if not key[0] or not key[1]:
            continue
        summary = summaries.setdefault(key, _empty_ad_match_summary())
        summary["seller_sprite_ad_rows_count"] += 1
        status = str(row.get("seller_sprite_match_status") or "").strip()
        if status == "已命中":
            summary["seller_sprite_ad_exact_match_count"] += 1
        elif status == "近似命中":
            summary["seller_sprite_ad_near_match_count"] += 1
        elif status == "未命中":
            summary["seller_sprite_ad_no_match_count"] += 1
        elif status == "无缓存":
            summary["seller_sprite_ad_no_cache_count"] += 1
    return summaries


def _ad_detail_rows_by_product(detail_rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    rows_by_key: dict[tuple[str, str], list[dict]] = {}
    for row in detail_rows:
        key = (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("asin") or "").strip().upper(),
        )
        if key[0] and key[1]:
            rows_by_key.setdefault(key, []).append(row)
    return rows_by_key


def _apply_product_fusion_to_ad_rows(
    rows: list[dict],
    detail_rows: list[dict],
    fusion_by_key: dict[tuple[str, str], dict[str, object]],
) -> tuple[list[dict], list[dict]]:
    enriched_rows: list[dict] = []
    enriched_details: list[dict] = []
    for row, detail in zip(rows, detail_rows):
        key = (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("asin") or "").strip().upper(),
        )
        fusion = fusion_by_key.get(key, {})
        item = dict(row)
        detail_item = dict(detail)
        for field in [
            "product_level_conclusion",
            "product_ad_boundary",
            "final_ad_allowed_actions",
            "final_ad_blocked_actions",
            "own_sellersprite_keywords",
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
            "competitor_sellersprite_keywords",
            "competitor_shared_keywords",
            "own_missing_competitor_keywords",
            "own_ad_terms_not_in_sellersprite",
            "competitor_frontend_status",
            "competitor_frontend_asins",
            "competitor_frontend_count",
            "comparable_competitor_count",
            "amazon_search_validation_status",
            "amazon_search_visible_competitors",
            "competitor_sellersprite_status",
            "competitor_sellersprite_asin_count",
            "competitor_sellersprite_keyword_count",
            "competitor_keyword_pressure",
            "frontend_competitiveness",
            "seller_sprite_ppc_missing_count",
            "seller_sprite_monthly_searches_missing_count",
            "seller_sprite_traffic_share_placeholder_count",
            "competitor_sellersprite_ppc_missing_count",
            "competitor_sellersprite_monthly_searches_missing_count",
            "competitor_sellersprite_traffic_share_placeholder_count",
            *MARKET_SURVEY_COMPLETENESS_FIELDS,
            *HISTORY_TREND_FIELDS,
        ]:
            value = fusion.get(field, "")
            if isinstance(value, list):
                display_value = " / ".join(str(item_value) for item_value in value)
            else:
                display_value = value
            item[field] = display_value
            detail_item[field] = display_value
        if (
            str(detail_item.get("seller_sprite_match_status") or "") == "未命中"
            and (_num(detail_item.get("ad_orders")) or 0) <= 0
            and ((_num(detail_item.get("ad_clicks")) or 0) >= 5 or (_money(detail_item.get("ad_spend")) or 0) >= 5)
        ):
            item["seller_sprite_ads_fusion_label"] = "无反查匹配需控费"
            item["seller_sprite_fusion_reason"] = "广告词有点击或花费且 0 单，自身卖家精灵无痕迹，优先降竞价或否定精准。"
            detail_item["seller_sprite_ads_fusion_label"] = item["seller_sprite_ads_fusion_label"]
            detail_item["seller_sprite_fusion_reason"] = item["seller_sprite_fusion_reason"]
        enriched_rows.append(item)
        enriched_details.append({column: detail_item.get(column, "") for column in FUSION_COLUMNS})
    return enriched_rows, enriched_details


def _append_summary_to_findings(row: dict, summary: dict[str, object]) -> str:
    findings = str(row.get("frontend_findings") or "").strip()
    if not summary:
        return findings
    status = summary.get("seller_sprite_check_status") or ""
    if status == "无缓存":
        return findings
    date = summary.get("seller_sprite_data_date") or ""
    count = summary.get("seller_sprite_keyword_count") or 0
    opp_count = summary.get("seller_sprite_opportunity_count") or 0
    high_count = summary.get("seller_sprite_high_competition_count") or 0
    date_part = f"{date}，" if date else ""
    addition = f"卖家精灵反查：{status}，{date_part}抓到{count}词，机会词{opp_count}个，高竞争{high_count}个。"
    if addition in findings:
        return findings
    return "；".join(part for part in [findings, addition] if part)


def enrich_report_view_rows(
    search_rows: list[dict],
    frontend_rows: list[dict],
    *,
    cache_path: Path = SELLERSPRITE_CACHE_PATH,
    competitor_discovery_cache_path: Path = SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
    history_path: Path = SELLERSPRITE_HISTORY_PATH,
    report_date: str | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    seller_records = load_sellersprite_records(cache_path)
    competitor_discovery_records = load_competitor_discovery_records(competitor_discovery_cache_path)
    history_rows = load_sellersprite_history(history_path)
    enriched_search: list[dict] = []
    detail_rows: list[dict] = []
    for row in search_rows:
        enriched, detail = _enrich_ad_row(row, seller_records)
        enriched_search.append(enriched)
        detail_rows.append(detail)
    ad_match_summaries = _ad_match_summary_by_product(detail_rows)
    ad_detail_by_key = _ad_detail_rows_by_product(detail_rows)
    enriched_frontend: list[dict] = []
    fusion_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for row in frontend_rows:
        key = (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("asin") or "").strip().upper(),
        )
        ad_summary = ad_match_summaries.get(key, _empty_ad_match_summary())
        record = seller_records.get(key)
        fusion_summary = _competitive_fusion_summary(
            row,
            record or {},
            seller_records,
            ad_detail_by_key.get(key, []),
            competitor_discovery_records,
            history_rows,
            report_date,
        )
        if not record:
            summary = _empty_product_summary()
            enriched = {**row, **summary, **ad_summary, **fusion_summary}
            enriched["frontend_findings"] = _append_summary_to_findings(enriched, summary)
            enriched = enrich_market_survey_completeness(enriched, report_date=report_date)
            fusion_by_key[key] = {field: enriched.get(field, "") for field in FUSION_COLUMNS}
            enriched_frontend.append(enriched)
            continue
        summary = _product_summary(record)
        enriched = {**row, **summary, **ad_summary, **fusion_summary}
        enriched["frontend_findings"] = _append_summary_to_findings(enriched, summary)
        enriched = enrich_market_survey_completeness(enriched, report_date=report_date)
        fusion_by_key[key] = {field: enriched.get(field, "") for field in FUSION_COLUMNS}
        enriched_frontend.append(enriched)
    enriched_search, detail_rows = _apply_product_fusion_to_ad_rows(enriched_search, detail_rows, fusion_by_key)
    return enriched_search, enriched_frontend, detail_rows
