from __future__ import annotations

import scripts.check_parallel_lock_owners as lock_owners


def test_parallel_lock_owner_manifest_accepts_single_owner() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["main.py", "src/report_presentation.py"],
        {
            "owners": [
                {
                    "owner": "agent-core",
                    "work_package": "core_business",
                    "files": ["main.py", "src/report_presentation.py"],
                }
            ]
        },
    )

    assert failures == []


def test_parallel_lock_owner_checker_is_itself_locked() -> None:
    path = "scripts/check_parallel_lock_owners.py"

    assert lock_owners.is_locked_parallel_path(path) is True
    failures = lock_owners.validate_owner_manifest(
        [path],
        {
            "owners": [
                {
                    "owner": "agent-report",
                    "work_package": "report_display",
                    "files": [path],
                }
            ]
        },
    )

    assert failures == []


def test_parallel_lock_owner_manifest_blocks_missing_owner() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["main.py", "src/report_presentation.py"],
        {
            "owners": [
                {
                    "owner": "agent-core",
                    "work_package": "core_business",
                    "files": ["main.py"],
                }
            ]
        },
    )

    assert "changed locked file has no owner: src/report_presentation.py" in failures


def test_parallel_lock_owner_manifest_blocks_multiple_owners() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["main.py"],
        {
            "owners": [
                {"owner": "agent-a", "work_package": "core_business", "files": ["main.py"]},
                {"owner": "agent-b", "work_package": "core_business", "files": ["main.py"]},
            ]
        },
    )

    assert "locked file has multiple owners: main.py -> agent-a, agent-b" in failures


def test_parallel_lock_owner_manifest_blocks_too_many_execution_agents() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["main.py"],
        {
            "owners": [
                {"owner": "agent-1", "work_package": "core_business", "files": ["main.py"]},
                {"owner": "agent-2", "work_package": "core_business", "files": ["src/report_presentation.py"]},
                {"owner": "agent-3", "work_package": "report_display", "files": ["src/generate_html_report.py"]},
                {"owner": "agent-4", "work_package": "core_business", "files": ["src/metrics.py"]},
                {"owner": "agent-5", "work_package": "core_business", "files": ["src/merge_data.py"]},
            ]
        },
    )

    assert "too many execution owners: 5 > 4" in failures


def test_parallel_lock_owner_manifest_rejects_non_locked_assignment() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["README.md"],
        {
            "owners": [
                {"owner": "docs", "work_package": "docs", "files": ["README.md"]},
            ]
        },
    )

    assert "owners[1] assigns non-locked file: README.md" in failures


def test_parallel_lock_owner_manifest_requires_work_package() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["main.py"],
        {
            "owners": [
                {"owner": "agent-core", "files": ["main.py"]},
            ]
        },
    )

    assert "owners[1] missing work_package" in failures


def test_parallel_lock_owner_manifest_blocks_out_of_package_lock() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["src/generate_html_report.py"],
        {
            "owners": [
                {
                    "owner": "agent-core",
                    "work_package": "core_business",
                    "files": ["src/generate_html_report.py"],
                },
            ]
        },
    )

    assert (
        "owners[1] assigns file outside work_package core_business: src/generate_html_report.py"
        in failures
    )


def test_parallel_lock_owner_manifest_main_thread_does_not_count_as_execution_agent() -> None:
    failures = lock_owners.validate_owner_manifest(
        ["scripts/check_showcase_commit_readiness.py"],
        {
            "owners": [
                {
                    "owner": "main-thread",
                    "role": "main_thread",
                    "files": ["scripts/check_showcase_commit_readiness.py"],
                }
            ]
        },
    )

    assert failures == []
