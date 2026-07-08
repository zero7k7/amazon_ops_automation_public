from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

import scripts.ensure_report_action_server as ensure_server
import scripts.report_action_server as server


class FakeUploadField:
    def __init__(self, filename: str, payload: bytes) -> None:
        self.filename = filename
        self.file = io.BytesIO(payload)


class FakeForm(dict):
    pass


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    output = root / "data" / "output"
    inbox = root / "data" / "inbox"
    staging = inbox / "_upload_staging"
    config = root / "config"
    review = root / "data" / "config_review"
    archive = root / "data" / "archive" / "config_updates"
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "OUTPUT_DIR", output)
    monkeypatch.setattr(server, "INBOX_DIR", inbox)
    monkeypatch.setattr(server, "UPLOAD_STAGING_DIR", staging)
    monkeypatch.setattr(server, "SUBMISSION_STATUS_PATH", output / "local_submission_status.json")
    monkeypatch.setattr(server, "CONFIG_DIR", config)
    monkeypatch.setattr(server, "CONFIG_REVIEW_DIR", review)
    monkeypatch.setattr(server, "CONFIG_ARCHIVE_DIR", archive)
    monkeypatch.setattr(
        server,
        "_start_sellersprite_reverse_async",
        lambda **kwargs: {
            "running": False,
            "returncode": 0,
            "status_scope": "sellersprite_async",
            "message": "test sellersprite skipped",
        },
    )
    monkeypatch.setattr(
        server,
        "CONFIG_UPLOAD_TARGETS",
        {
            "cost": {
                "label": "成本配置",
                "target_path": config / "product_cost_config.xlsx",
                "review_path": review / "product_cost_config.pending.xlsx",
                "allowed_filenames": {"product_cost_config.xlsx"},
                "required_sheets": {"product_cost_config": {"marketplace", "sku", "asin", "product_name", "currency"}},
                "review_command": None,
                "refresh_reports_after_apply": False,
                "requires_confirm": True,
            },
            "alias": {
                "label": "SKU 别名映射",
                "target_path": config / "sku_alias_map.xlsx",
                "review_path": review / "sku_alias_map.pending.xlsx",
                "allowed_filenames": {"sku_alias_map.xlsx"},
                "required_sheets": {"Sheet1": {"marketplace", "source_sku", "canonical_sku", "asin"}},
                "review_command": None,
                "refresh_reports_after_apply": False,
                "requires_confirm": False,
            },
        },
    )
    return inbox


def test_sellersprite_needed_summary_marks_stale_own_cache_missing(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "US",
                                    "sku": "SKU-1",
                                    "asin": "B0STALEOWN",
                                    "product_name": "Stale own cache",
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0STALEOWN",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": yesterday,
                        "keywords": [{"keyword": "old keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = server._sellersprite_reverse_needed_summary()

    assert summary["sellersprite_cached_count"] == 0
    assert "US B0STALEOWN" in summary["sellersprite_missing_labels"]


def test_sellersprite_needed_summary_does_not_treat_failed_cache_as_available(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "US",
                                    "sku": "SKU-1",
                                    "asin": "B0FAILCACHE",
                                    "product_name": "Failed cache",
                                },
                                {
                                    "marketplace": "US",
                                    "sku": "SKU-2",
                                    "asin": "B0EMPTYKEYS",
                                    "product_name": "Empty keywords",
                                },
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0FAILCACHE",
                        "seller_sprite_check_status": "抓取失败",
                        "data_date": today,
                        "keywords": [],
                    },
                    {
                        "marketplace": "US",
                        "asin": "B0EMPTYKEYS",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": today,
                        "keywords": [],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = server._sellersprite_reverse_needed_summary()

    assert summary["sellersprite_cached_count"] == 0
    assert summary["sellersprite_missing_count"] >= 2
    assert "US B0FAILCACHE" in summary["sellersprite_missing_labels"]
    assert "US B0EMPTYKEYS" in summary["sellersprite_missing_labels"]


def test_status_payload_refreshes_stale_sellersprite_no_run_message(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "US",
                                    "sku": "SKU-1",
                                    "asin": "B0FAILCACHE",
                                    "product_name": "Failed cache",
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0FAILCACHE",
                        "seller_sprite_check_status": "抓取失败",
                        "data_date": today,
                        "keywords": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    server._last_result = {"running": False, "message": "ready"}
    server._write_submission_status(
        {
            "running": False,
            "message": "ready",
            "sellersprite_async_status": {
                "running": False,
                "message": "卖家精灵后台反查无需运行：当前前台队列已有缓存。",
                "sellersprite_missing_count": 0,
            },
        }
    )

    payload = server._status_payload()

    seller_status = payload["sellersprite_async_status"]
    assert "本次需抓" in seller_status["message"]
    assert seller_status["sellersprite_missing_count"] >= 1
    assert "US B0FAILCACHE" in seller_status["sellersprite_missing_labels"]


def test_status_payload_replaces_stale_sellersprite_missing_count_when_cache_now_valid(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        server,
        "SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH",
        server.OUTPUT_DIR / "sellersprite_competitor_discovery_results.json",
    )
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(
        server._sellersprite_competitor_rows.__globals__,
        "SELLERSPRITE_CACHE_PATH",
        server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json",
    )
    today = date.today().isoformat()
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "priority": "P0",
                                    "marketplace": "US",
                                    "sku": "SKU-1",
                                    "asin": "B0VALID001",
                                    "product_name": "Valid cache",
                                    "frontend_competitor_count": 3,
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_competitor_discovery_results.json").write_text(
        json.dumps(
            {
                "items": [
                        {
                            "marketplace": "US",
                            "sku": "SKU-1",
                            "asin": "B0VALID001",
                            "competitor_discovery_status": "已抓取",
                            "data_date": today,
                            "checked_at": f"{today}T16:00:00",
                            "competitors": [
                                {
                                    "competitor_asin": "B0COMP0001",
                                    "competitor_title": "Valid competitor",
                                    "competitor_source": "sellersprite_keyword_overlap",
                                }
                            ],
                        }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0VALID001",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": today,
                        "checked_at": f"{today}T16:00:00",
                        "keywords": [{"keyword": "valid keyword"}],
                    },
                    {
                        "marketplace": "US",
                        "asin": "B0COMP0001",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": today,
                        "checked_at": f"{today}T16:00:00",
                        "keywords": [{"keyword": "valid keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    server._last_result = {"running": False, "message": "ready"}
    server._sellersprite_async_status = {"running": False, "message": "本次需抓 1 个 ASIN。"}
    server._write_submission_status(
        {
            "running": False,
            "message": "ready",
            "sellersprite_missing_count": 1,
            "sellersprite_missing_labels": ["US B0VALID001"],
            "sellersprite_async_status": {
                "running": False,
                "message": "本次需抓 1 个 ASIN。",
                "sellersprite_missing_count": 1,
            },
        }
    )

    payload = server._status_payload()

    assert payload["sellersprite_cached_count"] == 2
    assert payload["sellersprite_missing_count"] == 0
    assert payload["sellersprite_missing_labels"] == []
    assert payload["sellersprite_async_status"]["sellersprite_missing_count"] == 0
    assert "已有有效反查" in payload["sellersprite_async_status"]["message"]


def test_status_payload_shows_valid_cache_after_service_restart(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        server,
        "SELLERSPRITE_COMPETITOR_DISCOVERY_CACHE_PATH",
        server.OUTPUT_DIR / "sellersprite_competitor_discovery_results.json",
    )
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(
        server._sellersprite_competitor_rows.__globals__,
        "SELLERSPRITE_CACHE_PATH",
        server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json",
    )
    today = date.today().isoformat()
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "priority": "P0",
                                    "marketplace": "US",
                                    "sku": "SKU-1",
                                    "asin": "B0VALID001",
                                    "product_name": "Valid cache",
                                    "frontend_competitor_count": 3,
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_competitor_discovery_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "sku": "SKU-1",
                        "asin": "B0VALID001",
                        "competitor_discovery_status": "已抓取",
                        "data_date": today,
                        "checked_at": f"{today}T16:00:00",
                        "competitors": [
                            {
                                "competitor_asin": "B0COMP0001",
                                "competitor_title": "Valid competitor",
                                "competitor_source": "sellersprite_keyword_overlap",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0VALID001",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": today,
                        "checked_at": f"{today}T16:00:00",
                        "keywords": [{"keyword": "valid keyword"}],
                    },
                    {
                        "marketplace": "US",
                        "asin": "B0COMP0001",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": today,
                        "checked_at": f"{today}T16:00:00",
                        "keywords": [{"keyword": "valid keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    server._last_result = {"running": False, "message": "ready"}
    server._sellersprite_async_status = {"running": False, "message": "卖家精灵后台反查未运行。"}
    server._write_submission_status(
        {
            "running": False,
            "message": "ready",
            "sellersprite_async_status": {
                "running": False,
                "message": "卖家精灵后台反查未运行。",
            },
        }
    )

    payload = server._status_payload()

    assert payload["sellersprite_cached_count"] == 2
    assert payload["sellersprite_missing_count"] == 0
    assert "已有有效反查" in payload["sellersprite_async_status"]["message"]


def test_sellersprite_no_run_path_snapshots_cached_queue(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "US",
                                    "sku": "SKU-1",
                                    "asin": "B0CACHED01",
                                    "product_name": "Cached own",
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "US",
                        "asin": "B0CACHED01",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": today,
                        "keywords": [{"keyword": "cached keyword"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[list[dict]] = []
    monkeypatch.setattr(server, "upsert_sellersprite_history", lambda records, **kwargs: calls.append(list(records)))

    count = server._snapshot_cached_sellersprite_queue()

    assert count == 1
    assert calls[0][0]["asin"] == "B0CACHED01"
    assert calls[0][0]["seller_sprite_check_status"] == "已抓取"


def _xlsx_bytes(sheet_name: str, headers: list[str], row: list[object]) -> bytes:
    workbook = Workbook()
    ws = workbook.active
    ws.title = sheet_name
    ws.append(headers)
    ws.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_safe_upload_name_strips_path_and_unsafe_chars() -> None:
    assert server._safe_upload_name("../../ads report?.csv") == "ads report_.csv"
    assert server._safe_upload_name("今日 销售.xlsx") == "今日 销售.xlsx"


def test_validate_upload_name_rejects_bad_extension_and_large_file() -> None:
    _, extension_error = server._validate_upload_name("notes.txt", 10)
    _, size_error = server._validate_upload_name("ads.csv", server.MAX_UPLOAD_BYTES + 1)
    _, empty_error = server._validate_upload_name("ads.csv", 0)

    assert "只允许上传" in extension_error
    assert "超过 50MB" in size_error
    assert "文件为空" in empty_error
    assert server._validate_upload_name("ads.csv", 10)[1] == ""


def test_startup_clears_stale_frontend_retry_not_needed_status(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server.SUBMISSION_STATUS_PATH.write_text(
        json.dumps(
            {
                "running": False,
                "message": "无需刷新：7/7 个已有今日前台证据；未访问 Amazon。",
                "status_scope": "frontend_retry",
                "failure_mode": "frontend_refresh_not_needed",
                "frontend_refresh_total": 7,
                "frontend_refresh_skipped": 7,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    server._clear_stale_running_status_on_startup()

    payload = json.loads(server.SUBMISSION_STATUS_PATH.read_text(encoding="utf-8"))
    assert payload["status_scope"] == "frontend_retry_idle"
    assert payload["failure_mode"] == "frontend_retry_stale_result_cleared"
    assert "点击按钮会重新读取当前队列" in payload["message"]
    assert "frontend_refresh_skipped" not in payload


def test_save_uploaded_files_rejects_whole_batch_when_any_file_is_invalid(monkeypatch, tmp_path) -> None:
    inbox = _patch_paths(monkeypatch, tmp_path)
    form = FakeForm(
        {
            "files": [
                FakeUploadField("../../ads?.csv", b"header\nvalue\n"),
                FakeUploadField("bad.txt", b"bad"),
            ]
        }
    )

    saved, errors = server._save_uploaded_files(form)

    assert saved == []
    assert not (inbox / "ads_.csv").exists()
    assert errors and "只允许上传" in errors[0]


def test_save_uploaded_files_moves_valid_files_to_inbox(monkeypatch, tmp_path) -> None:
    inbox = _patch_paths(monkeypatch, tmp_path)
    form = FakeForm({"files": [FakeUploadField("../../ads?.csv", b"header\nvalue\n")]})

    saved, errors = server._save_uploaded_files(form)

    assert errors == []
    assert len(saved) == 1
    assert saved[0]["saved_filename"] == "ads_.csv"
    assert (inbox / "ads_.csv").read_bytes() == b"header\nvalue\n"


def test_save_uploaded_files_moves_multiple_valid_files_to_inbox(monkeypatch, tmp_path) -> None:
    inbox = _patch_paths(monkeypatch, tmp_path)
    form = FakeForm(
        {
            "files": [
                FakeUploadField("ads.csv", b"ad\n1\n"),
                FakeUploadField("erp.xlsx", b"erp\n1\n"),
            ]
        }
    )

    saved, errors = server._save_uploaded_files(form)

    assert errors == []
    assert [row["saved_filename"] for row in saved] == ["ads.csv", "erp.xlsx"]
    assert (inbox / "ads.csv").read_bytes() == b"ad\n1\n"
    assert (inbox / "erp.xlsx").read_bytes() == b"erp\n1\n"


def test_submission_status_persists_report_links(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    server._write_submission_status({"running": False, "message": "ok"})
    payload = server._load_submission_status()

    assert payload["message"] == "ok"
    assert payload["report_links"]["dashboard"].endswith("/report/dashboard.html")
    assert server.SUBMISSION_STATUS_PATH.exists()
    raw = json.loads(server.SUBMISSION_STATUS_PATH.read_text(encoding="utf-8"))
    assert raw["running"] is False


def test_completed_payload_drops_stale_runtime_fields(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server._write_submission_status(
        {
            "running": True,
            "message": "old",
            "step": 1,
            "total_steps": 1,
            "started_at_epoch": 100,
            "elapsed_seconds": 999,
        }
    )
    completed = subprocess.CompletedProcess(["cmd"], 0, stdout="ok", stderr="")

    payload = server._completed_payload(completed, "done", "failed")

    assert payload["running"] is False
    assert payload["message"] == "done"
    assert payload["returncode"] == 0
    assert "elapsed_seconds" not in payload
    assert "started_at_epoch" not in payload
    assert "step" not in payload
    assert "total_steps" not in payload


def test_run_command_with_status_returns_127_when_process_cannot_start(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    def raise_popen_error(*args, **kwargs):
        raise OSError("spawn denied")

    monkeypatch.setattr(server.subprocess, "Popen", raise_popen_error)

    completed = server._run_command_with_status(
        [server.sys.executable, "scripts/run_daily_update.py"],
        timeout=1,
        step=1,
        total_steps=1,
        message="运行 daily update",
    )

    assert completed.returncode == 127
    assert completed.stdout == ""
    assert "cannot start command: spawn denied" in completed.stderr


def test_run_command_returns_127_when_process_cannot_start(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    def raise_run_error(*args, **kwargs):
        raise OSError("spawn denied")

    monkeypatch.setattr(server.subprocess, "run", raise_run_error)

    completed = server._run_command([server.sys.executable, "main.py", "--marketplace", "ALL"], timeout=1)

    assert completed.returncode == 127
    assert completed.stdout == ""
    assert "cannot start command: spawn denied" in completed.stderr


def test_status_payload_hides_runtime_fields_after_completion(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server._sync_last_result(
        {
            "running": False,
            "message": "done",
            "step": 1,
            "total_steps": 1,
            "started_at_epoch": 100,
            "elapsed_seconds": 999,
        }
    )

    payload = server._status_payload()

    assert payload["running"] is False
    assert payload["message"] == "done"
    assert "elapsed_seconds" not in payload
    assert "started_at_epoch" not in payload


def test_status_payload_normalizes_legacy_frontend_retry_failure(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server._last_result = {"running": False, "message": "ready"}
    server._write_submission_status(
        {
            "running": False,
            "message": "前台数据重试失败：urllib 读取 Amazon 前台",
            "returncode": 1,
        }
    )

    payload = server._status_payload()

    assert payload["message"].startswith("urllib 快速重试失败")
    assert payload["returncode"] == 1
    assert payload["soft_failure"] is True
    assert payload["failure_mode"] == "urllib_frontend_blocked"


def test_status_payload_downgrades_restored_daily_update_failure_when_report_exists(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server._last_result = {"running": False, "message": "ready"}
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_recommendations.html").write_text("<html>ok</html>", encoding="utf-8")
    server._write_submission_status(
        {
            "running": False,
            "message": "daily update 失败，请查看输出摘要。",
            "returncode": 1,
            "stdout_tail": "\n".join(
                [
                    "[fail] report refresh blocker: import manifest successful core row 1 ads_report.csv missing parseable date",
                    "[restore] report outputs restored to pre-report snapshot after failure; database/archive state restored when tracked",
                ]
            ),
            "stderr_tail": "",
        }
    )

    payload = server._status_payload()

    assert payload["returncode"] == 0
    assert payload["original_returncode"] == 1
    assert payload["soft_failure"] is True
    assert payload["status_scope"] == "daily_update_restored_report"
    assert payload["failure_mode"] == "import_manifest_date_blocker_restored_report"
    assert "报告可用" in str(payload["message"])


def test_status_payload_keeps_restored_daily_update_failure_red_when_report_missing(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server._last_result = {"running": False, "message": "ready"}
    server._write_submission_status(
        {
            "running": False,
            "message": "daily update 失败，请查看输出摘要。",
            "returncode": 1,
            "stdout_tail": "\n".join(
                [
                    "[fail] report refresh blocker: import manifest successful core row 1 ads_report.csv missing parseable date",
                    "[restore] report outputs restored to pre-report snapshot after failure; database/archive state restored when tracked",
                ]
            ),
            "stderr_tail": "",
        }
    )

    payload = server._status_payload()

    assert payload["returncode"] == 1
    assert "original_returncode" not in payload
    assert payload["message"] == "daily update 失败，请查看输出摘要。"


def test_status_payload_normalizes_legacy_chrome_frontend_retry_message(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "UK",
                                    "asin": "B0PASS0001",
                                    "frontend_check_status": "已自动检查",
                                    "frontend_check_method": "chrome-cdp",
                                    "frontend_data_date": "2026-06-17",
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    server._last_result = {"running": False, "message": "ready"}
    server._write_submission_status(
        {
            "running": False,
            "message": "真实 Chrome 20次前台检查失败，已保留现有前台缓存。失败步骤：真实 Chrome CDP 20次前台检查",
            "returncode": 1,
            "failure_mode": "chrome_cdp_frontend_check_failed",
        }
    )

    payload = server._status_payload()

    assert payload["message"] == "调查完成：本轮队列 1/1。"
    assert "真实 Chrome 20次前台检查" not in payload["message"]
    assert payload["status_scope"] == "frontend_retry"
    assert payload["failure_mode"] == "chrome_cdp_frontend_check_passed"


def test_status_payload_compacts_current_frontend_retry_message(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    rows = [
        {
            "marketplace": "UK",
            "asin": f"B0PASS000{index}",
            "frontend_check_status": "已自动检查",
            "frontend_check_method": "chrome-cdp",
            "frontend_data_date": "2026-06-17",
        }
        for index in range(7)
    ]
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"marketplace_results": [{"report_view_snapshot": {"frontend_check_queue_rows": rows}}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    server._last_result = {"running": False, "message": "ready"}
    server._write_submission_status(
        {
            "running": False,
            "message": "当前前台队列刷新通过：新读 7 个，跳过 0 个，沿用缓存 0 个，失败 0 个；今日证据 7/7，队列成功率 100%，门槛 80%。",
            "returncode": 0,
            "status_scope": "frontend_retry",
            "frontend_refresh_total": 7,
            "frontend_refresh_live_checked": 7,
            "frontend_refresh_skipped": 0,
            "frontend_refresh_cache_used": 0,
            "frontend_refresh_failed": 0,
        }
    )

    payload = server._status_payload()

    assert payload["message"] == "调查完成：本轮队列 7/7，新读 7，失败 0。"
    assert "当前前台队列刷新" not in str(payload["message"])


def test_status_payload_reclassifies_partial_frontend_retry_from_latest_report(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "UK",
                                    "asin": "B0PASS0001",
                                    "frontend_check_status": "已自动检查",
                                    "frontend_check_method": "chrome-cdp",
                                    "frontend_stability_passed": True,
                                    "frontend_stability_total_attempts": 20,
                                    "frontend_stability_success_rate": 1.0,
                                    "frontend_data_date": "2026-06-17",
                                },
                                {
                                    "marketplace": "DE",
                                    "asin": "B0WAIT0001",
                                    "frontend_check_status": "待前台检查",
                                },
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    server._last_result = {"running": False, "message": "ready"}
    server._write_submission_status(
        {
            "running": False,
            "message": "当前前台队列 20次验收失败，已保留现有前台缓存。",
            "returncode": 1,
            "status_scope": "frontend_retry",
            "failure_mode": "chrome_cdp_frontend_check_failed",
        }
    )

    payload = server._status_payload()

    assert payload["soft_failure"] is True
    assert payload["failure_mode"] == "chrome_cdp_frontend_check_partial"
    assert payload["frontend_live_passed_count"] == 1
    assert payload["frontend_queue_total"] == 2
    assert payload["frontend_queue_passed"] is False
    assert "本轮队列 1/2" in str(payload["message"])
    assert "调查待补" in str(payload["message"])
    assert "DE B0WAIT0001" in str(payload["message"])


def test_status_payload_accepts_frontend_retry_when_queue_success_rate_reaches_80(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    rows = [
        {
            "marketplace": "UK",
            "asin": f"B0PASS000{index}",
            "frontend_check_status": "已自动检查",
            "frontend_check_method": "chrome-cdp",
            "frontend_stability_passed": True,
            "frontend_stability_total_attempts": 20,
            "frontend_stability_success_rate": 0.8,
            "frontend_data_date": "2026-06-17",
        }
        for index in range(4)
    ]
    rows.append({"marketplace": "DE", "asin": "B0WAIT0001", "frontend_check_status": "待前台检查"})
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"marketplace_results": [{"report_view_snapshot": {"frontend_check_queue_rows": rows}}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    server._last_result = {"running": False, "message": "ready"}
    server._write_submission_status(
        {
            "running": False,
            "message": "当前前台队列 20次验收失败，已保留现有前台缓存。",
            "returncode": 1,
            "status_scope": "frontend_retry",
            "failure_mode": "chrome_cdp_frontend_check_failed",
        }
    )

    payload = server._status_payload()

    assert payload["soft_failure"] is True
    assert payload["failure_mode"] == "chrome_cdp_frontend_check_passed_with_pending"
    assert payload["frontend_live_passed_count"] == 4
    assert payload["frontend_queue_total"] == 5
    assert payload["frontend_queue_success_rate"] == 0.8
    assert payload["frontend_queue_passed"] is True
    assert "调查完成" in str(payload["message"])
    assert "本轮队列 4/5" in str(payload["message"])
    assert "DE B0WAIT0001" in str(payload["message"])


def test_report_file_response_disables_browser_cache(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = server.OUTPUT_DIR / "latest_recommendations.html"
    report_path.write_text("<!doctype html><title>report</title>", encoding="utf-8")
    sent_headers: dict[str, str] = {}

    handler = object.__new__(server.Handler)
    handler.wfile = io.BytesIO()
    handler.headers = {}

    def fake_send_response(status: int, message: str | None = None) -> None:
        sent_headers[":status"] = str(status)

    def fake_send_header(key: str, value: object) -> None:
        sent_headers[key] = str(value)

    monkeypatch.setattr(handler, "send_response", fake_send_response)
    monkeypatch.setattr(handler, "send_header", fake_send_header)
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    handler._send_file(report_path)

    assert sent_headers[":status"] == "200"
    assert sent_headers["Cache-Control"] == "no-store"
    assert sent_headers["Pragma"] == "no-cache"
    assert 'name="report-action-token"' in handler.wfile.getvalue().decode("utf-8")


def test_missing_latest_report_returns_empty_state_page(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sent_headers: dict[str, str] = {}

    handler = object.__new__(server.Handler)
    handler.wfile = io.BytesIO()
    handler.headers = {}

    def fake_send_response(status: int, message: str | None = None) -> None:
        sent_headers[":status"] = str(status)

    def fake_send_header(key: str, value: object) -> None:
        sent_headers[key] = str(value)

    monkeypatch.setattr(handler, "send_response", fake_send_response)
    monkeypatch.setattr(handler, "send_header", fake_send_header)
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    handler._send_file(server.OUTPUT_DIR / "latest_recommendations.html")

    body = handler.wfile.getvalue().decode("utf-8")
    assert sent_headers[":status"] == "200"
    assert sent_headers["Content-Type"] == "text/html; charset=utf-8"
    assert "公共版当前没有报告数据" in body
    assert "B0B5HPKZKM" not in body
    assert "B0H73CXQ5J" not in body
    assert "B0BPC8WZL8" not in body


def test_missing_non_latest_report_still_returns_404(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sent_headers: dict[str, str] = {}

    handler = object.__new__(server.Handler)
    handler.wfile = io.BytesIO()
    handler.headers = {}

    def fake_send_response(status: int, message: str | None = None) -> None:
        sent_headers[":status"] = str(status)

    def fake_send_header(key: str, value: object) -> None:
        sent_headers[key] = str(value)

    monkeypatch.setattr(handler, "send_response", fake_send_response)
    monkeypatch.setattr(handler, "send_header", fake_send_header)
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    handler._send_file(server.OUTPUT_DIR / "dashboard.html")

    body = handler.wfile.getvalue().decode("utf-8")
    assert sent_headers[":status"] == "404"
    assert "report file not found" in body


def test_action_token_is_local_file_and_validates_header(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    token = server._load_or_create_action_token()

    assert len(token) >= 32
    assert server._action_token_path() == server.OUTPUT_DIR / ".report_action_token"
    assert server._action_token_path().exists()
    assert server._is_valid_action_token(token) is True
    assert server._is_valid_action_token("wrong-token") is False


def test_no_token_write_request_is_rejected(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    handler = object.__new__(server.Handler)
    handler.headers = {}
    handler.wfile = io.BytesIO()
    sent: dict[str, str] = {}

    monkeypatch.setattr(handler, "send_response", lambda status, message=None: sent.setdefault(":status", str(status)))
    monkeypatch.setattr(handler, "send_header", lambda key, value: sent.setdefault(key, str(value)))
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    accepted = handler._require_action_token(server.urlparse("/feedback/ad-action-complete"))

    assert accepted is False
    assert sent[":status"] == "403"
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["ok"] is False
    assert "token" in payload["message"]


def test_local_origin_cors_is_limited_and_not_wildcard(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    handler = object.__new__(server.Handler)
    handler.headers = {"Origin": "http://127.0.0.1:8765"}
    handler.wfile = io.BytesIO()
    headers: dict[str, str] = {}

    monkeypatch.setattr(handler, "send_response", lambda status, message=None: headers.setdefault(":status", str(status)))
    monkeypatch.setattr(handler, "send_header", lambda key, value: headers.setdefault(key, str(value)))
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    handler._send_json(200, {"ok": True})

    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8765"
    assert headers["Access-Control-Allow-Origin"] != "*"
    assert "X-Report-Action-Token" in headers["Access-Control-Allow-Headers"]


def test_untrusted_origin_gets_no_cors_allow_header(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    handler = object.__new__(server.Handler)
    handler.headers = {"Origin": "https://example.com"}
    handler.wfile = io.BytesIO()
    headers: dict[str, str] = {}

    monkeypatch.setattr(handler, "send_response", lambda status, message=None: headers.setdefault(":status", str(status)))
    monkeypatch.setattr(handler, "send_header", lambda key, value: headers.setdefault(key, str(value)))
    monkeypatch.setattr(handler, "end_headers", lambda: None)

    handler._send_json(200, {"ok": True})

    assert "Access-Control-Allow-Origin" not in headers


def test_get_run_endpoints_are_method_not_allowed_and_do_not_run(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    for path, method_name in [
        ("/run/report-refresh", "_start_report_refresh"),
        ("/run/frontend-retry", "_start_frontend_retry"),
    ]:
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.headers = {}
        handler.wfile = io.BytesIO()
        sent: dict[str, str] = {}

        monkeypatch.setattr(handler, "send_response", lambda status, message=None, sent=sent: sent.setdefault(":status", str(status)))
        monkeypatch.setattr(handler, "send_header", lambda key, value, sent=sent: sent.setdefault(key, str(value)))
        monkeypatch.setattr(handler, "end_headers", lambda: None)
        monkeypatch.setattr(handler, method_name, lambda: (_ for _ in ()).throw(AssertionError("GET triggered side effect")))

        handler.do_GET()

        assert sent[":status"] == "405"
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        assert payload["ok"] is False
        assert "POST" in payload["message"]


def test_valid_token_allows_all_side_effect_post_dispatch(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    token = server._load_or_create_action_token()
    cases = [
        ("/upload/today-data", "_handle_today_upload", None),
        ("/upload/config?kind=cost", "_handle_config_upload", "cost"),
        ("/apply/config?kind=alias", "_handle_config_apply", "alias"),
        ("/copy/text", "_handle_copy_text", None),
        ("/run/report-refresh", "_start_report_refresh", None),
        ("/run/daily-update", "_start_daily_update", None),
        ("/run/frontend-retry", "_start_frontend_retry", None),
        ("/run/frontend-check-one?marketplace=US&asin=B0TEST0001", "_start_frontend_check_one", "US"),
        ("/run/battle-diagnosis-one?marketplace=US&asin=B0TEST0001", "_start_battle_diagnosis_one", "US"),
        ("/feedback/ad-action-complete", "_handle_ad_action_complete", None),
        ("/feedback/ad-action-cancel", "_handle_ad_action_cancel", None),
    ]

    for path, method_name, expected_param in cases:
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.headers = {server.ACTION_TOKEN_HEADER: token}
        calls: list[tuple[str, object]] = []

        def forbidden_json(status: int, payload: dict[str, object]) -> None:
            raise AssertionError(f"{path} was blocked with {status}: {payload}")

        monkeypatch.setattr(handler, "_send_json", forbidden_json)
        if expected_param is None:
            monkeypatch.setattr(handler, method_name, lambda name=method_name: calls.append((name, None)))
        else:
            monkeypatch.setattr(handler, method_name, lambda params, name=method_name: calls.append((name, params)))

        handler.do_POST()

        assert calls and calls[0][0] == method_name
        if expected_param is not None:
            assert calls[0][1]["marketplace" if "marketplace" in calls[0][1] else "kind"] == expected_param


def test_copy_text_endpoint_writes_pbcopy(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    handler = object.__new__(server.Handler)
    body = json.dumps({"text": "keyword\t站点=UK | 动作=小预算试投"}).encode("utf-8")
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    sent: dict[str, object] = {}
    pbcopy_calls: list[dict[str, object]] = []

    def fake_run(args, **kwargs):
        pbcopy_calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(handler, "_send_json", lambda status, payload: sent.update({"status": status, "payload": payload}))

    handler._handle_copy_text()

    assert sent["status"] == 200
    assert sent["payload"]["ok"] is True
    assert pbcopy_calls[0]["args"] == ["pbcopy"]
    assert pbcopy_calls[0]["input"] == "keyword\t站点=UK | 动作=小预算试投"


def test_copy_text_endpoint_reports_pbcopy_start_failure(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    handler = object.__new__(server.Handler)
    body = json.dumps({"text": "keyword\t站点=UK | 动作=小预算试投"}).encode("utf-8")
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    sent: dict[str, object] = {}

    def fake_run(args, **kwargs):
        raise OSError("pbcopy missing")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(handler, "_send_json", lambda status, payload: sent.update({"status": status, "payload": payload}))

    handler._handle_copy_text()

    assert sent["status"] == 500
    assert sent["payload"]["ok"] is False
    assert sent["payload"]["message"] == "本机复制命令不可用：pbcopy missing"


def test_ensure_server_accepts_token_protected_ad_completion_endpoint(monkeypatch) -> None:
    def fake_urlopen(request, timeout=0.8):
        body = json.dumps({"ok": False, "message": "本地确认服务 token 缺失或无效"}).encode("utf-8")
        raise urllib.error.HTTPError(str(request.full_url), 403, "Forbidden", {}, io.BytesIO(body))

    monkeypatch.setattr(ensure_server.urllib.request, "urlopen", fake_urlopen)

    assert ensure_server._ad_completion_endpoint_ok() is True


def test_append_ad_completion_feedback_writes_required_fields_and_dedupes(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"report_date": "2026-06-17"}, ensure_ascii=False),
        encoding="utf-8",
    )

    row = {
        "marketplace": "US",
        "sku": "SKU-1",
        "asin": "B0TEST1234",
        "product_name": "Test product",
        "search_term_or_target": "metal board",
        "suggested_action": "降竞价10%-20%",
        "manual_action_taken": "降竞价 10%-20%",
        "confirmed_at": "2026-06-18 09:30:00",
    }

    feedback, appended, row_count = server.append_ad_completion_feedback(row)
    duplicate, duplicate_appended, duplicate_count = server.append_ad_completion_feedback(row)
    payload = json.loads((server.OUTPUT_DIR / "autoopt_feedback_input.json").read_text(encoding="utf-8"))

    assert appended is True
    assert row_count == 1
    assert duplicate_appended is False
    assert duplicate_count == 1
    assert duplicate["action_id"] == feedback["action_id"]
    assert len(payload["rows"]) == 1
    saved = payload["rows"][0]
    assert saved["confirmed_status"] == "已执行"
    assert saved["normalized_action"] == "bid_down"
    assert saved["action_scope"] == "search_term"
    assert saved["report_date"] == "2026-06-17"
    assert saved["next_review"] == "2026-06-21"
    assert saved["cooldown_days"] == 7
    assert saved["search_term_or_target"] == "metal board"
    audit_rows = []
    for audit_path in server.OUTPUT_DIR.glob("feedback_audit_log_*.json"):
        audit_rows.extend(json.loads(audit_path.read_text(encoding="utf-8")))
    assert any(
        row.get("event") == "complete_action"
        and row.get("action_id") == saved["action_id"]
        and row.get("previous_status") == "待确认"
        and row.get("new_status") == "已执行"
        for row in audit_rows
    )


def test_append_ad_completion_feedback_rejects_observation_actions(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    try:
        server.append_ad_completion_feedback(
            {
                "marketplace": "UK",
                "sku": "SKU-1",
                "asin": "B0TEST1234",
                "search_term_or_target": "demo notebook",
                "suggested_action": "观察",
                "manual_action_taken": "观察",
            }
    )
    except ValueError as exc:
        assert "不属于可执行广告动作" in str(exc)
    else:
        raise AssertionError("observation action should not be appended")


def test_ad_completion_feedback_round_trip_removes_copy_row_and_writes_keyword_review(monkeypatch, tmp_path) -> None:
    import src.autoopt_feedback as autoopt_feedback
    import src.report_presentation as report_presentation
    from src.generate_html_report import _render_ad_workbench

    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"report_date": "2026-06-17"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(report_presentation, "OUTPUT_DIR", server.OUTPUT_DIR)

    original_row = {
        "marketplace": "US",
        "sku": "SKU-1",
        "asin": "B0TEST1234",
        "product_name": "Test product",
        "search_term_or_target": "metal board",
        "campaign": "Manual Exact",
        "match_type_or_targeting": "exact",
        "suggested_action": "降竞价10%-20%",
        "copy_action_line": "建议降竞价 10%-20%",
        "confirmed_status": "待确认",
        "clicks": "8",
        "orders": "0",
        "spend": "$4.20",
        "reason": "8 clicks no promoted order",
        "html_visible": "是",
    }

    feedback, appended, _ = server.append_ad_completion_feedback(
        {
            **original_row,
            "manual_action_taken": "降竞价 10%-20%",
            "confirmed_at": "2026-06-18 09:30:00",
        }
    )

    assert appended is True
    assert feedback["normalized_action"] == "bid_down"

    refreshed_rows = report_presentation._apply_manual_feedback_to_search_queue([dict(original_row)])
    assert refreshed_rows[0]["confirmed_status"] == "已执行"

    html = _render_ad_workbench(
        refreshed_rows,
        all_marketplaces=True,
        anchor_id="today-ad-actions-all",
    )

    assert '<span class="status-badge status-muted">今天无新广告动作</span>' in html
    assert "当前没有需要复制执行的广告动作。" in html
    assert 'data-ad-copy-row' not in html
    assert "已执行留档" in html

    payload = autoopt_feedback.build_autoopt_payload(
        [
            {
                "has_data": True,
                "marketplace": "US",
                "summary": {"report_date": "2026-06-17"},
                "analysis_payload": {"target_marketplace": "US"},
                "report_view": {"search_term_processing_queue_rows": [original_row]},
            }
        ],
        output_dir=server.OUTPUT_DIR,
    )
    autoopt_feedback.write_autoopt_outputs(server.OUTPUT_DIR, "2026-06-17", payload)

    review_path = server.OUTPUT_DIR / "keyword_action_review_20260617.json"
    review_rows = json.loads(review_path.read_text(encoding="utf-8"))

    assert any(
        row.get("search_term_or_target") == "metal board"
        and row.get("normalized_action") == "bid_down"
        and row.get("action_id") == feedback["action_id"]
        for row in review_rows
    )


def test_growth_test_completion_preserves_experiment_fields_and_writes_review(monkeypatch, tmp_path) -> None:
    import src.autoopt_feedback as autoopt_feedback

    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"report_date": "2026-06-17"}, ensure_ascii=False),
        encoding="utf-8",
    )

    feedback, appended, row_count = server.append_ad_completion_feedback(
        {
            "marketplace": "UK",
            "sku": "SKU-PUBLIC-UK-GROWTH-01",
            "asin": "B0H73CXQ5J",
            "product_name": "Public craft sample",
            "search_term_or_target": "adjustable desk lamp",
            "suggested_action": "推广实验",
            "manual_action_taken": "推广实验",
            "confirmed_at": "2026-06-18 09:30:00",
            "experiment_type": "growth_test",
            "term_source": "search_term_report",
            "evidence_level": "强意图长尾",
            "suggested_daily_budget": "£1.50/天",
            "suggested_bid_min": "£0.30",
            "suggested_bid_max": "£0.38",
            "test_days": "7",
            "stop_loss_rule": "7天点击达到 12 次仍无本 SKU 订单则停。",
            "success_rule": "7天内至少出现本 SKU 订单。",
        }
    )

    assert appended is True
    assert row_count == 1
    assert feedback["normalized_action"] == "growth_test"
    assert feedback["experiment_type"] == "growth_test"
    assert feedback["term_source"] == "search_term_report"
    assert feedback["suggested_bid_min"] == "£0.30"
    assert feedback["suggested_bid_max"] == "£0.38"

    payload = autoopt_feedback.build_autoopt_payload(
        [
            {
                "has_data": True,
                "marketplace": "UK",
                "summary": {"report_date": "2026-06-17"},
                "analysis_payload": {"target_marketplace": "UK"},
                "report_view": {"search_term_processing_queue_rows": []},
            }
        ],
        output_dir=server.OUTPUT_DIR,
    )
    autoopt_feedback.write_autoopt_outputs(server.OUTPUT_DIR, "2026-06-17", payload)

    review_rows = json.loads((server.OUTPUT_DIR / "keyword_action_review_20260617.json").read_text(encoding="utf-8"))
    assert any(
        row.get("search_term_or_target") == "adjustable desk lamp"
        and row.get("normalized_action") == "growth_test"
        and row.get("action_id") == feedback["action_id"]
        for row in review_rows
    )


def test_growth_test_batch_completion_writes_term_level_self_optimization_rows(monkeypatch, tmp_path) -> None:
    import src.autoopt_feedback as autoopt_feedback

    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"report_date": "2026-06-17"}, ensure_ascii=False),
        encoding="utf-8",
    )

    base = {
        "marketplace": "UK",
        "sku": "SKU-PUBLIC-UK-GROWTH-01",
        "asin": "B0H73CXQ5J",
        "product_name": "Public craft sample",
        "suggested_action": "小预算试投",
        "manual_action_taken": "小预算试投",
        "confirmed_at": "2026-06-18 09:30:00",
        "experiment_type": "growth_test",
        "term_source": "search_term_report",
        "evidence_level": "强意图长尾",
        "suggested_daily_budget": "£1.50/天",
        "suggested_bid_min": "£0.30",
        "suggested_bid_max": "£0.38",
        "test_days": "7",
        "stop_loss_rule": "7天点击达到 12 次仍无本 SKU 订单则停。",
        "success_rule": "7天内至少出现本 SKU 订单。",
    }

    feedbacks, appended_flags, row_count = server.append_ad_completion_feedback_batch(
        {
            "actions": [
                {**base, "search_term_or_target": "adjustable desk lamp"},
                {**base, "search_term_or_target": "dimmer desk lamp with dimmer switch"},
            ]
        }
    )

    assert appended_flags == [True, True]
    assert row_count == 2
    assert [row["normalized_action"] for row in feedbacks] == ["growth_test", "growth_test"]
    saved_payload = json.loads((server.OUTPUT_DIR / "autoopt_feedback_input.json").read_text(encoding="utf-8"))
    assert len(saved_payload["rows"]) == 2
    assert {row["search_term_or_target"] for row in saved_payload["rows"]} == {
        "adjustable desk lamp",
        "dimmer desk lamp with dimmer switch",
    }

    payload = autoopt_feedback.build_autoopt_payload(
        [
            {
                "has_data": True,
                "marketplace": "UK",
                "summary": {"report_date": "2026-06-17"},
                "analysis_payload": {"target_marketplace": "UK"},
                "report_view": {"search_term_processing_queue_rows": []},
            }
        ],
        output_dir=server.OUTPUT_DIR,
    )
    autoopt_feedback.write_autoopt_outputs(server.OUTPUT_DIR, "2026-06-17", payload)

    review_rows = json.loads((server.OUTPUT_DIR / "keyword_action_review_20260617.json").read_text(encoding="utf-8"))
    reviewed_terms = {row.get("search_term_or_target") for row in review_rows if row.get("normalized_action") == "growth_test"}
    assert {"adjustable desk lamp", "dimmer desk lamp with dimmer switch"} <= reviewed_terms
    memory_terms = {
        row.get("search_term_or_target")
        for row in payload.get("keyword_strategy_memory", [])
        if row.get("normalized_action") == "growth_test"
    }
    assert {"adjustable desk lamp", "dimmer desk lamp with dimmer switch"} <= memory_terms


def test_cancel_growth_test_batch_completion_removes_self_optimization_rows(monkeypatch, tmp_path) -> None:
    import src.autoopt_feedback as autoopt_feedback

    _patch_paths(monkeypatch, tmp_path)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"report_date": "2026-06-17"}, ensure_ascii=False),
        encoding="utf-8",
    )

    base = {
        "marketplace": "UK",
        "sku": "SKU-PUBLIC-UK-GROWTH-01",
        "asin": "B0H73CXQ5J",
        "product_name": "Public craft sample",
        "suggested_action": "小预算试投",
        "manual_action_taken": "小预算试投",
        "confirmed_at": "2026-06-18 09:30:00",
        "experiment_type": "growth_test",
        "term_source": "search_term_report",
        "evidence_level": "强意图长尾",
        "suggested_daily_budget": "£1.50/天",
        "suggested_bid_min": "£0.30",
        "suggested_bid_max": "£0.38",
    }
    actions = [
        {**base, "search_term_or_target": "adjustable desk lamp"},
        {**base, "search_term_or_target": "dimmer desk lamp with dimmer switch"},
    ]
    feedbacks, appended_flags, row_count = server.append_ad_completion_feedback_batch({"actions": actions})

    assert appended_flags == [True, True]
    assert row_count == 2

    removed_rows, removed_count, remaining_count = server.cancel_ad_completion_feedback_batch({"actions": feedbacks})

    assert removed_count == 2
    assert remaining_count == 0
    assert {row["search_term_or_target"] for row in removed_rows} == {
        "adjustable desk lamp",
        "dimmer desk lamp with dimmer switch",
    }
    saved_payload = json.loads((server.OUTPUT_DIR / "autoopt_feedback_input.json").read_text(encoding="utf-8"))
    assert saved_payload["rows"] == []
    audit_rows = []
    for audit_path in server.OUTPUT_DIR.glob("feedback_audit_log_*.json"):
        audit_rows.extend(json.loads(audit_path.read_text(encoding="utf-8")))
    assert sum(1 for row in audit_rows if row.get("event") == "complete_action") == 2
    assert sum(1 for row in audit_rows if row.get("event") == "cancel_completed_action") == 2
    assert all(
        row.get("previous_status") == "已执行" and row.get("new_status") == "待确认"
        for row in audit_rows
        if row.get("event") == "cancel_completed_action"
    )

    payload = autoopt_feedback.build_autoopt_payload(
        [
            {
                "has_data": True,
                "marketplace": "UK",
                "summary": {"report_date": "2026-06-17"},
                "analysis_payload": {"target_marketplace": "UK"},
                "report_view": {"search_term_processing_queue_rows": []},
            }
        ],
        output_dir=server.OUTPUT_DIR,
    )
    autoopt_feedback.write_autoopt_outputs(server.OUTPUT_DIR, "2026-06-17", payload)

    review_rows = json.loads((server.OUTPUT_DIR / "keyword_action_review_20260617.json").read_text(encoding="utf-8"))
    assert all(row.get("normalized_action") != "growth_test" for row in review_rows)
    assert all(row.get("normalized_action") != "growth_test" for row in payload.get("keyword_strategy_memory", []))


def test_single_frontend_check_uses_urllib_cache_path(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    calls: list[list[str]] = []
    sellersprite_calls: list[dict[str, object]] = []
    events: list[str] = []

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        events.append("frontend" if "scripts/run_frontend_checks.py" in command else "report")
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(
        server,
        "_start_sellersprite_reverse_async",
        lambda **kwargs: events.append("sellersprite") or sellersprite_calls.append(kwargs) or {},
    )
    server._lock.acquire(blocking=False)

    server._run_frontend_check_one({"marketplace": "UK", "sku": "SKU-1", "asin": "B0TEST1234"})

    assert calls[0][:4] == [server.sys.executable, "scripts/run_frontend_checks.py", "--method", "urllib"]
    assert "--with-sellersprite-reverse-asin" not in calls[0]
    assert "--sellersprite-target-count" not in calls[0]
    assert "--reuse-browser-session" not in calls[0]
    assert "chrome-persistent" not in calls[0]
    assert sellersprite_calls == [{"params": {"marketplace": "UK", "sku": "SKU-1", "asin": "B0TEST1234"}}]
    assert events[:2] == ["sellersprite", "frontend"]


def test_battle_diagnosis_uses_urllib_cache_path(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    calls: list[list[str]] = []
    sellersprite_calls: list[dict[str, str]] = []
    events: list[str] = []

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        events.append("frontend" if "scripts/run_frontend_checks.py" in command else "report")
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(
        server,
        "_start_sellersprite_reverse_async",
        lambda **kwargs: events.append("sellersprite") or sellersprite_calls.append(kwargs) or {},
    )
    server._lock.acquire(blocking=False)

    server._run_battle_diagnosis_one({"marketplace": "UK", "sku": "SKU-1", "asin": "B0TEST1234"})

    assert calls[0][:4] == [server.sys.executable, "scripts/run_frontend_checks.py", "--method", "urllib"]
    assert "--with-sellersprite-reverse-asin" not in calls[0]
    assert "--sellersprite-target-count" not in calls[0]
    assert "--reuse-browser-session" not in calls[0]
    assert "chrome-persistent" not in calls[0]
    assert sellersprite_calls == [{"params": {"marketplace": "UK", "sku": "SKU-1", "asin": "B0TEST1234"}}]
    assert events[:2] == ["sellersprite", "frontend"]


def test_sellersprite_progress_parser_reads_start_and_finish_lines() -> None:
    start = server._sellersprite_progress_from_line("[sellersprite] 3/7 UK B0FAKELOG1 开始反查")
    assert start["event"] == "start"
    assert start["step"] == 3
    assert start["total_steps"] == 7
    assert start["current_label"] == "UK B0FAKELOG1"
    assert "3/7 UK B0FAKELOG1" in str(start["message"])

    finish = server._sellersprite_progress_from_line(
        "[sellersprite] UK B0FAKELOG1 已抓取 captured=20 total=43 error="
    )
    assert finish["event"] == "finish"
    assert finish["record_status"] == "已抓取"
    assert finish["captured_count"] == 20
    assert finish["reported_total"] == "43"


def test_chrome_cdp_launch_uses_background_offscreen_window(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    fake_chrome = tmp_path / "Google Chrome"
    fake_chrome.write_text("", encoding="utf-8")
    calls: list[list[str]] = []
    availability = iter([False, True])

    class DummyProcess:
        pass

    def fake_available(endpoint: str = server.CHROME_CDP_ENDPOINT) -> bool:
        try:
            return next(availability)
        except StopIteration:
            return True

    def fake_popen(command: list[str], **kwargs) -> DummyProcess:
        calls.append(command)
        return DummyProcess()

    monkeypatch.setattr(server, "MAC_CHROME_APP", str(fake_chrome))
    monkeypatch.setattr(server, "_chrome_cdp_available", fake_available)
    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    assert server._start_chrome_cdp_if_needed(wait_seconds=1) is True

    assert len(calls) == 1
    command = calls[0]
    assert command[:5] == ["/usr/bin/open", "-g", "-na", "Google Chrome", "--args"]
    assert "--remote-debugging-port=9222" in command
    assert any(part.startswith("--user-data-dir=") and "chrome_cdp_profile" in part for part in command)
    assert "--window-position=-32000,-32000" in command
    assert "--window-size=1280,900" in command


def test_sellersprite_reverse_command_uses_headed_offscreen_browser() -> None:
    command = server._sellersprite_reverse_command(priority="P0")

    assert command[:2] == [server.sys.executable, "scripts/sellersprite_reverse_asin_fetch.py"]
    assert "--target-count" in command
    assert command[command.index("--target-count") + 1] == "20"
    assert "--priority" in command
    assert command[command.index("--priority") + 1] == "P0"
    assert "--headless" not in command


def test_chrome_cdp_launch_failure_returns_false_and_logs_reason(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    fake_chrome = tmp_path / "Google Chrome"
    fake_chrome.write_text("", encoding="utf-8")

    def fake_popen(*args, **kwargs):
        raise OSError("macOS denied open")

    monkeypatch.setattr(server, "MAC_CHROME_APP", str(fake_chrome))
    monkeypatch.setattr(server, "_chrome_cdp_available", lambda endpoint=server.CHROME_CDP_ENDPOINT: False)
    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    assert server._start_chrome_cdp_if_needed(wait_seconds=1) is False

    log_text = (server.OUTPUT_DIR / "chrome_cdp_launch.log").read_text(encoding="utf-8")
    assert "cannot start Chrome CDP: macOS denied open" in log_text


def test_frontend_retry_uses_background_chrome_cdp_refresh_by_default(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    calls: list[list[str]] = []
    sellersprite_calls: list[dict[str, str]] = []
    events: list[str] = []
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "UK",
                                    "asin": "B0PASS0001",
                                    "frontend_check_status": "待前台检查",
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        events.append("report")
        calls.append(command)
        if command[:3] == [server.sys.executable, "main.py", "--marketplace"]:
            (server.OUTPUT_DIR / "latest_analysis.json").write_text(
                json.dumps(
                    {
                        "marketplace_results": [
                            {
                                "report_view_snapshot": {
                                    "frontend_check_queue_rows": [
                                        {
                                            "marketplace": "UK",
                                            "asin": "B0PASS0001",
                                            "frontend_check_status": "已自动检查",
                                            "frontend_check_method": "chrome-cdp",
                                            "frontend_data_date": "2026-06-17",
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    def fake_frontend_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        progress_writer=None,
    ) -> subprocess.CompletedProcess[str]:
        events.append("frontend")
        calls.append(command)
        (server.OUTPUT_DIR / "frontend_check_results.json").write_text(
            json.dumps(
                {
                    "refresh_summary": {
                        "frontend_refresh_total": 1,
                        "frontend_refresh_live_checked": 1,
                        "frontend_refresh_skipped": 0,
                        "frontend_refresh_cache_used": 0,
                        "frontend_refresh_failed": 0,
                    },
                    "items": [],
                    "cache": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="[frontend] checked 1 queued products; live=1 skipped=0 cache=0 failed=0", stderr="")

    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(server, "_chrome_cdp_available", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()
    payload = server._status_payload()

    assert len(calls) == 2
    frontend_command = calls[0]
    assert frontend_command[:4] == [server.sys.executable, "scripts/run_frontend_checks.py", "--method", "chrome-cdp"]
    assert "--cdp-attempts" in frontend_command
    assert frontend_command[frontend_command.index("--cdp-attempts") + 1] == "1"
    assert "--cdp-endpoint" in frontend_command
    assert "--retries" not in frontend_command
    assert "--search-policy" in frontend_command
    assert "always" in frontend_command
    assert frontend_command[frontend_command.index("--timeout") + 1] == "18"
    assert frontend_command[frontend_command.index("--sleep") + 1] == "0.5"
    assert "--only-stale" not in frontend_command
    assert "--limit" in frontend_command
    assert frontend_command[frontend_command.index("--limit") + 1] == "3"
    assert "--with-sellersprite-reverse-asin" not in frontend_command
    assert "--sellersprite-target-count" not in frontend_command
    assert "--strict-live-pass" not in frontend_command
    assert events[:2] == ["frontend", "report"]
    assert payload["returncode"] == 0
    assert payload["status_scope"] == "frontend_retry"
    assert payload["failure_mode"] == "chrome_cdp_frontend_check_passed"
    assert "本轮队列 1/1" in str(payload["message"])
    assert "新读 1" in str(payload["message"])
    assert "失败 0" in str(payload["message"])


def test_frontend_retry_skips_sellersprite_when_no_missing(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    calls: list[list[str]] = []
    events: list[str] = []

    monkeypatch.setattr(
        server,
        "_frontend_refresh_needed_summary",
        lambda: {
            "frontend_queue_total": 1,
            "frontend_refresh_needed_count": 1,
            "frontend_cached_count": 0,
        },
    )
    monkeypatch.setattr(
        server,
        "_sellersprite_reverse_needed_summary",
        lambda priority="": {
            "sellersprite_queue_total": 2,
            "sellersprite_cached_count": 2,
            "sellersprite_missing_count": 0,
        },
    )

    def fake_frontend_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        progress_writer=None,
    ) -> subprocess.CompletedProcess[str]:
        events.append("frontend")
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="[frontend] checked 1 queued products; live=1", stderr="")

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        events.append("report")
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="report ok", stderr="")

    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(
        server,
        "_run_sellersprite_command_with_progress",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("seller sprite should not run without missing ASIN")),
    )
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()

    assert events == ["frontend", "report"]


def test_frontend_retry_runs_missing_sellersprite_before_report_refresh(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    calls: list[list[str]] = []
    events: list[str] = []
    seller_summary_calls = {"count": 0}

    monkeypatch.setattr(
        server,
        "_frontend_refresh_needed_summary",
        lambda: {
            "frontend_queue_total": 1,
            "frontend_refresh_needed_count": 1,
            "frontend_cached_count": 0,
        },
    )

    def fake_seller_summary(priority: str = "") -> dict[str, object]:
        seller_summary_calls["count"] += 1
        if seller_summary_calls["count"] == 1:
            return {
                "sellersprite_queue_total": 3,
                "sellersprite_cached_count": 1,
                "sellersprite_missing_count": 2,
                "sellersprite_missing_labels": ["US B0OWN0001", "US B0COMP0001"],
            }
        return {
            "sellersprite_queue_total": 3,
            "sellersprite_cached_count": 3,
            "sellersprite_missing_count": 0,
            "sellersprite_missing_labels": [],
        }

    monkeypatch.setattr(server, "_sellersprite_reverse_needed_summary", fake_seller_summary)
    monkeypatch.setattr(server, "_sellersprite_reverse_command", lambda **kwargs: [server.sys.executable, "scripts/sellersprite_reverse_asin_fetch.py"])

    def fake_frontend_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        progress_writer=None,
    ) -> subprocess.CompletedProcess[str]:
        events.append("frontend")
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="[frontend] checked 1 queued products; live=1", stderr="")

    def fake_sellersprite_command(command: list[str], timeout: int, label: str) -> subprocess.CompletedProcess[str]:
        events.append("sellersprite")
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="[sellersprite] wrote cache; success=2/2", stderr="")

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        events.append("report")
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="report ok", stderr="")

    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(server, "_run_sellersprite_command_with_progress", fake_sellersprite_command)
    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()

    assert events == ["frontend", "sellersprite", "report"]
    assert calls[1] == [server.sys.executable, "scripts/sellersprite_reverse_asin_fetch.py"]
    assert server._sellersprite_async_status["running"] is False
    assert server._sellersprite_async_status["sellersprite_missing_count"] == 0


def test_frontend_retry_limit_expands_to_current_gap(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "marketplace": "US",
            "sku": f"SKU-{index}",
            "asin": f"B0GAP{index:05d}",
            "frontend_check_status": "待前台检查",
        }
        for index in range(7)
    ]
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {"marketplace_results": [{"report_view_snapshot": {"frontend_check_queue_rows": rows}}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps({"items": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_frontend_command(command, timeout, *, step, total_steps, progress_writer=None):
        calls.append(command)
        (server.OUTPUT_DIR / "frontend_check_results.json").write_text(
            json.dumps(
                {
                    "refresh_summary": {
                        "frontend_refresh_total": 7,
                        "frontend_refresh_live_checked": 7,
                        "frontend_refresh_skipped": 0,
                        "frontend_refresh_cache_used": 0,
                        "frontend_refresh_failed": 0,
                    },
                    "items": [],
                    "cache": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    def fake_run_command(command, timeout):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="report ok", stderr="")

    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(server, "_start_sellersprite_reverse_async", lambda **kwargs: {})
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()

    frontend_command = calls[0]
    assert "--limit" in frontend_command
    assert frontend_command[frontend_command.index("--limit") + 1] == "7"


def test_daily_update_success_starts_p0_frontend_async_without_blocking_status(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        message: str,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert step == 1
        assert total_steps == 1
        assert message == "运行 daily update"
        return subprocess.CompletedProcess(command, 0, stdout="daily ok", stderr="")

    monkeypatch.setattr(server, "_run_command_with_status", fake_run_command)
    def fake_start_p0_frontend_async() -> dict[str, object]:
        payload = {
            "running": True,
            "message": "P0 前台后台检查已启动，日报已完成；该检查不会阻塞报告使用。",
            "status_scope": "frontend_async",
        }
        server._sync_frontend_async_status(payload)
        return payload

    monkeypatch.setattr(server, "_start_p0_frontend_async_if_needed", fake_start_p0_frontend_async)
    server._lock.acquire(blocking=False)

    server._run_daily_update()
    payload = server._status_payload()

    assert calls == [[server.sys.executable, "scripts/run_daily_update.py"]]
    assert payload["running"] is False
    assert payload["message"] == "daily update 完成，报告已刷新。"
    assert payload["returncode"] == 0
    assert payload["frontend_async_status"]["running"] is True
    assert payload["frontend_async_status"]["status_scope"] == "frontend_async"
    assert "P0 前台后台检查已启动" in str(payload["frontend_async_status"]["message"])


def test_daily_update_popen_failure_persists_failed_status(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    def raise_popen_error(*args, **kwargs):
        raise OSError("spawn denied")

    monkeypatch.setattr(server.subprocess, "Popen", raise_popen_error)
    monkeypatch.setattr(
        server,
        "_start_p0_frontend_async_if_needed",
        lambda: (_ for _ in ()).throw(AssertionError("frontend async must not start after daily failure")),
    )
    server._lock.acquire(blocking=False)

    server._run_daily_update()
    payload = server._status_payload()

    assert payload["running"] is False
    assert payload["message"] == "daily update 失败，请查看输出摘要。"
    assert payload["returncode"] == 127
    assert "cannot start command: spawn denied" in payload["stderr_tail"]


def test_p0_frontend_async_refreshes_only_p0_queue(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    calls: list[list[str]] = []
    sellersprite_calls: list[dict[str, str]] = []
    events: list[str] = []
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "priority": "P0",
                                    "marketplace": "UK",
                                    "sku": "SKU-P0",
                                    "asin": "B0P0TEST01",
                                    "frontend_check_status": "待前台检查",
                                },
                                {
                                    "priority": "P1",
                                    "marketplace": "US",
                                    "sku": "SKU-P1",
                                    "asin": "B0P1TEST01",
                                    "frontend_check_status": "待前台检查",
                                },
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_frontend_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        progress_writer=None,
    ) -> subprocess.CompletedProcess[str]:
        events.append("frontend")
        calls.append(command)
        (server.OUTPUT_DIR / "frontend_check_results.json").write_text(
            json.dumps(
                {
                    "refresh_summary": {
                        "frontend_refresh_total": 1,
                        "frontend_refresh_live_checked": 1,
                        "frontend_refresh_skipped": 0,
                        "frontend_refresh_cache_used": 0,
                        "frontend_refresh_failed": 0,
                    },
                    "items": [],
                    "cache": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="p0 ok", stderr="")

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        events.append("report")
        calls.append(command)
        if command[:3] == [server.sys.executable, "main.py", "--marketplace"]:
            (server.OUTPUT_DIR / "latest_analysis.json").write_text(
                json.dumps(
                    {
                        "marketplace_results": [
                            {
                                "report_view_snapshot": {
                                    "frontend_check_queue_rows": [
                                        {
                                            "priority": "P0",
                                            "marketplace": "UK",
                                            "sku": "SKU-P0",
                                            "asin": "B0P0TEST01",
                                            "frontend_check_status": "已自动检查",
                                            "frontend_check_method": "chrome-cdp",
                                            "frontend_data_date": "2026-06-17",
                                        },
                                        {
                                            "priority": "P1",
                                            "marketplace": "US",
                                            "sku": "SKU-P1",
                                            "asin": "B0P1TEST01",
                                            "frontend_check_status": "待前台检查",
                                        },
                                    ]
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0, stdout="report ok", stderr="")

    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(
        server,
        "_start_sellersprite_reverse_async",
        lambda **kwargs: events.append("sellersprite") or sellersprite_calls.append(kwargs) or {},
    )
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._frontend_async_lock.acquire(blocking=False)

    server._run_p0_frontend_async()
    payload = server._status_payload()

    assert len(calls) == 2
    frontend_command = calls[0]
    assert frontend_command[:4] == [server.sys.executable, "scripts/run_frontend_checks.py", "--method", "chrome-cdp"]
    assert "--priority" in frontend_command
    assert frontend_command[frontend_command.index("--priority") + 1] == "P0"
    assert "--only-stale" in frontend_command
    assert "--require-competitor-samples" in frontend_command
    assert "--search-policy" in frontend_command
    assert frontend_command[frontend_command.index("--search-policy") + 1] == "always"
    assert frontend_command[frontend_command.index("--timeout") + 1] == "18"
    assert frontend_command[frontend_command.index("--sleep") + 1] == "0.5"
    assert "--limit" in frontend_command
    assert frontend_command[frontend_command.index("--limit") + 1] == "3"
    assert "--with-sellersprite-reverse-asin" not in frontend_command
    assert "--sellersprite-target-count" not in frontend_command
    assert calls[1][:3] == [server.sys.executable, "main.py", "--marketplace"]
    assert payload["running"] is False
    assert payload["frontend_async_status"]["running"] is False
    assert payload["frontend_async_status"]["status_scope"] == "frontend_async"
    assert payload["frontend_async_status"]["frontend_queue_total"] == 1
    assert payload["frontend_async_status"]["frontend_live_passed_count"] == 1
    assert "B0P1TEST01" not in "".join(payload["frontend_async_status"].get("frontend_live_passed_labels", []))
    assert sellersprite_calls == [{"priority": "P0"}]
    assert events[:2] == ["sellersprite", "frontend"]


def test_p0_frontend_async_reports_failure_when_final_report_refresh_cannot_start(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "priority": "P0",
                                    "marketplace": "UK",
                                    "sku": "SKU-P0",
                                    "asin": "B0P0TEST01",
                                    "frontend_check_status": "待前台检查",
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_frontend_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        progress_writer=None,
    ) -> subprocess.CompletedProcess[str]:
        (server.OUTPUT_DIR / "frontend_check_results.json").write_text(
            json.dumps(
                {
                    "refresh_summary": {
                        "frontend_refresh_total": 1,
                        "frontend_refresh_live_checked": 1,
                        "frontend_refresh_skipped": 0,
                        "frontend_refresh_cache_used": 0,
                        "frontend_refresh_failed": 0,
                    },
                    "items": [],
                    "cache": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="p0 ok", stderr="")

    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(
        server,
        "_run_command",
        lambda command, timeout: subprocess.CompletedProcess(command, 127, "", "cannot start command: spawn denied"),
    )
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._frontend_async_lock.acquire(blocking=False)

    server._run_p0_frontend_async()
    payload = server._status_payload()
    async_status = payload["frontend_async_status"]

    assert async_status["running"] is False
    assert async_status["returncode"] == 127
    assert "cannot start command: spawn denied" in async_status["stderr_tail"]
    assert async_status["status_scope"] == "frontend_async"


def test_p0_frontend_async_refreshes_today_product_page_without_competitor_samples(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    calls: list[list[str]] = []
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "priority": "P0",
                                    "marketplace": "US",
                                    "sku": "SKU-P0",
                                    "asin": "B0P0TEST01",
                                    "frontend_check_status": "已自动检查",
                                    "frontend_check_method": "chrome-cdp",
                                    "frontend_data_date": "2026-06-17",
                                    "frontend_competitor_count": 0,
                                    "frontend_competitors": [],
                                }
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_frontend_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        progress_writer=None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        (server.OUTPUT_DIR / "frontend_check_results.json").write_text(
            json.dumps(
                {
                    "refresh_summary": {
                        "frontend_refresh_total": 1,
                        "frontend_refresh_live_checked": 1,
                        "frontend_refresh_skipped": 0,
                        "frontend_refresh_cache_used": 0,
                        "frontend_refresh_failed": 0,
                    },
                    "items": [],
                    "cache": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="p0 ok", stderr="")

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == [server.sys.executable, "main.py", "--marketplace"]:
            (server.OUTPUT_DIR / "latest_analysis.json").write_text(
                json.dumps(
                    {
                        "marketplace_results": [
                            {
                                "report_view_snapshot": {
                                    "frontend_check_queue_rows": [
                                        {
                                            "priority": "P0",
                                            "marketplace": "US",
                                            "sku": "SKU-P0",
                                            "asin": "B0P0TEST01",
                                            "frontend_check_status": "已自动检查",
                                            "frontend_check_method": "chrome-cdp",
                                            "frontend_data_date": "2026-06-17",
                                            "frontend_competitor_count": 2,
                                            "frontend_competitors": [{"asin": "B0COMP1111"}, {"asin": "B0COMP2222"}],
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0, stdout="report ok", stderr="")

    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._frontend_async_lock.acquire(blocking=False)

    server._run_p0_frontend_async()

    assert len(calls) == 2
    assert calls[0][calls[0].index("--search-policy") + 1] == "always"
    assert "--require-competitor-samples" in calls[0]


def test_frontend_retry_forces_all_today_chrome_cdp_rows(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    calls: list[list[str]] = []
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {
                        "report_view_snapshot": {
                            "frontend_check_queue_rows": [
                                {
                                    "marketplace": "UK",
                                    "asin": f"B0PASS000{index}",
                                    "frontend_check_status": "已自动检查",
                                    "frontend_check_method": "chrome-cdp",
                                    "frontend_data_date": "2026-06-17",
                                }
                                for index in range(8)
                            ]
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (server.OUTPUT_DIR / "sellersprite_reverse_asin_results.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "marketplace": "UK",
                        "asin": f"B0PASS000{index}",
                        "seller_sprite_check_status": "已抓取",
                        "data_date": "2026-06-17",
                        "keywords": [{"keyword": "cached keyword"}],
                    }
                    for index in range(8)
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(
        server,
        "_run_frontend_command_with_progress",
        lambda command, timeout, *, step, total_steps, progress_writer=None: fake_run_command(command, timeout),
    )
    monkeypatch.setattr(server, "_start_sellersprite_reverse_async", lambda **kwargs: {})
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()
    payload = server._status_payload()

    assert len(calls) == 2
    assert calls[0][:4] == [server.sys.executable, "scripts/run_frontend_checks.py", "--method", "chrome-cdp"]
    assert "--only-stale" not in calls[0]
    assert "--limit" in calls[0]
    assert calls[0][calls[0].index("--limit") + 1] == "7"
    assert calls[1][:3] == [server.sys.executable, "main.py", "--marketplace"]
    assert payload["returncode"] == 0
    assert payload["failure_mode"] == "chrome_cdp_frontend_check_passed"
    assert "调查完成" in str(payload["message"])
    assert "本轮队列 8/8" in str(payload["message"])
    assert "无需刷新" not in str(payload["message"])


def test_frontend_retry_can_use_urllib_when_browser_frontend_disabled(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setenv(server.ENABLE_BROWSER_FRONTEND_ENV, "0")
    calls: list[list[str]] = []

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(
        server,
        "_run_frontend_command_with_progress",
        lambda command, timeout, *, step, total_steps, progress_writer=None: fake_run_command(command, timeout),
    )
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: False)
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps(
            {
                "marketplace_results": [
                    {"report_view_snapshot": {"frontend_check_queue_rows": [{"marketplace": "UK", "asin": "B0WAIT0001", "frontend_check_status": "待前台检查"}]}}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()
    payload = server._status_payload()

    assert len(calls) == 2
    assert calls[0][:4] == [server.sys.executable, "scripts/run_frontend_checks.py", "--method", "urllib"]
    assert payload["returncode"] == 0
    assert payload["status_scope"] == "frontend_retry"
    assert payload["failure_mode"] == "chrome_cdp_frontend_check_partial"


def test_frontend_retry_runs_sellersprite_even_when_chrome_cdp_unavailable(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    events: list[str] = []
    seller_summary_calls = {"count": 0}

    monkeypatch.setattr(
        server,
        "_frontend_refresh_needed_summary",
        lambda: {
            "frontend_queue_total": 1,
            "frontend_refresh_needed_count": 1,
            "frontend_cached_count": 0,
        },
    )

    def fake_seller_summary(priority: str = "") -> dict[str, object]:
        seller_summary_calls["count"] += 1
        if seller_summary_calls["count"] == 1:
            return {
                "sellersprite_queue_total": 2,
                "sellersprite_cached_count": 0,
                "sellersprite_missing_count": 2,
            }
        return {
            "sellersprite_queue_total": 2,
            "sellersprite_cached_count": 2,
            "sellersprite_missing_count": 0,
        }

    monkeypatch.setattr(server, "_sellersprite_reverse_needed_summary", fake_seller_summary)
    monkeypatch.setattr(server, "_sellersprite_reverse_command", lambda **kwargs: [server.sys.executable, "scripts/sellersprite_reverse_asin_fetch.py"])
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: False)
    monkeypatch.setattr(
        server,
        "_run_frontend_command_with_progress",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("frontend command should be skipped when Chrome CDP is unavailable")),
    )

    def fake_sellersprite_command(command: list[str], timeout: int, label: str) -> subprocess.CompletedProcess[str]:
        events.append("sellersprite")
        return subprocess.CompletedProcess(command, 0, stdout="seller ok", stderr="")

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        events.append("report")
        return subprocess.CompletedProcess(command, 0, stdout="report ok", stderr="")

    monkeypatch.setattr(server, "_run_sellersprite_command_with_progress", fake_sellersprite_command)
    monkeypatch.setattr(server, "_run_command", fake_run_command)
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()
    payload = server._status_payload()

    assert events == ["sellersprite", "report"]
    assert payload["failure_mode"] == "chrome_cdp_unavailable"
    assert payload["soft_failure"] is True
    assert server._sellersprite_async_status["sellersprite_missing_count"] == 0


def test_frontend_retry_refreshes_reports_after_partial_live_failure(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.delenv(server.ENABLE_BROWSER_FRONTEND_ENV, raising=False)
    monkeypatch.setattr(server, "_today_iso", lambda: "2026-06-17")
    calls: list[list[str]] = []
    rows = [
        {
            "marketplace": "UK",
            "asin": f"B0PASS000{index}",
            "frontend_check_status": "已自动检查",
            "frontend_check_method": "chrome-cdp",
            "frontend_stability_passed": True,
            "frontend_stability_total_attempts": 20,
            "frontend_stability_success_rate": 0.8,
            "frontend_data_date": "2026-06-17",
        }
        for index in range(4)
    ]
    rows.append({"marketplace": "DE", "asin": "B0WAIT0001", "frontend_check_status": "待前台检查"})
    server.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (server.OUTPUT_DIR / "latest_analysis.json").write_text(
        json.dumps({"marketplace_results": [{"report_view_snapshot": {"frontend_check_queue_rows": rows}}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    def fake_run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    def fake_frontend_command(
        command: list[str],
        timeout: int,
        *,
        step: int,
        total_steps: int,
        progress_writer=None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        (server.OUTPUT_DIR / "frontend_check_results.json").write_text(
            json.dumps(
                {
                    "refresh_summary": {
                        "frontend_refresh_total": 5,
                        "frontend_refresh_live_checked": 0,
                        "frontend_refresh_skipped": 4,
                        "frontend_refresh_cache_used": 0,
                        "frontend_refresh_failed": 1,
                    },
                    "items": [],
                    "cache": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, stdout="[frontend] wrote results\nfailed", stderr="")

    monkeypatch.setattr(server, "_run_command", fake_run_command)
    monkeypatch.setattr(server, "_run_frontend_command_with_progress", fake_frontend_command)
    monkeypatch.setattr(server, "_start_chrome_cdp_if_needed", lambda endpoint=server.CHROME_CDP_ENDPOINT: True)
    server._lock.acquire(blocking=False)

    server._run_frontend_retry()
    payload = server._status_payload()

    assert len(calls) == 2
    assert calls[0][:4] == [server.sys.executable, "scripts/run_frontend_checks.py", "--method", "chrome-cdp"]
    assert "--only-stale" not in calls[0]
    assert calls[1][:3] == [server.sys.executable, "main.py", "--marketplace"]
    assert payload["returncode"] == 1
    assert payload["status_scope"] == "frontend_retry"
    assert payload["failure_mode"] == "chrome_cdp_frontend_check_passed_with_pending"
    assert payload["soft_failure"] is True
    assert "本轮队列 4/5" in str(payload["message"])
    assert "新读 0" in str(payload["message"])
    assert "失败 1" in str(payload["message"])
    assert "调查完成" in str(payload["message"])
    assert "待补：DE B0WAIT0001" in str(payload["message"])


def test_config_upload_requires_expected_filename(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    safe_name, error = server._validate_config_upload_name("cost", "wrong.xlsx", 100)

    assert safe_name == "wrong.xlsx"
    assert "product_cost_config.xlsx" in error


def test_save_cost_config_upload_to_review_area(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    payload = _xlsx_bytes(
        "product_cost_config",
        ["marketplace", "sku", "asin", "product_name", "currency"],
        ["US", "SKU-1", "B0TEST0001", "Test product", "USD"],
    )
    form = FakeForm({"file": FakeUploadField("product_cost_config.xlsx", payload)})

    saved, errors = server._save_config_upload(form, "cost")

    assert errors == []
    assert saved["path"] == "data/config_review/product_cost_config.pending.xlsx"
    assert (tmp_path / "repo" / saved["path"]).exists()


def test_save_config_upload_rejects_missing_required_columns(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    payload = _xlsx_bytes("product_cost_config", ["marketplace", "sku"], ["US", "SKU-1"])
    form = FakeForm({"file": FakeUploadField("product_cost_config.xlsx", payload)})

    saved, errors = server._save_config_upload(form, "cost")

    assert saved == {}
    assert errors and "缺少列" in errors[0]
    assert not (tmp_path / "repo" / "data" / "config_review" / "product_cost_config.pending.xlsx").exists()


def test_apply_pending_alias_config_archives_and_replaces(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    config_dir = root / "config"
    review_dir = root / "data" / "config_review"
    config_dir.mkdir(parents=True)
    review_dir.mkdir(parents=True)
    current = _xlsx_bytes(
        "Sheet1",
        ["marketplace", "source_sku", "canonical_sku", "asin", "reason"],
        ["US", "OLD", "SKU-OLD", "B0OLD00001", "old"],
    )
    pending = _xlsx_bytes(
        "Sheet1",
        ["marketplace", "source_sku", "canonical_sku", "asin", "reason"],
        ["US", "NEW", "SKU-NEW", "B0NEW00001", "new"],
    )
    (config_dir / "sku_alias_map.xlsx").write_bytes(current)
    (review_dir / "sku_alias_map.pending.xlsx").write_bytes(pending)

    applied, completed = server._apply_pending_config("alias")

    assert completed is None
    assert applied["target_path"] == "config/sku_alias_map.xlsx"
    assert applied["archive_path"].startswith("data/archive/config_updates/sku_alias_map_alias_")
    assert not (review_dir / "sku_alias_map.pending.xlsx").exists()
    assert server._workbook_headers(config_dir / "sku_alias_map.xlsx", "Sheet1") >= {"marketplace", "source_sku"}
