"""Anti-drift test: checked-in generated artifacts must match generator output.

Regenerates all three Pine artifacts into a temp directory using the same
seed fixture and compares them against the checked-in versions under
``pine/generated/``.

* Pine and snippet files are compared byte-for-byte.
* The manifest is compared structurally (path fields are excluded since
  they contain machine-dependent absolute paths when output_root differs
  from the repo root).

If this test fails, run::

    python -m scripts.refresh_generated_artifacts

then commit the updated artifacts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.refresh_generated_artifacts import GENERATED_DIR, refresh

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files compared byte-for-byte
EXACT_ARTIFACTS = [
    "smc_micro_profiles_generated.pine",
    "smc_micro_profiles_core_import_snippet.pine",
]

# Manifest keys that contain machine-dependent paths — skip in comparison
_PATH_KEYS = {
    "input_path", "schema_path", "features_csv", "lists_csv",
    "state_csv", "diff_report_md", "pine_library", "core_import_snippet",
    # Governance fields depend on whether a prior manifest exists at the
    # target path.  When regenerating to a temp directory no prior exists,
    # so schema_version_previous / version_change_type / auto_commit_allowed
    # will differ from the checked-in manifest.
    "schema_version_previous", "version_change_type", "auto_commit_allowed",
}

_EXPORT_RE = re.compile(r"^export const \w+ ([A-Z][A-Z0-9_]+)\b", re.MULTILINE)

EVENT_RISK_EXPORTS = (
    "EVENT_WINDOW_STATE",
    "EVENT_RISK_LEVEL",
    "NEXT_EVENT_CLASS",
    "NEXT_EVENT_NAME",
    "NEXT_EVENT_TIME",
    "NEXT_EVENT_IMPACT",
    "EVENT_RESTRICT_BEFORE_MIN",
    "EVENT_RESTRICT_AFTER_MIN",
    "EVENT_COOLDOWN_ACTIVE",
    "MARKET_EVENT_BLOCKED",
    "SYMBOL_EVENT_BLOCKED",
    "EARNINGS_SOON_TICKERS",
    "HIGH_RISK_EVENT_TICKERS",
    "EVENT_PROVIDER_STATUS",
)

DEDICATED_V55B_LEAN_EXPORTS = (
    "SESSION_VOLATILITY_STATE",
    "PRIMARY_OB_SIDE",
    "PRIMARY_OB_DISTANCE",
    "OB_FRESH",
    "OB_AGE_BARS",
    "OB_MITIGATION_STATE",
    "PRIMARY_FVG_SIDE",
    "PRIMARY_FVG_DISTANCE",
    "FVG_FILL_PCT",
    "FVG_MATURITY_LEVEL",
    "FVG_FRESH",
    "FVG_INVALIDATED",
    "STRUCTURE_TREND_STRENGTH",
    "SIGNAL_QUALITY_SCORE",
    "SIGNAL_QUALITY_TIER",
    "SIGNAL_WARNINGS",
    "SIGNAL_BIAS_ALIGNMENT",
    "SIGNAL_FRESHNESS",
)

LEAN_ALIAS_PREFIXES = (
    "EVENT_RISK_LIGHT_",
    "SESSION_CONTEXT_LIGHT_",
    "STRUCTURE_STATE_LIGHT_",
    "ERL_",
    "SCL_",
    "STRL_",
)


def _extract_export_names(text: str) -> tuple[str, ...]:
    return tuple(_EXPORT_RE.findall(text))


def _export_block(export_names: tuple[str, ...], start_name: str, expected: tuple[str, ...]) -> tuple[str, ...]:
    start = export_names.index(start_name)
    return export_names[start : start + len(expected)]


class TestGeneratedArtifactDrift:
    """Fail if checked-in artifacts diverge from generator output."""

    @pytest.fixture(scope="class")
    def regenerated(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        """Regenerate artifacts into a temp directory once per class."""
        tmp = Path(tmp_path_factory.mktemp("regen"))
        refresh(output_root=tmp)
        return tmp

    @pytest.mark.parametrize("artifact", EXACT_ARTIFACTS)
    def test_artifact_matches(self, regenerated: Path, artifact: str):
        checked_in = GENERATED_DIR / artifact
        fresh = regenerated / "pine" / "generated" / artifact

        assert checked_in.exists(), (
            f"Checked-in artifact missing: {checked_in.relative_to(REPO_ROOT)}"
        )
        assert fresh.exists(), (
            f"Generator did not produce: {artifact}"
        )

        checked_in_text = checked_in.read_text(encoding="utf-8")
        fresh_text = fresh.read_text(encoding="utf-8")

        if checked_in_text != fresh_text:
            # Build a helpful diff summary (first 10 differing lines)
            old_lines = checked_in_text.splitlines()
            new_lines = fresh_text.splitlines()
            diffs: list[str] = []
            for i, (o, n) in enumerate(zip(old_lines, new_lines), 1):
                if o != n:
                    diffs.append(f"  L{i}:  checked-in: {o!r}")
                    diffs.append(f"  L{i}:  generator:  {n!r}")
                if len(diffs) >= 20:
                    break
            if len(old_lines) != len(new_lines):
                diffs.append(
                    f"  Line count: checked-in={len(old_lines)}, generator={len(new_lines)}"
                )
            diff_report = "\n".join(diffs)
            pytest.fail(
                f"Checked-in {artifact} is stale — run:\n\n"
                f"    python -m scripts.refresh_generated_artifacts\n\n"
                f"First differences:\n{diff_report}"
            )

    def test_manifest_structure_matches(self, regenerated: Path):
        """Compare manifest structurally, excluding machine-dependent path fields."""
        checked_in = json.loads(
            (GENERATED_DIR / "smc_micro_profiles_generated.json").read_text()
        )
        fresh = json.loads(
            (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.json").read_text()
        )
        checked_filtered = {k: v for k, v in checked_in.items() if k not in _PATH_KEYS}
        fresh_filtered = {k: v for k, v in fresh.items() if k not in _PATH_KEYS}
        assert checked_filtered == fresh_filtered, (
            "Checked-in manifest is stale — run:\n\n"
            "    python -m scripts.refresh_generated_artifacts\n\n"
            f"Differences (excluding path fields):\n"
            f"  checked-in keys: {sorted(checked_filtered.keys())}\n"
            f"  generator  keys: {sorted(fresh_filtered.keys())}"
        )

    def test_v5_field_count(self, regenerated: Path):
        """Sanity check: the Pine library contains the expected v5.5 field count."""
        pine = (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.pine").read_text()
        exports = [l for l in pine.splitlines() if l.startswith("export const")]
        # Shared lean families reuse canonical exports instead of duplicating
        # Event Risk / Session Context / Structure State fields.
        assert len(exports) == 274, (
            f"Expected 274 export const fields for the current v5.5b shared-export contract, got {len(exports)}"
        )

    def test_event_risk_exports_stay_in_canonical_order(self, regenerated: Path):
        pine = (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.pine").read_text()
        export_names = _extract_export_names(pine)
        assert _export_block(export_names, "EVENT_WINDOW_STATE", EVENT_RISK_EXPORTS) == EVENT_RISK_EXPORTS

    def test_dedicated_v55b_lean_exports_stay_in_canonical_order(self, regenerated: Path):
        pine = (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.pine").read_text()
        export_names = _extract_export_names(pine)
        assert _export_block(export_names, "SESSION_VOLATILITY_STATE", DEDICATED_V55B_LEAN_EXPORTS) == DEDICATED_V55B_LEAN_EXPORTS

    def test_shared_lean_families_do_not_reintroduce_alias_exports(self, regenerated: Path):
        pine = (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.pine").read_text()
        export_names = _extract_export_names(pine)
        for prefix in LEAN_ALIAS_PREFIXES:
            assert not any(name.startswith(prefix) for name in export_names), (
                f"Shared lean family alias export reintroduced: {prefix}*"
            )

    def test_manifest_has_v5_meta_keys(self, regenerated: Path):
        """Manifest must contain the v5 top-level meta fields."""
        import json

        manifest = json.loads(
            (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.json").read_text()
        )
        assert "library_field_version" in manifest
        assert manifest["library_field_version"] == "v5.5b"
        assert "asof_time" in manifest
        assert "refresh_count" in manifest
        assert "enrichment_blocks" in manifest

    def test_manifest_has_governance_fields(self, regenerated: Path):
        """Manifest must include governance metadata from the version policy."""
        manifest = json.loads(
            (regenerated / "pine" / "generated" / "smc_micro_profiles_generated.json").read_text()
        )
        for key in ("schema_version", "schema_version_previous",
                     "version_change_type", "auto_commit_allowed"):
            assert key in manifest, f"Manifest missing governance field: {key}"
