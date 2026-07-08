from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "data" / "output"
SERVER_PATH = ROOT / "scripts" / "report_action_server.py"
REPORT_SOURCE_PATH = ROOT / "src" / "generate_html_report.py"
REPORT_ASSETS_SOURCE_PATH = ROOT / "src" / "html_pages" / "assets.py"
GENERATED_REPORT_JS_PATH = OUTPUT_DIR / "assets" / "report.js"
REPORT_HTML_FILES = [
    "latest_recommendations.html",
    "summary.html",
    "dashboard.html",
    "uk_report.html",
    "us_report.html",
    "de_report.html",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "").replace("£", "").replace("$", "").replace("€", ""))
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_text(val)}" for key, val in value.items())
    return str(value)


def _row_label(row: dict) -> str:
    return " ".join(
        item
        for item in [
            str(row.get("marketplace") or "").strip(),
            str(row.get("sku") or "").strip(),
            str(row.get("asin") or "").strip(),
            str(row.get("product_name") or row.get("search_term_or_target") or "").strip(),
        ]
        if item
    )


def _is_actionable_ad(row: dict) -> bool:
    action = str(row.get("suggested_action") or row.get("normalized_action") or "").strip()
    if not action:
        return False
    if any(token in action for token in ["观察", "保留", "无需操作", "仅背景参考"]):
        return False
    return any(token in action for token in ["降竞价", "否定", "暂停", "加价", "小预算", "精准"])


def _has_any(row: dict, fields: Iterable[str]) -> bool:
    return any(row.get(field) not in (None, "", [], {}) for field in fields)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是", "需要"}


def _truthy_flag(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def _requires_frontend_evidence(row: dict) -> bool:
    if str(row.get("final_decision") or "") == "FRONTEND_FIRST":
        return True
    if _truthy(row.get("frontend_required")):
        return True
    frontend_text = " ".join(
        str(row.get(field) or "").strip()
        for field in [
            "frontend_status",
            "frontend_freshness",
            "frontend_auto_conclusion_label",
            "frontend_evidence_tier",
            "frontend_findings",
            "frontend_search_status",
            "frontend_search_findings",
        ]
    )
    if not frontend_text:
        return False
    return any(token in frontend_text for token in ["前台", "售价", "评分", "评论", "配送", "搜索", "Amazon", "沿用"])


def _audit_report_view_snapshot(result: dict, failures: list[str]) -> None:
    marketplace = str(result.get("marketplace") or "").upper()
    view = result.get("report_view_snapshot") or {}
    required = [
        "today_task_queue_rows",
        "html_search_term_processing_queue_rows",
        "frontend_check_queue_rows",
        "inventory_replenishment_rows",
        "product_final_decision_rows",
        "product_operation_cards",
        "action_effect_review_rows",
        "keyword_action_effect_review_rows",
    ]
    for key in required:
        if key not in view:
            failures.append(f"{marketplace} snapshot missing {key}")

    for key in ["action_effect_review_rows", "keyword_action_effect_review_rows"]:
        for row in view.get(key, []) or []:
            row_marketplace = str(row.get("marketplace") or "").upper()
            if row_marketplace and row_marketplace != marketplace:
                failures.append(f"{marketplace} {key} contains {row_marketplace} row: {_row_label(row)}")


def _audit_product_rows(result: dict, failures: list[str]) -> None:
    marketplace = str(result.get("marketplace") or "").upper()
    view = result.get("report_view_snapshot") or {}
    rows = list(view.get("product_operation_cards") or view.get("product_final_decision_rows") or [])
    p0p1 = list(view.get("today_task_queue_rows") or [])
    if p0p1 and not rows:
        failures.append(f"{marketplace} has P0/P1 rows but no product operation cards")

    for row in rows:
        label = _row_label(row)
        text = _text(row)
        if any(token in text for token in ["有潜力", "不能否"]):
            failures.append(f"{marketplace} product row uses unsafe potential wording: {label}")
        has_product_metrics = _has_any(row, ["ad_clicks", "ad_spend", "ad_orders", "total_orders", "acos", "target_acos"])
        has_sales_mix = _has_any(row, ["ad_orders", "total_orders"]) and _has_any(
            row,
            ["natural_orders", "recent_14d_natural_orders", "natural_order_note"],
        )
        has_profit = _has_any(row, ["profit_before_ads_per_unit", "cost_status", "cost_key_evidence"])
        has_inventory = _has_any(row, ["inventory_constraint", "inventory_reason"])
        has_frontend = _has_any(
            row,
            [
                "frontend_findings",
                "frontend_status",
                "frontend_evidence_tier",
                "frontend_freshness",
                "frontend_auto_conclusion_label",
                "frontend_search_status",
            ],
        )
        has_feedback = _has_any(row, ["feedback_cooldown_status", "keyword_memory_summary", "decision_reason", "fusion_reason"])
        stock = str(row.get("inventory_constraint") or "")
        if str(row.get("final_decision") or "") in {"FRONTEND_FIRST", "CONSERVATIVE_RUN", "EXECUTE_TODAY"}:
            missing = [
                name
                for name, ok in [
                    ("product_metrics", has_product_metrics),
                    ("erp_ad_natural_mix", has_sales_mix),
                    ("profit_or_cost", has_profit),
                    ("inventory", has_inventory),
                    ("history_or_reason", has_feedback),
                ]
                if not ok
            ]
            if _requires_frontend_evidence(row) and not has_frontend:
                missing.append("frontend_or_queue")
            if missing:
                failures.append(f"{marketplace} product row lacks evidence {missing}: {label}")
            reason_text = " ".join(
                str(row.get(field) or "")
                for field in ["decision_reason", "fusion_reason", "operation_main_reason", "keyword_memory_summary", "feedback_cooldown_status"]
            )
            if has_sales_mix and not any(token in reason_text for token in ["广告单", "总单", "自然单"]):
                failures.append(f"{marketplace} product row reason omits sales mix: {label}")
            if has_profit and not any(token in reason_text for token in ["利润", "成本", "target_acos", "广告前利润"]):
                failures.append(f"{marketplace} product row reason omits profit or cost: {label}")
            if has_inventory and stock not in {"", "NONE", "HEALTHY"} and not any(
                token in reason_text for token in ["库存", "断货", "低库存", "补货", "覆盖"]
            ):
                failures.append(f"{marketplace} product row reason omits inventory risk: {label}")
            if _requires_frontend_evidence(row) and has_frontend and not any(
                token in reason_text for token in ["前台", "评分", "评论", "Coupon", "配送", "Buy Box", "竞品", "搜索页", "缓存", "拦截"]
            ):
                failures.append(f"{marketplace} product row reason omits frontend evidence: {label}")
            if (row.get("feedback_cooldown_status") or row.get("keyword_memory_summary")) and not any(
                token in reason_text for token in ["冷却", "历史", "复盘", "记忆"]
            ):
                failures.append(f"{marketplace} product row reason omits history feedback: {label}")
        allowed = _text(row.get("today_allowed_actions"))
        if stock in {"OUT_OF_STOCK", "LOW_STOCK", "RESTOCK_RECOVERY"} and any(
            token in allowed for token in ["budget_up", "broad_scale", "bid_up"]
        ):
            failures.append(f"{marketplace} low-stock product still allows scale action: {label}")
        profit = _num(row.get("profit_before_ads_per_unit"))
        if profit is not None and profit <= 0 and any(token in allowed for token in ["budget_up", "broad_scale", "bid_up"]):
            failures.append(f"{marketplace} unprofitable product still allows scale action: {label}")


def _audit_ad_rows(result: dict, failures: list[str]) -> None:
    marketplace = str(result.get("marketplace") or "").upper()
    rows = (result.get("report_view_snapshot") or {}).get("html_search_term_processing_queue_rows") or []
    for row in rows:
        label = _row_label(row)
        text = _text(row)
        if any(token in text for token in ["有潜力", "不能否"]):
            failures.append(f"{marketplace} ad row uses unsafe potential wording: {label}")
        if _is_actionable_ad(row):
            missing = [
                field
                for field in ["classification_reason", "reason", "clicks", "spend", "orders"]
                if row.get(field) in (None, "")
            ]
            if missing:
                failures.append(f"{marketplace} actionable ad row missing {missing}: {label}")
        action = str(row.get("suggested_action") or "")
        orders = _num(row.get("orders")) or 0
        clicks = _num(row.get("clicks")) or 0
        if orders <= 0 and clicks < 8 and any(token in action for token in ["加价", "加预算", "放量"]):
            failures.append(f"{marketplace} sample-light zero-order row suggests scale: {label}")


def _audit_inventory_rows(result: dict, failures: list[str]) -> None:
    marketplace = str(result.get("marketplace") or "").upper()
    rows = (result.get("report_view_snapshot") or {}).get("inventory_replenishment_rows") or []
    for row in rows:
        label = _row_label(row)
        inventory_gap_text = _text(
            [
                row.get("stock_risk_reason"),
                row.get("replenishment_advice"),
                row.get("inventory_match_status"),
            ]
        )
        explained_inventory_gap = (
            "available_stock" in row
            and str(row.get("stock_risk_level") or "") == "UNKNOWN"
            and any(token in inventory_gap_text for token in ["缺少可用库存", "未读取到可用库存", "需先核对"])
        )
        for field in [
            "available_stock",
            "total_lead_time_days",
            "target_cover_days",
            "stock_risk_reason",
            "replenishment_advice",
        ]:
            if row.get(field) in (None, ""):
                if field == "available_stock" and explained_inventory_gap:
                    continue
                failures.append(f"{marketplace} inventory row missing {field}: {label}")
        level = str(row.get("stock_risk_level") or "")
        cover_missing = row.get("days_of_cover") in (None, "")
        baseline_text = _text(
            [
                row.get("stock_risk_reason"),
                row.get("replenishment_advice"),
                row.get("avg_daily_units_source"),
            ]
        )
        baseline_gap = (_num(row.get("avg_daily_units_used")) or 0) <= 0 or any(
            token in baseline_text for token in ["销量基准不足", "不能单纯按销量", "缺少销量基准"]
        )
        if cover_missing and not (level == "UNKNOWN" and baseline_gap):
            if level in {"LOW_STOCK", "OUT_OF_STOCK", "REPLENISH_SOON"} and baseline_gap:
                pass
            else:
                failures.append(f"{marketplace} inventory row missing days_of_cover: {label}")
        advice = str(row.get("replenishment_advice") or "")
        if level in {"LOW_STOCK", "OUT_OF_STOCK", "REPLENISH_SOON"} and not any(
            token in advice for token in ["补货", "缺少可用库存", "销量基准不足"]
        ):
            failures.append(f"{marketplace} risky inventory row lacks replenishment action: {label}")


def _audit_frontend_rows(result: dict, failures: list[str]) -> None:
    marketplace = str(result.get("marketplace") or "").upper()
    rows = (result.get("report_view_snapshot") or {}).get("frontend_check_queue_rows") or []
    for row in rows:
        status = str(row.get("frontend_check_status") or "")
        findings = str(row.get("frontend_findings") or "")
        freshness = str(row.get("frontend_data_freshness") or row.get("frontend_freshness") or "")
        label = _row_label(row)
        if "读取失败" in status and not any(token in findings + freshness for token in ["沿用", "待前台检查", "缓存"]):
            failures.append(f"{marketplace} failed frontend row lacks fallback label: {label}")
        if "沿用" in status and not re.search(r"\d{4}-\d{2}-\d{2}", status + findings + freshness):
            failures.append(f"{marketplace} cached frontend row lacks data date: {label}")
        if status in {"已自动检查"} or "沿用" in status:
            for field in ["frontend_price", "frontend_rating", "frontend_reviews", "frontend_coupon", "frontend_delivery"]:
                if row.get(field) in (None, ""):
                    failures.append(f"{marketplace} frontend row missing {field}: {label}")
            search_status = str(row.get("frontend_search_status") or "")
            if not search_status:
                failures.append(f"{marketplace} frontend row missing search page status: {label}")
            if "已自动检查" in search_status or "已读取部分结果" in search_status:
                for field in ["frontend_competitor_count", "frontend_search_quality_score", "frontend_search_findings"]:
                    if row.get(field) in (None, ""):
                        failures.append(f"{marketplace} frontend search row missing {field}: {label}")


def _audit_effect_review_rows(result: dict, failures: list[str]) -> None:
    marketplace = str(result.get("marketplace") or "").upper()
    view = result.get("report_view_snapshot") or {}
    rows = [
        *(view.get("action_effect_review_rows") or []),
        *(view.get("keyword_action_effect_review_rows") or []),
    ]
    for row in rows:
        label = _row_label(row)
        days = _num(row.get("days_since_execution"))
        judgement = str(row.get("judgement") or "")
        review_window = str(row.get("review_window") or "")
        next_step = str(row.get("next_step") or "")
        effect_metrics = str(row.get("effect_metrics") or "")
        if days is not None and days < 3 and judgement not in {"样本不足", "数据不足", "待观察"}:
            failures.append(f"{marketplace} review under 3 days makes strong judgement: {label}")
        if days is not None and days < 7 and review_window == "7天后复盘":
            failures.append(f"{marketplace} review window marked 7d before enough days: {label}")
        if days is not None and days >= 7 and not review_window:
            failures.append(f"{marketplace} review row lacks review_window: {label}")
        if not effect_metrics:
            failures.append(f"{marketplace} review row missing effect_metrics: {label}")
        if _truthy_flag(row.get("halo_only_conversion")):
            unsafe_text = " ".join([judgement, next_step, str(row.get("attribution_effect_note") or "")])
            if any(token in unsafe_text for token in ["加价", "放量", "有效"]) and "不" not in unsafe_text:
                failures.append(f"{marketplace} halo-only review can be read as effective: {label}")
        if _truthy_flag(row.get("target_sku_not_converted")) and _truthy_flag(row.get("promoted_conversion_improved")):
            failures.append(f"{marketplace} review has conflicting promoted conversion flags: {label}")
        if "光环" in effect_metrics and "本 SKU 单" not in effect_metrics:
            failures.append(f"{marketplace} review mentions halo without promoted SKU metric: {label}")


def _load_text(path: Path, failures: list[str]) -> str:
    if not path.exists():
        failures.append(f"missing {path}")
        return ""
    return path.read_text(encoding="utf-8")


def _require_markers(name: str, text: str, markers: Iterable[str], failures: list[str]) -> None:
    for marker in markers:
        if marker not in text:
            failures.append(f"{name} missing marker: {marker}")


def _load_report_js_contract_source(failures: list[str]) -> tuple[str, str]:
    try:
        from src.html_pages.assets import REPORT_JS

        return str(REPORT_ASSETS_SOURCE_PATH) + ":REPORT_JS", REPORT_JS
    except Exception as exc:
        if GENERATED_REPORT_JS_PATH.exists():
            return str(GENERATED_REPORT_JS_PATH), GENERATED_REPORT_JS_PATH.read_text(encoding="utf-8")
        failures.append(f"cannot load report JS contract from {REPORT_ASSETS_SOURCE_PATH}: {exc}")
        return "", ""


def _audit_anchor_integrity(name: str, html: str, failures: list[str]) -> None:
    ids = set(re.findall(r'\sid="([^"]+)"', html))
    anchors = re.findall(r'href="#([^"]+)"', html)
    for anchor in anchors:
        if anchor and anchor not in ids:
            failures.append(f"{name} anchor #{anchor} has no matching id")


def _audit_report_js_contract(failures: list[str]) -> None:
    name, source = _load_report_js_contract_source(failures)
    if not source:
        return
    markers = [
        "fetch('http://127.0.0.1:8765/upload/today-data'",
        "fetch('http://127.0.0.1:8765/run/daily-update'",
        "fetch('http://127.0.0.1:8765/submission/status?t='",
        "function reportActionUrl(runButton, action)",
        "fetch(reportActionUrl(runButton, action), { method: 'POST' })",
        "fetch('http://127.0.0.1:8765/upload/config?kind='",
        "fetch('http://127.0.0.1:8765/apply/config?kind='",
        "上传通过，正在自动启动 daily update",
        "reloadLatestReport(payload)",
        "isSoftFrontendRetryFailure",
        "X-Report-Action-Token",
        "report-action-token",
        "fetch('http://127.0.0.1:8765/feedback/ad-action-complete'",
        "fetch('http://127.0.0.1:8765/feedback/ad-action-cancel'",
    ]
    _require_markers(name, source, markers, failures)


def _audit_server_contract(failures: list[str]) -> None:
    source = _load_text(SERVER_PATH, failures)
    if not source:
        return
    markers = [
        'path == "/health"',
        'path == "/submission/status"',
        'path == "/config/status"',
        'path == "/run/frontend-retry"',
        'path == "/run/frontend-check-one"',
        'path == "/upload/today-data"',
        'path == "/upload/config"',
        'path == "/apply/config"',
        'path == "/run/daily-update"',
        'path == "/feedback/ad-action-complete"',
        'path == "/feedback/ad-action-cancel"',
        "ACTION_TOKEN_HEADER",
        "_require_action_token",
        "SIDE_EFFECT_GET_PATHS",
        "SIDE_EFFECT_POST_PATHS",
        "上传完成，preflight 通过。",
        "已开始导入 inbox 并刷新报告。",
        "已开始市场调查",
        "正在检查这个产品的前台，完成后会刷新报告。",
        "成本配置应用必须显式确认。",
    ]
    _require_markers(str(SERVER_PATH), source, markers, failures)
    if 'Access-Control-Allow-Origin", "*"' in source or "Access-Control-Allow-Origin', '*'" in source:
        failures.append("report_action_server.py still allows all CORS origins")
    do_get_section = source.split("    def do_GET", 1)[1].split("    def do_POST", 1)[0] if "    def do_GET" in source else ""
    for marker in ["self._start_frontend_retry(", "self._start_frontend_check_one(", "self._start_battle_diagnosis_one("]:
        if marker in do_get_section:
            failures.append("report_action_server.py still has GET side-effect dispatch")


def _audit_latest_recommendations_html(html: str, failures: list[str]) -> None:
    markers = [
        "上传并刷新日报",
        "市场调查",
        "产品级结论",
        "补货提醒",
        "执行后效果复盘",
        "today-ad-actions-all",
        "local-data-submit",
        "data-local-submit-form",
        "data-run-report-action=\"frontend-retry\"",
        "data-local-submit-status",
        "data-config-submit-form",
        "data-apply-config=\"cost\"",
        "data-apply-config=\"alias\"",
        "data-config-submit-status",
        "data-ad-search",
        "data-ad-status",
        "data-ad-action",
    ]
    _require_markers("latest_recommendations.html", html, markers, failures)
    if "手动运行 daily update" in html or "data-run-daily-update" in html:
        failures.append("latest_recommendations.html still exposes manual daily update button")
    if "上传并检查" in html or "上传后先看 preflight 结果，再运行 daily update" in html:
        failures.append("latest_recommendations.html still uses old upload wording")
    if "刷新调查队列" not in html or "缓存可参考，强操作只看完整证据" not in html:
        failures.append("latest_recommendations.html missing market survey refresh scope wording")


def _audit_summary_html(html: str, failures: list[str]) -> None:
    markers = [
        "三分钟摘要",
        "今日开工结论",
        "今日优先级概览",
        "今天先做",
        "今天先别做",
        "昨天动作今天要盯",
        "补货先看",
    ]
    _require_markers("summary.html", html, markers, failures)
    if not any(token in html for token in ["完整库存表在 ALL 工作台和 Excel", "可用库存", "覆盖", "建议补"]):
        failures.append("summary.html replenishment section lacks inventory evidence or fallback text")
    if "复制到广告后台" in html:
        failures.append("summary.html duplicates workbench-only operational details")


def _audit_dashboard_html(html: str, failures: list[str]) -> None:
    markers = [
        "运营状态入口",
        "打开三分钟摘要",
        "打开 ALL 运营控制台",
        "数据质量总览",
        "前台待检查",
        "沿用前台缓存",
        "成本/利润核对",
        "数据质量预警",
        "uk_report.html",
        "us_report.html",
        "de_report.html",
    ]
    _require_markers("dashboard.html", html, markers, failures)


def _audit_marketplace_html(output_dir: Path, failures: list[str]) -> None:
    required_by_marketplace = {
        "uk_report.html": "UK",
        "us_report.html": "US",
        "de_report.html": "DE",
    }
    common_markers = [
        "市场调查",
        "执行后效果复盘",
        "库存补货提醒",
        "数据质量与增强数据",
        "刷新调查队列",
        "data-run-report-action=\"frontend-retry\"",
        "data-run-report-status=\"frontend-retry\"",
        "缓存可参考，强操作只看完整证据",
        "判断硬标准",
    ]
    for filename, marketplace in required_by_marketplace.items():
        html = _load_text(output_dir / filename, failures)
        if not html:
            continue
        _require_markers(filename, html, [f"亚马逊运营日报｜{marketplace}", *common_markers], failures)
        if not any(token in html for token in ["广告状态", "今天广告动作"]):
            failures.append(f"{filename} missing ad action/status section")
        if "上传并刷新日报" in html:
            failures.append(f"{filename} should not duplicate upload workflow")


def _audit_html(output_dir: Path, failures: list[str]) -> None:
    pages = {filename: _load_text(output_dir / filename, failures) for filename in REPORT_HTML_FILES}
    if pages.get("latest_recommendations.html"):
        _audit_latest_recommendations_html(pages["latest_recommendations.html"], failures)
    if pages.get("summary.html"):
        _audit_summary_html(pages["summary.html"], failures)
    if pages.get("dashboard.html"):
        _audit_dashboard_html(pages["dashboard.html"], failures)
    _audit_marketplace_html(output_dir, failures)
    for filename, html in pages.items():
        if html:
            _audit_anchor_integrity(filename, html, failures)
    _audit_report_js_contract(failures)
    _audit_server_contract(failures)


def audit(output_dir: Path = OUTPUT_DIR) -> list[str]:
    analysis_path = output_dir / "latest_analysis.json"
    failures: list[str] = []
    if not analysis_path.exists():
        return [f"missing {analysis_path}"]
    payload = _load_json(analysis_path)
    results = payload.get("marketplace_results") or []
    if not results:
        failures.append("latest_analysis.json has no marketplace_results")
    for result in results:
        if not isinstance(result, dict):
            continue
        _audit_report_view_snapshot(result, failures)
        _audit_product_rows(result, failures)
        _audit_ad_rows(result, failures)
        _audit_inventory_rows(result, failures)
        _audit_frontend_rows(result, failures)
        _audit_effect_review_rows(result, failures)
    _audit_html(output_dir, failures)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ops console analysis completeness and action safety.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    failures = audit(args.output_dir)
    if failures:
        for failure in failures:
            print(f"[fail] {failure}", flush=True)
        return 1
    print("[done] ops console analysis audit passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
