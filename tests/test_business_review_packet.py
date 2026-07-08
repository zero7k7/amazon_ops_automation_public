from __future__ import annotations

import json
from pathlib import Path

import scripts.build_business_review_packet as packet


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    output = root / "data" / "output"
    output.mkdir(parents=True)
    monkeypatch.setattr(packet, "ROOT", root)
    monkeypatch.setattr(packet, "OUTPUT", output)
    monkeypatch.setattr(packet, "STATUS_REPORT", output / "showcase_status_report.json")
    monkeypatch.setattr(packet, "COST_AUDIT", output / "cost_config_diff_summary.json")
    monkeypatch.setattr(packet, "UNKNOWN_AUDIT", output / "unknown_inbox_audit.json")
    monkeypatch.setattr(packet, "PACKET_JSON", output / "business_review_packet.json")
    monkeypatch.setattr(packet, "PACKET_MARKDOWN", output / "business_review_packet.md")
    return output


def test_business_review_packet_summarizes_blockers_and_high_risk_costs(monkeypatch, tmp_path) -> None:
    output = _patch_paths(monkeypatch, tmp_path)
    packet.STATUS_REPORT.write_text(
        json.dumps(
            {
                "showcase_ready": True,
                "business_submit_ready": False,
                "daily_update_blocked": True,
                "report_date": "2026-06-08",
                "marketplaces": ["DE", "UK", "US"],
                "owner_manifest_confirmation_status": "lock_ownership_confirmed_by_main_thread_only",
                "business_confirmation_status": "confirmed",
                "business_confirmation_valid": True,
                "business_confirmation_file": "/tmp/business_review_confirmation.json",
                "strict_readiness_passed": False,
                "strict_readiness_exit_code": 1,
                "strict_readiness_summary": [
                    "[fail] strict mode requires confirmations: manual config confirmation missing; unknown inbox business files present"
                ],
                "unknown_inbox_details": [
                    {
                        "file": "/tmp/metric.xlsx",
                        "likely_report_type": "seller_central_promotion_metrics",
                        "likely_marketplace": "DE_or_EUR",
                        "business_interpretation": "促销表现报告",
                        "recommendation": "参考资料则隔离",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    packet.COST_AUDIT.write_text(
        json.dumps(
            {
                "total_changed_cells": 10,
                "sheets": {
                    "product_cost_config": {
                        "keyed_diff": {
                            "changed_record_count": 1,
                            "changed_marketplaces": {"UK": 1},
                            "sample_changed_records": [
                                {
                                    "key": "UK||SKU-1||B0TEST",
                                    "marketplace": "UK",
                                    "sku": "SKU-1",
                                    "asin": "B0TEST",
                                    "product_name": "Risk product",
                                    "changed_fields": [
                                        {"field": "selling_price", "before": "40", "after": "20"},
                                        {"field": "profit_after_10pct_ads", "before": "2", "after": "-1"},
                                        {"field": "suggested_target_acos", "before": "0.2", "after": "0"},
                                        {"field": "total_cost_before_ads", "before": "18", "after": "25"},
                                    ],
                                }
                            ],
                        }
                    },
                    "SKU匹配检查": {
                        "keyed_diff": {
                            "sample_changed_records": [
                                {
                                    "key": "UK||SKU-1||B0TEST",
                                    "changed_fields": [
                                        {"field": "current_inventory", "before": "0", "after": "50"}
                                    ],
                                }
                            ]
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    packet.UNKNOWN_AUDIT.write_text("[]", encoding="utf-8")

    code = packet.main(["--no-refresh-status"])
    payload = json.loads(packet.PACKET_JSON.read_text(encoding="utf-8"))
    markdown = packet.PACKET_MARKDOWN.read_text(encoding="utf-8")

    assert code == 0
    assert payload["showcase_ready"] is True
    assert payload["business_submit_ready"] is False
    assert payload["strict_blockers"] == [
        "manual config confirmation missing",
        "unknown inbox business files present",
    ]
    assert payload["business_confirmation_valid"] is True
    assert payload["business_confirmation_status"] == "confirmed"
    assert payload["business_confirmation_file"] == "/tmp/business_review_confirmation.json"
    assert payload["strict_readiness_passed"] is False
    assert payload["strict_readiness_exit_code"] == 1
    assert payload["cost_config_changed_cells"] == 10
    assert payload["cost_config_changed_product_records"] == 1
    assert payload["cost_config"]["changed_cells"] == 10
    assert payload["cost_config"]["high_risk_rows"][0]["sku"] == "SKU-1"
    assert "售价变动超过 30%" in payload["cost_config"]["high_risk_rows"][0]["reasons"]
    assert "10% 广告费后利润为负" in payload["cost_config"]["high_risk_rows"][0]["reasons"]
    assert "# 业务确认包" in markdown
    assert "manual config confirmation missing" in markdown
    assert "seller_central_promotion_metrics" in markdown
    assert "SKU-1" in markdown
    assert "业务确认记录：有效" in markdown


def test_business_review_packet_returns_failure_when_showcase_not_ready(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    packet.STATUS_REPORT.write_text(
        json.dumps({"showcase_ready": False, "business_submit_ready": False}),
        encoding="utf-8",
    )
    packet.COST_AUDIT.write_text(json.dumps({"total_changed_cells": 0}), encoding="utf-8")
    packet.UNKNOWN_AUDIT.write_text("[]", encoding="utf-8")

    assert packet.main(["--no-refresh-status"]) == 1


def test_business_review_packet_refreshes_status_by_default(monkeypatch, tmp_path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    packet.STATUS_REPORT.write_text(
        json.dumps({"showcase_ready": False, "business_submit_ready": False}),
        encoding="utf-8",
    )
    packet.COST_AUDIT.write_text(json.dumps({"total_changed_cells": 0}), encoding="utf-8")
    packet.UNKNOWN_AUDIT.write_text("[]", encoding="utf-8")

    def fake_refresh() -> None:
        packet.STATUS_REPORT.write_text(
            json.dumps(
                {
                    "showcase_ready": True,
                    "business_submit_ready": True,
                    "daily_update_blocked": False,
                    "business_confirmation_valid": True,
                    "business_confirmation_status": "confirmed",
                    "strict_readiness_passed": True,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(packet, "_refresh_status_report", fake_refresh)

    assert packet.main([]) == 0
    payload = json.loads(packet.PACKET_JSON.read_text(encoding="utf-8"))

    assert payload["showcase_ready"] is True
    assert payload["business_submit_ready"] is True
    assert payload["business_confirmation_valid"] is True
    assert payload["strict_readiness_passed"] is True
