from __future__ import annotations

from pathlib import Path

import pandas as pd

from .normalize_fields import (
    FieldValidationError,
    coerce_numeric,
    coerce_text,
    normalize_column_names,
    parse_date_column,
    rename_with_synonyms,
    require_columns,
)

ADS_FIELD_SPECS = {
    "date": {"source": "日期", "required": True, "type": "date"},
    "ad_product": {"source": "广告产品", "required": False, "type": "text"},
    "currency": {"source": "预算货币", "required": False, "type": "text"},
    "campaign_id": {"source": "广告活动编号", "required": False, "type": "text"},
    "campaign_name": {"source": "广告活动名称", "required": True, "type": "text"},
    "campaign_status": {"source": "广告活动投放状态", "required": False, "type": "text"},
    "campaign_budget_amount": {"source": "广告活动预算金额", "required": False, "type": "numeric"},
    "campaign_budget_type": {"source": "广告活动预算类型", "required": False, "type": "text"},
    "campaign_bid_strategy": {"source": "广告活动竞价方案", "required": False, "type": "text"},
    "campaign_cost_type": {"source": "广告活动成本类型", "required": False, "type": "text"},
    "campaign_country": {"source": "投放广告活动的国家/地区", "required": False, "type": "text"},
    "portfolio_id": {"source": "广告组合编号", "required": False, "type": "text"},
    "portfolio_name": {"source": "广告组合名称", "required": False, "type": "text"},
    "asin": {"source": "推广的商品编号", "required": True, "type": "text"},
    "sku": {"source": "推广的商品 SKU", "required": True, "type": "text"},
    "advertised_product_marketplace": {"source": "推广的商品站点", "required": True, "type": "text"},
    "ad_group_id": {"source": "广告组编号", "required": False, "type": "text"},
    "ad_group_name": {"source": "广告组名称", "required": False, "type": "text"},
    "ad_group_status": {"source": "广告组投放状态", "required": False, "type": "text"},
    "ad_group_cost_type": {"source": "广告组计费模式", "required": False, "type": "text"},
    "ad_id": {"source": "广告 ID", "required": False, "type": "text"},
    "ad_name": {"source": "广告名称", "required": False, "type": "text"},
    "ad_status": {"source": "广告投放状态", "required": False, "type": "text"},
    "search_term": {"source": "搜索词", "required": False, "type": "text"},
    "matched_target": {"source": "匹配的目标", "required": False, "type": "text"},
    "targeting": {"source": "投放值", "required": False, "type": "text"},
    "match_type": {"source": "投放匹配类型", "required": False, "type": "text"},
    "placement_name": {"source": "广告位名称", "required": False, "type": "text"},
    "placement_classification": {"source": "广告位分类", "required": False, "type": "text"},
    "impressions": {"source": "展示量", "required": True, "type": "numeric"},
    "clicks": {"source": "点击量", "required": True, "type": "numeric"},
    "total_clicks": {"source": "总点击量", "required": False, "type": "numeric"},
    "CTR": {"source": "点击率", "required": False, "type": "numeric"},
    "CPC": {"source": "CPC", "required": False, "type": "numeric"},
    "spend": {"source": "总成本", "required": True, "type": "numeric"},
    "ROAS": {"source": "ROAS", "required": False, "type": "numeric"},
    "view_orders": {"source": "购买量（所有浏览次数）", "required": True, "type": "numeric"},
    "ad_units": {"source": "销量（所有浏览次数）", "required": False, "type": "numeric"},
    "ad_units_sold": {"source": "已售商品数量（所有浏览次数）", "required": False, "type": "numeric"},
    "CVR": {"source": "购买率（所有浏览次数）", "required": False, "type": "numeric"},
    "view_sales": {"source": "销售额", "required": True, "type": "numeric"},
    "click_orders": {"source": "归因于点击的购买量", "required": False, "type": "numeric"},
    "click_sales": {"source": "归因于点击的销售额", "required": False, "type": "numeric"},
    "click_roas": {"source": "归因于点击的 ROAS", "required": False, "type": "numeric"},
    "click_cpa": {"source": "归因于点击的单次购买成本", "required": False, "type": "numeric"},
    "promoted_click_orders": {"source": "归因于点击的购买量（推广的商品）", "required": False, "type": "numeric"},
    "promoted_click_sales": {"source": "归因于点击的销售额（推广的商品）", "required": False, "type": "numeric"},
    "halo_click_orders": {"source": "归因于点击的购买量（光环）", "required": False, "type": "numeric"},
    "halo_click_sales": {"source": "归因于点击的销售额（品牌光环）", "required": False, "type": "numeric"},
    "halo_click_units": {"source": "归因于点击的已售商品数量（品牌光环）", "required": False, "type": "numeric"},
    "invalid_impression_rate": {"source": "无效展示率", "required": False, "type": "numeric"},
    "invalid_clicks": {"source": "无效点击", "required": False, "type": "numeric"},
}

ADS_SYNONYMS = {
    "date": ["report_date", "day", "start_date", "日期"],
    "ad_product": ["广告产品"],
    "currency": ["预算货币", "currency"],
    "campaign_id": ["campaign_id", "广告活动编号"],
    "campaign_name": ["campaign", "campaign_name_(informational_only)", "广告活动名称"],
    "campaign_status": ["广告活动投放状态"],
    "campaign_budget_amount": ["广告活动预算金额"],
    "campaign_budget_type": ["广告活动预算类型"],
    "campaign_bid_strategy": ["广告活动竞价方案"],
    "campaign_cost_type": ["广告活动成本类型"],
    "campaign_country": ["投放广告活动的国家/地区"],
    "portfolio_id": ["广告组合编号"],
    "portfolio_name": ["广告组合名称", "portfolio_name"],
    "ad_group_id": ["ad_group_id", "广告组编号"],
    "ad_group_name": ["ad_group", "ad_group_name_(informational_only)", "广告组名称"],
    "ad_group_status": ["广告组投放状态"],
    "ad_group_cost_type": ["广告组计费模式"],
    "ad_id": ["广告 ID", "ad_id"],
    "ad_name": ["广告名称"],
    "ad_status": ["广告投放状态"],
    "matched_target": ["匹配的目标"],
    "targeting": ["keyword_or_product_targeting", "keyword_text", "target", "投放值"],
    "match_type": ["targeting_type", "matchtype", "投放匹配类型"],
    "search_term": ["customer_search_term", "search_term_impression_share", "搜索词"],
    "sku": [
        "advertised_sku",
        "sku_(informational_only)",
        "seller_sku",
        "推广的商品_sku",
        "推广的商品sku",
        "推广的商品_sku",
        "推广的商品_sku",
        "推广的商品_sku",
        "推广的商品 sku",
        "推广的商品_sku",
        "推广的商品 SKU",
    ],
    "asin": ["advertised_asin", "asin_(informational_only)", "推广的商品编号"],
    "advertised_product_marketplace": ["推广的商品站点", "marketplace", "site"],
    "placement_name": ["广告位名称"],
    "placement_classification": ["广告位分类"],
    "impressions": ["impr.", "impression", "展示量"],
    "clicks": ["click", "click_throughs", "点击量"],
    "total_clicks": ["总点击量"],
    "CTR": ["点击率", "ctr"],
    "CPC": ["cpc"],
    "spend": ["cost", "ad_spend", "总成本", "广告库存成本"],
    "ROAS": ["roas"],
    "view_orders": ["7_day_total_orders_(#)", "orders", "14_day_total_orders_(#)", "购买量（所有浏览次数）"],
    "ad_units": ["销量（所有浏览次数）"],
    "ad_units_sold": ["已售商品数量（所有浏览次数）"],
    "CVR": ["购买率（所有浏览次数）", "cvr"],
    "view_sales": [
        "7_day_total_sales_",
        "sales",
        "14_day_total_sales_",
        "销售额",
    ],
    "click_orders": ["归因于点击的购买量"],
    "click_sales": ["归因于点击的销售额"],
    "click_roas": ["归因于点击的 ROAS", "归因于点击的ROAS"],
    "click_cpa": ["归因于点击的单次购买成本"],
    "promoted_click_orders": ["归因于点击的购买量（推广的商品）"],
    "promoted_click_sales": ["归因于点击的销售额（推广的商品）"],
    "halo_click_orders": ["归因于点击的购买量（光环）"],
    "halo_click_sales": ["归因于点击的销售额（品牌光环）"],
    "halo_click_units": ["归因于点击的已售商品数量（品牌光环）"],
    "invalid_impression_rate": ["无效展示率"],
    "invalid_clicks": ["无效点击"],
}

REQUIRED_ADS_COLUMNS = [
    "date",
    "campaign_name",
    "sku",
    "asin",
    "advertised_product_marketplace",
    "impressions",
    "clicks",
    "spend",
    "view_orders",
    "view_sales",
]

ATTRIBUTION_FIELDS = [
    "click_orders",
    "click_sales",
    "click_roas",
    "click_cpa",
    "promoted_click_orders",
    "promoted_click_sales",
    "halo_click_orders",
    "halo_click_sales",
    "halo_click_units",
]

MARKETPLACE_MAP = {
    "AMAZON_CO_UK": "UK",
    "AMAZON.COM": "US",
    "AMAZON_COM": "US",
    "AMAZON_DE": "DE",
}

CAMPAIGN_COUNTRY_MARKETPLACE_MAP = {
    "UK": "UK",
    "GB": "UK",
    "UNITED KINGDOM": "UK",
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "DE": "DE",
    "GERMANY": "DE",
}


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise FieldValidationError(f"暂不支持的广告报表格式: {path.name}")


def _non_empty_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return 0
    series = df[column]
    return int(series.notna().sum() if not pd.api.types.is_string_dtype(series) else series.astype(str).str.strip().ne("").sum())


def _build_field_quality(raw: pd.DataFrame, normalized: pd.DataFrame, source_path: Path) -> dict:
    fields: list[dict] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []
    for canonical, spec in ADS_FIELD_SPECS.items():
        present = canonical in normalized.columns
        source_column = spec["source"] if present else ""
        row = {
            "canonical_field": canonical,
            "expected_source_column": spec["source"],
            "source_column": source_column,
            "required": bool(spec["required"]),
            "present": present,
            "non_empty_rows": _non_empty_count(normalized, canonical),
            "type": spec["type"],
        }
        fields.append(row)
        if not present:
            if spec["required"]:
                missing_required.append(canonical)
            else:
                missing_optional.append(canonical)

    marketplace_values = []
    marketplace_column = "marketplace_raw" if "marketplace_raw" in normalized.columns else "advertised_product_marketplace"
    if marketplace_column in normalized.columns:
        marketplace_values = sorted(str(value).strip() for value in normalized[marketplace_column].dropna().unique() if str(value).strip())
    country_values = []
    if "campaign_country" in normalized.columns:
        country_values = sorted(str(value).strip() for value in normalized["campaign_country"].dropna().unique() if str(value).strip())

    warnings: list[str] = []
    missing_attribution_fields = [field for field in ATTRIBUTION_FIELDS if field not in normalized.columns]
    if missing_required:
        warnings.append("广告报表缺少必要字段: " + ", ".join(missing_required))
    if missing_attribution_fields:
        warnings.append("新版点击归因字段缺失，已按 0 兜底: " + ", ".join(missing_attribution_fields))
    if "placement_classification" not in normalized.columns:
        warnings.append("缺少广告位分类，无法按 placement 分类复盘。")
    if "bid" not in normalized.columns and "keyword_bid" not in normalized.columns:
        warnings.append("没有具体竞价字段，报告只能建议降竞价比例，不能给具体新 bid。")
    conversion_product_candidates = [
        column
        for column in normalized.columns
        if column in {"purchased_asin", "conversion_asin", "purchased_sku", "conversion_sku"}
        or "购买_asin" in column
        or "转化_asin" in column
    ]
    if not conversion_product_candidates:
        warnings.append("没有转化商品 ASIN/SKU 字段，购买 ASIN 归因需单独导出。")

    return {
        "source_file": str(source_path),
        "row_count": int(len(raw)),
        "column_count": int(len(raw.columns)),
        "raw_columns": [str(column) for column in raw.columns],
        "field_mapping": fields,
        "missing_required_fields": missing_required,
        "missing_optional_fields": missing_optional,
        "missing_attribution_fields": missing_attribution_fields,
        "marketplace_raw_values": marketplace_values,
        "campaign_country_values": country_values,
        "has_placement_classification": "placement_classification" in normalized.columns,
        "has_specific_bid_field": "bid" in normalized.columns or "keyword_bid" in normalized.columns,
        "has_conversion_product_field": bool(conversion_product_candidates),
        "warnings": warnings,
    }


def load_ads_report(source_path: Path) -> tuple[pd.DataFrame, Path]:
    if not source_path.exists():
        raise FileNotFoundError(f"缺少广告报表文件: {source_path}")

    raw = _read_table(source_path)
    normalized = normalize_column_names(raw)
    normalized = rename_with_synonyms(normalized, ADS_SYNONYMS)
    field_quality = _build_field_quality(raw, normalized, source_path)
    present_attribution_fields = [field for field in ATTRIBUTION_FIELDS if field in normalized.columns]
    require_columns(normalized, REQUIRED_ADS_COLUMNS, source_name=source_path.name)

    if "marketplace_raw" not in normalized.columns and "advertised_product_marketplace" in normalized.columns:
        normalized["marketplace_raw"] = normalized["advertised_product_marketplace"]
    if "advertised_product_marketplace" not in normalized.columns and "marketplace_raw" in normalized.columns:
        normalized["advertised_product_marketplace"] = normalized["marketplace_raw"]

    optional_columns = [
        column
        for column in ADS_FIELD_SPECS
        if column not in {"date", "campaign_name", "sku", "asin", "advertised_product_marketplace", "impressions", "clicks", "spend", "view_orders", "view_sales"}
    ]
    for optional_column in optional_columns:
        if optional_column not in normalized.columns:
            normalized[optional_column] = ""
    for attribution_column in ATTRIBUTION_FIELDS:
        if attribution_column not in normalized.columns:
            normalized[attribution_column] = ""
    text_columns = [
        column
        for column, spec in ADS_FIELD_SPECS.items()
        if spec["type"] == "text" and column in normalized.columns
    ]
    ads = coerce_text(
        normalized,
        text_columns + ["marketplace_raw"],
    )
    numeric_columns = [
        column
        for column, spec in ADS_FIELD_SPECS.items()
        if spec["type"] == "numeric" and column in ads.columns
    ]
    ads = coerce_numeric(ads, numeric_columns)
    ads["ad_orders"] = ads["view_orders"]
    ads["ad_sales"] = ads["view_sales"]
    ads["promoted_ad_orders"] = ads["promoted_click_orders"]
    ads["promoted_ad_sales"] = ads["promoted_click_sales"]
    ads["halo_ad_orders"] = ads["halo_click_orders"]
    ads["halo_ad_sales"] = ads["halo_click_sales"]
    ads["halo_ad_units"] = ads["halo_click_units"]
    ads["date"] = parse_date_column(ads["date"], column_name="广告报表日期")
    normalized_marketplace = ads["marketplace_raw"].astype(str).str.strip().str.upper()
    ads["marketplace"] = normalized_marketplace.map(MARKETPLACE_MAP).fillna("")
    if "campaign_country" in ads.columns:
        country_marketplace = (
            ads["campaign_country"]
            .astype(str)
            .str.strip()
            .str.upper()
            .map(CAMPAIGN_COUNTRY_MARKETPLACE_MAP)
            .fillna("")
        )
        ads["marketplace"] = ads["marketplace"].where(ads["marketplace"].astype(str).str.strip() != "", country_marketplace)
    ads["record_type"] = ads["search_term"].apply(lambda value: "search_term" if value else "campaign")

    validation_messages: list[str] = []
    data_quality_warnings: list[dict] = []
    invalid_click_rows = ads[ads["clicks"] > ads["impressions"]]
    if not invalid_click_rows.empty:
        sample = invalid_click_rows[["date", "campaign_name", "sku", "asin", "marketplace", "impressions", "clicks"]].head(10)
        validation_messages.append(
            "广告报表存在 clicks > impressions 的异常记录: "
            + sample.to_json(force_ascii=False, orient="records")
        )
    if "click_orders" in present_attribution_fields and (
        "promoted_click_orders" in present_attribution_fields or "halo_click_orders" in present_attribution_fields
    ):
        order_diff = (ads["click_orders"] - ads["promoted_click_orders"] - ads["halo_click_orders"]).abs()
        order_bad = ads[order_diff > 0.01]
        if not order_bad.empty:
            sample = order_bad[["date", "campaign_name", "sku", "asin", "marketplace", "click_orders", "promoted_click_orders", "halo_click_orders"]].head(20)
            warning = {
                "type": "click_order_split_mismatch",
                "row_count": int(len(order_bad)),
                "sample": sample.to_dict(orient="records"),
            }
            data_quality_warnings.append(warning)
            validation_messages.append(f"点击归因购买量拆分不一致 {len(order_bad)} 行，详见 data_quality_warnings。")
    if "click_sales" in present_attribution_fields and (
        "promoted_click_sales" in present_attribution_fields or "halo_click_sales" in present_attribution_fields
    ):
        sales_diff = (ads["click_sales"] - ads["promoted_click_sales"] - ads["halo_click_sales"]).abs()
        sales_bad = ads[sales_diff > 0.01]
        if not sales_bad.empty:
            sample = sales_bad[["date", "campaign_name", "sku", "asin", "marketplace", "click_sales", "promoted_click_sales", "halo_click_sales"]].head(20)
            warning = {
                "type": "click_sales_split_mismatch",
                "row_count": int(len(sales_bad)),
                "sample": sample.to_dict(orient="records"),
            }
            data_quality_warnings.append(warning)
            validation_messages.append(f"点击归因销售额拆分不一致 {len(sales_bad)} 行，详见 data_quality_warnings。")

    ads.attrs["validation_messages"] = validation_messages
    ads.attrs["field_quality"] = field_quality
    ads.attrs["data_quality_warnings"] = data_quality_warnings
    return ads, source_path
