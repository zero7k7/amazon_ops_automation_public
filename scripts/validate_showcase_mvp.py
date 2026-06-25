from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
SAFE_RUN_ROOT = ROOT / "data" / "output" / "safe_run"
VALIDATION_RECEIPT = ROOT / "data" / "output" / "showcase_validation_receipt.json"
VALIDATION_RECEIPT_SCHEMA_VERSION = 1
REQUIRED_FILES = [
    "latest_analysis.json",
    "latest_recommendations.html",
    "dashboard.html",
    "summary.html",
    "uk_report.html",
    "us_report.html",
    "de_report.html",
]
REQUIRED_ASSET_FILES = [
    "assets/report.css",
    "assets/report.js",
]
REQUIRED_SNAPSHOT_KEYS = {
    "today_task_queue_rows",
    "frontend_check_queue_rows",
    "cost_profit_diagnosis_rows",
    "listing_price_diagnosis_rows",
}
HTML_ERROR_MARKERS = ["Traceback", "KeyError", "NoneType"]
REQUIRED_HTML_MARKERS = {
    "dashboard.html": ["运营状态入口", "打开三分钟摘要", "打开 ALL 运营控制台"],
    "latest_recommendations.html": ["今天广告动作", "前台证据状态", "提交今日数据", "系统结论", "融合诊断"],
    "summary.html": ["三分钟摘要"],
    "uk_report.html": ["亚马逊运营日报｜UK", "广告状态", "数据质量与增强数据"],
    "us_report.html": ["亚马逊运营日报｜US", "广告状态", "数据质量与增强数据"],
    "de_report.html": ["亚马逊运营日报｜DE", "广告状态", "数据质量与增强数据"],
}
FORBIDDEN_HTML_MARKERS = {
    "latest_recommendations.html": [
        "需要确认的问题",
        "疑似前台竞争力需要确认",
        "<h2>前台数据更新</h2>",
        "<h2>刷新前台",
        "<h2>重新检查前台",
    ],
    "uk_report.html": ["<h2>前台数据更新</h2>"],
    "us_report.html": ["<h2>前台数据更新</h2>"],
    "de_report.html": ["<h2>前台数据更新</h2>"],
}
FRONTEND_CHECK_OK_STATUSES = {"已自动检查"}
OBSERVATION_ACTIONS = {"观察", "保留", "保留观察", "无需操作", "仅背景参考"}
AD_COPY_ANCHOR = 'id="today-ad-actions-all"'


def _is_frontend_fallback_status(status: str, freshness: str, findings: str) -> bool:
    text = " ".join([status, freshness, findings])
    return "待前台检查" in text or "沿用" in text


def _validate_frontend_rows(marketplace: str, rows: list[dict]) -> int:
    for idx, row in enumerate(rows, start=1):
        status = str(row.get("frontend_check_status") or "").strip()
        freshness = str(row.get("frontend_data_freshness") or "").strip()
        findings = str(row.get("frontend_findings") or "").strip()
        if status in FRONTEND_CHECK_OK_STATUSES:
            continue
        if not _is_frontend_fallback_status(status, freshness, findings):
            asin = row.get("asin") or "unknown_asin"
            return fail(
                f"{marketplace} frontend row {idx} {asin} missing cached-date or pending-check status"
            )
        if "沿用" in status and not any(char.isdigit() for char in status):
            asin = row.get("asin") or "unknown_asin"
            return fail(f"{marketplace} frontend row {idx} {asin} cache status missing date")
    return 0


def _iter_ad_action_rows(snapshot: dict) -> list[dict]:
    groups = snapshot.get("today_action_groups") or {}
    rows = groups.get("广告动作") if isinstance(groups, dict) else []
    return rows if isinstance(rows, list) else []


def _is_observation_ad_row(row: dict) -> bool:
    action = str(row.get("suggested_action") or row.get("normalized_action") or row.get("today_action") or "").strip()
    return action in OBSERVATION_ACTIONS or any(token in action for token in ["观察", "保留", "无需操作"])


def _validate_ad_observation_rows(marketplace: str, rows: list[dict]) -> int:
    for idx, row in enumerate(rows, start=1):
        if not _is_observation_ad_row(row):
            continue
        if str(row.get("confirmed_status") or "").strip() == "已执行":
            target = row.get("search_term_or_target") or row.get("targeting") or row.get("asin") or "unknown_target"
            return fail(f"{marketplace} ad observation row {idx} {target} is marked executed")
    return 0


def _ad_action_label_for_validation(row: dict) -> str:
    action = str(
        row.get("suggested_action")
        or row.get("scale_action")
        or row.get("copy_action_line")
        or ""
    ).strip()
    if "否" in action and "不直接否" not in action:
        return "否定精准"
    if "暂停" in action and "ASIN" in action.upper():
        return "暂停 ASIN 定向"
    if "加价" in action or "提高竞价" in action:
        return "加价"
    if "降竞价" in action or "降价竞价" in action:
        return "降竞价"
    if "降价" in action:
        return "降价"
    if "保留" in action:
        return "保留观察"
    return "观察"


def _is_pending_ad_workbench_row(row: dict) -> bool:
    if str(row.get("confirmed_status") or "") == "已执行":
        return False
    return _ad_action_label_for_validation(row) not in {"观察", "保留观察"}


def _ad_workbench_rows_from_snapshot(snapshot: dict) -> list[dict]:
    rows: list[dict] = []
    for key in ["html_search_term_processing_queue_rows", "scale_keyword_rows"]:
        value = snapshot.get(key) or []
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    groups = snapshot.get("today_action_groups") or {}
    if isinstance(groups, dict):
        group_rows = groups.get("广告动作") or []
        if isinstance(group_rows, list):
            rows.extend(row for row in group_rows if isinstance(row, dict))
    return rows


def _safe_run_has_pending_ad_workbench_rows(data: dict) -> bool:
    results = data.get("marketplace_results") or []
    if not isinstance(results, list):
        return False
    for result in results:
        if not isinstance(result, dict):
            continue
        snapshot = result.get("report_view_snapshot") or {}
        if not isinstance(snapshot, dict):
            continue
        if any(_is_pending_ad_workbench_row(row) for row in _ad_workbench_rows_from_snapshot(snapshot)):
            return True
    return False


def _validate_latest_recommendations_ad_area(text: str, *, has_pending_ad_rows: bool) -> int:
    if AD_COPY_ANCHOR not in text:
        return fail("latest_recommendations.html missing today-ad-actions-all anchor")
    if has_pending_ad_rows:
        if "复制到广告后台" not in text:
            return fail("latest_recommendations.html missing copy area for pending ad rows")
    else:
        if "待确认 0" not in text:
            return fail("latest_recommendations.html missing compact zero-pending ad status")
        if "复制到广告后台" in text:
            return fail("latest_recommendations.html shows copy area when no pending ad rows")
    return 0


def run_step(args: list[str], extra_env: dict[str, str] | None = None) -> int:
    print("[run]", " ".join(args), flush=True)
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(args, cwd=ROOT, env=env)
    print("[exit]", completed.returncode, flush=True)
    return completed.returncode


def fail(message: str) -> int:
    print(f"[fail] {message}", flush=True)
    return 1


def git_text(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def git_bytes(args: list[str]) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def git_lines(args: list[str]) -> list[str]:
    return [line for line in git_text(args).splitlines() if line.strip()]


def workspace_fingerprint() -> dict[str, object]:
    head = git_text(["rev-parse", "HEAD"]).strip()
    tracked_changed = git_lines(["diff", "--name-only", "HEAD", "--"])
    untracked = git_lines(["ls-files", "--others", "--exclude-standard"])
    changed_paths = sorted(set(tracked_changed + untracked))
    status_lines = git_lines(["status", "--porcelain=v1", "--untracked-files=all"])

    digest = sha256()
    digest.update(b"git-head\0")
    digest.update(head.encode("utf-8"))
    digest.update(b"\0tracked-diff\0")
    digest.update(git_bytes(["diff", "--binary", "HEAD", "--"]))
    digest.update(b"\0untracked-files\0")
    for relative_path in sorted(untracked):
        path = ROOT / relative_path
        digest.update(relative_path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(sha256(path.read_bytes()).hexdigest().encode("ascii"))
        digest.update(b"\0")

    return {
        "git_head": head,
        "workspace_hash": digest.hexdigest(),
        "changed_paths": changed_paths,
        "status_porcelain": status_lines,
    }


def _analysis_summary(safe_dir: Path) -> dict[str, object]:
    analysis_path = safe_dir / "latest_analysis.json"
    try:
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception:
        return {"report_date": "", "marketplaces": []}
    results = data.get("marketplace_results") or []
    marketplaces = []
    if isinstance(results, list):
        marketplaces = sorted(
            {
                str(result.get("marketplace") or "").upper()
                for result in results
                if isinstance(result, dict) and result.get("marketplace")
            }
        )
    return {
        "report_date": str(data.get("report_date") or ""),
        "marketplaces": marketplaces,
    }


def write_validation_receipt(
    safe_dir: Path,
    *,
    pytest_exit_code: int,
    safe_run_exit_code: int,
    output_validation_exit_code: int,
) -> None:
    state = workspace_fingerprint()
    payload = {
        "schema_version": VALIDATION_RECEIPT_SCHEMA_VERSION,
        "result": "passed",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "pytest_exit_code": pytest_exit_code,
        "safe_run_exit_code": safe_run_exit_code,
        "output_validation_exit_code": output_validation_exit_code,
        "safe_run_dir": str(safe_dir),
        **_analysis_summary(safe_dir),
        **state,
    }
    VALIDATION_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    VALIDATION_RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[check] wrote validation receipt: {VALIDATION_RECEIPT}", flush=True)


def clear_validation_receipt() -> None:
    if VALIDATION_RECEIPT.exists():
        VALIDATION_RECEIPT.unlink()


def validate_safe_run_outputs(safe_dir: Path) -> int:
    missing = [name for name in [*REQUIRED_FILES, *REQUIRED_ASSET_FILES] if not (safe_dir / name).exists()]
    if missing:
        return fail(f"safe-run missing files: {', '.join(missing)}")
    for name in REQUIRED_ASSET_FILES:
        if (safe_dir / name).stat().st_size <= 0:
            return fail(f"safe-run asset is empty: {name}")

    excel_files = sorted(safe_dir.glob("amazon_ops_report_*.xlsx"))
    if not excel_files:
        return fail("safe-run missing amazon_ops_report_*.xlsx")

    analysis_path = safe_dir / "latest_analysis.json"
    try:
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return fail(f"cannot read latest_analysis.json: {exc}")

    report_date = str(data.get("report_date") or "").strip()
    if not report_date:
        return fail("latest_analysis.json missing report_date")

    results = data.get("marketplace_results")
    if not isinstance(results, list) or len(results) != 3:
        return fail("latest_analysis.json must contain three marketplace_results")
    marketplaces = {str(result.get("marketplace") or "").upper() for result in results}
    if marketplaces != {"UK", "US", "DE"}:
        return fail(f"marketplace_results must contain UK, US, DE; got {sorted(marketplaces)}")
    has_pending_ad_rows = _safe_run_has_pending_ad_workbench_rows(data)

    import_summary = data.get("import_summary") or {}
    for key in ["ads_imported_rows", "erp_imported_rows"]:
        if key not in import_summary:
            return fail(f"import_summary missing {key}")

    for result in results:
        marketplace = str(result.get("marketplace") or "").upper()
        summary = result.get("summary") or {}
        if not summary.get("report_date"):
            return fail(f"{marketplace} summary missing report_date")
        snapshot = result.get("report_view_snapshot") or {}
        missing_snapshot = sorted(REQUIRED_SNAPSHOT_KEYS.difference(snapshot.keys()))
        if missing_snapshot:
            return fail(f"{marketplace} report_view_snapshot missing {', '.join(missing_snapshot)}")
        frontend_rows = snapshot.get("frontend_check_queue_rows") or []
        if not isinstance(frontend_rows, list):
            return fail(f"{marketplace} frontend_check_queue_rows must be a list")
        code = _validate_frontend_rows(marketplace, frontend_rows)
        if code != 0:
            return code
        code = _validate_ad_observation_rows(marketplace, _iter_ad_action_rows(snapshot))
        if code != 0:
            return code

    try:
        workbook = load_workbook(excel_files[-1], read_only=True)
    except Exception as exc:
        return fail(f"cannot open Excel workbook: {exc}")
    try:
        if "Metrics_Validation" not in workbook.sheetnames:
            return fail("Excel workbook missing Metrics_Validation sheet")
    finally:
        workbook.close()

    for name in REQUIRED_FILES:
        if not name.endswith(".html"):
            continue
        text = (safe_dir / name).read_text(encoding="utf-8", errors="replace")
        if report_date not in text:
            return fail(f"{name} does not show report_date {report_date}")
        marker = next((item for item in HTML_ERROR_MARKERS if item in text), "")
        if marker:
            return fail(f"{name} contains error marker {marker}")
        for required_marker in REQUIRED_HTML_MARKERS.get(name, []):
            if required_marker not in text:
                return fail(f"{name} missing required marker {required_marker}")
        if name == "latest_recommendations.html":
            code = _validate_latest_recommendations_ad_area(text, has_pending_ad_rows=has_pending_ad_rows)
            if code != 0:
                return code
        for forbidden_marker in FORBIDDEN_HTML_MARKERS.get(name, []):
            if forbidden_marker in text:
                return fail(f"{name} contains forbidden marker {forbidden_marker}")

    print(f"[check] safe-run outputs validated: {safe_dir}", flush=True)
    return 0


def main() -> int:
    clear_validation_receipt()
    python = sys.executable
    code = run_step([python, "-m", "pytest"])
    if code != 0:
        return fail("pytest failed")
    pytest_exit_code = code

    safe_run_id = f"showcase_{int(time.time() * 1000)}_{os.getpid()}"
    safe_dir = SAFE_RUN_ROOT / safe_run_id
    if safe_dir.exists():
        return fail(f"safe-run output directory already exists: {safe_dir}")

    code = run_step(
        [python, "main.py", "--marketplace", "ALL", "--safe-run"],
        extra_env={"AMAZON_OPS_SAFE_RUN_ID": safe_run_id},
    )
    if code != 0:
        return fail("ALL safe-run failed")
    safe_run_exit_code = code

    if not safe_dir.exists():
        return fail(f"cannot find expected safe-run output directory: {safe_dir}")

    code = validate_safe_run_outputs(safe_dir)
    if code != 0:
        return code
    output_validation_exit_code = code

    write_validation_receipt(
        safe_dir,
        pytest_exit_code=pytest_exit_code,
        safe_run_exit_code=safe_run_exit_code,
        output_validation_exit_code=output_validation_exit_code,
    )
    print("[done] showcase MVP validation passed: pytest, ALL safe-run, and generated outputs checked", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
