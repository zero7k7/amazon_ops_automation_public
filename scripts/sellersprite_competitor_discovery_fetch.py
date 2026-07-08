from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import frontend_check_queue as queue_state
from src.sellersprite_competitor_discovery import (
    SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
    discovery_record_needs_refresh,
    load_competitor_discovery_records,
    make_discovery_record,
    merge_competitor_discovery_records,
    parse_competitors_from_html,
    sellersprite_market_id,
)


OUTPUT_DIR = ROOT / "data" / "output"
LATEST_ANALYSIS = OUTPUT_DIR / "latest_analysis.json"
DEFAULT_PROFILE = OUTPUT_DIR / "chrome_sellersprite_profile_chromium"

DIRECT_ROUTES = [
    (
        "sellersprite_keyword_reverse_seed",
        "reversing",
        "https://www.sellersprite.com/v3/reversing?asin={asin}&marketId={market_id}&utm_source=codex_competitor_discovery",
    ),
    (
        "sellersprite_reversing_sources",
        "reversing_sources",
        "https://www.sellersprite.com/v3/reversing/sources?asin={asin}&marketId={market_id}&utm_source=codex_competitor_discovery",
    ),
    (
        "sellersprite_relation_keyword",
        "relation_keyword",
        "https://www.sellersprite.com/v3/relation-keyword?asin={asin}&market={market_id}&utm_source=codex_competitor_discovery",
    ),
    (
        "sellersprite_traffic_extend",
        "traffic_extend",
        "https://www.sellersprite.com/v3/traffic/extend/asin?q={asin}&marketId={market_id}&search=true&utm_source=codex_competitor_discovery",
    ),
    (
        "sellersprite_keyword_reverse_seed",
        "keyword_reverse_seed",
        "https://www.sellersprite.com/v3/keyword-reverse/?q={asin}&marketId={market_id}&utm_source=codex_competitor_discovery",
    ),
]

PAGE_READY_JS = r"""
({asin}) => {
  const text = document.body ? document.body.innerText : '';
  if (!text) return false;
  if (text.includes(asin)) return true;
  if (/50x|网页走丢|云游火星/i.test(text) || /\/html\/50x\//i.test(location.href)) return true;
  return /未登录|登录|无权限|暂无数据|无数据|没有数据|竞品|流量|关键词|ASIN/i.test(text);
}
"""


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


def _discovery_url(template: str, marketplace: str, asin: str) -> str:
    return template.format(asin=str(asin or "").strip().upper(), market_id=sellersprite_market_id(marketplace))


def _failure_status_from_error(error: str) -> str:
    text = str(error or "")
    if "Timeout" in text or "timeout" in text:
        return "网络超时"
    if "未登录" in text or "login" in text.lower():
        return "未登录"
    if "权限" in text or "permission" in text.lower():
        return "页面无权限"
    if "无竞品数据" in text:
        return "无竞品数据"
    return "页面结构变化"


def fetch_competitor_discovery_record(
    row: dict,
    *,
    profile: Path = DEFAULT_PROFILE,
    limit: int = 3,
    timeout_ms: int = 60000,
    visible: bool = True,
) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return make_discovery_record(row, competitors=[], status="页面结构变化", last_error=f"Playwright 不可用：{exc}")

    marketplace = str(row.get("marketplace") or "").strip().upper()
    asin = str(row.get("asin") or "").strip().upper()
    if not marketplace or not asin:
        return make_discovery_record(row, competitors=[], status="页面结构变化", last_error="缺少 marketplace 或 asin")
    try:
        sellersprite_market_id(marketplace)
    except ValueError as exc:
        return make_discovery_record(row, competitors=[], status="页面结构变化", last_error=str(exc))

    checked_at = datetime.now().isoformat(timespec="seconds")
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile),
                headless=not visible,
                viewport={"width": 1500, "height": 1000},
                locale="zh-CN",
                args=["--no-first-run", "--no-default-browser-check", "--window-position=-32000,-32000", "--window-size=1500,1000"],
                ignore_default_args=["--enable-automation"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            for source, page_name, template in DIRECT_ROUTES:
                url = _discovery_url(template, marketplace, asin)
                try:
                    page.goto(url, wait_until="commit", timeout=timeout_ms)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_function(PAGE_READY_JS, arg={"asin": asin}, timeout=35000, polling=500)
                    page.evaluate("() => window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight))")
                    page.wait_for_timeout(800)
                    content = page.content()
                    competitors, reason = parse_competitors_from_html(
                        content,
                        marketplace=marketplace,
                        sku=str(row.get("sku") or ""),
                        asin=asin,
                        source_page=page_name,
                        competitor_source=source,
                        checked_at=checked_at,
                        limit=limit,
                    )
                    if competitors:
                        context.close()
                        return make_discovery_record(
                            row,
                            competitors=competitors,
                            status="已抓取",
                            source_page=page_name,
                            checked_at=checked_at,
                        )
                    errors.append(f"{page_name}: {reason}")
                    if reason in {"未登录", "页面无权限"}:
                        break
                except Exception as exc:
                    errors.append(f"{page_name}: {exc}")
            context.close()
    except Exception as exc:
        errors.append(str(exc))
    last_error = "；".join(error for error in errors if error)[-1000:]
    status = _failure_status_from_error(last_error)
    return make_discovery_record(row, competitors=[], status=status, checked_at=checked_at, last_error=last_error)


def fetch_for_rows(
    rows: list[dict],
    *,
    profile: Path = DEFAULT_PROFILE,
    limit_per_product: int = 3,
    row_limit: int | None = None,
    visible: bool = True,
    skip_cached: bool = True,
    cache_days: int = 7,
) -> list[dict]:
    selected = rows[:row_limit] if row_limit is not None else rows
    if skip_cached:
        existing = load_competitor_discovery_records(SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH, max_age_days=cache_days)
        before = len(selected)
        selected = [
            row
            for row in selected
            if discovery_record_needs_refresh(
                existing.get(
                    (
                        str(row.get("marketplace") or "").strip().upper(),
                        str(row.get("sku") or "").strip(),
                        str(row.get("asin") or "").strip().upper(),
                    )
                ),
                max_age_days=cache_days,
            )
        ]
        skipped = before - len(selected)
        if skipped:
            print(f"[sellersprite-discovery] skipped cached rows: {skipped}", flush=True)
    records: list[dict] = []
    for index, row in enumerate(selected, start=1):
        print(
            f"[sellersprite-discovery] {index}/{len(selected)} {row.get('marketplace')} {row.get('asin')} 开始竞品发现",
            flush=True,
        )
        record = fetch_competitor_discovery_record(
            row,
            profile=profile,
            limit=limit_per_product,
            visible=visible,
        )
        print(
            f"[sellersprite-discovery] {record.get('marketplace')} {record.get('asin')} "
            f"{record.get('competitor_discovery_status')} competitors={record.get('competitor_count')} "
            f"error={record.get('last_error') or ''}",
            flush=True,
        )
        records.append(record)
        time.sleep(0.2)
    merge_competitor_discovery_records(records, SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch SellerSprite direct competitor discovery rows for frontend queue products.")
    parser.add_argument("--marketplace", default="")
    parser.add_argument("--sku", default="")
    parser.add_argument("--asin", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--competitor-limit-per-product", type=int, default=3)
    parser.add_argument("--cache-days", type=int, default=7)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not LATEST_ANALYSIS.exists():
        raise SystemExit(f"missing {LATEST_ANALYSIS}; run main.py --marketplace ALL first")
    rows = rows_from_latest_analysis(
        marketplace=args.marketplace,
        sku=args.sku,
        asin=args.asin,
        priority=args.priority,
    )
    records = fetch_for_rows(
        rows,
        profile=Path(args.profile).expanduser(),
        limit_per_product=args.competitor_limit_per_product,
        row_limit=args.limit,
        visible=not args.headless,
        skip_cached=not args.force,
        cache_days=args.cache_days,
    )
    existing = load_competitor_discovery_records(SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH, max_age_days=args.cache_days)
    covered = sum(
        1
        for row in rows
        if (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip().upper(),
        )
        in existing
    )
    success = sum(1 for record in records if record.get("competitors"))
    print(
        f"[sellersprite-discovery] wrote {SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH}; "
        f"success={success}/{len(records)} cached_cover={covered}/{len(rows)}",
        flush=True,
    )
    return 0 if success or not records or covered else 1


if __name__ == "__main__":
    raise SystemExit(main())
