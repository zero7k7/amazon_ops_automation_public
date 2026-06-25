# Amazon Ops Automation

Offline Amazon marketplace intelligence console for turning ads, sales, cost, SKU, and ASIN exports into operator-ready reports, action queues, and review workflows.

This public repository is a clean demo snapshot. It shows the architecture, report workflow, and local operating console without exposing private store data, historical outputs, browser profiles, cookies, sessions, or real cost/SKU configuration files.

## Repository Scope

This repo is intended for three uses:

- Review the reporting and decision-workflow architecture.
- Run a local demo with generated fake data.
- Adapt the pipeline to your own Amazon marketplace exports.

It is not a hosted SaaS product, a managed Amazon API integration, or a plug-and-play decision engine. Real operating decisions require your own clean exports, cost tables, SKU/ASIN mapping, and marketplace-specific validation.

## What It Does

- Parses Amazon ads CSV files and ERP sales workbooks.
- Joins data by `marketplace + sku + asin`.
- Computes rolling product and search-term metrics.
- Produces HTML, JSON, Markdown, and Excel reports.
- Builds an operations workbench for ad actions, low-budget keyword tests, frontend evidence, and review queues.
- Keeps optional Amazon frontend checks as best-effort enrichment, not a hard dependency.
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

The generated demo data is synthetic. It is only useful for checking that the pipeline runs and that the report UI renders.

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

Typical private inputs are:

- Amazon ads report exports.
- ERP sales exports.
- Seller Central custom analytics exports.
- Product cost configuration.
- SKU alias and SKU/ASIN mapping tables.
- Marketplace location settings for optional frontend evidence.

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

Before sharing a fork publicly, verify:

```bash
git status --short data config
git grep -n -I -E "token|secret|password|cookie|session|Authorization|Bearer"
```

No real business exports, generated reports, local browser profiles, credentials, or private configuration files should be committed.

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
