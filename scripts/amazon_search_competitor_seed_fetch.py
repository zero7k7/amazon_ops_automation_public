from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import frontend_check_queue as queue_state
from scripts import frontend_search_fetch as search_fetch
from src.sellersprite_competitor_discovery import (
    SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
    load_competitor_discovery_records,
    make_discovery_record,
    merge_competitor_discovery_records,
    normalize_competitors,
)
from src.sellersprite_fusion import (
    SELLERSPRITE_CACHE_PATH,
    build_sellersprite_competitor_pool,
    load_sellersprite_records,
)


OUTPUT_DIR = ROOT / "data" / "output"
LATEST_ANALYSIS = OUTPUT_DIR / "latest_analysis.json"
DEFAULT_PROFILE = OUTPUT_DIR / "chrome_frontend_profile_v2" / "amazon_search_seed"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MARKETPLACE_HOST = {
    "UK": "www.amazon.co.uk",
    "US": "www.amazon.com",
    "DE": "www.amazon.de",
}


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def _split_keywords(value: object) -> list[str]:
    seen: list[str] = []
    for item in re.split(r"[、；,|]", str(value or "")):
        text = _norm(item)
        if text and text not in seen:
            seen.append(text)
    return seen


def _search_url(marketplace: str, keyword: str) -> str:
    host = MARKETPLACE_HOST.get(str(marketplace or "").strip().upper())
    return f"https://{host}/s?k={quote_plus(keyword)}" if host and keyword else ""


def _candidate_keywords(row: dict, *, limit: int = 1) -> list[str]:
    candidates: list[str] = []
    for key in ("frontend_core_keyword", "frontend_search_keyword"):
        text = _norm(row.get(key))
        if text and text not in candidates:
            candidates.append(text)
    for text in _split_keywords(row.get("own_sellersprite_keywords")):
        if text not in candidates:
            candidates.append(text)
    return candidates[:limit]


def _needs_amazon_seed(
    row: dict,
    seller_records: dict[tuple[str, str], dict],
    discovery_records: dict[tuple[str, str, str], dict],
    *,
    limit_per_product: int,
) -> bool:
    marketplace = str(row.get("marketplace") or "").strip().upper()
    asin = str(row.get("asin") or "").strip().upper()
    own_record = seller_records.get((marketplace, asin), {})
    pool = build_sellersprite_competitor_pool(
        row,
        own_record,
        seller_records,
        limit=limit_per_product,
        competitor_discovery_records=discovery_records,
    )
    return int(pool.get("competitor_pool_count") or 0) < limit_per_product


def _record_from_search_payload(
    row: dict,
    *,
    keyword: str,
    parsed_search: dict[str, object],
    checked_at: str,
    limit_per_product: int,
    search_error: str = "",
) -> dict:
    marketplace = str(row.get("marketplace") or "").strip().upper()
    own_asin = str(row.get("asin") or "").strip().upper()
    raw_competitors: list[dict[str, object]] = []
    for item in parsed_search.get("competitors") or []:
        if not isinstance(item, dict):
            continue
        asin = str(item.get("asin") or "").strip().upper()
        if not asin or asin == own_asin:
            continue
        raw_competitors.append(
                {
                    "competitor_asin": asin,
                    "competitor_title": item.get("title") or "",
                    "competitor_source": "amazon_search_visible",
                    "source_page": "amazon_search_seed",
                    "source_keyword": keyword,
                    "traffic_or_rank_hint": f"Amazon自然位 {item.get('position') or ''}".strip(),
                    "confidence": "medium",
                }
            )
    competitors = normalize_competitors(
        raw_competitors,
        marketplace=marketplace,
        sku=str(row.get("sku") or ""),
        asin=own_asin,
        checked_at=checked_at,
        data_date=checked_at.split("T", 1)[0],
        limit=limit_per_product,
    )
    status = "已抓取" if competitors else "Amazon搜索无竞品"
    return make_discovery_record(
        row,
        competitors=competitors,
        status=status,
        source_page="amazon_search_seed",
        checked_at=checked_at,
        last_error=_norm(search_error)[:240],
    )


def rows_from_latest_analysis(
    *,
    marketplace: str = "",
    sku: str = "",
    asin: str = "",
    priority: str = "",
) -> list[dict]:
    payload = json.loads(LATEST_ANALYSIS.read_text(encoding="utf-8"))
    rows = queue_state.queue_rows(payload)
    filters = {
        "marketplace": str(marketplace or "").strip().upper(),
        "sku": str(sku or "").strip(),
        "asin": str(asin or "").strip().upper(),
    }
    if any(filters.values()):
        rows = [
            row
            for row in rows
            if (not filters["marketplace"] or str(row.get("marketplace") or "").strip().upper() == filters["marketplace"])
            and (not filters["sku"] or str(row.get("sku") or "").strip() == filters["sku"])
            and (not filters["asin"] or str(row.get("asin") or "").strip().upper() == filters["asin"])
        ]
        if not rows:
            rows = queue_state.fallback_rows_from_payload(payload, filters)
    priority_filter = str(priority or "").strip().upper()
    if priority_filter:
        rows = [row for row in rows if str(row.get("priority") or "").strip().upper() == priority_filter]
    return rows


def fetch_for_rows(
    rows: list[dict],
    *,
    profile: Path = DEFAULT_PROFILE,
    limit_per_product: int = 3,
    keywords_per_product: int = 1,
    timeout_ms: int = 25000,
    headless: bool = False,
    only_missing_pool: bool = True,
) -> list[dict]:
    seller_records = load_sellersprite_records(SELLERSPRITE_CACHE_PATH)
    discovery_records = load_competitor_discovery_records(SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH)
    selected = [
        row
        for row in rows
        if not only_missing_pool
        or _needs_amazon_seed(row, seller_records, discovery_records, limit_per_product=limit_per_product)
    ]
    if not selected:
        print("[amazon-search-seed] no rows need Amazon search seed", flush=True)
        return []
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        records = [
            make_discovery_record(
                row,
                competitors=[],
                status="Amazon搜索失败",
                source_page="amazon_search_seed",
                last_error=f"Playwright 不可用：{exc}",
            )
            for row in selected
        ]
        merge_competitor_discovery_records(records, SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH)
        return records

    records: list[dict] = []
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            viewport={"width": 1365, "height": 1800},
            user_agent=USER_AGENT,
            args=["--no-first-run", "--no-default-browser-check", "--window-position=-32000,-32000", "--window-size=1365,1800"],
            ignore_default_args=["--enable-automation"],
        )
        try:
            for index, row in enumerate(selected, start=1):
                marketplace = str(row.get("marketplace") or "").strip().upper()
                asin = str(row.get("asin") or "").strip().upper()
                keywords = _candidate_keywords(row, limit=keywords_per_product)
                print(
                    f"[amazon-search-seed] {index}/{len(selected)} {marketplace} {asin} keywords={len(keywords)}",
                    flush=True,
                )
                record: dict | None = None
                for keyword in keywords:
                    url = _search_url(marketplace, keyword)
                    checked_at = datetime.now().isoformat(timespec="seconds")
                    parsed: dict[str, object] = {}
                    error = ""
                    page = context.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        with contextlib.suppress(PlaywrightTimeoutError):
                            page.wait_for_selector('[data-component-type="s-search-result"][data-asin]', timeout=9000)
                        page.mouse.wheel(0, 1400)
                        page.wait_for_timeout(700)
                        parsed_raw = page.evaluate(
                            search_fetch.SEARCH_DOM_EVAL_JS,
                            {"ownAsin": asin, "limit": limit_per_product},
                        )
                        parsed = parsed_raw if isinstance(parsed_raw, dict) else {}
                    except Exception as exc:
                        error = str(exc)
                    finally:
                        with contextlib.suppress(Exception):
                            page.close()
                    record = _record_from_search_payload(
                        row,
                        keyword=keyword,
                        parsed_search=parsed,
                        checked_at=checked_at,
                        limit_per_product=limit_per_product,
                        search_error=error,
                    )
                    if record.get("competitors"):
                        break
                if record is None:
                    record = make_discovery_record(
                        row,
                        competitors=[],
                        status="Amazon搜索无关键词",
                        source_page="amazon_search_seed",
                    )
                print(
                    f"[amazon-search-seed] {marketplace} {asin} {record.get('competitor_discovery_status')} "
                    f"competitors={record.get('competitor_count')} error={record.get('last_error') or ''}",
                    flush=True,
                )
                records.append(record)
                time.sleep(0.2)
        finally:
            context.close()
    merge_competitor_discovery_records(records, SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed competitor discovery from Amazon keyword search pages.")
    parser.add_argument("--marketplace", default="")
    parser.add_argument("--sku", default="")
    parser.add_argument("--asin", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--competitor-limit-per-product", type=int, default=3)
    parser.add_argument("--keywords-per-product", type=int, default=1)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--timeout-ms", type=int, default=25000)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--all-rows", action="store_true", help="即使已有有效竞品池，也重新抓 Amazon 搜索候选。")
    args = parser.parse_args()
    if not LATEST_ANALYSIS.exists():
        raise SystemExit(f"missing {LATEST_ANALYSIS}; run main.py --marketplace ALL first")
    rows = rows_from_latest_analysis(
        marketplace=args.marketplace,
        sku=args.sku,
        asin=args.asin,
        priority=args.priority,
    )
    if args.limit is not None:
        rows = rows[: args.limit]
    records = fetch_for_rows(
        rows,
        profile=Path(args.profile).expanduser(),
        limit_per_product=args.competitor_limit_per_product,
        keywords_per_product=args.keywords_per_product,
        timeout_ms=args.timeout_ms,
        headless=args.headless,
        only_missing_pool=not args.all_rows,
    )
    success = sum(1 for record in records if record.get("competitors"))
    print(
        f"[amazon-search-seed] wrote {SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH}; success={success}/{len(records)}",
        flush=True,
    )
    return 0 if success or not records else 1


if __name__ == "__main__":
    raise SystemExit(main())
