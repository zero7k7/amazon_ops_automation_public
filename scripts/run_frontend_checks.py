from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Callable, Iterable

try:
    from scripts import frontend_check_queue as queue_state
    from scripts import frontend_product_fetch as product_fetch
    from scripts import frontend_check_results as result_state
    from scripts import frontend_search_fetch as search_fetch
    from scripts.validate_frontend_stability import build_stability_report
    from scripts.probe_frontend_chrome_cdp import _cdp_available as _chrome_cdp_available
    from scripts.probe_frontend_chrome_cdp import run_chrome_cdp_probe
except ModuleNotFoundError:  # pragma: no cover - used when executed as scripts/run_frontend_checks.py
    build_stability_report = None
    _chrome_cdp_available = None
    run_chrome_cdp_probe = None
    import frontend_check_queue as queue_state
    import frontend_product_fetch as product_fetch
    import frontend_check_results as result_state
    import frontend_search_fetch as search_fetch
    with contextlib.suppress(Exception):
        from validate_frontend_stability import build_stability_report
        from probe_frontend_chrome_cdp import _cdp_available as _chrome_cdp_available
        from probe_frontend_chrome_cdp import run_chrome_cdp_probe


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
LATEST_ANALYSIS = OUTPUT_DIR / "latest_analysis.json"
RESULTS_PATH = OUTPUT_DIR / "frontend_check_results.json"
LOCATION_CONFIG = ROOT / "config" / "frontend_locations.json"
PERSISTENT_CHROME_PROFILE_ROOT = OUTPUT_DIR / "chrome_frontend_profile_v2"
DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"

_record_key = result_state.record_key
_record_data_date = result_state.record_data_date
_today_iso = result_state.today_iso
_print_progress = result_state.print_progress


class StrictLivePassError(RuntimeError):
    def __init__(self, message: str, rows: list[dict]) -> None:
        super().__init__(message)
        self.rows = rows


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_LOCATIONS = {
    "UK": {"postcode": "SW1A 1AA", "locale": "en-GB", "timezone": "Europe/London"},
    "US": {"postcode": "10001", "locale": "en-US", "timezone": "America/New_York"},
    "DE": {"postcode": "10115", "locale": "de-DE", "timezone": "Europe/Berlin"},
}
EXPECTED_PRICE_SYMBOL = {"UK": "£", "US": "$", "DE": "€"}
EXPECTED_PRICE_CODE = {"UK": "GBP", "US": "USD", "DE": "EUR"}
BLOCKED_PRICE_CURRENCY_MARKERS = (
    "TWD",
    "NT$",
    "NTD",
    "HK$",
    "HKD",
    "RMB",
    "CNY",
    "CN¥",
    "￥",
    "¥",
    "CAD",
    "CA$",
    "AUD",
    "A$",
    "JPY",
    "JP¥",
    "円",
    "SGD",
    "S$",
)
BLOCKED_PRICE_PATTERN = r"(?:TWD|NT\$|NTD|HK\$|HKD|RMB|CNY|CN¥|￥|¥|CAD|CA\$|AUD|A\$|JPY|JP¥|円|SGD|S\$)\s*\$?\s*[0-9][^<]{0,30}"
PRICE_CODE_PATTERN = r"(?:USD|GBP|EUR|CAD|AUD|JPY|SGD)\s*[0-9][^<]{0,30}"
KNOWN_PRICE_PATTERN = rf"(?:{BLOCKED_PRICE_PATTERN}|{PRICE_CODE_PATTERN}|(?:TWD|NT\$|NTD|HK\$|HKD|RMB|CNY|CN¥|￥|¥|CAD|CA\$|AUD|A\$|JPY|JP¥|円|SGD|S\$)?\s*[£$€]\s*[0-9][^<]{{0,30}})"
WRONG_LOCATION_MARKERS = {
    "UK": ("united states", "canada", "australia", "japan", "germany", "deutschland"),
    "US": ("united kingdom", "great britain", "germany", "deutschland", "canada", "australia", "japan"),
    "DE": ("united states", "united kingdom", "great britain", "canada", "australia", "japan"),
}
MARKETPLACE_LOCATION_MARKERS = {
    "UK": ("united kingdom", "uk", "ireland", "aberdeen", "london", "manchester", "birmingham", "glasgow", "edinburgh"),
    "US": ("united states", "new york", "california", "texas", "florida", "washington"),
    "DE": ("germany", "deutschland", "berlin", "hamburg", "munich", "münchen", "frankfurt"),
}


def _load_locations() -> dict[str, dict[str, str]]:
    locations = {key: dict(value) for key, value in DEFAULT_LOCATIONS.items()}
    if not LOCATION_CONFIG.exists():
        return locations
    with contextlib.suppress(Exception):
        configured = json.loads(LOCATION_CONFIG.read_text(encoding="utf-8"))
        for key, value in configured.items():
            if isinstance(value, dict):
                locations[str(key).upper()] = {**locations.get(str(key).upper(), {}), **{str(k): str(v) for k, v in value.items()}}
    return locations


def _strip_html(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _extract_first(patterns: Iterable[str], html: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            return _strip_html(match.group(1))
    return ""


def _shorten(value: str, limit: int = 140) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _contains_blocked_currency_marker(value: object) -> bool:
    upper = str(value or "").upper()
    return any(marker in upper for marker in BLOCKED_PRICE_CURRENCY_MARKERS)


def _expected_location_token(marketplace: str) -> str:
    marketplace = str(marketplace or "").strip().upper()
    location = _load_locations().get(marketplace, {})
    return str(location.get("postcode") or "").strip()


def _clean_location_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_location_text_from_html(html: str) -> str:
    candidates = [
        _extract_first([r'id=["\']glow-ingress-line2["\'][^>]*>(.*?)</span>'], html),
        _extract_first([r'id=["\']contextualIngressPtLabel_deliveryShortLine["\'][^>]*>(.*?)</div>'], html),
        _extract_first([r'aria-label=["\']Deliver to ([^"\']{2,80})["\']'], html),
    ]
    for candidate in candidates:
        cleaned = _clean_location_text(candidate)
        if cleaned:
            return cleaned
    return ""


def _location_scope(location_note: object, marketplace: str) -> str:
    text = _clean_location_text(location_note)
    if not text:
        return "missing"
    marketplace_key = str(marketplace or "").strip().upper()
    lower = text.lower()
    if "未确认" in text or "无法确认" in text:
        return "missing"
    expected = _expected_location_token(marketplace_key)
    if expected and expected.lower() in lower:
        return "exact"
    if "已设置" in text and marketplace_key in text:
        return "exact"
    for marker in WRONG_LOCATION_MARKERS.get(marketplace_key, ()):
        if marker in lower:
            return "wrong"
    for marker in MARKETPLACE_LOCATION_MARKERS.get(marketplace_key, ()):
        if marker in lower:
            return "marketplace"
    return "unknown"


def _location_warning(location_note: object, marketplace: str) -> str:
    text = _clean_location_text(location_note)
    marketplace_key = str(marketplace or "").strip().upper()
    scope = _location_scope(text, marketplace_key)
    if scope == "exact":
        return ""
    if scope == "marketplace":
        return f"{marketplace_key} 地区非配置邮编：{text}"
    if scope == "wrong":
        return f"{marketplace_key} 地区异常：{text}"
    if "未确认" in text or "无法确认" in text:
        return f"{marketplace_key} 地区未确认"
    if scope == "missing":
        return f"{marketplace_key} 地区未确认" + (f"：{text}" if text else "")
    return f"{marketplace_key} 地区未确认：{text}"


def _location_hard_failure(location_note: object, marketplace: str) -> str:
    text = _clean_location_text(location_note)
    marketplace_key = str(marketplace or "").strip().upper()
    scope = _location_scope(text, marketplace_key)
    if scope in {"exact", "marketplace"}:
        return ""
    return _location_warning(text, marketplace_key)


def _location_verified(location_note: object, marketplace: str) -> bool:
    return _location_scope(location_note, marketplace) in {"exact", "marketplace"}


def _location_exact(location_note: object, marketplace: str) -> bool:
    return _location_scope(location_note, marketplace) == "exact"


def _merge_location_note(parsed: dict[str, str], location_note: str, marketplace: str) -> str:
    if _location_verified(location_note, marketplace):
        return _clean_location_text(location_note)
    visible = parsed.get("visible_location") or ""
    return _clean_location_text(location_note or visible)


def _apply_location_basis(parsed: dict[str, str], location_note: str, marketplace: str, *, allow_html_visible: bool = True) -> str:
    if allow_html_visible:
        effective_location_note = _merge_location_note(parsed, location_note, marketplace)
    else:
        effective_location_note = _clean_location_text(location_note)
    if effective_location_note and _location_scope(effective_location_note, marketplace) == "missing":
        if "未确认" in effective_location_note or "无法确认" in effective_location_note:
            effective_location_note = f"{str(marketplace or '').strip().upper()} 地区未确认"
    if effective_location_note:
        parsed["visible_location"] = effective_location_note
    else:
        parsed.pop("visible_location", None)
    parsed["location_warning"] = _location_warning(effective_location_note, marketplace)
    parsed["location_hard_failure"] = _location_hard_failure(effective_location_note, marketplace)
    parsed["location_scope"] = _location_scope(effective_location_note, marketplace)
    return effective_location_note


def _price_currency_warning(price: str, marketplace: str) -> str:
    text = re.sub(r"\s+", " ", str(price or "")).strip()
    if not text:
        return ""
    upper = text.upper()
    if _contains_blocked_currency_marker(upper):
        return f"价格币种异常：{text}，已忽略"
    expected_code = EXPECTED_PRICE_CODE.get(str(marketplace or "").strip().upper())
    code_match = re.search(r"\b(USD|GBP|EUR|CAD|AUD|JPY|SGD)\b|^(USD|GBP|EUR|CAD|AUD|JPY|SGD)", upper)
    actual_code = (code_match.group(1) or code_match.group(2)) if code_match else ""
    if actual_code and expected_code and actual_code != expected_code:
        return f"价格币种异常：期望 {expected_code}，实际 {text}，已忽略"
    expected = EXPECTED_PRICE_SYMBOL.get(str(marketplace or "").strip().upper())
    if expected:
        symbols = {symbol for symbol in ("£", "$", "€") if symbol in text}
        if symbols and expected not in symbols:
            return f"价格币种异常：期望 {expected}，实际 {text}，已忽略"
    return ""


def _clean_coupon_detail(value: str) -> str:
    text = _strip_html(value)
    text = unescape(text)
    text = re.sub(r"%20", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ;,")
    if not text:
        return ""
    concise = _extract_coupon_value(text)
    if concise:
        return concise
    bad_fragments = (
        "{",
        "}",
        "class=",
        "display:",
        "width:",
        "height:",
        "background",
        "Creator__",
        "_vc-",
        "%2C",
        "http",
    )
    if any(fragment.lower() in text.lower() for fragment in bad_fragments):
        match = re.search(
            r"([£$€]\s*\d+(?:[.,]\d{2})?\s+with\s+\d+\s+percent\s+savings|"
            r"Save\s+\d+%|"
            r"Apply\s+\d+%|"
            r"\d+%\s+(?:off|coupon|voucher|rabatt)|"
            r"[£$€]\s*\d+(?:[.,]\d{2})?\s+(?:off|coupon|voucher))",
            text,
            flags=re.I,
        )
        if match:
            return _extract_coupon_value(match.group(1)) or match.group(1).strip()
        return ""
    return _shorten(text, limit=90)


def _extract_coupon_value(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ;,")
    if not text:
        return ""
    if re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:%|percent)", text, flags=re.I):
        percent_value = re.match(r"(\d+(?:[.,]\d+)?)", text, flags=re.I)
        return f"{percent_value.group(1).replace(',', '.')}%" if percent_value else ""
    percent_match = re.search(
        r"(?:save|apply|coupon|voucher|rabatt|gutschein|spar|off|savings?|优惠|折扣)[^0-9]{0,40}(\d+(?:[.,]\d+)?)\s*(?:%|percent)"
        r"|(\d+(?:[.,]\d+)?)\s*(?:%|percent)[^.;,]{0,40}(?:off|coupon|voucher|rabatt|gutschein|savings?|优惠|折扣)",
        text,
        flags=re.I,
    )
    if percent_match:
        number = percent_match.group(1) or percent_match.group(2)
        return f"{number.replace(',', '.')}%"
    amount_match = re.search(r"([£$€]\s*\d+(?:[.,]\d{1,2})?)", text)
    if amount_match and re.search(r"off|coupon|voucher|rabatt|gutschein|save|apply|spar", text, flags=re.I):
        return re.sub(r"\s+", "", amount_match.group(1))
    if re.fullmatch(r"[£$€]\s*\d+(?:[.,]\d{1,2})?", text):
        return re.sub(r"\s+", "", text)
    german_amount_match = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*€", text)
    if german_amount_match and re.search(r"rabatt|gutschein|spar", text, flags=re.I):
        return f"{german_amount_match.group(1)}€"
    return ""


def parse_amazon_frontend(html: str, marketplace: str = "") -> dict[str, str]:
    title = _extract_first(
        [
            r'id=["\']productTitle["\'][^>]*>(.*?)</span>',
            r'<title[^>]*>(.*?)</title>',
        ],
        html,
    )
    price = _extract_first(
        [
            rf'class=["\'][^"\']*a-offscreen[^"\']*["\'][^>]*>\s*({KNOWN_PRICE_PATTERN})</span>',
            r'id=["\']priceblock_ourprice["\'][^>]*>(.*?)</span>',
            r'id=["\']priceblock_dealprice["\'][^>]*>(.*?)</span>',
            r'class=["\'][^"\']*a-price[^"\']*["\'][^>]*>.*?class=["\'][^"\']*a-offscreen[^"\']*["\'][^>]*>(.*?)</span>',
            r'class=["\'][^"\']*a-price-whole[^"\']*["\'][^>]*>(.*?)</span>',
        ],
        html,
    )
    price_warning = _price_currency_warning(price, marketplace)
    if price_warning:
        price = ""
    rating = _extract_first(
        [
            r'class=["\'][^"\']*a-icon-alt[^"\']*["\'][^>]*>([^<]*(?:out of 5|von 5|sur 5)[^<]*)</span>',
            r'([0-9][.,]?[0-9]?\s*(?:out of 5|von 5|sur 5)\s*stars?)',
        ],
        html,
    )
    reviews = _extract_first(
        [
            r'id=["\']acrCustomerReviewText["\'][^>]*>(.*?)</span>',
            r'([0-9,.]+\s+(?:ratings?|reviews?|Bewertungen?|Rezensionen?))',
        ],
        html,
    )
    coupon_detail = _clean_coupon_detail(
        _extract_first(
        [
            r'((?:Save|Apply|with|Coupon|Voucher)[^<]{0,70}(?:[£$€]\s*[0-9]+(?:[.,][0-9]{2})?|[0-9]+%)[^<]{0,70})',
            r'((?:Sparen|Rabatt|Gutschein)[^<]{0,70}(?:[0-9]+(?:[.,][0-9]{2})?\s*€|[0-9]+%)[^<]{0,70})',
        ],
        html,
        )
    )
    coupon = coupon_detail or ("待确认" if re.search(r"coupon|voucher|rabatt|gutschein|save\s+\d+|spar", html, flags=re.I) else "未稳定识别 Coupon")
    buy_box = (
        "识别到购买按钮"
        if re.search(r"add to basket|add to cart|buy now|in den einkaufswagen|jetzt kaufen", html, flags=re.I)
        else "未稳定识别 Buy Box/购买按钮"
    )
    delivery = _extract_first(
        [
            r'id=["\']mir-layout-DELIVERY_BLOCK[^"\']*["\'][^>]*>(.*?)</div>',
            r'(FREE delivery[^<]{0,120})',
            r'(Get it [^<]{0,120})',
            r'(Kostenlose Lieferung[^<]{0,120})',
        ],
        html,
    )
    captcha_or_block = bool(re.search(r"captcha|robot check|enter the characters|automated access", html, flags=re.I))
    visible_location = _extract_location_text_from_html(html)
    location_warning = _location_warning(visible_location, marketplace) if visible_location else ""
    location_hard_failure = _location_hard_failure(visible_location, marketplace) if visible_location else ""
    return {
        "marketplace": marketplace,
        "title": title,
        "price": price,
        "price_currency_warning": price_warning,
        "rating": rating,
        "reviews": reviews,
        "coupon": coupon,
        "coupon_detail": coupon_detail,
        "buy_box": buy_box,
        "delivery": delivery,
        "visible_location": visible_location,
        "location_warning": location_warning,
        "location_hard_failure": location_hard_failure,
        "location_scope": _location_scope(visible_location, marketplace) if visible_location else "missing",
        "captcha_or_block": "是" if captcha_or_block else "否",
    }


def _marketplace_search_url(marketplace: str, keyword: str) -> str:
    return queue_state.marketplace_search_url(marketplace, keyword)


def _marketplace_product_url(marketplace: str, asin: str) -> str:
    return queue_state.marketplace_product_url(marketplace, asin)


def parse_amazon_search_results(html: str, own_asin: str = "", limit: int = 3, marketplace: str = "") -> dict[str, object]:
    return search_fetch.parse_amazon_search_results(
        html,
        own_asin=own_asin,
        limit=limit,
        marketplace=marketplace,
        extract_first=_extract_first,
        known_price_pattern=KNOWN_PRICE_PATTERN,
        price_currency_warning=_price_currency_warning,
        shorten=_shorten,
    )


def _competitor_summary(competitors: list[dict[str, str]], own_position: str = "") -> str:
    return search_fetch.competitor_summary(competitors, own_position)


def _search_partial_evidence_summary(payload: dict[str, object], keyword: str) -> str:
    return search_fetch.search_partial_evidence_summary(
        payload,
        keyword,
        parse_number_text=_parse_number_text,
    )


def _sanitize_search_payload_prices(payload: dict[str, object], marketplace: str) -> dict[str, object]:
    return search_fetch.sanitize_search_payload_prices(
        payload,
        marketplace,
        price_currency_warning=_price_currency_warning,
    )


def _fetch_html_urllib(url: str, timeout: int) -> tuple[str, str]:
    return product_fetch.fetch_html_urllib(url, timeout, user_agent=USER_AGENT)


def _visible_delivery_location(page) -> str:
    return product_fetch.visible_delivery_location(page, clean_location_text=_clean_location_text)


def _apply_delivery_location(page, marketplace: str, postcode: str) -> str:
    return product_fetch.apply_delivery_location(
        page,
        marketplace,
        postcode,
        clean_location_text=_clean_location_text,
    )


def _launch_chromium(p, use_chrome: bool):
    return product_fetch.launch_chromium(p, use_chrome)


def _install_stealth_init(context) -> None:
    product_fetch.install_stealth_init(context)


def _launch_persistent_chromium_context(
    p,
    *,
    user_data_dir: Path,
    use_chrome: bool,
    locale: str,
    timezone_id: str,
    headless: bool = False,
):
    return product_fetch.launch_persistent_chromium_context(
        p,
        user_data_dir=user_data_dir,
        use_chrome=use_chrome,
        locale=locale,
        timezone_id=timezone_id,
        user_agent=USER_AGENT,
        headless=headless,
    )


_SEARCH_DOM_EVAL_JS = search_fetch.SEARCH_DOM_EVAL_JS
_SEARCH_STATUS_KEYS = search_fetch.SEARCH_STATUS_KEYS


def _search_status_strength(value: object) -> int:
    return search_fetch.search_status_strength(value)


class FrontendBrowserSession(product_fetch.FrontendBrowserSession):
    def __init__(
        self,
        *,
        use_chrome: bool = False,
        persistent: bool = False,
        profile_root: Path | None = None,
        headless: bool = False,
        apply_location: bool = True,
    ):
        super().__init__(
            user_agent=USER_AGENT,
            profile_root=profile_root or PERSISTENT_CHROME_PROFILE_ROOT,
            load_locations=_load_locations,
            clean_location_text=_clean_location_text,
            use_chrome=use_chrome,
            persistent=persistent,
            headless=headless,
            apply_location=apply_location,
            apply_delivery_location_func=_apply_delivery_location,
            launch_chromium_func=_launch_chromium,
        )


def _fetch_html_playwright(
    url: str,
    timeout: int,
    marketplace: str = "",
    attempt: int = 1,
    use_chrome: bool = False,
    browser_session: FrontendBrowserSession | None = None,
) -> tuple[str, str, str]:
    return product_fetch.fetch_html_playwright(
        url,
        timeout,
        marketplace=marketplace,
        attempt=attempt,
        use_chrome=use_chrome,
        browser_session=browser_session,
        user_agent=USER_AGENT,
        load_locations=_load_locations,
        clean_location_text=_clean_location_text,
        apply_delivery_location_func=_apply_delivery_location,
        launch_chromium_func=_launch_chromium,
    )


def _fetch_html(
    url: str,
    timeout: int,
    method: str = "auto",
    marketplace: str = "",
    attempt: int = 1,
    browser_session: FrontendBrowserSession | None = None,
) -> tuple[str, str, str, str]:
    return product_fetch.fetch_html(
        url,
        timeout,
        method=method,
        marketplace=marketplace,
        attempt=attempt,
        browser_session=browser_session,
        user_agent=USER_AGENT,
        load_locations=_load_locations,
        clean_location_text=_clean_location_text,
        apply_delivery_location_func=_apply_delivery_location,
        launch_chromium_func=_launch_chromium,
    )


def _parse_amazon_search_results_playwright(
    url: str,
    timeout: int,
    marketplace: str = "",
    own_asin: str = "",
    limit: int = 3,
    attempt: int = 1,
    use_chrome: bool = False,
    browser_session: FrontendBrowserSession | None = None,
) -> tuple[dict[str, object], str, str]:
    return search_fetch.parse_amazon_search_results_playwright(
        url,
        timeout,
        marketplace=marketplace,
        own_asin=own_asin,
        limit=limit,
        attempt=attempt,
        use_chrome=use_chrome,
        browser_session=browser_session,
        user_agent=USER_AGENT,
        load_locations=_load_locations,
        launch_chromium=_launch_chromium,
        install_stealth_init=_install_stealth_init,
        apply_delivery_location=_apply_delivery_location,
        sanitize_prices=_sanitize_search_payload_prices,
    )


def _parse_search_results(
    url: str,
    timeout: int,
    method: str,
    marketplace: str,
    own_asin: str,
    attempt: int,
    browser_session: FrontendBrowserSession | None = None,
) -> tuple[dict[str, object], str, str]:
    return search_fetch.parse_search_results(
        url,
        timeout,
        method,
        marketplace,
        own_asin,
        attempt,
        browser_session=browser_session,
        parse_playwright=_parse_amazon_search_results_playwright,
        partial_summary=_search_partial_evidence_summary,
        fetch_html=_fetch_html,
        parse_html=parse_amazon_search_results,
    )


def _parse_search_results_chrome_cdp(
    url: str,
    timeout: int,
    marketplace: str,
    own_asin: str,
    endpoint: str,
    limit: int = 3,
) -> tuple[dict[str, object], str, str]:
    return search_fetch.parse_search_results_chrome_cdp(
        url,
        timeout,
        marketplace,
        own_asin,
        endpoint,
        limit=limit,
        cdp_available=_chrome_cdp_available,
        sanitize_prices=_sanitize_search_payload_prices,
    )


def _search_payload_from_parsed(
    row: dict,
    *,
    search_keyword: str,
    search_url: str,
    parsed_search: dict[str, object],
    search_error: str,
    search_parser: str,
) -> dict[str, object]:
    return search_fetch.search_payload_from_parsed(
        row,
        search_keyword=search_keyword,
        search_url=search_url,
        parsed_search=parsed_search,
        search_error=search_error,
        search_parser=search_parser,
        parse_number_text=_parse_number_text,
        competitor_summary_func=_competitor_summary,
        partial_summary=_search_partial_evidence_summary,
    )


def _queue_rows(payload: dict) -> list[dict]:
    return queue_state.queue_rows(payload)


def _fallback_rows_from_payload(payload: dict, filters: dict[str, str]) -> list[dict]:
    return queue_state.fallback_rows_from_payload(payload, filters)


def _is_success_record(row: dict) -> bool:
    if _has_currency_contamination(row):
        return False
    if not _location_verified(row.get("frontend_location_note") or row.get("frontend_delivery"), str(row.get("marketplace") or "")):
        return False
    return str(row.get("frontend_check_status") or "") == "已自动检查" and bool(
        row.get("frontend_findings") or row.get("suspected_issue")
    )


def _has_currency_contamination(row: dict) -> bool:
    warning_keys = (
        "frontend_price_currency_warning",
        "price_currency_warning",
    )
    if any(str(row.get(key) or "").strip() for key in warning_keys):
        return True
    text_keys = (
        "frontend_findings",
        "frontend_search_findings",
        "frontend_price",
        "frontend_delivery",
    )
    if any(_contains_blocked_currency_marker(row.get(key)) for key in text_keys):
        return True
    price_warning = _price_currency_warning(str(row.get("frontend_price") or row.get("price") or ""), str(row.get("marketplace") or ""))
    if price_warning:
        return True
    for item in row.get("frontend_competitors") or []:
        if isinstance(item, dict):
            if str(item.get("price_currency_warning") or "").strip():
                return True
            if _contains_blocked_currency_marker(item.get("price")):
                return True
            if _price_currency_warning(str(item.get("price") or ""), str(row.get("marketplace") or "")):
                return True
    return False


def _load_previous_frontend_state() -> tuple[list[dict], dict[tuple[str, str, str], dict]]:
    return result_state.load_previous_frontend_state(
        RESULTS_PATH,
        is_success_record=_is_success_record,
        record_key=_record_key,
    )


def _cached_record_for(row: dict, cache: dict[tuple[str, str, str], dict]) -> dict | None:
    return result_state.cached_record_for(row, cache, record_key=_record_key)


def _has_competitor_samples(row: dict, minimum: int = 2) -> bool:
    count = int(_parse_number_text(row.get("frontend_competitor_count"), decimal_allowed=False) or 0)
    competitors = row.get("frontend_competitors") or []
    if isinstance(competitors, list):
        count = max(count, len([item for item in competitors if isinstance(item, dict)]))
    return count >= minimum


def _is_today_chrome_cdp_record(row: dict, today: str | None = None, *, require_competitor_samples: bool = False) -> bool:
    today = today or _today_iso()
    is_today = (
        _is_success_record(row)
        and str(row.get("frontend_check_method") or "") == "chrome-cdp"
        and not bool(row.get("frontend_cache_used"))
        and _record_data_date(row) == today
    )
    if not is_today:
        return False
    if require_competitor_samples:
        return _has_competitor_samples(row)
    return True


def _fresh_chrome_cdp_record_for(
    row: dict,
    cache: dict[tuple[str, str, str], dict],
    today: str,
    *,
    require_competitor_samples: bool = False,
) -> dict | None:
    cached = _cached_record_for(row, cache)
    if cached and _is_today_chrome_cdp_record(cached, today, require_competitor_samples=require_competitor_samples):
        return cached
    if _is_today_chrome_cdp_record(row, today, require_competitor_samples=require_competitor_samples):
        return row
    return None


def _record_from_fresh_skip(row: dict, fresh: dict) -> dict:
    copied = dict(fresh)
    copied.update(
        {
            "marketplace": row.get("marketplace"),
            "sku": row.get("sku"),
            "asin": row.get("asin"),
            "product_name": row.get("product_name") or copied.get("product_name"),
            "product_url": row.get("product_url") or copied.get("product_url"),
            "frontend_core_keyword": row.get("frontend_core_keyword") or copied.get("frontend_core_keyword"),
            "frontend_search_url": row.get("frontend_search_url") or copied.get("frontend_search_url"),
            "frontend_refresh_action": "skipped_fresh",
            "frontend_refresh_checked": False,
            "frontend_refresh_reason": "已有今日 Chrome CDP 成功证据，日常刷新跳过。",
        }
    )
    return copied


def _record_from_cache(row: dict, cached: dict, fetch_error: str, extra: dict[str, object] | None = None) -> dict:
    copied = dict(cached)
    current_search_keyword = str(
        row.get("frontend_core_keyword") or (extra or {}).get("frontend_search_keyword") or ""
    ).strip()
    cached_search_keyword = str(copied.get("frontend_search_keyword") or copied.get("frontend_core_keyword") or "").strip()
    current_search_url = str(
        row.get("frontend_search_url") or (extra or {}).get("frontend_search_url") or ""
    ).strip()
    cached_search_url = str(copied.get("frontend_search_url") or "").strip()
    search_context_changed = (
        bool(current_search_keyword and cached_search_keyword and current_search_keyword != cached_search_keyword)
        or bool(current_search_url and cached_search_url and current_search_url != cached_search_url)
    )
    cached_at = str(copied.get("checked_at") or "")
    cached_date = cached_at.split("T", 1)[0] if cached_at else ""
    cache_label = f"沿用 {cached_date} 前台数据" if cached_date else "沿用历史前台数据"
    prefix = f"{cache_label}{f'（{cached_at}）' if cached_at else ''}"
    findings = str(copied.get("frontend_findings") or "上次前台读取成功，但本次未稳定读取。")
    copied.update(
        {
            "marketplace": row.get("marketplace"),
            "sku": row.get("sku"),
            "asin": row.get("asin"),
            "product_name": row.get("product_name"),
            "product_url": row.get("product_url") or copied.get("product_url"),
            "frontend_core_keyword": row.get("frontend_core_keyword") or copied.get("frontend_core_keyword"),
            "frontend_search_url": row.get("frontend_search_url") or copied.get("frontend_search_url"),
            "frontend_check_status": cache_label,
            "frontend_findings": f"{prefix}；{findings}",
            "confirmed_status": row.get("confirmed_status") or copied.get("confirmed_status") or "待确认",
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "source": "auto_frontend_check_cache",
            "frontend_cache_used": True,
            "frontend_cache_checked_at": cached_at,
            "frontend_data_date": cached_date,
            "frontend_data_freshness": f"沿用 {cached_date} 前台数据" if cached_date else "沿用历史前台数据",
            "frontend_last_error": _shorten(fetch_error, limit=180),
            "frontend_refresh_action": "cache_fallback",
            "frontend_refresh_checked": True,
            "frontend_refresh_reason": "本次实时读取未成功，沿用最近一次可用前台缓存。",
        }
    )
    if search_context_changed:
        copied.update(
            {
                "frontend_search_status": "待前台检查",
                "frontend_search_findings": "搜索核心词或搜索 URL 已变化，历史搜索页证据仅作背景参考；本次未稳定读取当前搜索页。",
                "frontend_competitor_count": 0,
                "frontend_competitors": [],
                "own_search_position": "",
                "frontend_search_result_count": 0,
                "frontend_search_partial_evidence": False,
                "frontend_search_method": "",
                "frontend_search_keyword": current_search_keyword,
                "frontend_search_url": current_search_url or copied.get("frontend_search_url"),
            }
        )
    if extra:
        cached_strength = _search_status_strength(copied.get("frontend_search_status"))
        extra_strength = _search_status_strength(extra.get("frontend_search_status"))
        for key, value in extra.items():
            if key in _SEARCH_STATUS_KEYS:
                if search_context_changed:
                    if key == "frontend_search_findings" and value not in (None, "", [], {}):
                        copied[key] = f"搜索核心词或搜索 URL 已变化，历史搜索页证据仅作背景参考；{value}"
                        continue
                    copied[key] = value
                    continue
                if cached_strength > extra_strength:
                    continue
            if value not in (None, "", [], {}):
                copied[key] = value
    copied.update(_quality_payload_from_record(copied, fetch_error, basis="cache"))
    copied["frontend_auto_conclusion_basis"] = "cache"
    return copied


def _status_from_parsed(parsed: dict[str, str]) -> str:
    if parsed.get("captcha_or_block") == "是":
        return "待前台检查"
    if parsed.get("price_currency_warning"):
        return "待前台检查"
    if parsed.get("location_scope") in {"wrong", "unknown"}:
        return "待前台检查"
    if _contains_blocked_currency_marker(parsed.get("delivery")):
        return "待前台检查"
    if parsed.get("title") or parsed.get("price") or parsed.get("rating"):
        return "已自动检查"
    return "待前台检查"


def _frontend_failure_signal(parsed: dict[str, str], fetch_error: str = "", *, html_present: bool = False) -> str:
    signals: list[str] = []
    if parsed.get("price_currency_warning"):
        signals.append(str(parsed.get("price_currency_warning") or ""))
    if parsed.get("location_hard_failure") and parsed.get("location_scope") in {"wrong", "unknown"}:
        signals.append(str(parsed.get("location_hard_failure") or ""))
    elif parsed.get("location_warning") and parsed.get("location_scope") not in {"exact", "marketplace", "missing"}:
        signals.append(str(parsed.get("location_warning") or ""))
    if parsed.get("captcha_or_block") == "是":
        signals.append("Amazon 返回验证码或页面限制")
    if signals:
        return "；".join(dict.fromkeys(item for item in signals if item))
    if fetch_error:
        return str(fetch_error)
    if not html_present:
        return "Amazon 前台未返回可解析 HTML"
    if parsed and not (parsed.get("title") or parsed.get("price") or parsed.get("rating")):
        return "Amazon 前台页面字段解析不足"
    return ""


def _failure_signal_rank(signal: str) -> int:
    text = str(signal or "").lower()
    if "地区异常" in signal or "价格币种异常" in signal or "currency" in text:
        return 5
    if "验证码" in signal or "captcha" in text or "robot check" in text:
        return 4
    if "地区未确认" in signal or "location" in text:
        return 3
    if "urlopen" in text or "ssl" in text or "network" in text or "timed out" in text or "timeout" in text:
        return 2
    if signal:
        return 1
    return 0


def _public_frontend_failure_text(signal: str) -> str:
    text = str(signal or "").strip()
    lower = text.lower()
    if not text:
        return ""
    if "价格币种异常" in text or "地区异常" in text or "地区未确认" in text or "验证码" in text:
        return text
    if "urlopen" in lower or "nodename" in lower or "dns" in lower:
        return "网络或站点限制导致未读到页面"
    if "ssl" in lower or "eof occurred" in lower:
        return "Amazon 连接中断，未读到稳定页面"
    if "timeout" in lower or "timed out" in lower or "超时" in text:
        return "页面读取超时"
    if "未返回可解析 html" in lower:
        return "Amazon 前台未返回可解析 HTML"
    if "字段解析不足" in text:
        return "Amazon 前台页面字段解析不足"
    return text


def _pick_frontend_failure_signal(current: str, candidate: str) -> str:
    if not candidate:
        return current
    if not current:
        return candidate
    current_rank = _failure_signal_rank(current)
    candidate_rank = _failure_signal_rank(candidate)
    if candidate_rank > current_rank:
        return candidate
    if candidate_rank == current_rank and candidate not in current:
        return f"{current}；{candidate}"
    return current


def _front_structured_fields(parsed: dict[str, str], location_note: str = "") -> dict[str, str]:
    return {
        "frontend_price": parsed.get("price", ""),
        "frontend_price_currency_warning": parsed.get("price_currency_warning", ""),
        "frontend_rating": parsed.get("rating", ""),
        "frontend_reviews": parsed.get("reviews", ""),
        "frontend_coupon": parsed.get("coupon_detail") or parsed.get("coupon", ""),
        "frontend_buy_box": parsed.get("buy_box", ""),
        "frontend_delivery": location_note or parsed.get("delivery", ""),
        "frontend_location_note": location_note or parsed.get("visible_location", ""),
        "frontend_location_scope": parsed.get("location_scope", ""),
        "frontend_location_warning": parsed.get("location_warning", ""),
    }


def _grade_from_score(score: int) -> str:
    if score >= 75:
        return "strong"
    if score >= 55:
        return "acceptable"
    if score > 0:
        return "weak"
    return "unknown"


def _confidence_from_score(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _parse_number_text(value: object, *, decimal_allowed: bool = True) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not match:
        return None
    token = match.group(0)
    if "," in token and "." in token:
        token = token.replace(",", "")
    elif "," in token:
        tail = token.rsplit(",", 1)[-1]
        token = token.replace(",", "") if len(tail) == 3 else token.replace(",", ".")
    elif "." in token and not decimal_allowed:
        tail = token.rsplit(".", 1)[-1]
        if len(tail) == 3:
            token = token.replace(".", "")
    with contextlib.suppress(ValueError):
        return float(token)
    return None


def _parse_price_number(value: object) -> float | None:
    return _parse_number_text(value, decimal_allowed=True)


def _parse_rating(value: object) -> float | None:
    rating = _parse_number_text(value, decimal_allowed=True)
    if rating is None:
        return None
    if 0 < rating <= 5:
        return rating
    return None


def _parse_review_count(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([kK])?", text)
    if not match:
        return None
    number = match.group(1)
    suffix = match.group(2)
    if suffix:
        with contextlib.suppress(ValueError):
            return int(round(float(number.replace(",", ".")) * 1000))
        return None
    value_num = _parse_number_text(number, decimal_allowed=False)
    return int(round(value_num)) if value_num is not None else None


def _median(values: list[float]) -> float | None:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    midpoint = len(clean) // 2
    if len(clean) % 2:
        return clean[midpoint]
    return (clean[midpoint - 1] + clean[midpoint]) / 2


def _score_product_page(parsed: dict[str, str], row: dict | None = None, location_note: str = "") -> dict[str, object]:
    row = row or {}
    flags: list[str] = []
    reasons: list[str] = []
    components: dict[str, int] = {}
    location_basis = location_note or parsed.get("visible_location") or row.get("frontend_location_note") or row.get("frontend_delivery") or ""
    marketplace = str(row.get("marketplace") or parsed.get("marketplace") or "")
    location_hard_failure = str(parsed.get("location_hard_failure") or _location_hard_failure(location_basis, marketplace)).strip()
    location_warning = str(parsed.get("location_warning") or _location_warning(location_basis, marketplace)).strip()

    if parsed.get("captcha_or_block") == "是":
        return {
            "frontend_product_quality_score": 0,
            "frontend_product_quality_grade": "unknown",
            "frontend_product_quality_confidence": "low",
            "frontend_product_quality_reasons": ["Amazon 返回验证码或页面限制"],
            "frontend_product_quality_flags": ["amazon_blocked"],
            "frontend_product_quality_components": {},
        }
    if parsed.get("price_currency_warning"):
        return {
            "frontend_product_quality_score": 0,
            "frontend_product_quality_grade": "unknown",
            "frontend_product_quality_confidence": "low",
            "frontend_product_quality_reasons": [parsed.get("price_currency_warning", "价格币种异常")],
            "frontend_product_quality_flags": ["currency_mismatch"],
            "frontend_product_quality_components": {},
        }
    if location_hard_failure:
        return {
            "frontend_product_quality_score": 0,
            "frontend_product_quality_grade": "unknown",
            "frontend_product_quality_confidence": "low",
            "frontend_product_quality_reasons": [location_hard_failure],
            "frontend_product_quality_flags": ["location_unverified"],
            "frontend_product_quality_components": {},
        }
    if location_warning:
        flags.append("location_not_exact")
        reasons.append(location_warning)

    price = _parse_price_number(parsed.get("price"))
    rating = _parse_rating(parsed.get("rating"))
    reviews = _parse_review_count(parsed.get("reviews"))
    coupon_text = str(parsed.get("coupon_detail") or parsed.get("coupon") or "")
    buy_box_text = str(parsed.get("buy_box") or "")
    delivery_text = str(location_basis or parsed.get("delivery") or "")

    components["price_present"] = 20 if price is not None else 0
    if price is not None:
        reasons.append(f"已读取售价 {parsed.get('price')}")
    else:
        flags.append("price_missing")

    if rating is None:
        components["rating_score"] = 0
        flags.append("rating_missing")
    elif rating >= 4.2:
        components["rating_score"] = 20
        reasons.append(f"评分 {rating:g}")
    elif rating >= 4.0:
        components["rating_score"] = 15
        reasons.append(f"评分 {rating:g}")
    else:
        components["rating_score"] = 6
        flags.append("rating_low")
        reasons.append(f"评分偏弱 {rating:g}")

    if reviews is None:
        components["review_score"] = 0
        flags.append("reviews_missing")
    elif reviews >= 100:
        components["review_score"] = 15
        reasons.append(f"评论数 {reviews}")
    elif reviews >= 20:
        components["review_score"] = 10
        reasons.append(f"评论数 {reviews}")
    else:
        components["review_score"] = 5
        flags.append("reviews_low")
        reasons.append(f"评论数偏少 {reviews}")

    coupon_value = _extract_coupon_value(coupon_text)
    if coupon_value:
        components["coupon_score"] = 15
        reasons.append(f"Coupon {coupon_value}")
    elif "未稳定识别" in coupon_text or not coupon_text:
        components["coupon_score"] = 5
        flags.append("coupon_missing")
    else:
        components["coupon_score"] = 8
        flags.append("coupon_uncertain")

    if "识别到购买按钮" in buy_box_text:
        components["buy_box_score"] = 20
        reasons.append("Buy Box/购买按钮已识别")
    elif buy_box_text:
        components["buy_box_score"] = 0
        flags.append("buy_box_missing")
    else:
        components["buy_box_score"] = 0
        flags.append("buy_box_unknown")

    if delivery_text:
        components["delivery_score"] = 10
        reasons.append(f"配送 {delivery_text}")
    else:
        components["delivery_score"] = 5
        flags.append("delivery_missing")

    score = int(max(0, min(100, sum(components.values()))))
    return {
        "frontend_product_quality_score": score,
        "frontend_product_quality_grade": _grade_from_score(score),
        "frontend_product_quality_confidence": _confidence_from_score(score),
        "frontend_product_quality_reasons": reasons[:6],
        "frontend_product_quality_flags": flags[:8],
        "frontend_product_quality_components": components,
    }


def _score_search_page(parsed_product: dict[str, str], search_payload: dict[str, object], row: dict | None = None) -> dict[str, object]:
    row = row or {}
    competitors = search_payload.get("frontend_competitors") or []
    if not isinstance(competitors, list):
        competitors = []
    own_price = _parse_price_number(parsed_product.get("price") or row.get("frontend_price"))
    own_rating = _parse_rating(parsed_product.get("rating") or row.get("frontend_rating"))
    own_reviews = _parse_review_count(parsed_product.get("reviews") or row.get("frontend_reviews"))
    comp_prices = [_parse_price_number(item.get("price")) for item in competitors if isinstance(item, dict)]
    comp_ratings = [_parse_rating(item.get("rating")) for item in competitors if isinstance(item, dict)]
    comp_reviews = [_parse_review_count(item.get("reviews")) for item in competitors if isinstance(item, dict)]
    comp_prices_clean = [value for value in comp_prices if value is not None]
    comp_ratings_clean = [value for value in comp_ratings if value is not None]
    comp_reviews_clean = [value for value in comp_reviews if value is not None]
    flags: list[str] = []
    reasons: list[str] = []
    components: dict[str, int] = {}
    partial_evidence = bool(search_payload.get("frontend_search_partial_evidence"))
    result_count = _parse_number_text(search_payload.get("frontend_search_result_count"), decimal_allowed=False)

    count = len(competitors)
    if count >= 3:
        components["competitor_sample_score"] = 20
    elif count >= 2:
        components["competitor_sample_score"] = 15
    elif count == 1:
        components["competitor_sample_score"] = 8
        flags.append("competitor_sample_small")
        reasons.append("可比竞品少于2个，差距不计算")
    else:
        components["competitor_sample_score"] = 4 if partial_evidence or (result_count is not None and result_count > 0) else 0
        flags.append("competitor_sample_missing")
        if result_count is not None and result_count > 0:
            reasons.append(f"搜索页只识别结果卡 {int(result_count)} 个，未解析到可比竞品")

    own_position = _parse_number_text(search_payload.get("own_search_position"), decimal_allowed=False)
    if own_position is None:
        components["own_position_score"] = 5 if count else (3 if partial_evidence or (result_count is not None and result_count > 0) else 0)
    elif own_position <= 8:
        components["own_position_score"] = 15
        reasons.append(f"自然位约第 {int(own_position)}")
    elif own_position <= 16:
        components["own_position_score"] = 9
        reasons.append(f"自然位约第 {int(own_position)}")
    else:
        components["own_position_score"] = 4
        flags.append("own_position_low")
        reasons.append(f"自然位偏后，约第 {int(own_position)}")

    comp_price_median = _median(comp_prices_clean)
    price_delta_pct: float | None = None
    if count >= 2 and own_price is not None and comp_price_median:
        price_delta_pct = (own_price - comp_price_median) / comp_price_median
        if price_delta_pct <= 0.03:
            components["price_competitiveness_score"] = 25
        elif price_delta_pct <= 0.10:
            components["price_competitiveness_score"] = 15
        else:
            components["price_competitiveness_score"] = 5
            flags.append("price_gap")
        reasons.append(f"价格较竞品中位数 {price_delta_pct:+.1%}")
    else:
        components["price_competitiveness_score"] = 0
        flags.append("price_competition_unknown")

    comp_rating_avg = sum(comp_ratings_clean) / len(comp_ratings_clean) if comp_ratings_clean else None
    rating_delta: float | None = None
    if count >= 2 and own_rating is not None and comp_rating_avg is not None:
        rating_delta = own_rating - comp_rating_avg
        if rating_delta >= -0.1:
            components["rating_competitiveness_score"] = 20
        elif rating_delta >= -0.3:
            components["rating_competitiveness_score"] = 12
        else:
            components["rating_competitiveness_score"] = 5
            flags.append("rating_gap")
        reasons.append(f"评分较竞品均值 {rating_delta:+.1f}")
    else:
        components["rating_competitiveness_score"] = 0
        flags.append("rating_competition_unknown")

    comp_review_median = _median([float(value) for value in comp_reviews_clean])
    review_delta_pct: float | None = None
    if count >= 2 and own_reviews is not None and comp_review_median and comp_review_median > 0:
        review_delta_pct = (own_reviews - comp_review_median) / comp_review_median
        if review_delta_pct >= -0.2:
            components["review_strength_score"] = 20
        elif review_delta_pct >= -0.6:
            components["review_strength_score"] = 12
        else:
            components["review_strength_score"] = 5
            flags.append("review_gap")
        reasons.append(f"评论数较竞品中位数 {review_delta_pct:+.1%}")
    else:
        components["review_strength_score"] = 0
        flags.append("review_competition_unknown")

    score = int(max(0, min(100, sum(components.values()))))
    return {
        "frontend_search_quality_score": score,
        "frontend_search_quality_grade": _grade_from_score(score),
        "frontend_search_quality_confidence": _confidence_from_score(score),
        "frontend_search_quality_reasons": reasons[:6],
        "frontend_search_quality_flags": flags[:8],
        "frontend_search_quality_components": components,
        "frontend_search_result_count": int(result_count) if result_count is not None else "",
        "frontend_search_partial_evidence": partial_evidence,
        "frontend_price_delta_pct": round(price_delta_pct, 4) if price_delta_pct is not None else "",
        "frontend_rating_delta": round(rating_delta, 3) if rating_delta is not None else "",
        "frontend_review_delta_pct": round(review_delta_pct, 4) if review_delta_pct is not None else "",
        "frontend_competitor_price_median": round(comp_price_median, 2) if comp_price_median is not None else "",
        "frontend_competitor_rating_avg": round(comp_rating_avg, 2) if comp_rating_avg is not None else "",
        "frontend_competitor_review_median": int(round(comp_review_median)) if comp_review_median is not None else "",
    }


def _classify_frontend_failure(stage: str, error: str, parsed: dict[str, str] | None = None, url: str = "", method: str = "") -> dict[str, str]:
    parsed = parsed or {}
    text = " ".join(
        [
            str(error or ""),
            str(parsed.get("price_currency_warning") or ""),
            str(parsed.get("location_warning") or ""),
            str(parsed.get("captcha_or_block") or ""),
        ]
    ).lower()
    category = "none"
    reason = ""
    recoverability = "none"
    if not url:
        category = "missing_input"
        reason = "缺少前台 URL"
        recoverability = "fix_config"
    elif parsed.get("price_currency_warning") or "价格币种异常" in str(error or "") or "currency" in text:
        category = "currency_mismatch"
        reason = str(parsed.get("price_currency_warning") or error or "价格币种异常")
        recoverability = "retry_later"
    elif parsed.get("location_warning"):
        category = "location_unverified"
        reason = str(parsed.get("location_warning") or "地区未确认")
        recoverability = "retry_with_browser_location"
    elif parsed.get("captcha_or_block") == "是" or "captcha" in text or "robot check" in text:
        category = "captcha"
        reason = "Amazon 页面限制或验证码"
        recoverability = "retry_later"
    elif "playwright 未安装" in text or "playwright 不可用" in text:
        category = "dependency_missing"
        reason = "本机浏览器依赖不可用"
        recoverability = "fix_config"
    elif "timeout" in text or "timed out" in text or "超时" in text:
        category = "navigation_timeout"
        reason = "页面读取超时"
        recoverability = "retry_later"
    elif "页面读取失败" in text or "browser" in text or "chrome" in text:
        category = "browser_launch_failed"
        reason = "浏览器读取失败"
        recoverability = "retry_later"
    elif "urlopen" in text or "network" in text or "dns" in text or "nodename" in text or "blocked" in text:
        category = "network_error"
        reason = "网络或站点限制导致未读到页面"
        recoverability = "retry_later"
    elif "未返回可解析 html" in text or "字段解析不足" in text:
        category = "parse_incomplete"
        reason = "页面字段解析不足"
        recoverability = "retry_later"
    elif error:
        category = "unknown"
        reason = "自动读取失败"
        recoverability = "retry_later"
    elif parsed and not (parsed.get("title") or parsed.get("price") or parsed.get("rating")):
        category = "parse_incomplete"
        reason = "页面字段解析不足"
        recoverability = "retry_later"
    return {
        "frontend_failure_stage": stage if category != "none" else "none",
        "frontend_failure_category": category,
        "frontend_failure_reason": reason,
        "frontend_failure_recoverability": recoverability,
        "frontend_failure_method": method,
    }


def _auto_frontend_conclusion(
    product_quality: dict[str, object],
    search_quality: dict[str, object],
    failure: dict[str, str],
    *,
    basis: str,
) -> dict[str, object]:
    product_score = int(product_quality.get("frontend_product_quality_score") or 0)
    search_score = int(search_quality.get("frontend_search_quality_score") or 0)
    product_flags = set(product_quality.get("frontend_product_quality_flags") or [])
    search_flags = set(search_quality.get("frontend_search_quality_flags") or [])
    failure_category = str(failure.get("frontend_failure_category") or "none")
    weak_flags = {
        "rating_low",
        "reviews_low",
        "coupon_missing",
        "buy_box_missing",
        "price_gap",
        "rating_gap",
        "review_gap",
        "own_position_low",
    }
    weak_hit = bool((product_flags | search_flags) & weak_flags)
    strong_product = product_score >= 75
    strong_search = search_score >= 70
    usable_evidence = product_score >= 45 or search_score >= 45

    if failure_category not in {"none", ""} and not usable_evidence:
        code = "INSUFFICIENT_EVIDENCE"
        label = "自动证据不足，不能用于强诊断"
        confidence = "low"
        reasons = [failure.get("frontend_failure_reason") or "自动读取失败"]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        allowed = ["observe", "bid_down", "negative_exact"]
    elif weak_hit and (product_score < 75 or search_score < 70):
        code = "FRONTEND_WEAK"
        label = "明确前台劣势"
        confidence = "high" if product_score >= 45 or search_score >= 55 else "medium"
        reasons = [*product_quality.get("frontend_product_quality_reasons", []), *search_quality.get("frontend_search_quality_reasons", [])]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        allowed = ["observe", "bid_down", "negative_exact"]
    elif strong_product and strong_search and not weak_hit:
        code = "FRONTEND_OK"
        label = "未见明显前台劣势"
        confidence = "high"
        reasons = [*product_quality.get("frontend_product_quality_reasons", []), *search_quality.get("frontend_search_quality_reasons", [])]
        blocked = []
        allowed = ["observe", "bid_down", "negative_exact", "create_exact_low_budget"]
    elif usable_evidence:
        code = "EVIDENCE_CONFLICT"
        label = "证据冲突"
        confidence = "medium"
        reasons = [*product_quality.get("frontend_product_quality_reasons", []), *search_quality.get("frontend_search_quality_reasons", [])]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        allowed = ["observe", "bid_down", "negative_exact"]
    else:
        code = "INSUFFICIENT_EVIDENCE"
        label = "自动证据不足，不能用于强诊断"
        confidence = "low"
        reasons = ["产品页或搜索页字段不足"]
        blocked = ["bid_up", "budget_up", "broad_scale"]
        allowed = ["observe", "bid_down", "negative_exact"]

    return {
        "frontend_auto_conclusion": code,
        "frontend_auto_conclusion_label": label,
        "frontend_auto_conclusion_reasons": [str(item) for item in reasons if item][:6],
        "frontend_auto_conclusion_confidence": confidence,
        "frontend_auto_conclusion_basis": basis,
        "frontend_auto_conclusion_requires_manual_check": False,
        "frontend_auto_conclusion_blocked_ad_actions": blocked,
        "frontend_auto_conclusion_allowed_ad_actions": allowed,
    }


def _frontend_quality_payload(
    parsed: dict[str, str],
    row: dict,
    search_payload: dict[str, object],
    fetch_error: str,
    search_error: str = "",
    *,
    status: str = "",
    basis: str = "current_product_page",
    method: str = "",
    location_note: str = "",
) -> dict[str, object]:
    product_quality = _score_product_page(parsed, row, location_note=location_note)
    search_quality = _score_search_page(parsed, search_payload, row)
    location_basis = location_note or parsed.get("visible_location") or row.get("frontend_location_note") or row.get("frontend_delivery") or ""
    marketplace = str(row.get("marketplace") or parsed.get("marketplace") or "")
    location_warning = str(parsed.get("location_warning") or _location_warning(location_basis, marketplace)).strip()
    location_hard_failure = str(parsed.get("location_hard_failure") or _location_hard_failure(location_basis, marketplace)).strip()
    location_scope = parsed.get("location_scope") or _location_scope(location_basis, marketplace)
    failure = _classify_frontend_failure(
        "product_page",
        fetch_error or location_hard_failure,
        {**parsed, "location_warning": location_hard_failure},
        str(row.get("product_url") or ""),
        method,
    )
    if failure["frontend_failure_category"] == "none" and search_error:
        search_failure = _classify_frontend_failure(
            "search_page",
            search_error,
            {},
            str(search_payload.get("frontend_search_url") or ""),
            method,
        )
        failure = {
            **failure,
            "frontend_search_failure_category": search_failure["frontend_failure_category"],
            "frontend_search_last_error": _shorten(search_error, limit=180),
        }
    payload: dict[str, object] = {
        **product_quality,
        **search_quality,
        **failure,
    }
    total_score = int(round((int(product_quality.get("frontend_product_quality_score") or 0) * 0.6) + (int(search_quality.get("frontend_search_quality_score") or 0) * 0.4)))
    if location_hard_failure:
        total_score = min(total_score, 35)
    elif location_scope != "exact":
        total_score = min(total_score, 65)
    payload.update(
        {
            "frontend_evidence_quality_score": total_score,
            "frontend_evidence_quality_grade": _grade_from_score(total_score),
            "frontend_evidence_quality_confidence": _confidence_from_score(total_score),
            "frontend_location_verified": not bool(location_hard_failure),
            "frontend_location_exact": location_scope == "exact",
            "frontend_location_scope": location_scope,
            "frontend_location_warning": location_warning,
        }
    )
    conclusion_basis = basis
    if status == "已自动检查" and search_payload.get("frontend_search_status") == "已自动检查":
        conclusion_basis = "current_product_and_search_page"
    elif status == "已自动检查":
        conclusion_basis = "current_product_page"
    elif basis == "cache":
        conclusion_basis = "cache"
    else:
        conclusion_basis = "no_data"
    payload.update(_auto_frontend_conclusion(product_quality, search_quality, failure, basis=conclusion_basis))
    return payload


def _quality_payload_from_record(record: dict, fetch_error: str = "", *, basis: str = "cache") -> dict[str, object]:
    findings = str(record.get("frontend_findings") or "")

    def labeled(label: str) -> str:
        match = re.search(rf"{re.escape(label)}：([^；;]+)", findings)
        return match.group(1).strip() if match else ""

    parsed = {
        "price": str(record.get("frontend_price") or labeled("售价")),
        "rating": str(record.get("frontend_rating") or labeled("评分")),
        "reviews": str(record.get("frontend_reviews") or labeled("评论数")),
        "coupon": str(record.get("frontend_coupon") or labeled("Coupon")),
        "coupon_detail": str(record.get("frontend_coupon") or labeled("Coupon")),
        "buy_box": str(record.get("frontend_buy_box") or labeled("Buy Box")),
        "delivery": str(record.get("frontend_delivery") or labeled("配送")),
        "captcha_or_block": "否",
        "price_currency_warning": str(record.get("frontend_price_currency_warning") or ""),
        "visible_location": str(record.get("frontend_location_note") or record.get("frontend_delivery") or ""),
        "location_warning": str(record.get("frontend_location_warning") or ""),
    }
    if not parsed["price_currency_warning"]:
        parsed["price_currency_warning"] = _price_currency_warning(parsed["price"], str(record.get("marketplace") or ""))
        if parsed["price_currency_warning"]:
            parsed["price"] = ""
    search_payload = {
        "frontend_search_status": record.get("frontend_search_status") or "",
        "frontend_search_url": record.get("frontend_search_url") or "",
        "frontend_competitors": record.get("frontend_competitors") or [],
        "own_search_position": record.get("own_search_position") or "",
        "frontend_search_result_count": record.get("frontend_search_result_count") or "",
        "frontend_search_partial_evidence": bool(record.get("frontend_search_partial_evidence")),
    }
    return _frontend_quality_payload(
        parsed,
        record,
        search_payload,
        fetch_error,
        status=str(record.get("frontend_check_status") or ""),
        basis=basis,
        method=str(record.get("frontend_check_method") or ""),
        location_note=str(record.get("frontend_location_note") or record.get("frontend_delivery") or ""),
    )


def _findings(parsed: dict[str, str], fetch_error: str, location_note: str = "") -> str:
    if parsed.get("captcha_or_block") == "是":
        return "自动证据不足，不能用于强诊断；Amazon 返回验证码或页面限制。"
    combined_failure = _frontend_failure_signal(parsed, fetch_error, html_present=bool(parsed))
    if combined_failure:
        return "自动证据不足，不能用于强诊断；" + _shorten(_public_frontend_failure_text(combined_failure), limit=180)
    if fetch_error:
        return "自动证据不足，不能用于强诊断；" + _shorten(_public_frontend_failure_text(fetch_error), limit=140)
    parts = []
    if parsed.get("price_currency_warning"):
        parts.append(parsed["price_currency_warning"])
    for label, key in [
        ("售价", "price"),
        ("评分", "rating"),
        ("评论数", "reviews"),
        ("Coupon", "coupon"),
        ("Buy Box", "buy_box"),
    ]:
        value = parsed.get(key)
        if value:
            parts.append(f"{label}：{_shorten(value)}")
    if location_note:
        parts.append(f"配送：{_shorten(location_note, limit=60)}")
    elif parsed.get("location_warning"):
        parts.append(f"配送：{_shorten(parsed['location_warning'], limit=60)}")
    return "；".join(parts[:6]) if parts else "自动证据不足，不能用于强诊断；页面字段不完整。"


def _first_number(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(text or ""))
    if not match:
        return None
    with contextlib.suppress(ValueError):
        return float(match.group(0).replace(",", "."))
    return None


def _metric_number(text: str, label: str) -> float | None:
    pattern = rf"{re.escape(label)}\s*([0-9][0-9,\.]*)"
    match = re.search(pattern, str(text or ""))
    if not match:
        return None
    with contextlib.suppress(ValueError):
        return float(match.group(1).replace(",", ""))
    return None


def _should_check_search_page(row: dict, policy: str = "always") -> bool:
    if policy == "always":
        return True
    if policy == "never":
        return False
    text = "；".join(
        str(row.get(key) or "")
        for key in ["trigger_reason", "key_metrics", "frontend_check_focus", "suspected_issue"]
    )
    if any(token in text for token in ["广告", "点击", "ACOS", "搜索词", "ASIN", "转化", "加购", "消耗", "无单"]):
        return True
    clicks = _metric_number(text, "点击")
    spend = _metric_number(text, "花费")
    orders = _metric_number(text, "广告订单")
    return bool((clicks or 0) >= 8 or (spend or 0) >= 3 or orders == 0)


def _suspected_issue(parsed: dict[str, str], default: str, row: dict | None = None) -> str:
    if parsed.get("captcha_or_block") == "是":
        return default or "自动证据不足，不能用于强诊断"
    row = row or {}
    evidence_text = "；".join(
        str(row.get(key) or "")
        for key in ["trigger_reason", "key_metrics", "frontend_check_focus"]
    )
    rating_text = parsed.get("rating") or ""
    rating = _first_number(rating_text)
    reviews = _first_number(parsed.get("reviews") or "")
    coupon_text = str(parsed.get("coupon_detail") or parsed.get("coupon") or "")
    coupon_ok = bool(_extract_coupon_value(coupon_text))
    buy_box_ok = "识别到购买按钮" in str(parsed.get("buy_box") or "")
    frontend_basics_ok = bool((rating or 0) >= 4 and coupon_ok and buy_box_ok)
    clicks = _metric_number(evidence_text, "点击")
    ad_orders = _metric_number(evidence_text, "广告订单")

    if rating and rating < 4:
        return f"评分偏弱（{rating:g}），前台转化可能受评价拖累；先看竞品评分/评论差距。"
    if "加购" in evidence_text and ("购买 0" in evidence_text or "购买0" in evidence_text):
        if frontend_basics_ok:
            return "前台基础项正常但加购未购买；更像价格、Coupon、配送或竞品优惠临门一脚不够。"
        return "有加购但购买弱；优先核对价格、Coupon、配送和竞品优惠。"
    if ad_orders == 0 and (clicks or 0) >= 20:
        if frontend_basics_ok:
            review_text = f"{int(reviews)}评" if reviews else "有评价"
            return f"前台基础项未见明显硬伤（评分{rating:g}、{review_text}、有Coupon/Buy Box）；更像广告搜索词或ASIN定向不准，价格只做竞品复核。"
        return "点击不少但广告无单；先拆搜索词/ASIN定向，再核对价格和前台竞争力。"
    if "ACOS 高" in evidence_text or "ACOS" in evidence_text:
        if (ad_orders or 0) > 0:
            return "广告能出单但效率偏贵；重点看出单词出价、泛词和ASIN定向，不优先判断Listing问题。"
        return "广告花费偏贵但订单弱；优先查高花费0单词和前台价格差。"
    if parsed.get("price") and not coupon_ok:
        return "前台有价格但未识别到Coupon；若竞品有优惠，可能影响点击后转化。"
    if "未稳定识别 Buy Box" in parsed.get("buy_box", ""):
        return "疑似 Buy Box / 推荐报价不稳定"
    return default or "自动证据不足，不能用于强诊断"


def _default_search_payload(row: dict, search_policy: str = "never") -> dict[str, object]:
    search_keyword = str(row.get("frontend_core_keyword") or "").strip()
    search_url = str(row.get("frontend_search_url") or "") or _marketplace_search_url(
        str(row.get("marketplace") or ""), search_keyword
    )
    payload: dict[str, object] = {
        "frontend_search_keyword": search_keyword,
        "frontend_search_url": search_url,
        "frontend_search_status": "待前台检查" if search_url else "未配置核心词",
        "frontend_search_findings": "未配置核心词搜索页。",
        "frontend_competitor_count": 0,
        "frontend_competitors": [],
        "own_search_position": "",
    }
    if search_url and not _should_check_search_page(row, search_policy):
        payload["frontend_search_status"] = "按广告信号跳过"
        payload["frontend_search_findings"] = "当前不是广告点击/转化异常触发，跳过搜索页前三竞品以降低浏览器和报告开销。"
    return payload


def _build_frontend_result_row(
    row: dict,
    parsed: dict[str, str],
    *,
    fetch_error: str = "",
    fetch_method: str = "",
    location_note: str = "",
    search_payload: dict[str, object] | None = None,
    status: str | None = None,
    checked_at: str | None = None,
) -> dict:
    status = status or _status_from_parsed(parsed)
    checked_at = checked_at or datetime.now().isoformat(timespec="seconds")
    data_date = checked_at.split("T", 1)[0]
    effective_location_note = _apply_location_basis(parsed, location_note, str(row.get("marketplace") or ""), allow_html_visible=bool(parsed))
    search_payload = search_payload or _default_search_payload(row, "never")
    quality_payload = _frontend_quality_payload(
        parsed,
        {**row, "product_url": row.get("product_url") or _marketplace_product_url(str(row.get("marketplace") or ""), str(row.get("asin") or ""))},
        search_payload,
        fetch_error or parsed.get("price_currency_warning", ""),
        "",
        status=status,
        method=fetch_method,
        location_note=effective_location_note,
    )
    return {
        "marketplace": row.get("marketplace"),
        "sku": row.get("sku"),
        "asin": row.get("asin"),
        "product_name": row.get("product_name"),
        "product_url": row.get("product_url") or _marketplace_product_url(str(row.get("marketplace") or ""), str(row.get("asin") or "")),
        "frontend_check_status": status,
        "frontend_findings": _findings(parsed, fetch_error, location_note=effective_location_note),
        "suspected_issue": _suspected_issue(parsed, str(row.get("suspected_issue") or ""), row),
        "frontend_check_focus": row.get("frontend_check_focus"),
        "questions_to_check": row.get("questions_to_check"),
        "conservative_action": row.get("conservative_action"),
        "recommended_next_step": row.get("recommended_next_step"),
        "confirmed_status": row.get("confirmed_status") or "待确认",
        "checked_at": checked_at,
        "frontend_data_date": data_date if status == "已自动检查" else "",
        "frontend_data_freshness": "今日读取" if status == "已自动检查" else "无可用前台数据",
        "source": "auto_frontend_check",
        "frontend_check_method": fetch_method,
        "frontend_location_note": effective_location_note,
        "frontend_location_verified": _location_verified(effective_location_note, str(row.get("marketplace") or "")),
        "frontend_location_exact": _location_exact(effective_location_note, str(row.get("marketplace") or "")),
        "frontend_location_scope": _location_scope(effective_location_note, str(row.get("marketplace") or "")),
        "frontend_location_warning": parsed.get("location_warning", ""),
        "frontend_last_error": (
            _shorten(fetch_error or parsed.get("price_currency_warning", "") or parsed.get("location_warning", ""), limit=180)
            if status != "已自动检查"
            else ""
        ),
        **_front_structured_fields(parsed, location_note=effective_location_note),
        **search_payload,
        **quality_payload,
    }


def _result_row_from_cdp_probe(
    row: dict,
    *,
    endpoint: str,
    attempts: int,
    sleep_seconds: float,
    timeout: int,
    search_policy: str = "never",
) -> dict:
    if run_chrome_cdp_probe is None or build_stability_report is None:
        return _build_frontend_result_row(
            row,
            {},
            fetch_error="Chrome CDP 探测不可用：缺少脚本或依赖。",
            fetch_method="chrome-cdp",
            status="待前台检查",
        )
    try:
        payload = run_chrome_cdp_probe(
            endpoint=endpoint,
            marketplace=str(row.get("marketplace") or ""),
            asin=str(row.get("asin") or ""),
            attempts=attempts,
            sleep_seconds=sleep_seconds,
            timeout_seconds=timeout,
        )
    except Exception as exc:
        return _build_frontend_result_row(
            row,
            {},
            fetch_error=str(exc),
            fetch_method="chrome-cdp",
            status="待前台检查",
        )
    marketplace_key = re.sub(r"[^a-z0-9]+", "_", str(row.get("marketplace") or "").strip().lower()).strip("_")
    asin_key = re.sub(r"[^a-z0-9]+", "_", str(row.get("asin") or "").strip().lower()).strip("_")
    raw_attempts = [attempt for attempt in payload.get("attempts", []) if isinstance(attempt, dict)]

    if attempts < 20:
        latest = next((attempt for attempt in reversed(raw_attempts) if attempt.get("success")), raw_attempts[-1] if raw_attempts else {})
        parsed = {
            "marketplace": str(row.get("marketplace") or ""),
            "title": str(latest.get("title") or ""),
            "price": str(latest.get("price") or ""),
            "rating": str(latest.get("rating") or ""),
            "reviews": str(latest.get("reviews") or ""),
            "coupon": "待确认",
            "coupon_detail": "待确认",
            "buy_box": str(latest.get("buy_box") or "识别到购买按钮"),
            "delivery": str(latest.get("location") or ""),
            "visible_location": str(latest.get("location") or ""),
            "captcha_or_block": "是" if latest.get("captcha_or_block") else "否",
        }
        status = "已自动检查" if latest.get("success") else "待前台检查"
        fetch_error = "" if latest.get("success") else _shorten(str(latest.get("error") or latest.get("navigation_warning") or "Chrome CDP 实时读取失败"), 180)
        search_payload = _default_search_payload(row, search_policy)
        search_error = ""
        if latest.get("success") and search_payload.get("frontend_search_url") and _should_check_search_page(row, search_policy):
            parsed_search, search_error, search_parser = _parse_search_results_chrome_cdp(
                str(search_payload.get("frontend_search_url") or ""),
                timeout,
                str(row.get("marketplace") or ""),
                str(row.get("asin") or ""),
                endpoint,
            )
            search_payload = _search_payload_from_parsed(
                row,
                search_keyword=str(search_payload.get("frontend_search_keyword") or ""),
                search_url=str(search_payload.get("frontend_search_url") or ""),
                parsed_search=parsed_search,
                search_error=search_error,
                search_parser=search_parser,
            )
        result = _build_frontend_result_row(
            row,
            parsed if latest.get("success") else {},
            fetch_error=fetch_error,
            fetch_method="chrome-cdp",
            location_note=str(latest.get("location") or ""),
            search_payload=search_payload,
            status=status,
        )
        if search_error:
            result["frontend_search_last_error"] = _shorten(search_error, limit=180)
        return result

    report = build_stability_report(
        payload,
        marketplace=str(row.get("marketplace") or ""),
        asin=str(row.get("asin") or ""),
        min_attempts=20,
        max_failures=4,
        min_success_rate=0.8,
    )
    if marketplace_key and asin_key:
        attempts_path = OUTPUT_DIR / f"frontend_stability_attempts_{marketplace_key}_{asin_key}.json"
        report_path = OUTPUT_DIR / f"frontend_stability_report_{marketplace_key}_{asin_key}.json"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        attempts_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    passing_attempt_numbers = {
        str(attempt.get("attempt") or attempt.get("index") or "")
        for attempt in report.get("attempts", [])
        if isinstance(attempt, dict) and attempt.get("success")
    }
    passing_attempts = [
        attempt
        for attempt in raw_attempts
        if str(attempt.get("attempt") or attempt.get("index") or "") in passing_attempt_numbers
    ]
    latest = passing_attempts[-1] if passing_attempts else {}
    parsed = {
        "marketplace": str(row.get("marketplace") or ""),
        "title": str(latest.get("title") or ""),
        "price": str(latest.get("price") or ""),
        "rating": str(latest.get("rating") or ""),
        "reviews": str(latest.get("reviews") or ""),
        "coupon": "待确认",
        "coupon_detail": "待确认",
        "buy_box": str(latest.get("buy_box") or "识别到购买按钮"),
        "delivery": str(latest.get("location") or ""),
        "visible_location": str(latest.get("location") or ""),
        "captcha_or_block": "否",
    }
    status = "已自动检查" if report.get("passed") else "待前台检查"
    fetch_error = "" if report.get("passed") else (
        f"Chrome CDP 20次验收未通过：{report.get('success_count')}/{report.get('total_attempts')}，失败 {report.get('failure_count')}"
    )
    result = _build_frontend_result_row(
        row,
        parsed if report.get("passed") else {},
        fetch_error=fetch_error,
        fetch_method="chrome-cdp",
        location_note=str(latest.get("location") or ""),
        search_payload=_default_search_payload(row, search_policy),
        status=status,
    )
    result.update(
        {
            "frontend_stability_total_attempts": report.get("total_attempts"),
            "frontend_stability_success_count": report.get("success_count"),
            "frontend_stability_failure_count": report.get("failure_count"),
            "frontend_stability_success_rate": report.get("success_rate"),
            "frontend_stability_passed": bool(report.get("passed")),
        }
    )
    return result


def _mark_live_refresh(row: dict) -> dict:
    marked = dict(row)
    marked.update(
        {
            "frontend_refresh_action": "live_checked",
            "frontend_refresh_checked": True,
            "frontend_refresh_reason": "本次日常刷新读取。",
        }
    )
    return marked


def _mark_pending_refresh(row: dict) -> dict:
    marked = dict(row)
    marked.setdefault("frontend_refresh_action", "live_failed")
    marked.setdefault("frontend_refresh_checked", True)
    marked.setdefault("frontend_refresh_reason", "本次实时读取失败，未找到可用缓存。")
    return marked


def _refresh_summary(rows: list[dict]) -> dict[str, object]:
    return result_state.refresh_summary(rows)


def import_manual_frontend_evidence(
    *,
    marketplace: str,
    sku: str,
    asin: str,
    title: str = "",
    price: str = "",
    rating: str = "",
    reviews: str = "",
    location_note: str = "",
    coupon: str = "待确认",
    buy_box: str = "识别到购买按钮",
    method: str = "chrome-extension",
    checked_at: str = "",
    stability_total_attempts: int | None = None,
    stability_success_count: int | None = None,
    stability_failure_count: int | None = None,
    stability_success_rate: float | None = None,
    stability_passed: bool | None = None,
) -> dict:
    payload = json.loads(LATEST_ANALYSIS.read_text(encoding="utf-8"))
    filters = {
        "marketplace": str(marketplace or "").strip().upper(),
        "sku": str(sku or "").strip(),
        "asin": str(asin or "").strip().upper(),
    }
    rows = _queue_rows(payload)
    rows = [
        row
        for row in rows
        if (not filters["marketplace"] or str(row.get("marketplace") or "").strip().upper() == filters["marketplace"])
        and (not filters["sku"] or str(row.get("sku") or "").strip() == filters["sku"])
        and (not filters["asin"] or str(row.get("asin") or "").strip().upper() == filters["asin"])
    ]
    if not rows:
        rows = _fallback_rows_from_payload(payload, filters)
    if not rows:
        rows = [
            {
                "marketplace": filters["marketplace"],
                "sku": filters["sku"],
                "asin": filters["asin"],
                "product_name": "",
                "product_url": _marketplace_product_url(filters["marketplace"], filters["asin"]),
            }
        ]
    row = rows[0]
    parsed = {
        "marketplace": filters["marketplace"],
        "title": title,
        "price": price,
        "price_currency_warning": _price_currency_warning(price, filters["marketplace"]),
        "rating": rating,
        "reviews": reviews,
        "coupon": coupon,
        "coupon_detail": coupon,
        "buy_box": buy_box,
        "delivery": location_note,
        "visible_location": location_note,
        "location_warning": _location_warning(location_note, filters["marketplace"]),
        "location_hard_failure": _location_hard_failure(location_note, filters["marketplace"]),
        "location_scope": _location_scope(location_note, filters["marketplace"]),
        "captcha_or_block": "否",
    }
    if parsed["price_currency_warning"]:
        parsed["price"] = ""
    result_row = _build_frontend_result_row(
        row,
        parsed,
        fetch_error="",
        fetch_method=method,
        location_note=location_note,
        search_payload=_default_search_payload(row, "never"),
        checked_at=checked_at or None,
    )
    if stability_total_attempts is not None:
        result_row["frontend_stability_total_attempts"] = stability_total_attempts
    if stability_success_count is not None:
        result_row["frontend_stability_success_count"] = stability_success_count
    if stability_failure_count is not None:
        result_row["frontend_stability_failure_count"] = stability_failure_count
    if stability_success_rate is not None:
        result_row["frontend_stability_success_rate"] = stability_success_rate
    if stability_passed is not None:
        result_row["frontend_stability_passed"] = stability_passed
    output = [result_row]
    results_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fallback_policy": "live_fetch -> retry -> last_success_cache -> manual_first_check",
        "items": _merged_items(output),
        "cache": _cache_items(output),
    }
    RESULTS_PATH.write_text(json.dumps(results_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_row


def check_frontend_queue(
    timeout: int = 12,
    sleep_seconds: float = 1.2,
    limit: int | None = None,
    dry_run: bool = False,
    method: str = "auto",
    retries: int = 3,
    search_policy: str = "always",
    marketplace: str = "",
    sku: str = "",
    asin: str = "",
    priority: str = "",
    reuse_browser: bool = False,
    cdp_endpoint: str = DEFAULT_CDP_ENDPOINT,
    cdp_attempts: int = 20,
    strict_live_pass: bool = False,
    only_stale: bool = False,
    require_competitor_samples: bool = False,
    progress_callback: Callable[[int, int, dict, str], None] | None = None,
) -> list[dict]:
    payload = json.loads(LATEST_ANALYSIS.read_text(encoding="utf-8"))
    rows = _queue_rows(payload)
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
            rows = _fallback_rows_from_payload(payload, filters)
    priority_filter = str(priority or "").strip().upper()
    if priority_filter:
        rows = [row for row in rows if str(row.get("priority") or "").strip().upper() == priority_filter]
    _, cache = _load_previous_frontend_state()
    if limit is not None:
        rows = rows[:limit]
    output: list[dict] = []
    method_key = (method or "").lower()
    today = _today_iso()
    should_skip_fresh = only_stale and method_key == "chrome-cdp" and cdp_attempts < 20 and not any(filters.values())
    browser_session = (
        FrontendBrowserSession(
            use_chrome=method_key in {"chrome", "chrome-persistent"},
            persistent=method_key == "chrome-persistent",
            apply_location=method_key != "chrome-persistent",
        )
        if reuse_browser and not dry_run and method_key in {"auto", "playwright", "chrome", "chrome-persistent"}
        else None
    )
    try:
        for index, row in enumerate(rows, start=1):
            if should_skip_fresh:
                fresh = _fresh_chrome_cdp_record_for(
                    row,
                    cache,
                    today,
                    require_competitor_samples=require_competitor_samples,
                )
                if fresh:
                    if progress_callback:
                        progress_callback(index, len(rows), row, "skip")
                    output.append(_record_from_fresh_skip(row, fresh))
                    continue
            if method_key == "chrome-cdp":
                if progress_callback:
                    progress_callback(index, len(rows), row, "refresh")
                cdp_row = _result_row_from_cdp_probe(
                    row,
                    endpoint=cdp_endpoint,
                    attempts=cdp_attempts,
                    sleep_seconds=sleep_seconds,
                    timeout=timeout,
                    search_policy=search_policy,
                )
                if str(cdp_row.get("frontend_check_status") or "") != "已自动检查" and not dry_run:
                    cached = _cached_record_for(row, cache)
                    if cached:
                        output.append(_record_from_cache(row, cached, str(cdp_row.get("frontend_last_error") or "Chrome CDP 探测失败")))
                    else:
                        output.append(_mark_pending_refresh(cdp_row))
                else:
                    output.append(_mark_live_refresh(cdp_row))
                continue
            if progress_callback:
                progress_callback(index, len(rows), row, "refresh")
            url = str(row.get("product_url") or "")
            parsed: dict[str, str] = {}
            fetch_error = ""
            search_error = ""
            location_note = ""
            fetch_method = method
            product_failure_signal = ""
            if dry_run:
                fetch_error = "dry-run 未访问 Amazon"
                product_failure_signal = fetch_error
            elif url:
                attempts = max(1, retries)
                for attempt in range(1, attempts + 1):
                    html, fetch_error, fetch_method, location_note = _fetch_html(
                        url,
                        timeout + max(attempt - 1, 0) * 5,
                        method=method,
                        marketplace=str(row.get("marketplace") or ""),
                        attempt=attempt,
                        browser_session=browser_session,
                    )
                    parsed = parse_amazon_frontend(html, marketplace=str(row.get("marketplace") or "")) if html else {}
                    if location_note:
                        parsed["location_note"] = location_note
                    _apply_location_basis(parsed, location_note, str(row.get("marketplace") or ""), allow_html_visible=bool(html))
                    product_failure_signal = _pick_frontend_failure_signal(
                        product_failure_signal,
                        _frontend_failure_signal(parsed, fetch_error, html_present=bool(html)),
                    )
                    if _status_from_parsed(parsed) == "已自动检查":
                        product_failure_signal = ""
                        break
                    time.sleep(max(sleep_seconds, 0))
                time.sleep(max(sleep_seconds, 0))
            else:
                fetch_error = "缺少 product_url"
                product_failure_signal = fetch_error
            status = "待前台检查" if dry_run else _status_from_parsed(parsed)
            search_keyword = str(row.get("frontend_core_keyword") or "").strip()
            search_url = str(row.get("frontend_search_url") or "") or _marketplace_search_url(
                str(row.get("marketplace") or ""), search_keyword
            )
            search_payload: dict[str, object] = {
                "frontend_search_keyword": search_keyword,
                "frontend_search_url": search_url,
                "frontend_search_status": "待前台检查" if search_url else "未配置核心词",
                "frontend_search_findings": "未配置核心词搜索页。",
                "frontend_competitor_count": 0,
                "frontend_competitors": [],
                "own_search_position": "",
            }
            should_check_search = _should_check_search_page(row, search_policy)
            if not dry_run and search_url and should_check_search:
                for attempt in range(1, max(1, retries) + 1):
                    parsed_search, search_error, search_parser = _parse_search_results(
                        search_url,
                        timeout + max(attempt - 1, 0) * 5,
                        method,
                        str(row.get("marketplace") or ""),
                        str(row.get("asin") or ""),
                        attempt=attempt,
                        browser_session=browser_session,
                    )
                    competitors = parsed_search.get("competitors", []) if isinstance(parsed_search, dict) else []
                    result_count = int(_parse_number_text(parsed_search.get("search_result_count"), decimal_allowed=False) or 0) if isinstance(parsed_search, dict) else 0
                    own_position = str(parsed_search.get("own_search_position") or "") if isinstance(parsed_search, dict) else ""
                    if competitors:
                        search_payload.update(
                            {
                                "frontend_search_status": "已自动检查",
                                "frontend_search_findings": f"核心词“{search_keyword}”搜索页读取成功；{_competitor_summary(competitors, own_position)}",
                                "frontend_competitor_count": len(competitors),
                                "frontend_competitors": competitors,
                                "own_search_position": own_position,
                                "frontend_search_result_count": result_count,
                                "frontend_search_partial_evidence": False,
                                "frontend_search_method": search_parser,
                            }
                        )
                        break
                    partial_summary = _search_partial_evidence_summary(parsed_search, search_keyword) if isinstance(parsed_search, dict) else ""
                    if partial_summary:
                        search_payload.update(
                            {
                                "frontend_search_status": "已读取部分结果",
                                "frontend_search_findings": partial_summary + "；未稳定解析前三竞品价格/评分，不能用于强诊断。",
                                "frontend_competitor_count": 0,
                                "frontend_competitors": [],
                                "own_search_position": own_position,
                                "frontend_search_result_count": result_count,
                                "frontend_search_partial_evidence": True,
                                "frontend_search_method": search_parser,
                            }
                        )
                        break
                    search_payload["frontend_search_findings"] = (
                        f"核心词“{search_keyword}”搜索页本次未稳定读取前三竞品。"
                        if search_error
                        else f"核心词“{search_keyword}”搜索页未稳定解析前三竞品。"
                    )
                    time.sleep(max(sleep_seconds, 0))
            elif search_url and not should_check_search:
                search_payload["frontend_search_status"] = "按广告信号跳过"
                search_payload["frontend_search_findings"] = "当前不是广告点击/转化异常触发，跳过搜索页前三竞品以降低浏览器和报告开销。"
            if status != "已自动检查" and not dry_run:
                cached = _cached_record_for(row, cache)
                if cached:
                    cached_record = _record_from_cache(row, cached, product_failure_signal or fetch_error, extra=search_payload)
                    output.append(cached_record)
                    continue
            checked_at = datetime.now().isoformat(timespec="seconds")
            data_date = checked_at.split("T", 1)[0]
            effective_location_note = _apply_location_basis(parsed, location_note, str(row.get("marketplace") or ""), allow_html_visible=bool(parsed))
            quality_payload = _frontend_quality_payload(
                parsed,
                {**row, "product_url": url},
                search_payload,
                product_failure_signal or fetch_error or parsed.get("price_currency_warning", ""),
                search_error,
                status=status,
                method=fetch_method if not dry_run else "dry-run",
                location_note=effective_location_note,
            )
            result_row = {
                    "marketplace": row.get("marketplace"),
                    "sku": row.get("sku"),
                    "asin": row.get("asin"),
                    "product_name": row.get("product_name"),
                    "product_url": url,
                    "frontend_check_status": status,
                    "frontend_findings": (
                        _findings(parsed, product_failure_signal or fetch_error, location_note=effective_location_note)
                        if status == "已自动检查"
                        else _findings(parsed, product_failure_signal or fetch_error, location_note=effective_location_note)
                    ),
                    "suspected_issue": _suspected_issue(parsed, str(row.get("suspected_issue") or ""), row),
                    "frontend_check_focus": row.get("frontend_check_focus"),
                    "questions_to_check": row.get("questions_to_check"),
                    "conservative_action": row.get("conservative_action"),
                    "recommended_next_step": row.get("recommended_next_step"),
                    "confirmed_status": row.get("confirmed_status") or "待确认",
                    "checked_at": checked_at,
                    "frontend_data_date": data_date if status == "已自动检查" else "",
                    "frontend_data_freshness": "今日读取" if status == "已自动检查" else "无可用前台数据",
                    "source": "auto_frontend_check",
                    "frontend_check_method": fetch_method if not dry_run else "dry-run",
                    "frontend_location_note": effective_location_note,
                    "frontend_location_verified": _location_verified(effective_location_note, str(row.get("marketplace") or "")),
                    "frontend_location_exact": _location_exact(effective_location_note, str(row.get("marketplace") or "")),
                    "frontend_location_scope": _location_scope(effective_location_note, str(row.get("marketplace") or "")),
                    "frontend_location_warning": parsed.get("location_warning", ""),
                    "frontend_last_error": (
                        _shorten(product_failure_signal or fetch_error or parsed.get("price_currency_warning", "") or parsed.get("location_warning", ""), limit=180)
                        if status != "已自动检查"
                        else ""
                    ),
                    **_front_structured_fields(parsed, location_note=effective_location_note),
                    **search_payload,
                    **quality_payload,
                }
            output.append(_mark_live_refresh(result_row) if status == "已自动检查" else _mark_pending_refresh(result_row))
            if _is_success_record(output[-1]):
                key = _record_key(output[-1])
                cache[key] = output[-1]
                cache[(key[0], "", key[2])] = output[-1]
    finally:
        if browser_session is not None:
            browser_session.close()
    if strict_live_pass:
        failed = [
            row
            for row in output
            if not (
                str(row.get("frontend_check_status") or "") == "已自动检查"
                and str(row.get("frontend_check_method") or "") == "chrome-cdp"
                and str(row.get("source") or "") == "auto_frontend_check"
                and not bool(row.get("frontend_cache_used"))
                and bool(row.get("frontend_stability_passed"))
                and float(row.get("frontend_stability_success_rate") or 0) >= 0.8
                and int(row.get("frontend_stability_total_attempts") or 0) >= 20
            )
        ]
        if failed:
            labels = ", ".join(
                f"{row.get('marketplace')} {row.get('asin')} {row.get('frontend_check_status')}"
                for row in failed[:5]
            )
            more = f" 等 {len(failed)} 个" if len(failed) > 5 else ""
            raise StrictLivePassError(f"严格实时前台验收未通过：{labels}{more}", output)
    return output


def _cache_items(rows: list[dict]) -> list[dict]:
    return result_state.cache_items(
        rows,
        RESULTS_PATH,
        is_success_record=_is_success_record,
        record_key=_record_key,
    )


def _merged_items(rows: list[dict]) -> list[dict]:
    return result_state.merged_items(
        rows,
        RESULTS_PATH,
        is_success_record=_is_success_record,
        record_key=_record_key,
    )


def _write_results_payload(rows: list[dict]) -> None:
    result_state.write_results_payload(
        rows,
        RESULTS_PATH,
        is_success_record=_is_success_record,
        record_key=_record_key,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatically inspect Amazon product frontend pages for queued products.")
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--sleep", type=float, default=1.2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--marketplace", default="", help="只检查指定 marketplace。")
    parser.add_argument("--sku", default="", help="只检查指定 SKU。")
    parser.add_argument("--asin", default="", help="只检查指定 ASIN。")
    parser.add_argument("--priority", default="", help="只检查指定优先级的前台队列行，例如 P0。")
    parser.add_argument("--retries", type=int, default=3, help="前台读取失败时的重试次数，默认 3 次。")
    parser.add_argument(
        "--method",
        choices=["auto", "chrome", "chrome-persistent", "chrome-cdp", "playwright", "urllib"],
        default="auto",
        help="auto 优先 Playwright，失败后回退 urllib；chrome-cdp 附着真实 Chrome CDP。cdp-attempts 小于20时用于日常实时刷新，达到20时用于稳定性验收。",
    )
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT, help="chrome-cdp 方法使用的真实 Chrome CDP 地址。")
    parser.add_argument("--cdp-attempts", type=int, default=1, help="chrome-cdp 尝试次数。日常刷新默认 1；稳定性验收显式传 20。")
    parser.add_argument(
        "--strict-live-pass",
        action="store_true",
        help="要求所有输出对象均为实时20次验收通过；缓存或未通过行会让命令返回非0。",
    )
    parser.add_argument(
        "--only-stale",
        action="store_true",
        help="日常刷新只补齐缺失或过期的前台证据；已有今日 chrome-cdp 成功证据的队列行直接跳过。",
    )
    parser.add_argument(
        "--require-competitor-samples",
        action="store_true",
        help="配合 --only-stale 使用：已有今日产品页证据但竞品样本少于2个时仍刷新搜索页竞品样本。",
    )
    parser.add_argument(
        "--search-policy",
        choices=["always", "ad-driven", "never"],
        default="always",
        help="搜索页前三竞品检查策略：always 全查；ad-driven 仅广告异常触发；never 只查 Listing 前台。",
    )
    parser.add_argument(
        "--reuse-browser-session",
        action="store_true",
        help="在整批前台检查中复用同一个浏览器会话，减少反复启动 Chromium 带来的失败率。",
    )
    parser.add_argument(
        "--import-manual-evidence",
        action="store_true",
        help="导入已由真实 Chrome/人工核查得到的单品前台证据，不访问 Amazon。",
    )
    parser.add_argument("--manual-title", default="")
    parser.add_argument("--manual-price", default="")
    parser.add_argument("--manual-rating", default="")
    parser.add_argument("--manual-reviews", default="")
    parser.add_argument("--manual-location", default="")
    parser.add_argument("--manual-coupon", default="待确认")
    parser.add_argument("--manual-buy-box", default="识别到购买按钮")
    parser.add_argument("--manual-method", default="chrome-extension")
    parser.add_argument("--manual-stability-total-attempts", type=int, default=None)
    parser.add_argument("--manual-stability-success-count", type=int, default=None)
    parser.add_argument("--manual-stability-failure-count", type=int, default=None)
    parser.add_argument("--manual-stability-success-rate", type=float, default=None)
    parser.add_argument("--manual-stability-passed", action="store_true")
    args = parser.parse_args()

    if not LATEST_ANALYSIS.exists():
        raise SystemExit(f"missing {LATEST_ANALYSIS}; run main.py --marketplace ALL first")
    if args.import_manual_evidence:
        row = import_manual_frontend_evidence(
            marketplace=args.marketplace,
            sku=args.sku,
            asin=args.asin,
            title=args.manual_title,
            price=args.manual_price,
            rating=args.manual_rating,
            reviews=args.manual_reviews,
            location_note=args.manual_location,
            coupon=args.manual_coupon,
            buy_box=args.manual_buy_box,
            method=args.manual_method,
            stability_total_attempts=args.manual_stability_total_attempts,
            stability_success_count=args.manual_stability_success_count,
            stability_failure_count=args.manual_stability_failure_count,
            stability_success_rate=args.manual_stability_success_rate,
            stability_passed=(True if args.manual_stability_passed else None),
        )
        print(f"[frontend] wrote {RESULTS_PATH}")
        print(f"[frontend] imported manual evidence for {row.get('marketplace')} {row.get('asin')}: {row.get('frontend_check_status')}")
        return 0
    strict_error = ""
    try:
        rows = check_frontend_queue(
            timeout=args.timeout,
            sleep_seconds=args.sleep,
            limit=args.limit,
            dry_run=args.dry_run,
            method=args.method,
            retries=args.retries,
            search_policy=args.search_policy,
            marketplace=args.marketplace,
            sku=args.sku,
            asin=args.asin,
            priority=args.priority,
            reuse_browser=args.reuse_browser_session,
            cdp_endpoint=args.cdp_endpoint,
            cdp_attempts=args.cdp_attempts,
            strict_live_pass=args.strict_live_pass,
            only_stale=args.only_stale,
            require_competitor_samples=args.require_competitor_samples,
            progress_callback=_print_progress,
        )
    except StrictLivePassError as exc:
        rows = exc.rows
        strict_error = str(exc)
    except RuntimeError as exc:
        print(f"[frontend] {exc}")
        return 1
    if not args.dry_run:
        _write_results_payload(rows)
        print(f"[frontend] wrote {RESULTS_PATH}")
    summary = _refresh_summary(rows)
    print(
        "[frontend] checked "
        f"{len(rows)} queued products; live={summary['frontend_refresh_live_checked']} "
        f"skipped={summary['frontend_refresh_skipped']} "
        f"cache={summary['frontend_refresh_cache_used']} "
        f"failed={summary['frontend_refresh_failed']}"
    )
    for row in rows:
        print(f"- {row.get('marketplace')} {row.get('asin')} {row.get('frontend_check_status')}: {row.get('frontend_findings')}")
    if strict_error:
        print(f"[frontend] {strict_error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
