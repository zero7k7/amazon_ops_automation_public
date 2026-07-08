from __future__ import annotations

import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .merge_data import DailyDataset
from .metrics import HistoricalViews, add_ratio_columns

TRIPLE_KEYS = ["marketplace", "sku", "asin"]
PRODUCT_WINDOW_KEYS = TRIPLE_KEYS
NEGATIVE_KEYWORD_PATTERNS = [
    "ariel",
    "costco",
    "kirkland",
    "pizza",
    "dishwasher",
    "ceramic",
    "glass",
    "silicone",
    "cork",
    "stainless steel",
    "toilet",
    "bathroom",
    "washing liquid",
    "spice",
    "sandwich bag",
    "picnic",
]
CORE_RELEVANT_TERM_PATTERNS = [
    "dimmer desk lamp",
    "led desk lamp",
    "dimmer switch",
    "desk lamp",
    "metal desk lamp",
    "desk mat",
    "hot pans",
    "metal desk mat",
    "bin bags",
    "cable ties",
    "cable bags",
    "spiral notebook",
    "stationery notebook",
]
COMPETITOR_OR_BRAND_PATTERNS = ["demobrand", "demobrand"]
BROAD_GENERIC_PATTERNS = ["wood", "metal", "kitchen", "board", "bags", "storage"]
IRRELEVANT_TERM_MIN_CLICKS = 3
IRRELEVANT_TERM_MIN_SPEND = 1.5
SECTION_LIMITS = {
    "今日必须处理": 8,
    "建议否词/暂停": 15,
    "可以放量": 8,
    "成本/利润异常": 8,
    "明天观察": 10,
}
ASIN_TERM_PATTERN = re.compile(r"^B0[A-Z0-9]{8,}$", re.IGNORECASE)
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
PRODUCT_KEYWORD_RULES_PATH = CONFIG_DIR / "product_keyword_rules.csv"
PRODUCT_LINE_KEYWORDS_PATH = CONFIG_DIR / "product_line_keywords.json"


def _round_metric(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _serialize_row(row: pd.Series, fields: list[str]) -> dict:
    payload: dict[str, object] = {}
    for field in fields:
        value = row.get(field, "")
        if pd.isna(value):
            value = None
        elif isinstance(value, float):
            value = _round_metric(value, 4)
        payload[field] = value
    return payload


def _window_records(df: pd.DataFrame, sort_field: str) -> list[dict]:
    if df.empty:
        return []
    records = df.sort_values(sort_field, ascending=False).to_dict(orient="records")
    normalized_records: list[dict] = []
    for record in records:
        normalized_records.append(
            {
                key: (None if pd.isna(value) else _round_metric(value, 4) if isinstance(value, float) else value)
                for key, value in record.items()
            }
        )
    return normalized_records


def _recommendation(
    level: str,
    category: str,
    target: str,
    action: str,
    evidence: dict,
    note: str = "",
    markdown_section: str | None = None,
    markdown_visible: bool = True,
    priority_rank: int = 999,
) -> dict:
    return {
        "level": level,
        "category": category,
        "target": target,
        "action": action,
        "evidence": evidence,
        "note": note,
        "markdown_section": markdown_section,
        "markdown_visible": markdown_visible,
        "priority_rank": priority_rank,
    }


def _evidence_score(evidence: dict) -> float:
    score = 0.0
    for key in ["spend", "clicks", "ad_sales", "ad_orders", "impressions", "total_orders", "natural_orders"]:
        value = evidence.get(key, 0)
        if value not in (None, ""):
            try:
                score += float(value)
            except (TypeError, ValueError):
                continue
    return score


def _deduplicate_recommendations(items: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, str, str, str], dict] = {}
    for item in items:
        key = (item["level"], item["category"], item["target"], item["action"])
        existing = deduped.get(key)
        if existing is None or _evidence_score(item["evidence"]) > _evidence_score(existing["evidence"]):
            deduped[key] = item
    return list(deduped.values())


def _deduplicate_anomalies(items: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (item["rule"], item["target"])
        existing = deduped.get(key)
        if existing is None or _evidence_score(item["evidence"]) > _evidence_score(existing["evidence"]):
            deduped[key] = item
    return list(deduped.values())


DEFAULT_TARGET_ACOS = 0.10


def _target_acos_value(row: pd.Series) -> float | None:
    value = row.get("target_acos", None)
    if pd.isna(value) or value in ("", None):
        return DEFAULT_TARGET_ACOS
    numeric = float(value)
    return None if numeric <= 0 else numeric


def _has_invalid_target_acos(row: pd.Series) -> bool:
    value = row.get("target_acos", None)
    if pd.isna(value) or value in ("", None):
        return False
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return False


def _profit_before_ads_per_unit(row: pd.Series) -> float | None:
    value = row.get("profit_before_ads_per_unit", None)
    if pd.isna(value) or value in ("", None):
        return None
    return float(value)


def _is_low_acos(row: pd.Series) -> bool:
    acos = row.get("ACOS", None)
    if pd.isna(acos) or acos in ("", None) or float(row.get("ad_orders", 0)) <= 0:
        return False
    if _has_invalid_target_acos(row):
        return False
    profit = _profit_before_ads_per_unit(row)
    if profit is not None and profit <= 0:
        return False
    target_acos = _target_acos_value(row)
    if target_acos is not None:
        return float(acos) < target_acos
    return float(acos) <= 0.2


def _is_high_acos(row: pd.Series) -> bool:
    acos = row.get("ACOS", None)
    if pd.isna(acos) or acos in ("", None) or float(row.get("ad_sales", 0)) <= 0:
        return False
    if _has_invalid_target_acos(row):
        return False
    target_acos = _target_acos_value(row)
    if target_acos is not None:
        return float(acos) > target_acos
    return float(acos) >= 0.4


def _is_asin_search_term(term: str) -> bool:
    normalized = str(term).strip().upper().replace(" ", "")
    return bool(ASIN_TERM_PATTERN.match(normalized))


def _pattern_matches(term: str, pattern: str) -> bool:
    normalized = str(term).strip().lower()
    pattern = str(pattern).strip().lower()
    if not pattern:
        return False
    if " " in pattern:
        return pattern in normalized
    return bool(re.search(rf"(?<!\w){re.escape(pattern)}s?(?!\w)", normalized))


def _split_keyword_patterns(value: object) -> list[str]:
    if value in (None, "") or pd.isna(value):
        return []
    text = str(value).replace("\n", ";").replace("|", ";")
    return [part.strip().lower() for part in text.split(";") if part.strip()]


def _keyword_level_patterns(item: dict[str, object]) -> dict[str, list[str]]:
    levels = item.get("keyword_levels")
    if isinstance(levels, dict):
        return {
            "core": _split_keyword_patterns(";".join(levels.get("核心词", []) or levels.get("core_terms", []) or [])),
            "testable": _split_keyword_patterns(";".join(levels.get("可测词", []) or levels.get("testable_terms", []) or [])),
            "broad": _split_keyword_patterns(";".join(levels.get("泛词", []) or levels.get("broad_terms", []) or [])),
            "low_quality": _split_keyword_patterns(";".join(levels.get("低质词", []) or levels.get("low_quality_terms", []) or [])),
            "banned": _split_keyword_patterns(";".join(levels.get("禁词", []) or levels.get("banned_terms", []) or [])),
        }
    return {
        "core": _split_keyword_patterns(";".join(item.get("core_keywords", []) or [])),
        "testable": [],
        "broad": _split_keyword_patterns(";".join(item.get("broad_keywords", []) or [])),
        "low_quality": [],
        "banned": _split_keyword_patterns(";".join(item.get("irrelevant_keywords", []) or [])),
    }


@lru_cache(maxsize=1)
def _load_product_keyword_rules() -> list[dict[str, object]]:
    try:
        frame = pd.read_csv(PRODUCT_KEYWORD_RULES_PATH, dtype=str).fillna("") if PRODUCT_KEYWORD_RULES_PATH.exists() else pd.DataFrame()
    except Exception:
        frame = pd.DataFrame()
    rows: list[dict[str, object]] = []
    if not frame.empty:
        for _, row in frame.iterrows():
            rows.append(
                {
                    "marketplace": str(row.get("marketplace") or "").strip().upper(),
                    "product_line": str(row.get("product_line") or "").strip(),
                    "sku": str(row.get("sku") or "").strip(),
                    "asin": str(row.get("asin") or "").strip().upper(),
                    "name_patterns": [],
                    "core_keywords": _split_keyword_patterns(row.get("core_keywords")),
                    "broad_keywords": _split_keyword_patterns(row.get("broad_keywords")),
                    "irrelevant_keywords": _split_keyword_patterns(row.get("irrelevant_keywords")),
                    "competitor_keywords": _split_keyword_patterns(row.get("competitor_keywords")),
                    "source": "product_keyword_rules.csv",
                }
            )
    if PRODUCT_LINE_KEYWORDS_PATH.exists():
        try:
            payload = json.loads(PRODUCT_LINE_KEYWORDS_PATH.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        for item in payload.get("product_lines", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            levels = _keyword_level_patterns(item)
            rows.append(
                {
                    "marketplace": str(item.get("marketplace") or "").strip().upper(),
                    "product_line": str(item.get("product_line") or "").strip(),
                    "sku": "",
                    "asin": "",
                    "name_patterns": _split_keyword_patterns(";".join(item.get("name_patterns", []) or [])),
                    "core_keywords": levels["core"],
                    "testable_keywords": levels["testable"],
                    "broad_keywords": levels["broad"],
                    "low_quality_keywords": levels["low_quality"],
                    "irrelevant_keywords": levels["banned"],
                    "competitor_keywords": _split_keyword_patterns(";".join(item.get("competitor_keywords", []) or [])),
                    "keyword_levels": levels,
                    "source": "product_line_keywords.json",
                }
            )
    return rows


def _product_keyword_rule(
    marketplace: object = None,
    sku: object = None,
    asin: object = None,
    product_name: object = None,
) -> dict[str, object] | None:
    marketplace_key = str(marketplace or "").strip().upper()
    sku_key = str(sku or "").strip()
    asin_key = str(asin or "").strip().upper()
    product_name_key = str(product_name or "").strip().lower()
    if not marketplace_key and not sku_key and not asin_key and not product_name_key:
        return None
    candidates = []
    for rule in _load_product_keyword_rules():
        if marketplace_key and rule.get("marketplace") not in {"", marketplace_key}:
            continue
        score = 0
        if marketplace_key and rule.get("marketplace") == marketplace_key:
            score += 5
        if asin_key and rule.get("asin") == asin_key:
            score += 100
        if sku_key and rule.get("sku") == sku_key:
            score += 50
        if product_name_key and _match_rule_patterns(product_name_key, rule.get("name_patterns", [])):
            score += 20
        if score:
            candidates.append((score, rule))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _match_rule_patterns(term: str, patterns: list[str]) -> str | None:
    normalized = str(term or "").strip().lower()
    for pattern in patterns:
        if _pattern_matches(normalized, pattern):
            return pattern
    return None


def _is_core_relevant_search_term(term: str) -> bool:
    normalized = str(term).strip().lower()
    if _find_negative_pattern(normalized):
        return False
    if _is_asin_search_term(normalized):
        return False
    for pattern in COMPETITOR_OR_BRAND_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return False
    for pattern in CORE_RELEVANT_TERM_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return True
    return False


def _find_negative_pattern(
    term: str,
    marketplace: object = None,
    sku: object = None,
    asin: object = None,
    product_name: object = None,
) -> str | None:
    normalized = str(term).strip().lower()
    rule = _product_keyword_rule(marketplace=marketplace, sku=sku, asin=asin, product_name=product_name)
    if rule:
        product_pattern = _match_rule_patterns(normalized, rule.get("irrelevant_keywords", []))
        if product_pattern:
            return product_pattern
    for pattern in NEGATIVE_KEYWORD_PATTERNS:
        if pattern in normalized:
            return pattern
    return None


def _negative_sort_key(item: dict) -> tuple[float, float, float]:
    evidence = item.get("evidence", {})
    cvr = evidence.get("CVR")
    cvr_value = float(cvr) if cvr not in (None, "") else 999.0
    return (
        -float(evidence.get("spend", 0) or 0),
        -float(evidence.get("clicks", 0) or 0),
        cvr_value,
    )


def _default_sort_key(item: dict) -> tuple[float, float, float]:
    evidence = item.get("evidence", {})
    return (
        -float(evidence.get("spend", 0) or 0),
        -float(evidence.get("clicks", 0) or 0),
        -float(evidence.get("ad_orders", 0) or 0),
    )


def _format_value(key: str, value: object) -> str:
    if value in (None, ""):
        return "N/A"
    if key in {"ACOS", "TACOS", "CTR", "CVR", "target_acos", "suggested_target_acos", "break_even_acos"}:
        return f"{float(value) * 100:.1f}%"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _format_evidence(evidence: dict, keys: list[str]) -> str:
    parts: list[str] = []
    for key in keys:
        if key in evidence:
            parts.append(f"{key}={_format_value(key, evidence.get(key))}")
    return "；".join(parts) if parts else "无"


def _format_percent(value: object) -> str:
    if value in (None, ""):
        return "N/A"
    return f"{float(value) * 100:.1f}%"


def money_symbol_for_marketplace(marketplace: object = None, currency: object = None) -> str:
    currency_code = str(currency or "").strip().upper()
    marketplace_code = str(marketplace or "").strip().upper()
    if currency_code in {"GBP", "£"} or marketplace_code == "UK":
        return "£"
    if currency_code in {"USD", "$"} or marketplace_code == "US":
        return "$"
    if currency_code in {"EUR", "€"} or marketplace_code == "DE":
        return "€"
    return ""


def _format_money(value: object, marketplace: object = None, currency: object = None) -> str:
    if value in (None, ""):
        return "N/A"
    return f"{money_symbol_for_marketplace(marketplace, currency)}{float(value):.2f}"


def _format_count(value: object) -> str:
    if value in (None, ""):
        return "N/A"
    return str(int(round(float(value))))


def _infer_marketplace(analysis_payload: dict) -> str:
    for bucket in ["操作建议", "异常提醒"]:
        for item in analysis_payload.get(bucket, []):
            marketplace = item.get("evidence", {}).get("marketplace")
            if marketplace:
                return str(marketplace)
    product_summary = analysis_payload.get("产品汇总", {}).get("1d", [])
    if product_summary:
        marketplace = product_summary[0].get("marketplace")
        if marketplace:
            return str(marketplace)
    return "UK"


def _product_rule(row: pd.Series) -> tuple[str, str] | None:
    impressions = float(row.get("impressions", 0) or 0)
    clicks = float(row.get("clicks", 0) or 0)
    spend = float(row.get("spend", 0) or 0)
    ad_orders = float(row.get("ad_orders", 0) or 0)
    total_orders = float(row.get("total_orders", 0) or 0)
    natural_orders = float(row.get("natural_orders", 0) or 0)
    profit_before_ads_per_unit = _profit_before_ads_per_unit(row)

    if impressions == 0 and clicks == 0 and spend == 0 and (total_orders > 0 or natural_orders > 0):
        return "自然有单但广告无流量", "明天观察"
    if ad_orders == 0 and spend > 0:
        if clicks < 5 and spend < 2:
            return "样本量小且无销售", "明天观察"
        if clicks >= 15 or spend >= 5:
            return "有花费无销售", "今日必须处理"
        if profit_before_ads_per_unit is not None and spend > profit_before_ads_per_unit and clicks > 1:
            return "有花费无销售", "今日必须处理"
        if 5 <= clicks < 15:
            return "高点击无单", "低优先级检查"
    if _is_high_acos(row):
        return "高 ACOS", "今日必须处理"
    if _is_low_acos(row):
        low_volume = impressions < 500 and clicks < 5
        if low_volume:
            return "数据量小但已有转化，继续观察", "明天观察"
        return "有单低 ACOS", "可以放量"
    if impressions < 500 and clicks < 5:
        return "曝光低点击低", "低优先级检查"
    return None


def _latest_non_empty_value(frame: pd.DataFrame, column: str) -> object | None:
    if column not in frame.columns:
        return None
    series = frame[column].replace("", pd.NA).dropna()
    if series.empty:
        return None
    return series.iloc[-1]


def _to_float(value: object | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def _available_stock_value(frame: pd.DataFrame) -> float | None:
    for column in ["available_stock", "fba_stock", "available_inventory", "inventory", "stock"]:
        value = _latest_non_empty_value(frame, column)
        numeric = _to_float(value)
        if numeric is not None:
            return numeric
    return None


def _classify_search_term_intent(
    term: str,
    marketplace: object = None,
    sku: object = None,
    asin: object = None,
    product_name: object = None,
) -> str:
    normalized = str(term).strip().lower()
    rule = _product_keyword_rule(marketplace=marketplace, sku=sku, asin=asin, product_name=product_name)
    if rule and not _is_asin_search_term(normalized):
        if _match_rule_patterns(normalized, rule.get("irrelevant_keywords", [])):
            return "irrelevant"
        if _match_rule_patterns(normalized, rule.get("competitor_keywords", [])):
            return "competitor_or_brand"
        if _match_rule_patterns(normalized, rule.get("core_keywords", [])):
            return "core_relevant"
        if _match_rule_patterns(normalized, rule.get("testable_keywords", [])):
            return "testable_relevant"
        if _match_rule_patterns(normalized, rule.get("broad_keywords", [])):
            return "broad_generic"
        if _match_rule_patterns(normalized, rule.get("low_quality_keywords", [])):
            return "broad_generic"
    if _find_negative_pattern(normalized, marketplace=marketplace, sku=sku, asin=asin, product_name=product_name):
        return "irrelevant"
    for pattern in COMPETITOR_OR_BRAND_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return "competitor_or_brand"
    if _is_core_relevant_search_term(normalized):
        return "core_relevant"
    for pattern in CORE_RELEVANT_TERM_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return "core_relevant"
    for pattern in BROAD_GENERIC_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return "broad_generic"
    return "unknown"


def _classify_search_term_detail(
    term: str,
    marketplace: object = None,
    sku: object = None,
    asin: object = None,
    product_name: object = None,
) -> dict[str, str]:
    normalized = str(term).strip().lower()
    if _is_asin_search_term(normalized):
        return {
            "intent": "asin_targeting",
            "keyword_level": "ASIN定向",
            "matched_keyword": normalized.upper(),
            "classification_reason": "ASIN 定向，不按关键词词库直接判核心/禁词",
        }
    rule = _product_keyword_rule(marketplace=marketplace, sku=sku, asin=asin, product_name=product_name)
    if rule:
        checks = [
            ("禁词", "irrelevant", "irrelevant_keywords"),
            ("可测词", "competitor_or_brand", "competitor_keywords"),
            ("核心词", "core_relevant", "core_keywords"),
            ("可测词", "testable_relevant", "testable_keywords"),
            ("泛词", "broad_generic", "broad_keywords"),
            ("低质词", "broad_generic", "low_quality_keywords"),
        ]
        for level, intent, key in checks:
            matched = _match_rule_patterns(normalized, rule.get(key, []))
            if matched:
                product_line = str(rule.get("product_line") or "产品线")
                return {
                    "intent": intent,
                    "keyword_level": level,
                    "matched_keyword": matched,
                    "classification_reason": f"命中 {product_line} 的{level}词：{matched}",
                }
    negative = _find_negative_pattern(normalized, marketplace=marketplace, sku=sku, asin=asin, product_name=product_name)
    if negative:
        return {
            "intent": "irrelevant",
            "keyword_level": "禁词",
            "matched_keyword": negative,
            "classification_reason": f"命中通用禁词/不相关词：{negative}",
        }
    for pattern in COMPETITOR_OR_BRAND_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return {
                "intent": "competitor_or_brand",
                "keyword_level": "可测词",
                "matched_keyword": pattern,
                "classification_reason": f"命中竞品/品牌词：{pattern}，只做小预算验证",
            }
    for pattern in CORE_RELEVANT_TERM_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return {
                "intent": "core_relevant",
                "keyword_level": "核心词",
                "matched_keyword": pattern,
                "classification_reason": f"命中通用核心词：{pattern}",
            }
    for pattern in BROAD_GENERIC_PATTERNS:
        if _pattern_matches(normalized, pattern):
            return {
                "intent": "broad_generic",
                "keyword_level": "泛词",
                "matched_keyword": pattern,
                "classification_reason": f"命中通用泛词：{pattern}",
            }
    return {
        "intent": "unknown",
        "keyword_level": "可测词",
        "matched_keyword": "",
        "classification_reason": "未命中产品线词库，按可测词保守处理",
    }


def _inventory_stock_lookup(dataset: DailyDataset) -> dict[tuple[str, str, str], float]:
    lookup: dict[tuple[str, str, str], float] = {}
    mapping_check = getattr(dataset, "mapping_check", None)
    if mapping_check is None or getattr(mapping_check, "empty", True):
        return lookup
    for _, row in mapping_check.iterrows():
        key = (
            str(row.get("marketplace") or ""),
            str(row.get("sku") or ""),
            str(row.get("asin") or ""),
        )
        current_inventory = _to_float(row.get("current_inventory"))
        sea_inventory = _to_float(row.get("sea_inventory"))
        values = [value for value in [current_inventory, sea_inventory] if value is not None]
        if values:
            lookup[key] = float(sum(values))
    return lookup


def _inventory_stock_lookup_by_asin(dataset: DailyDataset) -> dict[tuple[str, str], float]:
    lookup: dict[tuple[str, str], float] = {}
    for triple_key, value in _inventory_stock_lookup(dataset).items():
        marketplace, _sku, asin = triple_key
        key = (marketplace, asin)
        lookup[key] = max(float(value), lookup.get(key, 0.0))
    return lookup


def _product_asin_daily(dataset: DailyDataset) -> pd.DataFrame:
    frame = dataset.product_daily.copy()
    if frame.empty:
        return frame
    group_keys = ["date", *PRODUCT_WINDOW_KEYS]
    sum_columns = [
        "impressions",
        "clicks",
        "spend",
        "ad_orders",
        "ad_sales",
        "total_orders",
        "total_sales",
        "natural_orders",
    ]
    aggregations = {column: "sum" for column in sum_columns if column in frame.columns}
    for column in [
        "sku",
        "product_name",
        "currency",
        "owner",
        "category",
        "target_acos",
        "profit_before_ads_per_unit",
        "unit_cost",
        "shipping_cost",
        "handling_fee",
        "selling_price",
        "fba_fee",
        "referral_fee",
        "vat",
        "digital_tax",
        "first_leg_cost",
        "purchase_cost",
        "break_even_acos",
        "cost_status",
    ]:
        if column in frame.columns and column not in group_keys:
            aggregations[column] = "first"
    grouped = frame.groupby(group_keys, dropna=False).agg(aggregations).reset_index()
    return add_ratio_columns(grouped)


def _product_window_record(views: HistoricalViews, days: int) -> dict[tuple[str, str, str], dict]:
    frame = views.product_windows.get(days, pd.DataFrame())
    lookup: dict[tuple[str, str, str], dict] = {}
    if frame.empty:
        return lookup
    for record in frame.to_dict(orient="records"):
        key = (
            str(record.get("marketplace") or ""),
            str(record.get("sku") or ""),
            str(record.get("asin") or ""),
        )
        lookup[key] = record
    return lookup


def _build_product_window_metrics(views: HistoricalViews) -> dict[str, list[dict]]:
    payload: dict[str, list[dict]] = {}
    for days, frame in views.product_windows.items():
        rows: list[dict] = []
        for row in frame.to_dict(orient="records"):
            total_orders = _to_float(row.get("total_orders")) or 0
            ad_orders = _to_float(row.get("ad_orders")) or 0
            rows.append(
                {
                    "marketplace": row.get("marketplace"),
                    "asin": row.get("asin"),
                    "sku": row.get("sku"),
                    "product_name": row.get("product_name"),
                    "ad_impressions": _round_metric(_to_float(row.get("impressions")) or 0),
                    "ad_clicks": _round_metric(_to_float(row.get("clicks")) or 0),
                    "ad_spend": _round_metric(_to_float(row.get("spend")) or 0),
                    "ad_orders": _round_metric(ad_orders),
                    "ad_sales": _round_metric(_to_float(row.get("ad_sales")) or 0),
                    "total_orders": _round_metric(total_orders),
                    "total_sales": _round_metric(_to_float(row.get("total_sales")) or 0),
                    "natural_orders": _round_metric(max(total_orders - ad_orders, 0)),
                    "ACOS": row.get("ACOS"),
                    "TACOS": row.get("TACOS"),
                    "ad_CVR": row.get("CVR"),
                    "ad_order_share": None if total_orders == 0 else ad_orders / total_orders,
                    "available_stock": row.get("available_stock"),
                    "target_acos": row.get("target_acos"),
                    "profit_before_ads_per_unit": row.get("profit_before_ads_per_unit"),
                }
            )
        payload[f"{days}d"] = rows
    return payload


REVIEW_PRODUCT_DAILY_FIELDS = [
    "date",
    "marketplace",
    "sku",
    "asin",
    "product_name",
    "clicks",
    "spend",
    "ad_orders",
    "ad_sales",
    "promoted_ad_orders",
    "promoted_ad_sales",
    "halo_ad_orders",
    "halo_ad_sales",
    "total_orders",
    "total_sales",
    "natural_orders",
    "available_stock",
    "target_acos",
]
REVIEW_SEARCH_TERM_DAILY_FIELDS = [
    "date",
    "marketplace",
    "sku",
    "asin",
    "product_name",
    "search_term",
    "campaign_name",
    "targeting",
    "matched_target",
    "match_type",
    "clicks",
    "spend",
    "ad_orders",
    "ad_sales",
    "promoted_ad_orders",
    "promoted_ad_sales",
    "halo_ad_orders",
    "halo_ad_sales",
]


def _review_daily_records(frame: pd.DataFrame, fields: list[str]) -> list[dict]:
    if frame.empty:
        return []
    available_fields = [field for field in fields if field in frame.columns]
    if not available_fields:
        return []
    export = frame[available_fields].copy()
    if "date" in export.columns:
        export["date"] = pd.to_datetime(export["date"]).dt.date.astype(str)
    records: list[dict] = []
    for record in export.to_dict(orient="records"):
        records.append(
            {
                key: (None if pd.isna(value) else _round_metric(value, 4) if isinstance(value, float) else value)
                for key, value in record.items()
            }
        )
    return records


def _build_unsold_risks(dataset: DailyDataset, views: HistoricalViews) -> list[dict]:
    product_history = _product_asin_daily(dataset)
    if product_history.empty:
        return []
    product_history["date"] = pd.to_datetime(product_history["date"]).dt.normalize()
    common_start, common_end = dataset.common_date_range
    if common_start is None or common_end is None:
        return []

    full_dates = pd.date_range(common_start, common_end, freq="D")
    window_starts = {
        7: pd.Timestamp(common_end - timedelta(days=6)),
        14: pd.Timestamp(common_end - timedelta(days=13)),
        30: pd.Timestamp(common_end - timedelta(days=29)),
    }
    latest_meta = product_history.sort_values("date").groupby(PRODUCT_WINDOW_KEYS, dropna=False).tail(1)
    inventory_lookup = _inventory_stock_lookup(dataset)
    risk_rows: list[dict] = []

    for product_key, group in product_history.groupby(PRODUCT_WINDOW_KEYS, dropna=False):
        marketplace, sku, asin = product_key
        group = group.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        latest_row = latest_meta[
            (latest_meta["marketplace"] == marketplace)
            & (latest_meta["sku"] == sku)
            & (latest_meta["asin"] == asin)
        ]
        latest_row = latest_row.iloc[-1] if not latest_row.empty else group.iloc[-1]

        full_group = group.set_index("date").reindex(full_dates)
        full_group["marketplace"] = marketplace
        full_group["sku"] = sku
        full_group["asin"] = asin
        for column in ["product_name", "currency", "owner", "category"]:
            if column in full_group.columns:
                full_group[column] = full_group[column].ffill().bfill()
        numeric_columns = [
            "impressions",
            "clicks",
            "spend",
            "ad_orders",
            "ad_sales",
            "total_orders",
            "total_sales",
            "natural_orders",
            "CTR",
            "CPC",
            "CVR",
            "ACOS",
            "TACOS",
            "unit_cost",
            "shipping_cost",
            "handling_fee",
            "has_spend_no_sales",
            "target_acos",
            "profit_before_ads_per_unit",
        ]
        for column in numeric_columns:
            if column in full_group.columns:
                full_group[column] = pd.to_numeric(full_group[column], errors="coerce").fillna(0)

        recent_7 = full_group[full_group.index >= window_starts[7]]
        recent_14 = full_group[full_group.index >= window_starts[14]]
        recent_30 = full_group[full_group.index >= window_starts[30]]

        recent_7_total_orders = float(recent_7["total_orders"].sum())
        recent_14_total_orders = float(recent_14["total_orders"].sum())
        recent_30_total_orders = float(recent_30["total_orders"].sum())
        recent_14_ad_orders = float(recent_14["ad_orders"].sum())
        recent_14_ad_spend = float(recent_14["spend"].sum())
        recent_14_clicks = float(recent_14["clicks"].sum())
        recent_14_natural_orders = float(recent_14["natural_orders"].sum())
        available_stock = inventory_lookup.get(product_key)
        if available_stock is None:
            available_stock = _available_stock_value(group)
        profit_before_ads_per_unit = _profit_before_ads_per_unit(latest_row)
        target_acos = _target_acos_value(latest_row)
        last_order_dates = full_group.loc[full_group["total_orders"] > 0].index
        last_order_date = last_order_dates.max().date() if not last_order_dates.empty else None
        consecutive_no_order_days = (
            (common_end - last_order_date).days if last_order_date else (common_end - common_start).days + 1
        )

        severe_reasons: list[str] = []
        medium_reasons: list[str] = []

        if recent_7_total_orders > 0 or consecutive_no_order_days <= 3 or recent_14_total_orders >= 3:
            continue

        if recent_14_total_orders == 0 and available_stock is not None and available_stock > 0 and consecutive_no_order_days >= 14:
            severe_reasons.append("近14天总订单为0、连续无单>=14天且仍有库存")
        if recent_30_total_orders <= 1 and available_stock is not None and available_stock >= 20 and consecutive_no_order_days >= 7:
            severe_reasons.append("近30天总订单<=1、库存>=20且连续无单>=7天")
        if recent_14_total_orders == 0 and recent_14_ad_spend > 0 and available_stock is not None and available_stock > 0:
            severe_reasons.append("近14天总订单为0且广告有花费")

        if recent_7_total_orders == 0 and recent_14_total_orders <= 1 and available_stock is not None and available_stock > 0:
            medium_reasons.append("近7天总订单为0、近14天总订单<=1且仍有库存")
        if recent_30_total_orders <= 2 and available_stock is not None and available_stock >= 20 and consecutive_no_order_days >= 5:
            medium_reasons.append("近30天总订单<=2、库存>=20且连续无单>=5天")

        if not severe_reasons and not medium_reasons:
            continue

        risk_level = "严重风险" if severe_reasons else "中度风险"
        reasons = severe_reasons if severe_reasons else medium_reasons
        if (profit_before_ads_per_unit is not None and profit_before_ads_per_unit < 0) or target_acos == 0:
            suggestion = "先核对售价、采购成本、头程成本、FBA费用；若利润为负属实，不建议加广告放量。"
        else:
            suggestion = "先检查价格、主图、评价、Coupon、竞品、Listing 承接和利润结构；确认利润允许且核心词高度相关后，再小预算测试精准词或商品投放。不要直接加预算放量。"

        risk_rows.append(
            {
                "risk_level": risk_level,
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": str(latest_row.get("product_name") or "N/A"),
                "available_stock": available_stock,
                "recent_7d_total_orders": _round_metric(recent_7_total_orders),
                "recent_14d_total_orders": _round_metric(recent_14_total_orders),
                "recent_30d_total_orders": _round_metric(recent_30_total_orders),
                "recent_14d_ad_orders": _round_metric(recent_14_ad_orders),
                "recent_14d_ad_spend": _round_metric(recent_14_ad_spend),
                "recent_14d_clicks": _round_metric(recent_14_clicks),
                "recent_14d_natural_orders": _round_metric(recent_14_natural_orders),
                "last_order_date": last_order_date.isoformat() if last_order_date else None,
                "consecutive_no_order_days": int(consecutive_no_order_days),
                "profit_before_ads_per_unit": profit_before_ads_per_unit,
                "target_acos": target_acos,
                "reason": "；".join(reasons),
                "suggestion": suggestion,
            }
        )

    severity_order = {"严重风险": 0, "中度风险": 1}
    return sorted(
        risk_rows,
        key=lambda row: (
            severity_order.get(str(row.get("risk_level") or ""), 99),
            -float(row.get("recent_14d_ad_spend") or 0),
            -float(row.get("recent_14d_clicks") or 0),
            str(row.get("sku") or ""),
        ),
    )


def _build_recent_product_rollup(dataset: DailyDataset, views: HistoricalViews) -> list[dict]:
    common_start, common_end = dataset.common_date_range
    if common_start is None or common_end is None:
        return []
    inventory_lookup = _inventory_stock_lookup(dataset)
    win7 = _product_window_record(views, 7)
    win14 = _product_window_record(views, 14)
    win30 = _product_window_record(views, 30)
    product_history = _product_asin_daily(dataset)
    if product_history.empty:
        return []
    product_history["date"] = pd.to_datetime(product_history["date"]).dt.normalize()
    rows: list[dict] = []
    for product_key, recent_14 in win14.items():
        recent_7 = win7.get(product_key, {})
        recent_30 = win30.get(product_key, {})
        marketplace, sku, asin = product_key
        group = product_history[
            (product_history["marketplace"].astype(str) == marketplace)
            & (product_history["sku"].astype(str) == sku)
            & (product_history["asin"].astype(str) == asin)
        ]
        last_order_dates = group.loc[pd.to_numeric(group["total_orders"], errors="coerce").fillna(0) > 0, "date"]
        last_order_date = last_order_dates.max().date() if not last_order_dates.empty else None
        available_stock = inventory_lookup.get(product_key)
        if available_stock is None:
            available_stock = _available_stock_value(group) if not group.empty else None
        rows.append(
            {
                "marketplace": marketplace,
                "sku": sku or recent_14.get("sku") or "N/A",
                "asin": asin,
                "product_name": str(recent_14.get("product_name") or "N/A"),
                "currency": recent_14.get("currency"),
                "available_stock": available_stock,
                "recent_7d_total_orders": _round_metric(float(recent_7.get("total_orders") or 0)),
                "recent_7d_ad_orders": _round_metric(float(recent_7.get("ad_orders") or 0)),
                "recent_7d_ad_spend": _round_metric(float(recent_7.get("spend") or 0)),
                "recent_7d_clicks": _round_metric(float(recent_7.get("clicks") or 0)),
                "recent_7d_ad_sales": _round_metric(float(recent_7.get("ad_sales") or 0)),
                "recent_14d_total_orders": _round_metric(float(recent_14.get("total_orders") or 0)),
                "recent_14d_total_sales": _round_metric(float(recent_14.get("total_sales") or 0)),
                "recent_30d_total_orders": _round_metric(float(recent_30.get("total_orders") or 0)),
                "recent_14d_ad_orders": _round_metric(float(recent_14.get("ad_orders") or 0)),
                "recent_14d_ad_spend": _round_metric(float(recent_14.get("spend") or 0)),
                "recent_14d_clicks": _round_metric(float(recent_14.get("clicks") or 0)),
                "recent_14d_ad_sales": _round_metric(float(recent_14.get("ad_sales") or 0)),
                "recent_14d_natural_orders": _round_metric(float(recent_14.get("natural_orders") or 0)),
                "recent_14d_acos": recent_14.get("ACOS"),
                "recent_14d_tacos": recent_14.get("TACOS"),
                "recent_14d_ad_cvr": recent_14.get("CVR"),
                "recent_14d_ad_order_share": None if float(recent_14.get("total_orders") or 0) == 0 else float(recent_14.get("ad_orders") or 0) / float(recent_14.get("total_orders") or 0),
                "last_order_date": last_order_date.isoformat() if last_order_date else None,
                "consecutive_no_order_days": int((common_end - last_order_date).days if last_order_date else (common_end - common_start).days + 1),
                "profit_before_ads_per_unit": _to_float(recent_14.get("profit_before_ads_per_unit")),
                "target_acos": _to_float(recent_14.get("target_acos")),
                "selling_price": _to_float(recent_14.get("selling_price")),
                "purchase_cost": _to_float(recent_14.get("purchase_cost")),
                "first_leg_cost": _to_float(recent_14.get("first_leg_cost")),
                "fba_fee": _to_float(recent_14.get("fba_fee")),
                "referral_fee": _to_float(recent_14.get("referral_fee")),
                "vat": _to_float(recent_14.get("vat")),
                "digital_tax": _to_float(recent_14.get("digital_tax")),
                "break_even_acos": _to_float(recent_14.get("break_even_acos")),
                "cost_status": None if pd.isna(recent_14.get("cost_status")) else recent_14.get("cost_status"),
            }
        )
    return rows


def _build_ad_no_conversion_risks(dataset: DailyDataset, views: HistoricalViews) -> list[dict]:
    rows: list[dict] = []
    for row in _build_recent_product_rollup(dataset, views):
        ad_orders = float(row.get("recent_14d_ad_orders") or 0)
        clicks = float(row.get("recent_14d_clicks") or 0)
        spend = float(row.get("recent_14d_ad_spend") or 0)
        total_orders = float(row.get("recent_14d_total_orders") or 0)
        profit = _to_float(row.get("profit_before_ads_per_unit")) or 0
        if ad_orders != 0:
            continue
        severe_reasons: list[str] = []
        medium_reasons: list[str] = []
        if clicks >= 20:
            severe_reasons.append("近14天广告无单且点击>=20")
        if spend >= max(10.0, profit):
            severe_reasons.append("近14天广告无单且花费达到利润/固定阈值")
        if spend >= 5 and total_orders > 0:
            severe_reasons.append("近期总订单存在，但广告花费>=5且无广告订单")
        if clicks >= 5:
            medium_reasons.append("近14天广告无单且点击>=5")
        if spend >= 3:
            medium_reasons.append("近14天广告无单且花费>=3")
        if not severe_reasons and not medium_reasons:
            continue
        reasons = severe_reasons if severe_reasons else medium_reasons
        row = row.copy()
        row["risk_level"] = "严重风险" if severe_reasons else "中度风险"
        row["reason"] = "；".join(reasons)
        row["suggestion"] = "先拆搜索词相关性和 Listing 转化，不要把它并入滞销判断；核心词降竞价并检查价格、主图、评价。"
        rows.append(row)
    severity_order = {"严重风险": 0, "中度风险": 1}
    return sorted(rows, key=lambda row: (severity_order.get(str(row.get("risk_level") or ""), 99), -float(row.get("recent_14d_ad_spend") or 0), -float(row.get("recent_14d_clicks") or 0)))


def _build_inventory_profit_pressure_risks(dataset: DailyDataset, views: HistoricalViews) -> list[dict]:
    rows: list[dict] = []
    for row in _build_recent_product_rollup(dataset, views):
        profit = _to_float(row.get("profit_before_ads_per_unit"))
        target_acos = _target_acos_value(row)
        reasons: list[str] = []
        if profit is not None and profit <= 0:
            reasons.append("广告前利润<=0")
        if _has_invalid_target_acos(row):
            reasons.append("target_acos<=0")
        if not reasons:
            continue
        row = row.copy()
        row["target_acos"] = target_acos if target_acos is not None else 0
        row["risk_level"] = "严重风险"
        row["reason"] = "；".join(reasons)
        row["suggestion"] = "先核对售价、采购成本、头程和 FBA 费用；利润为负或 target_acos<=0 时禁止建议加预算或放量；缺失目标 ACOS 才临时按 10% 观察。"
        rows.append(row)
    severity_order = {"严重风险": 0, "中度风险": 1}
    return sorted(rows, key=lambda row: (severity_order.get(str(row.get("risk_level") or ""), 99), -float(row.get("available_stock") or 0), str(row.get("sku") or "")))


def _build_anomalies(views: HistoricalViews, risk_targets: set[tuple[str, str, str]] | None = None) -> list[dict]:
    anomalies: list[dict] = []
    risk_targets = risk_targets or set()
    today_products = views.product_windows[1]

    for _, row in today_products.iterrows():
        product_rule = _product_rule(row)
        if not product_rule:
            continue
        rule, level = product_rule
        triple_key = (str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
        if triple_key in risk_targets and level in {"明天观察", "低优先级检查"}:
            continue
        if rule == "自然有单但广告无流量":
            continue
        if rule == "曝光低点击低" and (
            float(row.get("total_orders", 0) or 0) > 0 or float(row.get("natural_orders", 0) or 0) > 0
        ):
            continue
        evidence = _serialize_row(
            row,
            [
                "marketplace",
                "sku",
                "asin",
                "product_name",
                "impressions",
                "clicks",
                "spend",
                "ad_orders",
                "ad_sales",
                "total_orders",
                "total_sales",
                "natural_orders",
                "CTR",
                "CPC",
                "CVR",
                "ACOS",
                "TACOS",
                "target_acos",
                "profit_before_ads_per_unit",
                "has_spend_no_sales",
            ],
        )
        evidence["level"] = level
        anomalies.append({"rule": rule, "target": row["sku"], "evidence": evidence})

    if views.data_days >= 14:
        recent_products = views.product_windows[7].groupby(TRIPLE_KEYS, dropna=False)[["natural_orders"]].sum()
        prior_products = views.product_windows[14].groupby(TRIPLE_KEYS, dropna=False)[["natural_orders"]].sum()
        for triple_key in sorted(set(recent_products.index) & set(prior_products.index)):
            recent_natural = float(recent_products.loc[triple_key, "natural_orders"])
            full_natural = float(prior_products.loc[triple_key, "natural_orders"])
            prior_natural = max(full_natural - recent_natural, 0.0)
            if (
                prior_natural >= 5
                and recent_natural <= prior_natural * 0.5
                and (prior_natural - recent_natural) >= 3
            ):
                drop_abs = prior_natural - recent_natural
                drop_pct = drop_abs / prior_natural if prior_natural else None
                anomalies.append(
                    {
                        "rule": "自然单下降",
                        "target": triple_key[1],
                        "evidence": {
                            "marketplace": triple_key[0],
                            "sku": triple_key[1],
                            "asin": triple_key[2],
                            "recent_period_days": 7,
                            "recent_period_natural_orders": _round_metric(recent_natural),
                            "prior_period_natural_orders": _round_metric(prior_natural),
                            "natural_order_drop_abs": _round_metric(drop_abs),
                            "natural_order_drop_pct": _round_metric(drop_pct) if drop_pct is not None else None,
                        },
                    }
                )

    if views.data_days >= 14:
        recent_orders = views.product_windows[7].groupby(TRIPLE_KEYS, dropna=False)[["ad_orders", "total_orders", "natural_orders"]].sum()
        prior_orders = views.product_windows[14].groupby(TRIPLE_KEYS, dropna=False)[["ad_orders", "total_orders", "natural_orders"]].sum()
        for triple_key in sorted(set(recent_orders.index) & set(prior_orders.index)):
            recent_row = recent_orders.loc[triple_key]
            full_row = prior_orders.loc[triple_key]
            prior_ad_orders = max(float(full_row["ad_orders"]) - float(recent_row["ad_orders"]), 0.0)
            prior_total_orders = max(float(full_row["total_orders"]) - float(recent_row["total_orders"]), 0.0)
            prior_natural_orders = max(float(full_row["natural_orders"]) - float(recent_row["natural_orders"]), 0.0)
            recent_ad_orders = float(recent_row["ad_orders"])
            recent_total_orders = float(recent_row["total_orders"])
            recent_natural_orders = float(recent_row["natural_orders"])
            if (
                recent_ad_orders > prior_ad_orders
                and recent_total_orders <= prior_total_orders
                and prior_natural_orders >= 5
                and recent_natural_orders <= prior_natural_orders * 0.5
                and (prior_natural_orders - recent_natural_orders) >= 3
            ):
                anomalies.append(
                    {
                        "rule": "广告替代自然单",
                        "target": triple_key[1],
                        "evidence": {
                            "marketplace": triple_key[0],
                            "sku": triple_key[1],
                            "asin": triple_key[2],
                            "recent_period_days": 7,
                            "recent_ad_orders": _round_metric(recent_ad_orders),
                            "prior_ad_orders": _round_metric(prior_ad_orders),
                            "recent_total_orders": _round_metric(recent_total_orders),
                            "prior_total_orders": _round_metric(prior_total_orders),
                            "recent_natural_orders": _round_metric(recent_natural_orders),
                            "prior_natural_orders": _round_metric(prior_natural_orders),
                        },
                    }
                )
    return _deduplicate_anomalies(anomalies)


def _build_recommendations(views: HistoricalViews, risk_targets: set[tuple[str, str, str]] | None = None) -> list[dict]:
    if views.data_days < 7:
        return [
            _recommendation(
                level="明天观察",
                category="数据不足",
                target="全店",
                action="数据不足，仅观察",
                evidence={"history_days": views.data_days},
                note="历史数据不足 7 天，不输出强动作建议。",
                markdown_section="明天观察",
                markdown_visible=True,
                priority_rank=100,
            )
        ]

    recommendations: list[dict] = []
    risk_targets = risk_targets or set()
    today_products = views.product_windows[1]
    search_terms_7d = views.search_term_windows[7]
    anomalies = _build_anomalies(views)

    for _, row in today_products.iterrows():
        evidence = _serialize_row(
            row,
            [
                "marketplace",
                "sku",
                "asin",
                "product_name",
                "impressions",
                "clicks",
                "spend",
                "ad_orders",
                "ad_sales",
                "total_orders",
                "total_sales",
                "natural_orders",
                "ACOS",
                "TACOS",
                "target_acos",
                "profit_before_ads_per_unit",
            ],
        )
        product_rule = _product_rule(row)
        if not product_rule:
            continue
        rule, level = product_rule
        if level == "今日必须处理":
            action = "有花费无销售，优先检查投放词、Listing 转化和竞价" if rule == "有花费无销售" else "ACOS 高于目标，建议降竞价并收缩低效词" if rule == "高 ACOS" else "高点击无单，暂停低效词或检查详情页转化"
            recommendations.append(
                _recommendation(
                    level="今日必须处理",
                    category="产品",
                    target=row["sku"],
                    action=action,
                    evidence=evidence,
                    markdown_section="今日必须处理",
                    markdown_visible=True,
                    priority_rank=1 if rule == "有花费无销售" else 3 if rule == "高 ACOS" else 2,
                )
            )
        elif level == "可以放量":
            recommendations.append(
                _recommendation(
                    level="可以放量",
                    category="产品",
                    target=row["sku"],
                    action="表现稳定，可小幅放量",
                    evidence=evidence,
                    markdown_section="可以放量",
                    markdown_visible=True,
                    priority_rank=4,
                )
            )
        elif level == "明天观察":
            action = "自然有单但广告无流量，检查广告是否开启/预算/竞价" if rule == "自然有单但广告无流量" else "数据量小但已有转化，继续观察" if rule == "数据量小但已有转化，继续观察" else "样本量小且无销售，继续观察"
            recommendations.append(
                _recommendation(
                    level="明天观察",
                    category="产品",
                    target=row["sku"],
                    action=action,
                    evidence=evidence,
                    markdown_section="明天观察",
                    markdown_visible=True,
                    priority_rank=5,
                )
            )
        else:
            recommendations.append(
                _recommendation(
                    level="低优先级检查",
                    category="产品",
                    target=row["sku"],
                    action="低优先级检查搜索词与页面转化" if rule != "曝光低点击低" else "曝光低点击低，先检查广告结构与出价",
                    evidence=evidence,
                    markdown_section=None,
                    markdown_visible=False,
                    priority_rank=99,
                )
            )

    for anomaly in anomalies:
        rule = anomaly["rule"]
        if rule == "自然单下降":
            recommendations.append(
                _recommendation(
                    level="明天观察",
                    category="产品趋势",
                    target=anomaly["target"],
                    action="自然单明显下降，检查自然位、评价、价格和广告承接",
                    evidence=anomaly["evidence"],
                    markdown_section="明天观察",
                    markdown_visible=True,
                    priority_rank=6,
                )
            )
        elif rule == "广告替代自然单":
            recommendations.append(
                _recommendation(
                    level="明天观察",
                    category="产品趋势",
                    target=anomaly["target"],
                    action="广告订单增长但总单未增，自然单下降，检查是否广告替代自然单",
                    evidence=anomaly["evidence"],
                    markdown_section="明天观察",
                    markdown_visible=True,
                    priority_rank=7,
                )
            )

    for _, row in search_terms_7d.iterrows():
        clicks = float(row.get("clicks", 0) or 0)
        spend = float(row.get("spend", 0) or 0)
        ad_orders = float(row.get("ad_orders", 0) or 0)
        search_term = str(row.get("search_term", "") or "").strip()
        is_asin_term = _is_asin_search_term(search_term)
        negative_pattern = _find_negative_pattern(
            search_term,
            marketplace=row.get("marketplace"),
            sku=row.get("sku"),
            asin=row.get("asin"),
        )
        term_detail = _classify_search_term_detail(
            search_term,
            marketplace=row.get("marketplace"),
            sku=row.get("sku"),
            asin=row.get("asin"),
            product_name=row.get("product_name"),
        )
        intent = term_detail["intent"]
        profit_before_ads_per_unit = _profit_before_ads_per_unit(row)
        evidence = _serialize_row(
            row,
            [
                "marketplace",
                "search_term",
                "campaign_name",
                "ad_group_name",
                "targeting",
                "matched_target",
                "match_type",
                "sku",
                "asin",
                "product_name",
                "clicks",
                "spend",
                "ad_orders",
                "ad_sales",
                "CVR",
                "ACOS",
                "profit_before_ads_per_unit",
            ],
        )
        evidence["is_asin_term"] = is_asin_term
        evidence["intent"] = intent
        evidence["is_core_term"] = intent in {"core_relevant", "testable_relevant"}
        evidence["keyword_level"] = term_detail.get("keyword_level", "")
        evidence["matched_keyword"] = term_detail.get("matched_keyword", "")
        evidence["classification_reason"] = term_detail.get("classification_reason", "")
        product_keyword_rule = _product_keyword_rule(
            marketplace=row.get("marketplace"),
            sku=row.get("sku"),
            asin=row.get("asin"),
        )
        if product_keyword_rule:
            evidence["product_line"] = product_keyword_rule.get("product_line") or ""
            evidence["keyword_rule_source"] = "product_line"

        if ad_orders > 0:
            continue

        if is_asin_term and clicks < 5 and spend < 2:
            recommendations.append(
                _recommendation(
                    level="明天观察",
                    category="搜索词",
                    target=search_term,
                    action="ASIN 定向样本量小，继续观察",
                    evidence=evidence,
                    markdown_section=None,
                    markdown_visible=False,
                    priority_rank=99,
                )
            )
            continue

        if clicks <= 2 and spend < 2:
            recommendations.append(
                _recommendation(
                    level="明天观察",
                    category="搜索词",
                    target=search_term,
                    action="1-2 次点击无单，低优先级观察",
                    evidence=evidence,
                    markdown_section=None,
                    markdown_visible=False,
                    priority_rank=99,
                )
            )
            continue

        if negative_pattern and (clicks >= IRRELEVANT_TERM_MIN_CLICKS or spend >= IRRELEVANT_TERM_MIN_SPEND):
            recommendations.append(
                _recommendation(
                    level="建议否词/暂停",
                    category="搜索词",
                    target=search_term,
                    action="明显不相关，建议否词或暂停该词/定向",
                    evidence=evidence,
                    note=f"搜索词包含明显不相关词，且已有实际消耗: {negative_pattern}",
                    markdown_section="建议否词/暂停",
                    markdown_visible=True,
                    priority_rank=2,
                )
            )
        elif clicks <= 5:
            recommendations.append(
                _recommendation(
                    level="明天观察",
                    category="搜索词",
                    target=search_term,
                    action="3-5 次点击无单，观察或小幅降竞价，暂不做否定处理",
                    evidence=evidence,
                    note=f"intent={intent}",
                    markdown_section=None,
                    markdown_visible=False,
                    priority_rank=90,
                )
            )
        elif clicks <= 10:
            if intent in {"core_relevant", "testable_relevant"}:
                action = "强相关词点击无单，先降竞价并检查 Listing，暂不做否定处理"
                section = None
                visible = False
            elif intent in {"broad_generic", "competitor_or_brand", "unknown"}:
                action = "泛词/竞品词点击无单，建议降竞价或暂停观察"
                section = "建议否词/暂停"
                visible = True
            else:
                action = "检查相关性后处理"
                section = None
                visible = False
            recommendations.append(
                _recommendation(
                    level="建议否词/暂停" if visible else "明天观察",
                    category="搜索词",
                    target=search_term,
                    action=action,
                    evidence=evidence,
                    note=f"intent={intent}；6-10 次点击无单",
                    markdown_section=section,
                    markdown_visible=visible,
                    priority_rank=20 if visible else 80,
                )
            )
        elif clicks > 10 or spend >= 3 or (profit_before_ads_per_unit is not None and spend >= profit_before_ads_per_unit):
            if intent in {"core_relevant", "testable_relevant"}:
                action = "核心强相关词点击后不转化，先检查价格、主图、评价和 Listing，再降竞价"
            elif intent in {"broad_generic", "competitor_or_brand", "unknown"}:
                action = "高点击无单，可暂停或否词；先确认是否仍有相关转化价值"
            else:
                action = "高点击无单，建议否词或暂停"
            recommendations.append(
                _recommendation(
                    level="建议否词/暂停",
                    category="搜索词",
                    target=search_term,
                    action=action,
                    evidence=evidence,
                    note=f"intent={intent}；10+ 次点击无单或花费较高",
                    markdown_section="建议否词/暂停",
                    markdown_visible=True,
                    priority_rank=2,
                )
            )
        else:
            recommendations.append(
                _recommendation(
                    level="明天观察",
                    category="搜索词",
                    target=search_term,
                    action="点击或花费尚不足以判定，继续观察",
                    evidence=evidence,
                    markdown_section=None,
                    markdown_visible=False,
                    priority_rank=99,
                    note=f"命中疑似无关词 {negative_pattern}，但样本仍小于 clicks>={IRRELEVANT_TERM_MIN_CLICKS} 或 spend>={IRRELEVANT_TERM_MIN_SPEND}",
                )
            )

    if not recommendations:
        recommendations.append(
            _recommendation(
                level="明天观察",
                category="全店",
                target="全店",
                action="当前未触发强规则，延续观察",
                evidence={"history_days": views.data_days},
                markdown_section="明天观察",
                markdown_visible=True,
                priority_rank=100,
            )
        )
    return _deduplicate_recommendations(recommendations)


def build_analysis_payload(report_date: date, source_files: dict[str, str], dataset: DailyDataset, views: HistoricalViews) -> dict:
    product_summary = {f"{days}d": _window_records(frame, "spend") for days, frame in views.product_windows.items()}
    campaign_summary = {f"{days}d": _window_records(frame, "spend") for days, frame in views.campaign_windows.items()}
    search_term_summary = {f"{days}d": _window_records(frame, "clicks") for days, frame in views.search_term_windows.items()}
    anomalies = _build_anomalies(views)
    risk_rows = _build_unsold_risks(dataset, views)
    ad_no_conversion_rows = _build_ad_no_conversion_risks(dataset, views)
    inventory_profit_rows = _build_inventory_profit_pressure_risks(dataset, views)
    risk_targets = {(str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or "")) for row in risk_rows}
    recommendations = _build_recommendations(views, risk_targets=risk_targets)
    return {
        "report_date": report_date.isoformat(),
        "source_files": source_files,
        "ads_date_range": {
            "start": dataset.ads_date_range[0].isoformat() if dataset.ads_date_range[0] else None,
            "end": dataset.ads_date_range[1].isoformat() if dataset.ads_date_range[1] else None,
        },
        "erp_date_range": {
            "start": dataset.erp_date_range[0].isoformat() if dataset.erp_date_range[0] else None,
            "end": dataset.erp_date_range[1].isoformat() if dataset.erp_date_range[1] else None,
        },
        "erp_observed_sales_date_range": {
            "start": dataset.erp_observed_sales_date_range[0].isoformat() if dataset.erp_observed_sales_date_range[0] else None,
            "end": dataset.erp_observed_sales_date_range[1].isoformat() if dataset.erp_observed_sales_date_range[1] else None,
        },
        "erp_report_coverage_date_range": {
            "start": dataset.erp_report_coverage_date_range[0].isoformat() if dataset.erp_report_coverage_date_range[0] else None,
            "end": dataset.erp_report_coverage_date_range[1].isoformat() if dataset.erp_report_coverage_date_range[1] else None,
        },
        "erp_zero_filled_days": dataset.erp_zero_filled_days,
        "erp_last_sales_date": dataset.erp_last_sales_date.isoformat() if dataset.erp_last_sales_date else None,
        "zero_fill_applied": dataset.zero_fill_applied,
        "coverage_warning": dataset.coverage_warning,
        "common_date_range": {
            "start": dataset.common_date_range[0].isoformat() if dataset.common_date_range[0] else None,
            "end": dataset.common_date_range[1].isoformat() if dataset.common_date_range[1] else None,
        },
        "history_days": dataset.history_days,
        "data_quality": {
            "data_days": views.data_days,
            "validation_messages": dataset.validation_messages,
        },
        "产品汇总": product_summary,
        "product_window_metrics": _build_product_window_metrics(views),
        "review_product_daily": _review_daily_records(views.product_history, REVIEW_PRODUCT_DAILY_FIELDS),
        "review_search_term_daily": _review_daily_records(views.search_term_history, REVIEW_SEARCH_TERM_DAILY_FIELDS),
        "广告活动汇总": campaign_summary,
        "搜索词分析": search_term_summary,
        "异常提醒": anomalies,
        "操作建议": recommendations,
        "滞销 / 持续无单风险": risk_rows,
        "滞销风险": risk_rows,
        "广告消耗无转化风险": ad_no_conversion_rows,
        "库存 / 利润压力风险": inventory_profit_rows,
        "sku_mapping_check": dataset.mapping_check.to_dict(orient="records"),
    }


def _records_by_asin(records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        asin = str(record.get("asin") or "").strip()
        if asin:
            grouped.setdefault(asin, []).append(record)
    return grouped


def _best_numeric(records: list[dict], key: str, default: float = 0.0) -> float:
    values = []
    for record in records:
        value = _to_float(record.get(key))
        if value is not None:
            values.append(value)
    return max(values) if values else default


def _sum_numeric(records: list[dict], key: str) -> float:
    total = 0.0
    for record in records:
        value = _to_float(record.get(key))
        if value is not None:
            total += value
    return total


def _latest_product_lookup(analysis_payload: dict) -> dict[tuple[str, str, str], dict]:
    lookup: dict[tuple[str, str, str], dict] = {}
    for window in ["1d", "7d", "14d", "30d"]:
        for record in analysis_payload.get("产品汇总", {}).get(window, []):
            key = (str(record.get("marketplace") or ""), str(record.get("sku") or ""), str(record.get("asin") or ""))
            current = lookup.get(key, {})
            merged = {**record, **current}
            lookup[key] = merged
    return lookup


def build_no_order_diagnostics(analysis_payload: dict) -> list[dict]:
    common_days = 0
    common_range = analysis_payload.get("common_date_range") or {}
    try:
        common_start = pd.to_datetime(common_range.get("start")).date()
        common_end = pd.to_datetime(common_range.get("end")).date()
        common_days = max((common_end - common_start).days + 1, 0)
    except Exception:
        common_days = 0
    if int(analysis_payload.get("history_days", 0) or 0) < 7 or common_days < 7:
        data_insufficient = True
    else:
        data_insufficient = False

    product_lookup = _latest_product_lookup(analysis_payload)
    candidates: dict[tuple[str, str, str], dict] = {}
    for source in ["滞销风险"]:
        for row in analysis_payload.get(source, []):
            key = (str(row.get("marketplace") or ""), str(row.get("sku") or ""), str(row.get("asin") or ""))
            if key[2]:
                candidates[key] = {**product_lookup.get(key, {}), **row}
    for key, row in product_lookup.items():
        if data_insufficient:
            candidates.setdefault(key, row)
            continue
        recent_7 = float(row.get("total_orders", row.get("recent_7d_total_orders", 0)) or 0)
        recent_14 = float(row.get("recent_14d_total_orders", row.get("total_orders", 0)) or 0)
        recent_30 = float(row.get("recent_30d_total_orders", row.get("total_orders", 0)) or 0)
        stock = _to_float(row.get("available_stock")) or 0
        high_stock = stock >= 20
        if stock > 0 and (recent_7 == 0 or recent_14 == 0 or (recent_30 <= 1 and high_stock)):
            candidates.setdefault(key, row)

    traffic_by_asin = _records_by_asin(analysis_payload.get("custom_traffic_sales", []))
    query_by_asin = _records_by_asin(analysis_payload.get("custom_search_query_performance", []))
    search_terms_by_asin = _records_by_asin(analysis_payload.get("搜索词分析", {}).get("7d", []))

    diagnostics: list[dict] = []
    for key, product in candidates.items():
        marketplace, sku, asin = key
        product_name = product.get("product_name") or sku or asin
        if data_insufficient:
            diagnostics.append(
                {
                    "marketplace": marketplace,
                    "sku": sku,
                    "asin": asin,
                    "product_name": product_name,
                    "primary_reason": "数据不足",
                    "secondary_reasons": "",
                    "evidence": "ERP 历史数据不足，暂不判断不出单原因",
                    "recommended_action": "补充至少7天 ERP 数据后再诊断",
                    "recent_14d_clicks": 0,
                    "recent_14d_ad_spend": 0,
                    "recent_14d_ad_orders": 0,
                    "recent_14d_total_orders": 0,
                }
            )
            continue
        traffic_records = traffic_by_asin.get(asin, [])
        query_records = query_by_asin.get(asin, [])
        term_records = search_terms_by_asin.get(asin, [])
        clicks = _to_float(product.get("recent_14d_clicks")) or _to_float(product.get("clicks")) or _sum_numeric(term_records, "clicks")
        spend = _to_float(product.get("recent_14d_ad_spend")) or _to_float(product.get("spend")) or _sum_numeric(term_records, "spend")
        ad_orders = _to_float(product.get("recent_14d_ad_orders")) or _to_float(product.get("ad_orders")) or 0
        total_orders = _to_float(product.get("recent_14d_total_orders")) or _to_float(product.get("total_orders")) or 0
        profit = _to_float(product.get("profit_before_ads_per_unit"))
        target_acos = _target_acos_value(product)
        featured_offer_rate = _best_numeric(traffic_records, "recent_featured_offer_rate", 1.0)
        conversion_rate = _best_numeric(traffic_records, "recent_conversion_rate", 0.0)
        page_views = _best_numeric(traffic_records, "recent_featured_offer_page_views", 0.0)
        query_impressions = _sum_numeric(query_records, "query_impressions")
        query_clicks = _sum_numeric(query_records, "query_clicks")
        query_cart_adds = _sum_numeric(query_records, "query_cart_adds")
        query_purchases = _sum_numeric(query_records, "query_purchases")
        irrelevant_clicks = sum(
            _to_float(row.get("clicks")) or 0
            for row in term_records
            if _classify_search_term_intent(
                str(row.get("search_term") or ""),
                marketplace=row.get("marketplace") or marketplace,
                sku=row.get("sku") or product.get("sku"),
                asin=row.get("asin") or product.get("asin"),
                product_name=row.get("product_name") or product.get("product_name"),
            )
            == "irrelevant"
        )

        evidence_parts = [
            f"近14天广告点击 {int(clicks)}",
            f"广告订单 {int(ad_orders)}",
            f"广告花费 {_format_money(spend, marketplace=marketplace)}",
            f"近14天总单 {int(total_orders)}",
        ]
        if traffic_records:
            evidence_parts.append(f"traffic_sales 转化率 {_format_percent(conversion_rate)}")
            evidence_parts.append(f"推荐报价率 {_format_percent(featured_offer_rate)}")
            evidence_parts.append(f"推荐报价浏览量 {int(page_views)}")
        if query_records:
            evidence_parts.append(f"搜索查询展示 {int(query_impressions)} / 点击 {int(query_clicks)} / 加购 {int(query_cart_adds)} / 购买 {int(query_purchases)}")
        if (traffic_records or query_records) and all(str(row.get("period_hint") or "") == "unknown" for row in [*traffic_records, *query_records]):
            evidence_parts.append("增强数据周期未知，诊断仅供参考")

        secondary: list[str] = []
        if profit is not None and profit <= 0:
            primary = "利润不允许加广告"
            action = "核对售价、采购成本、头程、FBA 费用；不要放量"
        elif featured_offer_rate < 0.9:
            primary = "推荐报价风险"
            action = "检查 Buy Box、价格、库存和配送"
        elif clicks >= 10 and ad_orders == 0:
            primary = "点击后不转化"
            action = "检查 Listing、价格、评价、图片、五点和 A+，先不扩广告预算"
        elif query_cart_adds > 0 and query_purchases == 0:
            primary = "加购后不购买"
            action = "检查价格、Coupon、配送和竞品承接"
        elif query_impressions >= 300 and query_clicks <= max(2, query_impressions * 0.01):
            primary = "搜索结果点击弱"
            action = "检查主图、标题、价格、Coupon 和评分"
        elif irrelevant_clicks >= max(3, clicks * 0.5):
            primary = "搜索词不相关"
            action = "否掉明显不相关词，暂停无关 ASIN 定向"
        elif clicks == 0 and spend == 0:
            primary = "广告没跑起来"
            action = "检查广告是否开启、预算和竞价"
        elif page_views < 10 and query_impressions < 100:
            primary = "流量不足"
            action = "扩充强相关精准词和相关 ASIN，小预算测试"
        else:
            primary = "Listing 转化问题"
            action = "先修页面和价格，先不扩广告预算"

        if clicks >= 10 and ad_orders == 0 and primary != "点击后不转化":
            secondary.append("点击后不转化")
        if query_cart_adds > 0 and query_purchases == 0 and primary != "加购后不购买":
            secondary.append("加购后不购买")
        if irrelevant_clicks >= 3 and primary != "搜索词不相关":
            secondary.append("搜索词不相关")
        if featured_offer_rate < 0.9 and primary != "推荐报价风险":
            secondary.append("推荐报价风险")

        diagnostics.append(
            {
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": product_name,
                "primary_reason": primary,
                "secondary_reasons": "；".join(secondary) if secondary else "N/A",
                "evidence": "；".join(evidence_parts),
                "recommended_action": action,
                "recent_14d_clicks": _round_metric(clicks),
                "recent_14d_ad_spend": _round_metric(spend),
                "recent_14d_ad_orders": _round_metric(ad_orders),
                "recent_14d_total_orders": _round_metric(total_orders),
            }
        )
    reason_order = {
        "数据不足": 0,
        "利润不允许加广告": 1,
        "推荐报价风险": 2,
        "点击后不转化": 3,
        "加购后不购买": 4,
        "搜索结果点击弱": 5,
        "搜索词不相关": 6,
        "广告没跑起来": 7,
        "流量不足": 8,
        "Listing 转化问题": 9,
    }
    return sorted(
        diagnostics,
        key=lambda row: (
            reason_order.get(str(row.get("primary_reason") or ""), 99),
            -float(row.get("recent_14d_clicks") or 0),
            -float(row.get("recent_14d_ad_spend") or 0),
            str(row.get("sku") or ""),
        ),
    )


def _select_markdown_items(section: str, items: list[dict]) -> list[dict]:
    visible_items = [
        item
        for item in items
        if item.get("markdown_visible", True) and item.get("markdown_section") == section
    ]
    if section == "建议否词/暂停":
        asin_items = [item for item in visible_items if item.get("evidence", {}).get("is_asin_term")]
        non_asin_items = [item for item in visible_items if not item.get("evidence", {}).get("is_asin_term")]
        asin_items = sorted(asin_items, key=_negative_sort_key)[:10]
        combined = sorted(non_asin_items, key=_negative_sort_key)
        for item in asin_items:
            combined.append(item)
        deduped: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in sorted(combined, key=_negative_sort_key):
            key = (item["target"], str(item.get("evidence", {}).get("sku", "")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[: SECTION_LIMITS[section]]
    sorted_items = sorted(
        visible_items,
        key=lambda item: (item.get("priority_rank", 999), *_default_sort_key(item)),
    )
    return sorted_items[: SECTION_LIMITS[section]]
