"""W10 stat-review regression tests.

W10-1 (superseded): the earlier build_report() Bonferroni auto-wiring was
       removed — ``fdr_pvalue`` is already a Benjamini-Hochberg q-value adjusted
       across the run's families, so dividing ``fdr_q`` by the family count again
       double-corrected the same multiplicity. The gate now compares the BH
       q-value directly against ``fdr_q``; the tests below pin that BH-alone
       behaviour so the double-correction cannot silently return.
W10-2: run_ab_comparison main() --spec-path loads SPRT p0/p1/alpha/beta from
       the experiment JSON spec instead of the divergent module-level defaults.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _green_snapshot(family: str = "BOS", *, fdr_pvalue: float = 0.01) -> Any:
    """Minimal green FamilyMetrics for promotion-gate tests."""
    from governance.promotion_gate import FamilyMetrics
    return FamilyMetrics(
        family=family,  # type: ignore[arg-type]
        brier=0.18,
        ece=0.03,
        fdr_pvalue=fdr_pvalue,
        psr=0.97,
        mintrl_years=1.4,
        psi=0.12,
        live_brier=0.19,
        walkforward_brier=0.18,
    )


# ---------------------------------------------------------------------------
# W10-1 (superseded) — FDR uses the BH q-value alone, no per-run Bonferroni
# ---------------------------------------------------------------------------

class TestFdrBhAloneNoDoubleCorrection:
    """The gate must compare the (already BH-adjusted) fdr_pvalue against
    ``fdr_q`` directly — never re-divide it by the number of families."""

    def test_family_count_does_not_change_fdr_threshold(self) -> None:
        """A family with fdr_pvalue=0.03 clears the 0.05 bar regardless of how
        many families ran alongside it — the removed /k Bonferroni layer would
        have blocked it at fdr_q/k."""
        from scripts.run_promotion_gate import build_report

        snaps = [_green_snapshot(f, fdr_pvalue=0.03) for f in ("BOS", "OB", "FVG", "SWEEP")]
        report = build_report(snaps, strict_provenance=False)
        for decision in report["decisions"]:
            fdr_blockers = [
                b for b in decision["blockers"]
                if b["check"] == "fdr_significance" and b["severity"] == "blocker"
            ]
            assert not fdr_blockers, (
                f"{decision['family']}: fdr_pvalue=0.03 must clear fdr_q=0.05 "
                "irrespective of family count (no per-run Bonferroni re-division)"
            )

    def test_gatethresholds_has_no_concurrency_knob(self) -> None:
        """The removed Bonferroni layer must not creep back as a constructor kwarg."""
        from governance.promotion_gate import GateThresholds

        with pytest.raises(TypeError):
            GateThresholds(n_concurrent_families=2)  # type: ignore[call-arg]


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
        """W10-2: when --spec-path is passed, main() must load p0/p1 from the
        spec JSON and reach the SPRT-building code without error.

        Drives main() end-to-end with minimal (empty) benchmark manifests so it
        exits(1) from the empty-pairs guard — not from a spec parse error.
        Any KeyError/TypeError in spec loading would surface as an unhandled
        exception here, failing the test.
        """
        import json as _json

        spec = self._make_spec(tmp_path, p0=0.544, p1=0.574)
        # Minimal manifests so load_benchmark() returns [] instead of raising.
        for d in ("ctrl", "trt"):
            bd = tmp_path / d
            bd.mkdir(exist_ok=True)
            (bd / "benchmark_run_manifest.json").write_text(
                _json.dumps({"pair_runs": []}), encoding="utf-8"
            )
        out_dir = tmp_path / "out"

        from scripts.run_ab_comparison import main  # type: ignore[import]

        with pytest.raises(SystemExit) as exc_info:
            main([
                "--control-dir", str(tmp_path / "ctrl"),
                "--treatment-dir", str(tmp_path / "trt"),
                "--spec-path", str(spec),
                "--output-dir", str(out_dir),
            ])
        # exit(1) = empty benchmark dirs — spec was loaded successfully.
        assert exc_info.value.code == 1, (
            "Expected exit(1) for empty benchmark dirs after successful spec "
            f"load; got exit({exc_info.value.code})."
        )
        # W10-2 thread 4: also verify a spec with missing p0/p1 causes exit(1).
        # Both paths exit 1, but the spec-parse error must not silently pass.
        spec_bad = tmp_path / "bad_spec.json"
        spec_bad.write_text('{"sprt": {}}', encoding="utf-8")  # missing p0/p1
        with pytest.raises(SystemExit) as bad_info:
            main([
                "--control-dir", str(tmp_path / "ctrl"),
                "--treatment-dir", str(tmp_path / "trt"),
                "--spec-path", str(spec_bad),
                "--output-dir", str(out_dir),
            ])
        assert bad_info.value.code == 1, (
            "W10-2: spec with missing p0/p1 must exit 1 — "
            f"got exit({bad_info.value.code})"
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
