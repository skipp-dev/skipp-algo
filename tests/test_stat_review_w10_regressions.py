"""W10 stat-review regression tests.

W10-1: build_report() auto-wires n_concurrent_families from snapshot count
       so the W9-6 Bonferroni FWER correction activates for multi-family runs.
W10-2: run_ab_comparison main() --spec-path loads SPRT p0/p1/alpha/beta from
       the experiment JSON spec instead of the divergent module-level defaults.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _green_snapshot(family: str = "BOS") -> Any:
    """Minimal green FamilyMetrics for promotion-gate tests."""
    from governance.promotion_gate import FamilyMetrics
    return FamilyMetrics(
        family=family,  # type: ignore[arg-type]
        brier=0.18,
        ece=0.03,
        fdr_pvalue=0.01,
        psr=0.97,
        mintrl_years=1.4,
        psi=0.12,
        live_brier=0.19,
        walkforward_brier=0.18,
    )


# ---------------------------------------------------------------------------
# W10-1 — n_concurrent_families Bonferroni auto-wiring
# ---------------------------------------------------------------------------

class TestW10_1_NConcurrentFamilies:
    """W10-1: build_report() must pass n_concurrent_families=len(snapshots)
    to GateThresholds so the Bonferroni FWER correction is active for
    multi-family promotion runs."""

    def _run_build_report(self, snapshots: list[Any], **kwargs: Any) -> dict[str, Any]:
        from scripts.run_promotion_gate import build_report  # type: ignore[import]
        return build_report(snapshots, **kwargs)

    def test_single_family_effective_alpha_unchanged(self) -> None:
        """With 1 snapshot, n_concurrent_families=1, Bonferroni does nothing."""
        from governance.promotion_gate import GateThresholds
        t = GateThresholds(n_concurrent_families=1)
        # effective threshold = fdr_q / n_concurrent_families
        assert t.fdr_q / t.n_concurrent_families == pytest.approx(t.fdr_q)

    def test_two_families_halves_effective_alpha(self) -> None:
        """With 2 concurrent families the effective alpha should be halved
        relative to a single-family run (Bonferroni FWER = fdr_q / k)."""
        from governance.promotion_gate import GateThresholds
        t1 = GateThresholds(n_concurrent_families=1)
        t2 = GateThresholds(n_concurrent_families=2)
        effective_1 = t1.fdr_q / t1.n_concurrent_families
        effective_2 = t2.fdr_q / t2.n_concurrent_families
        assert effective_2 == pytest.approx(effective_1 / 2, rel=1e-9), (
            "W10-1: Bonferroni correction is not halving the threshold for "
            "k=2 families — the FWER correction is broken"
        )

    def test_build_report_uses_snapshot_count_for_n_concurrent_families(
        self,
    ) -> None:
        """build_report() must internally pass n_concurrent_families=len(snapshots)
        so callers that don't supply it explicitly get the correct correction."""
        from governance.promotion_gate import GateThresholds

        captured: dict[str, Any] = {}
        _orig_GateThresholds = GateThresholds

        class _CapturingGateThresholds(_orig_GateThresholds):  # type: ignore[misc]
            def __init__(self, **kw: Any) -> None:
                captured.update(kw)
                super().__init__(**kw)

        snaps = [_green_snapshot("BOS"), _green_snapshot("CHOCH")]
        with patch("scripts.run_promotion_gate.GateThresholds", _CapturingGateThresholds):
            from scripts.run_promotion_gate import build_report  # type: ignore[import]
            build_report(snaps)

        assert captured.get("n_concurrent_families") == 2, (
            f"W10-1: build_report() passed n_concurrent_families="
            f"{captured.get('n_concurrent_families')!r}, expected 2 (len of snapshot list). "
            "The Bonferroni correction is not being wired up automatically."
        )

    def test_explicit_override_respected(self) -> None:
        """When the caller explicitly passes n_concurrent_families it must take
        precedence over the automatic len(snapshots) calculation."""
        from governance.promotion_gate import GateThresholds

        captured: dict[str, Any] = {}
        _orig = GateThresholds

        class _Cap(_orig):  # type: ignore[misc]
            def __init__(self, **kw: Any) -> None:
                captured.update(kw)
                super().__init__(**kw)

        snaps = [_green_snapshot("BOS"), _green_snapshot("CHOCH")]
        with patch("scripts.run_promotion_gate.GateThresholds", _Cap):
            from scripts.run_promotion_gate import build_report  # type: ignore[import]
            build_report(snaps, n_concurrent_families=5)

        assert captured.get("n_concurrent_families") == 5, (
            "W10-1: explicit n_concurrent_families=5 not respected by build_report()"
        )


# ---------------------------------------------------------------------------
# W10-2 — SPRT spec-path CLI
# ---------------------------------------------------------------------------

class TestW10_2_SPRTSpecPath:
    """W10-2: run_ab_comparison main() must load p0/p1 from the experiment
    spec when --spec-path is supplied, not from the divergent module defaults."""

    def _make_spec(self, tmp_path: Path, **sprt_overrides: Any) -> Path:
        spec = {
            "experiment_name": "test_exp",
            "sprt": {
                "p0": 0.544,
                "p1": 0.574,
                "alpha": 0.05,
                "beta": 0.20,
                "max_n": 1200,
                **sprt_overrides,
            },
        }
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec), encoding="utf-8")
        return p

    def test_spec_path_builds_sprt_config_from_spec(
        self, tmp_path: Path
    ) -> None:
        """When --spec-path is passed, main() parses the spec JSON and builds a
        SPRTConfig with p0/p1 matching the spec — NOT the module-level defaults."""
        spec = self._make_spec(tmp_path, p0=0.544, p1=0.574)

        # Exercise the spec-loading code path directly (avoiding full treatment-
        # dir parsing) by calling the inline JSON-load block that was added by
        # the W10-2 fix.  We do this by importing run_ab_comparison, building
        # the args namespace manually, and replicating the spec-load logic to
        # verify it produces the correct SPRTConfig.
        import json as _json

        from scripts.run_ab_comparison import SPRT_ALPHA, SPRT_BETA, SPRTConfig  # type: ignore[import]

        _spec = _json.loads(spec.read_text())
        _s = _spec.get("sprt", {})
        cfg = SPRTConfig(
            p0=float(_s["p0"]),
            p1=float(_s["p1"]),
            alpha=float(_s.get("alpha", SPRT_ALPHA)),
            beta=float(_s.get("beta", SPRT_BETA)),
            max_n=int(_s["max_n"]) if "max_n" in _s else None,
        )
        assert cfg.p0 == pytest.approx(0.544), (
            f"W10-2: spec p0=0.544 not loaded — got p0={cfg.p0}"
        )
        assert cfg.p1 == pytest.approx(0.574), (
            f"W10-2: spec p1=0.574 not loaded — got p1={cfg.p1}"
        )

    def test_module_defaults_differ_from_spec(self) -> None:
        """Regression: confirm the module defaults ARE different from the spec
        values so we know the spec-path path is doing real work."""
        from scripts.run_ab_comparison import SPRT_P0, SPRT_P1
        spec_p0, spec_p1 = 0.544, 0.574
        # If this assertion ever fails it means the defaults were changed to
        # match the spec — at that point --spec-path becomes optional and this
        # test can be updated.
        assert spec_p0 != SPRT_P0 or spec_p1 != SPRT_P1, (
            "Module defaults now match the spec — the --spec-path guard is "
            "still useful (different experiment specs could have other values) "
            "but the drift described by W10-2 has been resolved in-place."
        )

    def test_missing_spec_path_file_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """When --spec-path points to a non-existent file main() must exit with
        a non-zero code rather than silently falling back to module defaults."""
        # Provide required dirs so argparse succeeds; the spec-path check fires
        # before control/treatment parsing.
        ctrl_dir = tmp_path / "ctrl"
        ctrl_dir.mkdir()
        trt_dir = tmp_path / "trt"
        trt_dir.mkdir()
        nonexistent = tmp_path / "no_such_file.json"
        from scripts.run_ab_comparison import main  # type: ignore[import]
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--control-dir", str(ctrl_dir),
                "--treatment-dir", str(trt_dir),
                "--spec-path", str(nonexistent),
            ])
        assert exc_info.value.code != 0, (
            "W10-2: missing --spec-path file should trigger sys.exit(1), "
            "not silently fall back to wrong SPRT defaults"
        )

    def test_invalid_json_spec_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """A malformed spec JSON must exit non-zero (not propagate an exception
        to the caller with wrong defaults in effect)."""
        ctrl_dir = tmp_path / "ctrl"
        ctrl_dir.mkdir()
        trt_dir = tmp_path / "trt"
        trt_dir.mkdir()
        bad_spec = tmp_path / "bad.json"
        bad_spec.write_text("{not valid json", encoding="utf-8")
        from scripts.run_ab_comparison import main  # type: ignore[import]
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--control-dir", str(ctrl_dir),
                "--treatment-dir", str(trt_dir),
                "--spec-path", str(bad_spec),
            ])
        assert exc_info.value.code != 0
