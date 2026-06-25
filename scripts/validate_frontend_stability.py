from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
LOCATION_CONFIG = ROOT / "config" / "frontend_locations.json"
DEFAULT_INPUT = OUTPUT_DIR / "frontend_stability_attempts.json"
DEFAULT_OUTPUT = OUTPUT_DIR / "frontend_stability_report.json"
DEFAULT_MIN_ATTEMPTS = 20
DEFAULT_MAX_FAILURES = 4
DEFAULT_MIN_SUCCESS_RATE = 0.80


EXPECTED_PRICE_SYMBOL = {"UK": "£", "US": "$", "DE": "€"}
WRONG_LOCATION_MARKERS = {
    "UK": ("united states", "canada", "australia", "japan", "germany", "deutschland"),
    "US": ("united kingdom", "great britain", "germany", "deutschland", "canada", "australia", "japan"),
    "DE": ("united states", "united kingdom", "great britain", "canada", "australia", "japan"),
}
MARKETPLACE_LOCATION_MARKERS = {
    "UK": ("united kingdom", "uk", "ireland", "aberdeen", "london", "manchester", "birmingham", "glasgow", "edinburgh"),
    "US": ("united states", "us", "new york", "california", "texas", "florida", "washington"),
    "DE": ("germany", "deutschland", "de", "berlin", "hamburg", "munich", "münchen", "frankfurt"),
}
DEFAULT_LOCATIONS = {
    "UK": {"postcode": "SW1A 1AA"},
    "US": {"postcode": "10001"},
    "DE": {"postcode": "10115"},
}


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
                marketplace = str(key).strip().upper()
                locations[marketplace] = {
                    **locations.get(marketplace, {}),
                    **{str(k): str(v) for k, v in value.items()},
                }
    return locations


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("attempts", "items", "runs", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _field(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return _clean(value)
    return ""


def _has_expected_price(row: dict[str, Any], marketplace: str) -> bool:
    price = _field(row, "frontend_price", "price", "primary")
    symbol = EXPECTED_PRICE_SYMBOL.get(marketplace)
    return bool(price and symbol and symbol in price and re.search(r"\d", price))


def _location_ok(row: dict[str, Any], marketplace: str) -> bool:
    note = _field(row, "frontend_location_note", "frontend_delivery", "delivery", "location", "visible_location")
    if not note:
        return False
    lower = note.lower()
    if any(marker in lower for marker in WRONG_LOCATION_MARKERS.get(marketplace, ())):
        return False
    configured = _load_locations().get(marketplace, {})
    postcode = _clean(configured.get("postcode"))
    if postcode and postcode.lower() in lower:
        return True
    if "已设置" in note and marketplace in note.upper():
        return True
    return any(marker in lower for marker in MARKETPLACE_LOCATION_MARKERS.get(marketplace, ()))


def _attempt_result(row: dict[str, Any], marketplace: str) -> dict[str, Any]:
    reasons: list[str] = []
    status = _field(row, "frontend_check_status", "status")
    explicit_success = row.get("success")
    if isinstance(explicit_success, str):
        explicit_success = explicit_success.strip().lower() in {"1", "true", "yes", "ok", "success"}
    elif explicit_success is not None:
        explicit_success = bool(explicit_success)
    captcha_text = " ".join(
        _field(row, key)
        for key in ("frontend_last_error", "error", "body", "title", "frontend_findings")
    ).lower()
    if any(token in captcha_text for token in ("captcha", "robot check", "automated access", "enter the characters")):
        reasons.append("captcha_or_block")
    if explicit_success is False:
        reasons.append("explicit_failure")
    if status and status not in {"已自动检查", "success", "ok"} and not status.startswith("沿用"):
        reasons.append(f"bad_status:{status}")
    if not _field(row, "frontend_title", "title"):
        reasons.append("missing_title")
    if not _has_expected_price(row, marketplace):
        reasons.append("missing_or_wrong_price")
    if not _location_ok(row, marketplace):
        reasons.append("missing_or_wrong_location")
    success = not reasons and (explicit_success is not False)
    return {
        "attempt": row.get("attempt") or row.get("index") or "",
        "success": success,
        "reasons": reasons,
        "price": _field(row, "frontend_price", "price", "primary"),
        "location": _field(row, "frontend_location_note", "frontend_delivery", "delivery", "location", "visible_location"),
        "method": _field(row, "frontend_check_method", "method"),
    }


def build_stability_report(
    payload: Any,
    *,
    marketplace: str,
    asin: str,
    min_attempts: int = DEFAULT_MIN_ATTEMPTS,
    max_failures: int = DEFAULT_MAX_FAILURES,
    min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE,
) -> dict[str, Any]:
    marketplace = _clean(marketplace).upper()
    asin = _clean(asin).upper()
    records = _records_from_payload(payload)
    if asin:
        records = [row for row in records if not _field(row, "asin", "ASIN") or _field(row, "asin", "ASIN").upper() == asin]
    attempts = [_attempt_result(row, marketplace) for row in records]
    total = len(attempts)
    success_count = sum(1 for row in attempts if row["success"])
    failures = total - success_count
    success_rate = success_count / total if total else 0.0
    passed = total >= min_attempts and failures <= max_failures and success_rate >= min_success_rate
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "marketplace": marketplace,
        "asin": asin,
        "total_attempts": total,
        "success_count": success_count,
        "failure_count": failures,
        "success_rate": round(success_rate, 4),
        "min_attempts": min_attempts,
        "max_failures": max_failures,
        "min_success_rate": min_success_rate,
        "passed": passed,
        "attempts": attempts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a 20-run Amazon frontend stability probe.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 JSON 文件路径；传 '-' 时只打印结果，不写文件。")
    parser.add_argument("--marketplace", required=True)
    parser.add_argument("--asin", required=True)
    parser.add_argument("--min-attempts", type=int, default=DEFAULT_MIN_ATTEMPTS)
    parser.add_argument("--max-failures", type=int, default=DEFAULT_MAX_FAILURES)
    parser.add_argument("--min-success-rate", type=float, default=DEFAULT_MIN_SUCCESS_RATE)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = build_stability_report(
        payload,
        marketplace=args.marketplace,
        asin=args.asin,
        min_attempts=args.min_attempts,
        max_failures=args.max_failures,
        min_success_rate=args.min_success_rate,
    )
    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    if str(args.output).strip() == "-":
        print(report_json)
    else:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_json, encoding="utf-8")
    print(
        f"[frontend-stability] {report['success_count']}/{report['total_attempts']} "
        f"success, failures={report['failure_count']}, passed={report['passed']}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
