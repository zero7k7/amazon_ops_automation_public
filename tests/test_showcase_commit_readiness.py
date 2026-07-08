from __future__ import annotations

import json
import sys

import scripts.check_showcase_commit_readiness as readiness


def _fake_git_lines(
    paths: list[str],
    *,
    cached: list[str] | None = None,
    untracked: list[str] | None = None,
    name_status: list[str] | None = None,
    cached_name_status: list[str] | None = None,
):
    def fake(args: list[str]) -> list[str]:
        if args == ["diff", "--name-only"]:
            return paths
        if args == ["diff", "--cached", "--name-only"]:
            return cached or []
        if args == ["ls-files", "--others", "--exclude-standard"]:
            return untracked or []
        if args == ["diff", "--name-status"]:
            return name_status or [f"M\t{path}" for path in paths]
        if args == ["diff", "--cached", "--name-status"]:
            return cached_name_status or [f"M\t{path}" for path in (cached or [])]
        raise AssertionError(f"unexpected git args: {args}")

    return fake


def test_commit_readiness_blocks_real_config_xlsx_modification(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(["config/product_cost_config.xlsx", "main.py"]),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main([])
    output = capsys.readouterr().out

    assert code == 1
    assert "public release blocks real config xlsx files" in output
    assert "config/product_cost_config.xlsx" in output


def test_commit_readiness_allows_real_config_xlsx_index_removal(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(
            ["config/product_cost_config.xlsx", "main.py"],
            name_status=["D\tconfig/product_cost_config.xlsx", "M\tmain.py"],
        ),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main([])
    output = capsys.readouterr().out

    assert code == 0
    assert "real config files removed from git index: config/product_cost_config.xlsx" in output
    assert "no manual config files changed" in output
    assert "business review required before commit" in output


def test_commit_readiness_strict_mode_accepts_explicit_confirmations(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(
            ["config/product_cost_config.xlsx", "main.py"],
            name_status=["D\tconfig/product_cost_config.xlsx", "M\tmain.py"],
        ),
    )
    monkeypatch.setattr(readiness, "parallel_lock_owner_failures", lambda paths: [])
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main(
        [
            "--strict",
            "--manual-config-confirmed",
            "--business-review-confirmed",
            "--parallel-lock-owner-confirmed",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert "strict confirmations accepted" in output


def test_commit_readiness_strict_mode_blocks_invalid_lock_owner_manifest(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(["main.py"]),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(
        readiness,
        "parallel_lock_owner_failures",
        lambda paths: ["changed locked file has no owner: main.py"],
    )
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main(
        [
            "--strict",
            "--business-review-confirmed",
            "--parallel-lock-owner-confirmed",
        ]
    )
    output = capsys.readouterr().out

    assert code == 1
    assert "parallel lock owner issue: changed locked file has no owner: main.py" in output
    assert "parallel lock owner manifest invalid" in output


def test_commit_readiness_checks_staged_manual_config(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines([], cached=["config/product_cost_config.xlsx"]),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main(["--strict"])
    output = capsys.readouterr().out

    assert code == 1
    assert "public release blocks real config xlsx files" in output


def test_commit_readiness_accepts_shareable_demo_files(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(
            [],
            untracked=[
                "config/templates/product_cost_config.example.xlsx",
                "config/templates/product_keyword_rules.example.csv",
                "config/templates/frontend_locations.example.json",
                "docs/demo_runbook.md",
                "docs/shareable_clone_runbook.md",
                "scripts/setup_demo_data.py",
            ],
        ),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main([])
    output = capsys.readouterr().out

    assert code == 0
    assert "manual config confirmation required" not in output
    assert "changed files are assigned to known commit groups" in output


def test_setup_demo_data_writes_public_offline_runtime_inputs(monkeypatch, tmp_path) -> None:
    from scripts import setup_demo_data

    monkeypatch.setattr(setup_demo_data, "ROOT", tmp_path)

    written = setup_demo_data.setup_demo_data(force=False)

    relative = {path.relative_to(tmp_path).as_posix() for path in written}
    assert "config/product_cost_config.xlsx" in relative
    assert "config/sku_alias_map.xlsx" in relative
    assert "data/raw_ads/ads_report_all.csv" in relative
    assert "data/raw_erp/sales_report_all.xlsx" in relative
    assert any(path.startswith("data/raw_amazon_custom/US/traffic_sales_us_compare_") for path in relative)
    assert any(path.startswith("data/raw_amazon_custom/US/search_query_performance_us_compare_") for path in relative)
    assert any(path.startswith("data/raw_amazon_custom/UK/traffic_sales_uk_compare_") for path in relative)
    assert any(path.startswith("data/raw_amazon_custom/DE/search_query_performance_de_compare_") for path in relative)
    assert "data/output/frontend_check_results.json" in relative
    assert "data/output/sellersprite_reverse_asin_results.json" in relative
    assert "data/output/sellersprite_competitor_discovery_results.json" in relative
    assert "data/output/sellersprite_history_snapshots.jsonl" in relative
    assert "data/output/autoopt_feedback_input.json" in relative

    ads_text = (tmp_path / "data/raw_ads/ads_report_all.csv").read_text(encoding="utf-8-sig")
    assert "SKU-PUBLIC-US-001" in ads_text
    assert "B0B5HPKZKM" in ads_text

    frontend_payload = json.loads((tmp_path / "data/output/frontend_check_results.json").read_text(encoding="utf-8"))
    assert frontend_payload["source"] == "setup_demo_data"
    assert any(item["asin"] == "B0B5HPKZKM" and item["frontend_cache_used"] is True for item in frontend_payload["items"])

    sellersprite_payload = json.loads(
        (tmp_path / "data/output/sellersprite_reverse_asin_results.json").read_text(encoding="utf-8")
    )
    roles = {item["source_role"] for item in sellersprite_payload["items"]}
    assert {"own", "competitor"} <= roles

    competitor_payload = json.loads(
        (tmp_path / "data/output/sellersprite_competitor_discovery_results.json").read_text(encoding="utf-8")
    )
    assert all(item["competitor_discovery_status"] == "已抓取" for item in competitor_payload["items"])
    assert all(item["competitor_count"] >= 3 for item in competitor_payload["items"])

    history_lines = (tmp_path / "data/output/sellersprite_history_snapshots.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) >= 18

    feedback_payload = json.loads((tmp_path / "data/output/autoopt_feedback_input.json").read_text(encoding="utf-8"))
    assert all(row["confirmed_status"] == "已执行" for row in feedback_payload["rows"])
    assert all(row["search_term_or_target"] for row in feedback_payload["rows"])

    try:
        setup_demo_data.setup_demo_data(force=False)
    except SystemExit as exc:
        assert "Refusing to overwrite existing file" in str(exc)
    else:
        raise AssertionError("setup_demo_data should refuse to overwrite existing demo targets")


def test_setup_demo_data_main_points_to_service_demo(monkeypatch, tmp_path, capsys) -> None:
    from scripts import setup_demo_data

    monkeypatch.setattr(setup_demo_data, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["setup_demo_data.py"])

    code = setup_demo_data.main()
    output = capsys.readouterr().out

    assert code == 0
    assert "scripts/run_report_window.py --workflow daily" in output
    assert "127.0.0.1:8765/report/latest_recommendations.html" in output
    assert "main.py --marketplace ALL --safe-run" not in output


def test_commit_readiness_blocks_staged_generated_files(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines([], cached=["data/output/latest_analysis.json"]),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main([])
    output = capsys.readouterr().out

    assert code == 1
    assert "generated data files changed or untracked" in output


def test_commit_readiness_blocks_staged_unknown_files(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines([], cached=["scripts/unassigned_helper.py"]),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main([])
    output = capsys.readouterr().out

    assert code == 1
    assert "changed files are not assigned to a commit group" in output


def test_commit_readiness_accepts_showcase_contract_docs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(["docs/business_confirmation_template.md", "docs/showcase_goal_contract.md"]),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main([])
    output = capsys.readouterr().out

    assert code == 0
    assert "showcase files: 2" in output
    assert "no manual config files changed" in output


def test_commit_readiness_strict_blocks_daily_entry_without_verification(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(["scripts/run_daily_update.py"]),
    )
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main(["--strict"])
    output = capsys.readouterr().out

    assert code == 1
    assert "daily update entry files changed" in output
    assert "daily update verification missing" in output


def test_commit_readiness_strict_blocks_unknown_inbox_even_without_git_changes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(readiness, "git_lines", _fake_git_lines([]))
    monkeypatch.setattr(
        readiness,
        "unknown_inbox_business_files",
        lambda: ["data/inbox/_unknown/metric.xlsx"],
    )
    monkeypatch.setattr(readiness, "validation_receipt_failures", lambda: [])

    code = readiness.main(["--strict"])
    output = capsys.readouterr().out

    assert code == 1
    assert "unknown inbox business files block daily update" in output
    assert "unknown inbox business files present" in output


def test_commit_readiness_strict_blocks_missing_validation_receipt(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        readiness,
        "git_lines",
        _fake_git_lines(["main.py"]),
    )
    monkeypatch.setattr(readiness, "parallel_lock_owner_failures", lambda paths: [])
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(
        readiness,
        "validation_receipt_failures",
        lambda: ["showcase validation receipt missing"],
    )

    code = readiness.main(
        [
            "--strict",
            "--business-review-confirmed",
            "--parallel-lock-owner-confirmed",
        ]
    )
    output = capsys.readouterr().out

    assert code == 1
    assert "showcase validation receipt issue: showcase validation receipt missing" in output
    assert "showcase validation receipt invalid or stale" in output


def test_commit_readiness_strict_blocks_stale_validation_receipt_without_git_changes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(readiness, "git_lines", _fake_git_lines([]))
    monkeypatch.setattr(readiness, "unknown_inbox_business_files", lambda: [])
    monkeypatch.setattr(
        readiness,
        "validation_receipt_failures",
        lambda: ["showcase validation receipt workspace_hash does not match current changes"],
    )

    code = readiness.main(["--strict"])
    output = capsys.readouterr().out

    assert code == 1
    assert "workspace_hash does not match current changes" in output
    assert "showcase validation receipt invalid or stale" in output


def test_validation_receipt_failures_blocks_schema_mismatch(monkeypatch, tmp_path) -> None:
    receipt = tmp_path / "showcase_validation_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 0,
                "result": "passed",
                "pytest_exit_code": 0,
                "safe_run_exit_code": 0,
                "output_validation_exit_code": 0,
                "git_head": "HEAD123",
                "workspace_hash": "hash123",
                "safe_run_dir": str(tmp_path),
                "report_date": "2026-06-24",
                "marketplaces": ["DE", "UK", "US"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(readiness, "VALIDATION_RECEIPT", receipt)
    monkeypatch.setattr(
        "scripts.validate_showcase_mvp.workspace_fingerprint",
        lambda: {"git_head": "HEAD123", "workspace_hash": "hash123"},
    )

    failures = readiness.validation_receipt_failures()

    assert "showcase validation receipt schema_version mismatch: expected 1, got <missing>" not in failures
    assert "showcase validation receipt schema_version mismatch: expected 1, got 0" in failures
