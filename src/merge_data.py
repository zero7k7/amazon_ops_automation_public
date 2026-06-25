from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .build_sku_asin_map import read_cost_config_sheet
from .metrics import add_ratio_columns
from .normalize_fields import FieldValidationError, coerce_text, normalize_column_names, rename_with_synonyms, require_columns

MAP_SYNONYMS = {
    "marketplace": ["site", "country", "store"],
    "sku": ["seller_sku"],
    "asin": ["child_asin"],
    "product_name": ["item_name", "title"],
    "currency": ["curr", "money_code"],
}

PRODUCT_CONFIG_SYNONYMS = {
    "marketplace": ["site", "country", "store"],
    "sku": ["seller_sku"],
    "asin": ["child_asin"],
    "owner": ["manager"],
    "category": ["product_line"],
}

COST_CONFIG_SYNONYMS = {
    "marketplace": ["site", "country", "store"],
    "sku": ["seller_sku"],
    "asin": ["child_asin"],
    "product_name": ["item_name", "title"],
    "currency": ["curr", "money_code"],
    "unit_cost": ["cost", "product_cost", "purchase_cost_local"],
    "shipping_cost": ["freight_cost", "ship_cost", "first_leg_cost_local"],
    "purchase_cost": ["purchase_cost_local", "unit_cost"],
    "first_leg_cost": ["first_leg_cost_local", "shipping_cost"],
    "handling_fee": ["packaging_cost", "other_cost", "packaging_cost_local_input"],
    "target_acos": ["suggested_target_acos", "target_acos"],
    "profit_before_ads_per_unit": ["profit_before_ads"],
}

TRIPLE_KEYS = ["marketplace", "sku", "asin"]
ALIAS_KEYS = ["marketplace", "source_sku", "asin"]
IGNORE_KEYS = ["marketplace", "asin"]
AD_METRIC_COLUMNS = [
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
]
SEARCH_TERM_SOURCE_COLUMNS = ["ad_group_name", "targeting", "matched_target", "match_type"]


@dataclass
class DailyDataset:
    report_date: object
    ads_date_range: tuple[object | None, object | None]
    erp_date_range: tuple[object | None, object | None]
    erp_observed_sales_date_range: tuple[object | None, object | None]
    erp_report_coverage_date_range: tuple[object | None, object | None]
    erp_zero_filled_days: int
    erp_last_sales_date: object | None
    zero_fill_applied: bool
    coverage_warning: str
    common_date_range: tuple[object | None, object | None]
    history_days: int
    product_daily: pd.DataFrame
    campaign_daily: pd.DataFrame
    search_term_daily: pd.DataFrame
    mapping_check: pd.DataFrame
    validation_messages: list[str]


def _load_excel(path: Path, synonyms: dict[str, list[str]], required: list[str], name: str) -> pd.DataFrame:
    if not path.exists():
        if required in (["sku"], TRIPLE_KEYS):
            return pd.DataFrame(columns=required)
        raise FileNotFoundError(f"缺少配置文件: {path}")
    frame = pd.read_excel(path)
    frame = normalize_column_names(frame)
    frame = rename_with_synonyms(frame, synonyms)
    require_columns(frame, required, source_name=name)
    return coerce_text(frame, frame.columns.tolist())


def _normalize_map(path: Path) -> pd.DataFrame:
    frame = _load_excel(path, MAP_SYNONYMS, ["marketplace", "sku", "asin", "product_name", "currency"], path.name)
    return frame.drop_duplicates(subset=TRIPLE_KEYS, keep="first").reset_index(drop=True)


def _normalize_product_config(path: Path) -> pd.DataFrame:
    frame = _load_excel(path, PRODUCT_CONFIG_SYNONYMS, ["sku"], path.name)
    if frame.empty:
        return frame
    if "marketplace" not in frame.columns:
        frame["marketplace"] = ""
    if "asin" not in frame.columns:
        frame["asin"] = ""
    keep = [column for column in ["marketplace", "sku", "asin", "owner", "category"] if column in frame.columns]
    return frame[keep].drop_duplicates(subset=[col for col in ["marketplace", "sku", "asin"] if col in keep], keep="first")


def _normalize_cost_config(path: Path) -> pd.DataFrame:
    frame = read_cost_config_sheet(path)
    frame = rename_with_synonyms(frame, COST_CONFIG_SYNONYMS)
    inventory_frame = pd.DataFrame()
    try:
        xls = pd.ExcelFile(path)
        if "SKU匹配检查" in xls.sheet_names:
            inventory_frame = pd.read_excel(xls, sheet_name="SKU匹配检查")
            inventory_frame = normalize_column_names(inventory_frame)
            inventory_frame = rename_with_synonyms(
                inventory_frame,
                {
                    "marketplace": ["site", "country", "store"],
                    "sku": ["seller_sku"],
                    "asin": ["child_asin"],
                },
            )
    except Exception:
        inventory_frame = pd.DataFrame()

    keep = [
        column
        for column in [
            "marketplace",
            "sku",
            "asin",
            "product_name",
            "currency",
            "unit_cost",
            "shipping_cost",
            "handling_fee",
            "target_acos",
            "profit_before_ads_per_unit",
        ]
        if column in frame.columns
    ]
    frame = frame[keep].copy()
    for column in keep:
        frame[column] = frame[column].fillna("").astype(str).str.strip() if frame[column].dtype == object else frame[column]
    if not inventory_frame.empty:
        inventory_keep = [column for column in ["marketplace", "sku", "asin", "current_inventory", "sea_inventory", "inventory_note"] if column in inventory_frame.columns]
        if inventory_keep:
            inventory_frame = inventory_frame[inventory_keep].copy()
            for column in inventory_keep:
                inventory_frame[column] = inventory_frame[column].fillna("").astype(str).str.strip() if inventory_frame[column].dtype == object else inventory_frame[column]
            frame = frame.merge(inventory_frame.drop_duplicates(subset=TRIPLE_KEYS, keep="first"), on=TRIPLE_KEYS, how="left", suffixes=("", "_inventory"))
            for column in ["current_inventory", "sea_inventory", "inventory_note"]:
                inventory_column = f"{column}_inventory"
                if inventory_column in frame.columns:
                    frame[column] = frame[column].where(frame[column].astype(str).str.strip() != "", frame[inventory_column])
                    frame.drop(columns=[inventory_column], inplace=True)
    return frame.drop_duplicates(subset=TRIPLE_KEYS, keep="first").reset_index(drop=True)


def _normalize_alias_map(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["marketplace", "source_sku", "canonical_sku", "asin", "reason"])
    frame = pd.read_excel(path)
    for column in ["marketplace", "source_sku", "canonical_sku", "asin", "reason"]:
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    return frame[["marketplace", "source_sku", "canonical_sku", "asin", "reason"]].drop_duplicates(subset=ALIAS_KEYS, keep="last")


def _normalize_ignored_issues(path: Path | None) -> pd.DataFrame:
    if not path or not path.exists():
        return pd.DataFrame(columns=["marketplace", "asin", "reason"])
    frame = pd.read_excel(path)
    for column in ["marketplace", "asin", "reason"]:
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    frame = frame[(frame["marketplace"] != "") & (frame["asin"] != "")]
    return frame[["marketplace", "asin", "reason"]].drop_duplicates(subset=IGNORE_KEYS, keep="last")


def _apply_ignored_issues(mapping_check: pd.DataFrame, ignored_issues: pd.DataFrame) -> pd.DataFrame:
    if mapping_check.empty or ignored_issues.empty:
        return mapping_check.copy()
    working = mapping_check.copy()
    for column in ["marketplace", "asin"]:
        working[column] = working[column].fillna("").astype(str).str.strip()
    ignored_keys = {
        (row["marketplace"], row["asin"])
        for _, row in ignored_issues.iterrows()
    }
    keep_mask = ~working.apply(lambda row: (row["marketplace"], row["asin"]) in ignored_keys, axis=1)
    return working[keep_mask].reset_index(drop=True)


def _filter_marketplace(frame: pd.DataFrame, marketplace: str | None) -> pd.DataFrame:
    if not marketplace:
        return frame.copy()
    return frame[frame["marketplace"].astype(str).str.upper() == marketplace.upper()].copy()


def _date_range_values(start: object, end: object) -> list[object]:
    if start is None or end is None or start > end:
        return []
    return pd.date_range(start=start, end=end, freq="D").date.tolist()


def _cross_join_dates(keys: pd.DataFrame, start: object, end: object) -> pd.DataFrame:
    dates = _date_range_values(start, end)
    if keys.empty or not dates:
        return pd.DataFrame(columns=["date", *keys.columns.tolist()])
    date_frame = pd.DataFrame({"date": dates})
    return date_frame.assign(_join_key=1).merge(keys.assign(_join_key=1), on="_join_key").drop(columns=["_join_key"])


def _apply_alias_map(frame: pd.DataFrame, alias_map: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or alias_map.empty:
        return frame.copy()
    working = frame.copy()
    working["source_sku"] = working["sku"].astype(str)
    working = working.merge(alias_map[["marketplace", "source_sku", "asin", "canonical_sku"]], on=["marketplace", "source_sku", "asin"], how="left")
    working["sku"] = working["canonical_sku"].where(working["canonical_sku"].astype(str).str.strip() != "", working["sku"])
    return working.drop(columns=["canonical_sku"])


def _backfill_missing_sku_from_asin(frame: pd.DataFrame, sku_map: pd.DataFrame, cost_config: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    reference = pd.concat(
        [
            sku_map[["marketplace", "sku", "asin", "product_name"]],
            cost_config[["marketplace", "sku", "asin", "product_name"]],
        ],
        ignore_index=True,
    ).copy()
    for column in ["marketplace", "sku", "asin", "product_name"]:
        reference[column] = reference[column].fillna("").astype(str).str.strip()
    reference = reference[(reference["marketplace"] != "") & (reference["asin"] != "") & (reference["sku"] != "")]
    unique_asin_reference = (
        reference.drop_duplicates(subset=["marketplace", "sku", "asin"])
        .groupby(["marketplace", "asin"], as_index=False)
        .filter(lambda group: group["sku"].nunique() == 1)
        .drop_duplicates(subset=["marketplace", "asin"], keep="first")
        [["marketplace", "asin", "sku", "product_name"]]
        .rename(columns={"sku": "resolved_sku", "product_name": "resolved_product_name"})
    )

    working = frame.copy()
    for column in ["marketplace", "sku", "asin"]:
        working[column] = working[column].fillna("").astype(str).str.strip()
    if "product_name" in working.columns:
        working["product_name"] = working["product_name"].fillna("").astype(str).str.strip()
    else:
        working["product_name"] = ""

    working = working.merge(unique_asin_reference, on=["marketplace", "asin"], how="left")
    missing_sku_mask = working["sku"] == ""
    working.loc[missing_sku_mask, "sku"] = working.loc[missing_sku_mask, "resolved_sku"].fillna("").astype(str).str.strip()
    missing_name_mask = working["product_name"] == ""
    working.loc[missing_name_mask, "product_name"] = working.loc[missing_name_mask, "resolved_product_name"].fillna("").astype(str).str.strip()
    return working.drop(columns=["resolved_sku", "resolved_product_name"])


def _build_mapping_check(ads_df: pd.DataFrame, erp_df: pd.DataFrame, sku_map: pd.DataFrame, cost_config: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat(
        [
            ads_df[["marketplace", "sku", "asin"]].assign(source="ads"),
            erp_df[["marketplace", "sku", "asin"]].assign(source="erp"),
        ],
        ignore_index=True,
    )
    combined["marketplace"] = combined["marketplace"].fillna("").astype(str).str.strip()
    combined["sku"] = combined["sku"].fillna("").astype(str).str.strip()
    combined["asin"] = combined["asin"].fillna("").astype(str).str.strip()
    grouped = combined.groupby(TRIPLE_KEYS, dropna=False)["source"].agg(lambda values: ",".join(sorted(set(values)))).reset_index()

    map_joined = grouped.merge(sku_map[TRIPLE_KEYS + ["product_name"]], on=TRIPLE_KEYS, how="left")
    cost_columns = TRIPLE_KEYS + ["product_name"]
    for extra_column in ["current_inventory", "sea_inventory", "inventory_note"]:
        if extra_column in cost_config.columns:
            cost_columns.append(extra_column)
    cost_joined = map_joined.merge(
        cost_config[cost_columns].rename(columns={"product_name": "cost_product_name"}),
        on=TRIPLE_KEYS,
        how="left",
    )

    def classify(row: pd.Series) -> tuple[str, str]:
        marketplace = "" if pd.isna(row["marketplace"]) else str(row["marketplace"]).strip()
        sku = "" if pd.isna(row["sku"]) else str(row["sku"]).strip()
        asin = "" if pd.isna(row["asin"]) else str(row["asin"]).strip()
        product_name = "" if pd.isna(row.get("product_name", "")) else str(row.get("product_name", "")).strip()
        cost_product_name = "" if pd.isna(row.get("cost_product_name", "")) else str(row.get("cost_product_name", "")).strip()
        has_map = product_name != ""
        has_cost = cost_product_name != ""
        if not marketplace:
            return "missing_marketplace", "marketplace 为空"
        if not sku:
            return "missing_sku", "sku 为空"
        if not asin:
            return "missing_asin", "asin 为空"
        if not has_map:
            return "missing_sku_asin_map", "sku_asin_map 中找不到 marketplace + sku + asin"
        if not has_cost:
            return "missing_cost_config", "product_cost_config 中找不到 marketplace + sku + asin"
        return "matched", ""

    statuses = cost_joined.apply(classify, axis=1, result_type="expand")
    cost_joined["mapping_status"] = statuses[0]
    cost_joined["reason"] = statuses[1]
    cost_joined["product_name"] = cost_joined["product_name"].where(cost_joined["product_name"].notna() & (cost_joined["product_name"].astype(str).str.strip() != ""), cost_joined["cost_product_name"])
    output_columns = ["marketplace", "sku", "asin", "product_name", "source", "mapping_status", "reason"]
    for extra_column in ["current_inventory", "sea_inventory", "inventory_note"]:
        if extra_column in cost_joined.columns:
            output_columns.append(extra_column)
    return cost_joined[output_columns]


def build_daily_dataset(
    ads_df: pd.DataFrame,
    erp_df: pd.DataFrame,
    sku_map_path: Path,
    product_config_path: Path,
    cost_config_path: Path,
    alias_map_path: Path | None = None,
    ignored_issues_path: Path | None = None,
    target_marketplace: str | None = None,
) -> DailyDataset:
    sku_map = _normalize_map(sku_map_path)
    product_config = _normalize_product_config(product_config_path)
    cost_config = _normalize_cost_config(cost_config_path)
    alias_map = _normalize_alias_map(alias_map_path) if alias_map_path else pd.DataFrame(columns=["marketplace", "source_sku", "canonical_sku", "asin", "reason"])
    ignored_issues = _normalize_ignored_issues(ignored_issues_path)

    global_ads_dates = sorted(ads_df["date"].dropna().unique()) if "date" in ads_df.columns else []
    global_erp_dates = sorted(erp_df["date"].dropna().unique()) if "date" in erp_df.columns else []
    global_ads_min_date = global_ads_dates[0] if global_ads_dates else None
    global_ads_max_date = global_ads_dates[-1] if global_ads_dates else None
    global_erp_min_date = global_erp_dates[0] if global_erp_dates else None
    global_erp_max_date = global_erp_dates[-1] if global_erp_dates else None

    ads_df = _filter_marketplace(ads_df, target_marketplace)
    erp_df = _filter_marketplace(erp_df, target_marketplace)
    ads_df = _apply_alias_map(ads_df, alias_map)
    erp_df = _apply_alias_map(erp_df, alias_map)
    ads_df = _backfill_missing_sku_from_asin(ads_df, sku_map, cost_config)
    erp_df = _backfill_missing_sku_from_asin(erp_df, sku_map, cost_config)

    ads_dates = sorted(ads_df["date"].dropna().unique())
    erp_dates = sorted(erp_df["date"].dropna().unique())
    if not ads_dates:
        raise FieldValidationError("广告报表没有可用日期，无法分析")
    ads_min_date, ads_max_date = ads_dates[0], ads_dates[-1]
    erp_observed_min_date = erp_dates[0] if erp_dates else None
    erp_observed_max_date = erp_dates[-1] if erp_dates else None
    coverage_start = ads_min_date or global_ads_min_date or global_erp_min_date
    coverage_end = ads_max_date or global_ads_max_date or global_erp_max_date
    if coverage_start is None or coverage_end is None:
        raise FieldValidationError("ERP 报表覆盖范围无法确认，无法分析")
    common_start = max(ads_min_date, coverage_start)
    common_end = min(ads_max_date, coverage_end)
    if common_start > common_end:
        raise FieldValidationError(
            "广告报表与 ERP 报表没有共同日期区间，"
            f"广告日期范围: {ads_min_date} ~ {ads_max_date}; ERP 报表覆盖范围: {coverage_start} ~ {coverage_end}"
        )
    report_date = common_end
    history_days = (common_end - common_start).days + 1
    erp_observed_dates_in_common = {
        value for value in erp_dates if common_start <= value <= common_end
    }
    common_dates = _date_range_values(common_start, common_end)
    zero_fill_applied = len(erp_observed_dates_in_common) < len(common_dates)
    erp_zero_filled_days = max((common_end - erp_observed_max_date).days, 0) if erp_observed_max_date else len(common_dates)
    if erp_observed_max_date and erp_observed_max_date < common_end:
        coverage_warning = f"{erp_observed_max_date + pd.Timedelta(days=1)} ~ {common_end} 无销量行，已按 0 单补齐"
    elif not erp_observed_max_date:
        coverage_warning = f"{common_start} ~ {common_end} 无销量行，已按 0 单补齐"
    else:
        coverage_warning = ""

    validation_messages = list(ads_df.attrs.get("validation_messages", []))
    validation_messages.extend(erp_df.attrs.get("validation_messages", []))
    if ads_min_date != coverage_start or ads_max_date != coverage_end:
        validation_messages.append(f"广告报表与 ERP 覆盖范围不完全一致，已使用最新共同日期区间 {common_start} ~ {common_end}")
    # ERP exports omit dates with zero orders. Missing sales rows inside a confirmed
    # report window are expected and are tracked via coverage_warning, not as a data
    # quality error.

    ads_df = ads_df[(ads_df["date"] >= common_start) & (ads_df["date"] <= common_end)].copy()
    erp_df = erp_df[(erp_df["date"] >= common_start) & (erp_df["date"] <= common_end)].copy()

    mapping_check = _build_mapping_check(ads_df, erp_df, sku_map, cost_config)
    mapping_check = _apply_ignored_issues(mapping_check, ignored_issues)
    missing_count = int((mapping_check["mapping_status"] != "matched").sum())
    if missing_count:
        validation_messages.append(f"存在 {missing_count} 条 marketplace + sku + asin 数据质量问题")

    matched_triples = mapping_check[mapping_check["mapping_status"] == "matched"][TRIPLE_KEYS].drop_duplicates()
    ads_usable = ads_df.merge(matched_triples, on=TRIPLE_KEYS, how="inner")
    erp_usable = erp_df.merge(matched_triples, on=TRIPLE_KEYS, how="inner")
    if ads_usable.empty and erp_usable.empty:
        scope = target_marketplace if target_marketplace else "全部 marketplace"
        raise FieldValidationError(f"未找到 {scope} 的可分析数据，请检查 marketplace + sku + asin 映射")

    ads_enriched = ads_usable.merge(sku_map, on=TRIPLE_KEYS, how="left", suffixes=("", "_map"))
    erp_enriched = erp_usable.merge(sku_map, on=TRIPLE_KEYS, how="left", suffixes=("", "_map"))
    for frame in [ads_enriched, erp_enriched]:
        if "product_name_map" in frame.columns:
            frame["product_name"] = frame["product_name"].where(frame["product_name"].astype(str).str.strip() != "", frame["product_name_map"])
            frame.drop(columns=["product_name_map"], inplace=True)
        if "currency" not in frame.columns and "currency_map" in frame.columns:
            frame.rename(columns={"currency_map": "currency"}, inplace=True)

    ads_product = (
        ads_enriched.groupby(["date", "marketplace", "sku", "asin"], dropna=False)[AD_METRIC_COLUMNS]
        .sum()
        .reset_index()
    )
    erp_aggregations = {"total_orders": "sum", "total_sales": "sum"}
    for column in ["fba_stock", "fbm_stock", "available_stock"]:
        if column in erp_enriched.columns:
            erp_aggregations[column] = "max"
    erp_product = (
        erp_enriched.groupby(["date", "marketplace", "sku", "asin"], dropna=False)
        .agg(erp_aggregations)
        .reset_index()
    )
    product_keys = (
        matched_triples.merge(sku_map[TRIPLE_KEYS + ["product_name"]], on=TRIPLE_KEYS, how="left")
        .drop_duplicates(subset=TRIPLE_KEYS)
        .reset_index(drop=True)
    )
    product_keys["product_name"] = product_keys["product_name"].fillna("").astype(str).str.strip()
    product_daily = _cross_join_dates(product_keys, common_start, common_end)
    product_daily = product_daily.merge(
        ads_product,
        on=["date", "marketplace", "sku", "asin"],
        how="left",
    ).merge(
        erp_product,
        on=["date", "marketplace", "sku", "asin"],
        how="left",
    )
    for column in [*AD_METRIC_COLUMNS, "total_orders", "total_sales"]:
        if column in product_daily.columns:
            product_daily[column] = product_daily[column].fillna(0)
    product_daily["natural_orders"] = (product_daily["total_orders"] - product_daily["ad_orders"]).clip(lower=0)

    if not product_config.empty:
        merge_keys = [key for key in TRIPLE_KEYS if key in product_config.columns]
        product_daily = product_daily.merge(product_config, on=merge_keys, how="left")
    cost_merge_columns = [
        column
        for column in [
            "marketplace",
            "sku",
            "asin",
            "currency",
            "unit_cost",
            "shipping_cost",
            "handling_fee",
            "target_acos",
            "profit_before_ads_per_unit",
        ]
        if column in cost_config.columns
    ]
    product_daily = product_daily.merge(cost_config[cost_merge_columns], on=TRIPLE_KEYS, how="left")
    product_daily = add_ratio_columns(product_daily)

    campaign_daily = (
        ads_enriched.groupby(["date", "marketplace", "campaign_name", "sku", "asin", "product_name"], dropna=False)[AD_METRIC_COLUMNS]
        .sum()
        .reset_index()
    )
    campaign_daily = campaign_daily.merge(
        product_daily[["date", "marketplace", "sku", "asin", "product_name", "total_orders", "total_sales", "natural_orders"]],
        on=["date", "marketplace", "sku", "asin"],
        how="left",
        suffixes=("", "_product"),
    )
    if "product_name_product" in campaign_daily.columns:
        campaign_daily.drop(columns=["product_name_product"], inplace=True)
    for column in ["total_orders", "total_sales", "natural_orders"]:
        if column in campaign_daily.columns:
            campaign_daily[column] = campaign_daily[column].fillna(0)
    campaign_daily = add_ratio_columns(campaign_daily)

    searchable = ads_enriched[ads_enriched["search_term"].astype(str).str.strip() != ""].copy()
    search_term_aggregations = {column: "sum" for column in AD_METRIC_COLUMNS}
    for column in SEARCH_TERM_SOURCE_COLUMNS:
        if column in searchable.columns:
            search_term_aggregations[column] = "first"
    search_term_daily = (
        searchable.groupby(
            ["date", "marketplace", "search_term", "campaign_name", "sku", "asin", "product_name"],
            dropna=False,
        )
        .agg(search_term_aggregations)
        .reset_index()
    )
    search_term_daily = search_term_daily.merge(
        product_daily[["date", "marketplace", "sku", "asin", "product_name", "total_orders", "total_sales", "natural_orders"]],
        on=["date", "marketplace", "sku", "asin"],
        how="left",
        suffixes=("", "_product"),
    )
    if "product_name_product" in search_term_daily.columns:
        search_term_daily.drop(columns=["product_name_product"], inplace=True)
    for column in ["total_orders", "total_sales", "natural_orders"]:
        if column in search_term_daily.columns:
            search_term_daily[column] = search_term_daily[column].fillna(0)
    search_term_daily = add_ratio_columns(search_term_daily)

    return DailyDataset(
        report_date=report_date,
        ads_date_range=(ads_min_date, ads_max_date),
        erp_date_range=(coverage_start, coverage_end),
        erp_observed_sales_date_range=(erp_observed_min_date, erp_observed_max_date),
        erp_report_coverage_date_range=(coverage_start, coverage_end),
        erp_zero_filled_days=erp_zero_filled_days,
        erp_last_sales_date=erp_observed_max_date,
        zero_fill_applied=zero_fill_applied,
        coverage_warning=coverage_warning,
        common_date_range=(common_start, common_end),
        history_days=history_days,
        product_daily=product_daily,
        campaign_daily=campaign_daily,
        search_term_daily=search_term_daily,
        mapping_check=mapping_check,
        validation_messages=validation_messages,
    )
