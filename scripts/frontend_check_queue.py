from __future__ import annotations

from urllib.parse import quote_plus


def marketplace_search_url(marketplace: str, keyword: str) -> str:
    keyword = str(keyword or "").strip()
    if not keyword:
        return ""
    query = quote_plus(keyword)
    marketplace = str(marketplace or "").upper()
    if marketplace == "UK":
        return f"https://www.amazon.co.uk/s?k={query}"
    if marketplace == "US":
        return f"https://www.amazon.com/s?k={query}"
    if marketplace == "DE":
        return f"https://www.amazon.de/s?k={query}"
    return ""


def marketplace_product_url(marketplace: str, asin: str) -> str:
    asin = str(asin or "").strip().upper()
    if not asin:
        return ""
    marketplace = str(marketplace or "").upper()
    if marketplace == "UK":
        return f"https://www.amazon.co.uk/dp/{asin}?th=1"
    if marketplace == "US":
        return f"https://www.amazon.com/dp/{asin}"
    if marketplace == "DE":
        return f"https://www.amazon.de/dp/{asin}"
    return ""


def queue_rows(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for result in payload.get("marketplace_results", []):
        view = result.get("report_view_snapshot", {})
        for row in view.get("frontend_check_queue_rows", []) or []:
            if isinstance(row, dict):
                rows.append(row)
    deduped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (
            str(row.get("marketplace") or "").upper(),
            str(row.get("sku") or ""),
            str(row.get("asin") or "").upper(),
        )
        if key[0] and key[2] and key not in deduped:
            deduped[key] = row
    return list(deduped.values())


def fallback_rows_from_payload(payload: dict, filters: dict[str, str]) -> list[dict]:
    candidates: list[dict] = []
    row_keys = [
        "today_task_queue_rows",
        "listing_price_diagnosis_rows",
        "frontend_check_queue_rows",
    ]
    for result in payload.get("marketplace_results", []) or []:
        view = result.get("report_view_snapshot", {}) if isinstance(result, dict) else {}
        if not isinstance(view, dict):
            continue
        for key in row_keys:
            for row in view.get(key, []) or []:
                if isinstance(row, dict):
                    candidates.append(row)
    matched: list[dict] = []
    for row in candidates:
        marketplace = str(row.get("marketplace") or row.get("站点") or "").strip().upper()
        sku = str(row.get("sku") or row.get("SKU") or "").strip()
        asin = str(row.get("asin") or row.get("ASIN") or "").strip().upper()
        if filters.get("marketplace") and marketplace != filters["marketplace"]:
            continue
        if filters.get("sku") and sku != filters["sku"]:
            continue
        if filters.get("asin") and asin != filters["asin"]:
            continue
        product_name = str(row.get("product_name") or row.get("产品") or "").strip()
        keyword = str(row.get("frontend_core_keyword") or product_name).strip()
        enriched = dict(row)
        enriched.update(
            {
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": product_name,
                "product_url": row.get("product_url") or marketplace_product_url(marketplace, asin),
                "frontend_core_keyword": keyword,
                "frontend_search_url": row.get("frontend_search_url") or marketplace_search_url(marketplace, keyword),
                "frontend_check_status": row.get("frontend_check_status") or "待前台检查",
                "frontend_check_focus": row.get("frontend_check_focus") or "价格；Coupon；Buy Box；评分；评论；配送；前三竞品",
                "questions_to_check": row.get("questions_to_check") or "价格是否有优势；Coupon 是否明确；Buy Box 是否正常；评分评论是否弱于竞品",
                "suspected_issue": row.get("suspected_issue") or row.get("primary_reason") or row.get("issue_type") or "",
            }
        )
        matched.append(enriched)
        break
    if matched:
        return matched
    marketplace = str(filters.get("marketplace") or "").strip().upper()
    asin = str(filters.get("asin") or "").strip().upper()
    if not marketplace or not asin:
        return []
    sku = str(filters.get("sku") or "").strip() or f"ADHOC-{marketplace}-{asin}"
    product_name = f"Public Amazon ASIN {asin}"
    keyword = product_name
    return [
        {
            "marketplace": marketplace,
            "sku": sku,
            "asin": asin,
            "product_name": product_name,
            "product_url": marketplace_product_url(marketplace, asin),
            "frontend_core_keyword": keyword,
            "frontend_search_url": marketplace_search_url(marketplace, keyword),
            "frontend_check_status": "待前台检查",
            "frontend_check_focus": "价格；Coupon；Buy Box；评分；评论；配送；前三竞品",
            "questions_to_check": "价格是否有优势；Coupon 是否明确；Buy Box 是否正常；评分评论是否弱于竞品",
            "suspected_issue": "临时公开商品检查行，仅用于本地服务功能验证。",
            "source_role": "ad_hoc_public_test",
            "priority": "P1",
        }
    ]
