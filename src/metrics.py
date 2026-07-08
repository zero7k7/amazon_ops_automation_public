from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from .normalize_fields import safe_divide

WINDOWS = [1, 3, 7, 14, 30]
METRIC_SUM_COLUMNS = [
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
    "total_orders",
    "total_sales",
    "natural_orders",
]
METRIC_FIRST_COLUMNS = [
    "sku",
    "product_name",
    "target_acos",
    "profit_before_ads_per_unit",
    "unit_cost",
    "shipping_cost",
    "handling_fee",
    "currency",
    "fba_stock",
    "fbm_stock",
    "available_stock",
    "ad_group_name",
    "targeting",
    "matched_target",
    "match_type",
]


def add_ratio_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    def spend_to_sales(row: pd.Series, sales_column: str) -> float | None:
        spend = float(row["spend"])
        sales = float(row[sales_column])
        if sales == 0 and spend > 0:
            return None
        return safe_divide(spend, sales)

    result["CTR"] = result.apply(lambda row: safe_divide(row["clicks"], row["impressions"]), axis=1)
    result["CPC"] = result.apply(lambda row: safe_divide(row["spend"], row["clicks"]), axis=1)
    result["CVR"] = result.apply(lambda row: safe_divide(row["ad_orders"], row["clicks"]), axis=1)
    result["ACOS"] = result.apply(lambda row: spend_to_sales(row, "ad_sales"), axis=1)
    result["TACOS"] = result.apply(lambda row: spend_to_sales(row, "total_sales"), axis=1)
    result["has_spend_no_sales"] = result.apply(lambda row: bool(float(row["spend"]) > 0 and float(row["ad_sales"]) == 0), axis=1)
    return result


def aggregate_with_metrics(df: pd.DataFrame, group_keys: list[str]) -> pd.DataFrame:
    if df.empty:
        return add_ratio_columns(pd.DataFrame(columns=[*group_keys, *METRIC_SUM_COLUMNS]))
    aggregations = {column: "sum" for column in METRIC_SUM_COLUMNS}
    for column in METRIC_FIRST_COLUMNS:
        if column in df.columns and column not in group_keys:
            aggregations[column] = "first"
    grouped = df.groupby(group_keys, dropna=False).agg(aggregations).reset_index()
    return add_ratio_columns(grouped)


@dataclass
class HistoricalViews:
    product_windows: dict[int, pd.DataFrame]
    campaign_windows: dict[int, pd.DataFrame]
    search_term_windows: dict[int, pd.DataFrame]
    product_history: pd.DataFrame
    search_term_history: pd.DataFrame
    data_days: int


def _window_slice(df: pd.DataFrame, report_date: date, days: int) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    start_date = report_date - timedelta(days=days - 1)
    return df[(df["date"] >= start_date) & (df["date"] <= report_date)].copy()


def _window_map(df: pd.DataFrame, report_date: date, group_keys: list[str]) -> dict[int, pd.DataFrame]:
    views: dict[int, pd.DataFrame] = {}
    for days in WINDOWS:
        views[days] = aggregate_with_metrics(_window_slice(df, report_date, days), group_keys)
        views[days]["window_days"] = days
    return views


def _overlay_current_history(history_df: pd.DataFrame, current_df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if current_df.empty:
        return history_df.copy()
    if history_df.empty:
        return current_df.copy()
    subset = ["date", *keys]
    history = history_df.copy()
    current = current_df.copy()
    for frame in [history, current]:
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
    current_keys = current[subset].drop_duplicates()
    kept_history = history.merge(current_keys.assign(_current_row=True), on=subset, how="left")
    kept_history = kept_history[kept_history["_current_row"].isna()].drop(columns=["_current_row"])
    combined = pd.concat([kept_history, current], ignore_index=True, sort=False)
    return combined


def build_windowed_views(
    report_date: date,
    current_product_daily: pd.DataFrame,
    current_campaign_daily: pd.DataFrame,
    current_search_term_daily: pd.DataFrame,
    history: dict[str, pd.DataFrame],
) -> HistoricalViews:
    product_history = _overlay_current_history(history["product_daily"].copy(), current_product_daily, ["marketplace", "sku", "asin"])
    campaign_history = _overlay_current_history(history["campaign_daily"].copy(), current_campaign_daily, ["marketplace", "campaign_name", "sku", "asin"])
    search_term_history = _overlay_current_history(history["search_term_daily"].copy(), current_search_term_daily, ["marketplace", "search_term", "campaign_name", "sku", "asin"])

    product_views = _window_map(product_history, report_date, ["marketplace", "sku", "asin"])
    campaign_views = _window_map(campaign_history, report_date, ["marketplace", "campaign_name", "sku", "asin", "product_name"])
    search_term_views = _window_map(search_term_history, report_date, ["marketplace", "search_term", "campaign_name", "sku", "asin", "product_name"])
    data_days = int(product_history["date"].nunique()) if not product_history.empty else 0
    return HistoricalViews(
        product_windows=product_views,
        campaign_windows=campaign_views,
        search_term_windows=search_term_views,
        product_history=product_history,
        search_term_history=search_term_history,
        data_days=data_days,
    )
