from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd

ALIAS_COLUMNS = ["marketplace", "source_sku", "canonical_sku", "asin", "reason"]
REVIEW_COLUMNS = [
    "marketplace",
    "source_sku",
    "asin",
    "source",
    "candidate_sku",
    "candidate_product_name",
    "match_basis",
    "confidence",
    "action_needed",
]


@dataclass
class AliasBuildResult:
    original_missing_count: int
    remaining_missing_count: int
    auto_aliases: pd.DataFrame
    review: pd.DataFrame
    alias_map: pd.DataFrame


def load_alias_map(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=ALIAS_COLUMNS)
    frame = pd.read_excel(path)
    for column in ALIAS_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame[ALIAS_COLUMNS].copy()
    for column in ALIAS_COLUMNS:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    return frame.drop_duplicates(subset=["marketplace", "source_sku", "asin"], keep="last").reset_index(drop=True)


def write_alias_map(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    export = frame.copy()
    for column in ALIAS_COLUMNS:
        if column not in export.columns:
            export[column] = ""
    export = export[ALIAS_COLUMNS].drop_duplicates(subset=["marketplace", "source_sku", "asin"], keep="last")
    export.to_excel(path, index=False)


def _strip_suffix(value: str) -> str:
    return re.sub(r"-(C|T)$", "", str(value).strip(), flags=re.IGNORECASE)


def _reference_candidates(reference: pd.DataFrame, marketplace: str, asin: str) -> pd.DataFrame:
    matched = reference[
        (reference["marketplace"].astype(str).str.upper() == marketplace.upper())
        & (reference["asin"].astype(str).str.strip() == asin)
    ][["marketplace", "sku", "asin", "product_name"]].drop_duplicates()
    return matched.reset_index(drop=True)


def _similarity_candidates(reference: pd.DataFrame, marketplace: str, source_sku: str) -> pd.DataFrame:
    stripped_source = _strip_suffix(source_sku)
    reference = reference.copy()
    reference["sku_base"] = reference["sku"].astype(str).map(_strip_suffix)
    matched = reference[
        (reference["marketplace"].astype(str).str.upper() == marketplace.upper())
        & (reference["sku_base"] == stripped_source)
    ][["marketplace", "sku", "asin", "product_name"]].drop_duplicates()
    return matched.reset_index(drop=True)


def build_alias_review(
    mapping_check: pd.DataFrame,
    sku_map: pd.DataFrame,
    cost_config: pd.DataFrame,
    alias_map_path: Path,
    review_output_path: Path,
) -> AliasBuildResult:
    reference = pd.concat(
        [
            sku_map[["marketplace", "sku", "asin", "product_name"]],
            cost_config[["marketplace", "sku", "asin", "product_name"]],
        ],
        ignore_index=True,
    ).drop_duplicates()

    existing_aliases = load_alias_map(alias_map_path)
    missing = mapping_check[mapping_check["mapping_status"] == "missing_sku_asin_map"].copy()
    original_missing_count = len(missing)

    review_rows: list[dict] = []
    auto_rows: list[dict] = []

    for _, row in missing.iterrows():
        marketplace = str(row["marketplace"]).strip()
        source_sku = str(row["sku"]).strip()
        asin = str(row["asin"]).strip()
        source = str(row.get("source", "")).strip()

        asin_candidates = _reference_candidates(reference, marketplace, asin)
        if len(asin_candidates) == 1:
            candidate = asin_candidates.iloc[0]
            review_rows.append(
                {
                    "marketplace": marketplace,
                    "source_sku": source_sku,
                    "asin": asin,
                    "source": source,
                    "candidate_sku": candidate["sku"],
                    "candidate_product_name": candidate["product_name"],
                    "match_basis": "asin_unique_match",
                    "confidence": "high",
                    "action_needed": "auto_apply",
                }
            )
            auto_rows.append(
                {
                    "marketplace": marketplace,
                    "source_sku": source_sku,
                    "canonical_sku": candidate["sku"],
                    "asin": asin,
                    "reason": "asin unique match from sku_asin_map/product_cost_config",
                }
            )
            continue

        if len(asin_candidates) > 1:
            for _, candidate in asin_candidates.iterrows():
                review_rows.append(
                    {
                        "marketplace": marketplace,
                        "source_sku": source_sku,
                        "asin": asin,
                        "source": source,
                        "candidate_sku": candidate["sku"],
                        "candidate_product_name": candidate["product_name"],
                        "match_basis": "asin_multiple_candidates",
                        "confidence": "medium",
                        "action_needed": "need_manual_review",
                    }
                )
            continue

        similarity_candidates = _similarity_candidates(reference, marketplace, source_sku)
        if len(similarity_candidates) == 1:
            candidate = similarity_candidates.iloc[0]
            review_rows.append(
                {
                    "marketplace": marketplace,
                    "source_sku": source_sku,
                    "asin": asin,
                    "source": source,
                    "candidate_sku": candidate["sku"],
                    "candidate_product_name": candidate["product_name"],
                    "match_basis": "sku_suffix_similarity",
                    "confidence": "medium",
                    "action_needed": "need_manual_review",
                }
            )
            continue

        if len(similarity_candidates) > 1:
            for _, candidate in similarity_candidates.iterrows():
                review_rows.append(
                    {
                        "marketplace": marketplace,
                        "source_sku": source_sku,
                        "asin": asin,
                        "source": source,
                        "candidate_sku": candidate["sku"],
                        "candidate_product_name": candidate["product_name"],
                        "match_basis": "sku_suffix_similarity_multiple",
                        "confidence": "low",
                        "action_needed": "need_manual_review",
                    }
                )
            continue

        review_rows.append(
            {
                "marketplace": marketplace,
                "source_sku": source_sku,
                "asin": asin,
                "source": source,
                "candidate_sku": "",
                "candidate_product_name": "",
                "match_basis": "no_candidate",
                "confidence": "low",
                "action_needed": "need_manual_review",
            }
        )

    review_df = pd.DataFrame(review_rows, columns=REVIEW_COLUMNS)
    auto_df = pd.DataFrame(auto_rows, columns=ALIAS_COLUMNS)
    merged_aliases = pd.concat([existing_aliases, auto_df], ignore_index=True)
    if not merged_aliases.empty:
        merged_aliases = merged_aliases.drop_duplicates(subset=["marketplace", "source_sku", "asin"], keep="last").reset_index(drop=True)
    else:
        merged_aliases = pd.DataFrame(columns=ALIAS_COLUMNS)

    remaining_missing = original_missing_count - len(auto_df.drop_duplicates(subset=["marketplace", "source_sku", "asin"]))

    review_output_path.parent.mkdir(parents=True, exist_ok=True)
    review_df.to_excel(review_output_path, index=False)
    write_alias_map(alias_map_path, merged_aliases)

    return AliasBuildResult(
        original_missing_count=original_missing_count,
        remaining_missing_count=max(remaining_missing, 0),
        auto_aliases=auto_df.drop_duplicates(subset=["marketplace", "source_sku", "asin"]).reset_index(drop=True),
        review=review_df,
        alias_map=merged_aliases,
    )
