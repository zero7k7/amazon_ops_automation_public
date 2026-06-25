# Demo Runbook

Use this runbook to verify a clean clone without private business data.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

## Generate Demo Inputs

```bash
.venv/bin/python scripts/setup_demo_data.py
```

Generated files are ignored by Git:

```text
config/product_cost_config.xlsx
config/sku_alias_map.xlsx
data/raw_ads/ads_report_all.csv
data/raw_erp/sales_report_all.xlsx
```

## Generate Reports

```bash
.venv/bin/python main.py --marketplace ALL --safe-run
```

Expected outputs:

```text
data/output/safe_run/<timestamp>/latest_recommendations.html
data/output/safe_run/<timestamp>/dashboard.html
data/output/safe_run/<timestamp>/summary.html
data/output/safe_run/<timestamp>/latest_analysis.json
data/output/safe_run/<timestamp>/amazon_ops_report_YYYY-MM-DD.xlsx
```
