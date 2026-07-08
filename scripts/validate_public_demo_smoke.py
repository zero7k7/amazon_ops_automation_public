from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAFE_RUN_DIR = ROOT / "data" / "output" / "safe_run"
PUBLIC_SAMPLE_ASINS = {"B0B5HPKZKM", "B0H73CXQ5J", "B0BPC8WZL8"}
FORBIDDEN_PUBLIC_DEMO_MARKERS = {
    "B0DEMO",
    "SKU-DEMO",
    "B084Z8CXXN",
    "PUBLIC-LIVE-ASIN-SMOKE",
    "公开 ASIN 测试",
}
REQUIRED_TEXT_OUTPUTS = [
    "latest_recommendations.html",
    "latest_recommendations.md",
    "dashboard.html",
    "summary.html",
    "uk_report.html",
    "us_report.html",
    "de_report.html",
    "marketplace_summary.md",
    "enhanced_data_requests.md",
]
REQUIRED_JSON_OUTPUTS = [
    "latest_analysis.json",
]


def _latest_safe_run_dir() -> Path:
    candidates = [path for path in SAFE_RUN_DIR.glob("*") if path.is_dir()]
    if not candidates:
        raise SystemExit(f"[fail] no safe-run directory found under {SAFE_RUN_DIR}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    safe_dir = _latest_safe_run_dir()
    failures: list[str] = []

    for name in REQUIRED_TEXT_OUTPUTS + REQUIRED_JSON_OUTPUTS:
        if not (safe_dir / name).is_file():
            failures.append(f"missing {name}")

    if not list(safe_dir.glob("amazon_ops_report_*.xlsx")):
        failures.append("missing amazon_ops_report_*.xlsx")
    if not list(safe_dir.glob("autoopt_log_*.json")):
        failures.append("missing autoopt_log_*.json")

    searchable = ""
    for name in REQUIRED_TEXT_OUTPUTS:
        path = safe_dir / name
        if path.is_file():
            searchable += "\n" + _read_text(path)
    latest_analysis = safe_dir / "latest_analysis.json"
    if latest_analysis.is_file():
        try:
            json.loads(_read_text(latest_analysis))
        except json.JSONDecodeError as exc:
            failures.append(f"latest_analysis.json invalid JSON: {exc}")
        searchable += "\n" + _read_text(latest_analysis)

    for asin in sorted(PUBLIC_SAMPLE_ASINS):
        if asin not in searchable:
            failures.append(f"missing public sample ASIN {asin}")
    for marker in sorted(FORBIDDEN_PUBLIC_DEMO_MARKERS):
        if marker in searchable:
            failures.append(f"forbidden marker still visible: {marker}")

    if failures:
        for failure in failures:
            print(f"[fail] {failure}")
        return 1

    print(f"[check] public demo safe-run outputs validated: {safe_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
