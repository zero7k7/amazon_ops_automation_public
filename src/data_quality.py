from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_data_quality_issue_detail(
    mapping_check: pd.DataFrame,
    cost_config: pd.DataFrame,
    sku_map: pd.DataFrame,
    alias_map: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    mapping = mapping_check.copy()
    for column in ["marketplace", "sku", "asin", "product_name", "source", "mapping_status", "reason"]:
        if column not in mapping.columns:
            mapping[column] = ""
        mapping[column] = mapping[column].fillna("").astype(str).str.strip()

    aliases = alias_map.copy() if not alias_map.empty else pd.DataFrame(columns=["marketplace", "source_sku", "canonical_sku", "asin", "reason"])
    for column in ["marketplace", "source_sku", "canonical_sku", "asin", "reason"]:
        if column not in aliases.columns:
            aliases[column] = ""
        aliases[column] = aliases[column].fillna("").astype(str).str.strip()

    reference = pd.concat(
        [
            sku_map[["marketplace", "sku", "asin", "product_name"]].copy(),
            cost_config[["marketplace", "sku", "asin", "product_name"]].copy(),
        ],
        ignore_index=True,
    ).drop_duplicates()
    for column in ["marketplace", "sku", "asin", "product_name"]:
        reference[column] = reference[column].fillna("").astype(str).str.strip()

    cost = cost_config.copy()
    for column in cost.columns:
        if cost[column].dtype == object:
            cost[column] = cost[column].fillna("").astype(str).str.strip()

    issue_rows: list[dict] = []

    def lookup_reference(marketplace: str, canonical_sku: str, asin: str) -> tuple[str, str]:
        if canonical_sku and asin:
            matched = reference[
                (reference["marketplace"] == marketplace)
                & (reference["sku"] == canonical_sku)
                & (reference["asin"] == asin)
            ]
            if not matched.empty:
                row = matched.iloc[0]
                return str(row["sku"]).strip(), str(row["product_name"]).strip()

        if asin:
            asin_matches = reference[
                (reference["marketplace"] == marketplace)
                & (reference["asin"] == asin)
            ].drop_duplicates(subset=["marketplace", "sku", "asin"])
            if len(asin_matches) == 1:
                row = asin_matches.iloc[0]
                return str(row["sku"]).strip(), str(row["product_name"]).strip()

        if canonical_sku:
            sku_matches = reference[
                (reference["marketplace"] == marketplace)
                & (reference["sku"] == canonical_sku)
            ].drop_duplicates(subset=["marketplace", "sku", "asin"])
            if len(sku_matches) == 1:
                row = sku_matches.iloc[0]
                return str(row["sku"]).strip(), str(row["product_name"]).strip()

        return canonical_sku, ""

    for _, row in mapping.iterrows():
        marketplace = row["marketplace"]
        source_sku = row["sku"]
        asin = row["asin"]
        mapping_status = row["mapping_status"]
        source = row["source"]
        reason = row["reason"]

        alias_match = aliases[
            (aliases["marketplace"] == marketplace)
            & (aliases["source_sku"] == source_sku)
            & (aliases["asin"] == asin)
        ]
        canonical_sku = source_sku
        if not alias_match.empty:
            canonical_sku = alias_match.iloc[-1]["canonical_sku"] or source_sku

        canonical_sku, lookup_product_name = lookup_reference(marketplace, canonical_sku, asin)
        product_name = row["product_name"] or lookup_product_name

        if mapping_status != "matched":
            issue_rows.append(
                {
                    "marketplace": marketplace,
                    "sku": source_sku,
                    "canonical_sku": canonical_sku,
                    "asin": asin,
                    "product_name": product_name,
                    "mapping_status": mapping_status,
                    "cost_status": "not_checked",
                    "issue_type": mapping_status,
                    "reason": reason,
                    "source": source,
                }
            )
            continue

        matched_cost = cost[
            (cost["marketplace"] == marketplace)
            & (cost["sku"] == canonical_sku)
            & (cost["asin"] == asin)
        ]
        if matched_cost.empty:
            issue_rows.append(
                {
                    "marketplace": marketplace,
                    "sku": source_sku,
                    "canonical_sku": canonical_sku,
                    "asin": asin,
                    "product_name": product_name,
                    "mapping_status": mapping_status,
                    "cost_status": "missing_cost_config",
                    "issue_type": "missing_cost_config",
                    "reason": "成本缺失，不影响广告数据，但影响利润判断",
                    "source": source,
                }
            )
            continue

        cost_row = matched_cost.iloc[0]
        cost_checks = [
            ("purchase_cost_local", "missing_product_cost"),
            ("suggested_target_acos", "missing_target_acos"),
            ("first_leg_cost_local", "missing_first_leg_cost"),
        ]
        for cost_column, issue_type in cost_checks:
            value = cost_row.get(cost_column, "")
            is_missing = pd.isna(value) or str(value).strip() == ""
            if is_missing:
                issue_rows.append(
                    {
                        "marketplace": marketplace,
                        "sku": source_sku,
                        "canonical_sku": canonical_sku,
                        "asin": asin,
                        "product_name": product_name,
                        "mapping_status": mapping_status,
                        "cost_status": issue_type,
                        "issue_type": issue_type,
                        "reason": "成本缺失，不影响广告数据，但影响利润判断",
                        "source": source,
                    }
                )

    detail = pd.DataFrame(
        issue_rows,
        columns=[
            "marketplace",
            "sku",
            "canonical_sku",
            "asin",
            "product_name",
            "mapping_status",
            "cost_status",
            "issue_type",
            "reason",
            "source",
        ],
    )

    counts = {
        "missing_sku_asin_map": int((detail["issue_type"] == "missing_sku_asin_map").sum()) if not detail.empty else 0,
        "missing_cost_config": int((detail["issue_type"] == "missing_cost_config").sum()) if not detail.empty else 0,
        "missing_product_cost": int((detail["issue_type"] == "missing_product_cost").sum()) if not detail.empty else 0,
        "missing_target_acos": int((detail["issue_type"] == "missing_target_acos").sum()) if not detail.empty else 0,
        "missing_first_leg_cost": int((detail["issue_type"] == "missing_first_leg_cost").sum()) if not detail.empty else 0,
        "missing_sku": int((detail["issue_type"] == "missing_sku").sum()) if not detail.empty else 0,
        "missing_marketplace": int((detail["issue_type"] == "missing_marketplace").sum()) if not detail.empty else 0,
        "missing_asin": int((detail["issue_type"] == "missing_asin").sum()) if not detail.empty else 0,
    }
    return detail, counts


def write_data_quality_issue_detail(path: Path, detail: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    detail.to_excel(path, index=False)


def build_missing_sku_detail(
    mapping_check: pd.DataFrame,
    sku_map: pd.DataFrame,
    cost_config: pd.DataFrame,
) -> pd.DataFrame:
    reference = pd.concat(
        [
            sku_map[["marketplace", "sku", "asin", "product_name"]],
            cost_config[["marketplace", "sku", "asin", "product_name"]],
        ],
        ignore_index=True,
    ).copy()
    for column in ["marketplace", "sku", "asin", "product_name"]:
        reference[column] = reference[column].fillna("").astype(str).str.strip()
    reference = reference[(reference["marketplace"] != "") & (reference["asin"] != "") & (reference["sku"] != "")]
    unique_asin_reference = (
        reference.drop_duplicates(subset=["marketplace", "sku", "asin"])
        .groupby(["marketplace", "asin"], as_index=False)
        .filter(lambda group: group["sku"].nunique() == 1)
        .drop_duplicates(subset=["marketplace", "asin"], keep="first")
        [["marketplace", "asin", "sku", "product_name"]]
        .rename(columns={"sku": "resolved_sku", "product_name": "resolved_product_name"})
    )

    working = mapping_check.copy()
    for column in ["marketplace", "sku", "asin", "product_name", "source", "mapping_status", "reason"]:
        if column not in working.columns:
            working[column] = ""
        working[column] = working[column].fillna("").astype(str).str.strip()
    working = working[(working["mapping_status"] == "missing_sku") & (working["asin"] != "")].copy()
    if working.empty:
        return pd.DataFrame(columns=["marketplace", "asin", "source", "resolved_sku", "resolved_product_name", "reason"])
    working = working.merge(unique_asin_reference, on=["marketplace", "asin"], how="left")
    detail = working[["marketplace", "asin", "source", "resolved_sku", "resolved_product_name", "reason"]].copy()
    if detail.empty:
        return pd.DataFrame(columns=["marketplace", "asin", "source", "resolved_sku", "resolved_product_name", "reason"])
    return detail.drop_duplicates().sort_values(["marketplace", "asin", "source"]).reset_index(drop=True)


def write_missing_sku_detail(path: Path, detail: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    detail.to_excel(path, index=False)
