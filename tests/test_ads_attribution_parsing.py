from __future__ import annotations

import pandas as pd

from src.parse_ads_report import load_ads_report


def _base_ads_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "日期": "2026-06-08",
        "广告活动名称": "Campaign",
        "推广的商品 SKU": "SKU-1",
        "推广的商品编号": "B0TEST0001",
        "推广的商品站点": "AMAZON.COM",
        "展示量": 100,
        "点击量": 10,
        "总成本": 5.0,
        "购买量（所有浏览次数）": 4,
        "销售额": 80.0,
    }
    row.update(overrides)
    return row


def test_ads_report_preserves_view_attribution_for_existing_order_and_sales_fields(tmp_path) -> None:
    path = tmp_path / "ads.csv"
    pd.DataFrame(
        [
            _base_ads_row(
                **{
                    "归因于点击的购买量": 2,
                    "归因于点击的销售额": 40.0,
                    "归因于点击的购买量（推广的商品）": 1,
                    "归因于点击的销售额（推广的商品）": 20.0,
                    "归因于点击的购买量（光环）": 1,
                    "归因于点击的销售额（品牌光环）": 20.0,
                    "归因于点击的已售商品数量（品牌光环）": 1,
                }
            )
        ]
    ).to_csv(path, index=False)

    ads, _ = load_ads_report(path)
    row = ads.iloc[0]

    assert row["ad_orders"] == 4
    assert row["ad_sales"] == 80.0
    assert row["click_orders"] == 2
    assert row["click_sales"] == 40.0
    assert row["promoted_ad_orders"] == 1
    assert row["promoted_ad_sales"] == 20.0
    assert row["halo_ad_orders"] == 1
    assert row["halo_ad_sales"] == 20.0
    assert row["halo_ad_units"] == 1


def test_ads_report_falls_back_to_view_attribution_when_click_fields_missing(tmp_path) -> None:
    path = tmp_path / "ads.csv"
    pd.DataFrame([_base_ads_row()]).to_csv(path, index=False)

    ads, _ = load_ads_report(path)
    row = ads.iloc[0]

    assert row["ad_orders"] == 4
    assert row["ad_sales"] == 80.0
    assert row["click_orders"] == 0
    assert row["click_sales"] == 0
    assert row["promoted_ad_orders"] == 0
    assert row["halo_ad_orders"] == 0
    assert "新版点击归因字段缺失" in "；".join(ads.attrs["field_quality"]["warnings"])
