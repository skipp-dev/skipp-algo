from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from scripts import run_smc_measurement_benchmark as benchmark_script
from smc_core.ensemble_quality import serialize_ensemble_quality, build_ensemble_quality
from smc_core.scoring import ScoredEvent
from smc_integration.measurement_evidence import MeasurementEvidence


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def test_measurement_benchmark_harness_writes_manifest_and_plots(monkeypatch, tmp_path: Path) -> None:
    evidence = MeasurementEvidence(
        events_by_family={
            "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
            "OB": [{"hit": True, "time_to_mitigation": 2.0, "invalidated": False, "mae": 0.02, "mfe": 0.04}],
            "FVG": [],
            "SWEEP": [{"hit": False, "time_to_mitigation": 4.0, "invalidated": True, "mae": 0.03, "mfe": 0.01}],
        },
        stratified_events={
            "htf_bias:BULLISH": {
                "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
                "OB": [{"hit": True, "time_to_mitigation": 2.0, "invalidated": False, "mae": 0.02, "mfe": 0.04}],
                "FVG": [],
                "SWEEP": [],
            },
            "vol_regime:NORMAL": {
                "BOS": [],
                "OB": [],
                "FVG": [],
                "SWEEP": [{"hit": False, "time_to_mitigation": 4.0, "invalidated": True, "mae": 0.03, "mfe": 0.01}],
            },
        },
        scored_events=[
            ScoredEvent("bos-1", "BOS", 0.75, True, 1.0),
            ScoredEvent("ob-1", "OB", 0.62, True, 2.0),
            ScoredEvent("sw-1", "SWEEP", 0.40, False, 3.0),
        ],
        details={
            "measurement_evidence_present": True,
            "evaluated_event_counts": {"BOS": 1, "OB": 1, "FVG": 0, "SWEEP": 1},
            "bars_source_mode": "synthetic_bundle",
            "ensemble_quality": serialize_ensemble_quality(
                build_ensemble_quality(
                    bias_direction="BULLISH",
                    bias_confidence=0.82,
                    vol_regime_label="NORMAL",
                    vol_regime_confidence=0.76,
                    scoring_result=benchmark_script.score_events(
                        [
                            ScoredEvent("bos-1", "BOS", 0.75, True, 1.0),
                            ScoredEvent("ob-1", "OB", 0.62, True, 2.0),
                            ScoredEvent("sw-1", "SWEEP", 0.40, False, 3.0),
                        ]
                    ),
                )
            ),
        },
        warnings=["example-warning"],
    )
    monkeypatch.setattr(benchmark_script, "build_measurement_evidence", lambda symbol, timeframe: evidence)
    monkeypatch.setattr(
        benchmark_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="AAPL",
                timeframes="15m",
                output_dir=str(tmp_path / "measurement_benchmark"),
            )
        ),
    )

    rc = benchmark_script.main()

    assert rc == 0
    root = tmp_path / "measurement_benchmark"
    pair_dir = root / "AAPL" / "15m"
    assert (pair_dir / "benchmark_AAPL_15m.json").exists()
    assert (pair_dir / "benchmark_AAPL_15m_kpis.csv").exists()
    assert (pair_dir / "scoring_AAPL_15m.json").exists()
    assert (pair_dir / "ensemble_quality_AAPL_15m.json").exists()
    assert (pair_dir / "measurement_summary_AAPL_15m.json").exists()
    assert (pair_dir / "measurement_summary_AAPL_15m.csv").exists()
    assert (pair_dir / "reliability_AAPL_15m.html").exists()
    assert (pair_dir / "stratification_AAPL_15m.html").exists()
    assert (pair_dir / "harness_manifest.json").exists()
    assert (root / "benchmark_run_summary.csv").exists()
    assert (root / "benchmark_run_manifest.json").exists()

    summary = json.loads((pair_dir / "measurement_summary_AAPL_15m.json").read_text(encoding="utf-8"))
    assert summary["measurement_evidence_present"] is True
    assert summary["benchmark_event_counts"]["BOS"] == 1
    assert summary["scoring"]["n_events"] == 3
    assert summary["scoring"]["families_present"] == ["BOS", "OB", "SWEEP"]
    assert summary["artifacts"]["ensemble_quality_json"] == "ensemble_quality_AAPL_15m.json"
    assert summary["ensemble_quality"]["available_components"] == ["bias", "scoring", "vol_regime"]
    assert summary["stratification_coverage"]["populated_bucket_count"] == 2

    run_manifest = json.loads((root / "benchmark_run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["pair_runs"][0]["artifact_dir"] == "AAPL/15m"
    assert run_manifest["pair_runs"][0]["summary_path"] == "AAPL/15m/measurement_summary_AAPL_15m.json"