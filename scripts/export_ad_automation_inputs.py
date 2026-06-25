from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "database" / "amazon_ops.db"
DEFAULT_OUTPUT_DIR = ROOT / "outputs"
MARKETPLACES = ["UK", "DE", "US"]


@dataclass(frozen=True)
class MarketplaceRule:
    zero_order_clicks: int
    zero_order_spend: float
    high_acos: float
    high_acos_clicks: int
    suggested_min_bid: float
    currency: str


RULES: dict[str, MarketplaceRule] = {
    "UK": MarketplaceRule(15, 4.0, 0.50, 20, 0.10, "GBP"),
    "DE": MarketplaceRule(12, 4.0, 0.50, 15, 0.10, "EUR"),
    "US": MarketplaceRule(20, 6.0, 0.50, 20, 0.12, "USD"),
}


REQUIRED_AD_COLUMNS = {
    "marketplace",
    "date",
    "campaign_id",
    "ad_group_id",
    "sku",
    "asin",
    "search_term",
    "targeting",
    "campaign_name",
    "ad_group_name",
    "match_type",
    "impressions",
    "clicks",
    "spend",
    "ad_orders",
    "ad_sales",
}


OPTIONAL_AD_COLUMNS_NOT_IN_CURRENT_DB = [
    "placement_classification",
    "placement_name",
    "campaign_status",
    "ad_group_status",
    "ad_status",
    "campaign_bid_strategy",
    "campaign_budget_amount",
    "CPC_bid",
    "advertised_product_marketplace",
]


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"找不到数据库：{db_path}")
    return sqlite3.connect(db_path)


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    exists = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        [table_name],
    ).fetchone()
    if not exists:
        return set()
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _read_ads(connection: sqlite3.Connection) -> tuple[pd.DataFrame, list[str]]:
    columns = _table_columns(connection, "ads_import_raw")
    if not columns:
        return pd.DataFrame(), ["缺少表 ads_import_raw，需先运行现有导入/日报流程。"]
    missing = sorted(REQUIRED_AD_COLUMNS - columns)
    if missing:
        return pd.DataFrame(), [f"ads_import_raw 缺少必要字段：{', '.join(missing)}"]
    query = """
        SELECT
            marketplace,
            date,
            campaign_id,
            ad_group_id,
            sku,
            asin,
            search_term,
            targeting,
            campaign_name,
            ad_group_name,
            match_type,
            impressions,
            clicks,
            spend,
            ad_orders,
            ad_sales
        FROM ads_import_raw
        WHERE marketplace IN ('UK', 'DE', 'US')
    """
    ads = pd.read_sql_query(query, connection)
    if ads.empty:
        return ads, ["ads_import_raw 中没有 UK/DE/US 广告数据。"]
    ads["date"] = pd.to_datetime(ads["date"], errors="coerce")
    for column in ["impressions", "clicks", "spend", "ad_orders", "ad_sales"]:
        ads[column] = pd.to_numeric(ads[column], errors="coerce").fillna(0.0)
    for column in ["marketplace", "campaign_id", "ad_group_id", "sku", "asin", "search_term", "targeting", "campaign_name", "ad_group_name", "match_type"]:
        ads[column] = ads[column].fillna("").astype(str).str.strip()
    return ads[ads["date"].notna()].copy(), []


def _read_product_daily(connection: sqlite3.Connection) -> tuple[pd.DataFrame, list[str]]:
    columns = _table_columns(connection, "product_daily")
    if not columns:
        return pd.DataFrame(), ["缺少表 product_daily，成本/销售匹配检查只能降级。"]
    desired = [
        "marketplace",
        "date",
        "sku",
        "asin",
        "unit_cost",
        "shipping_cost",
        "handling_fee",
        "total_orders",
        "total_sales",
    ]
    selected = [column for column in desired if column in columns]
    frame = pd.read_sql_query(f"SELECT {', '.join(selected)} FROM product_daily", connection)
    if frame.empty:
        return frame, ["product_daily 为空，成本/销售匹配检查只能降级。"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ["unit_cost", "shipping_cost", "handling_fee", "total_orders", "total_sales"]:
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ["marketplace", "sku", "asin"]:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    return frame[frame["date"].notna()].copy(), []


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    result = numerator / denominator.where(denominator > 0)
    return result.replace([float("inf"), float("-inf")], pd.NA)


def _fmt_amount(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").round(2)


def _fmt_ratio(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").round(4)


def _window_by_marketplace(ads: pd.DataFrame, days: int) -> tuple[pd.DataFrame, dict[str, tuple[str | None, str | None]]]:
    windows: list[pd.DataFrame] = []
    ranges: dict[str, tuple[str | None, str | None]] = {}
    for marketplace in MARKETPLACES:
        scoped = ads[ads["marketplace"].str.upper() == marketplace].copy()
        if scoped.empty:
            ranges[marketplace] = (None, None)
            continue
        end_date = scoped["date"].max().normalize()
        start_date = end_date - timedelta(days=days - 1)
        window = scoped[(scoped["date"] >= start_date) & (scoped["date"] <= end_date)].copy()
        windows.append(window)
        ranges[marketplace] = (start_date.date().isoformat(), end_date.date().isoformat())
    if not windows:
        return pd.DataFrame(columns=ads.columns), ranges
    return pd.concat(windows, ignore_index=True), ranges


def _targeting_type(row: pd.Series) -> str:
    search_term = str(row.get("search_term") or "").strip()
    targeting = str(row.get("targeting") or "").strip()
    if targeting.upper().startswith("B0"):
        return "asin_target"
    if search_term and search_term != targeting:
        return "search_term"
    if targeting:
        return "targeting"
    return "unknown"


def _build_candidates(window_ads: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "marketplace",
        "campaign_name",
        "campaign_id",
        "ad_group_name",
        "ad_group_id",
        "sku",
        "asin",
        "targeting",
        "search_term",
        "match_type",
    ]
    if window_ads.empty:
        return pd.DataFrame(columns=[
            *group_columns,
            "targeting_type",
            "impressions",
            "clicks",
            "spend",
            "ad_orders",
            "ad_sales",
            "ACOS",
            "CTR",
            "CPC",
            "CVR",
            "建议动作",
            "建议原因",
            "建议降价幅度",
            "建议最低竞价",
            "risk_level",
        ])
    grouped = (
        window_ads.groupby(group_columns, dropna=False, as_index=False)[["impressions", "clicks", "spend", "ad_orders", "ad_sales"]]
        .sum()
    )
    grouped["ACOS"] = _safe_div(grouped["spend"], grouped["ad_sales"])
    grouped["CTR"] = _safe_div(grouped["clicks"], grouped["impressions"])
    grouped["CPC"] = _safe_div(grouped["spend"], grouped["clicks"])
    grouped["CVR"] = _safe_div(grouped["ad_orders"], grouped["clicks"])
    grouped["targeting_type"] = grouped.apply(_targeting_type, axis=1)

    actions: list[str] = []
    reasons: list[str] = []
    lower_amounts: list[str] = []
    min_bids: list[float] = []
    risk_levels: list[str] = []

    for _, row in grouped.iterrows():
        marketplace = str(row["marketplace"]).upper()
        rule = RULES[marketplace]
        clicks = float(row["clicks"] or 0)
        spend = float(row["spend"] or 0)
        orders = float(row["ad_orders"] or 0)
        acos = row["ACOS"]
        min_bids.append(rule.suggested_min_bid)

        action = "keep"
        reason = "未命中保守自动化阈值，先保留。"
        lower = ""
        risk = "low"

        if orders == 0 and spend >= 2 * rule.zero_order_spend:
            action = "pause_or_negate"
            reason = f"严重浪费：30天无广告订单且花费 >= {2 * rule.zero_order_spend:.2f} {rule.currency}，应人工判断暂停或否定。"
            lower = ""
            risk = "high"
        elif orders == 0 and clicks >= rule.zero_order_clicks and spend >= rule.zero_order_spend:
            action = "lower_bid"
            reason = f"无单烧钱：点击 >= {rule.zero_order_clicks} 且花费 >= {rule.zero_order_spend:.2f} {rule.currency}。"
            lower = "25%"
            risk = "medium"
        elif pd.notna(acos) and orders > 0 and float(acos) > rule.high_acos and clicks >= rule.high_acos_clicks:
            action = "lower_bid"
            reason = f"高 ACoS：ACOS > {rule.high_acos:.0%} 且有订单，先降竞价控亏。"
            lower = "20%"
            risk = "medium"
        elif pd.notna(acos) and float(acos) <= 0.25 and orders >= 2 and clicks >= 10:
            action = "increase_later"
            reason = "低 ACoS 有订单，但先控亏后放量，暂不建议马上加价。"
            lower = ""
            risk = "low"

        actions.append(action)
        reasons.append(reason)
        lower_amounts.append(lower)
        risk_levels.append(risk)

    grouped["建议动作"] = actions
    grouped["建议原因"] = reasons
    grouped["建议降价幅度"] = lower_amounts
    grouped["建议最低竞价"] = min_bids
    grouped["risk_level"] = risk_levels
    _fmt_amount(grouped, ["spend", "ad_sales", "CPC", "建议最低竞价"])
    _fmt_ratio(grouped, ["ACOS", "CTR", "CVR"])
    return grouped[
        [
            "marketplace",
            "campaign_name",
            "campaign_id",
            "ad_group_name",
            "ad_group_id",
            "sku",
            "asin",
            "targeting",
            "search_term",
            "match_type",
            "targeting_type",
            "impressions",
            "clicks",
            "spend",
            "ad_orders",
            "ad_sales",
            "ACOS",
            "CTR",
            "CPC",
            "CVR",
            "建议动作",
            "建议原因",
            "建议降价幅度",
            "建议最低竞价",
            "risk_level",
        ]
    ].copy()


def _build_summary(window_ads: pd.DataFrame, candidates: pd.DataFrame, date_ranges: dict[str, tuple[str | None, str | None]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for marketplace in MARKETPLACES:
        rule = RULES[marketplace]
        scoped = window_ads[window_ads["marketplace"].str.upper() == marketplace]
        candidate_scope = candidates[candidates["marketplace"].str.upper() == marketplace] if not candidates.empty else pd.DataFrame()
        spend = float(scoped["spend"].sum()) if not scoped.empty else 0.0
        sales = float(scoped["ad_sales"].sum()) if not scoped.empty else 0.0
        orders = float(scoped["ad_orders"].sum()) if not scoped.empty else 0.0
        clicks = float(scoped["clicks"].sum()) if not scoped.empty else 0.0
        impressions = float(scoped["impressions"].sum()) if not scoped.empty else 0.0
        zero_scope = candidate_scope[candidate_scope["ad_orders"].fillna(0) <= 0] if not candidate_scope.empty else pd.DataFrame()
        high_scope = (
            candidate_scope[(candidate_scope["ad_orders"].fillna(0) > 0) & (candidate_scope["ACOS"].fillna(0) > rule.high_acos)]
            if not candidate_scope.empty
            else pd.DataFrame()
        )
        start, end = date_ranges.get(marketplace, (None, None))
        rows.append(
            {
                "marketplace": marketplace,
                "date_start": start or "",
                "date_end": end or "",
                "spend": round(spend, 2),
                "ad_sales": round(sales, 2),
                "ad_orders": round(orders, 2),
                "clicks": round(clicks, 2),
                "impressions": round(impressions, 2),
                "ACOS": round(spend / sales, 4) if sales > 0 else pd.NA,
                "CTR": round(clicks / impressions, 4) if impressions > 0 else pd.NA,
                "CPC": round(spend / clicks, 2) if clicks > 0 else pd.NA,
                "CVR": round(orders / clicks, 4) if clicks > 0 else pd.NA,
                "zero_order_spend": round(float(zero_scope["spend"].sum()), 2) if not zero_scope.empty else 0.0,
                "zero_order_clicks": round(float(zero_scope["clicks"].sum()), 2) if not zero_scope.empty else 0.0,
                "high_acos_spend": round(float(high_scope["spend"].sum()), 2) if not high_scope.empty else 0.0,
                "建议的无单烧钱花费阈值": rule.zero_order_spend,
                "建议的无单烧钱点击阈值": rule.zero_order_clicks,
                "建议的高ACoS阈值": rule.high_acos,
                "建议最低竞价": rule.suggested_min_bid,
            }
        )
    return pd.DataFrame(rows)


def _build_zero_order_waste(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    rows = candidates[candidates["ad_orders"].fillna(0) <= 0].copy()
    return rows[
        [
            "marketplace",
            "campaign_name",
            "ad_group_name",
            "sku",
            "asin",
            "targeting",
            "search_term",
            "clicks",
            "spend",
            "impressions",
            "CTR",
            "CPC",
            "建议动作",
            "建议原因",
        ]
    ].sort_values(["marketplace", "spend", "clicks"], ascending=[True, False, False])


def _build_high_acos_targets(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    masks = []
    for _, row in candidates.iterrows():
        marketplace = str(row.get("marketplace") or "").upper()
        rule = RULES.get(marketplace)
        acos = row.get("ACOS")
        masks.append(bool(rule and pd.notna(acos) and float(row.get("ad_orders") or 0) > 0 and float(acos) > rule.high_acos))
    rows = candidates[pd.Series(masks, index=candidates.index)].copy()
    return rows[
        [
            "marketplace",
            "campaign_name",
            "ad_group_name",
            "sku",
            "asin",
            "targeting",
            "search_term",
            "clicks",
            "spend",
            "ad_orders",
            "ad_sales",
            "ACOS",
            "CPC",
            "CVR",
            "建议动作",
            "建议原因",
        ]
    ].sort_values(["marketplace", "ACOS", "spend"], ascending=[True, False, False])


def _build_data_quality(
    ads: pd.DataFrame,
    window_ads: pd.DataFrame,
    product_daily: pd.DataFrame,
    date_ranges: dict[str, tuple[str | None, str | None]],
    source_warnings: list[str],
) -> pd.DataFrame:
    product_latest = pd.DataFrame()
    if not product_daily.empty:
        product_latest = (
            product_daily.sort_values("date")
            .groupby(["marketplace", "sku", "asin"], as_index=False)
            .tail(1)
            .copy()
        )
    rows: list[dict[str, object]] = []
    for marketplace in MARKETPLACES:
        scoped_all = ads[ads["marketplace"].str.upper() == marketplace] if not ads.empty else pd.DataFrame()
        scoped = window_ads[window_ads["marketplace"].str.upper() == marketplace] if not window_ads.empty else pd.DataFrame()
        start, end = date_ranges.get(marketplace, (None, None))
        missing_sku_count = int((scoped["sku"].fillna("").astype(str).str.strip() == "").sum()) if not scoped.empty else 0
        missing_asin_count = int((scoped["asin"].fillna("").astype(str).str.strip() == "").sum()) if not scoped.empty else 0
        missing_cost_count = 0
        missing_sales_match_count = 0
        notes: list[str] = []
        if scoped_all.empty:
            notes.append("该 marketplace 没有广告数据。")
        if not product_latest.empty and not scoped.empty:
            objects = scoped[["marketplace", "sku", "asin"]].drop_duplicates()
            merged = objects.merge(product_latest, on=["marketplace", "sku", "asin"], how="left")
            cost_columns = ["unit_cost", "shipping_cost", "handling_fee"]
            missing_cost_count = int(merged[cost_columns].isna().all(axis=1).sum())
            missing_sales_match_count = int(merged["date"].isna().sum())
        elif not scoped.empty:
            missing_sales_match_count = int(scoped[["marketplace", "sku", "asin"]].drop_duplicates().shape[0])
            notes.append("product_daily 不可用，无法核对成本和销售匹配。")
        missing_optional = [
            column for column in OPTIONAL_AD_COLUMNS_NOT_IN_CURRENT_DB if column not in _table_columns_for_quality
        ]
        if missing_optional:
            notes.append("当前 SQLite 广告表未保留字段：" + ", ".join(missing_optional) + "；如需这些字段，请从新版广告报告导入并扩展只读字段暴露。")
        for warning in source_warnings:
            if warning not in notes:
                notes.append(warning)
        rows.append(
            {
                "marketplace": marketplace,
                "ads_rows": int(len(scoped)),
                "date_start": start or "",
                "date_end": end or "",
                "missing_sku_count": missing_sku_count,
                "missing_asin_count": missing_asin_count,
                "missing_cost_count": missing_cost_count,
                "missing_sales_match_count": missing_sales_match_count,
                "notes": "；".join(notes) if notes else "OK",
            }
        )
    return pd.DataFrame(rows)


_table_columns_for_quality: set[str] = set()


def _autosize_sheet(writer: pd.ExcelWriter, sheet_name: str, frame: pd.DataFrame) -> None:
    worksheet = writer.sheets[sheet_name]
    for idx, column in enumerate(frame.columns, start=1):
        values = [str(column), *[str(value) for value in frame[column].head(200).fillna("").tolist()]]
        width = min(max(len(value) for value in values) + 2, 60)
        worksheet.column_dimensions[worksheet.cell(row=1, column=idx).column_letter].width = width
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions


def _write_excel(output_path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            export = frame.copy()
            if export.empty:
                export = pd.DataFrame({"说明": ["无匹配数据"]})
            export.to_excel(writer, sheet_name=sheet_name, index=False)
            _autosize_sheet(writer, sheet_name, export)


def build_export(days: int, output_path: Path, db_path: Path = DEFAULT_DB_PATH) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    global _table_columns_for_quality
    with _connect(db_path) as connection:
        _table_columns_for_quality = _table_columns(connection, "ads_import_raw")
        ads, ads_warnings = _read_ads(connection)
        product_daily, product_warnings = _read_product_daily(connection)
    source_warnings = [*ads_warnings, *product_warnings]
    window_ads, date_ranges = _window_by_marketplace(ads, days)
    candidates = _build_candidates(window_ads)
    summary = _build_summary(window_ads, candidates, date_ranges)
    zero_order_waste = _build_zero_order_waste(candidates)
    high_acos_targets = _build_high_acos_targets(candidates)
    data_quality = _build_data_quality(ads, window_ads, product_daily, date_ranges, source_warnings)
    sheets = {
        "summary_by_marketplace": summary,
        "automation_candidates": candidates.sort_values(["marketplace", "risk_level", "spend"], ascending=[True, True, False]) if not candidates.empty else candidates,
        "zero_order_waste": zero_order_waste,
        "high_acos_targets": high_acos_targets,
        "data_quality": data_quality,
    }
    _write_excel(output_path, sheets)
    stats = {
        "output_path": str(output_path.resolve()),
        "date_ranges": date_ranges,
        "zero_order_counts": {
            marketplace: int(
                len(candidates[(candidates["marketplace"].str.upper() == marketplace) & (candidates["ad_orders"].fillna(0) <= 0)])
            )
            if not candidates.empty
            else 0
            for marketplace in MARKETPLACES
        },
        "threshold_zero_order_counts": {
            marketplace: int(
                len(
                    candidates[
                        (candidates["marketplace"].str.upper() == marketplace)
                        & (candidates["建议原因"].astype(str).str.contains("无单烧钱|严重浪费", regex=True))
                    ]
                )
            )
            if not candidates.empty
            else 0
            for marketplace in MARKETPLACES
        },
        "high_acos_counts": {
            marketplace: int(len(high_acos_targets[high_acos_targets["marketplace"].str.upper() == marketplace]))
            if not high_acos_targets.empty
            else 0
            for marketplace in MARKETPLACES
        },
        "quality_warnings": data_quality[data_quality["notes"] != "OK"][["marketplace", "notes"]].to_dict("records"),
    }
    return sheets, stats


def _default_output_path() -> Path:
    today = datetime.now().date().isoformat()
    return DEFAULT_OUTPUT_DIR / f"ad_automation_inputs_{today}.xlsx"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出广告自动化规则设置输入数据。")
    parser.add_argument("--days", type=int, default=30, help="每个 marketplace 从最新广告日期回看天数，默认 30。")
    parser.add_argument("--output", type=Path, default=_default_output_path(), help="输出 Excel 路径。")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite 数据库路径，默认 database/amazon_ops.db。")
    args = parser.parse_args()
    if args.days <= 0:
        raise SystemExit("--days 必须大于 0")
    _, stats = build_export(days=args.days, output_path=args.output, db_path=args.db)
    print(f"导出文件路径：{stats['output_path']}")
    print("各 marketplace 日期范围：")
    for marketplace in MARKETPLACES:
        start, end = stats["date_ranges"].get(marketplace, (None, None))
        print(f"- {marketplace}: {start or '无数据'} ~ {end or '无数据'}")
    print("无单烧钱对象数量（命中阈值，含严重浪费）：")
    for marketplace, count in stats["threshold_zero_order_counts"].items():
        print(f"- {marketplace}: {count}")
    print("高 ACoS 对象数量：")
    for marketplace, count in stats["high_acos_counts"].items():
        print(f"- {marketplace}: {count}")
    warnings = stats["quality_warnings"]
    print("数据质量警告：")
    if not warnings:
        print("- 无")
    else:
        for item in warnings:
            print(f"- {item['marketplace']}: {item['notes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
