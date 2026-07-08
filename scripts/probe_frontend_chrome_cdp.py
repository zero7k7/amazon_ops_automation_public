from __future__ import annotations

import argparse
import contextlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from validate_frontend_stability import build_stability_report
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.probe_frontend_chrome_cdp
    from scripts.validate_frontend_stability import build_stability_report


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
LOCATION_CONFIG = ROOT / "config" / "frontend_locations.json"
DEFAULT_ATTEMPTS_PATH = OUTPUT_DIR / "frontend_stability_attempts_live.json"
DEFAULT_REPORT_PATH = OUTPUT_DIR / "frontend_stability_report_live.json"
DEFAULT_LOCATIONS = {
    "UK": {"postcode": "SW1A 1AA", "locale": "en-GB", "timezone": "Europe/London"},
    "US": {"postcode": "10001", "locale": "en-US", "timezone": "America/New_York"},
    "DE": {"postcode": "10115", "locale": "de-DE", "timezone": "Europe/Berlin"},
}
PRODUCT_URLS = {
    "UK": "https://www.amazon.co.uk/dp/{asin}?th=1",
    "US": "https://www.amazon.com/dp/{asin}",
    "DE": "https://www.amazon.de/dp/{asin}",
}


EXTRACT_FRONTEND_JS = """() => {
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const firstText = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const text = clean(node && (node.innerText || node.textContent));
      if (text) return text;
    }
    return '';
  };
  const price = firstText([
    '#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen',
    '#corePrice_feature_div .priceToPay .a-offscreen',
    '#apex_desktop .apexPriceToPay .a-offscreen',
    '#apex_desktop .a-price .a-offscreen',
    '.a-price .a-offscreen',
    '#priceblock_ourprice',
    '#priceblock_dealprice',
    '#price_inside_buybox'
  ]);
  const bodyText = clean(document.body && document.body.innerText);
  const captcha = /captcha|robot check|automated access|enter the characters/i.test(bodyText);
  const continueShopping = /click the button below to continue shopping|continue shopping/i.test(bodyText)
    && !document.querySelector('#productTitle')
    && !price;
  return {
    title: firstText(['#productTitle']) || clean(document.title),
    price,
    rating: firstText(['#acrPopover .a-icon-alt', '.reviewCountTextLinkedHistogram .a-icon-alt', '.a-icon-alt']),
    reviews: firstText(['#acrCustomerReviewText']),
    location: firstText(['#glow-ingress-line2', '#contextualIngressPtLabel_deliveryShortLine']),
    buy_box: document.querySelector('#add-to-cart-button, #buy-now-button') ? '识别到购买按钮' : '',
    captcha_or_block: captcha,
    continue_shopping: continueShopping,
    url: location.href
  };
}"""


CLICK_CONTINUE_SHOPPING_JS = """() => {
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const bodyText = clean(document.body && document.body.innerText);
  if (!/click the button below to continue shopping|continue shopping/i.test(bodyText)) return false;
  const candidates = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a'));
  for (const node of candidates) {
    const label = clean(node.innerText || node.textContent || node.value || node.getAttribute('aria-label'));
    if (/^continue shopping$/i.test(label) || /continue shopping/i.test(label)) {
      node.click();
      return true;
    }
  }
  return false;
}"""

DISMISS_COOKIE_BANNER_JS = """() => {
  const node = document.querySelector('#sp-cc-rejectall-link, #sp-cc-accept');
  if (!node) return false;
  node.click();
  return true;
}"""


def _load_locations() -> dict[str, dict[str, str]]:
    locations = {key: dict(value) for key, value in DEFAULT_LOCATIONS.items()}
    if not LOCATION_CONFIG.exists():
        return locations
    try:
        raw = json.loads(LOCATION_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return locations
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                market = str(key).strip().upper()
                locations[market] = {**locations.get(market, {}), **{str(k): str(v) for k, v in value.items()}}
    return locations


def _json_url(url: str, timeout: int = 3) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _cdp_available(endpoint: str) -> bool:
    try:
        payload = _json_url(f"{endpoint.rstrip('/')}/json/version")
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(payload.get("webSocketDebuggerUrl"))


def _marketplace_url(marketplace: str, asin: str) -> str:
    marketplace = str(marketplace or "").strip().upper()
    template = PRODUCT_URLS.get(marketplace)
    if not template:
        raise ValueError(f"unsupported marketplace: {marketplace}")
    return template.format(asin=str(asin or "").strip().upper())


def _clean_price(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    match = re.search(r"([£$€]\s*[0-9][0-9.,]*)", text)
    return match.group(1) if match else text


def _verified_location_setup(note: object, marketplace: str) -> bool:
    text = re.sub(r"\s+", " ", str(note or "")).strip().lower()
    if not text:
        return False
    marketplace_key = str(marketplace or "").strip().upper()
    postcode = _load_locations().get(marketplace_key, {}).get("postcode", "")
    postcode_compact = re.sub(r"\s+", "", str(postcode or "").lower())
    text_compact = re.sub(r"\s+", "", text.replace("\u200c", ""))
    return "已设置" in str(note or "") or bool(postcode_compact and postcode_compact[:5] in text_compact)


def _needs_location_retry(note: object, marketplace: str) -> bool:
    text = re.sub(r"\s+", " ", str(note or "")).strip().lower()
    if not text:
        return True
    if _verified_location_setup(note, marketplace):
        return False
    return text in {"update location", "update your location"} or "未确认" in str(note or "")


def _apply_frontend_payload(row: dict[str, Any], payload: Any) -> bool:
    if not isinstance(payload, dict):
        row["error"] = "empty evaluate payload"
        return False
    payload_location = payload.get("location") or ""
    setup_note = row.get("location_setup_note") or ""
    setup_verified = _verified_location_setup(setup_note, str(row.get("marketplace") or ""))
    location = setup_note if setup_verified else payload_location
    row.update(
        {
            "title": payload.get("title") or "",
            "price": _clean_price(payload.get("price") or ""),
            "rating": payload.get("rating") or "",
            "reviews": payload.get("reviews") or "",
            "location": location,
            "visible_location": payload_location,
            "buy_box": payload.get("buy_box") or "",
            "captcha_or_block": bool(payload.get("captcha_or_block")),
            "continue_shopping": bool(payload.get("continue_shopping")),
            "url": payload.get("url") or "",
        }
    )
    if not setup_verified:
        row.pop("location_setup_note", None)
    row["success"] = bool(row.get("title") and row.get("price") and row.get("location")) and not bool(
        row.get("captcha_or_block") or row.get("continue_shopping")
    )
    return True


def _wait_for_readable_page(page: Any, timeout_error: type[Exception]) -> None:
    with contextlib.suppress(timeout_error):
        page.wait_for_load_state("domcontentloaded", timeout=2000)
    page.wait_for_timeout(250)


def _click_continue_shopping_if_present(page: Any, timeout_error: type[Exception]) -> bool:
    try:
        clicked = bool(page.evaluate(CLICK_CONTINUE_SHOPPING_JS))
    except Exception:
        return False
    if not clicked:
        return False
    with contextlib.suppress(timeout_error):
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    _wait_for_readable_page(page, timeout_error)
    return True


def _dismiss_cookie_banner_if_present(page: Any, timeout_error: type[Exception]) -> bool:
    try:
        clicked = bool(page.evaluate(DISMISS_COOKIE_BANNER_JS))
    except Exception:
        return False
    if not clicked:
        return False
    _wait_for_readable_page(page, timeout_error)
    return True


def _read_frontend_payload(page: Any, timeout_error: type[Exception]) -> dict[str, Any]:
    last_payload: dict[str, Any] = {}
    for retry_index in range(3):
        try:
            payload = page.evaluate(EXTRACT_FRONTEND_JS)
        except Exception:
            if retry_index == 2:
                raise
            page.wait_for_timeout(1000)
            continue
        if isinstance(payload, dict):
            last_payload = payload
            has_product_fields = bool(payload.get("price") and payload.get("title"))
            if has_product_fields or retry_index == 2:
                return payload
        page.wait_for_timeout(500)
        with contextlib.suppress(timeout_error):
            page.wait_for_load_state("domcontentloaded", timeout=1000)
    return last_payload


def _visible_delivery_location(page: Any) -> str:
    selectors = [
        "#glow-ingress-line2",
        "#contextualIngressPtLabel_deliveryShortLine",
        "#nav-global-location-popover-link",
    ]
    for selector in selectors:
        with contextlib.suppress(Exception):
            text = page.locator(selector).first.inner_text(timeout=2500)
            cleaned = re.sub(r"\s+", " ", str(text or "").replace("\u200c", "")).strip()
            cleaned = re.sub(r"^Deliver to\s+", "", cleaned, flags=re.I).strip()
            if cleaned:
                return cleaned
    return ""


def _open_location_popover(page: Any) -> bool:
    selectors = [
        "#nav-global-location-popover-link",
        "#contextualIngressPtLink",
        "#glow-ingress-block",
    ]
    for selector in selectors:
        with contextlib.suppress(Exception):
            page.locator(selector).first.click(timeout=3000, force=True)
            page.wait_for_timeout(1200)
            if page.locator("#GLUXZipUpdateInput").first.is_visible(timeout=1500):
                return True
    with contextlib.suppress(Exception):
        opened = bool(
            page.evaluate(
                """() => {
                  const candidates = [
                    '#nav-global-location-popover-link',
                    '#contextualIngressPtLink',
                    '#glow-ingress-block',
                    '#nav-global-location-data-modal-action'
                  ];
                  for (const selector of candidates) {
                    const node = document.querySelector(selector);
                    if (node) {
                      node.click();
                      return true;
                    }
                  }
                  return false;
                }"""
            )
        )
        if opened:
            page.wait_for_timeout(700)
            if page.locator("#GLUXZipUpdateInput").first.is_visible(timeout=2000):
                return True
    return False


def _apply_delivery_location(page: Any, marketplace: str, timeout_error: type[Exception]) -> str:
    marketplace_key = str(marketplace or "").strip().upper()
    location = _load_locations().get(marketplace_key, {})
    postcode = str(location.get("postcode") or "").strip()
    if not postcode:
        return ""
    try:
        if not page.locator("#GLUXZipUpdateInput").first.is_visible(timeout=1000):
            _open_location_popover(page)
        zip_input = page.locator("#GLUXZipUpdateInput").first
        zip_input.fill(postcode, timeout=8000)
        page.locator("#GLUXZipUpdate").first.click(timeout=5000)
        with contextlib.suppress(Exception):
            page.locator("#GLUXConfirmClose, input[name='glowDoneButton']").first.click(timeout=5000)
        with contextlib.suppress(Exception):
            page.locator(".a-popover-footer input[type='submit']").first.click(timeout=5000)
        page.wait_for_timeout(800)
        with contextlib.suppress(timeout_error):
            page.reload(wait_until="domcontentloaded", timeout=20000)
        _wait_for_readable_page(page, timeout_error)
        visible = _visible_delivery_location(page)
        if visible and _verified_location_setup(visible, marketplace_key):
            return f"{marketplace_key} {postcode} 已设置"
        if visible:
            return visible
        return f"{marketplace_key} {postcode} 未确认：未读取到页面顶部配送地区"
    except Exception as exc:
        visible = _visible_delivery_location(page)
        if visible:
            return visible
        return f"{marketplace_key} {postcode} 未确认：{exc}"


def _prepare_product_page(page: Any, url: str, marketplace: str, timeout_seconds: int, timeout_error: type[Exception]) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
    _wait_for_readable_page(page, timeout_error)
    payload = page.evaluate(EXTRACT_FRONTEND_JS)
    if isinstance(payload, dict) and payload.get("continue_shopping"):
        _click_continue_shopping_if_present(page, timeout_error)
    _dismiss_cookie_banner_if_present(page, timeout_error)
    return _apply_delivery_location(page, marketplace, timeout_error)


def _warm_location_setup(
    page: Any,
    url: str,
    marketplace: str,
    timeout_seconds: int,
    timeout_error: type[Exception],
    max_rounds: int = 3,
) -> str:
    location_setup_note = ""
    for _ in range(max(1, max_rounds)):
        with contextlib.suppress(Exception):
            note = _prepare_product_page(page, url, marketplace, timeout_seconds, timeout_error)
            if note:
                location_setup_note = note
            if _verified_location_setup(location_setup_note, marketplace):
                return location_setup_note
        with contextlib.suppress(Exception):
            page.reload(wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        _wait_for_readable_page(page, timeout_error)
    return location_setup_note


def run_chrome_cdp_probe(
    *,
    endpoint: str,
    marketplace: str,
    asin: str,
    attempts: int,
    sleep_seconds: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not _cdp_available(endpoint):
        raise RuntimeError(f"Chrome CDP endpoint is not available: {endpoint}")
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if not _marketplace_url(marketplace, asin):
        raise ValueError("invalid marketplace or asin")
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(f"Playwright is not available: {exc}") from exc

    rows: list[dict[str, Any]] = []
    url = _marketplace_url(marketplace, asin)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            warm_rounds = 1 if attempts < 20 else 3
            location_setup_note = _warm_location_setup(
                page,
                url,
                marketplace,
                timeout_seconds,
                PlaywrightTimeoutError,
                max_rounds=warm_rounds,
            )
            if not _verified_location_setup(location_setup_note, marketplace):
                location_setup_note = ""
            for index in range(1, attempts + 1):
                started = datetime.now().isoformat(timespec="seconds")
                row: dict[str, Any] = {
                    "attempt": index,
                    "marketplace": marketplace.upper(),
                    "asin": asin.upper(),
                    "method": "chrome-cdp",
                    "checked_at": started,
                    "success": False,
                }
                if location_setup_note:
                    row["location_setup_note"] = location_setup_note
                try:
                    navigation_error = ""
                    try:
                        with contextlib.suppress(Exception):
                            page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                        page.goto(url, wait_until="commit", timeout=timeout_seconds * 1000)
                    except PlaywrightTimeoutError as exc:
                        navigation_error = str(exc)
                        with contextlib.suppress(Exception):
                            page.evaluate("() => window.stop()")
                    if navigation_error:
                        row["navigation_warning"] = navigation_error
                    _wait_for_readable_page(page, PlaywrightTimeoutError)
                    _dismiss_cookie_banner_if_present(page, PlaywrightTimeoutError)
                    payload = _read_frontend_payload(page, PlaywrightTimeoutError)
                    if isinstance(payload, dict) and payload.get("continue_shopping"):
                        row["continue_shopping_page"] = True
                        if _click_continue_shopping_if_present(page, PlaywrightTimeoutError):
                            row["continue_shopping_dismissed"] = True
                            payload = _read_frontend_payload(page, PlaywrightTimeoutError)
                    _apply_frontend_payload(row, payload)
                    if _needs_location_retry(row.get("location") or row.get("visible_location"), marketplace):
                        retry_note = _apply_delivery_location(page, marketplace, PlaywrightTimeoutError)
                        if retry_note:
                            location_setup_note = retry_note if _verified_location_setup(retry_note, marketplace) else ""
                            row["location_setup_note"] = retry_note
                            payload = _read_frontend_payload(page, PlaywrightTimeoutError)
                            _apply_frontend_payload(row, payload)
                except Exception as exc:
                    row["error"] = str(exc)
                rows.append(row)
                if index < attempts:
                    time.sleep(max(sleep_seconds, 0))
        finally:
            browser.close()
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "attempts": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Amazon frontend stability through an existing real Chrome CDP session.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--marketplace", required=True)
    parser.add_argument("--asin", required=True)
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--attempts-output", default=str(DEFAULT_ATTEMPTS_PATH))
    parser.add_argument("--report-output", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    payload = run_chrome_cdp_probe(
        endpoint=args.endpoint,
        marketplace=args.marketplace,
        asin=args.asin,
        attempts=args.attempts,
        sleep_seconds=args.sleep,
        timeout_seconds=args.timeout,
    )
    report = build_stability_report(
        payload,
        marketplace=args.marketplace,
        asin=args.asin,
        min_attempts=20,
        max_failures=4,
        min_success_rate=0.8,
    )
    attempts_output = Path(args.attempts_output)
    report_output = Path(args.report_output)
    attempts_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    attempts_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[chrome-cdp-probe] {report['success_count']}/{report['total_attempts']} "
        f"success, failures={report['failure_count']}, passed={report['passed']}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
