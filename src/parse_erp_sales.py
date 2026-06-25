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

ERP_SYNONYMS = {
    "date": ["report_date", "sales_date", "day", "时间"],
    "sku": ["seller_sku", "merchant_sku", "sku"],
    "asin": ["child_asin", "parent_asin", "asin"],
    "product_name": ["item_name", "title", "品名", "标题"],
    "country_raw": ["国家", "country"],
    "store_raw": ["店铺", "store"],
    "total_orders": ["orders", "order_qty", "units_sold", "订单量"],
    "total_sales": ["sales", "sales_amount", "gmv", "销售额"],
    "fba_stock": ["fba_stock", "fba可售", "fba_available"],
    "fbm_stock": ["fbm_stock", "fbm可售", "fbm_available"],
    "available_stock": ["available_stock", "available_inventory", "可用库存", "库存"],
}

REQUIRED_ERP_COLUMNS = ["date", "sku", "asin", "product_name", "total_orders", "total_sales"]


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise FieldValidationError(f"暂不支持的 ERP 报表格式: {path.name}")


def _derive_marketplace(country_raw: str, store_raw: str) -> str:
    country = str(country_raw).strip().upper()
    store = str(store_raw).strip().upper()
    if country in {"英国", "UK"} or store == "AWBS-EU-UK":
        return "UK"
    if country in {"美国", "US"}:
        return "US"
    if country in {"德国", "DE"}:
        return "DE"
    return ""


def load_erp_report(source_path: Path) -> tuple[pd.DataFrame, Path]:
    if not source_path.exists():
        raise FileNotFoundError(f"缺少 ERP 销量表文件: {source_path}")

    raw = _read_table(source_path)
    normalized = normalize_column_names(raw)
    normalized = rename_with_synonyms(normalized, ERP_SYNONYMS)
    require_columns(normalized, REQUIRED_ERP_COLUMNS, source_name=source_path.name)

    erp = coerce_text(normalized, ["sku", "asin", "product_name", "country_raw", "store_raw"])
    erp = coerce_numeric(erp, ["total_orders", "total_sales", "fba_stock", "fbm_stock", "available_stock"])
    erp["date"] = parse_date_column(erp["date"], column_name="ERP 日期")
    erp["marketplace"] = erp.apply(
        lambda row: _derive_marketplace(row.get("country_raw", ""), row.get("store_raw", "")),
        axis=1,
    )
    erp.attrs["validation_messages"] = []
    return erp, source_path
