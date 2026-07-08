from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_ops_console_analysis import audit


def _base_view() -> dict:
    return {
        "today_task_queue_rows": [],
        "html_search_term_processing_queue_rows": [],
        "frontend_check_queue_rows": [],
        "inventory_replenishment_rows": [
            {
                "marketplace": "UK",
                "sku": "SKU-1",
                "asin": "B0INV",
                "product_name": "库存样本不足品",
                "available_stock": 12,
                "days_of_cover": None,
                "avg_daily_units_used": 0,
                "avg_daily_units_source": "销量基准不足",
                "total_lead_time_days": 100,
                "target_cover_days": 130,
                "stock_risk_level": "UNKNOWN",
                "stock_risk_reason": "近期销量基准不足，不能单纯按销量判断库存安全。",
                "replenishment_advice": "销量基准不足，需结合广告/前台观察。",
            }
        ],
        "product_final_decision_rows": [],
        "product_operation_cards": [
            {
                "marketplace": "UK",
                "sku": "SKU-1",
                "asin": "B0CARD",
                "product_name": "运营卡片",
                "final_decision": "CONSERVATIVE_RUN",
                "ad_clicks": 18,
                "ad_spend": 6.2,
                "ad_orders": 1,
                "total_orders": 2,
                "natural_orders": 1,
                "acos": 0.32,
                "target_acos": 0.28,
                "profit_before_ads_per_unit": 4.2,
                "inventory_constraint": "HEALTHY",
                "inventory_reason": "库存覆盖安全。",
                "decision_reason": "广告有消耗；广告单 1，总单 2，自然单 1；利润 4.2；库存覆盖安全。",
                "today_allowed_actions": ["bid_down"],
            }
        ],
        "action_effect_review_rows": [],
        "keyword_action_effect_review_rows": [],
    }


def _write_case(tmp_path: Path, view: dict, html: str | None = None) -> Path:
    payload = {
        "report_date": "2026-06-17",
        "marketplace_results": [
            {
                "marketplace": "UK",
                "report_view_snapshot": view,
            }
        ],
    }
    (tmp_path / "latest_analysis.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "latest_recommendations.html").write_text(
        html
        or "上传并刷新日报 手动运行 daily update 前台证据状态 产品级结论 补货提醒 执行后效果复盘",
        encoding="utf-8",
    )
    _write_required_report_pages(tmp_path)
    return tmp_path


def _write_required_report_pages(tmp_path: Path) -> None:
    pages = {
        "summary.html": (
            "三分钟摘要 今日开工结论 今日优先级概览 今天先做 今天先别做 "
            "昨天动作今天要盯 补货先看 完整库存表在 ALL 工作台和 Excel"
        ),
        "dashboard.html": (
            "运营状态入口 打开三分钟摘要 打开 ALL 运营控制台 数据质量总览 "
            "前台待检查 沿用前台缓存 成本/利润核对 数据质量预警 "
            "uk_report.html us_report.html de_report.html"
        ),
        "uk_report.html": _marketplace_html("UK"),
        "us_report.html": _marketplace_html("US"),
        "de_report.html": _marketplace_html("DE"),
    }
    for filename, text in pages.items():
        (tmp_path / filename).write_text(text, encoding="utf-8")


def _latest_html(extra: str = "") -> str:
    return (
        '上传并刷新日报 手动运行 daily update 前台证据状态 产品级结论 补货提醒 执行后效果复盘 '
        'today-ad-actions-all local-data-submit data-local-submit-form data-run-daily-update '
        'data-run-report-action="frontend-retry" data-local-submit-status data-config-submit-form '
        'data-apply-config="cost" data-apply-config="alias" data-config-submit-status '
        'data-ad-search data-ad-status data-ad-action 20次稳定性只用于验收测试 '
        f"{extra}"
    )


def _marketplace_html(marketplace: str) -> str:
    return (
        f"亚马逊运营日报｜{marketplace} 广告状态 前台证据状态 执行后效果复盘 "
        '库存补货提醒 数据质量与增强数据 刷新当前前台队列 data-run-report-action="frontend-retry" '
        'data-run-report-status="frontend-retry" 失败时保留缓存 判断硬标准'
    )


@pytest.fixture(autouse=True)
def _patch_source_contracts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scripts.audit_ops_console_analysis as audit_module

    report_source = tmp_path / "generate_html_report.py"
    report_source.write_text(
        "\n".join(
            [
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
        ),
        encoding="utf-8",
    )
    server_source = tmp_path / "report_action_server.py"
    server_source.write_text(
        "\n".join(
            [
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
                "已开始当前前台队列缺口刷新",
                "正在检查这个产品的前台，完成后会刷新报告。",
                "成本配置应用必须显式确认。",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        audit_module,
        "_load_report_js_contract_source",
        lambda failures: (str(report_source), report_source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(audit_module, "SERVER_PATH", server_source)


def test_audit_accepts_unknown_inventory_with_sales_baseline_gap_and_no_frontend_queue(tmp_path) -> None:
    output_dir = _write_case(tmp_path, _base_view(), html=_latest_html())

    assert audit(output_dir) == []


def test_audit_fails_cross_marketplace_action_review_rows(tmp_path) -> None:
    view = _base_view()
    view["action_effect_review_rows"] = [
        {
            "marketplace": "US",
            "sku": "SKU-US",
            "asin": "B0US",
            "product_name": "US product",
        }
    ]
    output_dir = _write_case(tmp_path, view, html=_latest_html())

    failures = audit(output_dir)

    assert any("action_effect_review_rows contains US row" in failure for failure in failures)


def test_audit_fails_low_stock_product_allowed_to_scale(tmp_path) -> None:
    view = _base_view()
    view["product_operation_cards"][0]["inventory_constraint"] = "LOW_STOCK"
    view["product_operation_cards"][0]["today_allowed_actions"] = ["budget_up"]
    output_dir = _write_case(tmp_path, view, html=_latest_html())

    failures = audit(output_dir)

    assert any("low-stock product still allows scale action" in failure for failure in failures)


def test_audit_fails_sample_light_zero_order_scale_action(tmp_path) -> None:
    view = _base_view()
    view["html_search_term_processing_queue_rows"] = [
        {
            "marketplace": "UK",
            "sku": "SKU-AD",
            "asin": "B0AD",
            "search_term_or_target": "led desk lamp",
            "suggested_action": "加价 5%-10%",
            "classification_reason": "相关但未验证",
            "reason": "小样本无成交",
            "clicks": 3,
            "spend": 2.1,
            "orders": 0,
        }
    ]
    output_dir = _write_case(tmp_path, view, html=_latest_html())

    failures = audit(output_dir)

    assert any("sample-light zero-order row suggests scale" in failure for failure in failures)


def test_audit_fails_old_upload_wording(tmp_path) -> None:
    html = _latest_html("上传后先看 preflight 结果，再运行 daily update")
    output_dir = _write_case(tmp_path, _base_view(), html=html)

    failures = audit(output_dir)

    assert any("still uses old upload wording" in failure for failure in failures)


def test_audit_requires_all_report_pages(tmp_path) -> None:
    output_dir = _write_case(tmp_path, _base_view(), html=_latest_html())
    (output_dir / "summary.html").unlink()

    failures = audit(output_dir)

    assert any("missing" in failure and "summary.html" in failure for failure in failures)


def test_audit_fails_broken_latest_recommendation_anchor(tmp_path) -> None:
    html = _latest_html('<a href="#missing-section">Broken</a><section id="present-section"></section>')
    output_dir = _write_case(tmp_path, _base_view(), html=html)

    failures = audit(output_dir)

    assert any("anchor #missing-section has no matching id" in failure for failure in failures)


def test_audit_fails_summary_that_duplicates_workbench_details(tmp_path) -> None:
    output_dir = _write_case(tmp_path, _base_view(), html=_latest_html())
    (output_dir / "summary.html").write_text(
        "三分钟摘要 今日开工结论 今日优先级概览 今天先做 今天先别做 "
        "昨天动作今天要盯 补货先看 完整库存表在 ALL 工作台和 Excel 复制到广告后台",
        encoding="utf-8",
    )

    failures = audit(output_dir)

    assert any("summary.html duplicates workbench-only operational details" in failure for failure in failures)


def test_audit_fails_missing_server_endpoint_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.audit_ops_console_analysis as audit_module

    server_source = tmp_path / "broken_report_action_server.py"
    server_source.write_text('path == "/health"', encoding="utf-8")
    monkeypatch.setattr(audit_module, "SERVER_PATH", server_source)
    output_dir = _write_case(tmp_path, _base_view(), html=_latest_html())

    failures = audit(output_dir)

    assert any('/run/daily-update' in failure for failure in failures)


def test_audit_fails_product_card_without_profit_or_natural_mix(tmp_path) -> None:
    view = _base_view()
    view["product_operation_cards"][0].pop("natural_orders")
    view["product_operation_cards"][0].pop("profit_before_ads_per_unit")
    output_dir = _write_case(tmp_path, view, html=_latest_html())

    failures = audit(output_dir)

    assert any("erp_ad_natural_mix" in failure for failure in failures)
    assert any("profit_or_cost" in failure for failure in failures)


def test_audit_fails_product_card_reason_that_omits_available_evidence(tmp_path) -> None:
    view = _base_view()
    view["product_operation_cards"][0]["inventory_constraint"] = "LOW_STOCK"
    view["product_operation_cards"][0]["frontend_status"] = "沿用 2026-06-16 前台数据"
    view["product_operation_cards"][0]["frontend_auto_conclusion_label"] = "自动证据不足，不能用于强诊断"
    view["product_operation_cards"][0]["frontend_search_status"] = "已读取部分结果"
    view["product_operation_cards"][0]["decision_reason"] = "广告有消耗，先保守观察。"
    output_dir = _write_case(tmp_path, view, html=_latest_html())

    failures = audit(output_dir)

    assert any("reason omits sales mix" in failure for failure in failures)
    assert any("reason omits profit or cost" in failure for failure in failures)
    assert any("reason omits inventory risk" in failure for failure in failures)
    assert any("reason omits frontend evidence" in failure for failure in failures)


def test_audit_fails_frontend_row_missing_competitiveness_parts(tmp_path) -> None:
    view = _base_view()
    view["frontend_check_queue_rows"] = [
        {
            "marketplace": "UK",
            "sku": "SKU-FRONT",
            "asin": "B0FRONT",
            "product_name": "前台缺字段产品",
            "frontend_check_status": "已自动检查",
            "frontend_price": "£19.99",
            "frontend_rating": "4.2 out of 5 stars",
            "frontend_search_status": "已自动检查",
            "frontend_competitor_count": 3,
            "frontend_search_quality_score": 70,
            "frontend_search_findings": "前三竞品已读取",
        }
    ]
    output_dir = _write_case(tmp_path, view, html=_latest_html())

    failures = audit(output_dir)

    assert any("frontend_reviews" in failure for failure in failures)
    assert any("frontend_coupon" in failure for failure in failures)
    assert any("frontend_delivery" in failure for failure in failures)


def test_audit_fails_halo_only_review_that_reads_as_effective(tmp_path) -> None:
    view = _base_view()
    view["keyword_action_effect_review_rows"] = [
        {
            "marketplace": "UK",
            "sku": "SKU-HALO",
            "asin": "B0HALO",
            "product_name": "光环测试品",
            "search_term_or_target": "halo term",
            "days_since_execution": "8",
            "review_window": "7天后复盘",
            "judgement": "有改善迹象",
            "next_step": "可以继续加价",
            "effect_metrics": "7天：订单 1，光环单 1，本 SKU 单 0",
            "halo_only_conversion": "True",
            "target_sku_not_converted": "True",
            "promoted_conversion_improved": "False",
        }
    ]
    output_dir = _write_case(tmp_path, view, html=_latest_html())

    failures = audit(output_dir)

    assert any("halo-only review" in failure for failure in failures)
