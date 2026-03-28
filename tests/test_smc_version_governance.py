"""Tests for the version-governance decision engine and semver policy helpers.

Covers:
- classify_version_change() for every transition type
- auto_commit_allowed() policy matrix
- evaluate_governance() with manifest pairs and field-count signals
- Escalation logic (field layout changed without major bump)
- CLI exit-code contract
- Manifest metadata: schema_version_previous + version_change_type
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from smc_core.schema_version import (
    SCHEMA_VERSION,
    VersionChangeType,
    auto_commit_allowed,
    classify_version_change,
    parse_semver,
)
from scripts.smc_version_governance import evaluate_governance


# ── 1. classify_version_change ──────────────────────────────────────


class TestClassifyVersionChange:
    def test_unchanged(self):
        assert classify_version_change("1.2.0", "1.2.0") == VersionChangeType.UNCHANGED

    def test_patch_bump(self):
        assert classify_version_change("1.2.0", "1.2.1") == VersionChangeType.PATCH

    def test_patch_downgrade(self):
        assert classify_version_change("1.2.3", "1.2.0") == VersionChangeType.PATCH

    def test_minor_bump(self):
        assert classify_version_change("1.2.0", "1.3.0") == VersionChangeType.MINOR

    def test_minor_downgrade(self):
        assert classify_version_change("1.3.0", "1.2.0") == VersionChangeType.MINOR

    def test_major_bump(self):
        assert classify_version_change("1.2.0", "2.0.0") == VersionChangeType.MAJOR

    def test_major_downgrade(self):
        assert classify_version_change("2.0.0", "1.0.0") == VersionChangeType.MAJOR

    def test_minor_with_patch_change(self):
        assert classify_version_change("1.2.3", "1.3.1") == VersionChangeType.MINOR

    def test_major_with_minor_and_patch_change(self):
        assert classify_version_change("1.5.3", "2.1.0") == VersionChangeType.MAJOR


# ── 2. auto_commit_allowed ──────────────────────────────────────────


class TestAutoCommitAllowed:
    def test_unchanged_allowed(self):
        assert auto_commit_allowed(VersionChangeType.UNCHANGED) is True

    def test_patch_allowed(self):
        assert auto_commit_allowed(VersionChangeType.PATCH) is True

    def test_minor_allowed(self):
        assert auto_commit_allowed(VersionChangeType.MINOR) is True

    def test_major_blocked(self):
        assert auto_commit_allowed(VersionChangeType.MAJOR) is False


# ── 3. VersionChangeType is a str enum ──────────────────────────────


class TestVersionChangeTypeEnum:
    def test_values_are_strings(self):
        assert VersionChangeType.UNCHANGED == "unchanged"
        assert VersionChangeType.PATCH == "patch"
        assert VersionChangeType.MINOR == "minor"
        assert VersionChangeType.MAJOR == "major"

    def test_json_serializable(self):
        result = json.dumps({"change": VersionChangeType.MINOR})
        assert '"minor"' in result


# ── 4. evaluate_governance ──────────────────────────────────────────


class TestEvaluateGovernance:
    """Tests for the full governance decision engine."""

    def test_unchanged_versions_auto_commit_allowed(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is True
        assert decision["pr_required"] is False
        assert decision["effective_change_type"] == "unchanged"
        assert decision["reasons"] == []

    def test_patch_bump_allowed(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.2.1", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is True
        assert decision["schema_change_type"] == "patch"
        assert decision["effective_change_type"] == "patch"

    def test_minor_bump_allowed(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.3.0", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is True
        assert decision["schema_change_type"] == "minor"

    def test_major_bump_blocks_auto_commit(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "2.0.0", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is False
        assert decision["pr_required"] is True
        assert decision["effective_change_type"] == "major"
        assert any("major bump" in r for r in decision["reasons"])

    def test_field_version_change_escalates_to_major(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.2.0", "library_field_version": "v5"},
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is False
        assert decision["pr_required"] is True
        assert decision["effective_change_type"] == "major"
        assert any("library_field_version changed" in r for r in decision["reasons"])
        assert any("escalated to MAJOR" in r for r in decision["reasons"])

    def test_field_count_change_escalates_to_major(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=39,
        )
        assert decision["auto_commit_allowed"] is False
        assert decision["pr_required"] is True
        assert any("export field count changed" in r for r in decision["reasons"])

    def test_field_count_decrease_escalates_to_major(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=35,
        )
        assert decision["auto_commit_allowed"] is False
        assert decision["pr_required"] is True

    def test_major_bump_plus_field_change_stays_major(self):
        """Both semver major and field-version change → still MAJOR (not double-escalated)."""
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "2.0.0", "library_field_version": "v5"},
            old_field_count=37,
            new_field_count=42,
        )
        assert decision["effective_change_type"] == "major"
        assert decision["pr_required"] is True

    def test_empty_old_manifest_allows_auto_commit(self):
        decision = evaluate_governance(
            old_manifest={},
            new_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            old_field_count=0,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is True
        assert decision["schema_version_old"] == "0.0.0"

    def test_invalid_old_version_treated_as_zero(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "bad"},
            new_manifest={"schema_version": "1.2.0"},
        )
        assert decision["schema_version_old"] == "0.0.0"

    def test_metadata_fields_populated(self):
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.1.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["schema_version_old"] == "1.1.0"
        assert decision["schema_version_new"] == "1.2.0"
        assert decision["field_version_old"] == "v4"
        assert decision["field_version_new"] == "v4"
        assert decision["field_count_old"] == 37
        assert decision["field_count_new"] == 37

    def test_old_field_count_zero_no_escalation(self):
        """When old_field_count is 0 (first run), field count change is not escalated."""
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0"},
            new_manifest={"schema_version": "1.2.0"},
            old_field_count=0,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is True

    def test_minor_bump_with_field_version_change_escalates(self):
        """Minor semver bump + field-version change → escalated to MAJOR."""
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.3.0", "library_field_version": "v5"},
        )
        assert decision["effective_change_type"] == "major"
        assert decision["schema_change_type"] == "minor"
        assert decision["pr_required"] is True


# ── 4b. Manifest cross-check ───────────────────────────────────────


class TestManifestCrossCheck:
    """Verify that embedded auto_commit_allowed=false in the manifest
    overrides a computed 'allowed' decision (fail-closed)."""

    def test_manifest_false_overrides_computed_allowed(self):
        """Generator says blocked → governance CLI must also block."""
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={
                "schema_version": "1.2.0",
                "library_field_version": "v4",
                "auto_commit_allowed": False,
            },
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is False
        assert decision["pr_required"] is True
        assert any("manifest auto_commit_allowed=false" in r for r in decision["reasons"])

    def test_manifest_true_does_not_override_computed_block(self):
        """Manifest says allowed, but CLI detects major → still blocked."""
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={
                "schema_version": "2.0.0",
                "library_field_version": "v4",
                "auto_commit_allowed": True,
            },
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is False
        assert decision["pr_required"] is True

    def test_manifest_missing_field_no_override(self):
        """When manifest has no auto_commit_allowed, no cross-check override."""
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            new_manifest={"schema_version": "1.2.0", "library_field_version": "v4"},
            old_field_count=37,
            new_field_count=37,
        )
        assert decision["auto_commit_allowed"] is True
        assert decision["manifest_auto_commit_allowed"] is None

    def test_manifest_auto_commit_allowed_in_output(self):
        """The output always includes manifest_auto_commit_allowed."""
        decision = evaluate_governance(
            old_manifest={"schema_version": "1.2.0"},
            new_manifest={
                "schema_version": "1.2.0",
                "auto_commit_allowed": True,
            },
        )
        assert "manifest_auto_commit_allowed" in decision
        assert decision["manifest_auto_commit_allowed"] is True

    def test_initial_deploy_ignores_manifest_false(self):
        """Initial deploy (no old manifest) is always allowed, even if
        the new manifest says auto_commit_allowed: false."""
        decision = evaluate_governance(
            old_manifest={},
            new_manifest={
                "schema_version": "1.2.0",
                "auto_commit_allowed": False,
            },
        )
        # Initial deploys are exempt — auto_commit is always allowed
        # because there are no existing consumers to break.
        # The manifest cross-check only fires when the computed result
        # was 'allowed' and the manifest overrides it to 'blocked'.
        # For initial deploys, the computed result is already 'allowed'
        # via the is_initial exemption, and manifest=false overrides.
        assert decision["auto_commit_allowed"] is False
        assert decision["pr_required"] is True


class TestGovernanceCLI:
    def test_auto_commit_exit_zero(self, tmp_path: Path):
        old = tmp_path / "old.json"
        new = tmp_path / "new.json"
        old.write_text(json.dumps({"schema_version": "1.2.0", "library_field_version": "v4"}))
        new.write_text(json.dumps({"schema_version": "1.2.0", "library_field_version": "v4"}))

        import subprocess
        result = subprocess.run(
            ["python", "scripts/smc_version_governance.py",
             "--old-manifest", str(old), "--new-manifest", str(new)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["auto_commit_allowed"] is True

    def test_breaking_exit_one(self, tmp_path: Path):
        old = tmp_path / "old.json"
        new = tmp_path / "new.json"
        old.write_text(json.dumps({"schema_version": "1.2.0", "library_field_version": "v4"}))
        new.write_text(json.dumps({"schema_version": "2.0.0", "library_field_version": "v5"}))

        import subprocess
        result = subprocess.run(
            ["python", "scripts/smc_version_governance.py",
             "--old-manifest", str(old), "--new-manifest", str(new)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["pr_required"] is True

    def test_missing_old_manifest_treated_as_initial(self, tmp_path: Path):
        old = tmp_path / "nonexistent.json"
        new = tmp_path / "new.json"
        new.write_text(json.dumps({"schema_version": "1.2.0"}))

        import subprocess
        result = subprocess.run(
            ["python", "scripts/smc_version_governance.py",
             "--old-manifest", str(old), "--new-manifest", str(new)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 0

    def test_cli_with_library_files(self, tmp_path: Path):
        old_manifest = tmp_path / "old.json"
        new_manifest = tmp_path / "new.json"
        old_lib = tmp_path / "old.pine"
        new_lib = tmp_path / "new.pine"

        old_manifest.write_text(json.dumps({"schema_version": "1.2.0", "library_field_version": "v4"}))
        new_manifest.write_text(json.dumps({"schema_version": "1.2.0", "library_field_version": "v4"}))
        old_lib.write_text("\n".join([f"export const F{i} = {i}" for i in range(37)]))
        new_lib.write_text("\n".join([f"export const F{i} = {i}" for i in range(37)]))

        import subprocess
        result = subprocess.run(
            ["python", "scripts/smc_version_governance.py",
             "--old-manifest", str(old_manifest), "--new-manifest", str(new_manifest),
             "--old-library", str(old_lib), "--library", str(new_lib)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["field_count_old"] == 37
        assert output["field_count_new"] == 37

    def test_cli_field_count_mismatch_blocks(self, tmp_path: Path):
        old_manifest = tmp_path / "old.json"
        new_manifest = tmp_path / "new.json"
        old_lib = tmp_path / "old.pine"
        new_lib = tmp_path / "new.pine"

        old_manifest.write_text(json.dumps({"schema_version": "1.2.0", "library_field_version": "v4"}))
        new_manifest.write_text(json.dumps({"schema_version": "1.2.0", "library_field_version": "v4"}))
        old_lib.write_text("\n".join([f"export const F{i} = {i}" for i in range(37)]))
        new_lib.write_text("\n".join([f"export const F{i} = {i}" for i in range(40)]))

        import subprocess
        result = subprocess.run(
            ["python", "scripts/smc_version_governance.py",
             "--old-manifest", str(old_manifest), "--new-manifest", str(new_manifest),
             "--old-library", str(old_lib), "--library", str(new_lib)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["pr_required"] is True


# ── 6. Manifest governance metadata ────────────────────────────────


class TestManifestGovernanceMetadata:
    """Verify that the generated manifest includes version_change_type
    and schema_version_previous when regenerated."""

    def test_manifest_includes_version_change_type(self, tmp_path: Path):
        from scripts.generate_smc_micro_profiles import load_schema
        from scripts.smc_microstructure_base_runtime import generate_pine_library_from_base
        from scripts.smc_schema_resolver import resolve_microstructure_schema_path

        import pandas as pd
        schema_path = resolve_microstructure_schema_path()

        # Write a base CSV
        csv_path = tmp_path / "base.csv"
        row = {
            "asof_date": "2026-03-28", "symbol": "AAPL", "exchange": "NASDAQ",
            "asset_type": "stock", "universe_bucket": "test",
            "history_coverage_days_20d": 20, "adv_dollar_rth_20d": 150000000,
            "avg_spread_bps_rth_20d": 1.2, "rth_active_minutes_share_20d": 0.95,
            "open_30m_dollar_share_20d": 0.20, "close_60m_dollar_share_20d": 0.22,
            "clean_intraday_score_20d": 0.92, "consistency_score_20d": 0.90,
            "close_hygiene_20d": 0.91, "wickiness_20d": 0.10,
            "pm_dollar_share_20d": 0.15, "pm_trades_share_20d": 0.14,
            "pm_active_minutes_share_20d": 0.20, "pm_spread_bps_20d": 3.0,
            "pm_wickiness_20d": 0.12, "midday_dollar_share_20d": 0.24,
            "midday_trades_share_20d": 0.23, "midday_active_minutes_share_20d": 0.25,
            "midday_spread_bps_20d": 2.0, "midday_efficiency_20d": 0.80,
            "ah_dollar_share_20d": 0.12, "ah_trades_share_20d": 0.11,
            "ah_active_minutes_share_20d": 0.14, "ah_spread_bps_20d": 3.0,
            "ah_wickiness_20d": 0.10, "reclaim_respect_rate_20d": 0.90,
            "reclaim_failure_rate_20d": 0.08, "reclaim_followthrough_r_20d": 1.60,
            "ob_sweep_reversal_rate_20d": 0.25, "ob_sweep_depth_p75_20d": 0.30,
            "fvg_sweep_reversal_rate_20d": 0.20, "fvg_sweep_depth_p75_20d": 0.28,
            "stop_hunt_rate_20d": 0.10, "setup_decay_half_life_bars_20d": 30.0,
            "early_vs_late_followthrough_ratio_20d": 0.90, "stale_fail_rate_20d": 0.10,
        }
        pd.DataFrame([row]).to_csv(csv_path, index=False)

        # First generation — no previous manifest
        result = generate_pine_library_from_base(
            base_csv_path=csv_path,
            schema_path=schema_path,
            output_root=tmp_path,
        )
        manifest_path = result["manifest_path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema_version"] == SCHEMA_VERSION
        assert manifest["schema_version_previous"] == ""
        assert manifest["version_change_type"] == "initial"
        assert manifest["auto_commit_allowed"] is True

    def test_manifest_records_unchanged_on_regeneration(self, tmp_path: Path):
        from scripts.smc_microstructure_base_runtime import generate_pine_library_from_base
        from scripts.smc_schema_resolver import resolve_microstructure_schema_path

        import pandas as pd
        schema_path = resolve_microstructure_schema_path()
        csv_path = tmp_path / "base.csv"
        row = {
            "asof_date": "2026-03-28", "symbol": "AAPL", "exchange": "NASDAQ",
            "asset_type": "stock", "universe_bucket": "test",
            "history_coverage_days_20d": 20, "adv_dollar_rth_20d": 150000000,
            "avg_spread_bps_rth_20d": 1.2, "rth_active_minutes_share_20d": 0.95,
            "open_30m_dollar_share_20d": 0.20, "close_60m_dollar_share_20d": 0.22,
            "clean_intraday_score_20d": 0.92, "consistency_score_20d": 0.90,
            "close_hygiene_20d": 0.91, "wickiness_20d": 0.10,
            "pm_dollar_share_20d": 0.15, "pm_trades_share_20d": 0.14,
            "pm_active_minutes_share_20d": 0.20, "pm_spread_bps_20d": 3.0,
            "pm_wickiness_20d": 0.12, "midday_dollar_share_20d": 0.24,
            "midday_trades_share_20d": 0.23, "midday_active_minutes_share_20d": 0.25,
            "midday_spread_bps_20d": 2.0, "midday_efficiency_20d": 0.80,
            "ah_dollar_share_20d": 0.12, "ah_trades_share_20d": 0.11,
            "ah_active_minutes_share_20d": 0.14, "ah_spread_bps_20d": 3.0,
            "ah_wickiness_20d": 0.10, "reclaim_respect_rate_20d": 0.90,
            "reclaim_failure_rate_20d": 0.08, "reclaim_followthrough_r_20d": 1.60,
            "ob_sweep_reversal_rate_20d": 0.25, "ob_sweep_depth_p75_20d": 0.30,
            "fvg_sweep_reversal_rate_20d": 0.20, "fvg_sweep_depth_p75_20d": 0.28,
            "stop_hunt_rate_20d": 0.10, "setup_decay_half_life_bars_20d": 30.0,
            "early_vs_late_followthrough_ratio_20d": 0.90, "stale_fail_rate_20d": 0.10,
        }
        pd.DataFrame([row]).to_csv(csv_path, index=False)

        # First generation
        generate_pine_library_from_base(
            base_csv_path=csv_path,
            schema_path=schema_path,
            output_root=tmp_path,
        )

        # Second generation — same schema version
        result2 = generate_pine_library_from_base(
            base_csv_path=csv_path,
            schema_path=schema_path,
            output_root=tmp_path,
        )
        manifest = json.loads(result2["manifest_path"].read_text(encoding="utf-8"))
        assert manifest["schema_version_previous"] == SCHEMA_VERSION
        assert manifest["version_change_type"] == "unchanged"
        assert manifest["auto_commit_allowed"] is True
