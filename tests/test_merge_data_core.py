from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.merge_data import build_daily_dataset
from src.metrics import add_ratio_columns, build_windowed_views


AD_METRICS = {
    "impressions": 100,
    "clicks": 0,
    "spend": 0.0,
    "ad_orders": 0,
    "ad_sales": 0.0,
    "click_orders": 0,
    "click_sales": 0.0,
    "promoted_ad_orders": 0,
    "promoted_ad_sales": 0.0,
    "halo_ad_orders": 0,
    "halo_ad_sales": 0.0,
    "halo_ad_units": 0,
}


def _write_configs(
    tmp_path: Path,
    *,
    sku_rows: list[dict[str, object]],
    cost_rows: list[dict[str, object]],
    alias_rows: list[dict[str, object]] | None = None,
) -> dict[str, Path]:
    sku_map_path = tmp_path / "sku_asin_map.xlsx"
    cost_config_path = tmp_path / "product_cost_config.xlsx"
    alias_map_path = tmp_path / "sku_alias_map.xlsx"

    pd.DataFrame(sku_rows).to_excel(sku_map_path, index=False)
    with pd.ExcelWriter(cost_config_path) as writer:
        pd.DataFrame(cost_rows).to_excel(writer, sheet_name="product_cost_config", index=False)
    if alias_rows is not None:
        pd.DataFrame(alias_rows).to_excel(alias_map_path, index=False)

    return {
        "sku_map_path": sku_map_path,
        "product_config_path": tmp_path / "product_config.xlsx",
        "cost_config_path": cost_config_path,
        "alias_map_path": alias_map_path,
        "ignored_issues_path": tmp_path / "ignored_quality_issues.xlsx",
    }


def _sku_row(sku: str, asin: str, product_name: str = "Fake product") -> dict[str, object]:
    return {
        "marketplace": "US",
        "sku": sku,
        "asin": asin,
        "product_name": product_name,
        "currency": "USD",
    }


def _cost_row(sku: str, asin: str, product_name: str = "Fake product") -> dict[str, object]:
    return {
        "marketplace": "US",
        "sku": sku,
        "asin": asin,
        "product_name": product_name,
        "currency": "USD",
        "unit_cost": 4.0,
        "shipping_cost": 1.0,
        "handling_fee": 0.5,
        "target_acos": 0.25,
        "profit_before_ads_per_unit": 8.0,
    }


def _ad_row(day: date, sku: str, asin: str, **overrides: object) -> dict[str, object]:
    row = {
        "date": day,
        "marketplace": "US",
        "sku": sku,
        "asin": asin,
        "campaign_name": "Fake campaign",
        "search_term": "fake term",
        **AD_METRICS,
    }
    row.update(overrides)
    return row


def _erp_row(day: date, sku: str, asin: str, orders: int, sales: float) -> dict[str, object]:
    return {
        "date": day,
        "marketplace": "US",
        "sku": sku,
        "asin": asin,
        "product_name": "Fake product",
        "total_orders": orders,
        "total_sales": sales,
        "available_stock": 20,
    }


def test_build_daily_dataset_zero_fills_missing_erp_sales_dates(tmp_path: Path) -> None:
    paths = _write_configs(
        tmp_path,
        sku_rows=[_sku_row("SKU-ZERO", "B0FAKEZERO")],
        cost_rows=[_cost_row("SKU-ZERO", "B0FAKEZERO")],
    )
    days = [date(2026, 6, 1) + timedelta(days=offset) for offset in range(7)]
    ads_df = pd.DataFrame([_ad_row(day, "SKU-ZERO", "B0FAKEZERO") for day in days])
    erp_df = pd.DataFrame(
        [
            _erp_row(date(2026, 6, 1), "SKU-ZERO", "B0FAKEZERO", 2, 40.0),
            _erp_row(date(2026, 6, 3), "SKU-ZERO", "B0FAKEZERO", 1, 20.0),
        ]
    )

    dataset = build_daily_dataset(ads_df, erp_df, target_marketplace="US", **paths)

    assert dataset.common_date_range == (date(2026, 6, 1), date(2026, 6, 7))
    assert dataset.zero_fill_applied is True
    assert dataset.erp_zero_filled_days == 4
    assert "2026-06-04 ~ 2026-06-07 无销量行，已按 0 单补齐" == dataset.coverage_warning
    product_daily = dataset.product_daily.sort_values("date").reset_index(drop=True)
    assert len(product_daily) == 7
    assert product_daily.loc[product_daily["date"] == date(2026, 6, 2), "total_orders"].iloc[0] == 0
    assert product_daily.loc[product_daily["date"] == date(2026, 6, 7), "total_sales"].iloc[0] == 0


def test_build_daily_dataset_applies_alias_without_changing_triple_key_shape(tmp_path: Path) -> None:
    paths = _write_configs(
        tmp_path,
        sku_rows=[_sku_row("SKU-CANON", "B0FAKEALIAS")],
        cost_rows=[_cost_row("SKU-CANON", "B0FAKEALIAS")],
        alias_rows=[
            {
                "marketplace": "US",
                "source_sku": "SKU-ALIAS",
                "canonical_sku": "SKU-CANON",
                "asin": "B0FAKEALIAS",
                "reason": "test alias",
            }
        ],
    )
    ads_df = pd.DataFrame([_ad_row(date(2026, 6, 7), "SKU-ALIAS", "B0FAKEALIAS", clicks=5)])
    erp_df = pd.DataFrame([_erp_row(date(2026, 6, 7), "SKU-ALIAS", "B0FAKEALIAS", 1, 25.0)])

    dataset = build_daily_dataset(ads_df, erp_df, target_marketplace="US", **paths)

    triples = dataset.product_daily[["marketplace", "sku", "asin"]].drop_duplicates().to_dict(orient="records")
    assert triples == [{"marketplace": "US", "sku": "SKU-CANON", "asin": "B0FAKEALIAS"}]
    assert set(dataset.mapping_check["mapping_status"]) == {"matched"}
    assert "SKU-ALIAS" not in set(dataset.product_daily["sku"])


def test_build_daily_dataset_backfills_blank_sku_from_unique_marketplace_asin(tmp_path: Path) -> None:
    paths = _write_configs(
        tmp_path,
        sku_rows=[_sku_row("SKU-FILL", "B0FAKEFILL")],
        cost_rows=[_cost_row("SKU-FILL", "B0FAKEFILL")],
    )
    ads_df = pd.DataFrame([_ad_row(date(2026, 6, 7), "", "B0FAKEFILL", clicks=3)])
    erp_df = pd.DataFrame([_erp_row(date(2026, 6, 7), "", "B0FAKEFILL", 1, 30.0)])

    dataset = build_daily_dataset(ads_df, erp_df, target_marketplace="US", **paths)

    assert dataset.product_daily["sku"].drop_duplicates().tolist() == ["SKU-FILL"]
    assert dataset.mapping_check[["marketplace", "sku", "asin", "mapping_status"]].to_dict(orient="records") == [
        {"marketplace": "US", "sku": "SKU-FILL", "asin": "B0FAKEFILL", "mapping_status": "matched"}
    ]


def test_build_daily_dataset_marks_missing_cost_config_without_using_bad_row(tmp_path: Path) -> None:
    paths = _write_configs(
        tmp_path,
        sku_rows=[
            _sku_row("SKU-GOOD", "B0FAKEGOOD"),
            _sku_row("SKU-NOCOST", "B0FAKENOCOST"),
        ],
        cost_rows=[_cost_row("SKU-GOOD", "B0FAKEGOOD")],
    )
    ads_df = pd.DataFrame(
        [
            _ad_row(date(2026, 6, 7), "SKU-GOOD", "B0FAKEGOOD", clicks=2),
            _ad_row(date(2026, 6, 7), "SKU-NOCOST", "B0FAKENOCOST", clicks=9),
        ]
    )
    erp_df = pd.DataFrame(
        [
            _erp_row(date(2026, 6, 7), "SKU-GOOD", "B0FAKEGOOD", 1, 20.0),
            _erp_row(date(2026, 6, 7), "SKU-NOCOST", "B0FAKENOCOST", 1, 20.0),
        ]
    )

    dataset = build_daily_dataset(ads_df, erp_df, target_marketplace="US", **paths)

    missing = dataset.mapping_check[dataset.mapping_check["sku"] == "SKU-NOCOST"].iloc[0]
    assert missing["mapping_status"] == "missing_cost_config"
    assert "product_cost_config 中找不到 marketplace + sku + asin" == missing["reason"]
    assert "SKU-NOCOST" not in set(dataset.product_daily["sku"])
    assert any("存在 1 条 marketplace + sku + asin 数据质量问题" in message for message in dataset.validation_messages)


def test_metrics_window_boundaries_include_only_requested_dates() -> None:
    rows = []
    for offset in range(15):
        day = date(2026, 6, 1) + timedelta(days=offset)
        rows.append(
            {
                "date": day,
                "marketplace": "US",
                "sku": "SKU-WINDOW",
                "asin": "B0FAKEWINDOW",
                "product_name": "Fake window product",
                "campaign_name": "Fake campaign",
                "search_term": "fake term",
                **AD_METRICS,
                "clicks": 1,
                "spend": 1.0,
                "total_orders": 1,
                "total_sales": 10.0,
                "natural_orders": 1,
            }
        )
    daily = pd.DataFrame(rows)
    history = {
        "product_daily": pd.DataFrame(),
        "campaign_daily": pd.DataFrame(),
        "search_term_daily": pd.DataFrame(),
    }

    views = build_windowed_views(date(2026, 6, 15), daily, daily, daily, history)

    assert views.product_windows[1].iloc[0]["clicks"] == 1
    assert views.product_windows[7].iloc[0]["clicks"] == 7
    assert views.product_windows[14].iloc[0]["clicks"] == 14


def test_add_ratio_columns_keeps_acos_and_tacos_empty_when_spend_has_no_sales() -> None:
    frame = pd.DataFrame(
        [
            {
                **AD_METRICS,
                "clicks": 4,
                "spend": 12.0,
                "ad_sales": 0.0,
                "total_orders": 0,
                "total_sales": 0.0,
                "natural_orders": 0,
            }
        ]
    )

    result = add_ratio_columns(frame)

    assert pd.isna(result.loc[0, "ACOS"])
    assert pd.isna(result.loc[0, "TACOS"])
    assert bool(result.loc[0, "has_spend_no_sales"]) is True
