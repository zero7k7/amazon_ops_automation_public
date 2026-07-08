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

from scripts.validate_showcase_mvp import validate_safe_run_outputs

OUTPUT = ROOT / "data" / "output"
LATEST_ANALYSIS = OUTPUT / "latest_analysis.json"
COST_AUDIT = OUTPUT / "cost_config_diff_summary.json"
UNKNOWN_AUDIT = OUTPUT / "unknown_inbox_audit.json"
UNKNOWN_INBOX_DIR = ROOT / "data" / "inbox" / "_unknown"
OWNER_DRAFT = ROOT / "docs" / "parallel_lock_owners.draft.json"
OWNER_MANIFEST = ROOT / "docs" / "parallel_lock_owners.json"
BUSINESS_CONFIRMATION = ROOT / "docs" / "business_review_confirmation.json"
JSON_OUTPUT = OUTPUT / "showcase_status_report.json"
MARKDOWN_OUTPUT = OUTPUT / "showcase_status_report.md"
STRICT_READINESS_SCRIPT = ROOT / "scripts" / "check_showcase_commit_readiness.py"
BUSINESS_INBOX_SUFFIXES = {".csv", ".xlsx"}

REQUIRED_FORMAL_OUTPUTS = [
    "summary.html",
    "latest_recommendations.html",
    "latest_recommendations.md",
    "dashboard.html",
    "uk_report.html",
    "us_report.html",
    "de_report.html",
    "latest_analysis.json",
    "marketplace_summary.md",
]


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _latest_excel() -> str:
    files = sorted(OUTPUT.glob("amazon_ops_report_*.xlsx"), key=lambda path: path.stat().st_mtime, reverse=True)
    return str(files[0]) if files else ""


def _marketplaces(analysis: dict[str, Any]) -> list[str]:
    results = analysis.get("marketplace_results")
    if not isinstance(results, list):
        return []
    return sorted({str(row.get("marketplace") or "").upper() for row in results if isinstance(row, dict) and row.get("marketplace")})


def _missing_outputs() -> list[str]:
    missing = [name for name in REQUIRED_FORMAL_OUTPUTS if not (OUTPUT / name).exists()]
    if not _latest_excel():
        missing.append("amazon_ops_report_*.xlsx")
    return missing


def _unknown_inbox_blocker_files() -> list[str]:
    if not UNKNOWN_INBOX_DIR.exists():
        return []
    files = [
        path
        for path in UNKNOWN_INBOX_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in BUSINESS_INBOX_SUFFIXES
    ]
    return sorted(str(path) for path in files)


def _unknown_audit_details(unknown_audit: list[Any], blocker_files: list[str]) -> list[dict[str, str]]:
    by_path: dict[str, dict[str, Any]] = {}
    for row in unknown_audit:
        if not isinstance(row, dict):
            continue
        for key in ["original_path", "original_filename"]:
            value = str(row.get(key) or "")
            if value:
                by_path[value] = row

    details: list[dict[str, str]] = []
    for file_path in blocker_files:
        row = by_path.get(file_path) or by_path.get(Path(file_path).name) or {}
        details.append(
            {
                "file": file_path,
                "likely_report_type": str(row.get("likely_report_type") or "unknown"),
                "likely_marketplace": str(row.get("likely_marketplace") or row.get("detected_marketplace") or "UNKNOWN"),
                "business_interpretation": str(row.get("business_interpretation") or row.get("reason") or ""),
                "recommendation": str(row.get("recommendation") or ""),
            }
        )
    return details


def _validate_existing_outputs() -> dict[str, Any]:
    code = validate_safe_run_outputs(OUTPUT)
    return {"passed": code == 0, "exit_code": code}


def _cost_product_record_count(cost_audit: dict[str, Any]) -> int:
    product_diff = ((cost_audit.get("sheets") or {}).get("product_cost_config") or {}).get("keyed_diff") or {}
    if "changed_record_count" in product_diff:
        return int(product_diff.get("changed_record_count") or 0)
    records = product_diff.get("sample_changed_records") or []
    return len(records) if isinstance(records, list) else 0


def _cost_config_sample_records(cost_audit: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    product_diff = ((cost_audit.get("sheets") or {}).get("product_cost_config") or {}).get("keyed_diff") or {}
    records = product_diff.get("sample_changed_records") or []
    if not isinstance(records, list):
        return []

    samples: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        raw_changes = record.get("changed_fields") or []
        changed_fields: list[str] = []
        if isinstance(raw_changes, list):
            for change in raw_changes:
                if isinstance(change, dict) and change.get("field"):
                    changed_fields.append(str(change["field"]))
        samples.append(
            {
                "marketplace": str(record.get("marketplace") or ""),
                "sku": str(record.get("sku") or ""),
                "asin": str(record.get("asin") or ""),
                "product_name": str(record.get("product_name") or ""),
                "changed_fields": changed_fields,
                "risk_hints": _cost_config_risk_hints(changed_fields),
            }
        )
        if len(samples) >= limit:
            break
    return samples


def _cost_config_risk_hints(changed_fields: Sequence[str]) -> list[str]:
    fields = set(changed_fields)
    hints: list[str] = []
    margin_fields = {
        "target_acos",
        "suggested_target_acos",
        "break_even_acos",
        "profit_after_10pct_ads",
        "profit_before_ads",
        "profit_margin_after_10pct_ads",
        "roi_after_10pct_ads",
    }
    cost_fields = {
        "amazon_fees_excl_ads",
        "digital_tax",
        "first_leg_cost_local",
        "landed_cost_excl_amazon",
        "purchase_cost_local",
        "referral_fee",
        "return_fee_estimate",
        "storage_fee_estimate",
        "total_cost_before_ads",
        "vat",
    }
    if fields & {"selling_price"}:
        hints.append("售价变化会影响利润和 ACOS 目标")
    if fields & {"current_inventory", "inventory_note"}:
        hints.append("库存变化会影响补货和广告强度判断")
    if fields & margin_fields:
        hints.append("利润或 ACOS 口径变化会影响广告动作门槛")
    if fields & cost_fields:
        hints.append("成本费用变化会影响毛利和盈亏平衡判断")
    return hints


def _owner_draft_groups(owner_draft: dict[str, Any]) -> list[dict[str, Any]]:
    owners = owner_draft.get("owners")
    if not isinstance(owners, list):
        return []

    groups: list[dict[str, Any]] = []
    for entry in owners:
        if not isinstance(entry, dict):
            continue
        files = entry.get("files")
        groups.append(
            {
                "work_package": str(entry.get("work_package") or ""),
                "owner": str(entry.get("owner") or ""),
                "file_count": len(files) if isinstance(files, list) else 0,
                "confirmation_status": str(entry.get("confirmation_status") or ""),
            }
        )
    return groups


def _business_confirmation_valid(confirmation: dict[str, Any]) -> bool:
    flags = confirmation.get("allowed_strict_flags") or {}
    if not isinstance(flags, dict):
        return False
    required_flags = [
        "manual_config_confirmed",
        "business_review_confirmed",
        "parallel_lock_owner_confirmed",
        "daily_update_verified",
    ]
    return (
        confirmation.get("confirmation_status") == "confirmed"
        and all(bool(flags.get(flag)) for flag in required_flags)
    )


def _run_strict_readiness() -> dict[str, Any]:
    if not STRICT_READINESS_SCRIPT.exists():
        return {
            "passed": False,
            "exit_code": 127,
            "summary": f"missing script: {STRICT_READINESS_SCRIPT}",
        }

    command = [sys.executable, str(STRICT_READINESS_SCRIPT), "--strict"]
    confirmation = _load_json(BUSINESS_CONFIRMATION, {})
    if isinstance(confirmation, dict) and _business_confirmation_valid(confirmation):
        command.extend(
            [
                "--manual-config-confirmed",
                "--business-review-confirmed",
                "--parallel-lock-owner-confirmed",
                "--daily-update-verified",
            ]
        )

    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "summary": output_lines[-5:],
    }


def build_status_payload() -> dict[str, Any]:
    analysis = _load_json(LATEST_ANALYSIS, {})
    cost_audit = _load_json(COST_AUDIT, {})
    unknown_audit = _load_json(UNKNOWN_AUDIT, [])
    owner_draft = _load_json(OWNER_DRAFT, {})
    owner_manifest = _load_json(OWNER_MANIFEST, {})
    business_confirmation = _load_json(BUSINESS_CONFIRMATION, {})
    if not isinstance(analysis, dict):
        analysis = {}
    if not isinstance(cost_audit, dict):
        cost_audit = {}
    if not isinstance(unknown_audit, list):
        unknown_audit = []
    if not isinstance(owner_draft, dict):
        owner_draft = {}
    if not isinstance(owner_manifest, dict):
        owner_manifest = {}
    if not isinstance(business_confirmation, dict):
        business_confirmation = {}

    missing_outputs = _missing_outputs()
    output_validation = _validate_existing_outputs() if not missing_outputs else {"passed": False, "exit_code": 1}
    marketplaces = _marketplaces(analysis)
    report_date = str(analysis.get("report_date") or "")
    cost_changed_cells = int(cost_audit.get("total_changed_cells") or 0)
    cost_product_records = _cost_product_record_count(cost_audit)
    audit_unknown_blockers = [
        row for row in unknown_audit if isinstance(row, dict) and row.get("blocks_daily_update")
    ]
    unknown_blocker_files = _unknown_inbox_blocker_files()
    unknown_details = _unknown_audit_details(unknown_audit, unknown_blocker_files)
    cost_sample_records = _cost_config_sample_records(cost_audit)
    owner_draft_groups = _owner_draft_groups(owner_draft)
    owner_manifest_groups = _owner_draft_groups(owner_manifest)
    business_confirmation_valid = _business_confirmation_valid(business_confirmation)
    strict_readiness = _run_strict_readiness()

    showcase_ready = bool(
        not missing_outputs
        and report_date
        and marketplaces == ["DE", "UK", "US"]
        and output_validation["passed"]
    )
    daily_blocked = bool(unknown_blocker_files)
    business_submit_ready = (
        showcase_ready
        and (cost_changed_cells == 0 or business_confirmation_valid)
        and not daily_blocked
        and bool(strict_readiness["passed"])
    )

    return {
        "showcase_ready": showcase_ready,
        "business_submit_ready": business_submit_ready,
        "daily_update_blocked": daily_blocked,
        "report_date": report_date,
        "marketplaces": marketplaces,
        "missing_outputs": missing_outputs,
        "output_validation_passed": bool(output_validation["passed"]),
        "output_validation_exit_code": output_validation["exit_code"],
        "latest_excel": _latest_excel(),
        "cost_config_changed_cells": cost_changed_cells,
        "cost_config_changed_product_records": cost_product_records,
        "cost_config_sample_records": cost_sample_records,
        "unknown_inbox_blockers": len(unknown_blocker_files),
        "unknown_inbox_files": unknown_blocker_files,
        "unknown_inbox_details": unknown_details,
        "unknown_inbox_audit_blockers": len(audit_unknown_blockers),
        "owner_draft_confirmation_status": str(owner_draft.get("confirmation_status") or ""),
        "owner_draft_groups": owner_draft_groups,
        "owner_manifest_confirmation_status": str(owner_manifest.get("confirmation_status") or ""),
        "owner_manifest_groups": owner_manifest_groups,
        "business_confirmation_status": str(business_confirmation.get("confirmation_status") or ""),
        "business_confirmation_valid": business_confirmation_valid,
        "business_confirmation_file": str(BUSINESS_CONFIRMATION),
        "strict_readiness_passed": bool(strict_readiness["passed"]),
        "strict_readiness_exit_code": strict_readiness["exit_code"],
        "strict_readiness_summary": strict_readiness["summary"],
        "required_next_actions": _required_next_actions(
            cost_changed_cells,
            business_confirmation_valid,
            daily_blocked,
            missing_outputs,
            bool(output_validation["passed"]),
            bool(strict_readiness["passed"]),
        ),
        "evidence_files": {
            "latest_analysis": str(LATEST_ANALYSIS),
            "cost_audit": str(COST_AUDIT),
            "unknown_inbox_audit": str(UNKNOWN_AUDIT),
            "unknown_inbox_dir": str(UNKNOWN_INBOX_DIR),
            "parallel_owner_draft": str(OWNER_DRAFT),
            "parallel_owner_manifest": str(OWNER_MANIFEST),
            "business_confirmation": str(BUSINESS_CONFIRMATION),
            "strict_readiness": str(STRICT_READINESS_SCRIPT),
            "showcase_contract": str(ROOT / "docs" / "showcase_goal_contract.md"),
        },
    }


def _required_next_actions(
    cost_changed_cells: int,
    business_confirmation_valid: bool,
    daily_blocked: bool,
    missing_outputs: list[str],
    output_validation_passed: bool,
    strict_readiness_passed: bool,
) -> list[str]:
    actions: list[str] = []
    if missing_outputs:
        actions.append("先运行 scripts/validate_showcase_mvp.py 生成并验证展示产物。")
    elif not output_validation_passed:
        actions.append("正式展示产物内容校验失败，先运行 scripts/validate_showcase_mvp.py 并检查 HTML/Excel/JSON。")
    if daily_blocked:
        actions.append("先查看 data/output/unknown_inbox_audit.md；若确认只是参考资料，运行 scripts/quarantine_reviewed_unknown_inbox.py --apply 后再跑 preflight。")
    if cost_changed_cells and not business_confirmation_valid:
        actions.append("业务 owner 按 docs/business_confirmation_template.md 确认 config/product_cost_config.xlsx，并保留 docs/business_review_confirmation.json。")
    if not strict_readiness_passed:
        actions.append("处理 scripts/check_showcase_commit_readiness.py --strict 的失败项，再进入提交。")
    if not actions:
        actions.append("按 docs/showcase_commit_groups.md 分组准备提交。")
    return actions


def build_markdown(payload: dict[str, Any]) -> str:
    status = "可以展示" if payload["showcase_ready"] else "不能展示"
    submit_status = "可以业务提交" if payload["business_submit_ready"] else "不能业务提交"
    lines = [
        "# 展示状态报告",
        "",
        f"- 展示状态：{status}",
        f"- 业务提交状态：{submit_status}",
        f"- daily update 阻塞：{'是' if payload['daily_update_blocked'] else '否'}",
        f"- 报告日期：{payload.get('report_date') or 'N/A'}",
        f"- 站点：{', '.join(payload.get('marketplaces') or []) or 'N/A'}",
        f"- 成本配置差异单元格：{payload.get('cost_config_changed_cells')}",
        f"- 成本配置变化产品记录：{payload.get('cost_config_changed_product_records')}",
        f"- 业务确认记录：{'有效' if payload.get('business_confirmation_valid') else '未确认'}",
        f"- unknown inbox 阻塞文件数：{payload.get('unknown_inbox_blockers')}",
        f"- 展示产物内容校验：{'通过' if payload.get('output_validation_passed') else '未通过'}",
        f"- 展示产物内容校验退出码：{payload.get('output_validation_exit_code')}",
        f"- 严格提交门禁：{'通过' if payload.get('strict_readiness_passed') else '未通过'}",
        f"- 严格提交门禁退出码：{payload.get('strict_readiness_exit_code')}",
        "",
    ]
    missing = payload.get("missing_outputs") or []
    if missing:
        lines.extend(["## 缺失展示产物", "", *[f"- {item}" for item in missing], ""])

    unknown_files = payload.get("unknown_inbox_files") or []
    if unknown_files:
        lines.extend(["## unknown inbox 阻塞文件", "", *[f"- {item}" for item in unknown_files], ""])

    unknown_details = payload.get("unknown_inbox_details") or []
    if unknown_details:
        lines.extend(["## unknown inbox 审计结论", ""])
        for row in unknown_details:
            lines.append(f"- 文件：{row.get('file')}")
            lines.append(f"  类型：{row.get('likely_report_type')}")
            lines.append(f"  站点：{row.get('likely_marketplace')}")
            if row.get("business_interpretation"):
                lines.append(f"  判断：{row.get('business_interpretation')}")
            if row.get("recommendation"):
                lines.append(f"  建议：{row.get('recommendation')}")
        lines.append("")

    cost_samples = payload.get("cost_config_sample_records") or []
    if cost_samples:
        lines.extend(["## 成本配置样本", ""])
        for row in cost_samples:
            identity = " / ".join(
                item
                for item in [
                    row.get("marketplace"),
                    row.get("sku"),
                    row.get("asin"),
                    row.get("product_name"),
                ]
                if item
            )
            lines.append(f"- {identity or 'UNKNOWN'}")
            changed_fields = row.get("changed_fields") or []
            if changed_fields:
                lines.append(f"  变化字段：{', '.join(changed_fields)}")
            risk_hints = row.get("risk_hints") or []
            if risk_hints:
                lines.append(f"  风险提示：{'; '.join(risk_hints)}")
        lines.append("")

    owner_groups = payload.get("owner_draft_groups") or []
    if owner_groups:
        lines.extend(["## 并行 owner 草案", ""])
        if payload.get("owner_draft_confirmation_status"):
            lines.append(f"- 草案状态：{payload.get('owner_draft_confirmation_status')}")
        for row in owner_groups:
            lines.append(
                "- "
                + f"{row.get('work_package') or 'UNKNOWN'}: "
                + f"{row.get('owner') or 'UNKNOWN'}, "
                + f"文件数 {row.get('file_count')}, "
                + f"确认状态 {row.get('confirmation_status') or 'UNKNOWN'}"
            )
        lines.append("")

    owner_manifest_groups = payload.get("owner_manifest_groups") or []
    if owner_manifest_groups:
        lines.extend(["## 并行 owner 正式清单", ""])
        if payload.get("owner_manifest_confirmation_status"):
            lines.append(f"- 清单状态：{payload.get('owner_manifest_confirmation_status')}")
        for row in owner_manifest_groups:
            lines.append(
                "- "
                + f"{row.get('work_package') or 'UNKNOWN'}: "
                + f"{row.get('owner') or 'UNKNOWN'}, "
                + f"文件数 {row.get('file_count')}, "
                + f"确认状态 {row.get('confirmation_status') or 'UNKNOWN'}"
            )
        lines.append("")

    if payload.get("business_confirmation_file"):
        lines.extend(
            [
                "## 业务确认记录",
                "",
                f"- 状态：{payload.get('business_confirmation_status') or 'N/A'}",
                f"- 有效：{'是' if payload.get('business_confirmation_valid') else '否'}",
                f"- 文件：`{payload.get('business_confirmation_file')}`",
                "",
            ]
        )

    strict_summary = payload.get("strict_readiness_summary") or []
    if strict_summary:
        lines.extend(["## 严格提交门禁摘要", "", *[f"- {item}" for item in strict_summary], ""])

    lines.extend(
        [
            "## 下一步",
            "",
            *[f"{idx}. {item}" for idx, item in enumerate(payload.get("required_next_actions") or [], start=1)],
            "",
            "## 证据文件",
            "",
        ]
    )
    for label, path in (payload.get("evidence_files") or {}).items():
        lines.append(f"- {label}: `{path}`")
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MARKDOWN_OUTPUT.write_text(build_markdown(payload), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a quick showcase readiness status report from existing evidence files.")
    parser.add_argument("--fail-if-not-showcase-ready", action="store_true")
    parser.add_argument("--fail-if-not-business-ready", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_status_payload()
    write_outputs(payload)
    print(f"[check] showcase_ready: {payload['showcase_ready']}", flush=True)
    print(f"[check] business_submit_ready: {payload['business_submit_ready']}", flush=True)
    print(f"[check] wrote: {JSON_OUTPUT}", flush=True)
    print(f"[check] wrote: {MARKDOWN_OUTPUT}", flush=True)
    if args.fail_if_not_showcase_ready and not payload["showcase_ready"]:
        print("[fail] showcase status report is not showcase ready", flush=True)
        return 1
    if args.fail_if_not_business_ready and not payload["business_submit_ready"]:
        print("[fail] showcase status report is not business submit ready", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
