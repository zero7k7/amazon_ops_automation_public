from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import frontend_check_queue as queue_state
from scripts import amazon_search_competitor_seed_fetch as amazon_seed_fetch
from scripts import sellersprite_competitor_discovery_fetch as competitor_discovery_fetch
from src.sellersprite_competitor_discovery import (
    SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
    load_competitor_discovery_records,
)
from src.sellersprite_fusion import (
    SELLERSPRITE_CACHE_PATH,
    build_sellersprite_competitor_pool,
    load_sellersprite_records,
    merge_sellersprite_records,
)
from src.sellersprite_history import (
    sellersprite_cache_max_age_days_for_row,
    upsert_sellersprite_history,
)


OUTPUT_DIR = ROOT / "data" / "output"
LATEST_ANALYSIS = OUTPUT_DIR / "latest_analysis.json"
DEFAULT_PROFILE = OUTPUT_DIR / "chrome_sellersprite_profile_chromium"
DEFAULT_EXTENSION_ID = "lnbmbgocenenhhhdojdielgnmeflbnfb"


def _marketplace_product_url(marketplace: str, asin: str) -> str:
    return queue_state.marketplace_product_url(marketplace, asin)


def _latest_extension_path(extension_id: str = DEFAULT_EXTENSION_ID) -> Path | None:
    base = Path.home() / "Library/Application Support/Google/Chrome/Default/Extensions" / extension_id
    if not base.exists():
        return None
    versions = [path for path in base.iterdir() if path.is_dir()]
    return sorted(versions, key=lambda path: path.name)[-1] if versions else None


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _cached_recent(record: dict | None, *, max_age_days: int | None = None) -> bool:
    if not record:
        return False
    status = str(record.get("seller_sprite_check_status") or record.get("status") or "").strip()
    keywords = record.get("keywords")
    if status and status != "已抓取":
        return False
    if not isinstance(keywords, list) or not any(isinstance(item, dict) and str(item.get("keyword") or "").strip() for item in keywords):
        return False
    if max_age_days is None:
        return True
    data_date = _parse_date(record.get("data_date") or record.get("checked_at"))
    if data_date is None:
        return False
    return (datetime.now().date() - data_date).days <= max_age_days


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


def _should_fetch_competitors(row: dict) -> bool:
    if _parse_competitors(row):
        return True
    text = "；".join(
        str(row.get(key) or "")
        for key in [
            "priority",
            "trigger_reason",
            "frontend_auto_conclusion",
            "frontend_auto_conclusion_label",
            "frontend_search_findings",
            "suspected_issue",
            "product_level_conclusion",
            "competitor_keyword_pressure",
        ]
    )
    competitor_count = 0
    try:
        competitor_count = int(float(str(row.get("frontend_competitor_count") or "0").replace(",", "")))
    except ValueError:
        competitor_count = 0
    return (
        str(row.get("priority") or "").strip().upper() == "P0"
        or "FRONTEND_WEAK" in text
        or "明确前台劣势" in text
        or "广告" in text
        or "竞品" in text
        or competitor_count >= 2
    )


def _competitor_rows(
    rows: list[dict],
    *,
    competitor_limit_per_product: int = 3,
    seller_records: dict[tuple[str, str], dict] | None = None,
    competitor_discovery_records: dict[tuple[str, str, str], dict] | None = None,
) -> list[dict]:
    seller_records = seller_records if seller_records is not None else load_sellersprite_records(SELLERSPRITE_CACHE_PATH)
    competitor_discovery_records = (
        competitor_discovery_records
        if competitor_discovery_records is not None
        else load_competitor_discovery_records(SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH)
    )
    competitors: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not _should_fetch_competitors(row):
            continue
        marketplace = str(row.get("marketplace") or "").strip().upper()
        if not marketplace:
            continue
        parent_asin = str(row.get("asin") or "").strip().upper()
        own_record = seller_records.get((marketplace, parent_asin), {})
        pool = build_sellersprite_competitor_pool(
            row,
            own_record,
            seller_records,
            limit=competitor_limit_per_product,
            competitor_discovery_records=competitor_discovery_records,
        )
        for comp in pool.get("competitor_pool_items") or []:
            asin = str(comp.get("asin") or "").strip().upper()
            if not asin or asin == parent_asin:
                continue
            key = (marketplace, asin)
            if key in seen:
                continue
            seen.add(key)
            competitors.append(
                {
                    "marketplace": marketplace,
                    "sku": row.get("sku") or "",
                    "asin": asin,
                    "product_name": comp.get("title") or f"竞品 {asin}",
                    "product_url": _marketplace_product_url(marketplace, asin),
                    "source_role": "competitor",
                    "priority": row.get("priority") or "",
                    "parent_priority": row.get("priority") or "",
                    "parent_ad_spend": row.get("ad_spend") or row.get("spend") or "",
                    "parent_ad_action": row.get("suggested_action") or row.get("copy_action_line") or "",
                    "competitor_discovery_source": comp.get("source") or "",
                    "competitor_pool_confidence": comp.get("confidence") or "",
                    "competitor_source_keyword": comp.get("source_keyword") or "",
                    "parent_marketplace": marketplace,
                    "parent_sku": row.get("sku") or "",
                    "parent_asin": parent_asin,
                    "parent_product_name": row.get("product_name") or "",
                }
            )
    return competitors


SELLERSPRITE_COLLECT_JS = r"""
async ({targetCount, stepPx}) => {
  const norm = s => (s || '').replace(/\u00a0/g, ' ').replace(/[ \t]+/g, ' ').trim();
  const extract = () => {
    const rows = [];
    for (const tr of document.querySelectorAll('tr')) {
      const cells = Array.from(tr.querySelectorAll('td')).map(td => norm(td.innerText)).filter(Boolean);
      if (cells.length < 8 || !/^\d+$/.test(cells[0] || '')) continue;
      const keyLines = (cells[1] || '').split('\n').map(norm).filter(Boolean);
      const keyword = keyLines[0] || '';
      if (!/[a-zA-Z]/.test(keyword)) continue;
      rows.push({
        row: Number(cells[0]),
        keyword,
        translation: keyLines[1] || '',
        traffic_share: cells[2] || '',
        keyword_type: cells[3] || '',
        natural_rank: cells[5] || '',
        ad_rank: cells[6] || '',
        aba_rank: cells[7] || '',
        monthly_searches: cells[8] || '',
        spr: cells[9] || '',
        title_density: cells[10] || '',
        purchases: cells[11] || '',
        impressions_clicks: cells[12] || '',
        product_supply: cells[13] || '',
        ad_products: cells[14] || '',
        concentration: cells[15] || '',
        ppc: cells[16] || ''
      });
    }
    return rows;
  };
  let target = document.querySelector('.vxe-table--body-wrapper.body--wrapper') || document.querySelector('.vxe-table--body-wrapper');
  if (!target) {
    const scrollers = Array.from(document.querySelectorAll('*')).filter(el => {
      const cs = getComputedStyle(el);
      return el.scrollHeight > el.clientHeight + 40 && el.clientHeight > 80 && el.clientWidth > 300 && cs.display !== 'none' && cs.visibility !== 'hidden';
    });
    let best = null;
    for (const el of scrollers) {
      const original = el.scrollTop;
      el.scrollTop = 0; el.dispatchEvent(new Event('scroll', {bubbles:true})); await new Promise(r => setTimeout(r, 80));
      const a = extract().map(r => `${r.row}:${r.keyword}`).join('|');
      el.scrollTop = Math.floor(el.scrollHeight * 0.7); el.dispatchEvent(new Event('scroll', {bubbles:true})); await new Promise(r => setTimeout(r, 120));
      const b = extract().map(r => `${r.row}:${r.keyword}`).join('|');
      el.scrollTop = original;
      if (a !== b && (!best || (el.scrollHeight - el.clientHeight) > (best.scrollHeight - best.clientHeight))) best = el;
    }
    target = best || document.scrollingElement;
  }
  const seen = new Map();
  const maxTop = Math.max(0, target.scrollHeight - target.clientHeight);
  for (let top = 0; top <= maxTop + stepPx && seen.size < targetCount; top += stepPx) {
    target.scrollTop = Math.min(top, maxTop);
    target.dispatchEvent(new Event('scroll', {bubbles:true}));
      await new Promise(r => setTimeout(r, 120));
    for (const row of extract()) {
      const key = `${row.row}:${row.keyword}`;
      if (!seen.has(key)) seen.set(key, row);
    }
  }
  return {
    target_class: String(target.className || ''),
    target_scroll_height: target.scrollHeight,
    rows: Array.from(seen.values()).sort((a,b) => a.row - b.row).slice(0, targetCount)
  };
}
"""


SELLERSPRITE_CLICK_REVERSE_JS = r"""
() => {
  const norm = s => (s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const candidates = Array.from(document.querySelectorAll('a,button,span,div'))
    .filter(el => norm(el.innerText || el.textContent) === '关键词反查');
  if (!candidates.length) return false;
  const visible = candidates.find(el => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  });
  const target = visible || candidates[0];
  target.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
  return true;
}
"""


SELLERSPRITE_REVERSE_READY_JS = r"""
() => {
  const text = document.body ? document.body.innerText : '';
  if (text.includes('关键词反查')) return true;
  return Array.from(document.querySelectorAll('a,button,span,div'))
    .some(el => (el.innerText || el.textContent || '').trim() === '关键词反查');
}
"""


SELLERSPRITE_TABLE_READY_JS = r"""
() => {
  const text = document.body ? document.body.innerText : '';
  if (/为您找到\s*\d+\s*条结果/.test(text)) return true;
  return Array.from(document.querySelectorAll('tr')).some(tr => {
    const first = tr.querySelector('td');
    return first && /^\d+$/.test((first.innerText || '').trim());
  });
}
"""


def _parse_reported_total(text: str) -> int | None:
    match = re.search(r"为您找到\s*(\d+)\s*条结果", text)
    return int(match.group(1)) if match else None


def fetch_reverse_asin_record(
    row: dict,
    *,
    profile: Path = DEFAULT_PROFILE,
    extension_path: Path | None = None,
    target_count: int = 20,
    timeout_ms: int = 60000,
    visible: bool = True,
) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return _failure_record(row, f"Playwright 不可用：{exc}")

    marketplace = str(row.get("marketplace") or "").strip().upper()
    asin = str(row.get("asin") or "").strip().upper()
    url = str(row.get("product_url") or "") or _marketplace_product_url(marketplace, asin)
    if not marketplace or not asin or not url:
        return _failure_record(row, "缺少 marketplace、asin 或 product_url")
    extension_path = extension_path or _latest_extension_path()
    if not extension_path or not extension_path.exists():
        return _failure_record(row, "未找到卖家精灵 Chrome 扩展")

    checked_at = datetime.now().isoformat(timespec="seconds")
    try:
        with sync_playwright() as p:
            browser_args = [
                f"--disable-extensions-except={extension_path}",
                f"--load-extension={extension_path}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            if visible:
                browser_args.extend(["--window-position=-32000,-32000", "--window-size=1500,1000"])
            context_options = {
                "headless": not visible,
                "viewport": {"width": 1500, "height": 1000},
                "locale": "zh-CN",
                "args": browser_args,
                "ignore_default_args": ["--enable-automation"],
            }
            context = p.chromium.launch_persistent_context(str(profile), **context_options)
            page = context.pages[0] if context.pages else context.new_page()
            last_error = ""
            body_text = ""
            collected: dict[str, object] = {"rows": []}
            for attempt in range(2):
                try:
                    page.goto(url, wait_until="commit", timeout=timeout_ms)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_function(SELLERSPRITE_REVERSE_READY_JS, timeout=35000, polling=500)
                    clicked = page.evaluate(SELLERSPRITE_CLICK_REVERSE_JS)
                    if not clicked:
                        last_error = "未找到卖家精灵关键词反查入口"
                        continue
                    try:
                        page.wait_for_function(
                            SELLERSPRITE_TABLE_READY_JS,
                            timeout=15000,
                            polling=500,
                        )
                    except Exception:
                        page.wait_for_timeout(2000)
                    body_text = page.locator("body").inner_text(timeout=10000)
                    collected = page.evaluate(SELLERSPRITE_COLLECT_JS, {"targetCount": target_count, "stepPx": 220})
                    if collected.get("rows"):
                        break
                    last_error = "卖家精灵反查未抓到关键词行"
                    page.wait_for_timeout(1200)
                except Exception as exc:
                    last_error = str(exc)
                    if attempt == 0:
                        page.wait_for_timeout(2500)
                        continue
                    raise
            context.close()
    except Exception as exc:
        return _failure_record(row, str(exc), checked_at=checked_at)

    keywords = collected.get("rows") or []
    return {
        "marketplace": marketplace,
        "sku": row.get("sku") or "",
        "asin": asin,
        "product_name": row.get("product_name") or "",
        "source_role": row.get("source_role") or "own",
        "competitor_discovery_source": row.get("competitor_discovery_source") or "",
        "competitor_pool_confidence": row.get("competitor_pool_confidence") or "",
        "competitor_source_keyword": row.get("competitor_source_keyword") or "",
        "parent_marketplace": row.get("parent_marketplace") or "",
        "parent_sku": row.get("parent_sku") or "",
        "parent_asin": row.get("parent_asin") or "",
        "parent_product_name": row.get("parent_product_name") or "",
        "seller_sprite_check_status": "已抓取" if keywords else "抓取失败",
        "data_date": checked_at.split("T", 1)[0],
        "checked_at": checked_at,
        "source": "sellersprite_reverse_asin",
        "reported_total": _parse_reported_total(body_text),
        "captured_count": len(keywords),
        "target_class": collected.get("target_class") or "",
        "target_scroll_height": collected.get("target_scroll_height") or "",
        "keywords": keywords,
        "last_error": "" if keywords else last_error or "卖家精灵反查未抓到关键词行",
    }


def _failure_record(row: dict, error: str, *, checked_at: str | None = None) -> dict:
    checked_at = checked_at or datetime.now().isoformat(timespec="seconds")
    return {
        "marketplace": str(row.get("marketplace") or "").strip().upper(),
        "sku": row.get("sku") or "",
        "asin": str(row.get("asin") or "").strip().upper(),
        "product_name": row.get("product_name") or "",
        "source_role": row.get("source_role") or "own",
        "competitor_discovery_source": row.get("competitor_discovery_source") or "",
        "competitor_pool_confidence": row.get("competitor_pool_confidence") or "",
        "competitor_source_keyword": row.get("competitor_source_keyword") or "",
        "parent_marketplace": row.get("parent_marketplace") or "",
        "parent_sku": row.get("parent_sku") or "",
        "parent_asin": row.get("parent_asin") or "",
        "parent_product_name": row.get("parent_product_name") or "",
        "seller_sprite_check_status": "抓取失败",
        "data_date": checked_at.split("T", 1)[0],
        "checked_at": checked_at,
        "source": "sellersprite_reverse_asin",
        "reported_total": "",
        "captured_count": 0,
        "keywords": [],
        "last_error": _norm(error)[:240],
    }


def rows_from_latest_analysis(
    *,
    marketplace: str = "",
    sku: str = "",
    asin: str = "",
    priority: str = "",
    include_competitors: bool = False,
    competitor_limit_per_product: int = 2,
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
    if include_competitors:
        discovery_records = load_competitor_discovery_records(SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH)
        rows = [
            *rows,
            *_competitor_rows(
                rows,
                competitor_limit_per_product=competitor_limit_per_product,
                competitor_discovery_records=discovery_records,
            ),
        ]
    return rows


def fetch_for_rows(
    rows: list[dict],
    *,
    profile: Path = DEFAULT_PROFILE,
    extension_path: Path | None = None,
    target_count: int = 20,
    limit: int | None = None,
    visible: bool = True,
    skip_cached: bool = True,
    competitor_cache_days: int = 7,
) -> list[dict]:
    selected = rows[:limit] if limit is not None else rows
    if skip_cached:
        existing = load_sellersprite_records(SELLERSPRITE_CACHE_PATH)
        before = len(selected)
        needs_fetch: list[dict] = []
        cached_records: list[dict] = []
        for row in selected:
            key = (
                str(row.get("marketplace") or "").strip().upper(),
                str(row.get("asin") or "").strip().upper(),
            )
            record = existing.get(key)
            max_age_days = sellersprite_cache_max_age_days_for_row(row, competitor_cache_days=competitor_cache_days)
            if _cached_recent(record, max_age_days=max_age_days):
                cached_record = dict(record or {})
                for field in [
                    "marketplace",
                    "sku",
                    "asin",
                    "source_role",
                    "parent_marketplace",
                    "parent_sku",
                    "parent_asin",
                    "parent_product_name",
                    "competitor_discovery_source",
                    "competitor_pool_confidence",
                    "competitor_source_keyword",
                ]:
                    value = row.get(field)
                    if value not in (None, ""):
                        cached_record[field] = value
                cached_records.append(cached_record)
            else:
                needs_fetch.append(row)
        selected = needs_fetch
        skipped = before - len(selected)
        if skipped:
            print(f"[sellersprite] skipped cached rows: {skipped}", flush=True)
            upsert_sellersprite_history(cached_records, snapshot_status="沿用缓存")
    records: list[dict] = []
    for index, row in enumerate(selected, start=1):
        print(
            f"[sellersprite] {index}/{len(selected)} {row.get('marketplace')} {row.get('asin')} 开始反查",
            flush=True,
        )
        record = fetch_reverse_asin_record(
            row,
            profile=profile,
            extension_path=extension_path,
            target_count=target_count,
            visible=visible,
        )
        print(
            f"[sellersprite] {record.get('marketplace')} {record.get('asin')} {record.get('seller_sprite_check_status')} "
            f"captured={record.get('captured_count')} total={record.get('reported_total')} error={record.get('last_error') or ''}",
            flush=True,
        )
        records.append(record)
        time.sleep(0.2)
    merge_sellersprite_records(records, SELLERSPRITE_CACHE_PATH)
    upsert_sellersprite_history(records)
    return records


def _competitor_pool_snapshot_records(rows: list[dict]) -> list[dict]:
    today = date.today().isoformat()
    snapshots: list[dict] = []
    for row in rows:
        if str(row.get("source_role") or "") != "competitor":
            continue
        snapshots.append(
            {
                **row,
                "seller_sprite_check_status": "竞品池快照",
                "data_date": today,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "source": "sellersprite_competitor_pool_snapshot",
                "keywords": [],
            }
        )
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch SellerSprite reverse-ASIN keyword rows for frontend queue products.")
    parser.add_argument("--marketplace", default="")
    parser.add_argument("--sku", default="")
    parser.add_argument("--asin", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--target-count", type=int, default=20)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--extension-path", default="")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--force", action="store_true", help="重新抓取已有缓存的 ASIN。默认跳过已有缓存，避免重复访问。")
    parser.add_argument("--include-competitors", action="store_true", help="同时抓取需要判断产品的 Top 非广告竞品。")
    parser.add_argument("--competitor-limit-per-product", type=int, default=2)
    parser.add_argument("--competitor-cache-days", type=int, default=7)
    parser.add_argument("--skip-competitor-discovery", action="store_true", help="调试用：跳过卖家精灵直达竞品发现，只用现有缓存或旧 seed。")
    parser.add_argument("--skip-amazon-search-seed", action="store_true", help="调试用：跳过 Amazon 核心词搜索候选补种。")
    args = parser.parse_args()
    if not LATEST_ANALYSIS.exists():
        raise SystemExit(f"missing {LATEST_ANALYSIS}; run main.py --marketplace ALL first")
    rows = rows_from_latest_analysis(
        marketplace=args.marketplace,
        sku=args.sku,
        asin=args.asin,
        priority=args.priority,
        include_competitors=False,
        competitor_limit_per_product=args.competitor_limit_per_product,
    )
    extension_path = Path(args.extension_path).expanduser() if args.extension_path else None
    records = fetch_for_rows(
        rows,
        profile=Path(args.profile).expanduser(),
        extension_path=extension_path,
        target_count=args.target_count,
        limit=args.limit,
        visible=not args.headless,
        skip_cached=not args.force,
        competitor_cache_days=args.competitor_cache_days,
    )
    competitor_rows: list[dict] = []
    if args.include_competitors:
        base_rows_for_competitors = rows[: args.limit] if args.limit is not None else rows
        if not args.skip_competitor_discovery:
            competitor_discovery_fetch.fetch_for_rows(
                base_rows_for_competitors,
                profile=Path(args.profile).expanduser(),
                limit_per_product=args.competitor_limit_per_product,
                row_limit=None,
                visible=not args.headless,
                skip_cached=not args.force,
                cache_days=args.competitor_cache_days,
            )
        if not args.skip_amazon_search_seed:
            amazon_seed_fetch.fetch_for_rows(
                base_rows_for_competitors,
                profile=amazon_seed_fetch.DEFAULT_PROFILE,
                limit_per_product=args.competitor_limit_per_product,
                keywords_per_product=1,
                headless=args.headless,
                only_missing_pool=True,
            )
        cached_for_pool = load_sellersprite_records(SELLERSPRITE_CACHE_PATH)
        cached_discovery = load_competitor_discovery_records(
            SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH,
            max_age_days=args.competitor_cache_days,
        )
        competitor_rows = _competitor_rows(
            base_rows_for_competitors,
            competitor_limit_per_product=args.competitor_limit_per_product,
            seller_records=cached_for_pool,
            competitor_discovery_records=cached_discovery,
        )
        upsert_sellersprite_history(_competitor_pool_snapshot_records(competitor_rows), snapshot_status="竞品池快照")
        records.extend(
            fetch_for_rows(
                competitor_rows,
                profile=Path(args.profile).expanduser(),
                extension_path=extension_path,
                target_count=args.target_count,
                limit=None,
                visible=not args.headless,
                skip_cached=not args.force,
                competitor_cache_days=args.competitor_cache_days,
            )
        )
    success = sum(1 for record in records if record.get("keywords"))
    cached_after = load_sellersprite_records(SELLERSPRITE_CACHE_PATH)
    all_rows = [*rows, *competitor_rows]
    cached_cover = sum(
        1
        for row in all_rows
        if (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("asin") or "").strip().upper(),
        )
        in cached_after
    )
    print(
        f"[sellersprite] wrote {SELLERSPRITE_CACHE_PATH}; success={success}/{len(records)} cached_cover={cached_cover}/{len(all_rows)}",
        flush=True,
    )
    return 0 if success or not records or cached_cover else 1


if __name__ == "__main__":
    raise SystemExit(main())
