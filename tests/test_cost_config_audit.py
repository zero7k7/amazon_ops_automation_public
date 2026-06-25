from __future__ import annotations

from openpyxl import Workbook

from scripts.audit_cost_config_changes import _compare_sheet_by_business_key, build_markdown_summary


def _sheet(rows: list[list[object]]):
    workbook = Workbook()
    ws = workbook.active
    for row in rows:
        ws.append(row)
    return workbook, ws


def test_cost_config_audit_compares_rows_by_marketplace_sku_asin() -> None:
    before_wb, before_ws = _sheet(
        [
            ["marketplace", "sku", "asin", "product_name", "selling_price", "target_acos"],
            ["US", "SKU-1", "B0TEST0001", "Test product", 19.99, 0.2],
            ["UK", "SKU-2", "B0TEST0002", "Other product", 15.99, 0.18],
        ]
    )
    after_wb, after_ws = _sheet(
        [
            ["marketplace", "sku", "asin", "product_name", "selling_price", "target_acos"],
            ["UK", "SKU-2", "B0TEST0002", "Other product", 15.99, 0.18],
            ["US", "SKU-1", "B0TEST0001", "Test product", 21.99, 0.25],
        ]
    )

    diff = _compare_sheet_by_business_key(before_ws, after_ws)

    assert diff is not None
    assert diff["added_count"] == 0
    assert diff["removed_count"] == 0
    assert diff["changed_record_count"] == 1
    assert diff["changed_fields"] == {"selling_price": 1, "target_acos": 1}
    assert diff["changed_marketplaces"] == {"US": 1}
    assert diff["sample_changed_records"][0]["key"] == "US||SKU-1||B0TEST0001"

    before_wb.close()
    after_wb.close()


def test_cost_config_audit_markdown_lists_review_fields() -> None:
    markdown = build_markdown_summary(
        {
            "baseline": "HEAD:config/product_cost_config.xlsx",
            "config_path": "config/product_cost_config.xlsx",
            "total_changed_cells": 2,
            "sheets": {
                "product_cost_config": {
                    "keyed_diff": {
                        "changed_record_count": 1,
                        "changed_marketplaces": {"US": 1},
                        "changed_fields": {"selling_price": 1, "suggested_target_acos": 1},
                        "sample_changed_records": [
                            {
                                "key": "US||SKU-1||B0TEST0001",
                                "marketplace": "US",
                                "sku": "SKU-1",
                                "asin": "B0TEST0001",
                                "product_name": "Test product",
                                "changed_fields": [
                                    {"field": "selling_price", "before": "19.99", "after": "21.99"},
                                    {"field": "suggested_target_acos", "before": "0.2", "after": "0.25"},
                                ],
                            }
                        ],
                    }
                },
                "SKU匹配检查": {
                    "keyed_diff": {
                        "sample_changed_records": [
                            {
                                "key": "US||SKU-1||B0TEST0001",
                                "changed_fields": [
                                    {"field": "inventory_note", "before": "", "after": "库存确认"},
                                ],
                            }
                        ]
                    }
                },
            },
        }
    )

    assert "# product_cost_config 差异人工确认表" in markdown
    assert "## 最高风险差异" in markdown
    assert "| US | SKU-1 | B0TEST0001 | Test product | selling_price | 19.99 | 21.99 |" in markdown
    assert "| US | SKU-1 | B0TEST0001 | Test product | suggested_target_acos | 0.2 | 0.25 |" in markdown
    assert "| US | SKU-1 | B0TEST0001 | Test product | inventory_note |  | 库存确认 |" in markdown


def test_cost_config_audit_marks_high_risk_margin_and_inventory_changes() -> None:
    markdown = build_markdown_summary(
        {
            "baseline": "HEAD:config/product_cost_config.xlsx",
            "config_path": "config/product_cost_config.xlsx",
            "total_changed_cells": 5,
            "sheets": {
                "product_cost_config": {
                    "keyed_diff": {
                        "changed_record_count": 1,
                        "changed_marketplaces": {"UK": 1},
                        "changed_fields": {
                            "selling_price": 1,
                            "profit_after_10pct_ads": 1,
                            "suggested_target_acos": 1,
                            "total_cost_before_ads": 1,
                        },
                        "sample_changed_records": [
                            {
                                "key": "UK||SKU-RISK||B0RISK0001",
                                "marketplace": "UK",
                                "sku": "SKU-RISK",
                                "asin": "B0RISK0001",
                                "product_name": "Risk product",
                                "changed_fields": [
                                    {"field": "selling_price", "before": "35.00", "after": "20.00"},
                                    {"field": "profit_after_10pct_ads", "before": "2.00", "after": "-1.25"},
                                    {"field": "suggested_target_acos", "before": "0.20", "after": "0"},
                                    {"field": "total_cost_before_ads", "before": "25.00", "after": "22.00"},
                                ],
                            }
                        ],
                    }
                },
                "SKU匹配检查": {
                    "keyed_diff": {
                        "sample_changed_records": [
                            {
                                "key": "UK||SKU-RISK||B0RISK0001",
                                "changed_fields": [
                                    {"field": "current_inventory", "before": "0", "after": "80"},
                                ],
                            }
                        ]
                    }
                },
            },
        }
    )

    assert "售价变动超过 30%" in markdown
    assert "建议 target ACOS 变为 0" in markdown
    assert "10% 广告费后利润为负" in markdown
    assert "库存从 0 变为有货" in markdown
