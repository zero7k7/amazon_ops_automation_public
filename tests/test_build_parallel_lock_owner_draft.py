from __future__ import annotations

import scripts.build_parallel_lock_owner_draft as draft


def _owners_by_package(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(owner.get("work_package")): owner
        for owner in payload.get("owners", [])
        if isinstance(owner, dict)
    }


def test_build_owner_draft_groups_changed_locked_files() -> None:
    payload = draft.build_owner_draft(
        [
            "config/product_cost_config.xlsx",
            "main.py",
            "src/report_presentation.py",
            "src/generate_html_report.py",
            "scripts/check_parallel_lock_owners.py",
            "scripts/run_frontend_checks.py",
            "README.md",
        ]
    )
    owners = _owners_by_package(payload)

    assert payload["confirmation_status"] == "draft_requires_manual_owner_confirmation"
    assert owners["business_config"]["files"] == ["config/product_cost_config.xlsx"]
    assert owners["core_business"]["files"] == ["main.py", "src/report_presentation.py"]
    assert owners["report_display"]["files"] == [
        "scripts/check_parallel_lock_owners.py",
        "src/generate_html_report.py",
    ]
    assert owners["daily_frontend"]["files"] == ["scripts/run_frontend_checks.py"]
    assert all(str(owner["owner"]).startswith("REVIEW_REQUIRED_") for owner in owners.values())


def test_build_owner_draft_ignores_non_locked_files() -> None:
    payload = draft.build_owner_draft(["README.md", "scripts/run_daily_update.py"])

    assert payload["owners"] == []
