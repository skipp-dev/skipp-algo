"""Pine-boundary pin for ``HR_SENTINEL_DEGRADED`` (F-3).

Part of the Boundary-Contract Improvement Plan 2026-04-23 (PR-BC-02).

Guarantees that the generated Pine library ships the
``HR_SENTINEL_DEGRADED`` constant so TradingView consumers can write
``mp.ZONE_HR_FVG == mp.HR_SENTINEL_DEGRADED`` instead of hardcoding
``-1.0``. A generator refactor that drops the sentinel export would
silently break the symbolic comparison — this test trips CI instead.

If this test fails:

1. Confirm ``scripts/generate_smc_micro_profiles.py`` still emits
   ``export const float HR_SENTINEL_DEGRADED = …`` inside the
   ``// ── Pine Consumer Maturity (Phase H) ──`` block.
2. Regenerate the seed fixture:
   ``python -m scripts.refresh_generated_artifacts`` and commit the
   updated ``tests/fixtures/generated_seed/pine/generated/*``.
3. Verify ``library_field_version`` stays at ``v5.5c`` or a later tag;
   never revert to ``v5.5b``.
"""
from __future__ import annotations

from pathlib import Path

from scripts.smc_zone_priority_consumer import HR_SENTINEL_DEGRADED

REPO_ROOT = Path(__file__).resolve().parents[1]
PINE_LIB = REPO_ROOT / "pine" / "generated" / "smc_micro_profiles_generated.pine"
SEED_LIB = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "generated_seed"
    / "pine"
    / "generated"
    / "smc_micro_profiles_generated.pine"
)


def test_hr_sentinel_exported_to_pine_library() -> None:
    """Canonical Pine library must expose HR_SENTINEL_DEGRADED as an export."""
    text = PINE_LIB.read_text(encoding="utf-8")
    assert "export const float HR_SENTINEL_DEGRADED" in text, (
        "Pine library is missing the HR_SENTINEL_DEGRADED constant. "
        "Pine consumers rely on `mp.HR_SENTINEL_DEGRADED` to detect "
        "degraded per-family HR exports without hardcoding -1.0."
    )


def test_hr_sentinel_numeric_value_is_minus_one() -> None:
    """Exported Pine value must match the Python constant to 4 decimals."""
    text = PINE_LIB.read_text(encoding="utf-8")
    expected = f"export const float HR_SENTINEL_DEGRADED = {HR_SENTINEL_DEGRADED:.4f}"
    assert expected in text, (
        f"Pine-exported HR_SENTINEL_DEGRADED must equal {HR_SENTINEL_DEGRADED:.4f} "
        f"(Python: HR_SENTINEL_DEGRADED = {HR_SENTINEL_DEGRADED})."
    )


def test_hr_sentinel_exported_in_seed_fixture() -> None:
    """Seed-reference fixture tracks the same sentinel export.

    Regenerated via ``python -m scripts.refresh_generated_artifacts``;
    guards against generator changes that would leave the fixture stale.
    """
    text = SEED_LIB.read_text(encoding="utf-8")
    expected = f"export const float HR_SENTINEL_DEGRADED = {HR_SENTINEL_DEGRADED:.4f}"
    assert expected in text, (
        "Seed-reference Pine library missing HR_SENTINEL_DEGRADED export. "
        "Run `python -m scripts.refresh_generated_artifacts` and commit "
        "the regenerated fixture."
    )


def test_hr_sentinel_python_contract_invariant() -> None:
    """Sentinel must remain a negative magic number outside the [0, 1] HR range."""
    assert HR_SENTINEL_DEGRADED == -1.0
    assert HR_SENTINEL_DEGRADED < 0.0
