from __future__ import annotations

import html
import sys
from pathlib import Path

from .analyze_rules import money_symbol_for_marketplace
from .autoopt_feedback import load_feedback_input
from .html_pages import common as common_page
from .html_pages import components_ad_workbench as ad_workbench_components
from .html_pages import components_cards as cards_components
from .html_pages import components_common as common_components
from .html_pages import components_frontend as frontend_components
from .html_pages import components_review as review_components
from .html_pages import dashboard as dashboard_page
from .html_pages import marketplace as marketplace_page
from .html_pages import recommendations as recommendations_page
from .html_pages import summary as summary_page
from .html_pages.assets import CSS, REPORT_JS, REPORT_UI_CSS
from .report_presentation import data_quality_status_from_summary


MARKETPLACE_DISPLAY_ORDER = {"US": 0, "UK": 1, "DE": 2}


def _inline_markup(text: str) -> str:
    escaped = html.escape(text)
    parts = escaped.split("`")
    if len(parts) == 1:
        return escaped
    rendered: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            rendered.append(f"<code>{part}</code>")
        else:
            rendered.append(part)
    return "".join(rendered)


def _first_present(row: dict[str, object], *fields: str) -> object:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return ""


def _marketplace_sort_key(value: object) -> tuple[int, str]:
    marketplace = str(value or "N/A").upper()
    return (MARKETPLACE_DISPLAY_ORDER.get(marketplace, 99), marketplace)


def _sort_results_by_marketplace(results: list[dict]) -> list[dict]:
    return sorted(results, key=lambda result: _marketplace_sort_key(result.get("marketplace")))


def _num_from_text(value: object) -> float:
    text = str(value or "")
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _render_boss_summary(
    report_date: str,
    p0_count: int,
    p1_count: int,
    listing_count: int,
    review_count: int,
    quality_warn_count: int,
    all_tasks: list[dict[str, str]],
    all_listing_reviews: list[dict[str, str]],
    all_search: list[dict[str, str]] | None = None,
    show_p1_link: bool = True,
) -> str:
    return common_page._render_boss_summary(
        sys.modules[__name__],
        report_date,
        p0_count,
        p1_count,
        listing_count,
        review_count,
        quality_warn_count,
        all_tasks,
        all_listing_reviews,
        all_search,
        show_p1_link,
    )


def _row_class(cells: list[str]) -> str:
    return common_components._row_class(sys.modules[__name__], cells)


def _render_table(headers: list[str], rows: list[dict[str, str]]) -> str:
    return common_components._render_table(sys.modules[__name__], headers, rows)


def _render_collapsed_section(
    title: str,
    content: str,
    intro: str = "",
    *,
    open_by_default: bool = False,
    section_id: str = "",
) -> str:
    return common_components._render_collapsed_section(
        sys.modules[__name__],
        title,
        content,
        intro,
        open_by_default=open_by_default,
        section_id=section_id,
    )


def _render_collapsed_block(title: str, content: str, intro: str = "", *, open_by_default: bool = False) -> str:
    return common_components._render_collapsed_block(
        sys.modules[__name__],
        title,
        content,
        intro,
        open_by_default=open_by_default,
    )


def _render_bullets(items: list[str]) -> str:
    return common_components._render_bullets(sys.modules[__name__], items)


def _tag_class(action: str) -> str:
    return common_components._tag_class(sys.modules[__name__], action)


def _confirmed_tag(status: object) -> str:
    return common_components._confirmed_tag(sys.modules[__name__], status)


def _amazon_product_url(marketplace: object, asin: object) -> str:
    return common_components._amazon_product_url(sys.modules[__name__], marketplace, asin)


def _asin_link_html(marketplace: object, asin: object) -> str:
    return common_components._asin_link_html(sys.modules[__name__], marketplace, asin)


def _product_meta_html(
    row: dict[str, object],
    *,
    asin_key: str = "asin",
    sku_key: str = "sku",
    marketplace_key: str = "marketplace",
    include_frontend_link: bool = True,
) -> str:
    return common_components._product_meta_html(
        sys.modules[__name__],
        row,
        asin_key=asin_key,
        sku_key=sku_key,
        marketplace_key=marketplace_key,
        include_frontend_link=include_frontend_link,
    )


def _frontend_key(row: dict[str, object]) -> tuple[str, str, str]:
    return common_components._frontend_key(sys.modules[__name__], row)


def _build_frontend_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, str]]:
    return common_components._build_frontend_lookup(sys.modules[__name__], rows)


def _lookup_frontend_evidence(
    row: dict[str, object],
    frontend_lookup: dict[tuple[str, str, str], dict[str, str]] | None,
) -> dict[str, str] | None:
    return common_components._lookup_frontend_evidence(sys.modules[__name__], row, frontend_lookup)


def _value_list(value: object) -> list[str]:
    return common_components._value_list(sys.modules[__name__], value)


def _fmt_signed_percent(value: object) -> str:
    return common_components._fmt_signed_percent(sys.modules[__name__], value)


def _fmt_signed_number(value: object, digits: int = 1) -> str:
    return common_components._fmt_signed_number(sys.modules[__name__], value, digits)


def _frontend_status_label(raw_status: str, row: dict[str, object]) -> str:
    return common_components._frontend_status_label(sys.modules[__name__], raw_status, row)


def _frontend_findings_text(findings: str) -> str:
    return common_components._frontend_findings_text(sys.modules[__name__], findings)


def _frontend_stability_badge(row: dict[str, object]) -> str:
    return common_components._frontend_stability_badge(sys.modules[__name__], row)


def _collect_report_counters(
    all_tasks: list[dict[str, str]],
    all_search: list[dict[str, str]],
    all_review: list[dict[str, str]],
    quality_rows: list[dict[str, str]],
    all_listing_reviews: list[dict[str, str]] | None = None,
) -> dict[str, int]:
    return common_components._collect_report_counters(
        sys.modules[__name__],
        all_tasks,
        all_search,
        all_review,
        quality_rows,
        all_listing_reviews,
    )


def _render_common_principles() -> str:
    return common_components._render_common_principles(sys.modules[__name__])


def _render_common_principles_body() -> str:
    return common_components._render_common_principles_body(sys.modules[__name__])


def _render_common_chatgpt_materials() -> str:
    return common_components._render_common_chatgpt_materials(sys.modules[__name__])


def _page_shell(title: str, body_html: str) -> str:
    return common_page._page_shell(sys.modules[__name__], title, body_html)


def _ensure_report_assets(output_dir: Path) -> None:
    common_page._ensure_report_assets(sys.modules[__name__], output_dir)


def _write_page(output_path: Path, title: str, body_html: str) -> None:
    common_page._write_page(sys.modules[__name__], output_path, title, body_html)


def _render_nav(current: str) -> str:
    return common_page._render_nav(sys.modules[__name__], current)


def _render_marketplace_status_cards(result: dict, view: dict, report_date: str) -> str:
    return common_page._render_marketplace_status_cards(sys.modules[__name__], result, view, report_date)


def markdown_to_html(markdown_text: str, title: str = "Amazon Daily Report") -> str:
    return common_page.markdown_to_html(sys.modules[__name__], markdown_text, title=title)


def write_html_report(markdown_text: str, output_path: Path, title: str = "Amazon Daily Report") -> None:
    common_page.write_html_report(sys.modules[__name__], markdown_text, output_path, title=title)


def write_recommendations_workbench_html(results: list[dict], output_path: Path, report_date: str) -> None:
    recommendations_page.write_recommendations_workbench_html(sys.modules[__name__], results, output_path, report_date)


def write_summary_html(results: list[dict], output_path: Path, report_date: str) -> None:
    summary_page.write_summary_html(sys.modules[__name__], results, output_path, report_date)


def _marketplace_currency(result: dict) -> str:
    return common_page._marketplace_currency(sys.modules[__name__], result)


def _marketplace_status_text(result: dict) -> tuple[str, str]:
    return common_page._marketplace_status_text(sys.modules[__name__], result)


def _render_frontend_evidence_block(
    row: dict[str, object],
    frontend_lookup: dict[tuple[str, str, str], dict[str, str]] | None,
) -> str:
    return frontend_components._render_frontend_evidence_block(
        sys.modules[__name__],
        row,
        frontend_lookup,
    )


def _render_frontend_gap_block(frontend: dict[str, object] | None) -> str:
    return frontend_components._render_frontend_gap_block(sys.modules[__name__], frontend)


def _frontend_queue_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return frontend_components._frontend_queue_counts(sys.modules[__name__], rows)


def _render_frontend_status_summary(rows: list[dict[str, str]]) -> str:
    return frontend_components._render_frontend_status_summary(sys.modules[__name__], rows)


def _render_frontend_check_cards(rows: list[dict[str, str]], limit: int = 5) -> str:
    return frontend_components._render_frontend_check_cards(sys.modules[__name__], rows, limit)


def _render_frontend_retry_tool() -> str:
    return frontend_components._render_frontend_retry_tool(sys.modules[__name__])


ACTIONABLE_COPY_LINES = ad_workbench_components.ACTIONABLE_COPY_LINES


def _render_search_queue_groups(
    rows: list[dict[str, str]], limit_per_group: int = 8, show_status: bool = True
) -> str:
    return ad_workbench_components._render_search_queue_groups(
        sys.modules[__name__],
        rows,
        limit_per_group=limit_per_group,
        show_status=show_status,
    )


def _render_ad_copy_sections(rows: list[dict[str, str]]) -> str:
    return ad_workbench_components._render_ad_copy_sections(sys.modules[__name__], rows)


def _render_search_queue_evidence_groups(
    rows: list[dict[str, str]], limit_per_group: int = 8
) -> str:
    return ad_workbench_components._render_search_queue_evidence_groups(
        sys.modules[__name__], rows, limit_per_group=limit_per_group
    )


def _scale_keywords_as_ad_queue_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return ad_workbench_components._scale_keywords_as_ad_queue_rows(sys.modules[__name__], rows)


def _ad_action_label(row: dict[str, str]) -> str:
    return ad_workbench_components._ad_action_label(sys.modules[__name__], row)


def _ad_action_key(label: str) -> str:
    return ad_workbench_components._ad_action_key(sys.modules[__name__], label)


def _ad_status_key(row: dict[str, str]) -> str:
    return ad_workbench_components._ad_status_key(sys.modules[__name__], row)


def _ad_status_label(key: str) -> str:
    return ad_workbench_components._ad_status_label(sys.modules[__name__], key)


def _ad_status_class(key: str) -> str:
    return ad_workbench_components._ad_status_class(sys.modules[__name__], key)


def _ad_action_class(action_key: str) -> str:
    return ad_workbench_components._ad_action_class(sys.modules[__name__], action_key)


def _ad_action_badge_class(action_key: str) -> str:
    return ad_workbench_components._ad_action_badge_class(sys.modules[__name__], action_key)


def _ad_copy_groups(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    return ad_workbench_components._ad_copy_groups(sys.modules[__name__], rows)


def _ad_summary(
    rows: list[dict[str, str]], *, all_marketplaces: bool = False, marketplace_hint: str = ""
) -> dict[str, str]:
    return ad_workbench_components._ad_summary(
        sys.modules[__name__],
        rows,
        all_marketplaces=all_marketplaces,
        marketplace_hint=marketplace_hint,
    )


def _render_ad_copy_boxes(rows: list[dict[str, str]], prefix: str) -> str:
    return ad_workbench_components._render_ad_copy_boxes(sys.modules[__name__], rows, prefix)


def _render_ad_task_cards(rows: list[dict[str, str]]) -> str:
    return ad_workbench_components._render_ad_task_cards(sys.modules[__name__], rows)


def _render_ad_action_banner(
    rows: list[dict[str, str]], *, anchor_id: str, hidden_low_click_count: int = 0
) -> str:
    return ad_workbench_components._render_ad_action_banner(
        sys.modules[__name__],
        rows,
        anchor_id=anchor_id,
        hidden_low_click_count=hidden_low_click_count,
    )


def _is_observation_only_summary_row(row: dict[str, str]) -> bool:
    return ad_workbench_components._is_observation_only_summary_row(sys.modules[__name__], row)


def _render_ad_workbench(
    rows: list[dict[str, str]],
    *,
    all_marketplaces: bool,
    hidden_low_click_count: int = 0,
    title: str = "今天广告动作",
    marketplace_hint: str = "",
    anchor_id: str = "today-ad-actions",
    growth_test_rows: list[dict[str, str]] | None = None,
    keyword_review_count: int = 0,
    history_anchor: str = "action-effect-review",
) -> str:
    return ad_workbench_components._render_ad_workbench(
        sys.modules[__name__],
        rows,
        all_marketplaces=all_marketplaces,
        hidden_low_click_count=hidden_low_click_count,
        title=title,
        marketplace_hint=marketplace_hint,
        anchor_id=anchor_id,
        growth_test_rows=growth_test_rows,
        keyword_review_count=keyword_review_count,
        history_anchor=history_anchor,
    )


def _render_ad_workbench_status_only(
    rows: list[dict[str, str]],
    *,
    hidden_low_click_count: int = 0,
    marketplace_hint: str = "",
    section_id: str = "",
    show_details: bool = False,
    collapsed: bool = False,
) -> str:
    return ad_workbench_components._render_ad_workbench_status_only(
        sys.modules[__name__],
        rows,
        hidden_low_click_count=hidden_low_click_count,
        marketplace_hint=marketplace_hint,
        section_id=section_id,
        show_details=show_details,
        collapsed=collapsed,
    )


def _render_search_queue_by_marketplace(rows: list[dict[str, str]]) -> str:
    return ad_workbench_components._render_search_queue_by_marketplace(
        sys.modules[__name__], rows
    )


def _display_review_instruction(value: object) -> tuple[str, str]:
    return cards_components.with_shared(sys.modules[__name__], cards_components._display_review_instruction, value)


def _metric_badges_from_evidence(text: str, limit: int = 4) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._metric_badges_from_evidence, text, limit)


def _render_task_cards(
    rows: list[dict[str, str]],
    priority: str | None = None,
    limit: int | None = None,
    empty_message: str | None = "当前没有可展示内容。",
    frontend_lookup: dict[tuple[str, str, str], dict[str, str]] | None = None,
) -> str:
    return cards_components.with_shared(
        sys.modules[__name__],
        cards_components._render_task_cards,
        rows,
        priority,
        limit,
        empty_message,
        frontend_lookup,
    )


def _render_task_review_status(row: dict[str, str]) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_task_review_status, row)


def _exclude_listing_tasks(rows: list[dict[str, str]], p0_rows: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    return cards_components.with_shared(sys.modules[__name__], cards_components._exclude_listing_tasks, rows, p0_rows)


def _exclude_executed_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return cards_components.with_shared(sys.modules[__name__], cards_components._exclude_executed_rows, rows)


def _executed_risk_rows(rows: list[dict[str, str]], limit: int = 6) -> list[dict[str, str]]:
    return cards_components.with_shared(sys.modules[__name__], cards_components._executed_risk_rows, rows, limit)


def _filter_listing_rows_for_p0(listing_rows: list[dict[str, str]], task_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return cards_components.with_shared(sys.modules[__name__], cards_components._filter_listing_rows_for_p0, listing_rows, task_rows)


def _optional_num_from_text(value: object) -> float | None:
    return cards_components.with_shared(sys.modules[__name__], cards_components._optional_num_from_text, value)


def _render_watch_pool(rows: list[dict[str, str]], limit: int = 3) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_watch_pool, rows, limit)


def _render_profit_cost_cards(rows: list[dict[str, str]], limit: int = 3) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_profit_cost_cards, rows, limit)


def _render_scale_candidate_cards(rows: list[dict[str, str]], limit: int = 4) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_scale_candidate_cards, rows, limit)


def _render_scale_keyword_cards(rows: list[dict[str, str]], limit: int = 8) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_scale_keyword_cards, rows, limit)


def _render_product_final_decision_cards(rows: list[dict[str, str]], limit: int = 6) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_product_final_decision_cards, rows, limit)


def _format_operation_metric(value: object, marketplace: object = "", kind: str = "count") -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._format_operation_metric, value, marketplace, kind)


def _action_list_text(values: object, labels: dict[str, str]) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._action_list_text, values, labels)


def _action_item_count(values: object) -> int:
    return cards_components.with_shared(sys.modules[__name__], cards_components._action_item_count, values)


def _render_operation_ad_actions(rows: list[dict[str, str]]) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_operation_ad_actions, rows)


def _render_frontend_coverage_strip(summary: dict[str, object]) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_frontend_coverage_strip, summary)


def _render_product_operation_cards(rows: list[dict[str, str]], coverage_summary: dict[str, object] | None = None, limit: int = 8) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_product_operation_cards, rows, coverage_summary, limit)


def _render_inventory_replenishment_cards(rows: list[dict[str, str]], limit: int = 6) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_inventory_replenishment_cards, rows, limit)


def _render_listing_review_cards(
    rows: list[dict[str, str]],
    limit: int = 5,
    frontend_lookup: dict[tuple[str, str, str], dict[str, str]] | None = None,
) -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_listing_review_cards, rows, limit, frontend_lookup)


def _render_local_data_submit_tool() -> str:
    return cards_components.with_shared(sys.modules[__name__], cards_components._render_local_data_submit_tool)


def _render_review_list(rows: list[dict[str, str]], limit: int = 5) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_review_list, rows, limit)


def _render_optimization_notes(notes: list[str]) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_optimization_notes, notes)


def _render_action_review_cards(limit: int = 3, marketplace: str | None = None) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_action_review_cards, limit, marketplace)


def _render_yesterday_attribution(rows: list[dict[str, str]], limit: int = 6, compact: bool = False) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_yesterday_attribution, rows, limit, compact)


def _render_yesterday_attribution_strip(rows: list[dict[str, str]]) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_yesterday_attribution_strip, rows)


def _render_action_effect_review_rows(rows: list[dict[str, str]], limit: int = 5) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_action_effect_review_rows, rows, limit)


def _render_keyword_action_effect_review_rows(rows: list[dict[str, str]], limit: int = 5) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_keyword_action_effect_review_rows, rows, limit)


def _render_semicolon_list(text: object) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_semicolon_list, text)


def _render_semicolon_list_limited(text: object, limit: int = 2) -> str:
    return review_components.with_shared(sys.modules[__name__], review_components._render_semicolon_list_limited, text, limit)


def write_dashboard_html(results: list[dict], output_path: Path, report_date: str) -> None:
    dashboard_page.write_dashboard_html(sys.modules[__name__], results, output_path, report_date)


def write_marketplace_report_html(result: dict, output_path: Path, report_date: str) -> None:
    marketplace_page.write_marketplace_report_html(sys.modules[__name__], result, output_path, report_date)
