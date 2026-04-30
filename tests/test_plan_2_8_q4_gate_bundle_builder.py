"""Tests for ``scripts/plan_2_8_q4_gate_bundle_builder.py``.

Includes a small end-to-end check: builder output is fed into the
evaluator without any massaging, so the schema contract between the
two scripts stays pinned.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


builder = _load(
    "plan_2_8_q4_gate_bundle_builder",
    REPO / "scripts" / "plan_2_8_q4_gate_bundle_builder.py",
)
evaluator = _load(
    "plan_2_8_q4_gate_evaluator",
    REPO / "scripts" / "plan_2_8_q4_gate_evaluator.py",
)


def _rollup(scoring_root: str, families: dict[str, dict[str, dict[str, float]]]) -> dict:
    """Build a synthetic rollup matching the on-disk schema.

    families: ``{tf: {family: {n_events, hit_rate}}}``
    """
    per_tf = {}
    for tf, fam_map in families.items():
        per_tf[tf] = {
            "n_events": sum(int(v["n_events"]) for v in fam_map.values()),
            "hit_rate": 0.0,
            "symbols": [],
            "families": {
                fam: {"n_events": int(v["n_events"]), "hit_rate": float(v["hit_rate"])}
                for fam, v in fam_map.items()
            },
        }
    return {
        "schema_version": 1,
        "scoring_root": scoring_root,
        "timeframes": list(families.keys()),
        "files_scanned": 0,
        "per_tf": per_tf,
        "unknown_timeframes": {},
        "phase_e2_verdict": {},
    }


# ---- core builder --------------------------------------------------------- #

def test_build_bundle_intersects_buckets_and_orders_them() -> None:
    base = _rollup("base/", {
        "5m":  {"FVG": {"n_events": 100, "hit_rate": 0.45},
                "BOS": {"n_events":  50, "hit_rate": 0.40}},
        "1H":  {"FVG": {"n_events":  80, "hit_rate": 0.46}},
    })
    cand = _rollup("cand/", {
        "5m":  {"FVG": {"n_events": 110, "hit_rate": 0.49},
                "BOS": {"n_events":  55, "hit_rate": 0.43}},
        "1H":  {"FVG": {"n_events":  85, "hit_rate": 0.50}},
        "4H":  {"BOS": {"n_events":  35, "hit_rate": 0.55}},  # not in base
    })
    bundle = builder.build_bundle(
        baseline_rollup=base, candidate_rollup=cand,
        brier_baseline=0.235, brier_candidate=0.236,
    )
    keys = [b["key"] for b in bundle["buckets"]]
    # Intersection only, sorted.
    assert keys == ["1H/FVG", "5m/BOS", "5m/FVG"]
    fvg_5m = next(b for b in bundle["buckets"] if b["key"] == "5m/FVG")
    assert fvg_5m["hr_baseline"] == pytest.approx(0.45)
    assert fvg_5m["hr_candidate"] == pytest.approx(0.49)
    # n_events comes from the CANDIDATE arm (G3 gates the treatment).
    assert fvg_5m["n_events"] == 110


def test_build_bundle_carries_brier_and_sources() -> None:
    base = _rollup("baseroot", {"5m": {"FVG": {"n_events": 30, "hit_rate": 0.4}}})
    cand = _rollup("candroot", {"5m": {"FVG": {"n_events": 30, "hit_rate": 0.45}}})
    bundle = builder.build_bundle(
        baseline_rollup=base, candidate_rollup=cand,
        brier_baseline=0.21, brier_candidate=0.22,
    )
    assert bundle["brier_baseline"] == pytest.approx(0.21)
    assert bundle["brier_candidate"] == pytest.approx(0.22)
    assert bundle["sources"]["baseline_rollup"] == "baseroot"
    assert bundle["sources"]["candidate_rollup"] == "candroot"
    assert bundle["schema_version"] == 1


def test_bucket_filter_preserves_order() -> None:
    base = _rollup("b/", {
        "5m": {"FVG": {"n_events": 30, "hit_rate": 0.4},
               "BOS": {"n_events": 30, "hit_rate": 0.4}},
        "4H": {"BOS": {"n_events": 30, "hit_rate": 0.4}},
    })
    cand = _rollup("c/", {
        "5m": {"FVG": {"n_events": 30, "hit_rate": 0.5},
               "BOS": {"n_events": 30, "hit_rate": 0.5}},
        "4H": {"BOS": {"n_events": 30, "hit_rate": 0.5}},
    })
    bundle = builder.build_bundle(
        baseline_rollup=base, candidate_rollup=cand,
        brier_baseline=0.2, brier_candidate=0.2,
        bucket_filter=["4H/BOS", "5m/FVG"],
    )
    assert [b["key"] for b in bundle["buckets"]] == ["4H/BOS", "5m/FVG"]


def test_bucket_filter_rejects_missing_bucket() -> None:
    base = _rollup("b/", {"5m": {"FVG": {"n_events": 30, "hit_rate": 0.4}}})
    cand = _rollup("c/", {"5m": {"FVG": {"n_events": 30, "hit_rate": 0.5}}})
    with pytest.raises(ValueError, match="not present in both rollups"):
        builder.build_bundle(
            baseline_rollup=base, candidate_rollup=cand,
            brier_baseline=0.2, brier_candidate=0.2,
            bucket_filter=["4H/BOS"],
        )


def test_bucket_filter_rejects_malformed_spec() -> None:
    base = _rollup("b/", {"5m": {"FVG": {"n_events": 30, "hit_rate": 0.4}}})
    cand = _rollup("c/", {"5m": {"FVG": {"n_events": 30, "hit_rate": 0.5}}})
    with pytest.raises(ValueError, match="must be 'tf/family'"):
        builder.build_bundle(
            baseline_rollup=base, candidate_rollup=cand,
            brier_baseline=0.2, brier_candidate=0.2,
            bucket_filter=["bogus"],
        )


# ---- end-to-end with the evaluator ---------------------------------------- #

def test_builder_output_feeds_evaluator_pass_path() -> None:
    base = _rollup("b/", {
        "5m": {"FVG": {"n_events": 100, "hit_rate": 0.45}},
        "1H": {"FVG": {"n_events": 100, "hit_rate": 0.45}},
        "4H": {"BOS": {"n_events":  35, "hit_rate": 0.40}},
    })
    cand = _rollup("c/", {
        "5m": {"FVG": {"n_events": 100, "hit_rate": 0.49}},  # +4pp
        "1H": {"FVG": {"n_events": 100, "hit_rate": 0.49}},  # +4pp
        "4H": {"BOS": {"n_events":  35, "hit_rate": 0.44}},  # +4pp
    })
    bundle = builder.build_bundle(
        baseline_rollup=base, candidate_rollup=cand,
        brier_baseline=0.235, brier_candidate=0.236,  # regression < 0.02
    )
    verdict = evaluator.evaluate_gate(bundle)
    # 3 buckets each with +4pp uplift, all >= 30 events, brier OK.
    assert verdict["overall"] == "pass"
    assert verdict["gates"]["G1_uplift"]["passed"]
    assert verdict["gates"]["G2_brier"]["passed"]
    assert verdict["gates"]["G3_min_events"]["passed"]


def test_builder_output_feeds_evaluator_fail_g3_path() -> None:
    base = _rollup("b/", {
        "5m": {"FVG": {"n_events": 25, "hit_rate": 0.45}},   # below 30
        "1H": {"FVG": {"n_events": 30, "hit_rate": 0.45}},
    })
    cand = _rollup("c/", {
        "5m": {"FVG": {"n_events": 25, "hit_rate": 0.50}},   # below 30
        "1H": {"FVG": {"n_events": 30, "hit_rate": 0.50}},
    })
    bundle = builder.build_bundle(
        baseline_rollup=base, candidate_rollup=cand,
        brier_baseline=0.2, brier_candidate=0.2,
    )
    verdict = evaluator.evaluate_gate(bundle)
    assert verdict["overall"] == "fail"
    assert not verdict["gates"]["G3_min_events"]["passed"]
    assert "5m/FVG" in verdict["gates"]["G3_min_events"]["under_threshold_buckets"]


# ---- CLI ------------------------------------------------------------------ #

def test_cli_writes_bundle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base_path = tmp_path / "base.json"
    cand_path = tmp_path / "cand.json"
    out_path = tmp_path / "out" / "bundle.json"
    base_path.write_text(json.dumps(_rollup("b/", {
        "5m": {"FVG": {"n_events": 30, "hit_rate": 0.4}}})), encoding="utf-8")
    cand_path.write_text(json.dumps(_rollup("c/", {
        "5m": {"FVG": {"n_events": 30, "hit_rate": 0.5}}})), encoding="utf-8")
    rc = builder.main([
        "--baseline-rollup", str(base_path),
        "--candidate-rollup", str(cand_path),
        "--brier-baseline", "0.20",
        "--brier-candidate", "0.21",
        "--output", str(out_path),
    ])
    assert rc == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert written["buckets"][0]["key"] == "5m/FVG"
    assert "wrote bundle with 1 bucket(s)" in capsys.readouterr().out


def test_cli_error_on_unreadable_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = builder.main([
        "--baseline-rollup", str(tmp_path / "missing.json"),
        "--candidate-rollup", str(tmp_path / "missing.json"),
        "--brier-baseline", "0.2",
        "--brier-candidate", "0.2",
        "--output", str(tmp_path / "out.json"),
    ])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().err
