from __future__ import annotations

import argparse
import contextlib
import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from run_frontend_checks import DEFAULT_LOCATIONS, USER_AGENT, _apply_delivery_location, _load_locations
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.sync_frontend_prices
    from scripts.run_frontend_checks import DEFAULT_LOCATIONS, USER_AGENT, _apply_delivery_location, _load_locations


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "product_cost_config.xlsx"
TARGETS_PATH = ROOT / "data" / "output" / "price_check_targets.json"
RESULTS_PATH = ROOT / "data" / "output" / "current_browser_price_check.json"
SUMMARY_PATH = ROOT / "data" / "output" / "current_browser_price_check_summary.md"
LATEST_ANALYSIS = ROOT / "data" / "output" / "latest_analysis.json"

MARKETPLACE_DOMAIN = {
    "UK": "www.amazon.co.uk",
    "US": "www.amazon.com",
    "DE": "www.amazon.de",
}
EXPECTED_SYMBOL = {"UK": "£", "US": "$", "DE": "€"}
DEFAULT_CURRENCY = {"UK": "GBP", "US": "USD", "DE": "EUR"}
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
SCALING_FEE_COLUMNS = [
    "referral_fee",
    "digital_tax",
    "vat",
    "storage_fee_estimate",
    "return_fee_estimate",
    "ad_fee_10pct",
]
TARGET_ACOS_BREAK_EVEN_FACTOR = 0.50
TARGET_ACOS_MAX = 0.30


PRICE_EXTRACTOR_JS = """() => {
  const q = (sel) => document.querySelector(sel);
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const title = clean(q('#productTitle')?.innerText || document.title);
  const priceNodes = Array.from(document.querySelectorAll('.a-price')).map((el) => ({
    cls: el.className || '',
    text: clean(el.querySelector('.a-offscreen')?.textContent || el.innerText || el.textContent || ''),
  })).filter((item) => item.text && /[$£€]/.test(item.text));
  let primary = '';
  const primaryNode = priceNodes.find((item) =>
    /priceToPay|pricetopay|price-to-pay/i.test(item.cls) &&
    !/perunit|basis|text-price/i.test(item.cls)
  );
  if (primaryNode) primary = primaryNode.text;
  if (!primary) {
    const direct = [
      '#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen',
      '#corePrice_feature_div .priceToPay .a-offscreen',
      '#apex_desktop .apex-pricetopay-value .a-offscreen',
      '#priceblock_ourprice',
      '#priceblock_dealprice',
      '#price_inside_buybox',
    ];
    for (const selector of direct) {
      const node = q(selector);
      const text = clean(node?.innerText || node?.textContent);
      if (text && /[$£€]/.test(text)) {
        primary = text;
        break;
      }
    }
  }
  const couponCandidates = [];
  document.querySelectorAll('[id*=coupon], [class*=coupon], label, .promoPriceBlockMessage, .savingPriceOverride').forEach((el) => {
    const text = clean(el.innerText || el.textContent || '');
    if (
      text &&
      /(coupon|voucher|save|spar|rabatt|gutschein|apply|with)/i.test(text) &&
      text.length < 220 &&
      !couponCandidates.includes(text)
    ) {
      couponCandidates.push(text);
    }
  });
  const delivery = clean(
    q('#contextualIngressPtLabel_deliveryShortLine')?.innerText ||
    q('#glow-ingress-line2')?.innerText ||
    q('#mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE')?.innerText
  );
  const availability = clean(q('#availability')?.innerText);
  const buyBox = Boolean(q('#add-to-cart-button') || q('#buy-now-button'));
  const body = document.body.innerText || '';
  const captcha = /captcha|robot check|Enter the characters/i.test(body);
  return {
    title,
    primary,
    priceNodes: priceNodes.slice(0, 8),
    couponCandidates: couponCandidates.slice(0, 4),
    delivery,
    availability,
    buyBox,
    captcha,
    url: location.href,
  };
}"""


def _load_cost_config(path: Path = CONFIG_PATH) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name="product_cost_config")


def _load_ad_flagged_keys(path: Path = LATEST_ANALYSIS) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    keys: set[tuple[str, str, str]] = set()
    for result in payload.get("marketplace_results", []) if isinstance(payload, dict) else []:
        view = result.get("report_view_snapshot", {}) if isinstance(result, dict) else {}
        for row in view.get("frontend_check_queue_rows", []) or []:
            if not isinstance(row, dict):
                continue
            marketplace = str(row.get("marketplace") or "").strip().upper()
            sku = str(row.get("sku") or "").strip()
            asin = str(row.get("asin") or "").strip().upper()
            if marketplace and asin:
                keys.add((marketplace, sku, asin))
                keys.add((marketplace, "", asin))
    return keys


def _build_targets(cost_config: pd.DataFrame, scope: str = "all") -> list[dict[str, Any]]:
    flagged = _load_ad_flagged_keys() if scope == "ad-flagged" else set()
    targets: list[dict[str, Any]] = []
    for _, row in cost_config.iterrows():
        marketplace = str(row.get("marketplace") or "").strip().upper()
        asin = str(row.get("asin") or "").strip()
        sku = str(row.get("sku") or "").strip()
        domain = MARKETPLACE_DOMAIN.get(marketplace)
        if not domain or not asin:
            continue
        if flagged and (marketplace, sku, asin.upper()) not in flagged and (marketplace, "", asin.upper()) not in flagged:
            continue
        targets.append(
            {
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": str(row.get("product_name") or "").strip(),
                "config_price": _to_float(row.get("selling_price")),
                "url": f"https://{domain}/dp/{asin}",
            }
        )
    return targets


def _parse_money(value: Any) -> tuple[str, float] | None:
    text = str(value or "").replace("\xa0", " ").strip()
    upper = text.upper()
    if not text or any(marker in upper for marker in BLOCKED_PRICE_CURRENCY_MARKERS):
        return None
    match = re.search(r"([$£€])\s*([0-9]+(?:[.,][0-9]{2})?)", text)
    if match:
        return match.group(1), float(match.group(2).replace(",", "."))
    match = re.search(r"([0-9]+(?:[.,][0-9]{2})?)\s*([$£€])", text)
    if match:
        return match.group(2), float(match.group(1).replace(",", "."))
    return None


def _to_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    top = _to_float(numerator)
    bottom = _to_float(denominator)
    if top is None or bottom in (None, 0):
        return None
    return top / bottom


def _price_note(item: dict[str, Any]) -> str:
    note = str(item.get("coupon_text") or "").strip()
    if note.lower() == "transparency":
        note = "未读到 Coupon/优惠券"
    if item.get("status") == "currency_mismatch":
        note = str(item.get("currency_note") or "币种不匹配，未反写")
    if item.get("status") == "price_not_found":
        note = "未稳定读到主售价"
    return note


def _write_summary(payload: dict[str, Any], path: Path = SUMMARY_PATH) -> None:
    lines = [
        "|站点|SKU|ASIN|商品|配置价|浏览器前台价|差异|Coupon/备注|",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for item in payload.get("items", []):
        parsed = _parse_money(item.get("frontend_price"))
        diff = ""
        if parsed and item.get("config_price") is not None:
            diff = f"{parsed[1] - float(item['config_price']):+.2f}"
        lines.append(
            "|{marketplace}|{sku}|{asin}|{product_name}|{config_price}|{frontend_price}|{diff}|{note}|".format(
                marketplace=item.get("marketplace", ""),
                sku=item.get("sku", ""),
                asin=item.get("asin", ""),
                product_name=item.get("product_name", ""),
                config_price="" if item.get("config_price") is None else f"{float(item['config_price']):.2f}",
                frontend_price=item.get("frontend_price") or "未读到",
                diff=diff,
                note=_price_note(item)[:90],
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def check_frontend_prices(method: str = "chrome", timeout: int = 30, sleep: float = 1.2, scope: str = "all") -> dict[str, Any]:
    targets = _build_targets(_load_cost_config(), scope=scope)
    TARGETS_PATH.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")
    locations = _load_locations()
    results: list[dict[str, Any]] = []

    if not targets:
        payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "scope": scope, "items": []}
        RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_summary(payload)
        return payload

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        if method == "chrome":
            launch_options["channel"] = "chrome"
        browser = playwright.chromium.launch(**launch_options)
        contexts: dict[str, Any] = {}
        pages: dict[str, Any] = {}
        try:
            for marketplace in sorted({item["marketplace"] for item in targets}):
                location = locations.get(marketplace, DEFAULT_LOCATIONS.get(marketplace, {}))
                contexts[marketplace] = browser.new_context(
                    user_agent=USER_AGENT,
                    locale=location.get("locale") or "en-GB",
                    timezone_id=location.get("timezone") or "Europe/London",
                    viewport={"width": 1365, "height": 1600},
                )
                pages[marketplace] = contexts[marketplace].new_page()

            for item in targets:
                marketplace = item["marketplace"]
                page = pages[marketplace]
                location = locations.get(marketplace, DEFAULT_LOCATIONS.get(marketplace, {}))
                result = {**item, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "ok"}
                try:
                    page.goto(item["url"], wait_until="domcontentloaded", timeout=max(timeout, 1) * 1000)
                    with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                        page.wait_for_load_state("networkidle", timeout=5000)
                    result["location_note"] = _apply_delivery_location(page, marketplace, location.get("postcode", ""))
                    page.wait_for_timeout(int(max(sleep, 0) * 1000))
                    page_data = page.evaluate(PRICE_EXTRACTOR_JS)
                    result.update(page_data)
                    result["frontend_price"] = page_data.get("primary") or ""
                    result["coupon_text"] = (page_data.get("couponCandidates") or [""])[0]
                    parsed = _parse_money(result["frontend_price"])
                    expected_symbol = EXPECTED_SYMBOL.get(marketplace)
                    if page_data.get("captcha"):
                        result["status"] = "captcha_or_blocked"
                    elif not parsed:
                        result["status"] = "price_not_found"
                    elif expected_symbol and parsed[0] != expected_symbol:
                        result["status"] = "currency_mismatch"
                        result["currency_note"] = f"期望 {expected_symbol}，实际 {result['frontend_price']}，未反写"
                    else:
                        result["frontend_price_value"] = parsed[1]
                except Exception as exc:
                    result["status"] = "error"
                    result["error"] = str(exc)[:500]
                results.append(result)
                print(
                    item["marketplace"],
                    item["asin"],
                    result.get("status"),
                    result.get("frontend_price", ""),
                    flush=True,
                )
        finally:
            for context in contexts.values():
                with contextlib.suppress(Exception):
                    context.close()
            browser.close()

    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "scope": scope, "items": results}
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary(payload)
    return payload


def apply_frontend_prices(results_path: Path = RESULTS_PATH, config_path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    if not results_path.exists():
        raise FileNotFoundError(f"缺少前台核价结果: {results_path}")
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    results = {
        (str(item.get("marketplace") or "").upper(), str(item.get("sku") or ""), str(item.get("asin") or "")): item
        for item in payload.get("items", [])
    }
    workbook = pd.ExcelFile(config_path)
    sheets = {sheet: pd.read_excel(workbook, sheet_name=sheet) for sheet in workbook.sheet_names}
    frame = sheets.get("product_cost_config")
    if frame is None:
        raise ValueError("product_cost_config.xlsx 缺少 product_cost_config sheet")

    updates: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        key = (
            str(row.get("marketplace") or "").strip().upper(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip(),
        )
        item = results.get(key)
        if not item or item.get("status") != "ok":
            continue
        parsed = _parse_money(item.get("frontend_price"))
        if not parsed:
            continue
        new_price = parsed[1]
        old_price = _to_float(row.get("selling_price"))
        if old_price is None or abs(new_price - old_price) < 0.005:
            continue

        updates.append(
            {
                "marketplace": key[0],
                "sku": key[1],
                "asin": key[2],
                "product_name": row.get("product_name"),
                "old_price": old_price,
                "new_price": new_price,
                "frontend_price": item.get("frontend_price"),
            }
        )
        frame.at[idx, "selling_price"] = new_price
        for column in SCALING_FEE_COLUMNS:
            if column in frame.columns:
                ratio = _safe_ratio(row.get(column), old_price)
                if ratio is not None:
                    frame.at[idx, column] = new_price * ratio
        _recalculate_row(frame, idx)

    sheets["product_cost_config"] = frame
    if "汇总" in sheets:
        summary = sheets["汇总"].copy()
        extra = pd.DataFrame(
            [
                ["前台价反写时间", time.strftime("%Y-%m-%d %H:%M")],
                ["前台价反写行数", len(updates)],
                ["前台价结果文件", str(results_path)],
            ],
            columns=list(summary.columns[:2]) if len(summary.columns) >= 2 else ["成本表处理结果", "Unnamed: 1"],
        )
        sheets["汇总"] = pd.concat([summary, extra], ignore_index=True)

    with pd.ExcelWriter(config_path, engine="openpyxl") as writer:
        for sheet_name, sheet_frame in sheets.items():
            sheet_frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return updates


def _recalculate_row(frame: pd.DataFrame, idx: int) -> None:
    def value(column: str) -> float:
        return _to_float(frame.at[idx, column]) or 0.0 if column in frame.columns else 0.0

    if "purchase_cost_local" in frame.columns and "purchase_cost_rmb" in frame.columns and "exchange_rate" in frame.columns:
        exchange_rate = value("exchange_rate")
        if exchange_rate:
            frame.at[idx, "purchase_cost_local"] = value("purchase_cost_rmb") / exchange_rate
            frame.at[idx, "first_leg_cost_local"] = value("first_leg_cost_rmb") / exchange_rate

    if "amazon_fees_excl_ads" in frame.columns:
        frame.at[idx, "amazon_fees_excl_ads"] = sum(value(col) for col in ["referral_fee", "digital_tax", "vat", "storage_fee_estimate", "return_fee_estimate", "fba_fee"])
    if "landed_cost_excl_amazon" in frame.columns:
        frame.at[idx, "landed_cost_excl_amazon"] = sum(value(col) for col in ["purchase_cost_local", "first_leg_cost_local", "packaging_cost_local_input"])
    if "total_cost_before_ads" in frame.columns:
        frame.at[idx, "total_cost_before_ads"] = value("amazon_fees_excl_ads") + value("landed_cost_excl_amazon")
    if "profit_before_ads" in frame.columns:
        frame.at[idx, "profit_before_ads"] = value("selling_price") - value("total_cost_before_ads")
    if "break_even_acos" in frame.columns:
        selling_price = value("selling_price")
        frame.at[idx, "break_even_acos"] = value("profit_before_ads") / selling_price if selling_price else 0.0
    if "suggested_target_acos" in frame.columns:
        frame.at[idx, "suggested_target_acos"] = safe_target_acos_from_break_even(value("break_even_acos"))
    if "profit_after_10pct_ads" in frame.columns:
        frame.at[idx, "profit_after_10pct_ads"] = value("profit_before_ads") - value("ad_fee_10pct")
    if "profit_margin_after_10pct_ads" in frame.columns:
        selling_price = value("selling_price")
        frame.at[idx, "profit_margin_after_10pct_ads"] = value("profit_after_10pct_ads") / selling_price if selling_price else 0.0
    if "roi_after_10pct_ads" in frame.columns:
        denominator = value("total_cost_before_ads") + value("ad_fee_10pct")
        frame.at[idx, "roi_after_10pct_ads"] = value("profit_after_10pct_ads") / denominator if denominator else 0.0


def safe_target_acos_from_break_even(break_even_acos: Any) -> float:
    value = _to_float(break_even_acos)
    if value is None or value <= 0:
        return 0.0
    return min(value * TARGET_ACOS_BREAK_EVEN_FACTOR, TARGET_ACOS_MAX)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Amazon frontend prices and optionally sync them into product_cost_config.xlsx.")
    parser.add_argument("--check", action="store_true", help="打开前台页面核对价格")
    parser.add_argument("--apply", action="store_true", help="把已核到的前台价反写进成本配置")
    parser.add_argument("--method", choices=["chrome", "playwright"], default="chrome")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=1.2)
    parser.add_argument(
        "--scope",
        choices=["all", "ad-flagged"],
        default="all",
        help="all 查成本表全部商品；ad-flagged 只查广告/今日动作队列点名商品。",
    )
    args = parser.parse_args()

    if not args.check and not args.apply:
        args.check = True
        args.apply = True

    if args.check:
        check_frontend_prices(method=args.method, timeout=args.timeout, sleep=args.sleep, scope=args.scope)
    if args.apply:
        updates = apply_frontend_prices()
        print(f"[frontend-price] synced {len(updates)} price rows")
        for item in updates:
            print(
                f"- {item['marketplace']} {item['sku']} {item['asin']} "
                f"{item['old_price']:.2f} -> {item['new_price']:.2f} ({item['frontend_price']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
