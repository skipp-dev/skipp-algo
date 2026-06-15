"""Anti-drift test: checked-in seed-reference artifacts must match generator output.

Regenerates all three Pine artifacts into a temp directory using the same
seed fixture and compares them against the checked-in seed-reference versions
under ``tests/fixtures/generated_seed/pine/generated/``.

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
    "NEXT_EVENT_NAME",
    "NEXT_EVENT_TIME",
    "NEXT_EVENT_IMPACT",
    "EVENT_RESTRICT_BEFORE_MIN",
    "EVENT_RESTRICT_AFTER_MIN",
    "EVENT_COOLDOWN_ACTIVE",
    "MARKET_EVENT_BLOCKED",
    "SYMBOL_EVENT_BLOCKED",
    "EARNINGS_SOON_TICKERS",
    "EVENT_PROVIDER_STATUS",
    "HIGH_RISK_EVENT_TICKERS",
    "NEXT_EVENT_CLASS",
)

DEDICATED_V55B_LEAN_EXPORTS = (
    "SESSION_VOLATILITY_STATE",
    "PRIMARY_OB_SIDE",
    "PRIMARY_OB_DISTANCE",
    "OB_FRESH",
    "OB_AGE_BARS",
    "OB_MITIGATION_STATE",
    # FVG Lifecycle Light
    "PRIMARY_FVG_SIDE",
    "PRIMARY_FVG_DISTANCE",
    "FVG_FILL_PCT",
    "FVG_MATURITY_LEVEL",
    "FVG_FRESH",
    "FVG_INVALIDATED",
    "FVG_NET_IMBALANCE",
    # Imbalance Lifecycle Extended (WP-OH9)
    "BPR_DIRECTION",
    # Liquidity Pools (WP-OH9)
    "BUY_SIDE_POOL_LEVEL",
    "BUY_SIDE_POOL_STRENGTH",
    # Liquidity Sweeps Extended (WP-OH9)
    "LIQUIDITY_TAKEN_DIRECTION",
    # Structure State Light
    "STRUCTURE_LAST_EVENT",
    "STRUCTURE_EVENT_AGE_BARS",
    "STRUCTURE_FRESH",
    "STRUCTURE_TREND_STRENGTH",
    # Signal Quality
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
            for i, (o, n) in enumerate(zip(old_lines, new_lines, strict=False), 1):
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
        exports = [ln for ln in pine.splitlines() if ln.startswith("export const")]
        # Shared lean families reuse canonical exports instead of duplicating
        # Event Risk / Session Context / Structure State fields.
        # v6 adds 20 new fields: Short Interest(4), Treasury(4), Sector Rotation(4),
        # Institutional(3), Analyst(3), Insider(2).
        # v6.1 adds FVG_NET_IMBALANCE.
        # WP-OH9 re-exports 15 Pine-consumed fields: OB extended(9), BPR_DIRECTION,
        # BUY_SIDE_POOL_LEVEL/STRENGTH, HIGH_RISK_EVENT_TICKERS, NEXT_EVENT_CLASS,
        # LIQUIDITY_TAKEN_DIRECTION.
        # WP-PINE2 adds UNIVERSE_TICKERS.
        # WP-8: removed 42 deprecated fields from generator output (Range Regime 11,
        # Range Profile Regime 22, Order Block Extended 9). 177 → 135.
        # C9: Zone Priority adds 5 fields (RANK, SCORE, TOP_FAMILY, CATALYST, REASON). 135 → 140.
        # Calibration consumer adds 4 fields (ZONE_CAL_OB/FVG/BOS/SWEEP). 140 → 144.
        # Phase F: Contextual calibration adds 20 fields:
        # - 4 families × 3 sessions (ASIA/LONDON/NY_AM, Q3 F1 wiring 2026-04-22) = 12
        # - 4 families × 2 vol regimes (NORMAL/HIGH_VOL) = 8
        # 144 → 164.
        # Hero State Contract adds 7 fields. 164 → 171.
        # ENG-WS2-02 trust block adds 6 fields (TRUST_STATE, TRUST_ACTION_IMPACT,
        # TRUST_CAUSE_DOMAIN, TRUST_CAUSE_FAILURE_TYPE, TRUST_CAUSE_CODE,
        # TRUST_DEGRADATION_REASON). 171 → 177.
        # ENG-WS2-04 action degradation adds 3 fields (ACTION_DEGRADATION_TIER,
        # ACTION_DEGRADATION_REASON, ACTION_DEGRADATION_DERIVED_FROM). 177 → 180.
        # ENG-WS3-03 hero market mode adds 5 fields (HERO_MARKET_REGIME, _BIAS,
        # _SESSION, _TRUST, _FRESHNESS). 180 → 185.
        # ENG-WS3-04 hero setup quality adds 4 fields (HERO_QUALITY_TIER,
        # HERO_QUALITY_WHY_NOW, HERO_QUALITY_MAIN_RISK, HERO_QUALITY_FAMILY_HEALTH).
        # 185 → 189.
        # ENG-WS3-05 originally added 5 reserved action fields
        # (HERO_ACTION_VERB, HERO_ACTION_VERB_DE, HERO_ACTION_REASON,
        # HERO_ACTION_DEGRADATION, HERO_ACTION_QUALITY). 189 → 194.
        # Pre-existing drift between the asserted count (194) and the
        # checked-in fixture (200) is realigned here together with the
        # ZONE_CAL_TRUST scalar (ADR 2026-04-22 — degrade per-family HR
        # display on sub-saturation corpora). Net add of this commit: +1.
        # 200 → 201.
        # F-3 (Boundary-Contract Plan 2026-04-23, PR-BC-02): +1 additive
        # Pine-library const `HR_SENTINEL_DEGRADED` so consumers can
        # reference the sentinel by symbol instead of hardcoding -1.0.
        # 201 → 202.
        # F-6 consolidates HERO_ACTION/HERO_ACTION_VERB and removes the
        # 5 reserved action exports again while keeping the single
        # existing HERO_ACTION export:
        # 202 → 197.
        assert len(exports) == 197, (
            f"Expected 197 export const fields for the current v8 shared-export contract, got {len(exports)}"
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
        assert manifest["library_field_version"] == "v8.0a"
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
