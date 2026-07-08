from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.run_daily_update import (
    FRONTEND_GATE_CONSISTENCY_FIELDS,
    _frontend_gate_field_value,
    _frontend_gate_value,
    _output_refresh_snapshot,
    report_refresh_failures,
    report_state_snapshot,
    restore_report_state_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_RESULTS_JSON = ROOT / "data" / "output" / "frontend_check_results.json"
LATEST_ANALYSIS_JSON = ROOT / "data" / "output" / "latest_analysis.json"


def run_step(args: list[str]) -> int:
    print("[run]", " ".join(args), flush=True)
    try:
        completed = subprocess.run(args, cwd=ROOT)
    except OSError as exc:
        print(f"[fail] cannot start step: {exc}", flush=True)
        return 127
    print("[exit]", completed.returncode, flush=True)
    return completed.returncode


def restore_outputs_after_failure(snapshot: dict[str, object]) -> None:
    failures = restore_report_state_snapshot(snapshot)
    if failures:
        for failure in failures:
            print(f"[fail] state restore blocker: {failure}", flush=True)
        return
    print(
        "[restore] report outputs restored to pre-run snapshot after failure; database/archive state restored when tracked",
        flush=True,
    )


def _mtime_ns(path: Path) -> int | None:
    if not path.exists():
        return None
    return path.stat().st_mtime_ns


def _frontend_results_generated_at(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("generated_at") or "").strip()


def frontend_results_refresh_failures(
    path: Path | None = None,
    *,
    previous_mtime_ns: int | None = None,
    previous_generated_at: str = "",
    expected_analysis_path: Path | None = None,
) -> list[str]:
    path = path or FRONTEND_RESULTS_JSON
    current_mtime = _mtime_ns(path)
    if current_mtime is None:
        return [f"frontend check results missing after frontend step: {path}"]
    if previous_mtime_ns is not None and current_mtime == previous_mtime_ns:
        return [f"frontend check results were not refreshed by frontend step: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"frontend check results cannot be read: {exc}"]
    if not isinstance(payload, dict):
        return [f"frontend check results root must be an object: {path}"]
    generated_at = str(payload.get("generated_at") or "").strip()
    if not generated_at:
        return [f"frontend check results missing generated_at: {path}"]
    if previous_generated_at and generated_at == previous_generated_at:
        return [f"frontend check results generated_at was not refreshed by frontend step: {path}"]
    if not isinstance(payload.get("refresh_summary"), dict):
        return [f"frontend check results refresh_summary must be an object: {path}"]
    summary = payload.get("refresh_summary") or {}
    try:
        total = int(summary.get("frontend_refresh_total") or 0)
        live_checked = int(summary.get("frontend_refresh_live_checked") or 0)
        skipped = int(summary.get("frontend_refresh_skipped") or 0)
        cache_used = int(summary.get("frontend_refresh_cache_used") or 0)
        failed = int(summary.get("frontend_refresh_failed") or 0)
    except (TypeError, ValueError):
        return [f"frontend check results refresh_summary counts must be numeric: {path}"]
    if total > 0 and failed >= total and live_checked + skipped + cache_used == 0:
        return [f"frontend check results contain only failed frontend refresh rows: {path}"]
    items = payload.get("items")
    if not isinstance(items, list):
        return [f"frontend check results items must be a list: {path}"]
    if expected_analysis_path is not None:
        try:
            analysis_payload = json.loads(expected_analysis_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return [f"latest analysis cannot be read for frontend refresh validation: {exc}"]
        if not isinstance(analysis_payload, dict):
            return [f"latest analysis root must be an object for frontend refresh validation: {expected_analysis_path}"]
        expected = _latest_analysis_frontend_identities(analysis_payload)
        actual = {
            identity
            for row in items
            if isinstance(row, dict)
            for identity in [_frontend_identity(row)]
            if all(identity)
        }
        missing = sorted(expected.difference(actual))
        if missing:
            labels = ["/".join(identity) for identity in missing[:5]]
            return [
                "frontend check results did not cover queued frontend identities: "
                + "; ".join(labels)
            ]
        generated_date = generated_at[:10] if len(generated_at) >= 10 else ""
        item_rows = {
            identity: row
            for row in items
            if isinstance(row, dict)
            for identity in [_frontend_identity(row)]
            if all(identity)
        }
        stale = []
        for identity in sorted(expected):
            row = item_rows.get(identity) or {}
            refresh_action = str(row.get("frontend_refresh_action") or "").strip()
            data_date = _date_prefix(row, "frontend_data_date", "checked_at", "generated_at")
            if refresh_action or (generated_date and data_date == generated_date):
                continue
            stale.append("/".join(identity))
        if stale:
            return [
                "frontend check results covered queued identities with stale rows lacking refresh action: "
                + "; ".join(stale[:5])
            ]
    return []


def _frontend_identity(row: dict, fallback_marketplace: object = "") -> tuple[str, str, str]:
    return (
        str(row.get("marketplace") or fallback_marketplace or "").strip().upper(),
        str(row.get("sku") or row.get("SKU") or "").strip(),
        str(row.get("asin") or row.get("ASIN") or "").strip().upper(),
    )


def _date_prefix(row: dict, *fields: str) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
            return value[:10]
    return ""


def _frontend_results_absorption_identities(payload: dict) -> set[tuple[str, str, str]]:
    generated_at = str(payload.get("generated_at") or "").strip()
    generated_date = generated_at[:10] if len(generated_at) >= 10 else ""
    identities: set[tuple[str, str, str]] = set()
    for row in payload.get("items") or []:
        if not isinstance(row, dict):
            continue
        identity = _frontend_identity(row)
        if not all(identity):
            continue
        refresh_action = str(row.get("frontend_refresh_action") or "").strip()
        data_date = _date_prefix(row, "frontend_data_date", "checked_at", "generated_at")
        if refresh_action or (generated_date and data_date == generated_date):
            identities.add(identity)
    return identities


def _frontend_results_absorption_rows(payload: dict) -> dict[tuple[str, str, str], dict]:
    generated_at = str(payload.get("generated_at") or "").strip()
    generated_date = generated_at[:10] if len(generated_at) >= 10 else ""
    rows: dict[tuple[str, str, str], dict] = {}
    for row in payload.get("items") or []:
        if not isinstance(row, dict):
            continue
        identity = _frontend_identity(row)
        if not all(identity):
            continue
        refresh_action = str(row.get("frontend_refresh_action") or "").strip()
        data_date = _date_prefix(row, "frontend_data_date", "checked_at", "generated_at")
        if refresh_action or (generated_date and data_date == generated_date):
            rows[identity] = row
    return rows


def _latest_analysis_frontend_identities(payload: dict) -> set[tuple[str, str, str]]:
    identities: set[tuple[str, str, str]] = set()
    for result in payload.get("marketplace_results") or []:
        if not isinstance(result, dict):
            continue
        marketplace = str(result.get("marketplace") or "").strip().upper()
        snapshot = result.get("report_view_snapshot") or {}
        if not isinstance(snapshot, dict):
            continue
        for row in snapshot.get("frontend_check_queue_rows") or []:
            if not isinstance(row, dict):
                continue
            identity = _frontend_identity(row, marketplace)
            if all(identity):
                identities.add(identity)
    return identities


def _latest_analysis_frontend_rows(payload: dict) -> dict[tuple[str, str, str], dict]:
    rows: dict[tuple[str, str, str], dict] = {}
    for result in payload.get("marketplace_results") or []:
        if not isinstance(result, dict):
            continue
        marketplace = str(result.get("marketplace") or "").strip().upper()
        snapshot = result.get("report_view_snapshot") or {}
        if not isinstance(snapshot, dict):
            continue
        for row in snapshot.get("frontend_check_queue_rows") or []:
            if not isinstance(row, dict):
                continue
            identity = _frontend_identity(row, marketplace)
            if all(identity):
                rows[identity] = row
    return rows


def _canonical_frontend_absorption_value(field: str, value: object) -> str:
    if field == "frontend_data_date":
        text = str(value or "").strip()
        return text[:10] if len(text) >= 10 else text
    if field in FRONTEND_GATE_CONSISTENCY_FIELDS:
        return _frontend_gate_field_value(field, value)
    return _frontend_gate_value(value)


def _frontend_absorption_signature(row: dict) -> dict[str, str]:
    signature: dict[str, str] = {}
    fields = list(
        dict.fromkeys(
            ["frontend_check_status", "frontend_data_date", "frontend_refresh_action", *FRONTEND_GATE_CONSISTENCY_FIELDS]
        )
    )
    for field in fields:
        if field in row and row.get(field) not in (None, ""):
            signature[field] = _canonical_frontend_absorption_value(field, row.get(field))
    return signature


def _frontend_absorption_values_match(field: str, expected_value: str, actual_value: str) -> bool:
    if expected_value == actual_value:
        return True
    if field in FRONTEND_GATE_CONSISTENCY_FIELDS and expected_value == "false" and actual_value == "":
        return True
    return False


def frontend_results_absorption_failures(
    results_path: Path | None = None,
    analysis_path: Path | None = None,
) -> list[str]:
    results_path = results_path or FRONTEND_RESULTS_JSON
    analysis_path = analysis_path or LATEST_ANALYSIS_JSON
    try:
        results_payload = json.loads(results_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"frontend check results cannot be read for absorption validation: {exc}"]
    try:
        analysis_payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"latest analysis cannot be read for frontend absorption validation: {exc}"]
    if not isinstance(results_payload, dict):
        return [f"frontend check results root must be an object for absorption validation: {results_path}"]
    if not isinstance(analysis_payload, dict):
        return [f"latest analysis root must be an object for frontend absorption validation: {analysis_path}"]
    expected_rows = _frontend_results_absorption_rows(results_payload)
    expected = set(expected_rows)
    if not expected:
        return []
    actual_rows = _latest_analysis_frontend_rows(analysis_payload)
    actual = set(actual_rows)
    for identity in sorted(expected.intersection(actual)):
        expected_signature = _frontend_absorption_signature(expected_rows[identity])
        actual_signature = _frontend_absorption_signature(actual_rows[identity])
        for field, expected_value in expected_signature.items():
            actual_value = actual_signature.get(field, "")
            if not _frontend_absorption_values_match(field, expected_value, actual_value):
                return [
                    "frontend check results field was not absorbed into latest_analysis frontend queue "
                    f"for {'/'.join(identity)} field {field}: expected {expected_value!r}, got {actual_value!r}"
                ]
    return []


def run_frontend_price_sync(python: str) -> int:
    chrome_step = [
        python,
        "scripts/sync_frontend_prices.py",
        "--check",
        "--apply",
        "--method",
        "chrome",
        "--timeout",
        "30",
        "--scope",
        "ad-flagged",
    ]
    code = run_step(chrome_step)
    if code == 0:
        return 0

    fallback_step = [
        python,
        "scripts/sync_frontend_prices.py",
        "--check",
        "--apply",
        "--method",
        "playwright",
        "--timeout",
        "30",
        "--scope",
        "ad-flagged",
    ]
    print("[warn] Chrome price sync failed; retrying with Playwright Chromium.", flush=True)
    code = run_step(fallback_step)
    if code == 0:
        return 0

    print("[fail] Frontend price sync failed in live browser mode.", flush=True)
    return code


def _browser_frontend_enabled(cli_enabled: bool, cli_disabled: bool) -> bool:
    if cli_disabled:
        return False
    if cli_enabled:
        return True
    value = os.environ.get("AMAZON_OPS_ENABLE_BROWSER_FRONTEND", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ALL reports with optional frontend enrichment.")
    parser.add_argument(
        "--live-browser-frontend",
        action="store_true",
        help="允许启动 Chrome/Playwright 做实时前台价格同步和页面检查。默认禁用，避免 macOS 权限环境弹出浏览器崩溃提示。",
    )
    parser.add_argument(
        "--no-live-browser-frontend",
        action="store_true",
        help="强制禁用 Chrome/Playwright，即使环境变量 AMAZON_OPS_ENABLE_BROWSER_FRONTEND 已设置也不启动浏览器。",
    )
    parser.add_argument(
        "--frontend-method",
        choices=["auto", "chrome", "chrome-persistent", "playwright", "urllib"],
        default="",
        help="前台检查读取方式。未指定时，安全模式使用 urllib；live-browser 模式使用 auto。",
    )
    args = parser.parse_args()

    python = sys.executable
    browser_enabled = _browser_frontend_enabled(args.live_browser_frontend, args.no_live_browser_frontend)
    frontend_method = args.frontend_method or ("auto" if browser_enabled else "urllib")
    steps = [
        [python, "main.py", "--marketplace", "ALL"],
        [
            python,
            "scripts/run_frontend_checks.py",
            "--method",
            frontend_method,
            "--timeout",
            "30",
            "--retries",
            "3",
            "--search-policy",
            "always",
            *(["--reuse-browser-session"] if browser_enabled else []),
        ],
        [python, "main.py", "--marketplace", "ALL"],
    ]
    pre_run_state_snapshot = report_state_snapshot()
    code = run_step(steps[0])
    if code != 0:
        restore_outputs_after_failure(pre_run_state_snapshot)
        return code
    if browser_enabled:
        code = run_frontend_price_sync(python)
        if code != 0:
            restore_outputs_after_failure(pre_run_state_snapshot)
            return code
    else:
        print(
            "[skip] Browser frontend disabled; skipping Chrome/Playwright price sync to avoid macOS crash prompts.",
            flush=True,
        )
    previous_frontend_results_mtime = _mtime_ns(FRONTEND_RESULTS_JSON)
    previous_frontend_results_generated_at = _frontend_results_generated_at(FRONTEND_RESULTS_JSON)
    code = run_step(steps[1])
    if code != 0:
        restore_outputs_after_failure(pre_run_state_snapshot)
        return code
    frontend_failures = frontend_results_refresh_failures(
        previous_mtime_ns=previous_frontend_results_mtime,
        previous_generated_at=previous_frontend_results_generated_at,
        expected_analysis_path=LATEST_ANALYSIS_JSON,
    )
    if frontend_failures:
        for failure in frontend_failures:
            print(f"[fail] frontend refresh blocker: {failure}", flush=True)
        restore_outputs_after_failure(pre_run_state_snapshot)
        return 1
    previous_output_mtimes = _output_refresh_snapshot()
    code = run_step(steps[2])
    if code != 0:
        restore_outputs_after_failure(pre_run_state_snapshot)
        return code
    refresh_failures = report_refresh_failures(previous_mtimes_ns=previous_output_mtimes)
    if refresh_failures:
        for failure in refresh_failures:
            print(f"[fail] report refresh blocker: {failure}", flush=True)
        restore_outputs_after_failure(pre_run_state_snapshot)
        return 1
    absorption_failures = frontend_results_absorption_failures()
    if absorption_failures:
        for failure in absorption_failures:
            print(f"[fail] frontend absorption blocker: {failure}", flush=True)
        restore_outputs_after_failure(pre_run_state_snapshot)
        return 1
    mode = "live browser frontend" if browser_enabled else "no-browser cached/urllib frontend"
    print(f"[done] reports refreshed with {mode} and frontend_check_results.json", flush=True)
    print(f"[open] {ROOT / 'data' / 'output' / 'latest_recommendations.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
