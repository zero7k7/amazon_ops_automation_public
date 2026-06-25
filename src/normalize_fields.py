from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


class FieldValidationError(ValueError):
    """Raised when source data is missing required columns."""


def _clean_name(name: str) -> str:
    return (
        str(name)
        .strip()
        .lower()
        .replace("\ufeff", "")
        .replace("\n", " ")
        .replace("-", "_")
        .replace("/", "_")
        .replace(" ", "_")
    )


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.copy()
    renamed.columns = [_clean_name(column) for column in renamed.columns]
    return renamed


def rename_with_synonyms(df: pd.DataFrame, synonyms: dict[str, Iterable[str]]) -> pd.DataFrame:
    renamed = df.copy()
    available = {column: column for column in renamed.columns}
    mapping: dict[str, str] = {}
    for canonical_name, candidates in synonyms.items():
        canonical_normalized = _clean_name(canonical_name)
        if canonical_normalized in available:
            mapping[canonical_normalized] = canonical_name
            continue
        for candidate in candidates:
            candidate_normalized = _clean_name(candidate)
            if candidate_normalized in available:
                mapping[candidate_normalized] = canonical_name
                break
    if mapping:
        renamed = renamed.rename(columns=mapping)
    return renamed


def require_columns(df: pd.DataFrame, required_columns: Iterable[str], source_name: str) -> None:
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        missing_str = ", ".join(missing)
        raise FieldValidationError(f"{source_name} 缺少必要字段: {missing_str}")


def coerce_numeric(df: pd.DataFrame, numeric_columns: Iterable[str]) -> pd.DataFrame:
    converted = df.copy()
    for column in numeric_columns:
        if column in converted.columns:
            converted[column] = pd.to_numeric(converted[column], errors="coerce").fillna(0)
    return converted


def coerce_text(df: pd.DataFrame, text_columns: Iterable[str]) -> pd.DataFrame:
    converted = df.copy()
    for column in text_columns:
        if column in converted.columns:
            converted[column] = converted[column].fillna("").astype(str).str.strip()
    return converted


def parse_date_column(series: pd.Series, column_name: str) -> pd.Series:
    normalized = (
        series.astype(str)
        .str.strip()
        .str.replace("年", "-", regex=False)
        .str.replace("月", "-", regex=False)
        .str.replace("日", "", regex=False)
        .str.replace("/", "-", regex=False)
    )
    parsed = pd.to_datetime(normalized, errors="coerce")
    if parsed.isna().all():
        raise FieldValidationError(f"{column_name} 无法解析为日期")
    return parsed.dt.date


@dataclass(frozen=True)
class SafeDivResult:
    numerator: float
    denominator: float
    value: float


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator in (0, 0.0):
        return 0.0
    return float(numerator) / float(denominator)
