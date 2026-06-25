from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

import scripts.import_inbox_files as importer


def _write_traffic_workbook(path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "metric-data"
    worksheet.append(
        [
            "ASIN",
            "商品名称",
            "转化率",
            "推荐报价浏览量",
            "推荐报价率",
            "已订购商品数量",
            "已发货商品数量",
        ]
    )
    worksheet.append(["B0TEST0001", "Sample", 0.1, 10, 0.9, 1, 1])
    workbook.save(path)


def _write_traffic_workbook_with_rows(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "metric-data"
    worksheet.append(
        [
            "ASIN",
            "商品名称",
            "转化率 (Week 25)(%)",
            "转化率 (Week 24)(%)",
            "推荐报价浏览量 (Week 25)",
            "推荐报价浏览量 (Week 24)",
            "推荐报价率 (Week 25)",
            "推荐报价率 (Week 24)",
            "已订购商品数量 (Week 25)",
            "已订购商品数量 (Week 24)",
            "已发货商品数量 (Week 25)",
            "已发货商品数量 (Week 24)",
        ]
    )
    worksheet.append(["Total", "", 0.1, 0.1, 10, 8, 1, 1, 1, 1, 1, 1])
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def test_same_batch_enhanced_import_keeps_distinct_targets(monkeypatch, tmp_path: Path) -> None:
    raw_custom_us = tmp_path / "raw_amazon_custom" / "US"
    raw_custom_us.mkdir(parents=True)
    monkeypatch.setattr(importer, "RAW_CUSTOM_US", raw_custom_us)

    def fake_header_info(path: Path, marketplace: str) -> dict[str, object]:
        return {
            "data_type": "traffic_sales",
            "marketplace": "US",
            "recent_start": "2026-06-14",
            "recent_end": "2026-06-20",
            "prior_start": "2026-06-07",
            "prior_end": "2026-06-13",
            "detected_from": "header",
            "format_type": "wow",
            "detected_date_range": "2026-06-14 ~ 2026-06-20 vs 2026-06-07 ~ 2026-06-13",
            "freshness": "fresh",
        }

    monkeypatch.setattr(importer, "detect_enhanced_header_info", fake_header_info)
    monkeypatch.setattr(importer, "infer_enhanced_marketplaces_and_asin_count", lambda path, asin_map: ({"US"}, 1))

    first = tmp_path / "1.xlsx"
    second = tmp_path / "2.xlsx"
    _write_traffic_workbook(first)
    _write_traffic_workbook(second)

    reserved_targets: set[Path] = set()
    first_row, _ = importer.process_file(
        first,
        dry_run=True,
        asin_map={},
        selected_ads=None,
        selected_erp=None,
        reserved_targets=reserved_targets,
    )
    second_row, _ = importer.process_file(
        second,
        dry_run=True,
        asin_map={},
        selected_ads=None,
        selected_erp=None,
        reserved_targets=reserved_targets,
    )

    assert first_row.status == "imported"
    assert second_row.status == "imported"
    assert first_row.target_path != second_row.target_path
    assert first_row.target_conflict == ""
    assert second_row.target_conflict.startswith("same_batch_target_conflict:")
    assert second_row.target_path.endswith("__2.xlsx")
    assert first_row.enhanced_detected_from == "header"
    assert first_row.enhanced_freshness == "fresh"
    assert first_row.diagnosis_usage == "pending_report_refresh"


def test_enhanced_marketplace_does_not_trust_amazon_com_link_when_content_is_localized(tmp_path: Path) -> None:
    uk = tmp_path / "uk.xlsx"
    de = tmp_path / "de.xlsx"
    us = tmp_path / "us.xlsx"
    _write_traffic_workbook_with_rows(
        uk,
        [
            [
                '=HYPERLINK("https://amazon.com/dp/B0UKTEST01", "B0UKTEST01")',
                "Heavy Duty Bin Bags 90L for Kitchen Bin and Brabantia Bin Liners",
                0.1,
                0.1,
                10,
                8,
                1,
                1,
                1,
                1,
                1,
                1,
            ]
        ],
    )
    _write_traffic_workbook_with_rows(
        de,
        [
            [
                '=HYPERLINK("https://amazon.com/dp/B0DETEST01", "B0DETEST01")',
                "Teebox Bambus für Teebeutel Küche Holz mit Sichtfenster",
                0.1,
                0.1,
                10,
                8,
                1,
                1,
                1,
                1,
                1,
                1,
            ]
        ],
    )
    _write_traffic_workbook_with_rows(
        us,
        [
            [
                '=HYPERLINK("https://amazon.com/dp/B0USTEST01", "B0USTEST01")',
                "Heavy Duty 23 Gallon Trash Bags for Garbage Can",
                0.1,
                0.1,
                10,
                8,
                1,
                1,
                1,
                1,
                1,
                1,
            ]
        ],
    )

    assert importer.infer_enhanced_marketplaces_and_asin_count(uk, {}) == ({"UK"}, 1)
    assert importer.infer_enhanced_marketplaces_and_asin_count(de, {}) == ({"DE"}, 1)
    assert importer.infer_enhanced_marketplaces_and_asin_count(us, {}) == ({"US"}, 1)
