# Amazon Ops Automation

Offline demo pipeline for Amazon advertising, ERP sales, cost configuration, SKU/ASIN mapping, and operations reports.

This public repository is a clean demo snapshot. It does not include private business data, historical report outputs, browser profiles, cookies, sessions, or real cost/SKU configuration files.

## What It Does

- Parses Amazon ads CSV files and ERP sales workbooks.
- Joins data by `marketplace + sku + asin`.
- Computes rolling product and search-term metrics.
- Produces HTML, JSON, Markdown, and Excel reports.
- Includes a local demo data generator so the project can run after clone.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_demo_data.py
.venv/bin/python main.py --marketplace ALL --safe-run
```

Reports are written under:

```text
data/output/safe_run/<timestamp>/
```

Open:

```text
latest_recommendations.html
dashboard.html
summary.html
```

## Demo Data

`scripts/setup_demo_data.py` creates fake runtime inputs:

```text
config/product_cost_config.xlsx
config/sku_alias_map.xlsx
data/raw_ads/ads_report_all.csv
data/raw_erp/sales_report_all.xlsx
```

These files are ignored by Git. The script refuses to overwrite existing files unless `--force` is passed.

## Use With Your Own Store

The demo can run immediately after clone. Real store operation requires your own exported files and mapping tables:

```text
config/product_cost_config.xlsx
config/sku_alias_map.xlsx
config/sku_asin_map.xlsx
config/product_keyword_rules.csv
data/raw_ads/
data/raw_erp/
```

Start from the examples in `config/templates/`, then keep real store files out of Git. Report quality depends on correct cost, SKU, ASIN, and marketplace mapping. If those inputs are incomplete, the generated recommendations should be treated as a smoke test instead of an operating decision.

## Public Data Boundary

The repository intentionally excludes:

```text
data/
database/
outputs/
logs/
real config/*.xlsx
real config/*.csv
browser profiles
cookies, sessions, tokens
generated report HTML/JSON/Excel files
```

Only demo templates under `config/templates/` are tracked.

## Validation

Run the test suite:

```bash
.venv/bin/python -m pytest
```

Run a report generation smoke test:

```bash
.venv/bin/python main.py --marketplace ALL --safe-run
```

## Notes

- Frontend checks are optional enrichment. Report generation does not require a browser.
- Live browser checks are disabled by default in daily workflows to avoid local permission prompts.
- Lingxing MCP support is optional and requires user-provided environment variables.
