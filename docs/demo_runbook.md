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
.\.venv\Scripts\python.exe scripts\setup_demo_data.py
```

Generated files are ignored by Git:

```text
config/product_cost_config.xlsx
config/sku_alias_map.xlsx
data/raw_ads/ads_report_all.csv
data/raw_erp/sales_report_all.xlsx
```

## Generate Reports

macOS or Linux shell:

```bash
.venv/bin/python main.py --marketplace ALL --safe-run
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py --marketplace ALL --safe-run
```

Expected outputs:

```text
data/output/safe_run/<timestamp>/latest_recommendations.html
data/output/safe_run/<timestamp>/dashboard.html
data/output/safe_run/<timestamp>/summary.html
data/output/safe_run/<timestamp>/latest_analysis.json
data/output/safe_run/<timestamp>/amazon_ops_report_YYYY-MM-DD.xlsx
```

## Validate The Demo

macOS or Linux shell:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/validate_showcase_mvp.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\validate_showcase_mvp.py
```

The validation should create safe-run output only under `data/output/safe_run/`. Generated reports, real exports, cookies, sessions, browser profiles, and local virtual environments must stay out of Git.
