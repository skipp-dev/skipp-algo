"""Regression pins for the sweep_trap.py docstring/comment truth-fixes.

A truth-audit found several names/comments in ``smc_core/sweep_trap.py``
promising more than the code does:

- ``sweep_body`` / "sweep body" / "zero-body candle" actually meant the wick
  *penetration* past the level, not the candle's open→close body.
- the ``fib_retrace_depth`` inline comment claimed price "retraced" post-sweep,
  though no post-sweep bar is consulted.
- ``trap_quality_score`` was described as a "leading indicator" of follow-through
  without any empirical calibration.
- the wrapper comment said a structure reversal made the trap "no longer active",
  though it only subtracts a confidence penalty.

These assertions fail if the misleading phrasing returns.
"""

from __future__ import annotations

from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "smc_core" / "sweep_trap.py").read_text(
    encoding="utf-8"
)
CORE_TESTS = (
    Path(__file__).resolve().parents[1] / "tests" / "test_smc_core_sweep_trap.py"
).read_text(encoding="utf-8")


def test_local_var_named_penetration_not_body() -> None:
    assert "sweep_penetration: float = abs(swept_level - sweep_extreme)" in SRC
    assert "sweep_body" not in SRC, "the 'sweep_body' misnomer returned"


def test_no_stale_candle_body_phrasing() -> None:
    assert "zero-body candle" not in SRC
    assert "fraction of the sweep body" not in SRC
    assert "fraction of sweep body recovered" not in SRC
    # The honest replacement must be present.
    assert "sweep penetration" in SRC


def test_fib_retrace_comment_admits_no_post_sweep_retrace() -> None:
    assert "how deeply did price retrace" not in SRC
    assert "NOT a measured price retrace" in SRC


def test_quality_score_marked_heuristic_and_unverified() -> None:
    assert "unverified heuristic" in SRC
    assert "NOT\nan empirically established leading indicator" in SRC or (
        "NOT an empirically established leading indicator"
        in SRC.replace("\n", " ").replace("  ", " ")
    )


def test_reversal_comment_is_confidence_reduction_not_deactivation() -> None:
    assert "the trap is no longer\n    # active" not in SRC
    assert "does not by itself deactivate" in SRC


def test_reversal_test_names_no_longer_claim_cancellation() -> None:
    # The old test *functions* asserted a "cancel"/"neutralise" that never
    # happened; guard their definitions are gone (match on 'def ' so an
    # explanatory mention of the old name in a comment doesn't trip this).
    assert "def test_enabled_reversal_against_sweep_cancels_trap" not in CORE_TESTS
    assert "def test_enabled_strong_reversal_neutralises_trap" not in CORE_TESTS
    assert "def test_reversal_against_sweep_reduces_confidence_but_stays_detected" in CORE_TESTS
