from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

import scripts.audit_unknown_inbox as audit
from scripts.import_inbox_files import ManifestRow


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    inbox = root / "data" / "inbox"
    unknown = inbox / "_unknown"
    output = root / "data" / "output"
    unknown.mkdir(parents=True)
    output.mkdir(parents=True)
    monkeypatch.setattr(audit, "INBOX", inbox)
    monkeypatch.setattr(audit, "UNKNOWN_DIR", unknown)
    monkeypatch.setattr(audit, "OUTPUT", output)
    monkeypatch.setattr(audit, "JSON_OUTPUT", output / "unknown_inbox_audit.json")
    monkeypatch.setattr(audit, "MARKDOWN_OUTPUT", output / "unknown_inbox_audit.md")
    return unknown


def test_unknown_inbox_audit_writes_outputs_and_can_fail(monkeypatch, tmp_path, capsys) -> None:
    unknown = _patch_paths(monkeypatch, tmp_path)
    target = unknown / "metric.xlsx"
    target.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(audit, "load_asin_marketplace_map", lambda: {})

    def fake_process_file(path, *, dry_run, asin_map, selected_ads, selected_erp):
        assert path == target
        assert dry_run is True
        return (
            ManifestRow(
                original_filename=path.name,
                original_path=str(path),
                detected_type="unknown",
                detected_marketplace="UNKNOWN",
                period_type="unknown",
                detected_date_range="unknown",
                target_path="",
                archive_path="",
                status="unknown",
                reason="无法识别文件类型",
                modified_time="2026-06-09 10:00:00",
                rows=1,
                columns=1,
                asin_count=0,
                created_at="2026-06-09 10:01:00",
            ),
            0,
        )

    monkeypatch.setattr(audit, "process_file", fake_process_file)

    code = audit.main(["--fail-on-blocker"])
    output = capsys.readouterr().out

    assert code == 1
    assert "unknown business files: 1" in output
    assert "unknown inbox business files block daily update" in output
    assert audit.JSON_OUTPUT.exists()
    assert audit.MARKDOWN_OUTPUT.exists()
    assert "metric.xlsx" in audit.MARKDOWN_OUTPUT.read_text(encoding="utf-8")
    assert "无法识别文件类型" in audit.MARKDOWN_OUTPUT.read_text(encoding="utf-8")


def test_unknown_inbox_audit_passes_when_no_business_files(monkeypatch, tmp_path, capsys) -> None:
    unknown = _patch_paths(monkeypatch, tmp_path)
    (unknown / ".DS_Store").write_text("placeholder", encoding="utf-8")

    code = audit.main(["--fail-on-blocker"])
    output = capsys.readouterr().out

    assert code == 0
    assert "unknown business files: 0" in output
    assert "未发现阻断 daily update" in audit.MARKDOWN_OUTPUT.read_text(encoding="utf-8")


def test_unknown_inbox_audit_identifies_promotion_metric_report(monkeypatch, tmp_path) -> None:
    unknown = _patch_paths(monkeypatch, tmp_path)
    target = unknown / "metric-data.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "metric-data"
    worksheet.append(
        [
            "促销类型",
            "促销编号",
            "促销名称",
            "促销开始时间",
            "促销结束时间",
            "促销批准状态",
            "促销浏览次数 (Week 21)",
            "来自已订购商品的促销销售额 (Week 21)(€)",
        ]
    )
    worksheet.append(["Total", "", "", "", "", "", 17, 71.23])
    workbook.save(target)

    monkeypatch.setattr(audit, "load_asin_marketplace_map", lambda: {})

    def fake_process_file(path, *, dry_run, asin_map, selected_ads, selected_erp):
        return (
            ManifestRow(
                original_filename=path.name,
                original_path=str(path),
                detected_type="unknown",
                detected_marketplace="UNKNOWN",
                period_type="unknown",
                detected_date_range="unknown",
                target_path="",
                archive_path="",
                status="unknown",
                reason="无法识别文件类型",
                modified_time="2026-06-09 10:00:00",
                rows=2,
                columns=8,
                asin_count=0,
                created_at="2026-06-09 10:01:00",
            ),
            0,
        )

    monkeypatch.setattr(audit, "process_file", fake_process_file)

    rows = audit.build_audit_rows([target])
    markdown = audit.build_markdown(rows)

    assert rows[0]["likely_report_type"] == "seller_central_promotion_metrics"
    assert rows[0]["likely_marketplace"] == "DE_or_EUR"
    assert "促销表现 metric-data" in rows[0]["business_interpretation"]
    assert "当前不参与 daily import" in rows[0]["recommendation"]
    assert "Seller Central 促销表现" in markdown
