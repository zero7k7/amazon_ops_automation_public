from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_parallel_lock_owners import (
    is_locked_parallel_path,
    load_manifest,
    validate_owner_manifest,
)


LOCK_OWNER_MANIFEST = ROOT / "docs" / "parallel_lock_owners.json"
VALIDATION_RECEIPT = ROOT / "data" / "output" / "showcase_validation_receipt.json"
VALIDATION_RECEIPT_SCHEMA_VERSION = 1
UNKNOWN_INBOX_DIR = ROOT / "data" / "inbox" / "_unknown"
BUSINESS_INBOX_SUFFIXES = {".csv", ".xlsx"}

SHOWCASE_FILES = {
    ".gitignore",
    ".github/workflows/demo-cross-platform.yml",
    "AGENTS.md",
    "README.md",
    "README_RUN.md",
    "docs/business_confirmation_template.md",
    "docs/business_review_confirmation.json",
    "docs/showcase_goal_contract.md",
    "docs/showcase_commit_groups.md",
    "docs/multi_agent_work_packages.md",
    "docs/analysis_module_refactor_plan.md",
    "docs/data_leakage_guard.md",
    "docs/demo_runbook.md",
    "docs/frontend_stability_plan.md",
    "docs/github_release_readiness.md",
    "docs/release_boundary_plan.md",
    "docs/release_control_audit.md",
    "docs/shareable_clone_runbook.md",
    "docs/shareable_release_manifest.md",
    "docs/shareable_release_status.md",
    "docs/showcase_mvp_checklist.md",
    "docs/parallel_lock_owners.draft.json",
    "docs/parallel_lock_owners.json",
    "scripts/build_parallel_lock_owner_draft.py",
    "scripts/audit_unknown_inbox.py",
    "scripts/build_business_review_packet.py",
    "scripts/build_showcase_status_report.py",
    "scripts/check_daily_update_preflight.py",
    "scripts/check_parallel_lock_owners.py",
    "scripts/check_showcase_commit_readiness.py",
    "retry_frontend_checks.command",
    "run_today_report.command",
    "start_report_action_server.command",
    "scripts/ensure_report_action_server.py",
    "scripts/frontend_check_queue.py",
    "scripts/frontend_check_results.py",
    "scripts/frontend_product_fetch.py",
    "scripts/frontend_search_fetch.py",
    "scripts/import_and_run_all.bat",
    "scripts/quarantine_reviewed_unknown_inbox.py",
    "scripts/report_action_server.py",
    "scripts/run_report_window.py",
    "scripts/run_all_with_frontend_checks.py",
    "scripts/run_daily_update.py",
    "scripts/run_frontend_checks.py",
    "scripts/chrome_cdp_helper.py",
    "scripts/probe_frontend_chrome_cdp.py",
    "scripts/stop_local_services.py",
    "scripts/setup_demo_data.py",
    "scripts/validate_frontend_stability.py",
    "scripts/audit_ops_console_analysis.py",
    "scripts/validate_public_demo_smoke.py",
    "scripts/validate_showcase_mvp.py",
    "src/generate_excel_report.py",
    "src/generate_html_report.py",
    "src/html_pages/__init__.py",
    "src/html_pages/assets.py",
    "src/html_pages/common.py",
    "src/html_pages/components_ad_workbench.py",
    "src/html_pages/components_cards.py",
    "src/html_pages/components_common.py",
    "src/html_pages/components_frontend.py",
    "src/html_pages/components_review.py",
    "src/html_pages/dashboard.py",
    "src/html_pages/marketplace.py",
    "src/html_pages/recommendations.py",
    "src/html_pages/summary.py",
    "src/report_view/__init__.py",
    "src/report_view/ad_workbench.py",
    "src/report_view/frontend.py",
    "src/report_view/listing_review.py",
    "src/report_view/operations.py",
    "src/report_view/review.py",
    "tests/test_reporting_regressions.py",
    "tests/test_daily_update_preflight.py",
    "tests/test_build_parallel_lock_owner_draft.py",
    "tests/test_business_review_packet.py",
    "tests/test_parallel_lock_owners.py",
    "tests/test_quarantine_reviewed_unknown_inbox.py",
    "tests/test_report_action_server_upload.py",
    "tests/test_run_daily_update.py",
    "tests/test_audit_ops_console_analysis.py",
    "tests/test_chrome_cdp_helper.py",
    "tests/test_probe_frontend_chrome_cdp.py",
    "tests/test_validate_frontend_stability.py",
    "tests/test_showcase_status_report.py",
    "tests/test_unknown_inbox_audit.py",
    "tests/test_showcase_commit_readiness.py",
    "tests/test_validate_showcase_mvp.py",
}

BUSINESS_REVIEW_FILES = {
    "main.py",
    "scripts/audit_cost_config_changes.py",
    "scripts/export_ad_automation_inputs.py",
    "scripts/run_lingxing_mcp.py",
    "scripts/sync_frontend_prices.py",
    "src/analyze_rules.py",
    "src/autoopt_feedback.py",
    "src/build_sku_asin_map.py",
    "src/db.py",
    "src/inventory_replenishment.py",
    "src/lingxing_mcp_client.py",
    "src/merge_data.py",
    "src/metrics.py",
    "src/parse_ads_report.py",
    "src/parse_erp_sales.py",
    "src/product_battle_diagnosis.py",
    "src/product_decision_layer.py",
    "src/report_presentation.py",
    "tests/test_action_queue_regressions.py",
    "tests/test_ads_attribution_parsing.py",
    "tests/test_cost_config_audit.py",
    "tests/test_lingxing_mcp_client.py",
    "tests/test_local_service_lifecycle.py",
    "tests/test_metrics.py",
    "tests/test_raw_import_persistence.py",
    "tests/test_merge_data_core.py",
}

MANUAL_CONFIG_FILES = {
    "config/product_cost_config.xlsx",
    "config/product_keyword_rules.csv",
    "config/sku_alias_map.xlsx",
    "config/sku_asin_map.xlsx",
    "config/ignored_quality_issues.xlsx",
}

CONFIG_TEMPLATE_FILES = {
    "config/templates/product_cost_config.example.xlsx",
    "config/templates/frontend_locations.example.json",
    "config/templates/product_keyword_rules.example.csv",
    "config/templates/sku_alias_map.example.xlsx",
    "config/templates/sku_asin_map.example.xlsx",
}

DAILY_ENTRY_FILES = {
    "scripts/run_daily_update.py",
    "scripts/check_daily_update_preflight.py",
    "scripts/audit_unknown_inbox.py",
    "scripts/build_showcase_status_report.py",
    "scripts/run_all_with_frontend_checks.py",
    "scripts/run_frontend_checks.py",
    "scripts/ensure_report_action_server.py",
    "scripts/report_action_server.py",
    "scripts/run_report_window.py",
    "scripts/sync_frontend_prices.py",
    "run_today_report.command",
    "retry_frontend_checks.command",
    "start_report_action_server.command",
    "scripts/import_and_run_all.bat",
}

GENERATED_PREFIXES = (
    "data/output/",
    "data/archive/",
    "data/raw_ads/",
    "data/raw_erp/",
    "data/raw_amazon_custom/",
    "database/",
    "logs/",
)
LOCAL_PREFIXES = (
    ".claude/",
    ".pytest_cache/",
    "__pycache__/",
)
NOISE_SUFFIXES = (
    ".pyc",
    ".DS_Store",
    ".bak",
)


def git_lines(args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def changed_paths() -> list[str]:
    paths = set(git_lines(["diff", "--name-only"]))
    paths.update(git_lines(["diff", "--cached", "--name-only"]))
    paths.update(git_lines(["ls-files", "--others", "--exclude-standard"]))
    return sorted(paths)


def changed_name_status() -> dict[str, str]:
    rows = git_lines(["diff", "--name-status"])
    rows.extend(git_lines(["diff", "--cached", "--name-status"]))
    status_by_path: dict[str, str] = {}
    for row in rows:
        parts = row.split("\t")
        if len(parts) >= 2:
            status_by_path[parts[-1]] = parts[0]
    return status_by_path


def public_config_leakage(paths: Sequence[str], status_by_path: dict[str, str]) -> list[str]:
    return sorted(
        path
        for path in paths
        if path.startswith("config/")
        and path.endswith(".xlsx")
        and path not in CONFIG_TEMPLATE_FILES
        and status_by_path.get(path) != "D"
    )


def parallel_lock_owner_failures(paths: Sequence[str]) -> list[str]:
    manifest, load_failures = load_manifest(LOCK_OWNER_MANIFEST)
    if load_failures:
        return load_failures
    if manifest is None:
        return ["parallel lock owner manifest could not be loaded"]
    return validate_owner_manifest(paths, manifest)


def unknown_inbox_business_files() -> list[str]:
    if not UNKNOWN_INBOX_DIR.exists():
        return []
    files = [
        path
        for path in UNKNOWN_INBOX_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in BUSINESS_INBOX_SUFFIXES
    ]
    return sorted(str(path.relative_to(ROOT)) for path in files)


def validation_receipt_failures() -> list[str]:
    if not VALIDATION_RECEIPT.exists():
        return ["showcase validation receipt missing"]
    receipt = _load_json(VALIDATION_RECEIPT)
    if receipt is None:
        return ["showcase validation receipt cannot be read"]

    failures: list[str] = []
    actual_schema = receipt.get("schema_version", "<missing>")
    try:
        schema_number = int(receipt.get("schema_version") or 0)
    except (TypeError, ValueError):
        schema_number = 0
    if schema_number != VALIDATION_RECEIPT_SCHEMA_VERSION:
        failures.append(
            "showcase validation receipt schema_version mismatch: "
            f"expected {VALIDATION_RECEIPT_SCHEMA_VERSION}, got {actual_schema}"
        )
    if receipt.get("result") != "passed":
        failures.append("showcase validation receipt result is not passed")
    for key in ["pytest_exit_code", "safe_run_exit_code", "output_validation_exit_code"]:
        if int(receipt.get(key) or 0) != 0:
            failures.append(f"showcase validation receipt has non-zero {key}")

    try:
        from scripts.validate_showcase_mvp import workspace_fingerprint

        current_state = workspace_fingerprint()
    except Exception as exc:
        failures.append(f"cannot compute current workspace validation hash: {exc}")
        return failures

    if str(receipt.get("git_head") or "") != str(current_state.get("git_head") or ""):
        failures.append("showcase validation receipt git_head does not match current HEAD")
    if str(receipt.get("workspace_hash") or "") != str(current_state.get("workspace_hash") or ""):
        failures.append("showcase validation receipt workspace_hash does not match current changes")

    safe_run_dir = Path(str(receipt.get("safe_run_dir") or ""))
    if not safe_run_dir.exists():
        failures.append("showcase validation receipt safe_run_dir is missing")
    if not receipt.get("report_date"):
        failures.append("showcase validation receipt missing report_date")
    marketplaces = receipt.get("marketplaces")
    if marketplaces != ["DE", "UK", "US"]:
        failures.append("showcase validation receipt missing DE, UK, US marketplaces")
    return failures


def fail(message: str) -> int:
    print(f"[fail] {message}", flush=True)
    return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check showcase commit grouping and review gates.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when review-only warnings still need explicit confirmation.",
    )
    parser.add_argument(
        "--manual-config-confirmed",
        action="store_true",
        help="Strict mode: confirm manual config changes were reviewed by the business owner.",
    )
    parser.add_argument(
        "--business-review-confirmed",
        action="store_true",
        help="Strict mode: confirm business logic files were reviewed by their owner.",
    )
    parser.add_argument(
        "--parallel-lock-owner-confirmed",
        action="store_true",
        help="Strict mode: confirm changed parallel lock files had a single owner.",
    )
    parser.add_argument(
        "--daily-update-verified",
        action="store_true",
        help="Strict mode: confirm daily entry changes were verified after preflight passed.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = changed_paths()
    status_by_path = changed_name_status()
    unknown_inbox_blockers = unknown_inbox_business_files()
    receipt_failures = validation_receipt_failures()
    if not paths:
        print("[check] working tree has no changed or untracked files", flush=True)
        if unknown_inbox_blockers:
            print(
                "[warn] unknown inbox business files block daily update: "
                + ", ".join(unknown_inbox_blockers),
                flush=True,
            )
        else:
            print("[check] no unknown inbox business blockers", flush=True)
        if receipt_failures:
            for failure in receipt_failures:
                print("[warn] showcase validation receipt issue: " + failure, flush=True)
        else:
            print("[check] showcase validation receipt matches current workspace", flush=True)
        if args.strict:
            strict_failures = []
            if unknown_inbox_blockers:
                strict_failures.append("unknown inbox business files present")
            if receipt_failures:
                strict_failures.append("showcase validation receipt invalid or stale")
            if strict_failures:
                return fail("strict mode requires confirmations: " + "; ".join(strict_failures))
        return 0

    known_paths = SHOWCASE_FILES | BUSINESS_REVIEW_FILES | MANUAL_CONFIG_FILES | CONFIG_TEMPLATE_FILES
    generated = [path for path in paths if path.startswith(GENERATED_PREFIXES)]
    local_noise = [
        path
        for path in paths
        if path.startswith(LOCAL_PREFIXES) or path.endswith(NOISE_SUFFIXES)
    ]
    unknown = [
        path
        for path in paths
        if path not in known_paths
        and path not in generated
        and path not in local_noise
    ]
    manual_config = [path for path in paths if path in MANUAL_CONFIG_FILES and status_by_path.get(path) != "D"]
    removed_config = [path for path in paths if path in MANUAL_CONFIG_FILES and status_by_path.get(path) == "D"]
    public_config_blockers = public_config_leakage(paths, status_by_path)
    business_review = [path for path in paths if path in BUSINESS_REVIEW_FILES]
    showcase = [path for path in paths if path in SHOWCASE_FILES]
    locked_parallel = [path for path in paths if is_locked_parallel_path(path)]
    daily_entry = [path for path in paths if path in DAILY_ENTRY_FILES]

    if generated:
        return fail("generated data files changed or untracked: " + ", ".join(generated))
    if local_noise:
        return fail("local noise files changed or untracked: " + ", ".join(local_noise))
    if unknown:
        return fail("changed files are not assigned to a commit group: " + ", ".join(unknown))
    if public_config_blockers:
        return fail(
            "public release blocks real config xlsx files; use config/templates examples and remove from index: "
            + ", ".join(public_config_blockers)
        )

    print("[check] showcase files:", len(showcase), flush=True)
    print("[check] business review files:", len(business_review), flush=True)
    if removed_config:
        print("[check] real config files removed from git index: " + ", ".join(removed_config), flush=True)
    if manual_config:
        print("[warn] manual config confirmation required: " + ", ".join(manual_config), flush=True)
    else:
        print("[check] no manual config files changed", flush=True)
    if business_review:
        print("[warn] business review required before commit: " + ", ".join(business_review), flush=True)
    else:
        print("[check] no business review files changed", flush=True)
    if locked_parallel:
        print("[warn] parallel lock files changed: " + ", ".join(locked_parallel), flush=True)
        print("[warn] confirm each lock file had a single owner before merge", flush=True)
    else:
        print("[check] no parallel lock files changed", flush=True)
    lock_owner_failures = parallel_lock_owner_failures(paths) if locked_parallel else []
    if lock_owner_failures:
        for failure in lock_owner_failures:
            print("[warn] parallel lock owner issue: " + failure, flush=True)
    elif locked_parallel:
        print("[check] parallel lock owner manifest covers changed locked files", flush=True)
    if daily_entry:
        print("[warn] daily update entry files changed: " + ", ".join(daily_entry), flush=True)
    else:
        print("[check] no daily update entry files changed", flush=True)
    if unknown_inbox_blockers:
        print(
            "[warn] unknown inbox business files block daily update: "
            + ", ".join(unknown_inbox_blockers),
            flush=True,
        )
    else:
        print("[check] no unknown inbox business blockers", flush=True)
    if receipt_failures:
        for failure in receipt_failures:
            print("[warn] showcase validation receipt issue: " + failure, flush=True)
    else:
        print("[check] showcase validation receipt matches current workspace", flush=True)
    if args.strict:
        strict_failures = []
        if manual_config and not args.manual_config_confirmed:
            strict_failures.append("manual config confirmation missing")
        if business_review and not args.business_review_confirmed:
            strict_failures.append("business review confirmation missing")
        if locked_parallel and not args.parallel_lock_owner_confirmed:
            strict_failures.append("parallel lock owner confirmation missing")
        if lock_owner_failures:
            strict_failures.append("parallel lock owner manifest invalid")
        if daily_entry and not args.daily_update_verified:
            strict_failures.append("daily update verification missing")
        if unknown_inbox_blockers:
            strict_failures.append("unknown inbox business files present")
        if receipt_failures:
            strict_failures.append("showcase validation receipt invalid or stale")
        if strict_failures:
            return fail("strict mode requires confirmations: " + "; ".join(strict_failures))
        print("[check] strict confirmations accepted", flush=True)
    print("[done] changed files are assigned to known commit groups", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
