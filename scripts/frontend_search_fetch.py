from __future__ import annotations

import contextlib
import importlib.util
import re
import time
from typing import Callable


SEARCH_DOM_EVAL_JS = """({ ownAsin, limit }) => {
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const firstText = (root, selectors) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const text = clean(node && (node.innerText || node.getAttribute('aria-label') || node.textContent));
      if (text) return text;
    }
    return '';
  };
  const cards = Array.from(document.querySelectorAll('[data-component-type="s-search-result"][data-asin]'));
  const competitors = [];
  const seen = new Set();
  let ownPosition = '';
  let position = 0;
  let cardCount = 0;
  for (const card of cards) {
    const asin = clean(card.getAttribute('data-asin')).toUpperCase();
    if (!asin || seen.has(asin)) continue;
    seen.add(asin);
    position += 1;
    cardCount += 1;
    const title = firstText(card, [
      'h2 span',
      '[data-cy="title-recipe"] span',
      '.a-size-base-plus',
      '.a-size-medium',
      '[aria-label]'
    ]);
    const price = firstText(card, ['.a-price .a-offscreen', '.a-offscreen']);
    const rating = firstText(card, ['.a-icon-alt']);
    const reviews = firstText(card, [
      'a[href*="customerReviews"] span',
      'span[aria-label*="ratings"]',
      'span[aria-label*="rating"]',
      'span[aria-label*="Bewertungen"]',
      'span[aria-label*="Rezensionen"]'
    ]);
    if (asin === ownAsin) {
      ownPosition = String(position);
      continue;
    }
    if (!title && !price) continue;
    const sponsored = /sponsored|gesponsert/i.test(clean(card.innerText)) ? '是' : '否';
    if (sponsored === '是') continue;
    competitors.push({
      asin,
      title: title.slice(0, 100),
      price,
      rating,
      reviews,
      sponsored,
      position: String(position)
    });
    if (competitors.length >= limit) break;
  }
  return { own_search_position: ownPosition, competitors, search_result_count: cardCount };
}"""

SEARCH_STATUS_KEYS = (
    "frontend_search_status",
    "frontend_search_findings",
    "frontend_competitor_count",
    "frontend_competitors",
    "own_search_position",
    "frontend_search_result_count",
    "frontend_search_partial_evidence",
    "frontend_search_method",
    "frontend_search_url",
    "frontend_search_keyword",
)


def search_status_strength(value: object) -> int:
    status = str(value or "").strip()
    if status == "已自动检查":
        return 4
    if status == "已读取部分结果":
        return 3
    if status == "按广告信号跳过":
        return 2
    if status == "待前台检查":
        return 1
    return 0


def parse_amazon_search_results(
    html: str,
    *,
    own_asin: str = "",
    limit: int = 3,
    marketplace: str = "",
    extract_first: Callable[[list[str], str], str],
    known_price_pattern: str,
    price_currency_warning: Callable[[str, str], str],
    shorten: Callable[[str, int], str],
) -> dict[str, object]:
    own_asin = str(own_asin or "").strip().upper()
    matches = list(re.finditer(r"data-asin=[\"']([A-Z0-9]{10})[\"']", html, flags=re.I))
    competitors: list[dict[str, str]] = []
    seen: set[str] = set()
    own_position = ""
    result_position = 0
    for index, match in enumerate(matches):
        asin = match.group(1).upper()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(html), match.start() + 18000)
        block = html[match.start() : end]
        if not re.search(r"s-result-item|data-component-type", block, flags=re.I):
            continue
        result_position += 1
        title = extract_first(
            [
                r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>',
                r"class=[\"'][^\"']*a-size-(?:base|medium|large)[^\"']*[\"'][^>]*>(.*?)</span>",
                r"aria-label=[\"']([^\"']{20,220})[\"']",
            ],
            block,
        )
        if asin == own_asin:
            own_position = str(result_position)
            continue
        raw_price = extract_first(
            [
                rf"class=[\"'][^\"']*a-offscreen[^\"']*[\"'][^>]*>\s*({known_price_pattern})</span>",
                r"class=[\"'][^\"']*a-price-whole[^\"']*[\"'][^>]*>(.*?)</span>",
            ],
            block,
        )
        price_warning = price_currency_warning(raw_price, marketplace)
        price = "" if price_warning else raw_price
        if not title and not price:
            continue
        sponsored = "是" if re.search(r"sponsored|gesponsert", block, flags=re.I) else "否"
        if sponsored == "是":
            continue
        competitors.append(
            {
                "asin": asin,
                "title": shorten(title, 100),
                "price": price,
                "price_currency_warning": price_warning,
                "rating": extract_first(
                    [
                        r"class=[\"'][^\"']*a-icon-alt[^\"']*[\"'][^>]*>([^<]*(?:out of 5|von 5|sur 5)[^<]*)</span>",
                    ],
                    block,
                ),
                "reviews": extract_first(
                    [
                        r"aria-label=[\"']([0-9,.]+\s+(?:ratings?|reviews?|Bewertungen?|Rezensionen?))[\"']",
                        r'([0-9,.]+\\s+(?:ratings?|reviews?|Bewertungen?|Rezensionen?))',
                    ],
                    block,
                ),
                "sponsored": sponsored,
                "position": str(result_position),
            }
        )
        if len(competitors) >= limit:
            break
    return {"own_search_position": own_position, "competitors": competitors, "search_result_count": result_position}


def competitor_summary(competitors: list[dict[str, str]], own_position: str = "") -> str:
    parts: list[str] = []
    if own_position:
        parts.append(f"自己商品搜索位次约第 {own_position} 位")
    for index, item in enumerate(competitors[:3], start=1):
        details = [item.get("asin", "")]
        if item.get("price"):
            details.append(item["price"])
        if item.get("rating"):
            details.append(item["rating"])
        if item.get("reviews"):
            details.append(item["reviews"])
        parts.append(f"竞品{index}：" + "，".join(detail for detail in details if detail))
    return "；".join(parts) if parts else "搜索页未稳定解析到前三竞品。"


def search_partial_evidence_summary(
    payload: dict[str, object],
    keyword: str,
    *,
    parse_number_text: Callable[..., float | None],
) -> str:
    count = parse_number_text(payload.get("search_result_count"), decimal_allowed=False)
    own_position = str(payload.get("own_search_position") or "").strip()
    parts: list[str] = []
    if count is not None and count > 0:
        parts.append(f"已识别搜索结果卡 {int(count)} 个")
    if own_position:
        parts.append(f"自己商品搜索位次约第 {own_position} 位")
    if not parts:
        return ""
    return f"核心词“{keyword}”搜索页只读取到部分证据：" + "；".join(parts)


def sanitize_search_payload_prices(
    payload: dict[str, object],
    marketplace: str,
    *,
    price_currency_warning: Callable[[str, str], str],
) -> dict[str, object]:
    competitors = payload.get("competitors")
    if not isinstance(competitors, list):
        return payload
    sanitized: list[dict[str, object]] = []
    for item in competitors:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        price = str(copied.get("price") or "")
        warning = price_currency_warning(price, marketplace)
        if warning:
            copied["price"] = ""
            copied["price_currency_warning"] = warning
        sanitized.append(copied)
    payload["competitors"] = sanitized
    return payload


def parse_amazon_search_results_playwright(
    url: str,
    timeout: int,
    *,
    marketplace: str = "",
    own_asin: str = "",
    limit: int = 3,
    attempt: int = 1,
    use_chrome: bool = False,
    browser_session=None,
    user_agent: str,
    load_locations: Callable[[], dict[str, dict[str, str]]],
    launch_chromium: Callable[..., object],
    install_stealth_init: Callable[[object], None],
    apply_delivery_location: Callable[[object, str, str], str],
    sanitize_prices: Callable[[dict[str, object], str], dict[str, object]],
) -> tuple[dict[str, object], str, str]:
    if not importlib.util.find_spec("playwright"):
        return {}, "Playwright 未安装", "playwright"
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency guard
        return {}, f"Playwright 不可用：{exc}", "playwright"

    browser = None
    try:
        locations = load_locations()
        location = locations.get(str(marketplace or "").upper(), {})
        if browser_session is not None:
            context = browser_session.get_context(marketplace)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=max(timeout, 1) * 1000)
                with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                    page.wait_for_selector('[data-component-type="s-search-result"][data-asin]', timeout=7000 + max(attempt - 1, 0) * 2500)
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(900 + max(attempt - 1, 0) * 500)
                with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                    page.wait_for_load_state("networkidle", timeout=3000)
                payload = page.evaluate(
                    SEARCH_DOM_EVAL_JS,
                    {"ownAsin": str(own_asin or "").strip().upper(), "limit": limit},
                )
                if isinstance(payload, dict):
                    payload["search_location_note"] = browser_session.get_location_note(marketplace)
                    return sanitize_prices(payload, marketplace), "", "chrome-dom" if use_chrome else "playwright-dom"
                return {}, "", "chrome-dom" if use_chrome else "playwright-dom"
            finally:
                with contextlib.suppress(Exception):
                    page.close()
        with sync_playwright() as p:
            browser = launch_chromium(p, use_chrome)
            context = browser.new_context(
                user_agent=user_agent,
                locale=location.get("locale") or "en-GB",
                timezone_id=location.get("timezone") or "Europe/London",
                viewport={"width": 1365, "height": 1800},
            )
            install_stealth_init(context)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=max(timeout, 1) * 1000)
            location_note = apply_delivery_location(page, str(marketplace or "").upper(), location.get("postcode", ""))
            with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                page.wait_for_selector('[data-component-type="s-search-result"][data-asin]', timeout=7000 + max(attempt - 1, 0) * 2500)
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(900 + max(attempt - 1, 0) * 500)
            with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                page.wait_for_load_state("networkidle", timeout=3000)
            payload = page.evaluate(SEARCH_DOM_EVAL_JS, {"ownAsin": str(own_asin or "").strip().upper(), "limit": limit})
            context.close()
            browser.close()
            if isinstance(payload, dict):
                payload["search_location_note"] = location_note
                return sanitize_prices(payload, marketplace), "", "chrome-dom" if use_chrome else "playwright-dom"
            return {}, "", "chrome-dom" if use_chrome else "playwright-dom"
    except Exception as exc:
        method_name = "Chrome" if use_chrome else "Playwright"
        error = f"{method_name} 搜索页读取失败：{exc}"
    if browser:
        with contextlib.suppress(Exception):
            browser.close()
    return {}, error, "chrome-dom" if use_chrome else "playwright-dom"


def parse_search_results(
    url: str,
    timeout: int,
    method: str,
    marketplace: str,
    own_asin: str,
    attempt: int,
    *,
    browser_session=None,
    parse_playwright: Callable[..., tuple[dict[str, object], str, str]],
    partial_summary: Callable[[dict[str, object], str], str],
    fetch_html: Callable[..., tuple[str, str, str, str]],
    parse_html: Callable[..., dict[str, object]],
) -> tuple[dict[str, object], str, str]:
    method = (method or "auto").lower()
    dom_partial: dict[str, object] = {}
    dom_error = ""
    dom_parser = ""
    if method in {"chrome", "chrome-persistent"}:
        parsed, error, parser = parse_playwright(
            url,
            timeout,
            marketplace=marketplace,
            own_asin=own_asin,
            attempt=attempt,
            use_chrome=True,
            browser_session=browser_session,
        )
        if parsed.get("competitors") or method in {"chrome", "chrome-persistent"}:
            parser_name = "chrome-persistent-dom" if method == "chrome-persistent" and parser == "chrome-dom" else parser
            return parsed, error, parser_name
        if partial_summary(parsed, ""):
            dom_partial = dict(parsed)
            dom_error = error
            dom_parser = parser
    if method in {"auto", "playwright"}:
        parsed, error, parser = parse_playwright(
            url,
            timeout,
            marketplace=marketplace,
            own_asin=own_asin,
            attempt=attempt,
            browser_session=browser_session,
        )
        if parsed.get("competitors") or method == "playwright":
            return parsed, error, parser
        if partial_summary(parsed, ""):
            dom_partial = dict(parsed)
            dom_error = error
            dom_parser = parser
    search_html, search_error, parser, _ = fetch_html(
        url,
        timeout,
        method="urllib" if method == "auto" else method,
        marketplace=marketplace,
        attempt=attempt,
        browser_session=browser_session,
    )
    parsed_search = parse_html(search_html, own_asin=own_asin, marketplace=marketplace) if search_html else {}
    if dom_partial:
        merged = dict(dom_partial)
        if isinstance(parsed_search, dict):
            for key, value in parsed_search.items():
                if key == "competitors":
                    if value:
                        merged[key] = value
                elif value not in ("", None, [], {}):
                    merged[key] = value
        return merged, search_error or dom_error, parser or dom_parser
    return parsed_search, search_error, parser


def parse_search_results_chrome_cdp(
    url: str,
    timeout: int,
    marketplace: str,
    own_asin: str,
    endpoint: str,
    *,
    limit: int = 3,
    cdp_available: Callable[[str], bool] | None,
    sanitize_prices: Callable[[dict[str, object], str], dict[str, object]],
) -> tuple[dict[str, object], str, str]:
    if cdp_available is None:
        return {}, "Chrome CDP 探测不可用：缺少脚本或依赖。", "chrome-cdp-dom"
    if not cdp_available(endpoint):
        return {}, f"Chrome CDP endpoint is not available: {endpoint}", "chrome-cdp-dom"
    if not importlib.util.find_spec("playwright"):
        return {}, "Playwright 未安装", "chrome-cdp-dom"
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency guard
        return {}, f"Playwright 不可用：{exc}", "chrome-cdp-dom"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            try:
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=max(timeout, 1) * 1000)
                    with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                        page.wait_for_selector(
                            '[data-component-type="s-search-result"][data-asin]',
                            timeout=4000,
                        )
                    page.mouse.wheel(0, 1400)
                    page.wait_for_timeout(500)
                    with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                        page.wait_for_load_state("networkidle", timeout=1000)
                    payload = page.evaluate(
                        SEARCH_DOM_EVAL_JS,
                        {"ownAsin": str(own_asin or "").strip().upper(), "limit": limit},
                    )
                    if isinstance(payload, dict):
                        return sanitize_prices(payload, marketplace), "", "chrome-cdp-dom"
                    return {}, "", "chrome-cdp-dom"
                finally:
                    with contextlib.suppress(Exception):
                        page.close()
            finally:
                browser.close()
    except Exception as exc:
        return {}, f"Chrome CDP 搜索页读取失败：{exc}", "chrome-cdp-dom"


def search_payload_from_parsed(
    row: dict,
    *,
    search_keyword: str,
    search_url: str,
    parsed_search: dict[str, object],
    search_error: str,
    search_parser: str,
    parse_number_text: Callable[..., float | None],
    competitor_summary_func: Callable[[list[dict[str, str]], str], str],
    partial_summary: Callable[[dict[str, object], str], str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "frontend_search_keyword": search_keyword,
        "frontend_search_url": search_url,
        "frontend_search_status": "待前台检查" if search_url else "未配置核心词",
        "frontend_search_findings": "未配置核心词搜索页。",
        "frontend_competitor_count": 0,
        "frontend_competitors": [],
        "own_search_position": "",
    }
    competitors = parsed_search.get("competitors", []) if isinstance(parsed_search, dict) else []
    result_count = (
        int(parse_number_text(parsed_search.get("search_result_count"), decimal_allowed=False) or 0)
        if isinstance(parsed_search, dict)
        else 0
    )
    own_position = str(parsed_search.get("own_search_position") or "") if isinstance(parsed_search, dict) else ""
    if competitors:
        payload.update(
            {
                "frontend_search_status": "已自动检查",
                "frontend_search_findings": f"核心词“{search_keyword}”搜索页读取成功；{competitor_summary_func(competitors, own_position)}",
                "frontend_competitor_count": len(competitors),
                "frontend_competitors": competitors,
                "own_search_position": own_position,
                "frontend_search_result_count": result_count,
                "frontend_search_partial_evidence": False,
                "frontend_search_method": search_parser,
            }
        )
        return payload
    partial = partial_summary(parsed_search, search_keyword) if isinstance(parsed_search, dict) else ""
    if partial:
        payload.update(
            {
                "frontend_search_status": "已读取部分结果",
                "frontend_search_findings": partial + "；未稳定解析前三竞品价格/评分，不能用于强诊断。",
                "frontend_competitor_count": 0,
                "frontend_competitors": [],
                "own_search_position": own_position,
                "frontend_search_result_count": result_count,
                "frontend_search_partial_evidence": True,
                "frontend_search_method": search_parser,
            }
        )
        return payload
    if search_url:
        payload["frontend_search_findings"] = (
            f"核心词“{search_keyword}”搜索页本次未稳定读取前三竞品。"
            if search_error
            else f"核心词“{search_keyword}”搜索页未稳定解析前三竞品。"
        )
        if search_parser:
            payload["frontend_search_method"] = search_parser
    return payload
