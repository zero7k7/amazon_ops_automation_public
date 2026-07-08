from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from main import prepare_ads_import_frame, prepare_erp_import_frame
from src.db import (
    ADS_IMPORT_RAW_KEY_COLUMNS,
    CAMPAIGN_DAILY_KEY_COLUMNS,
    ERP_IMPORT_RAW_KEY_COLUMNS,
    PRODUCT_DAILY_KEY_COLUMNS,
    SEARCH_TERM_DAILY_KEY_COLUMNS,
    AnalyticsDatabase,
)


def _daily_frames(
    *,
    date: str = "2026-06-08",
    marketplace: str = "US",
    sku: str = "SKU-1",
    asin: str = "B0TEST0001",
    clicks: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    product = pd.DataFrame(
        [
            {
                "date": date,
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": "Test product",
                "clicks": clicks,
                "spend": float(clicks),
                "total_orders": 1,
            }
        ]
    )
    campaign = product.assign(campaign_name="Campaign")
    search = campaign.assign(search_term="test term")
    return product, campaign, search


def _raw_import_frames(
    *,
    date: str = "2026-06-08",
    marketplace: str = "US",
    sku: str = "SKU-1",
    asin: str = "B0TEST0001",
    clicks: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ads = pd.DataFrame(
        [
            {
                "marketplace": marketplace,
                "date": date,
                "campaign_id": "C1",
                "ad_group_id": "G1",
                "sku": sku,
                "asin": asin,
                "search_term": "test term",
                "targeting": "test term",
                "campaign_name": "Campaign",
                "ad_group_name": "Group",
                "match_type": "exact",
                "impressions": clicks * 10,
                "clicks": clicks,
                "spend": float(clicks),
                "ad_orders": 1,
                "ad_sales": 20.0,
                "click_orders": 1,
                "click_sales": 20.0,
                "promoted_ad_orders": 1,
                "promoted_ad_sales": 20.0,
                "halo_ad_orders": 0,
                "halo_ad_sales": 0.0,
                "halo_ad_units": 0,
            }
        ]
    )
    erp = pd.DataFrame(
        [
            {
                "marketplace": marketplace,
                "date": date,
                "sku": sku,
                "asin": asin,
                "product_name": "Test product",
                "total_orders": clicks,
                "total_sales": float(clicks) * 20,
                "fba_stock": 12,
                "fbm_stock": 4,
                "available_stock": 16,
            }
        ]
    )
    return ads, erp


def test_persistence_key_contracts_match_existing_sqlite_primary_keys(tmp_path) -> None:
    expected_keys = {
        "ads_import_raw": ADS_IMPORT_RAW_KEY_COLUMNS,
        "erp_import_raw": ERP_IMPORT_RAW_KEY_COLUMNS,
        "product_daily": PRODUCT_DAILY_KEY_COLUMNS,
        "campaign_daily": CAMPAIGN_DAILY_KEY_COLUMNS,
        "search_term_daily": SEARCH_TERM_DAILY_KEY_COLUMNS,
    }
    assert expected_keys == {
        "ads_import_raw": ["marketplace", "date", "campaign_id", "ad_group_id", "sku", "asin", "search_term", "targeting"],
        "erp_import_raw": ["marketplace", "date", "sku", "asin"],
        "product_daily": ["date", "marketplace", "sku", "asin"],
        "campaign_daily": ["date", "marketplace", "campaign_name", "sku", "asin"],
        "search_term_daily": ["date", "marketplace", "search_term", "campaign_name", "sku", "asin"],
    }

    db = AnalyticsDatabase(tmp_path / "key_contract.sqlite")
    with db._connect() as connection:
        primary_keys = {
            table_name: [
                row[1]
                for row in sorted(
                    connection.execute(f"PRAGMA table_info({table_name})").fetchall(),
                    key=lambda row: row[5],
                )
                if row[5]
            ]
            for table_name in expected_keys
        }

    assert primary_keys == expected_keys


def test_daily_frame_upsert_begins_immediate_transaction_before_deleting_scope(monkeypatch, tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_begin_immediate.sqlite")
    statements: list[str] = []

    class TraceConnection(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            statements.append(" ".join(str(sql).strip().split()))
            return super().execute(sql, parameters)

    def connect_traced():
        return sqlite3.connect(db.db_path, factory=TraceConnection)

    monkeypatch.setattr(db, "_connect", connect_traced)

    product_daily, campaign_daily, search_term_daily = _daily_frames(clicks=1)
    db.upsert_daily_frames(product_daily, campaign_daily, search_term_daily)

    first_delete_index = next(
        index for index, statement in enumerate(statements) if statement.startswith("DELETE FROM product_daily")
    )
    assert statements[0] == "BEGIN IMMEDIATE"
    assert first_delete_index > 0


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
                    "search_term": "metal board",
                    "targeting": "metal board",
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


def test_raw_import_rolls_back_ads_when_erp_write_fails(monkeypatch, tmp_path) -> None:
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
                    "search_term": "metal board",
                    "targeting": "metal board",
                    "campaign_name": "Campaign",
                    "ad_group_name": "Group",
                    "match_type": "exact",
                    "impressions": 10,
                    "clicks": 1,
                    "spend": 0.5,
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
                    "total_orders": 1,
                    "total_sales": 20.0,
                }
            ]
        ),
        erp_source,
        archive,
    )

    db = AnalyticsDatabase(tmp_path / "raw_import_rollback.sqlite")
    original_upsert = db._upsert

    def fail_on_erp(connection, table_name, frame, key_columns):
        if table_name == "erp_import_raw":
            raise RuntimeError("simulated erp raw write failure")
        return original_upsert(connection, table_name, frame, key_columns)

    monkeypatch.setattr(db, "_upsert", fail_on_erp)

    with pytest.raises(RuntimeError, match="simulated erp raw write failure"):
        db.import_raw_frames(ads_frame, erp_frame)

    with db._connect() as connection:
        ads_count = connection.execute("SELECT COUNT(*) FROM ads_import_raw").fetchone()[0]
        erp_count = connection.execute("SELECT COUNT(*) FROM erp_import_raw").fetchone()[0]

    assert ads_count == 0
    assert erp_count == 0


def test_raw_import_can_retry_after_erp_write_failure(monkeypatch, tmp_path) -> None:
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
                    "search_term": "metal board",
                    "targeting": "metal board",
                    "campaign_name": "Campaign",
                    "ad_group_name": "Group",
                    "match_type": "exact",
                    "impressions": 10,
                    "clicks": 1,
                    "spend": 0.5,
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
                    "total_orders": 1,
                    "total_sales": 20.0,
                }
            ]
        ),
        erp_source,
        archive,
    )

    db = AnalyticsDatabase(tmp_path / "raw_import_retry.sqlite")
    original_upsert = db._upsert
    failure_enabled = True

    def fail_once_on_erp(connection, table_name, frame, key_columns):
        if failure_enabled and table_name == "erp_import_raw":
            raise RuntimeError("simulated recoverable erp raw write failure")
        return original_upsert(connection, table_name, frame, key_columns)

    monkeypatch.setattr(db, "_upsert", fail_once_on_erp)

    with pytest.raises(RuntimeError, match="simulated recoverable erp raw write failure"):
        db.import_raw_frames(ads_frame, erp_frame)

    with db._connect() as connection:
        ads_count_after_failure = connection.execute("SELECT COUNT(*) FROM ads_import_raw").fetchone()[0]
        erp_count_after_failure = connection.execute("SELECT COUNT(*) FROM erp_import_raw").fetchone()[0]

    assert ads_count_after_failure == 0
    assert erp_count_after_failure == 0

    failure_enabled = False
    stats = db.import_raw_frames(ads_frame, erp_frame)

    with db._connect() as connection:
        ads_count_after_retry = connection.execute("SELECT COUNT(*) FROM ads_import_raw").fetchone()[0]
        erp_count_after_retry = connection.execute("SELECT COUNT(*) FROM erp_import_raw").fetchone()[0]

    assert stats["added_rows"] == 2
    assert ads_count_after_retry == 1
    assert erp_count_after_retry == 1


def test_daily_frame_upsert_rolls_back_delete_and_partial_insert_on_failure(monkeypatch, tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_rollback.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)
    original_upsert = db._upsert

    def fail_on_campaign(connection, table_name, frame, key_columns):
        if table_name == "campaign_daily":
            raise RuntimeError("simulated campaign write failure")
        return original_upsert(connection, table_name, frame, key_columns)

    monkeypatch.setattr(db, "_upsert", fail_on_campaign)

    with pytest.raises(RuntimeError, match="simulated campaign write failure"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_clicks = connection.execute("SELECT clicks FROM product_daily WHERE marketplace = 'US'").fetchall()
        campaign_clicks = connection.execute("SELECT clicks FROM campaign_daily WHERE marketplace = 'US'").fetchall()
        search_clicks = connection.execute("SELECT clicks FROM search_term_daily WHERE marketplace = 'US'").fetchall()

    assert product_clicks == [(1.0,)]
    assert campaign_clicks == [(1.0,)]
    assert search_clicks == [(1.0,)]


def test_daily_frame_upsert_rolls_back_after_late_table_failure(monkeypatch, tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_late_table_rollback.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)
    original_upsert = db._upsert

    def fail_on_search_term(connection, table_name, frame, key_columns):
        if table_name == "search_term_daily":
            raise RuntimeError("simulated search term write failure")
        return original_upsert(connection, table_name, frame, key_columns)

    monkeypatch.setattr(db, "_upsert", fail_on_search_term)

    with pytest.raises(RuntimeError, match="simulated search term write failure"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_clicks = connection.execute("SELECT clicks FROM product_daily WHERE marketplace = 'US'").fetchall()
        campaign_clicks = connection.execute("SELECT clicks FROM campaign_daily WHERE marketplace = 'US'").fetchall()
        search_clicks = connection.execute("SELECT clicks FROM search_term_daily WHERE marketplace = 'US'").fetchall()

    assert product_clicks == [(1.0,)]
    assert campaign_clicks == [(1.0,)]
    assert search_clicks == [(1.0,)]


def test_daily_frame_upsert_can_retry_after_late_table_failure(monkeypatch, tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_late_table_retry.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)
    original_upsert = db._upsert
    failure_enabled = True

    def fail_once_on_search_term(connection, table_name, frame, key_columns):
        if failure_enabled and table_name == "search_term_daily":
            raise RuntimeError("simulated recoverable search term write failure")
        return original_upsert(connection, table_name, frame, key_columns)

    monkeypatch.setattr(db, "_upsert", fail_once_on_search_term)

    with pytest.raises(RuntimeError, match="simulated recoverable search term write failure"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_clicks_after_failure = connection.execute("SELECT clicks FROM product_daily WHERE marketplace = 'US'").fetchall()
        campaign_clicks_after_failure = connection.execute("SELECT clicks FROM campaign_daily WHERE marketplace = 'US'").fetchall()
        search_clicks_after_failure = connection.execute("SELECT clicks FROM search_term_daily WHERE marketplace = 'US'").fetchall()

    assert product_clicks_after_failure == [(1.0,)]
    assert campaign_clicks_after_failure == [(1.0,)]
    assert search_clicks_after_failure == [(1.0,)]

    failure_enabled = False
    db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_clicks_after_retry = connection.execute("SELECT clicks FROM product_daily WHERE marketplace = 'US'").fetchall()
        campaign_clicks_after_retry = connection.execute("SELECT clicks FROM campaign_daily WHERE marketplace = 'US'").fetchall()
        search_clicks_after_retry = connection.execute("SELECT clicks FROM search_term_daily WHERE marketplace = 'US'").fetchall()

    assert product_clicks_after_retry == [(99.0,)]
    assert campaign_clicks_after_retry == [(99.0,)]
    assert search_clicks_after_retry == [(99.0,)]


def test_daily_frame_upsert_rolls_back_when_commit_fails(monkeypatch, tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_commit_failure_rollback.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)
    opened_connections: list[sqlite3.Connection] = []

    class CommitFailConnection(sqlite3.Connection):
        rollback_called = False

        def commit(self) -> None:
            raise sqlite3.OperationalError("simulated sqlite commit failure")

        def rollback(self) -> None:
            self.rollback_called = True
            return super().rollback()

    def connect_with_failing_commit():
        connection = sqlite3.connect(db.db_path, factory=CommitFailConnection)
        opened_connections.append(connection)
        return connection

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)
    monkeypatch.setattr(db, "_connect", connect_with_failing_commit)

    with pytest.raises(sqlite3.OperationalError, match="simulated sqlite commit failure"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    assert opened_connections[0].rollback_called is True

    with sqlite3.connect(db.db_path) as connection:
        product_clicks = connection.execute("SELECT clicks FROM product_daily WHERE marketplace = 'US'").fetchall()
        campaign_clicks = connection.execute("SELECT clicks FROM campaign_daily WHERE marketplace = 'US'").fetchall()
        search_clicks = connection.execute("SELECT clicks FROM search_term_daily WHERE marketplace = 'US'").fetchall()

    assert product_clicks == [(1.0,)]
    assert campaign_clicks == [(1.0,)]
    assert search_clicks == [(1.0,)]


def test_daily_frame_upsert_rolls_back_after_sqlite_engine_failure(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_sqlite_engine_rollback.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)

    with db._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_search_term_daily_replacement
            BEFORE INSERT ON search_term_daily
            WHEN NEW.clicks = 99
            BEGIN
                SELECT RAISE(ABORT, 'simulated sqlite search term write failure');
            END
            """
        )

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)

    with pytest.raises(Exception, match="simulated sqlite search term write failure"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_clicks = connection.execute("SELECT clicks FROM product_daily WHERE marketplace = 'US'").fetchall()
        campaign_clicks = connection.execute("SELECT clicks FROM campaign_daily WHERE marketplace = 'US'").fetchall()
        search_clicks = connection.execute("SELECT clicks FROM search_term_daily WHERE marketplace = 'US'").fetchall()

    assert product_clicks == [(1.0,)]
    assert campaign_clicks == [(1.0,)]
    assert search_clicks == [(1.0,)]


def test_daily_frame_upsert_rolls_back_partial_product_executemany_failure(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_product_partial_insert_rollback.sqlite")
    ok_product, ok_campaign, ok_search = _daily_frames(
        sku="SKU-OK",
        asin="B0OK000001",
        clicks=1,
    )
    bad_product, bad_campaign, bad_search = _daily_frames(
        sku="SKU-BAD",
        asin="B0BAD00001",
        clicks=2,
    )
    db.upsert_daily_frames(
        pd.concat([ok_product, bad_product], ignore_index=True),
        pd.concat([ok_campaign, bad_campaign], ignore_index=True),
        pd.concat([ok_search, bad_search], ignore_index=True),
    )

    with db._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_second_product_replacement
            BEFORE INSERT ON product_daily
            WHEN NEW.sku = 'SKU-BAD' AND NEW.clicks = 101
            BEGIN
                SELECT RAISE(ABORT, 'simulated partial product insert failure');
            END
            """
        )

    replacement_ok_product, replacement_ok_campaign, replacement_ok_search = _daily_frames(
        sku="SKU-OK",
        asin="B0OK000001",
        clicks=99,
    )
    replacement_bad_product, replacement_bad_campaign, replacement_bad_search = _daily_frames(
        sku="SKU-BAD",
        asin="B0BAD00001",
        clicks=101,
    )

    with pytest.raises(Exception, match="simulated partial product insert failure"):
        db.upsert_daily_frames(
            pd.concat([replacement_ok_product, replacement_bad_product], ignore_index=True),
            pd.concat([replacement_ok_campaign, replacement_bad_campaign], ignore_index=True),
            pd.concat([replacement_ok_search, replacement_bad_search], ignore_index=True),
        )

    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT sku, clicks FROM product_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT sku, clicks FROM campaign_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT sku, clicks FROM search_term_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()

    assert product_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]
    assert campaign_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]
    assert search_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]


def test_daily_frame_upsert_rolls_back_partial_campaign_executemany_failure(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_campaign_partial_insert_rollback.sqlite")
    ok_product, ok_campaign, ok_search = _daily_frames(
        sku="SKU-OK",
        asin="B0OK000001",
        clicks=1,
    )
    bad_product, bad_campaign, bad_search = _daily_frames(
        sku="SKU-BAD",
        asin="B0BAD00001",
        clicks=2,
    )
    db.upsert_daily_frames(
        pd.concat([ok_product, bad_product], ignore_index=True),
        pd.concat([ok_campaign, bad_campaign], ignore_index=True),
        pd.concat([ok_search, bad_search], ignore_index=True),
    )

    with db._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_second_campaign_replacement
            BEFORE INSERT ON campaign_daily
            WHEN NEW.sku = 'SKU-BAD' AND NEW.clicks = 101
            BEGIN
                SELECT RAISE(ABORT, 'simulated partial campaign insert failure');
            END
            """
        )

    replacement_ok_product, replacement_ok_campaign, replacement_ok_search = _daily_frames(
        sku="SKU-OK",
        asin="B0OK000001",
        clicks=99,
    )
    replacement_bad_product, replacement_bad_campaign, replacement_bad_search = _daily_frames(
        sku="SKU-BAD",
        asin="B0BAD00001",
        clicks=101,
    )

    with pytest.raises(Exception, match="simulated partial campaign insert failure"):
        db.upsert_daily_frames(
            pd.concat([replacement_ok_product, replacement_bad_product], ignore_index=True),
            pd.concat([replacement_ok_campaign, replacement_bad_campaign], ignore_index=True),
            pd.concat([replacement_ok_search, replacement_bad_search], ignore_index=True),
        )

    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT sku, clicks FROM product_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT sku, clicks FROM campaign_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT sku, clicks FROM search_term_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()

    assert product_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]
    assert campaign_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]
    assert search_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]


def test_daily_frame_upsert_rolls_back_partial_search_term_executemany_failure(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_search_partial_insert_rollback.sqlite")
    ok_product, ok_campaign, ok_search = _daily_frames(
        sku="SKU-OK",
        asin="B0OK000001",
        clicks=1,
    )
    bad_product, bad_campaign, bad_search = _daily_frames(
        sku="SKU-BAD",
        asin="B0BAD00001",
        clicks=2,
    )
    db.upsert_daily_frames(
        pd.concat([ok_product, bad_product], ignore_index=True),
        pd.concat([ok_campaign, bad_campaign], ignore_index=True),
        pd.concat([ok_search, bad_search], ignore_index=True),
    )

    with db._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_second_search_term_replacement
            BEFORE INSERT ON search_term_daily
            WHEN NEW.sku = 'SKU-BAD' AND NEW.clicks = 101
            BEGIN
                SELECT RAISE(ABORT, 'simulated partial search term insert failure');
            END
            """
        )

    replacement_ok_product, replacement_ok_campaign, replacement_ok_search = _daily_frames(
        sku="SKU-OK",
        asin="B0OK000001",
        clicks=99,
    )
    replacement_bad_product, replacement_bad_campaign, replacement_bad_search = _daily_frames(
        sku="SKU-BAD",
        asin="B0BAD00001",
        clicks=101,
    )

    with pytest.raises(Exception, match="simulated partial search term insert failure"):
        db.upsert_daily_frames(
            pd.concat([replacement_ok_product, replacement_bad_product], ignore_index=True),
            pd.concat([replacement_ok_campaign, replacement_bad_campaign], ignore_index=True),
            pd.concat([replacement_ok_search, replacement_bad_search], ignore_index=True),
        )

    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT sku, clicks FROM product_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT sku, clicks FROM campaign_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT sku, clicks FROM search_term_daily WHERE marketplace = 'US' ORDER BY sku"
        ).fetchall()

    assert product_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]
    assert campaign_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]
    assert search_rows == [("SKU-BAD", 2.0), ("SKU-OK", 1.0)]


def test_daily_frame_upsert_rolls_back_when_delete_phase_fails(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_delete_phase_rollback.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)

    with db._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_campaign_daily_replacement_delete
            BEFORE DELETE ON campaign_daily
            WHEN OLD.marketplace = 'US'
            BEGIN
                SELECT RAISE(ABORT, 'simulated sqlite campaign delete failure');
            END
            """
        )

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)

    with pytest.raises(Exception, match="simulated sqlite campaign delete failure"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_clicks = connection.execute("SELECT clicks FROM product_daily WHERE marketplace = 'US'").fetchall()
        campaign_clicks = connection.execute("SELECT clicks FROM campaign_daily WHERE marketplace = 'US'").fetchall()
        search_clicks = connection.execute("SELECT clicks FROM search_term_daily WHERE marketplace = 'US'").fetchall()

    assert product_clicks == [(1.0,)]
    assert campaign_clicks == [(1.0,)]
    assert search_clicks == [(1.0,)]


def test_daily_frame_upsert_failure_keeps_all_marketplace_scopes_atomic(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_multi_scope_rollback.sqlite")
    us_product, us_campaign, us_search = _daily_frames(
        marketplace="US",
        sku="SKU-US",
        asin="B0US000001",
        clicks=1,
    )
    uk_product, uk_campaign, uk_search = _daily_frames(
        marketplace="UK",
        sku="SKU-UK",
        asin="B0UK000001",
        clicks=7,
    )
    db.upsert_daily_frames(
        pd.concat([us_product, uk_product], ignore_index=True),
        pd.concat([us_campaign, uk_campaign], ignore_index=True),
        pd.concat([us_search, uk_search], ignore_index=True),
    )

    with db._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_us_search_term_replacement
            BEFORE INSERT ON search_term_daily
            WHEN NEW.marketplace = 'US' AND NEW.clicks = 99
            BEGIN
                SELECT RAISE(ABORT, 'simulated us search term replacement failure');
            END
            """
        )

    replacement_product, replacement_campaign, replacement_search = _daily_frames(
        marketplace="US",
        sku="SKU-US",
        asin="B0US000001",
        clicks=99,
    )

    with pytest.raises(Exception, match="simulated us search term replacement failure"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM product_daily ORDER BY marketplace, sku"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM campaign_daily ORDER BY marketplace, sku"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM search_term_daily ORDER BY marketplace, sku"
        ).fetchall()

    expected_rows = [("UK", "SKU-UK", 7.0), ("US", "SKU-US", 1.0)]
    assert product_rows == expected_rows
    assert campaign_rows == expected_rows
    assert search_rows == expected_rows


def test_daily_frame_upsert_preserves_current_date_marketplace_cross_product_scope_contract(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_scope_contract.sqlite")
    existing_frames = [
        _daily_frames(date="2026-06-08", marketplace="US", sku="SKU-US-08", asin="B0US000008", clicks=1),
        _daily_frames(date="2026-06-09", marketplace="US", sku="SKU-US-09", asin="B0US000009", clicks=2),
        _daily_frames(date="2026-06-08", marketplace="UK", sku="SKU-UK-08", asin="B0UK000008", clicks=3),
        _daily_frames(date="2026-06-09", marketplace="UK", sku="SKU-UK-09", asin="B0UK000009", clicks=4),
    ]
    db.upsert_daily_frames(
        pd.concat([frames[0] for frames in existing_frames], ignore_index=True),
        pd.concat([frames[1] for frames in existing_frames], ignore_index=True),
        pd.concat([frames[2] for frames in existing_frames], ignore_index=True),
    )

    replacement_frames = [
        _daily_frames(date="2026-06-08", marketplace="US", sku="SKU-US-08", asin="B0US000008", clicks=99),
        _daily_frames(date="2026-06-09", marketplace="UK", sku="SKU-UK-09", asin="B0UK000009", clicks=77),
    ]
    db.upsert_daily_frames(
        pd.concat([frames[0] for frames in replacement_frames], ignore_index=True),
        pd.concat([frames[1] for frames in replacement_frames], ignore_index=True),
        pd.concat([frames[2] for frames in replacement_frames], ignore_index=True),
    )

    expected_rows = [
        ("2026-06-08", "US", "SKU-US-08", 99.0),
        ("2026-06-09", "UK", "SKU-UK-09", 77.0),
    ]
    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT date, marketplace, sku, clicks FROM product_daily ORDER BY date, marketplace, sku"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT date, marketplace, sku, clicks FROM campaign_daily ORDER BY date, marketplace, sku"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT date, marketplace, sku, clicks FROM search_term_daily ORDER BY date, marketplace, sku"
        ).fetchall()

    assert product_rows == expected_rows
    assert campaign_rows == expected_rows
    assert search_rows == expected_rows


def test_daily_frame_upsert_preserves_child_tables_when_replacement_is_empty(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_empty_child_scope.sqlite")
    us_product, us_campaign, us_search = _daily_frames(
        marketplace="US",
        sku="SKU-US",
        asin="B0US000001",
        clicks=1,
    )
    uk_product, uk_campaign, uk_search = _daily_frames(
        marketplace="UK",
        sku="SKU-UK",
        asin="B0UK000001",
        clicks=7,
    )
    db.upsert_daily_frames(
        pd.concat([us_product, uk_product], ignore_index=True),
        pd.concat([us_campaign, uk_campaign], ignore_index=True),
        pd.concat([us_search, uk_search], ignore_index=True),
    )

    replacement_product, replacement_campaign, replacement_search = _daily_frames(
        marketplace="US",
        sku="SKU-US",
        asin="B0US000001",
        clicks=99,
    )
    db.upsert_daily_frames(
        replacement_product,
        replacement_campaign.iloc[0:0].copy(),
        replacement_search.iloc[0:0].copy(),
    )

    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM product_daily ORDER BY marketplace, sku"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM campaign_daily ORDER BY marketplace, sku"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM search_term_daily ORDER BY marketplace, sku"
        ).fetchall()

    assert product_rows == [("UK", "SKU-UK", 7.0), ("US", "SKU-US", 99.0)]
    assert campaign_rows == [("UK", "SKU-UK", 7.0), ("US", "SKU-US", 1.0)]
    assert search_rows == [("UK", "SKU-UK", 7.0), ("US", "SKU-US", 1.0)]


def test_daily_frame_empty_child_table_cleanup_rolls_back_when_insert_fails(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_empty_child_rollback.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)
    replacement_product = replacement_product.assign(new_report_only_metric=123)

    with pytest.raises(Exception, match="new_report_only_metric"):
        db.upsert_daily_frames(
            replacement_product,
            replacement_campaign.iloc[0:0].copy(),
            replacement_search.iloc[0:0].copy(),
        )

    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM product_daily WHERE marketplace = 'US'"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM campaign_daily WHERE marketplace = 'US'"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM search_term_daily WHERE marketplace = 'US'"
        ).fetchall()

    assert product_rows == [("US", "SKU-1", 1.0)]
    assert campaign_rows == [("US", "SKU-1", 1.0)]
    assert search_rows == [("US", "SKU-1", 1.0)]


def test_daily_frame_upsert_rolls_back_when_frame_has_unknown_database_column(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "daily_unknown_column_rollback.sqlite")
    original_product, original_campaign, original_search = _daily_frames(clicks=1)
    db.upsert_daily_frames(original_product, original_campaign, original_search)

    replacement_product, replacement_campaign, replacement_search = _daily_frames(clicks=99)
    replacement_product = replacement_product.assign(new_report_only_metric=123)

    with pytest.raises(Exception, match="new_report_only_metric"):
        db.upsert_daily_frames(replacement_product, replacement_campaign, replacement_search)

    with db._connect() as connection:
        product_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM product_daily WHERE marketplace = 'US'"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM campaign_daily WHERE marketplace = 'US'"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT marketplace, sku, clicks FROM search_term_daily WHERE marketplace = 'US'"
        ).fetchall()

    assert product_rows == [("US", "SKU-1", 1.0)]
    assert campaign_rows == [("US", "SKU-1", 1.0)]
    assert search_rows == [("US", "SKU-1", 1.0)]


def test_raw_import_and_daily_upsert_roll_back_together_when_daily_write_fails(tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "raw_daily_combined_rollback.sqlite")
    raw_ads, raw_erp = _raw_import_frames(date="2026-06-08", clicks=1)
    product_daily, campaign_daily, search_term_daily = _daily_frames(date="2026-06-08", clicks=1)
    db.import_raw_and_daily_frames(raw_ads, raw_erp, product_daily, campaign_daily, search_term_daily)

    with db._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_combined_search_term_replacement
            BEFORE INSERT ON search_term_daily
            WHEN NEW.date = '2026-06-09'
            BEGIN
                SELECT RAISE(ABORT, 'simulated combined daily write failure');
            END
            """
        )

    replacement_ads, replacement_erp = _raw_import_frames(date="2026-06-09", clicks=99)
    replacement_product, replacement_campaign, replacement_search = _daily_frames(date="2026-06-09", clicks=99)

    with pytest.raises(Exception, match="simulated combined daily write failure"):
        db.import_raw_and_daily_frames(
            replacement_ads,
            replacement_erp,
            replacement_product,
            replacement_campaign,
            replacement_search,
        )

    with db._connect() as connection:
        raw_ads_rows = connection.execute(
            "SELECT date, clicks FROM ads_import_raw ORDER BY date"
        ).fetchall()
        raw_erp_rows = connection.execute(
            "SELECT date, total_orders FROM erp_import_raw ORDER BY date"
        ).fetchall()
        product_rows = connection.execute(
            "SELECT date, clicks FROM product_daily ORDER BY date"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT date, clicks FROM campaign_daily ORDER BY date"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT date, clicks FROM search_term_daily ORDER BY date"
        ).fetchall()

    assert raw_ads_rows == [("2026-06-08", 1.0)]
    assert raw_erp_rows == [("2026-06-08", 1.0)]
    assert product_rows == [("2026-06-08", 1.0)]
    assert campaign_rows == [("2026-06-08", 1.0)]
    assert search_rows == [("2026-06-08", 1.0)]


def test_raw_import_and_daily_upsert_roll_back_together_when_raw_write_fails(monkeypatch, tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "raw_daily_combined_raw_failure.sqlite")
    raw_ads, raw_erp = _raw_import_frames(date="2026-06-08", clicks=1)
    product_daily, campaign_daily, search_term_daily = _daily_frames(date="2026-06-08", clicks=1)
    db.import_raw_and_daily_frames(raw_ads, raw_erp, product_daily, campaign_daily, search_term_daily)

    replacement_ads, replacement_erp = _raw_import_frames(date="2026-06-09", clicks=99)
    replacement_product, replacement_campaign, replacement_search = _daily_frames(date="2026-06-09", clicks=99)
    original_upsert = db._upsert

    def fail_on_raw_erp(connection, table_name, frame, key_columns):
        if table_name == "erp_import_raw":
            raise RuntimeError("simulated combined raw erp write failure")
        return original_upsert(connection, table_name, frame, key_columns)

    monkeypatch.setattr(db, "_upsert", fail_on_raw_erp)

    with pytest.raises(RuntimeError, match="simulated combined raw erp write failure"):
        db.import_raw_and_daily_frames(
            replacement_ads,
            replacement_erp,
            replacement_product,
            replacement_campaign,
            replacement_search,
        )

    with db._connect() as connection:
        raw_ads_rows = connection.execute(
            "SELECT date, clicks FROM ads_import_raw ORDER BY date"
        ).fetchall()
        raw_erp_rows = connection.execute(
            "SELECT date, total_orders FROM erp_import_raw ORDER BY date"
        ).fetchall()
        product_rows = connection.execute(
            "SELECT date, clicks FROM product_daily ORDER BY date"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT date, clicks FROM campaign_daily ORDER BY date"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT date, clicks FROM search_term_daily ORDER BY date"
        ).fetchall()

    assert raw_ads_rows == [("2026-06-08", 1.0)]
    assert raw_erp_rows == [("2026-06-08", 1.0)]
    assert product_rows == [("2026-06-08", 1.0)]
    assert campaign_rows == [("2026-06-08", 1.0)]
    assert search_rows == [("2026-06-08", 1.0)]


def test_raw_import_and_daily_upsert_roll_back_together_when_commit_fails(monkeypatch, tmp_path) -> None:
    db = AnalyticsDatabase(tmp_path / "raw_daily_combined_commit_failure.sqlite")
    raw_ads, raw_erp = _raw_import_frames(date="2026-06-08", clicks=1)
    product_daily, campaign_daily, search_term_daily = _daily_frames(date="2026-06-08", clicks=1)
    db.import_raw_and_daily_frames(raw_ads, raw_erp, product_daily, campaign_daily, search_term_daily)

    class CommitFailConnection(sqlite3.Connection):
        def commit(self) -> None:
            raise sqlite3.OperationalError("simulated combined sqlite commit failure")

    def connect_with_failing_commit():
        return sqlite3.connect(db.db_path, factory=CommitFailConnection)

    replacement_ads, replacement_erp = _raw_import_frames(date="2026-06-09", clicks=99)
    replacement_product, replacement_campaign, replacement_search = _daily_frames(date="2026-06-09", clicks=99)
    monkeypatch.setattr(db, "_connect", connect_with_failing_commit)

    with pytest.raises(sqlite3.OperationalError, match="simulated combined sqlite commit failure"):
        db.import_raw_and_daily_frames(
            replacement_ads,
            replacement_erp,
            replacement_product,
            replacement_campaign,
            replacement_search,
        )

    with sqlite3.connect(db.db_path) as connection:
        raw_ads_rows = connection.execute(
            "SELECT date, clicks FROM ads_import_raw ORDER BY date"
        ).fetchall()
        raw_erp_rows = connection.execute(
            "SELECT date, total_orders FROM erp_import_raw ORDER BY date"
        ).fetchall()
        product_rows = connection.execute(
            "SELECT date, clicks FROM product_daily ORDER BY date"
        ).fetchall()
        campaign_rows = connection.execute(
            "SELECT date, clicks FROM campaign_daily ORDER BY date"
        ).fetchall()
        search_rows = connection.execute(
            "SELECT date, clicks FROM search_term_daily ORDER BY date"
        ).fetchall()

    assert raw_ads_rows == [("2026-06-08", 1.0)]
    assert raw_erp_rows == [("2026-06-08", 1.0)]
    assert product_rows == [("2026-06-08", 1.0)]
    assert campaign_rows == [("2026-06-08", 1.0)]
    assert search_rows == [("2026-06-08", 1.0)]
