from __future__ import annotations

from pathlib import Path

import pandas as pd

from main import prepare_ads_import_frame, prepare_erp_import_frame
from src.db import AnalyticsDatabase


def test_raw_import_frames_keep_attribution_and_inventory_fields(tmp_path) -> None:
    ads_source = tmp_path / "ads.csv"
    erp_source = tmp_path / "erp.xlsx"
    ads_archive = tmp_path / "archive_ads.csv"
    erp_archive = tmp_path / "archive_erp.xlsx"
    for path in [ads_source, erp_source, ads_archive, erp_archive]:
        path.write_text("fixture", encoding="utf-8")

    ads_frame = prepare_ads_import_frame(
        pd.DataFrame(
            [
                {
                    "marketplace": "US",
                    "date": "2026-06-08",
                    "campaign_id": "C1",
                    "ad_group_id": "G1",
                    "sku": "SKU-1",
                    "asin": "B0TEST0001",
                    "search_term": "led desk lamp",
                    "targeting": "led desk lamp",
                    "campaign_name": "Campaign",
                    "ad_group_name": "Group",
                    "match_type": "exact",
                    "impressions": 100,
                    "clicks": 10,
                    "spend": 5.0,
                    "ad_orders": 2,
                    "ad_sales": 40.0,
                    "click_orders": 2,
                    "click_sales": 40.0,
                    "click_roas": 8.0,
                    "click_cpa": 2.5,
                    "promoted_click_orders": 1,
                    "promoted_click_sales": 20.0,
                    "promoted_ad_orders": 1,
                    "promoted_ad_sales": 20.0,
                    "halo_click_orders": 1,
                    "halo_click_sales": 20.0,
                    "halo_click_units": 1,
                    "halo_ad_orders": 1,
                    "halo_ad_sales": 20.0,
                    "halo_ad_units": 1,
                }
            ]
        ),
        ads_source,
        ads_archive,
    )
    erp_frame = prepare_erp_import_frame(
        pd.DataFrame(
            [
                {
                    "marketplace": "US",
                    "date": "2026-06-08",
                    "sku": "SKU-1",
                    "asin": "B0TEST0001",
                    "product_name": "Test product",
                    "total_orders": 3,
                    "total_sales": 60.0,
                    "fba_stock": 12,
                    "fbm_stock": 4,
                    "available_stock": 16,
                }
            ]
        ),
        erp_source,
        erp_archive,
    )

    assert "click_orders" in ads_frame.columns
    assert "promoted_ad_orders" in ads_frame.columns
    assert "halo_ad_units" in ads_frame.columns
    assert "available_stock" in erp_frame.columns

    db = AnalyticsDatabase(tmp_path / "raw_import.sqlite")
    first_stats = db.import_raw_frames(ads_frame, erp_frame)
    second_stats = db.import_raw_frames(ads_frame, erp_frame)

    assert first_stats["added_rows"] == 2
    assert second_stats["duplicate_skipped_rows"] == 2

    with db._connect() as connection:
        ads_row = connection.execute(
            "SELECT click_orders, promoted_ad_orders, halo_ad_units FROM ads_import_raw WHERE marketplace = 'US'"
        ).fetchone()
        erp_row = connection.execute(
            "SELECT fba_stock, fbm_stock, available_stock FROM erp_import_raw WHERE marketplace = 'US'"
        ).fetchone()

    assert ads_row == (2.0, 1.0, 1.0)
    assert erp_row == (12.0, 4.0, 16.0)


def test_raw_import_frame_defaults_keep_legacy_reports_importable(tmp_path) -> None:
    ads_source = tmp_path / "ads.csv"
    erp_source = tmp_path / "erp.xlsx"
    ads_archive = tmp_path / "archive_ads.csv"
    erp_archive = tmp_path / "archive_erp.xlsx"
    for path in [ads_source, erp_source, ads_archive, erp_archive]:
        path.write_text("fixture", encoding="utf-8")

    ads_frame = prepare_ads_import_frame(
        pd.DataFrame(
            [
                {
                    "marketplace": "UK",
                    "date": "2026-06-08",
                    "campaign_id": "C1",
                    "ad_group_id": "G1",
                    "sku": "SKU-1",
                    "asin": "B0TEST0001",
                    "search_term": "",
                    "targeting": "",
                    "campaign_name": "Campaign",
                    "ad_group_name": "Group",
                    "match_type": "",
                    "impressions": 10,
                    "clicks": 1,
                    "spend": 0.5,
                    "ad_orders": 0,
                    "ad_sales": 0,
                }
            ]
        ),
        ads_source,
        ads_archive,
    )
    erp_frame = prepare_erp_import_frame(
        pd.DataFrame(
            [
                {
                    "marketplace": "UK",
                    "date": "2026-06-08",
                    "sku": "SKU-1",
                    "asin": "B0TEST0001",
                    "product_name": "Legacy product",
                    "total_orders": 1,
                    "total_sales": 9.99,
                }
            ]
        ),
        erp_source,
        erp_archive,
    )

    assert ads_frame.loc[0, "click_orders"] == 0
    assert ads_frame.loc[0, "halo_ad_units"] == 0
    assert erp_frame.loc[0, "fba_stock"] == 0
    assert erp_frame.loc[0, "available_stock"] == 0


def test_erp_raw_import_updates_when_only_inventory_changes(tmp_path) -> None:
    ads_source = tmp_path / "ads.csv"
    erp_source = tmp_path / "erp.xlsx"
    archive = tmp_path / "archive.xlsx"
    for path in [ads_source, erp_source, archive]:
        path.write_text("fixture", encoding="utf-8")

    ads_frame = prepare_ads_import_frame(
        pd.DataFrame(
            [
                {
                    "marketplace": "US",
                    "date": "2026-06-08",
                    "campaign_id": "C1",
                    "ad_group_id": "G1",
                    "sku": "SKU-1",
                    "asin": "B0TEST0001",
                    "search_term": "",
                    "targeting": "",
                    "campaign_name": "Campaign",
                    "ad_group_name": "Group",
                    "match_type": "",
                    "impressions": 0,
                    "clicks": 0,
                    "spend": 0,
                    "ad_orders": 0,
                    "ad_sales": 0,
                }
            ]
        ),
        ads_source,
        archive,
    )
    erp_frame = prepare_erp_import_frame(
        pd.DataFrame(
            [
                {
                    "marketplace": "US",
                    "date": "2026-06-08",
                    "sku": "SKU-1",
                    "asin": "B0TEST0001",
                    "product_name": "Test product",
                    "total_orders": 3,
                    "total_sales": 60.0,
                    "fba_stock": 12,
                    "fbm_stock": 0,
                    "available_stock": 12,
                }
            ]
        ),
        erp_source,
        archive,
    )
    updated_erp_frame = erp_frame.copy()
    updated_erp_frame.loc[0, "fba_stock"] = 18
    updated_erp_frame.loc[0, "available_stock"] = 18

    db = AnalyticsDatabase(tmp_path / "inventory_update.sqlite")
    first_stats = db.import_raw_frames(ads_frame, erp_frame)
    second_stats = db.import_raw_frames(ads_frame, updated_erp_frame)

    assert first_stats["erp_added_rows"] == 1
    assert second_stats["erp_overwrite_updated_rows"] == 1
    assert second_stats["erp_duplicate_skipped_rows"] == 0

    with db._connect() as connection:
        erp_row = connection.execute(
            "SELECT fba_stock, available_stock FROM erp_import_raw WHERE marketplace = 'US'"
        ).fetchone()

    assert erp_row == (18.0, 18.0)
