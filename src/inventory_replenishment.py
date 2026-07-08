from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from .parse_erp_sales import load_erp_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY_PATH = ROOT / "data" / "inventory.xlsx"
OUTPUT_DIR = ROOT / "data" / "output"
RAW_ERP_DIR = ROOT / "data" / "raw_erp"

PRODUCTION_DAYS = 30
INBOUND_DAYS = {"UK": 70, "DE": 70, "US": 40}
TARGET_BUFFER_DAYS = 30

PRODUCT_ALIASES = {
    "demo_desk_lamp": ["demo desk lamp", "led desk lamp", "reading lamp"],
    "demo_notebook": ["demo notebook", "spiral notebook", "ruled notebook"],
    "demo_cable_ties": ["demo cable ties", "reusable cable ties", "wire ties"],
}

_RAW_ERP_INVENTORY_CACHE: dict[str, pd.DataFrame] = {}


@dataclass(frozen=True)
class InventorySourceRow:
    source_product_name: str
    current_inventory: float | None
    box_count: float | None
    latest_notes: str


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _norm_name(value: object) -> str:
    return re.sub(r"[\s_\-（）()]+", "", _clean(value).lower())


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean(value).replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _format_qty(value: float | None) -> str:
    if value is None:
        return "N/A"
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:.1f}"


def _format_days(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= 9999:
        return "9999+"
    if value >= 100:
        return str(int(round(value)))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _latest_inventory_notes(row: pd.Series) -> str:
    base_columns = {"品名", "库存余量", "库存箱数", "unnamed: 0", "Unnamed: 0"}
    events: list[tuple[str, float]] = []
    for column, value in row.items():
        if str(column) in base_columns:
            continue
        qty = _to_float(value)
        if qty is None or abs(qty) < 0.001:
            continue
        label = column.strftime("%Y-%m-%d") if hasattr(column, "strftime") else str(column)
        events.append((label, qty))
    return "；".join(f"{label} {_format_qty(qty)}" for label, qty in events[-4:])


def load_inventory_source(path: Path = DEFAULT_INVENTORY_PATH, sheet_name: str = "库存情况") -> tuple[list[InventorySourceRow], list[dict[str, str]]]:
    if not path.exists():
        return [], [{"level": "warning", "message": f"库存文件不存在：{path}"}]
    try:
        frame = pd.read_excel(path, sheet_name=sheet_name)
    except Exception as exc:
        return [], [{"level": "warning", "message": f"库存文件读取失败：{exc}"}]
    if frame.empty:
        return [], [{"level": "warning", "message": f"库存表为空：{sheet_name}"}]
    warnings: list[dict[str, str]] = []
    rows: list[InventorySourceRow] = []
    for _, row in frame.iterrows():
        name = _clean(row.get("品名"))
        if not name:
            continue
        rows.append(
            InventorySourceRow(
                source_product_name=name,
                current_inventory=_to_float(row.get("库存余量")),
                box_count=_to_float(row.get("库存箱数")),
                latest_notes=_latest_inventory_notes(row),
            )
        )
    if not rows:
        warnings.append({"level": "warning", "message": "库存情况中没有识别到品名行"})
    return rows, warnings


def _candidate_product_rows(sku_map: pd.DataFrame, cost_config: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for frame in [sku_map, cost_config]:
        if frame is None or frame.empty:
            continue
        working = frame.copy()
        for column in ["marketplace", "sku", "asin", "product_name"]:
            if column not in working.columns:
                working[column] = ""
            working[column] = working[column].fillna("").astype(str).str.strip()
        frames.append(working[["marketplace", "sku", "asin", "product_name"]])
    if not frames:
        return pd.DataFrame(columns=["marketplace", "sku", "asin", "product_name"])
    combined = pd.concat(frames, ignore_index=True)
    combined["marketplace"] = combined["marketplace"].astype(str).str.upper()
    combined = combined[(combined["marketplace"] != "") & (combined["asin"] != "")]
    return combined.drop_duplicates(subset=["marketplace", "sku", "asin"], keep="first").reset_index(drop=True)


def _alias_terms(source_product_name: str) -> list[str]:
    terms = [source_product_name]
    terms.extend(PRODUCT_ALIASES.get(source_product_name, []))
    norm_source = _norm_name(source_product_name)
    for key, values in PRODUCT_ALIASES.items():
        if _norm_name(key) == norm_source:
            terms.extend(values)
    return list(dict.fromkeys(term for term in terms if _clean(term)))


def _matches_inventory_name(source_product_name: str, target_product_name: str) -> bool:
    source_norm = _norm_name(source_product_name)
    target_norm = _norm_name(target_product_name)
    if not source_norm or not target_norm:
        return False
    if source_norm in target_norm or target_norm in source_norm:
        return True
    for term in _alias_terms(source_product_name):
        term_norm = _norm_name(term)
        if term_norm and (term_norm in target_norm or target_norm in term_norm):
            return True
    return False


def _manual_restock_recovery_keys(output_dir: Path = OUTPUT_DIR) -> set[tuple[str, str, str]]:
    path = output_dir / "autoopt_feedback_input.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    rows = payload.get("rows") if isinstance(payload, dict) else []
    keys: set[tuple[str, str, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = "；".join(
            _clean(row.get(key))
            for key in ["product_name", "diagnosis_type", "today_action", "confirmed_note", "manual_action_taken", "next_review"]
        )
        combined = text
        if "断货" not in combined or not any(token in combined for token in ["刚到货", "补货恢复", "恢复期"]):
            continue
        keys.add(
            (
                _clean(row.get("marketplace")).upper(),
                _clean(row.get("sku")),
                _clean(row.get("asin")).upper(),
            )
        )
    return keys


def _window_row(views, marketplace: str, sku: str, asin: str, days: int) -> dict[str, object]:
    frame = getattr(views, "product_windows", {}).get(days, pd.DataFrame())
    if frame is None or frame.empty:
        return {}
    working = frame.copy()
    working["marketplace"] = working["marketplace"].fillna("").astype(str).str.upper()
    if "sku" not in working.columns:
        working["sku"] = ""
    working["sku"] = working["sku"].fillna("").astype(str).str.strip()
    working["asin"] = working["asin"].fillna("").astype(str).str.upper()
    match = working[
        (working["marketplace"] == marketplace.upper())
        & (working["sku"] == sku)
        & (working["asin"] == asin.upper())
    ]
    if match.empty and not sku:
        match = working[(working["marketplace"] == marketplace.upper()) & (working["asin"] == asin.upper())]
    if match.empty:
        return {}
    return match.iloc[0].to_dict()


def _metric(views, marketplace: str, sku: str, asin: str, days: int, column: str) -> float:
    row = _window_row(views, marketplace, sku, asin, days)
    return _to_float(row.get(column)) or 0.0


def _latest_inventory_value(product_daily: pd.DataFrame, marketplace: str, sku: str, asin: str) -> dict[str, object]:
    if product_daily is None or product_daily.empty:
        return {}
    working = product_daily.copy()
    working["marketplace"] = working["marketplace"].fillna("").astype(str).str.upper()
    working["sku"] = working["sku"].fillna("").astype(str).str.strip()
    working["asin"] = working["asin"].fillna("").astype(str).str.upper()
    match = working[
        (working["marketplace"] == marketplace.upper())
        & (working["sku"] == sku)
        & (working["asin"] == asin.upper())
    ].copy()
    if match.empty:
        match = working[
            (working["marketplace"] == marketplace.upper())
            & (working["asin"] == asin.upper())
        ].copy()
    if match.empty:
        return {}
    match["date"] = pd.to_datetime(match["date"], errors="coerce")
    match = match.sort_values("date")
    for _, row in match.iloc[::-1].iterrows():
        fba_stock = _to_float(row.get("fba_stock"))
        available_stock = _to_float(row.get("available_stock"))
        fbm_stock = _to_float(row.get("fbm_stock"))
        if fba_stock is not None:
            return {
                "fba_stock": fba_stock,
                "available_stock": available_stock,
                "fbm_stock": fbm_stock,
                "inventory_date": row.get("date").date().isoformat() if pd.notna(row.get("date")) else "",
                "inventory_source": "ERP销量表-可用库存" if available_stock is not None else "ERP销量表-FBA可售",
            }
        if available_stock is not None:
            return {
                "fba_stock": None,
                "available_stock": available_stock,
                "fbm_stock": fbm_stock,
                "inventory_date": row.get("date").date().isoformat() if pd.notna(row.get("date")) else "",
                "inventory_source": "ERP销量表-可用库存",
            }
    return {}


def _raw_erp_inventory_frame(marketplace: str) -> pd.DataFrame:
    marketplace = str(marketplace or "").strip().upper()
    if marketplace in _RAW_ERP_INVENTORY_CACHE:
        return _RAW_ERP_INVENTORY_CACHE[marketplace]
    path = RAW_ERP_DIR / f"sales_report_{marketplace.lower()}.xlsx"
    if not path.exists():
        _RAW_ERP_INVENTORY_CACHE[marketplace] = pd.DataFrame()
        return _RAW_ERP_INVENTORY_CACHE[marketplace]
    try:
        frame, _ = load_erp_report(path)
    except Exception:
        frame = pd.DataFrame()
    _RAW_ERP_INVENTORY_CACHE[marketplace] = frame
    return frame


def _fallback_inventory_value_from_raw_erp(marketplace: str, sku: str, asin: str) -> dict[str, object]:
    frame = _raw_erp_inventory_frame(marketplace)
    return _latest_inventory_value(frame, marketplace, sku, asin)


def _local_inventory_for_product(source_rows: list[InventorySourceRow], product_name: str) -> InventorySourceRow | None:
    for source in source_rows:
        if _norm_name(source.source_product_name) == _norm_name(product_name):
            return source
    for source in source_rows:
        if _matches_inventory_name(source.source_product_name, product_name):
            return source
    return None


def _avg_daily_units(views, marketplace: str, sku: str, asin: str, days: int) -> float:
    return _metric(views, marketplace, sku, asin, days, "total_orders") / float(days)


def _selected_avg_daily(avg7: float, avg14: float, avg30: float) -> tuple[float, str]:
    if avg14 > 0:
        return avg14, "14d"
    if avg30 > 0:
        return avg30, "30d"
    if avg7 > 0:
        return avg7, "7d"
    return 0.0, "none"


def _lead_time(marketplace: str) -> tuple[int, int, int, int]:
    marketplace = marketplace.upper()
    inbound_days = INBOUND_DAYS.get(marketplace, 70)
    total = PRODUCTION_DAYS + inbound_days
    target = total + TARGET_BUFFER_DAYS
    return PRODUCTION_DAYS, inbound_days, total, target


def _status_label(level: str) -> str:
    return {
        "OUT_OF_STOCK": "断货",
        "LOW_STOCK": "低库存",
        "REPLENISH_SOON": "进入补货窗口",
        "HEALTHY": "健康",
        "RESTOCK_RECOVERY": "刚到货恢复期",
        "UNKNOWN": "销量基准不足",
        "UNMATCHED": "未匹配",
    }.get(level, level)


def build_inventory_replenishment(
    *,
    marketplace: str,
    sku_map: pd.DataFrame,
    cost_config: pd.DataFrame,
    views,
    product_daily: pd.DataFrame | None = None,
    report_date: date,
    inventory_path: Path = DEFAULT_INVENTORY_PATH,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, object]:
    source_rows, warnings = load_inventory_source(inventory_path)
    candidates = _candidate_product_rows(sku_map, cost_config)
    restock_keys = _manual_restock_recovery_keys(output_dir)
    rows: list[dict[str, object]] = []
    matched_sources: set[str] = set()
    marketplace = marketplace.upper()

    for _, candidate in candidates.iterrows():
        if str(candidate.get("marketplace") or "").upper() != marketplace:
            continue
        match = candidate.to_dict()
        asin = _clean(match.get("asin")).upper()
        sku = _clean(match.get("sku"))
        product_name = _clean(match.get("product_name"))
        if not asin:
            continue
        local_source = _local_inventory_for_product(source_rows, product_name)
        if local_source:
            matched_sources.add(local_source.source_product_name)
        inventory = _latest_inventory_value(product_daily if product_daily is not None else pd.DataFrame(), marketplace, sku, asin)
        if not inventory:
            inventory = _fallback_inventory_value_from_raw_erp(marketplace, sku, asin)
            if inventory:
                inventory["inventory_source"] = str(inventory.get("inventory_source") or "ERP销量表").replace(
                    "ERP销量表", "ERP销量表-站点文件"
                )
        available_inventory = _to_float(inventory.get("available_stock"))
        fba_inventory = _to_float(inventory.get("fba_stock"))
        current_inventory = available_inventory if available_inventory is not None else fba_inventory

        avg7 = _avg_daily_units(views, marketplace, sku, asin, 7)
        avg14 = _avg_daily_units(views, marketplace, sku, asin, 14)
        avg30 = _avg_daily_units(views, marketplace, sku, asin, 30)
        selected_avg, avg_source = _selected_avg_daily(avg7, avg14, avg30)
        clicks14 = _metric(views, marketplace, sku, asin, 14, "clicks")
        orders14 = _metric(views, marketplace, sku, asin, 14, "total_orders")
        ad_orders14 = _metric(views, marketplace, sku, asin, 14, "ad_orders")
        production_days, inbound_days, total_lead, target_cover = _lead_time(marketplace)
        if current_inventory is not None and selected_avg > 0:
            days_of_cover: float | None = current_inventory / selected_avg
            recommended_qty = max(0.0, target_cover * selected_avg - current_inventory)
            reorder_deadline = report_date + timedelta(days=max(0, int(math.floor(days_of_cover - total_lead))))
        else:
            days_of_cover = None
            recommended_qty = None
            reorder_deadline = None

        product_key = (marketplace, sku, asin)
        asin_key = (marketplace, "", asin)
        is_manual_recovery = product_key in restock_keys or asin_key in restock_keys
        has_recent_activity = clicks14 > 0 or orders14 > 0 or ad_orders14 > 0
        if current_inventory is None:
            level = "UNKNOWN"
            reason = "ERP销量表未读取到可用库存，不能判断断货或覆盖天数。"
        elif current_inventory <= 0:
            level = "OUT_OF_STOCK"
            reason = "可用库存为 0 或以下，广告应避免继续烧量。"
        elif is_manual_recovery and has_recent_activity:
            level = "RESTOCK_RECOVERY"
            reason = "人工确认此前断货且当前刚到货，近期广告/销量需按恢复期观察。"
        elif selected_avg <= 0:
            level = "UNKNOWN"
            reason = "近期销量基准不足，不能单纯按销量判断库存安全。"
            if clicks14 > 0:
                reason += " 但广告仍有点击，需要结合前台和广告恢复观察。"
        elif days_of_cover is not None and days_of_cover <= total_lead:
            level = "LOW_STOCK"
            reason = f"可用库存覆盖约 {_format_days(days_of_cover)} 天，低于总提前期 {total_lead} 天。"
        elif days_of_cover is not None and days_of_cover <= target_cover:
            level = "REPLENISH_SOON"
            reason = f"可用库存覆盖约 {_format_days(days_of_cover)} 天，已进入目标覆盖 {target_cover} 天内。"
        else:
            level = "HEALTHY"
            reason = f"可用库存覆盖约 {_format_days(days_of_cover)} 天，高于目标覆盖 {target_cover} 天。"

        if level == "RESTOCK_RECOVERY":
            if recommended_qty is not None and recommended_qty > 0:
                reorder_note = (
                    f"刚到货恢复期，先观察 3 到 7 天，不作为今日采购指令；"
                    f"按目标覆盖口径理论缺口约 {int(math.ceil(recommended_qty))} 件，仅作参考。"
                )
            else:
                reorder_note = "刚到货恢复期，先观察 3 到 7 天，不作为今日采购指令。"
        elif current_inventory is None:
            reorder_note = "缺少可用库存，需先核对销量表库存字段。"
        elif recommended_qty is None:
            reorder_note = "销量基准不足，需结合广告/前台观察。"
        elif recommended_qty <= 0:
            reorder_note = "暂不需要补货。"
        else:
            reorder_note = f"建议补货约 {int(math.ceil(recommended_qty))} 件。"

        display_reorder_qty = None if level == "RESTOCK_RECOVERY" else recommended_qty
        rows.append(
            {
                "marketplace": marketplace,
                "sku": sku,
                "asin": asin,
                "product_name": product_name,
                "current_inventory": current_inventory,
                "fba_stock": fba_inventory,
                "fbm_stock": inventory.get("fbm_stock"),
                "available_stock": current_inventory,
                "box_count": local_source.box_count if local_source else None,
                "local_inventory": local_source.current_inventory if local_source else None,
                "avg_daily_units_7d": round(avg7, 4),
                "avg_daily_units_14d": round(avg14, 4),
                "avg_daily_units_30d": round(avg30, 4),
                "avg_daily_units_used": round(selected_avg, 4),
                "avg_daily_units_source": avg_source,
                "days_of_cover": round(days_of_cover, 2) if days_of_cover is not None else None,
                "production_days": production_days,
                "shipping_or_inbound_days": inbound_days,
                "total_lead_time_days": total_lead,
                "target_cover_days": target_cover,
                "recommended_reorder_qty": int(math.ceil(display_reorder_qty)) if display_reorder_qty is not None else None,
                "reference_reorder_qty": int(math.ceil(recommended_qty)) if recommended_qty is not None else None,
                "reorder_deadline": reorder_deadline.isoformat() if reorder_deadline else "",
                "stock_risk_level": level,
                "stock_status_label": _status_label(level),
                "stock_risk_reason": reason,
                "replenishment_advice": reorder_note,
                "inventory_source_product_name": local_source.source_product_name if local_source else "",
                "inventory_match_status": "可用库存已读取" if current_inventory is not None else "缺少可用库存",
                "inventory_source": inventory.get("inventory_source") or "ERP销量表",
                "inventory_date": inventory.get("inventory_date") or "",
                "latest_inbound_or_shipment_notes": local_source.latest_notes if local_source else "",
                "recent_14d_clicks": clicks14,
                "recent_14d_orders": orders14,
                "recent_14d_ad_orders": ad_orders14,
            }
        )

    for source in source_rows:
        if source.source_product_name not in matched_sources:
            warnings.append(
                {
                    "level": "warning",
                    "message": f"本地库存品名未匹配到 SKU/ASIN：{source.source_product_name}",
                    "inventory_source_product_name": source.source_product_name,
                }
            )

    return {
        "inventory_file": str(inventory_path),
        "marketplace": marketplace,
        "report_date": report_date.isoformat() if hasattr(report_date, "isoformat") else str(report_date),
        "production_days": PRODUCTION_DAYS,
        "shipping_or_inbound_days": INBOUND_DAYS.get(marketplace, 70),
        "total_lead_time_days": PRODUCTION_DAYS + INBOUND_DAYS.get(marketplace, 70),
        "target_cover_days": PRODUCTION_DAYS + INBOUND_DAYS.get(marketplace, 70) + TARGET_BUFFER_DAYS,
        "rows": sorted(rows, key=lambda row: (str(row.get("stock_risk_level")), str(row.get("product_name")), str(row.get("asin")))),
        "warnings": warnings,
        "matched_inventory_product_names": sorted(matched_sources),
    }


def inventory_rows_from_results(results: Iterable[dict]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for result in results:
        rows.extend(result.get("analysis_payload", {}).get("inventory_replenishment", {}).get("rows", []) or [])
    return rows


def inventory_warnings_from_results(results: Iterable[dict]) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    for result in results:
        marketplace = result.get("marketplace")
        for warning in result.get("analysis_payload", {}).get("inventory_replenishment", {}).get("warnings", []) or []:
            if isinstance(warning, dict):
                warnings.append({"marketplace": marketplace, **warning})
    return warnings


def build_inventory_markdown(rows: list[dict[str, object]], report_date: str) -> str:
    lines = [f"# 库存补货提醒｜{report_date}", ""]
    if not rows:
        lines.append("当前没有可展示的库存补货记录。")
        return "\n".join(lines) + "\n"
    lines.append("| 站点 | 产品 | SKU | ASIN | 可用库存 | 覆盖天数 | 总提前期 | 目标覆盖 | 状态 | 建议 |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---|---|")
    status_order = {"OUT_OF_STOCK": 0, "LOW_STOCK": 1, "RESTOCK_RECOVERY": 2, "REPLENISH_SOON": 3, "UNKNOWN": 4, "HEALTHY": 5}
    for row in sorted(rows, key=lambda item: (status_order.get(str(item.get("stock_risk_level")), 9), str(item.get("marketplace")), str(item.get("product_name")))):
        lines.append(
            "| "
            + " | ".join(
                [
                    _clean(row.get("marketplace")),
                    _clean(row.get("product_name")),
                    _clean(row.get("sku")),
                    _clean(row.get("asin")),
                    _format_qty(_to_float(row.get("current_inventory"))),
                    _format_days(_to_float(row.get("days_of_cover"))),
                    _clean(row.get("total_lead_time_days")),
                    _clean(row.get("target_cover_days")),
                    _clean(row.get("stock_status_label")),
                    _clean(row.get("replenishment_advice")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_inventory_outputs(
    output_dir: Path,
    rows: list[dict[str, object]],
    report_date: str,
    warnings: list[dict[str, object]] | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "inventory_replenishment.json"
    md_path = output_dir / "inventory_replenishment.md"
    json_path.write_text(
        json.dumps({"report_date": report_date, "rows": rows, "warnings": warnings or []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(build_inventory_markdown(rows, report_date), encoding="utf-8")
    return json_path, md_path
