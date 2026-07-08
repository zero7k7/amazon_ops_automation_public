# Demo Runbook

Use this runbook to verify a clean clone without private business data.

## Install

macOS or Linux shell:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
$env:PYTHONUTF8="1"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Generate Demo Inputs

macOS or Linux shell:

```bash
.venv/bin/python scripts/setup_demo_data.py
```

Windows PowerShell:

```powershell
$env:PYTHONUTF8="1"
.\.venv\Scripts\python.exe scripts\setup_demo_data.py
```

Generated files are ignored by Git:

```text
config/product_cost_config.xlsx
config/sku_alias_map.xlsx
data/raw_ads/ads_report_all.csv
data/raw_erp/sales_report_all.xlsx
data/raw_amazon_custom/<MARKET>/traffic_sales_*.xlsx
data/raw_amazon_custom/<MARKET>/search_query_performance_*.xlsx
data/output/frontend_check_results.json
data/output/sellersprite_reverse_asin_results.json
data/output/sellersprite_competitor_discovery_results.json
data/output/sellersprite_history_snapshots.jsonl
data/output/autoopt_feedback_input.json
```

The demo inputs use synthetic office products and `B0DEMO...` ASINs. They exercise ads, ERP sales, cost mapping, enhanced custom analytics, frontend cache display, SellerSprite-style enrichment, competitor discovery, historical trend snapshots, and executed feedback review without depending on live Amazon pages.

## Run The Demo Console

macOS or Linux shell:

```bash
.venv/bin/python scripts/run_report_window.py --workflow daily
```

Windows PowerShell:

```powershell
$env:PYTHONUTF8="1"
.\run_today_report.bat
```

The default demo starts the local button service and opens:

```text
http://127.0.0.1:8765/report/latest_recommendations.html
```

Keep the terminal window open while using report buttons. Demo reports are written under `data/output/`.

## Validate The Demo

macOS or Linux shell:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/validate_showcase_mvp.py
```

Windows PowerShell:

```powershell
$env:PYTHONUTF8="1"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\validate_showcase_mvp.py
```

The validation should create safe-run output only under `data/output/safe_run/`. Generated reports, real exports, cookies, sessions, browser profiles, and local virtual environments must stay out of Git.

For a read-only report generation check without starting the local service, run:

```bash
.venv/bin/python main.py --marketplace ALL --safe-run
```

Windows PowerShell:

```powershell
$env:PYTHONUTF8="1"
.\.venv\Scripts\python.exe main.py --marketplace ALL --safe-run
```
