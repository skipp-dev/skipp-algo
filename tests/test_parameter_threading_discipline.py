"""Discipline: neutral-default feature parameters must be wired through by callers.

W10-1 root-cause: ``build_report()`` received ``n_concurrent_families`` with a
neutral default (``None`` → 1), but the only production caller
``main()`` in ``run_promotion_gate.py`` never passed the actual snapshot count.
The Bonferroni correction was therefore dormant for every multi-family run.

This file guards against that class of defect by verifying, via
``unittest.mock.patch``, that callers of ``build_report()`` supply a
**non-trivial** ``n_concurrent_families`` whenever the input contains more than
one family.
"""

from __future__ import annotations

from unittest.mock import call, patch

import pytest

from governance.promotion_gate import FamilyMetrics, GateThresholds


# ---------------------------------------------------------------------------
# Minimal helpers
# ---------------------------------------------------------------------------

def _make_snap(family: str = "BOS") -> FamilyMetrics:
    """Return the most minimal valid FamilyMetrics (all metrics omitted)."""
    return FamilyMetrics(family=family)  # type: ignore[arg-type]


def _captured_n_concurrent(snapshots, **kwargs) -> int:
    """Call build_report and return the n_concurrent_families value that
    was forwarded to GateThresholds.__init__."""
    from scripts.run_promotion_gate import build_report

    captured: list[int] = []
    original_init = GateThresholds.__init__

    def _spy_init(self, *args, **kw):
        captured.append(kw.get("n_concurrent_families"))
        original_init(self, *args, **kw)

    with patch.object(GateThresholds, "__init__", _spy_init):
        build_report(snapshots, **kwargs)

    assert captured, "GateThresholds.__init__ was never called inside build_report"
    return captured[0]


# ---------------------------------------------------------------------------
# Guard 1 — build_report wires n_concurrent_families from snapshot count
# ---------------------------------------------------------------------------


class TestBuildReportConcurrencyWiring:
    """build_report() must pass n_concurrent_families == len(snapshots) to
    GateThresholds whenever the caller does not override it explicitly."""

    def test_single_snapshot_passes_n1(self) -> None:
        """One snapshot → n_concurrent_families=1, Bonferroni inactive (expected)."""
        n = _captured_n_concurrent([_make_snap("BOS")])
        assert n == 1, (
            f"With 1 snapshot, n_concurrent_families must be 1 (got {n})"
        )

    def test_two_snapshots_passes_n2(self) -> None:
        """Two snapshots → n_concurrent_families=2 (Bonferroni halves threshold)."""
        n = _captured_n_concurrent([_make_snap("BOS"), _make_snap("FVG")])
        assert n == 2, (
            f"With 2 snapshots, n_concurrent_families must be 2, got {n}. "
            "W10-1 regression: the Bonferroni correction would be dormant."
        )

    def test_three_snapshots_passes_n3(self) -> None:
        """Three snapshots → n_concurrent_families=3."""
        n = _captured_n_concurrent(
            [_make_snap("BOS"), _make_snap("FVG"), _make_snap("OB")]
        )
        assert n == 3, f"Expected n_concurrent_families=3, got {n}"

    def test_explicit_override_is_respected(self) -> None:
        """An explicit n_concurrent_families override must not be silently replaced."""
        n = _captured_n_concurrent(
            [_make_snap("BOS"), _make_snap("FVG")],
            n_concurrent_families=5,  # caller forces 5 (larger portfolio context)
        )
        assert n == 5, (
            f"Explicit n_concurrent_families=5 override was not respected (got {n})."
        )

    def test_empty_snapshot_list_does_not_crash(self) -> None:
        """build_report([]) must not raise — n_concurrent_families resolves to 1."""
        from scripts.run_promotion_gate import build_report

        result = build_report([])
        assert isinstance(result, dict)
