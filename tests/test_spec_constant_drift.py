"""Discipline: hardcoded constants that originate from a spec file must not drift.

W10-2 root-cause: ``run_ab_comparison.py`` had ``SPRT_P0=0.55, SPRT_P1=0.60``
hardcoded, while the registered F2 spec already specified ``p0=0.544, p1=0.574``.
The divergence was +6pp / +26pp — large enough to silently change the test's MDE
from 30pp (spec) to 50pp (fallback), reducing statistical power with no warning.

This file guards against that class of defect by cross-referencing every numeric
constant in a script that claims to implement a spec against the actual spec file.

Design notes
------------
- The spec JSON under ``artifacts/experiments/`` is the single source of truth.
- Script-level constants are permitted to *diverge intentionally* (they serve as
  wider, multi-family fallbacks), but the divergence must be documented in the
  constant's own comment, and the magnitude of drift must not silently grow.
  Tests here assert that divergence is bounded and expected, not zero.
- A new experiment spec must add a corresponding section here.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
F2_SPEC_PATH = REPO_ROOT / "artifacts" / "experiments" / "f2_contextual_promotion.json"


# ---------------------------------------------------------------------------
# Guard A — F2 spec SPRT constants vs run_ab_comparison fallbacks
#
# The script carries intentional fallbacks (SPRT_P0=0.55 / SPRT_P1=0.60) that
# are wider than the spec (0.544/0.574).  The rationale is documented in the
# comment block at lines ~608-617 of run_ab_comparison.py.
#
# These tests ensure:
#  1. The fallbacks are still the *intended* values (no accidental edit).
#  2. The fallback drift is bounded (the script comment warns about it).
#  3. The spec itself has not silently changed to match the fallbacks
#     (which would make the tests vacuously pass while hiding the real problem).
# ---------------------------------------------------------------------------


class TestF2SPRTConstantDrift:
    """Cross-reference F2 spec SPRT values against run_ab_comparison fallbacks."""

    @pytest.fixture(scope="class")
    def f2_spec_sprt(self) -> dict:
        import json

        with F2_SPEC_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data["sprt"]

    def test_spec_p0_has_not_changed(self, f2_spec_sprt: dict) -> None:
        """Spec p0 must remain at 0.544 (2026-06-09 dual-arm baseline measurement).
        If this fails, update the constant AND the rationale, then bump this pin.
        """
        assert f2_spec_sprt["p0"] == pytest.approx(0.544, abs=1e-6), (
            f"F2 spec p0 changed to {f2_spec_sprt['p0']}. "
            "If deliberate, also update SPRT_P0 in run_ab_comparison.py and "
            "the rationale comment in the spec JSON."
        )

    def test_spec_p1_has_not_changed(self, f2_spec_sprt: dict) -> None:
        """Spec p1 must remain at 0.574 (+3pp MDE over 0.544 baseline).
        If this fails, update the constant AND the rationale, then bump this pin.
        """
        assert f2_spec_sprt["p1"] == pytest.approx(0.574, abs=1e-6), (
            f"F2 spec p1 changed to {f2_spec_sprt['p1']}. "
            "If deliberate, also update SPRT_P1 in run_ab_comparison.py and "
            "the rationale comment in the spec JSON."
        )

    def test_fallback_p0_is_intended_value(self) -> None:
        """SPRT_P0 must be the documented fallback 0.55 (G3 lifetime-corpus median)."""
        from scripts.run_ab_comparison import SPRT_P0

        assert pytest.approx(0.55, abs=1e-9) == SPRT_P0, (
            f"SPRT_P0 changed from documented value 0.55 to {SPRT_P0}. "
            "Accidental edit? Update this pin if the change is intentional."
        )

    def test_fallback_p1_is_intended_value(self) -> None:
        """SPRT_P1 must be the documented fallback 0.60 (G3 +5pp MDE)."""
        from scripts.run_ab_comparison import SPRT_P1

        assert pytest.approx(0.60, abs=1e-9) == SPRT_P1, (
            f"SPRT_P1 changed from documented value 0.60 to {SPRT_P1}. "
            "Accidental edit? Update this pin if the change is intentional."
        )

    def test_fallback_drift_from_spec_is_bounded(self, f2_spec_sprt: dict) -> None:
        """The divergence between fallback and spec must stay within documented bounds.

        The W10-2 comment documents +6pp / +26pp drift.  We allow up to ±2pp on
        p0 and ±5pp on p1 before requiring an explicit re-review.  Exceeding
        these thresholds means the fallback has moved far from the spec without a
        matching rationale update.
        """
        from scripts.run_ab_comparison import SPRT_P0, SPRT_P1

        drift_p0 = abs(SPRT_P0 - f2_spec_sprt["p0"])
        drift_p1 = abs(SPRT_P1 - f2_spec_sprt["p1"])

        assert drift_p0 <= 0.020, (
            f"SPRT_P0 fallback drifted {drift_p0*100:.1f}pp from spec p0 "
            f"({f2_spec_sprt['p0']}). Exceeds ±2pp review threshold. "
            "Update fallback or spec, then revise this bound."
        )
        assert drift_p1 <= 0.050, (
            f"SPRT_P1 fallback drifted {drift_p1*100:.1f}pp from spec p1 "
            f"({f2_spec_sprt['p1']}). Exceeds ±5pp review threshold. "
            "Update fallback or spec, then revise this bound."
        )

    def test_fallbacks_diverge_from_spec(self, f2_spec_sprt: dict) -> None:
        """Sanity check: fallbacks must NOT accidentally match the spec exactly.

        If they did, the drift tests above would be vacuously green and this
        cross-referencing layer would lose its ability to detect future spec
        changes that are NOT mirrored in the script.
        """
        from scripts.run_ab_comparison import SPRT_P0, SPRT_P1

        assert pytest.approx(f2_spec_sprt["p0"], abs=1e-6) != SPRT_P0, (
            "SPRT_P0 now matches the spec exactly. That is unexpected for a "
            "fallback constant. If intentional, remove or update this sanity check."
        )
        assert pytest.approx(f2_spec_sprt["p1"], abs=1e-6) != SPRT_P1, (
            "SPRT_P1 now matches the spec exactly. Unexpected for a fallback. "
            "If intentional, remove or update this sanity check."
        )


# ---------------------------------------------------------------------------
# Guard B — F2 spec max_n must be pinned (changes imply power re-analysis)
# ---------------------------------------------------------------------------


class TestF2SPRTMaxNPin:
    """max_n is a power-analysis output; silent changes invalidate the study plan."""

    def test_spec_max_n_pinned(self) -> None:
        import json

        with F2_SPEC_PATH.open(encoding="utf-8") as fh:
            sprt = json.load(fh)["sprt"]

        assert sprt["max_n"] == 1200, (
            f"F2 spec max_n changed to {sprt['max_n']} (expected 1200). "
            "This is a power-analysis input — update the ADR and re-run the "
            "power simulation before changing this pin."
        )


# ---------------------------------------------------------------------------
# Guard C — every spec file in artifacts/experiments/ is loadable and valid
# ---------------------------------------------------------------------------


class TestAllSpecFilesLoadable:
    """Spec files must remain parseable and contain the required top-level keys."""

    REQUIRED_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "name", "sprt", "rollback_gate"}
    )

    def _spec_paths(self) -> list[Path]:
        experiments_dir = REPO_ROOT / "artifacts" / "experiments"
        return list(experiments_dir.glob("*.json"))

    def test_at_least_one_spec_exists(self) -> None:
        assert self._spec_paths(), (
            "No *.json spec files found in artifacts/experiments/. "
            "Expected at least f2_contextual_promotion.json."
        )

    @pytest.mark.parametrize("spec_path", list((REPO_ROOT / "artifacts" / "experiments").glob("*.json")))
    def test_spec_contains_required_keys(self, spec_path: Path) -> None:
        import json

        with spec_path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        missing = self.REQUIRED_KEYS - set(data.keys())
        assert not missing, (
            f"{spec_path.name} is missing required keys: {missing}. "
            "Add the keys or update REQUIRED_KEYS in this test."
        )
