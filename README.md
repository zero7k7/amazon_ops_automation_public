# Amazon Ops Automation

## 广告报表导出字段

后台自定义广告报表列时，优先按本节勾选。判断依据是 `src/parse_ads_report.py` 的 `REQUIRED_ADS_COLUMNS`、`ADS_FIELD_SPECS` 和 `ATTRIBUTION_FIELDS`。少选核心字段会直接影响导入，少选归因和搜索词字段会降低广告动作判断质量。

<details>
<summary>详情：广告后台定制列截图</summary>

![Amazon 广告定制列截图](public/amazon_ads_custom_columns_2026_06_25.png)

</details>

提交表必须有的中文表头：

```text
日期	广告活动名称	推广的商品 SKU	推广的商品编号	推广的商品站点	展示量	点击量	总成本	购买量（所有浏览次数）	销售额
```

建议提交表完整中文表头，可直接复制到 Excel 第一行：

```text
日期	广告产品	预算货币	广告活动编号	广告活动名称	广告活动投放状态	广告活动预算金额	广告活动预算类型	广告活动竞价方案	广告活动成本类型	投放广告活动的国家/地区	广告组合编号	广告组合名称	推广的商品编号	推广的商品 SKU	推广的商品站点	广告组编号	广告组名称	广告组投放状态	广告组计费模式	广告 ID	广告名称	广告投放状态	搜索词	匹配的目标	投放值	投放匹配类型	广告位名称	广告位分类	展示量	点击量	总点击量	点击率	CPC	总成本	ROAS	购买量（所有浏览次数）	销量（所有浏览次数）	已售商品数量（所有浏览次数）	购买率（所有浏览次数）	销售额	归因于点击的购买量	归因于点击的销售额	归因于点击的 ROAS	归因于点击的单次购买成本	归因于点击的购买量（推广的商品）	归因于点击的销售额（推广的商品）	由浏览产生的销售额（推广的商品）	归因于点击的购买量（光环）	归因于点击的销售额（品牌光环）	归因于点击的已售商品数量（品牌光环）	无效展示率	无效点击
```

后台尺寸列建议勾选：

1. 日期
2. 广告产品
3. 预算货币
4. 广告活动编号
5. 广告活动名称
6. 广告活动预算金额
7. 广告活动预算类型
8. 广告活动投放状态
9. 广告活动开始日期
10. 广告活动竞价方案
11. 广告活动成本类型
12. 投放广告活动的国家/地区
13. 广告组合编号
14. 广告组合名称
15. 推广的商品编号
16. 推广的商品 SKU
17. 推广的商品站点
18. 广告组编号
19. 广告组名称
20. 广告组投放状态
21. 广告组计费模式
22. 广告 ID
23. 广告名称
24. 广告投放状态
25. 搜索词
26. 匹配的目标
27. 投放值
28. 投放匹配类型
29. 广告位名称
30. 广告位分类

后台指标列建议勾选：

1. 展示量
2. 点击量
3. 无效展示率
4. 无效点击
5. 总点击量
6. 点击率
7. CPC
8. 广告库存成本
9. 总成本
10. ROAS
11. 购买量（所有浏览次数）
12. 销量（所有浏览次数）
13. 已售商品数量（所有浏览次数）
14. 购买率（所有浏览次数）
15. 销售额
16. 归因于点击的购买量
17. 归因于点击的销售额
18. 归因于点击的 ROAS
19. 归因于点击的单次购买成本
20. 归因于点击的购买量（推广的商品）
21. 归因于点击的销售额（推广的商品）
22. 由浏览产生的销售额（推广的商品）
23. 归因于点击的购买量（光环）
24. 归因于点击的销售额（品牌光环）
25. 归因于点击的已售商品数量（品牌光环）

风险判断：

1. `广告库存成本` 和 `总成本` 都建议保留。系统当前把 `总成本` 作为核心成本字段，同时也把 `广告库存成本` 识别为成本来源。
2. `搜索词`、`匹配的目标`、`投放值`、`投放匹配类型` 缺失时，产品级报表还能跑，但搜索词和 ASIN 定向动作会明显变弱。
3. 点击归因字段缺失时，系统会按 0 兜底。风险是推广 SKU 订单和光环订单无法拆分，容易把光环成交误判成投放对象有效。
4. `由浏览产生的销售额（推广的商品）` 当前核心解析不依赖，但历史字段审计里出现过该列，保留它可以降低后续归因口径变化风险。
5. 当前代码只检查 `bid` 或 `keyword_bid` 这类字段名。中文后台里的 `目标竞价` 即使导出，当前版本也未必会被识别为具体竞价字段。影响是报告可以给降竞价比例，但不能稳定给具体新 bid。

Offline Amazon marketplace intelligence console for turning ads, sales, cost, SKU, and ASIN exports into operator-ready reports, action queues, and review workflows.

This public repository is a clean demo snapshot. It shows the architecture, report workflow, and local operating console without exposing private store data, historical outputs, browser profiles, cookies, sessions, or real cost/SKU configuration files.

## Repository Scope

This repo is intended for three uses:

- Review the reporting and decision-workflow architecture.
- Run a local demo with generated fake data.
- Adapt the pipeline to your own Amazon marketplace exports.

It is not a hosted SaaS product, a managed Amazon API integration, or a plug-and-play decision engine. Real operating decisions require your own clean exports, cost tables, SKU/ASIN mapping, and marketplace-specific validation.

## Platform Status

This public demo is currently a macOS-first local version. The checked demo workflow is validated on macOS with a local Python environment.

- Core report generation is plain Python and should be portable after dependency setup.
- Local browser, clipboard, shell, and daily-ops conveniences are macOS-validated.
- Windows users should treat this as source code plus a demo pipeline until Windows launch scripts and browser/clipboard fallbacks are separately verified.

## What It Does

- Parses Amazon ads CSV files and ERP sales workbooks.
- Joins data by `marketplace + sku + asin`.
- Computes rolling product and search-term metrics.
- Produces HTML, JSON, Markdown, and Excel reports.
- Builds an operations workbench for ad actions, low-budget keyword tests, frontend evidence, and review queues.
- Keeps optional Amazon frontend checks as best-effort enrichment, not a hard dependency.
- Includes a local demo data generator so the project can run after clone.

## Quick Start (macOS-validated)

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
