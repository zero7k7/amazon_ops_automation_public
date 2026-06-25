from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .normalize_fields import FieldValidationError, normalize_column_names, require_columns

EXPECTED_SHEET_NAME = "product_cost_config"
REQUIRED_COLUMNS = ["marketplace", "sku", "asin", "product_name", "currency"]


@dataclass
class SkuAsinMapBuildResult:
    source_path: Path
    sheet_name: str
    output_path: Path
    unmapped_output_path: Path
    row_count: int
    unmapped_count: int


def inspect_cost_config_file(path: Path) -> list[str]:
    if path.exists():
        return pd.ExcelFile(path).sheet_names
    alt_path = path.with_suffix(path.suffix + ".xlsx")
    if alt_path.exists():
        raise FileNotFoundError(
            f"文件名错误: 发现 {alt_path.name}，但缺少 {path.name}，请修正文件名后再运行"
        )
    raise FileNotFoundError(f"缺少成本配置表: {path}")


def read_cost_config_sheet(path: Path, sheet_name: str = EXPECTED_SHEET_NAME) -> pd.DataFrame:
    sheet_names = inspect_cost_config_file(path)
    xls = pd.ExcelFile(path)
    if sheet_name not in sheet_names:
        previews: dict[str, list[dict]] = {}
        for current_sheet in sheet_names:
            previews[current_sheet] = pd.read_excel(xls, sheet_name=current_sheet, nrows=5).to_dict(orient="records")
        raise FieldValidationError(
            f"找不到 {sheet_name} sheet. 当前 sheets: {sheet_names}. 前 5 行预览: {previews}"
        )
    frame = pd.read_excel(xls, sheet_name=sheet_name)
    frame = normalize_column_names(frame)
    require_columns(frame, REQUIRED_COLUMNS, source_name=f"{path.name}:{sheet_name}")
    for column in REQUIRED_COLUMNS:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    return frame


def build_sku_asin_map_from_cost_config(
    cost_config_path: Path,
    output_path: Path,
    unmapped_output_path: Path,
    *,
    allow_overwrite: bool = True,
) -> SkuAsinMapBuildResult:
    frame = read_cost_config_sheet(cost_config_path, sheet_name=EXPECTED_SHEET_NAME)
    mapping = frame[REQUIRED_COLUMNS].copy()

    unmapped = mapping[(mapping["sku"] == "") | (mapping["asin"] == "")]
    unique_mapping = (
        mapping[(mapping["sku"] != "") & (mapping["asin"] != "")]
        .drop_duplicates(subset=["marketplace", "sku", "asin"], keep="first")
        .reset_index(drop=True)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    unmapped_output_path.parent.mkdir(parents=True, exist_ok=True)
    if allow_overwrite or not output_path.exists():
        try:
            unique_mapping.to_excel(output_path, index=False)
        except PermissionError:
            if not output_path.exists():
                raise
    unmapped.to_excel(unmapped_output_path, index=False)

    return SkuAsinMapBuildResult(
        source_path=cost_config_path,
        sheet_name=EXPECTED_SHEET_NAME,
        output_path=output_path,
        unmapped_output_path=unmapped_output_path,
        row_count=len(unique_mapping),
        unmapped_count=len(unmapped),
    )
