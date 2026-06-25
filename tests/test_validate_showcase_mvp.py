from __future__ import annotations

import json
from pathlib import Path

import scripts.validate_showcase_mvp as showcase_validate


def test_validate_frontend_rows_accepts_pending_and_cached_status() -> None:
    rows = [
        {
            "asin": "B0PENDING",
            "frontend_check_status": "待前台检查",
            "frontend_data_freshness": "无可用前台数据",
            "frontend_findings": "暂无最近成功前台数据",
        },
        {
            "asin": "B0CACHED",
            "frontend_check_status": "沿用 2026-06-05 前台数据",
            "frontend_data_freshness": "沿用 2026-06-05 前台数据",
            "frontend_findings": "沿用 2026-06-05 前台数据",
        },
    ]

    assert showcase_validate._validate_frontend_rows("US", rows) == 0


def test_validate_frontend_rows_blocks_failed_status_without_fallback(capsys) -> None:
    rows = [
        {
            "asin": "B0BAD",
            "frontend_check_status": "读取失败",
            "frontend_data_freshness": "",
            "frontend_findings": "自动读取失败",
        }
    ]

    code = showcase_validate._validate_frontend_rows("US", rows)
    output = capsys.readouterr().out

    assert code == 1
    assert "missing cached-date or pending-check status" in output


def test_validate_frontend_rows_blocks_cache_status_without_date(capsys) -> None:
    rows = [
        {
            "asin": "B0BAD",
            "frontend_check_status": "沿用缓存前台数据",
            "frontend_data_freshness": "沿用缓存前台数据",
            "frontend_findings": "沿用缓存前台数据",
        }
    ]

    code = showcase_validate._validate_frontend_rows("US", rows)
    output = capsys.readouterr().out

    assert code == 1
    assert "cache status missing date" in output


def test_validate_ad_observation_rows_blocks_executed_watch_row(capsys) -> None:
    rows = [
        {
            "search_term_or_target": "low sample keyword",
            "suggested_action": "观察",
            "confirmed_status": "已执行",
        }
    ]

    code = showcase_validate._validate_ad_observation_rows("UK", rows)
    output = capsys.readouterr().out

    assert code == 1
    assert "ad observation row" in output


def test_validate_ad_observation_rows_allows_executable_done_row() -> None:
    rows = [
        {
            "search_term_or_target": "bad keyword",
            "suggested_action": "否定精准",
            "confirmed_status": "已执行",
        }
    ]

    assert showcase_validate._validate_ad_observation_rows("UK", rows) == 0


def _write_minimal_safe_run(safe_dir: Path, latest_html: str, ad_rows: list[dict] | None = None) -> None:
    safe_dir.mkdir()
    (safe_dir / "assets").mkdir()
    (safe_dir / "assets" / "report.css").write_text("body{}", encoding="utf-8")
    (safe_dir / "assets" / "report.js").write_text("console.log('ok')", encoding="utf-8")
    report_date = "2026-06-08"
    analysis = {
        "report_date": report_date,
        "import_summary": {"ads_imported_rows": 10, "erp_imported_rows": 10},
        "marketplace_results": [
            {
                "marketplace": market,
                "summary": {"report_date": report_date},
                "report_view_snapshot": {
                    "today_task_queue_rows": [],
                    "frontend_check_queue_rows": [
                        {
                            "asin": f"B0{market}TEST",
                            "frontend_check_status": "待前台检查",
                            "frontend_data_freshness": "无可用前台数据",
                            "frontend_findings": "自动证据不足，不能用于强诊断",
                        }
                    ],
                    "cost_profit_diagnosis_rows": [],
                    "listing_price_diagnosis_rows": [],
                    "today_action_groups": {"广告动作": ad_rows or []},
                },
            }
            for market in ["UK", "US", "DE"]
        ],
    }
    (safe_dir / "latest_analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    for name, text in {
        "latest_recommendations.html": latest_html,
        "dashboard.html": "2026-06-08 运营状态入口 打开三分钟摘要 打开 ALL 运营控制台",
        "summary.html": "2026-06-08 三分钟摘要",
        "uk_report.html": "2026-06-08 亚马逊运营日报｜UK 广告状态 数据质量与增强数据",
        "us_report.html": "2026-06-08 亚马逊运营日报｜US 广告状态 数据质量与增强数据",
        "de_report.html": "2026-06-08 亚马逊运营日报｜DE 广告状态 数据质量与增强数据",
    }.items():
        (safe_dir / name).write_text(text, encoding="utf-8")
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = "Metrics_Validation"
    workbook.save(safe_dir / "amazon_ops_report_20260608.xlsx")


def test_validate_safe_run_blocks_generic_confirmation_copy(capsys, tmp_path) -> None:
    safe_dir = tmp_path / "safe"
    _write_minimal_safe_run(
        safe_dir,
        '2026-06-08 今天广告动作 id="today-ad-actions-all" 待确认 0 前台证据状态 提交今日数据 系统结论 融合诊断 需要确认的问题',
    )

    code = showcase_validate.validate_safe_run_outputs(safe_dir)
    output = capsys.readouterr().out

    assert code == 1
    assert "forbidden marker" in output


def test_validate_safe_run_accepts_decision_markers(capsys, tmp_path) -> None:
    safe_dir = tmp_path / "safe"
    _write_minimal_safe_run(
        safe_dir,
        '2026-06-08 今天广告动作 id="today-ad-actions-all" 待确认 0 前台证据状态 提交今日数据 系统结论 融合诊断 前台缓存工具',
    )

    code = showcase_validate.validate_safe_run_outputs(safe_dir)
    output = capsys.readouterr().out

    assert code == 0
    assert "safe-run outputs validated" in output


def test_validate_safe_run_requires_copy_area_for_pending_ads(capsys, tmp_path) -> None:
    safe_dir = tmp_path / "safe"
    _write_minimal_safe_run(
        safe_dir,
        '2026-06-08 今天广告动作 id="today-ad-actions-all" 待确认 1 前台证据状态 提交今日数据 系统结论 融合诊断',
        ad_rows=[{"confirmed_status": "待确认", "copy_action_line": "建议否词"}],
    )

    code = showcase_validate.validate_safe_run_outputs(safe_dir)
    output = capsys.readouterr().out

    assert code == 1
    assert "missing copy area for pending ad rows" in output


def test_validate_safe_run_allows_copy_area_for_pending_ads(capsys, tmp_path) -> None:
    safe_dir = tmp_path / "safe"
    _write_minimal_safe_run(
        safe_dir,
        '2026-06-08 今天广告动作 id="today-ad-actions-all" 复制到广告后台 前台证据状态 提交今日数据 系统结论 融合诊断',
        ad_rows=[{"confirmed_status": "待确认", "copy_action_line": "建议否词"}],
    )

    code = showcase_validate.validate_safe_run_outputs(safe_dir)
    output = capsys.readouterr().out

    assert code == 0
    assert "safe-run outputs validated" in output


def test_validate_safe_run_treats_background_ad_note_as_zero_pending(capsys, tmp_path) -> None:
    safe_dir = tmp_path / "safe"
    _write_minimal_safe_run(
        safe_dir,
        '2026-06-08 今天广告动作 id="today-ad-actions-all" 待确认 0 前台证据状态 提交今日数据 系统结论 融合诊断',
        ad_rows=[
            {
                "confirmed_status": "仅背景参考",
                "today_action": "保守跑：不加预算，只保留高相关精准词和必要降竞价/否词。",
            }
        ],
    )

    code = showcase_validate.validate_safe_run_outputs(safe_dir)
    output = capsys.readouterr().out

    assert code == 0
    assert "safe-run outputs validated" in output


def test_validate_safe_run_accepts_empty_copy_area_with_growth_pending(capsys, tmp_path) -> None:
    safe_dir = tmp_path / "safe"
    _write_minimal_safe_run(
        safe_dir,
        (
            '2026-06-08 今天广告动作 id="today-ad-actions-all" 待处理</span><strong>0</strong> '
            "复制到广告后台 无待确认动作 当前没有需要复制执行的广告动作 小预算投词 待确认 1 "
            "前台证据状态 提交今日数据 系统结论 融合诊断"
        ),
    )

    code = showcase_validate.validate_safe_run_outputs(safe_dir)
    output = capsys.readouterr().out

    assert code == 0
    assert "safe-run outputs validated" in output


def test_workspace_fingerprint_tracks_untracked_file_content(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(showcase_validate, "ROOT", tmp_path)
    monkeypatch.setattr(showcase_validate, "git_text", lambda args: "HEAD123\n" if args == ["rev-parse", "HEAD"] else "")
    monkeypatch.setattr(showcase_validate, "git_lines", lambda args: ["new.txt"] if args == ["ls-files", "--others", "--exclude-standard"] else [])
    monkeypatch.setattr(showcase_validate, "git_bytes", lambda args: b"")
    (tmp_path / "new.txt").write_text("before", encoding="utf-8")

    before = showcase_validate.workspace_fingerprint()["workspace_hash"]
    (tmp_path / "new.txt").write_text("after", encoding="utf-8")
    after = showcase_validate.workspace_fingerprint()["workspace_hash"]

    assert before != after


def test_write_validation_receipt_records_current_workspace(monkeypatch, tmp_path) -> None:
    safe_dir = tmp_path / "safe"
    safe_dir.mkdir()
    (safe_dir / "latest_analysis.json").write_text(
        json.dumps(
            {
                "report_date": "2026-06-08",
                "marketplace_results": [
                    {"marketplace": "DE"},
                    {"marketplace": "UK"},
                    {"marketplace": "US"},
                ],
            }
        ),
        encoding="utf-8",
    )
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(showcase_validate, "VALIDATION_RECEIPT", receipt)
    monkeypatch.setattr(
        showcase_validate,
        "workspace_fingerprint",
        lambda: {
            "git_head": "HEAD123",
            "workspace_hash": "hash123",
            "changed_paths": ["main.py"],
            "status_porcelain": [" M main.py"],
        },
    )

    showcase_validate.write_validation_receipt(
        safe_dir,
        pytest_exit_code=0,
        safe_run_exit_code=0,
        output_validation_exit_code=0,
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))

    assert payload["result"] == "passed"
    assert payload["git_head"] == "HEAD123"
    assert payload["workspace_hash"] == "hash123"
    assert payload["report_date"] == "2026-06-08"
    assert payload["marketplaces"] == ["DE", "UK", "US"]
    assert payload["safe_run_dir"] == str(safe_dir)
