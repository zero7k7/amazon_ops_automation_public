from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "data" / "output"
STATUS_REPORT = OUTPUT / "showcase_status_report.json"
COST_AUDIT = OUTPUT / "cost_config_diff_summary.json"
UNKNOWN_AUDIT = OUTPUT / "unknown_inbox_audit.json"
PACKET_JSON = OUTPUT / "business_review_packet.json"
PACKET_MARKDOWN = OUTPUT / "business_review_packet.md"


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _to_float(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text or text.startswith("="):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _change_lookup(row: dict[str, Any]) -> dict[str, dict[str, str]]:
    changes = row.get("changed_fields") or []
    if not isinstance(changes, list):
        return {}
    return {
        str(item.get("field") or ""): item
        for item in changes
        if isinstance(item, dict) and item.get("field")
    }


def _format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _risk_rows(cost_audit: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    product_diff = ((cost_audit.get("sheets") or {}).get("product_cost_config") or {}).get("keyed_diff") or {}
    inventory_diff = ((cost_audit.get("sheets") or {}).get("SKU匹配检查") or {}).get("keyed_diff") or {}
    inventory_by_key = {
        str(row.get("key") or ""): _change_lookup(row)
        for row in inventory_diff.get("sample_changed_records", []) or []
        if isinstance(row, dict)
    }

    rows: list[dict[str, Any]] = []
    for record in product_diff.get("sample_changed_records", []) or []:
        if not isinstance(record, dict):
            continue
        changes = _change_lookup(record)
        inventory_changes = inventory_by_key.get(str(record.get("key") or ""), {})
        score = 0
        reasons: list[str] = []
        evidence: list[str] = []

        price_change = changes.get("selling_price") or inventory_changes.get("selling_price")
        price_before = _to_float((price_change or {}).get("before"))
        price_after = _to_float((price_change or {}).get("after"))
        if price_before is not None and price_after is not None and price_before:
            price_delta = (price_after - price_before) / abs(price_before)
            if abs(price_delta) >= 0.30:
                score += 35
                reasons.append("售价变动超过 30%")
            elif abs(price_delta) >= 0.15:
                score += 20
                reasons.append("售价变动超过 15%")
            if abs(price_delta) >= 0.15:
                evidence.append(f"selling_price {price_before:g} -> {price_after:g} ({_format_pct(price_delta)})")

        target_change = changes.get("suggested_target_acos") or inventory_changes.get("suggested_target_acos")
        target_after = _to_float((target_change or {}).get("after"))
        if target_after is not None:
            if target_after <= 0:
                score += 35
                reasons.append("建议 target ACOS 变为 0")
            elif target_after < 0.05:
                score += 25
                reasons.append("建议 target ACOS 低于 5%")
            if target_after < 0.05:
                evidence.append(f"suggested_target_acos {target_after:.4f}")

        profit_after_change = changes.get("profit_after_10pct_ads") or inventory_changes.get("profit_after_10pct_ads")
        profit_after = _to_float((profit_after_change or {}).get("after"))
        if profit_after is not None and profit_after < 0:
            score += 35
            reasons.append("10% 广告费后利润为负")
            evidence.append(f"profit_after_10pct_ads {profit_after:g}")

        profit_before_change = changes.get("profit_before_ads") or inventory_changes.get("profit_before_ads")
        profit_before = _to_float((profit_before_change or {}).get("after"))
        if profit_before is not None and profit_before < 0:
            score += 25
            reasons.append("广告前利润为负")
            evidence.append(f"profit_before_ads {profit_before:g}")

        inventory_change = changes.get("current_inventory") or inventory_changes.get("current_inventory")
        inventory_before = _to_float((inventory_change or {}).get("before"))
        inventory_after = _to_float((inventory_change or {}).get("after"))
        if inventory_before is not None and inventory_after is not None:
            if inventory_before <= 0 < inventory_after:
                score += 25
                reasons.append("库存从 0 变为有货")
                evidence.append(f"current_inventory {inventory_before:g} -> {inventory_after:g}")
            elif inventory_before > 0 and inventory_after <= 0:
                score += 25
                reasons.append("库存从有货变为 0")
                evidence.append(f"current_inventory {inventory_before:g} -> {inventory_after:g}")

        total_cost_change = changes.get("total_cost_before_ads") or inventory_changes.get("total_cost_before_ads")
        total_cost_after = _to_float((total_cost_change or {}).get("after"))
        if price_after is not None and total_cost_after is not None and price_after < total_cost_after:
            score += 30
            reasons.append("售价低于广告前总成本")
            evidence.append(f"price {price_after:g} < total_cost_before_ads {total_cost_after:g}")

        if not score:
            continue
        rows.append(
            {
                "score": score,
                "marketplace": str(record.get("marketplace") or ""),
                "sku": str(record.get("sku") or ""),
                "asin": str(record.get("asin") or ""),
                "product_name": str(record.get("product_name") or ""),
                "reasons": list(dict.fromkeys(reasons)),
                "evidence": list(dict.fromkeys(evidence)),
            }
        )
    return sorted(rows, key=lambda item: (-int(item["score"]), item["marketplace"], item["sku"]))[:limit]


def _strict_blockers(status: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for line in status.get("strict_readiness_summary") or []:
        text = str(line)
        marker = "strict mode requires confirmations:"
        if marker not in text:
            continue
        tail = text.split(marker, 1)[1]
        blockers.extend(item.strip() for item in tail.split(";") if item.strip())
    return blockers


def _cost_summary(cost_audit: dict[str, Any]) -> dict[str, Any]:
    product_diff = ((cost_audit.get("sheets") or {}).get("product_cost_config") or {}).get("keyed_diff") or {}
    return {
        "changed_cells": int(cost_audit.get("total_changed_cells") or 0),
        "changed_product_records": int(product_diff.get("changed_record_count") or 0),
        "changed_marketplaces": product_diff.get("changed_marketplaces") or {},
        "high_risk_rows": _risk_rows(cost_audit),
    }


def _refresh_status_report() -> None:
    from scripts import build_showcase_status_report as status_report

    status_report.ROOT = ROOT
    status_report.OUTPUT = OUTPUT
    status_report.LATEST_ANALYSIS = OUTPUT / "latest_analysis.json"
    status_report.COST_AUDIT = COST_AUDIT
    status_report.UNKNOWN_AUDIT = UNKNOWN_AUDIT
    status_report.UNKNOWN_INBOX_DIR = ROOT / "data" / "inbox" / "_unknown"
    status_report.OWNER_DRAFT = ROOT / "docs" / "parallel_lock_owners.draft.json"
    status_report.OWNER_MANIFEST = ROOT / "docs" / "parallel_lock_owners.json"
    status_report.BUSINESS_CONFIRMATION = ROOT / "docs" / "business_review_confirmation.json"
    status_report.JSON_OUTPUT = STATUS_REPORT
    status_report.MARKDOWN_OUTPUT = OUTPUT / "showcase_status_report.md"
    status_report.write_outputs(status_report.build_status_payload())


def build_packet() -> dict[str, Any]:
    status = _load_json(STATUS_REPORT, {})
    cost_audit = _load_json(COST_AUDIT, {})
    unknown_audit = _load_json(UNKNOWN_AUDIT, [])
    if not isinstance(status, dict):
        status = {}
    if not isinstance(cost_audit, dict):
        cost_audit = {}
    if not isinstance(unknown_audit, list):
        unknown_audit = []
    cost_config = _cost_summary(cost_audit)

    return {
        "showcase_ready": bool(status.get("showcase_ready")),
        "business_submit_ready": bool(status.get("business_submit_ready")),
        "daily_update_blocked": bool(status.get("daily_update_blocked")),
        "report_date": str(status.get("report_date") or ""),
        "marketplaces": status.get("marketplaces") or [],
        "strict_readiness_passed": bool(status.get("strict_readiness_passed")),
        "strict_readiness_exit_code": int(status.get("strict_readiness_exit_code") or 0),
        "strict_blockers": _strict_blockers(status),
        "unknown_inbox_details": status.get("unknown_inbox_details") or [],
        "unknown_audit_count": len([row for row in unknown_audit if isinstance(row, dict)]),
        "cost_config_changed_cells": int(cost_config.get("changed_cells") or 0),
        "cost_config_changed_product_records": int(cost_config.get("changed_product_records") or 0),
        "cost_config": cost_config,
        "owner_manifest_confirmation_status": str(status.get("owner_manifest_confirmation_status") or ""),
        "business_confirmation_status": str(status.get("business_confirmation_status") or ""),
        "business_confirmation_valid": bool(status.get("business_confirmation_valid")),
        "business_confirmation_file": str(status.get("business_confirmation_file") or ""),
        "evidence_files": {
            "showcase_status_report": str(STATUS_REPORT),
            "cost_config_diff_summary": str(COST_AUDIT),
            "cost_config_diff_markdown": str(OUTPUT / "cost_config_diff_summary.md"),
            "unknown_inbox_audit": str(UNKNOWN_AUDIT),
            "business_confirmation": str(status.get("business_confirmation_file") or ROOT / "docs" / "business_review_confirmation.json"),
            "business_confirmation_template": str(ROOT / "docs" / "business_confirmation_template.md"),
        },
    }


def _line_items(items: Sequence[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- 无"]


def _markdown_escape(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def build_markdown(packet: dict[str, Any]) -> str:
    cost = packet.get("cost_config") or {}
    lines = [
        "# 业务确认包",
        "",
        f"- 展示状态：{'可以展示' if packet.get('showcase_ready') else '不能展示'}",
        f"- 业务提交状态：{'可以业务提交' if packet.get('business_submit_ready') else '不能业务提交'}",
        f"- daily update 阻塞：{'是' if packet.get('daily_update_blocked') else '否'}",
        f"- 报告日期：{packet.get('report_date') or 'N/A'}",
        f"- 站点：{', '.join(packet.get('marketplaces') or []) or 'N/A'}",
        f"- 成本配置差异单元格：{cost.get('changed_cells')}",
        f"- 成本配置变化产品记录：{cost.get('changed_product_records')}",
        f"- owner 清单状态：{packet.get('owner_manifest_confirmation_status') or 'N/A'}",
        f"- 业务确认记录：{'有效' if packet.get('business_confirmation_valid') else '未确认'}",
        f"- 业务确认状态：{packet.get('business_confirmation_status') or 'N/A'}",
        "",
        "## strict 阻塞项",
        "",
        *_line_items(packet.get("strict_blockers") or []),
        "",
        "## unknown inbox",
        "",
    ]
    unknown_details = packet.get("unknown_inbox_details") or []
    if unknown_details:
        for row in unknown_details:
            lines.append(f"- 文件：{row.get('file')}")
            lines.append(f"  类型：{row.get('likely_report_type')}")
            lines.append(f"  站点：{row.get('likely_marketplace')}")
            if row.get("business_interpretation"):
                lines.append(f"  判断：{row.get('business_interpretation')}")
            if row.get("recommendation"):
                lines.append(f"  建议：{row.get('recommendation')}")
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 成本高风险样本",
            "",
            "| 风险分 | 站点 | SKU | ASIN | 产品 | 原因 | 证据 |",
            "|---:|---|---|---|---|---|---|",
        ]
    )
    risk_rows = cost.get("high_risk_rows") or []
    if risk_rows:
        for row in risk_rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_escape(row.get("score")),
                        _markdown_escape(row.get("marketplace")),
                        _markdown_escape(row.get("sku")),
                        _markdown_escape(row.get("asin")),
                        _markdown_escape(row.get("product_name")),
                        _markdown_escape("；".join(row.get("reasons") or [])),
                        _markdown_escape("；".join(row.get("evidence") or [])),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| 0 | N/A | N/A | N/A | N/A | 未识别到高风险样本 |  |")

    lines.extend(
        [
            "",
            "## 人工确认结论待填",
            "",
            "```text",
            "确认日期：",
            "确认人：",
            "unknown inbox 处理结论：参考资料隔离 / 纳入诊断需补解析 / 其他",
            "成本配置结论：保留 / 回滚 / 部分修正",
            "业务逻辑审查结论：通过 / 需修正",
            "daily update 验证结论：待 preflight 通过后验证",
            "允许 strict 参数：",
            "  manual-config-confirmed: yes / no",
            "  business-review-confirmed: yes / no",
            "  parallel-lock-owner-confirmed: yes / no",
            "  daily-update-verified: yes / no",
            "仍需修正项目：",
            "```",
            "",
            "## 证据文件",
            "",
        ]
    )
    for label, path in (packet.get("evidence_files") or {}).items():
        lines.append(f"- {label}: `{path}`")
    return "\n".join(lines) + "\n"


def write_outputs(packet: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    PACKET_JSON.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    PACKET_MARKDOWN.write_text(build_markdown(packet), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a business review packet from the latest showcase evidence.")
    parser.add_argument(
        "--no-refresh-status",
        action="store_true",
        help="Use the existing showcase_status_report.json without refreshing it first.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.no_refresh_status:
        _refresh_status_report()
    packet = build_packet()
    write_outputs(packet)
    print(f"[check] wrote: {PACKET_JSON}", flush=True)
    print(f"[check] wrote: {PACKET_MARKDOWN}", flush=True)
    print(f"[check] business_submit_ready: {packet['business_submit_ready']}", flush=True)
    return 0 if packet["showcase_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
