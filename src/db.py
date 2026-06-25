from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from pandas.api.types import is_number


class AnalyticsDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            for table_name, required_columns in {
                "product_daily": {"marketplace", "sku", "asin"},
                "campaign_daily": {"marketplace", "campaign_name", "sku", "asin"},
                "search_term_daily": {"marketplace", "search_term", "campaign_name", "sku", "asin"},
            }.items():
                if self._needs_reset(connection, table_name, required_columns):
                    connection.execute(f"DROP TABLE IF EXISTS {table_name}")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ads_import_raw (
                    marketplace TEXT NOT NULL,
                    date TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    ad_group_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    asin TEXT NOT NULL,
                    search_term TEXT NOT NULL,
                    targeting TEXT NOT NULL,
                    campaign_name TEXT,
                    ad_group_name TEXT,
                    match_type TEXT,
                    impressions REAL,
                    clicks REAL,
                    spend REAL,
                    ad_orders REAL,
                    ad_sales REAL,
                    click_orders REAL,
                    click_sales REAL,
                    click_roas REAL,
                    click_cpa REAL,
                    promoted_click_orders REAL,
                    promoted_click_sales REAL,
                    promoted_ad_orders REAL,
                    promoted_ad_sales REAL,
                    halo_click_orders REAL,
                    halo_click_sales REAL,
                    halo_click_units REAL,
                    halo_ad_orders REAL,
                    halo_ad_sales REAL,
                    halo_ad_units REAL,
                    source_file TEXT,
                    archive_file TEXT,
                    raw_modified_at TEXT,
                    imported_at TEXT,
                    PRIMARY KEY (marketplace, date, campaign_id, ad_group_id, sku, asin, search_term, targeting)
                );
                CREATE TABLE IF NOT EXISTS erp_import_raw (
                    marketplace TEXT NOT NULL,
                    date TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    asin TEXT NOT NULL,
                    product_name TEXT,
                    total_orders REAL,
                    total_sales REAL,
                    fba_stock REAL,
                    fbm_stock REAL,
                    available_stock REAL,
                    source_file TEXT,
                    archive_file TEXT,
                    raw_modified_at TEXT,
                    imported_at TEXT,
                    PRIMARY KEY (marketplace, date, sku, asin)
                );
                CREATE TABLE IF NOT EXISTS product_daily (
                    date TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    asin TEXT NOT NULL,
                    product_name TEXT,
                    impressions REAL,
                    clicks REAL,
                    spend REAL,
                    ad_orders REAL,
                    ad_sales REAL,
                    click_orders REAL,
                    click_sales REAL,
                    promoted_ad_orders REAL,
                    promoted_ad_sales REAL,
                    halo_ad_orders REAL,
                    halo_ad_sales REAL,
                    halo_ad_units REAL,
                    total_orders REAL,
                    total_sales REAL,
                    natural_orders REAL,
                    CTR REAL,
                    CPC REAL,
                    CVR REAL,
                    ACOS REAL,
                    TACOS REAL,
                    has_spend_no_sales INTEGER,
                    owner TEXT,
                    category TEXT,
                    currency TEXT,
                    unit_cost REAL,
                    shipping_cost REAL,
                    handling_fee REAL,
                    target_acos REAL,
                    profit_before_ads_per_unit REAL,
                    fba_stock REAL,
                    fbm_stock REAL,
                    available_stock REAL,
                    PRIMARY KEY (date, marketplace, sku, asin)
                );
                CREATE TABLE IF NOT EXISTS campaign_daily (
                    date TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    campaign_name TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    asin TEXT NOT NULL,
                    product_name TEXT,
                    ad_group_name TEXT,
                    targeting TEXT,
                    matched_target TEXT,
                    match_type TEXT,
                    impressions REAL,
                    clicks REAL,
                    spend REAL,
                    ad_orders REAL,
                    ad_sales REAL,
                    click_orders REAL,
                    click_sales REAL,
                    promoted_ad_orders REAL,
                    promoted_ad_sales REAL,
                    halo_ad_orders REAL,
                    halo_ad_sales REAL,
                    halo_ad_units REAL,
                    total_orders REAL,
                    total_sales REAL,
                    natural_orders REAL,
                    CTR REAL,
                    CPC REAL,
                    CVR REAL,
                    ACOS REAL,
                    TACOS REAL,
                    has_spend_no_sales INTEGER,
                    PRIMARY KEY (date, marketplace, campaign_name, sku, asin)
                );
                CREATE TABLE IF NOT EXISTS search_term_daily (
                    date TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    search_term TEXT NOT NULL,
                    campaign_name TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    asin TEXT NOT NULL,
                    product_name TEXT,
                    impressions REAL,
                    clicks REAL,
                    spend REAL,
                    ad_orders REAL,
                    ad_sales REAL,
                    click_orders REAL,
                    click_sales REAL,
                    promoted_ad_orders REAL,
                    promoted_ad_sales REAL,
                    halo_ad_orders REAL,
                    halo_ad_sales REAL,
                    halo_ad_units REAL,
                    total_orders REAL,
                    total_sales REAL,
                    natural_orders REAL,
                    CTR REAL,
                    CPC REAL,
                    CVR REAL,
                    ACOS REAL,
                    TACOS REAL,
                    has_spend_no_sales INTEGER,
                    PRIMARY KEY (date, marketplace, search_term, campaign_name, sku, asin)
                );
                """
            )
            self._ensure_column(connection, "product_daily", "has_spend_no_sales", "INTEGER")
            self._ensure_column(connection, "product_daily", "target_acos", "REAL")
            self._ensure_column(connection, "product_daily", "profit_before_ads_per_unit", "REAL")
            self._ensure_column(connection, "product_daily", "fba_stock", "REAL")
            self._ensure_column(connection, "product_daily", "fbm_stock", "REAL")
            self._ensure_column(connection, "product_daily", "available_stock", "REAL")
            self._ensure_column(connection, "erp_import_raw", "fba_stock", "REAL")
            self._ensure_column(connection, "erp_import_raw", "fbm_stock", "REAL")
            self._ensure_column(connection, "erp_import_raw", "available_stock", "REAL")
            self._ensure_column(connection, "campaign_daily", "has_spend_no_sales", "INTEGER")
            self._ensure_column(connection, "search_term_daily", "has_spend_no_sales", "INTEGER")
            attribution_columns = {
                "ads_import_raw": [
                    "click_orders",
                    "click_sales",
                    "click_roas",
                    "click_cpa",
                    "promoted_click_orders",
                    "promoted_click_sales",
                    "promoted_ad_orders",
                    "promoted_ad_sales",
                    "halo_click_orders",
                    "halo_click_sales",
                    "halo_click_units",
                    "halo_ad_orders",
                    "halo_ad_sales",
                    "halo_ad_units",
                ],
                "product_daily": [
                    "click_orders",
                    "click_sales",
                    "promoted_ad_orders",
                    "promoted_ad_sales",
                    "halo_ad_orders",
                    "halo_ad_sales",
                    "halo_ad_units",
                ],
                "campaign_daily": [
                    "click_orders",
                    "click_sales",
                    "promoted_ad_orders",
                    "promoted_ad_sales",
                    "halo_ad_orders",
                    "halo_ad_sales",
                    "halo_ad_units",
                ],
                "search_term_daily": [
                    "click_orders",
                    "click_sales",
                    "promoted_ad_orders",
                    "promoted_ad_sales",
                    "halo_ad_orders",
                    "halo_ad_sales",
                    "halo_ad_units",
                ],
            }
            for table_name, columns in attribution_columns.items():
                for column in columns:
                    self._ensure_column(connection, table_name, column, "REAL")
            for column in ["ad_group_name", "targeting", "matched_target", "match_type"]:
                self._ensure_column(connection, "search_term_daily", column, "TEXT")
            connection.commit()

    def _needs_reset(self, connection: sqlite3.Connection, table_name: str, required_columns: set[str]) -> bool:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            [table_name],
        ).fetchall()
        if not rows:
            return False
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        return not required_columns.issubset(columns)

    def _ensure_column(self, connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _upsert(self, connection: sqlite3.Connection, table_name: str, frame: pd.DataFrame, key_columns: list[str]) -> None:
        if frame.empty:
            return
        export = frame.copy()
        export["date"] = export["date"].astype(str)
        columns = list(export.columns)
        placeholders = ", ".join(["?"] * len(columns))
        update_columns = [column for column in columns if column not in key_columns]
        update_clause = ", ".join([f"{column}=excluded.{column}" for column in update_columns])
        sql = f"""
            INSERT INTO {table_name} ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT ({", ".join(key_columns)}) DO UPDATE SET
            {update_clause}
        """
        connection.executemany(sql, export.itertuples(index=False, name=None))

    def _load_existing_subset(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        dates = sorted({str(value) for value in frame["date"].astype(str).tolist()})
        marketplaces = sorted({str(value) for value in frame["marketplace"].astype(str).tolist()})
        date_placeholders = ", ".join(["?"] * len(dates))
        marketplace_placeholders = ", ".join(["?"] * len(marketplaces))
        query = (
            f"SELECT * FROM {table_name} "
            f"WHERE date IN ({date_placeholders}) AND marketplace IN ({marketplace_placeholders})"
        )
        return pd.read_sql_query(query, connection, params=[*dates, *marketplaces])

    def _classify_raw_import(
        self,
        incoming: pd.DataFrame,
        existing: pd.DataFrame,
        key_columns: list[str],
        compare_columns: list[str],
    ) -> tuple[pd.DataFrame, int, int, int]:
        if incoming.empty:
            return incoming.copy(), 0, 0, 0
        incoming_work = incoming.copy()
        existing_work = existing.copy()
        if "date" in incoming_work.columns:
            incoming_work["date"] = incoming_work["date"].astype(str)
        if "date" in existing_work.columns:
            existing_work["date"] = existing_work["date"].astype(str)
        for frame in [incoming_work, existing_work]:
            for column in key_columns + compare_columns:
                if column not in frame.columns:
                    frame[column] = ""
        merged = incoming_work.merge(
            existing_work[key_columns + compare_columns],
            on=key_columns,
            how="left",
            suffixes=("", "_existing"),
        )
        upsert_mask = []
        new_count = 0
        duplicate_count = 0
        update_count = 0
        for _, row in merged.iterrows():
            has_existing = any(not pd.isna(row.get(f"{column}_existing")) for column in compare_columns)
            if not has_existing:
                upsert_mask.append(True)
                new_count += 1
                continue
            changed = False
            for column in compare_columns:
                left = row.get(column)
                right = row.get(f"{column}_existing")
                if self._values_equal(left, right):
                    continue
                changed = True
                break
            if changed:
                upsert_mask.append(True)
                update_count += 1
            else:
                upsert_mask.append(False)
                duplicate_count += 1
        export = merged.loc[upsert_mask, incoming.columns].copy()
        return export, new_count, duplicate_count, update_count

    def _values_equal(self, left, right) -> bool:
        if pd.isna(left) and pd.isna(right):
            return True
        if pd.isna(left) or pd.isna(right):
            return False
        if is_number(left) and is_number(right):
            return float(left) == float(right)
        if str(left).strip() == str(right).strip():
            return True
        return False

    def import_raw_frames(
        self,
        ads_raw: pd.DataFrame,
        erp_raw: pd.DataFrame,
    ) -> dict[str, int]:
        stats = {
            "ads_imported_rows": len(ads_raw),
            "erp_imported_rows": len(erp_raw),
            "added_rows": 0,
            "duplicate_skipped_rows": 0,
            "overwrite_updated_rows": 0,
            "ads_added_rows": 0,
            "ads_duplicate_skipped_rows": 0,
            "ads_overwrite_updated_rows": 0,
            "erp_added_rows": 0,
            "erp_duplicate_skipped_rows": 0,
            "erp_overwrite_updated_rows": 0,
        }
        with self._connect() as connection:
            ads_existing = self._load_existing_subset(connection, "ads_import_raw", ads_raw)
            ads_export, ads_new, ads_dup, ads_update = self._classify_raw_import(
                incoming=ads_raw,
                existing=ads_existing,
                key_columns=["marketplace", "date", "campaign_id", "ad_group_id", "sku", "asin", "search_term", "targeting"],
                compare_columns=[
                    "campaign_name",
                    "ad_group_name",
                    "match_type",
                    "impressions",
                    "clicks",
                    "spend",
                    "ad_orders",
                    "ad_sales",
                    "click_orders",
                    "click_sales",
                    "promoted_ad_orders",
                    "promoted_ad_sales",
                    "halo_ad_orders",
                    "halo_ad_sales",
                    "halo_ad_units",
                ],
            )
            self._upsert(
                connection,
                "ads_import_raw",
                ads_export,
                ["marketplace", "date", "campaign_id", "ad_group_id", "sku", "asin", "search_term", "targeting"],
            )

            erp_existing = self._load_existing_subset(connection, "erp_import_raw", erp_raw)
            erp_export, erp_new, erp_dup, erp_update = self._classify_raw_import(
                incoming=erp_raw,
                existing=erp_existing,
                key_columns=["marketplace", "date", "sku", "asin"],
                compare_columns=["product_name", "total_orders", "total_sales", "fba_stock", "fbm_stock", "available_stock"],
            )
            self._upsert(
                connection,
                "erp_import_raw",
                erp_export,
                ["marketplace", "date", "sku", "asin"],
            )
            connection.commit()

        stats["ads_added_rows"] = ads_new
        stats["ads_duplicate_skipped_rows"] = ads_dup
        stats["ads_overwrite_updated_rows"] = ads_update
        stats["erp_added_rows"] = erp_new
        stats["erp_duplicate_skipped_rows"] = erp_dup
        stats["erp_overwrite_updated_rows"] = erp_update
        stats["added_rows"] = ads_new + erp_new
        stats["duplicate_skipped_rows"] = ads_dup + erp_dup
        stats["overwrite_updated_rows"] = ads_update + erp_update
        return stats

    def _delete_existing_scope(self, connection: sqlite3.Connection, table_name: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        date_values = sorted({str(value) for value in frame["date"].astype(str).tolist()})
        marketplace_values = sorted({str(value) for value in frame["marketplace"].astype(str).tolist()})
        for date_value in date_values:
            for marketplace_value in marketplace_values:
                connection.execute(
                    f"DELETE FROM {table_name} WHERE date = ? AND marketplace = ?",
                    [date_value, marketplace_value],
                )

    def upsert_daily_frames(self, product_daily: pd.DataFrame, campaign_daily: pd.DataFrame, search_term_daily: pd.DataFrame) -> None:
        with self._connect() as connection:
            self._delete_existing_scope(connection, "product_daily", product_daily)
            self._delete_existing_scope(connection, "campaign_daily", campaign_daily)
            self._delete_existing_scope(connection, "search_term_daily", search_term_daily)
            self._upsert(connection, "product_daily", product_daily, ["date", "marketplace", "sku", "asin"])
            self._upsert(connection, "campaign_daily", campaign_daily, ["date", "marketplace", "campaign_name", "sku", "asin"])
            self._upsert(connection, "search_term_daily", search_term_daily, ["date", "marketplace", "search_term", "campaign_name", "sku", "asin"])
            connection.commit()

    def load_history(self, as_of_date, marketplace: str | None = None) -> dict[str, pd.DataFrame]:
        query_date = str(as_of_date)
        clause = ""
        params: list[object] = [query_date]
        if marketplace:
            clause = " AND marketplace = ?"
            params.append(marketplace)
        with self._connect() as connection:
            product_daily = pd.read_sql_query(f"SELECT * FROM product_daily WHERE date <= ?{clause}", connection, params=params)
            campaign_daily = pd.read_sql_query(f"SELECT * FROM campaign_daily WHERE date <= ?{clause}", connection, params=params)
            search_term_daily = pd.read_sql_query(f"SELECT * FROM search_term_daily WHERE date <= ?{clause}", connection, params=params)
        for frame in [product_daily, campaign_daily, search_term_daily]:
            if not frame.empty:
                frame["date"] = pd.to_datetime(frame["date"]).dt.date
        return {
            "product_daily": product_daily,
            "campaign_daily": campaign_daily,
            "search_term_daily": search_term_daily,
        }
