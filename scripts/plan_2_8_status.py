"""Quick-status helper for the Plan 2.8 rollout.

Walks the repo for the artifacts each Plan-2.8 phase is supposed to
produce and prints a compact phase-by-phase report. Read-only.

Each phase has a list of *expected anchors* — file paths or workflow
files. The script reports each anchor as ``ok``, ``missing``, or (for
optional anchors) ``optional-missing``. Operators run this before a
W13 review to confirm everything is in place; CI runs it as a daily
sanity ping.

Exit codes
----------
  0 = all required anchors present (some optional may be missing)
  1 = at least one required anchor missing or unreadable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


PHASES: list[dict[str, Any]] = [
    {
        "name": "Phase 0 - tooltips + grounding",
        "anchors": [
            ("required", "docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md"),
            ("required", "tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py"),
            ("required", "SMC_Core_Engine.pine"),
        ],
    },
    {
        "name": "Phase 1 - 4-TF benchmark + per-TF rollup",
        "anchors": [
            ("required", "scripts/plan_2_8_tf_family_rollup.py"),
            ("required", "tests/test_plan_2_8_tf_family_rollup.py"),
            ("required", "tests/test_plan_2_8_s3_1_chart_tf_expansion.py"),
            ("required", "tests/test_plan_2_8_s3_1_per_tf_partitioning.py"),
            ("required", "tests/test_plan_2_8_rolling_workflow_rollup_wiring.py"),
            ("required", "tests/test_plan_2_8_rolling_workflow_history_wiring.py"),
            ("required", "scripts/plan_2_8_history_archive.py"),
            ("required", "scripts/plan_2_8_history_rotate.py"),
            ("required", "scripts/plan_2_8_history_validate.py"),
            ("required", "tests/test_plan_2_8_history_validate.py"),
            ("required", "scripts/plan_2_8_history_diff.py"),
            ("required", "tests/test_plan_2_8_history_diff.py"),
            ("required", "scripts/plan_2_8_top_movers.py"),
            ("required", "tests/test_plan_2_8_top_movers.py"),
            ("required", "scripts/plan_2_8_alert_snooze.py"),
            ("required", "tests/test_plan_2_8_alert_snooze.py"),
            ("required", "configs/plan_2_8_snoozes.json"),
            ("required", "scripts/plan_2_8_coverage.py"),
            ("required", "tests/test_plan_2_8_coverage.py"),
            ("required", "scripts/plan_2_8_history_stability.py"),
            ("required", "tests/test_plan_2_8_history_stability.py"),
            ("required", "scripts/plan_2_8_snooze_admin.py"),
            ("required", "tests/test_plan_2_8_snooze_admin.py"),
            ("required", "scripts/plan_2_8_snooze_lint.py"),
            ("required", "tests/test_plan_2_8_snooze_lint.py"),
            ("required", "scripts/plan_2_8_history_backfill.py"),
            ("required", "tests/test_plan_2_8_history_backfill.py"),
            ("required", "scripts/plan_2_8_adr_queue.py"),
            ("required", "tests/test_plan_2_8_adr_queue.py"),
            ("required", "scripts/plan_2_8_weekly_runcard.py"),
            ("required", "tests/test_plan_2_8_weekly_runcard.py"),
            ("required", "scripts/plan_2_8_health.py"),
            ("required", "tests/test_plan_2_8_health.py"),
            ("required", "scripts/plan_2_8_changelog_digest.py"),
            ("required", "tests/test_plan_2_8_changelog_digest.py"),
            ("required", "scripts/plan_2_8_runcard_index.py"),
            ("required", "tests/test_plan_2_8_runcard_index.py"),
            ("required", "scripts/plan_2_8_digest_compare.py"),
            ("required", "tests/test_plan_2_8_digest_compare.py"),
            ("required", "scripts/plan_2_8_alert_history_heatmap.py"),
            ("required", "tests/test_plan_2_8_alert_history_heatmap.py"),
            ("required", "scripts/plan_2_8_runbook_toc.py"),
            ("required", "tests/test_plan_2_8_runbook_toc.py"),
            ("required", "scripts/plan_2_8_status_snapshot.py"),
            ("required", "tests/test_plan_2_8_status_snapshot.py"),
            ("required", "scripts/plan_2_8_digest_archive.py"),
            ("required", "tests/test_plan_2_8_digest_archive.py"),
            ("required", "scripts/plan_2_8_runcard_from_status.py"),
            ("required", "tests/test_plan_2_8_runcard_from_status.py"),
            ("required", "scripts/plan_2_8_history_prune.py"),
            ("required", "tests/test_plan_2_8_history_prune.py"),
            ("required", "scripts/plan_2_8_history_export.py"),
            ("required", "tests/test_plan_2_8_history_export.py"),
            ("required", "scripts/plan_2_8_runbook_link_check.py"),
            ("required", "tests/test_plan_2_8_runbook_link_check.py"),
            ("required", "scripts/plan_2_8_snooze_expiry_report.py"),
            ("required", "tests/test_plan_2_8_snooze_expiry_report.py"),
            ("required", "scripts/plan_2_8_manifest.py"),
            ("required", "tests/test_plan_2_8_manifest.py"),
            ("required", "scripts/plan_2_8_manifest_diff.py"),
            ("required", "tests/test_plan_2_8_manifest_diff.py"),
            ("required", "scripts/plan_2_8_digest_schema.py"),
            ("required", "tests/test_plan_2_8_digest_schema.py"),
            ("required", "scripts/plan_2_8_runcard_badge.py"),
            ("required", "tests/test_plan_2_8_runcard_badge.py"),
            ("required", "scripts/plan_2_8_badge_markdown.py"),
            ("required", "tests/test_plan_2_8_badge_markdown.py"),
            ("required", "scripts/plan_2_8_alert_trend.py"),
            ("required", "tests/test_plan_2_8_alert_trend.py"),
            ("required", "scripts/plan_2_8_alert_trend_gate.py"),
            ("required", "tests/test_plan_2_8_alert_trend_gate.py"),
            ("required", "scripts/plan_2_8_digest_to_coverage.py"),
            ("required", "tests/test_plan_2_8_digest_to_coverage.py"),
            ("required", "scripts/plan_2_8_runbook_sections.py"),
            ("required", "tests/test_plan_2_8_runbook_sections.py"),
            ("required", "scripts/plan_2_8_status_ledger.py"),
            ("required", "tests/test_plan_2_8_status_ledger.py"),
            ("required", "scripts/plan_2_8_status_ledger_summarize.py"),
            ("required", "tests/test_plan_2_8_status_ledger_summarize.py"),
            ("required", "scripts/plan_2_8_status_ledger_prune.py"),
            ("required", "tests/test_plan_2_8_status_ledger_prune.py"),
            ("required", "scripts/plan_2_8_weekly_index.py"),
            ("required", "tests/test_plan_2_8_weekly_index.py"),
            ("required", "scripts/plan_2_8_run_stamp.py"),
            ("required", "tests/test_plan_2_8_run_stamp.py"),
            ("required", "scripts/plan_2_8_status_flip_alert.py"),
            ("required", "tests/test_plan_2_8_status_flip_alert.py"),
            ("required", "scripts/plan_2_8_ledger_csv_export.py"),
            ("required", "tests/test_plan_2_8_ledger_csv_export.py"),
            ("required", "scripts/plan_2_8_ledger_validate.py"),
            ("required", "tests/test_plan_2_8_ledger_validate.py"),
            ("required", "scripts/plan_2_8_ledger_stats_json.py"),
            ("required", "tests/test_plan_2_8_ledger_stats_json.py"),
            ("required", "scripts/plan_2_8_artifact_checksum.py"),
            ("required", "tests/test_plan_2_8_artifact_checksum.py"),
            ("required", "scripts/plan_2_8_digest_archive_index.py"),
            ("required", "tests/test_plan_2_8_digest_archive_index.py"),
            ("required", "scripts/plan_2_8_checksum_verify.py"),
            ("required", "tests/test_plan_2_8_checksum_verify.py"),
            ("required", "scripts/plan_2_8_ledger_status_matrix.py"),
            ("required", "tests/test_plan_2_8_ledger_status_matrix.py"),
            ("required", "scripts/plan_2_8_digest_size_budget.py"),
            ("required", "tests/test_plan_2_8_digest_size_budget.py"),
            ("required", "scripts/plan_2_8_ledger_downtime.py"),
            ("required", "tests/test_plan_2_8_ledger_downtime.py"),
            ("required", "scripts/plan_2_8_ledger_weekly_rollup.py"),
            ("required", "tests/test_plan_2_8_ledger_weekly_rollup.py"),
            ("required", "scripts/plan_2_8_digest_index_compare.py"),
            ("required", "tests/test_plan_2_8_digest_index_compare.py"),
            ("required", "scripts/plan_2_8_ledger_uptime_pct.py"),
            ("required", "tests/test_plan_2_8_ledger_uptime_pct.py"),
            ("required", "scripts/plan_2_8_digest_file_manifest.py"),
            ("required", "tests/test_plan_2_8_digest_file_manifest.py"),
            ("required", "scripts/plan_2_8_weekly_summary_index.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_index.py"),
            ("required", "scripts/plan_2_8_ledger_latest_status.py"),
            ("required", "tests/test_plan_2_8_ledger_latest_status.py"),
            ("required", "scripts/plan_2_8_ledger_longest_streak.py"),
            ("required", "tests/test_plan_2_8_ledger_longest_streak.py"),
            ("required", "scripts/plan_2_8_digest_metadata.py"),
            ("required", "tests/test_plan_2_8_digest_metadata.py"),
            ("required", "scripts/plan_2_8_metadata_diff.py"),
            ("required", "tests/test_plan_2_8_metadata_diff.py"),
            ("required", "scripts/plan_2_8_ledger_trend.py"),
            ("required", "tests/test_plan_2_8_ledger_trend.py"),
            ("required", "scripts/plan_2_8_weekly_summary_linkcheck.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_linkcheck.py"),
            ("required", "scripts/plan_2_8_ledger_flap_rate.py"),
            ("required", "tests/test_plan_2_8_ledger_flap_rate.py"),
            ("required", "scripts/plan_2_8_trend_threshold_alert.py"),
            ("required", "tests/test_plan_2_8_trend_threshold_alert.py"),
            ("required", "scripts/plan_2_8_digest_artifact_catalog.py"),
            ("required", "tests/test_plan_2_8_digest_artifact_catalog.py"),
            ("required", "scripts/plan_2_8_ledger_status_today.py"),
            ("required", "tests/test_plan_2_8_ledger_status_today.py"),
            ("required", "scripts/plan_2_8_digest_recent_changes.py"),
            ("required", "tests/test_plan_2_8_digest_recent_changes.py"),
            ("required", "scripts/plan_2_8_weekly_summary_toc_only.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_toc_only.py"),
            ("required", "scripts/plan_2_8_ledger_streak_now.py"),
            ("required", "tests/test_plan_2_8_ledger_streak_now.py"),
            ("required", "scripts/plan_2_8_digest_artifact_age.py"),
            ("required", "tests/test_plan_2_8_digest_artifact_age.py"),
            ("required", "scripts/plan_2_8_ledger_month_summary.py"),
            ("required", "tests/test_plan_2_8_ledger_month_summary.py"),
            ("required", "scripts/plan_2_8_ledger_worst_day.py"),
            ("required", "tests/test_plan_2_8_ledger_worst_day.py"),
            ("required", "scripts/plan_2_8_digest_catalog_diff.py"),
            ("required", "tests/test_plan_2_8_digest_catalog_diff.py"),
            ("required", "scripts/plan_2_8_weekly_summary_section_stats.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_section_stats.py"),
            ("required", "scripts/plan_2_8_ledger_best_day.py"),
            ("required", "tests/test_plan_2_8_ledger_best_day.py"),
            ("required", "scripts/plan_2_8_digest_size_trend.py"),
            ("required", "tests/test_plan_2_8_digest_size_trend.py"),
            ("required", "scripts/plan_2_8_weekly_summary_heading_order.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_heading_order.py"),
            ("required", "scripts/plan_2_8_ledger_status_share.py"),
            ("required", "tests/test_plan_2_8_ledger_status_share.py"),
            ("required", "scripts/plan_2_8_digest_missing_artifacts.py"),
            ("required", "tests/test_plan_2_8_digest_missing_artifacts.py"),
            ("required", "scripts/plan_2_8_weekly_summary_toc_checksum.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_toc_checksum.py"),
            ("required", "scripts/plan_2_8_ledger_hour_histogram.py"),
            ("required", "tests/test_plan_2_8_ledger_hour_histogram.py"),
            ("required", "scripts/plan_2_8_digest_stale_report.py"),
            ("required", "tests/test_plan_2_8_digest_stale_report.py"),
            ("required", "scripts/plan_2_8_weekly_summary_required_sections.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_required_sections.py"),
            ("required", "scripts/plan_2_8_ledger_weekday_histogram.py"),
            ("required", "tests/test_plan_2_8_ledger_weekday_histogram.py"),
            ("required", "scripts/plan_2_8_digest_summary_index.py"),
            ("required", "tests/test_plan_2_8_digest_summary_index.py"),
            ("required", "scripts/plan_2_8_ledger_gap_detector.py"),
            ("required", "tests/test_plan_2_8_ledger_gap_detector.py"),
            ("required", "scripts/plan_2_8_ledger_transition_matrix.py"),
            ("required", "tests/test_plan_2_8_ledger_transition_matrix.py"),
            ("required", "scripts/plan_2_8_digest_hash_inventory.py"),
            ("required", "tests/test_plan_2_8_digest_hash_inventory.py"),
            ("required", "scripts/plan_2_8_weekly_summary_preview.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_preview.py"),
            ("required", "scripts/plan_2_8_ledger_latest_flip.py"),
            ("required", "tests/test_plan_2_8_ledger_latest_flip.py"),
            ("required", "scripts/plan_2_8_digest_filetype_breakdown.py"),
            ("required", "tests/test_plan_2_8_digest_filetype_breakdown.py"),
            ("required", "scripts/plan_2_8_weekly_summary_word_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_word_count.py"),
            ("required", "scripts/plan_2_8_ledger_first_flip.py"),
            ("required", "tests/test_plan_2_8_ledger_first_flip.py"),
            ("required", "scripts/plan_2_8_digest_largest_files.py"),
            ("required", "tests/test_plan_2_8_digest_largest_files.py"),
            ("required", "scripts/plan_2_8_weekly_summary_code_blocks.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_code_blocks.py"),
            ("required", "scripts/plan_2_8_ledger_status_run_length.py"),
            ("required", "tests/test_plan_2_8_ledger_status_run_length.py"),
            ("required", "scripts/plan_2_8_digest_smallest_files.py"),
            ("required", "tests/test_plan_2_8_digest_smallest_files.py"),
            ("required", "scripts/plan_2_8_weekly_summary_link_check.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_link_check.py"),
            ("required", "scripts/plan_2_8_ledger_longest_run.py"),
            ("required", "tests/test_plan_2_8_ledger_longest_run.py"),
            ("required", "scripts/plan_2_8_digest_size_histogram.py"),
            ("required", "tests/test_plan_2_8_digest_size_histogram.py"),
            ("required", "scripts/plan_2_8_weekly_summary_list_stats.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_list_stats.py"),
            ("required", "scripts/plan_2_8_ledger_last_n_summary.py"),
            ("required", "tests/test_plan_2_8_ledger_last_n_summary.py"),
            ("required", "scripts/plan_2_8_digest_mean_size.py"),
            ("required", "tests/test_plan_2_8_digest_mean_size.py"),
            ("required", "scripts/plan_2_8_weekly_summary_tables_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_tables_count.py"),
            ("required", "scripts/plan_2_8_ledger_recent_green_ratio.py"),
            ("required", "tests/test_plan_2_8_ledger_recent_green_ratio.py"),
            ("required", "scripts/plan_2_8_digest_median_size.py"),
            ("required", "tests/test_plan_2_8_digest_median_size.py"),
            ("required", "scripts/plan_2_8_weekly_summary_emphasis_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_emphasis_count.py"),
            ("required", "scripts/plan_2_8_ledger_status_streaks.py"),
            ("required", "tests/test_plan_2_8_ledger_status_streaks.py"),
            ("required", "scripts/plan_2_8_digest_oldest_newest.py"),
            ("required", "tests/test_plan_2_8_digest_oldest_newest.py"),
            ("required", "scripts/plan_2_8_weekly_summary_image_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_image_count.py"),
            ("required", "scripts/plan_2_8_ledger_distinct_days.py"),
            ("required", "tests/test_plan_2_8_ledger_distinct_days.py"),
            ("required", "scripts/plan_2_8_digest_extension_coverage.py"),
            ("required", "tests/test_plan_2_8_digest_extension_coverage.py"),
            ("required", "scripts/plan_2_8_weekly_summary_paragraph_stats.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_paragraph_stats.py"),
            ("required", "scripts/plan_2_8_ledger_amber_ratio.py"),
            ("required", "tests/test_plan_2_8_ledger_amber_ratio.py"),
            ("required", "scripts/plan_2_8_digest_name_length_stats.py"),
            ("required", "tests/test_plan_2_8_digest_name_length_stats.py"),
            ("required", "scripts/plan_2_8_weekly_summary_heading_hierarchy.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_heading_hierarchy.py"),
            ("required", "scripts/plan_2_8_ledger_red_ratio.py"),
            ("required", "tests/test_plan_2_8_ledger_red_ratio.py"),
            ("required", "scripts/plan_2_8_digest_file_age_stats.py"),
            ("required", "tests/test_plan_2_8_digest_file_age_stats.py"),
            ("required", "scripts/plan_2_8_weekly_summary_blockquote_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_blockquote_count.py"),
            ("required", "scripts/plan_2_8_ledger_unknown_ratio.py"),
            ("required", "tests/test_plan_2_8_ledger_unknown_ratio.py"),
            ("required", "scripts/plan_2_8_digest_empty_files.py"),
            ("required", "tests/test_plan_2_8_digest_empty_files.py"),
            ("required", "scripts/plan_2_8_weekly_summary_hr_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_hr_count.py"),
            ("required", "scripts/plan_2_8_ledger_median_gap.py"),
            ("required", "tests/test_plan_2_8_ledger_median_gap.py"),
            ("required", "scripts/plan_2_8_digest_empty_ratio.py"),
            ("required", "tests/test_plan_2_8_digest_empty_ratio.py"),
            ("required", "scripts/plan_2_8_weekly_summary_inline_code_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_inline_code_count.py"),
            ("required", "scripts/plan_2_8_ledger_unique_statuses.py"),
            ("required", "tests/test_plan_2_8_ledger_unique_statuses.py"),
            ("required", "scripts/plan_2_8_digest_size_sum.py"),
            ("required", "tests/test_plan_2_8_digest_size_sum.py"),
            ("required", "scripts/plan_2_8_weekly_summary_table_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_table_count.py"),
            ("required", "scripts/plan_2_8_ledger_first_green_age.py"),
            ("required", "tests/test_plan_2_8_ledger_first_green_age.py"),
            ("required", "scripts/plan_2_8_digest_largest_file.py"),
            ("required", "tests/test_plan_2_8_digest_largest_file.py"),
            ("required", "scripts/plan_2_8_weekly_summary_link_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_link_count.py"),
            ("required", "scripts/plan_2_8_ledger_latest_captured_at.py"),
            ("required", "tests/test_plan_2_8_ledger_latest_captured_at.py"),
            ("required", "scripts/plan_2_8_digest_smallest_file.py"),
            ("required", "tests/test_plan_2_8_digest_smallest_file.py"),
            ("required", "scripts/plan_2_8_weekly_summary_list_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_list_count.py"),
            ("required", "scripts/plan_2_8_ledger_oldest_captured_at.py"),
            ("required", "tests/test_plan_2_8_ledger_oldest_captured_at.py"),
            ("required", "scripts/plan_2_8_digest_ext_top.py"),
            ("required", "tests/test_plan_2_8_digest_ext_top.py"),
            ("required", "scripts/plan_2_8_weekly_summary_ordered_list_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_ordered_list_count.py"),
            ("required", "scripts/plan_2_8_ledger_captures_per_day.py"),
            ("required", "tests/test_plan_2_8_ledger_captures_per_day.py"),
            ("required", "scripts/plan_2_8_digest_tiny_files.py"),
            ("required", "tests/test_plan_2_8_digest_tiny_files.py"),
            ("required", "scripts/plan_2_8_weekly_summary_sha256.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_sha256.py"),
            ("required", "scripts/plan_2_8_ledger_longest_gap.py"),
            ("required", "tests/test_plan_2_8_ledger_longest_gap.py"),
            ("required", "scripts/plan_2_8_digest_duplicate_sizes.py"),
            ("required", "tests/test_plan_2_8_digest_duplicate_sizes.py"),
            ("required", "scripts/plan_2_8_weekly_summary_longest_line.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_longest_line.py"),
            ("required", "scripts/plan_2_8_ledger_green_streak_history.py"),
            ("required", "tests/test_plan_2_8_ledger_green_streak_history.py"),
            ("required", "scripts/plan_2_8_digest_oldest_file.py"),
            ("required", "tests/test_plan_2_8_digest_oldest_file.py"),
            ("required", "scripts/plan_2_8_weekly_summary_footnote_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_footnote_count.py"),
            ("required", "scripts/plan_2_8_ledger_first_red.py"),
            ("required", "tests/test_plan_2_8_ledger_first_red.py"),
            ("required", "scripts/plan_2_8_digest_newest_file.py"),
            ("required", "tests/test_plan_2_8_digest_newest_file.py"),
            ("required", "scripts/plan_2_8_weekly_summary_bold_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_bold_count.py"),
            ("required", "scripts/plan_2_8_ledger_first_amber.py"),
            ("required", "tests/test_plan_2_8_ledger_first_amber.py"),
            ("required", "scripts/plan_2_8_digest_median_mtime.py"),
            ("required", "tests/test_plan_2_8_digest_median_mtime.py"),
            ("required", "scripts/plan_2_8_weekly_summary_strikethrough_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_strikethrough_count.py"),
            ("required", "scripts/plan_2_8_ledger_first_unknown.py"),
            ("required", "tests/test_plan_2_8_ledger_first_unknown.py"),
            ("required", "scripts/plan_2_8_digest_mtime_span.py"),
            ("required", "tests/test_plan_2_8_digest_mtime_span.py"),
            ("required", "scripts/plan_2_8_weekly_summary_reference_defs.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_reference_defs.py"),
            ("required", "scripts/plan_2_8_ledger_last_red.py"),
            ("required", "tests/test_plan_2_8_ledger_last_red.py"),
            ("required", "scripts/plan_2_8_digest_per_ext_bytes.py"),
            ("required", "tests/test_plan_2_8_digest_per_ext_bytes.py"),
            ("required", "scripts/plan_2_8_weekly_summary_html_tag_count.py"),
            ("required", "tests/test_plan_2_8_weekly_summary_html_tag_count.py"),
            ("required", "scripts/plan_2_8_alert_history.py"),
            ("required", "tests/test_plan_2_8_alert_history.py"),
            ("required", "scripts/plan_2_8_alert_history_summary.py"),
            ("required", "tests/test_plan_2_8_alert_history_summary.py"),
            ("required", "scripts/plan_2_8_digest_rollup.py"),
            ("required", "tests/test_plan_2_8_digest_rollup.py"),
            ("required", ".github/workflows/plan-2-8-monthly-digest.yml"),
            ("required", "tests/test_plan_2_8_monthly_digest_workflow.py"),
            ("required", "tests/test_plan_2_8_rolling_workflow_rotate_wiring.py"),
            ("required", "tests/test_plan_2_8_rolling_workflow_validate_wiring.py"),
            ("required", "scripts/plan_2_8_trend_digest.py"),
            ("required", "tests/test_plan_2_8_trend_digest_issue_body.py"),
            ("required", "tests/test_plan_2_8_weekly_digest_issue_wiring.py"),
            ("required", ".github/workflows/smc-measurement-benchmark-rolling.yml"),
            ("required", ".github/workflows/plan-2-8-weekly-digest.yml"),
        ],
    },
    {
        "name": "Phase 2 - A/B bundle builder",
        "anchors": [
            ("required", "scripts/plan_2_8_q4_gate_bundle_builder.py"),
            ("required", "tests/test_plan_2_8_q4_gate_bundle_builder.py"),
            ("optional", "artifacts/plan_2_8_q4_gate_bundle.json"),
        ],
    },
    {
        "name": "Phase 3 - Q4 gate evaluator + dryrun + ADR",
        "anchors": [
            ("required", "scripts/plan_2_8_q4_gate_evaluator.py"),
            ("required", "tests/test_plan_2_8_q4_gate_evaluator.py"),
            ("required", ".github/workflows/plan-2-8-q4-gate-dryrun.yml"),
            ("required", "tests/test_plan_2_8_q4_gate_workflow.py"),
            ("required", "scripts/append_adr.py"),
            ("required", "tests/test_append_adr.py"),
            ("required", "docs/DECISIONS.md"),
            ("required", "tests/test_docs_decisions_adr.py"),
            ("required", "docs/plan_2_8_rollout_runbook.md"),
            ("required", "tests/test_plan_2_8_rollout_runbook.py"),
        ],
    },
]


def evaluate_status(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Walk the phase anchor list under ``repo_root`` and return a status dict."""
    phases_out: list[dict[str, Any]] = []
    overall_ok = True
    for phase in PHASES:
        anchors_out: list[dict[str, Any]] = []
        phase_ok = True
        for kind, rel in phase["anchors"]:
            path = repo_root / rel
            present = path.exists()
            if not present and kind == "required":
                status = "missing"
                phase_ok = False
                overall_ok = False
            elif not present:
                status = "optional-missing"
            else:
                status = "ok"
            anchors_out.append({"path": rel, "kind": kind, "status": status})
        phases_out.append({
            "name": phase["name"],
            "ok": phase_ok,
            "anchors": anchors_out,
        })
    return {
        "schema_version": 1,
        "ok": overall_ok,
        "phases": phases_out,
    }


def render_markdown(status: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Plan 2.8 phase status")
    lines.append("")
    lines.append(f"overall: **{'ok' if status['ok'] else 'INCOMPLETE'}**")
    lines.append("")
    for phase in status["phases"]:
        marker = "ok" if phase["ok"] else "INCOMPLETE"
        lines.append(f"## {phase['name']}  ({marker})")
        lines.append("")
        lines.append("| anchor | kind | status |")
        lines.append("| --- | --- | :---: |")
        for a in phase["anchors"]:
            lines.append(f"| `{a['path']}` | {a['kind']} | {a['status']} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan 2.8 rollout status report.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    status = evaluate_status(args.repo_root)
    body = (
        render_markdown(status) if args.format == "md"
        else json.dumps(status, indent=2) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0 if status["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
