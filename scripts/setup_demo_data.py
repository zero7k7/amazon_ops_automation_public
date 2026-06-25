from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]

PRODUCTS = [
    {
        "marketplace": "US",
        "country": "US",
        "marketplace_raw": "AMAZON.COM",
        "sku": "SKU-DEMO-US-001",
        "asin": "B0DEMOUS01",
        "product_name": "Demo storage bin",
        "currency": "USD",
        "unit_cost": 4.20,
        "shipping_cost": 1.10,
        "handling_fee": 0.40,
        "target_acos": 0.22,
        "profit_before_ads_per_unit": 6.30,
        "current_inventory": 120,
        "sea_inventory": 80,
        "search_terms": ["demo storage bin", "plastic storage box"],
    },
    {
        "marketplace": "UK",
        "country": "UK",
        "marketplace_raw": "AMAZON_CO_UK",
        "sku": "SKU-DEMO-UK-001",
        "asin": "B0DEMOUK01",
        "product_name": "Demo tea caddy",
        "currency": "GBP",
        "unit_cost": 3.10,
        "shipping_cost": 0.80,
        "handling_fee": 0.30,
        "target_acos": 0.24,
        "profit_before_ads_per_unit": 5.20,
        "current_inventory": 95,
        "sea_inventory": 40,
        "search_terms": ["demo tea caddy", "tea storage box"],
    },
    {
        "marketplace": "DE",
        "country": "DE",
        "marketplace_raw": "AMAZON_DE",
        "sku": "SKU-DEMO-DE-001",
        "asin": "B0DEMODE01",
        "product_name": "Demo cable clips",
        "currency": "EUR",
        "unit_cost": 2.40,
        "shipping_cost": 0.70,
        "handling_fee": 0.25,
        "target_acos": 0.20,
        "profit_before_ads_per_unit": 4.10,
        "current_inventory": 150,
        "sea_inventory": 60,
        "search_terms": ["demo cable clips", "cable organiser clips"],
    },
]


def _write_workbook(path: Path, sheets: dict[str, list[dict[str, object]]]) -> None:
    wb = Workbook()
    first = True
    for title, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title=title)
        ws.title = title
        first = False
        headers = list(rows[0].keys()) if rows else []
        ws.append(headers)
        for row in rows:
            ws.append([row.get(header, "") for header in headers])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _guard(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(
            f"Refusing to overwrite existing file: {path}. "
            "Run with --force only in a demo clone or after backing up real business files."
        )


def _ads_rows() -> list[dict[str, object]]:
    start = date.today() - timedelta(days=13)
    rows: list[dict[str, object]] = []
    for offset in range(14):
        day = start + timedelta(days=offset)
        for product in PRODUCTS:
            for term_index, term in enumerate(product["search_terms"]):
                clicks = 2 + ((offset + term_index) % 4)
                orders = 1 if offset in {4, 9, 13} and term_index == 0 else 0
                spend = round(clicks * (0.28 + 0.05 * term_index), 2)
                sales = orders * (18.99 if product["marketplace"] == "US" else 16.99)
                rows.append(
                    {
                        "report_date": day.isoformat(),
                        "campaign_name_(informational_only)": f"Demo {product['marketplace']} auto campaign",
                        "campaign_country": product["country"],
                        "ad_group": f"Demo {product['marketplace']} ad group",
                        "advertised_sku": product["sku"],
                        "advertised_asin": product["asin"],
                        "marketplace": product["marketplace_raw"],
                        "customer_search_term": term,
                        "keyword_or_product_targeting": term,
                        "targeting_type": "BROAD" if term_index else "EXACT",
                        "impr.": 100 + offset * 5 + term_index * 10,
                        "click": clicks,
                        "cost": spend,
                        "orders": orders,
                        "sales": round(sales, 2),
                    }
                )
    return rows


def _erp_rows() -> list[dict[str, object]]:
    start = date.today() - timedelta(days=13)
    rows: list[dict[str, object]] = []
    for offset in range(14):
        day = start + timedelta(days=offset)
        for product in PRODUCTS:
            orders = 1 + ((offset + len(product["sku"])) % 3)
            rows.append(
                {
                    "sales_date": day.isoformat(),
                    "seller_sku": product["sku"],
                    "child_asin": product["asin"],
                    "item_name": product["product_name"],
                    "country": product["country"],
                    "orders": orders,
                    "sales": round(orders * (18.99 if product["marketplace"] == "US" else 16.99), 2),
                    "fba_stock": product["current_inventory"],
                    "available_stock": product["current_inventory"],
                }
            )
    return rows


def _cost_rows() -> list[dict[str, object]]:
    return [
        {
            "marketplace": product["marketplace"],
            "sku": product["sku"],
            "asin": product["asin"],
            "product_name": product["product_name"],
            "currency": product["currency"],
            "unit_cost": product["unit_cost"],
            "shipping_cost": product["shipping_cost"],
            "handling_fee": product["handling_fee"],
            "target_acos": product["target_acos"],
            "profit_before_ads_per_unit": product["profit_before_ads_per_unit"],
        }
        for product in PRODUCTS
    ]


def _inventory_rows() -> list[dict[str, object]]:
    return [
        {
            "marketplace": product["marketplace"],
            "sku": product["sku"],
            "asin": product["asin"],
            "current_inventory": product["current_inventory"],
            "sea_inventory": product["sea_inventory"],
            "inventory_note": "Demo inventory only",
        }
        for product in PRODUCTS
    ]


def _alias_rows() -> list[dict[str, object]]:
    return [
        {
            "marketplace": product["marketplace"],
            "source_sku": product["sku"],
            "canonical_sku": product["sku"],
            "asin": product["asin"],
            "reason": "demo self mapping",
        }
        for product in PRODUCTS
    ]


def setup_demo_data(*, force: bool) -> list[Path]:
    targets = [
        ROOT / "config" / "product_cost_config.xlsx",
        ROOT / "config" / "sku_alias_map.xlsx",
        ROOT / "data" / "raw_ads" / "ads_report_all.csv",
        ROOT / "data" / "raw_erp" / "sales_report_all.xlsx",
    ]
    for target in targets:
        _guard(target, force=force)

    written: list[Path] = []
    ads_path = ROOT / "data" / "raw_ads" / "ads_report_all.csv"
    ads_path.parent.mkdir(parents=True, exist_ok=True)
    ads_rows = _ads_rows()
    with ads_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ads_rows[0].keys()))
        writer.writeheader()
        writer.writerows(ads_rows)
    written.append(ads_path)

    erp_path = ROOT / "data" / "raw_erp" / "sales_report_all.xlsx"
    _write_workbook(erp_path, {"sales_report_all": _erp_rows()})
    written.append(erp_path)

    cost_path = ROOT / "config" / "product_cost_config.xlsx"
    _write_workbook(
        cost_path,
        {
            "product_cost_config": _cost_rows(),
            "SKU匹配检查": _inventory_rows(),
        },
    )
    written.append(cost_path)

    alias_path = ROOT / "config" / "sku_alias_map.xlsx"
    _write_workbook(alias_path, {"sku_alias_map": _alias_rows()})
    written.append(alias_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Create fake demo data for a clean clone.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing demo target files. Do not use in a real business workspace without backups.",
    )
    args = parser.parse_args()
    written = setup_demo_data(force=args.force)
    print("Demo data written:")
    for path in written:
        print(f"- {path.relative_to(ROOT)}")
    print("Next command: python main.py --marketplace ALL --safe-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
