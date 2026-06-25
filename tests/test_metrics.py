from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.metrics import add_ratio_columns, build_windowed_views


class MetricsTestCase(unittest.TestCase):
    def test_add_ratio_columns_handles_zero_denominator(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "impressions": 0,
                    "clicks": 0,
                    "spend": 0,
                    "ad_orders": 0,
                    "ad_sales": 0,
                    "total_orders": 0,
                    "total_sales": 0,
                    "natural_orders": 0,
                }
            ]
        )
        result = add_ratio_columns(frame)
        self.assertEqual(result.loc[0, "CTR"], 0)
        self.assertEqual(result.loc[0, "CPC"], 0)
        self.assertEqual(result.loc[0, "CVR"], 0)
        self.assertEqual(result.loc[0, "ACOS"], 0)
        self.assertEqual(result.loc[0, "TACOS"], 0)

    def test_windowed_views_sum_click_attribution_and_keep_inventory(self) -> None:
        rows = []
        for day, clicks, ad_orders, ad_sales, promoted_orders, halo_orders, stock in [
            (date(2026, 6, 2), 4, 1, 20.0, 1, 0, 11),
            (date(2026, 6, 8), 6, 2, 40.0, 1, 1, 9),
        ]:
            rows.append(
                {
                    "date": day,
                    "marketplace": "US",
                    "sku": "SKU-1",
                    "asin": "B0TEST0001",
                    "product_name": "Test product",
                    "campaign_name": "Campaign",
                    "search_term": "bamboo board",
                    "impressions": 100,
                    "clicks": clicks,
                    "spend": 5.0,
                    "ad_orders": ad_orders,
                    "ad_sales": ad_sales,
                    "click_orders": ad_orders,
                    "click_sales": ad_sales,
                    "promoted_ad_orders": promoted_orders,
                    "promoted_ad_sales": promoted_orders * 20.0,
                    "halo_ad_orders": halo_orders,
                    "halo_ad_sales": halo_orders * 20.0,
                    "halo_ad_units": halo_orders,
                    "total_orders": 3,
                    "total_sales": 60.0,
                    "natural_orders": 3 - ad_orders,
                    "target_acos": 0.25,
                    "profit_before_ads_per_unit": 10.0,
                    "unit_cost": 4.0,
                    "shipping_cost": 1.0,
                    "handling_fee": 0.5,
                    "currency": "USD",
                    "fba_stock": stock,
                    "fbm_stock": 0,
                    "available_stock": stock,
                }
            )
        current = pd.DataFrame(rows)
        history = {
            "product_daily": pd.DataFrame(),
            "campaign_daily": pd.DataFrame(),
            "search_term_daily": pd.DataFrame(),
        }

        views = build_windowed_views(date(2026, 6, 8), current, current, current, history)
        product_7d = views.product_windows[7].iloc[0]

        self.assertEqual(product_7d["clicks"], 10)
        self.assertEqual(product_7d["ad_orders"], 3)
        self.assertEqual(product_7d["ad_sales"], 60.0)
        self.assertEqual(product_7d["click_orders"], 3)
        self.assertEqual(product_7d["promoted_ad_orders"], 2)
        self.assertEqual(product_7d["halo_ad_orders"], 1)
        self.assertEqual(product_7d["halo_ad_units"], 1)
        self.assertEqual(product_7d["available_stock"], 11)
        self.assertEqual(product_7d["CVR"], 0.3)
        self.assertAlmostEqual(product_7d["ACOS"], 10.0 / 60.0)

    def test_product_windows_do_not_merge_same_asin_different_skus(self) -> None:
        rows = [
            {
                "date": date(2026, 6, 8),
                "marketplace": "US",
                "sku": "SKU-A",
                "asin": "B0SHARED01",
                "product_name": "Shared ASIN A",
                "campaign_name": "Campaign A",
                "search_term": "term a",
                "impressions": 100,
                "clicks": 10,
                "spend": 5.0,
                "ad_orders": 1,
                "ad_sales": 20.0,
                "click_orders": 1,
                "click_sales": 20.0,
                "promoted_ad_orders": 1,
                "promoted_ad_sales": 20.0,
                "halo_ad_orders": 0,
                "halo_ad_sales": 0.0,
                "halo_ad_units": 0,
                "total_orders": 2,
                "total_sales": 40.0,
                "natural_orders": 1,
                "available_stock": 8,
            },
            {
                "date": date(2026, 6, 8),
                "marketplace": "US",
                "sku": "SKU-B",
                "asin": "B0SHARED01",
                "product_name": "Shared ASIN B",
                "campaign_name": "Campaign B",
                "search_term": "term b",
                "impressions": 200,
                "clicks": 20,
                "spend": 8.0,
                "ad_orders": 3,
                "ad_sales": 60.0,
                "click_orders": 3,
                "click_sales": 60.0,
                "promoted_ad_orders": 3,
                "promoted_ad_sales": 60.0,
                "halo_ad_orders": 0,
                "halo_ad_sales": 0.0,
                "halo_ad_units": 0,
                "total_orders": 5,
                "total_sales": 100.0,
                "natural_orders": 2,
                "available_stock": 19,
            },
        ]
        current = pd.DataFrame(rows)
        history = {
            "product_daily": pd.DataFrame(),
            "campaign_daily": pd.DataFrame(),
            "search_term_daily": pd.DataFrame(),
        }

        views = build_windowed_views(date(2026, 6, 8), current, current, current, history)
        product_1d = views.product_windows[1].sort_values("sku").reset_index(drop=True)

        self.assertEqual(product_1d[["marketplace", "sku", "asin"]].to_dict(orient="records"), [
            {"marketplace": "US", "sku": "SKU-A", "asin": "B0SHARED01"},
            {"marketplace": "US", "sku": "SKU-B", "asin": "B0SHARED01"},
        ])
        self.assertEqual(product_1d.loc[0, "total_orders"], 2)
        self.assertEqual(product_1d.loc[1, "total_orders"], 5)
        self.assertEqual(product_1d.loc[0, "available_stock"], 8)
        self.assertEqual(product_1d.loc[1, "available_stock"], 19)


if __name__ == "__main__":
    unittest.main()
