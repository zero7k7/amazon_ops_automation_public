from __future__ import annotations


def _attempt(index: int, *, success: bool = True) -> dict[str, object]:
    row = {
        "attempt": index,
        "marketplace": "UK",
        "asin": "B0DEMOFRNT",
        "success": success,
        "title": "Demo Adjustable Desk Lamp",
        "price": "£17.89",
        "rating": "4.2 out of 5 stars",
        "reviews": "(38)",
        "location": "Aberdeen AB10 1",
        "method": "chrome-extension",
    }
    if not success:
        row.update({"title": "", "price": "", "error": "Amazon 返回验证码"})
    return row


def test_frontend_stability_accepts_19_of_20_success() -> None:
    from scripts.validate_frontend_stability import build_stability_report

    attempts = [_attempt(index, success=index != 16) for index in range(1, 21)]

    report = build_stability_report(
        {"attempts": attempts},
        marketplace="UK",
        asin="B0DEMOFRNT",
    )

    assert report["total_attempts"] == 20
    assert report["success_count"] == 19
    assert report["failure_count"] == 1
    assert report["success_rate"] == 0.95
    assert report["passed"] is True


def test_frontend_stability_accepts_16_of_20_success() -> None:
    from scripts.validate_frontend_stability import build_stability_report

    attempts = [_attempt(index, success=index not in {4, 9, 12, 16}) for index in range(1, 21)]

    report = build_stability_report(
        {"attempts": attempts},
        marketplace="UK",
        asin="B0DEMOFRNT",
    )

    assert report["success_count"] == 16
    assert report["failure_count"] == 4
    assert report["success_rate"] == 0.8
    assert report["passed"] is True


def test_frontend_stability_rejects_15_of_20_success() -> None:
    from scripts.validate_frontend_stability import build_stability_report

    attempts = [_attempt(index, success=index not in {4, 9, 12, 16, 19}) for index in range(1, 21)]

    report = build_stability_report(
        {"attempts": attempts},
        marketplace="UK",
        asin="B0DEMOFRNT",
    )

    assert report["success_count"] == 15
    assert report["failure_count"] == 5
    assert report["success_rate"] == 0.75
    assert report["passed"] is False


def test_frontend_stability_rejects_less_than_20_attempts() -> None:
    from scripts.validate_frontend_stability import build_stability_report

    attempts = [_attempt(index) for index in range(1, 19)]

    report = build_stability_report(
        {"attempts": attempts},
        marketplace="UK",
        asin="B0DEMOFRNT",
    )

    assert report["total_attempts"] == 18
    assert report["success_rate"] == 1.0
    assert report["passed"] is False


def test_frontend_stability_rejects_wrong_marketplace_currency() -> None:
    from scripts.validate_frontend_stability import build_stability_report

    attempts = [_attempt(index) for index in range(1, 21)]
    attempts[0]["price"] = "€20.70"

    report = build_stability_report(
        {"attempts": attempts},
        marketplace="UK",
        asin="B0DEMOFRNT",
    )

    assert report["success_count"] == 19
    assert report["attempts"][0]["reasons"] == ["missing_or_wrong_price"]


def test_frontend_stability_accepts_configured_us_postcode_note() -> None:
    from scripts.validate_frontend_stability import build_stability_report

    attempts = [
        {
            "attempt": index,
            "marketplace": "US",
            "asin": "B0TEST1234",
            "success": True,
            "title": "US product",
            "price": "$41.91",
            "rating": "3.9 out of 5 stars",
            "reviews": "(52)",
            "location": "US 10001 已设置",
            "method": "chrome-cdp",
        }
        for index in range(1, 21)
    ]

    report = build_stability_report(
        {"attempts": attempts},
        marketplace="US",
        asin="B0TEST1234",
    )

    assert report["success_count"] == 20
    assert report["passed"] is True


def test_frontend_stability_accepts_configured_de_postcode_note() -> None:
    from scripts.validate_frontend_stability import build_stability_report

    attempts = [
        {
            "attempt": index,
            "marketplace": "DE",
            "asin": "B0TEST1234",
            "success": True,
            "title": "DE product",
            "price": "€17.99",
            "rating": "4,2 von 5 Sternen",
            "reviews": "(38)",
            "location": "DE 10115 已设置",
            "method": "chrome-cdp",
        }
        for index in range(1, 21)
    ]

    report = build_stability_report(
        {"attempts": attempts},
        marketplace="DE",
        asin="B0TEST1234",
    )

    assert report["success_count"] == 20
    assert report["passed"] is True


def test_frontend_stability_cli_can_print_without_writing(monkeypatch, tmp_path, capsys) -> None:
    import json
    import sys

    from scripts import validate_frontend_stability as stability

    input_path = tmp_path / "attempts.json"
    input_path.write_text(
        json.dumps({"attempts": [_attempt(index) for index in range(1, 21)]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_frontend_stability.py",
            "--input",
            str(input_path),
            "--output",
            "-",
            "--marketplace",
            "UK",
            "--asin",
            "B0DEMOFRNT",
        ],
    )

    code = stability.main()

    assert code == 0
    assert '"passed": true' in capsys.readouterr().out
