from __future__ import annotations

import csv
import json
from argparse import Namespace
from pathlib import Path

from scripts import analyze_smc_contextual_calibration_history as analysis_script


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _contextual_dimension(adjusted_brier: float, adjusted_ece: float) -> dict:
    return {
        "n_events": 18,
        "covered_events": 18,
        "coverage_ratio": 1.0,
        "populated_groups": 2,
        "delta_brier_score": round(0.20 - adjusted_brier, 6),
        "delta_ece": round(0.14 - adjusted_ece, 6),
        "adjusted_brier_score": adjusted_brier,
        "adjusted_ece": adjusted_ece,
        "fallback_event_count": 0,
    }


def _build_evidence_summary(now_ts: float) -> dict:
    return {
        "generated_at": now_ts - 10.0,
        "generated_at_iso": "2023-11-14T22:13:10+00:00",
        "report_kind": "gate_evidence_summary",
        "measurement_history": {
            "contextual_recommendation_policy": {
                "min_scoring_events": 8,
                "min_coverage_ratio": 0.6,
                "min_populated_groups": 1,
                "min_delta_brier_score": 0.001,
                "min_delta_ece": 0.002,
                "max_fallback_event_ratio": 0.35,
            },
            "contextual_promotion_policy": {
                "min_history_runs": 3,
                "min_recommended_run_ratio": 0.75,
                "require_metric_consensus": True,
            },
            "history_by_pair": {
                "AAPL/15m": [
                    {
                        "pair": "AAPL/15m",
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "checked_at": now_ts - 60.0,
                        "checked_at_iso": "2023-11-14T22:12:20+00:00",
                        "n_events": 18,
                        "contextual_calibration": {
                            "session": _contextual_dimension(0.11, 0.08),
                            "htf_bias": _contextual_dimension(0.14, 0.10),
                        },
                    },
                    {
                        "pair": "AAPL/15m",
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "checked_at": now_ts - 120.0,
                        "checked_at_iso": "2023-11-14T22:11:20+00:00",
                        "n_events": 18,
                        "contextual_calibration": {
                            "session": _contextual_dimension(0.115, 0.082),
                            "htf_bias": _contextual_dimension(0.145, 0.101),
                        },
                    },
                    {
                        "pair": "AAPL/15m",
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "checked_at": now_ts - 180.0,
                        "checked_at_iso": "2023-11-14T22:10:20+00:00",
                        "n_events": 18,
                        "contextual_calibration": {
                            "session": _contextual_dimension(0.118, 0.083),
                            "htf_bias": _contextual_dimension(0.146, 0.102),
                        },
                    },
                ],
                "MSFT/1H": [
                    {
                        "pair": "MSFT/1H",
                        "symbol": "MSFT",
                        "timeframe": "1H",
                        "checked_at": now_ts - 90.0,
                        "checked_at_iso": "2023-11-14T22:11:50+00:00",
                        "n_events": 18,
                        "contextual_calibration": {
                            "session": _contextual_dimension(0.145, 0.102),
                            "htf_bias": _contextual_dimension(0.12, 0.085),
                        },
                    },
                    {
                        "pair": "MSFT/1H",
                        "symbol": "MSFT",
                        "timeframe": "1H",
                        "checked_at": now_ts - 150.0,
                        "checked_at_iso": "2023-11-14T22:10:50+00:00",
                        "n_events": 18,
                        "contextual_calibration": {
                            "session": _contextual_dimension(0.119, 0.084),
                            "htf_bias": _contextual_dimension(0.143, 0.101),
                        },
                    },
                ],
            },
        },
    }


def test_contextual_history_analysis_summarizes_recommendation_and_promotion(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(analysis_script.time, "time", lambda: now_ts)

    evidence_summary = _build_evidence_summary(now_ts)
    input_path = tmp_path / "smc_evidence_summary.json"
    _write_json(input_path, evidence_summary)

    captured: list[dict] = []
    monkeypatch.setattr(
        analysis_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input=str(input_path),
                output="-",
            )
        ),
    )
    monkeypatch.setattr(analysis_script, "_render", lambda report, output: captured.append(report))

    rc = analysis_script.main()

    assert rc == 0
    report = captured[-1]
    assert report["report_kind"] == "contextual_calibration_history_analysis"
    assert report["pairs_total"] == 2
    assert report["history_runs_total"] == 5
    assert report["recommendation_runs_total"] == 5
    assert report["promotion_ready_runs_total"] == 1
    assert report["recommendation_counts"] == {"session": 4, "htf_bias": 1}
    assert report["promotion_ready_counts"] == {"session": 1}
    assert report["latest_recommendation_counts"] == {"htf_bias": 1, "session": 1}
    assert report["latest_promotion_ready_counts"] == {"session": 1}
    assert report["contextual_recommendation_policy"]["max_fallback_event_ratio"] == 0.35
    assert report["contextual_promotion_policy"]["min_recommended_run_ratio"] == 0.75
    assert report["pairs_with_recommendation_switches"] == ["MSFT/1H"]
    assert report["pairs_latest_not_promotion_ready"] == ["MSFT/1H"]

    pair_summaries = {row["pair"]: row for row in report["pair_summaries"]}
    assert pair_summaries["AAPL/15m"]["latest_recommended_dimension"] == "session"
    assert pair_summaries["AAPL/15m"]["latest_promotion_ready"] is True
    assert pair_summaries["AAPL/15m"]["modal_recommended_dimension"] == "session"
    assert pair_summaries["AAPL/15m"]["modal_recommendation_share"] == 1.0
    assert pair_summaries["MSFT/1H"]["latest_recommended_dimension"] == "htf_bias"
    assert pair_summaries["MSFT/1H"]["latest_promotion_ready"] is False
    assert pair_summaries["MSFT/1H"]["recommendation_counts"] == {"htf_bias": 1, "session": 1}


def test_contextual_history_analysis_writes_markdown_and_pair_csv(monkeypatch, tmp_path: Path) -> None:
    now_ts = 1_700_000_000.0
    monkeypatch.setattr(analysis_script.time, "time", lambda: now_ts)

    input_path = tmp_path / "smc_evidence_summary.json"
    json_output_path = tmp_path / "smc_contextual_history_analysis.json"
    markdown_output_path = tmp_path / "smc_contextual_history_analysis.md"
    csv_output_path = tmp_path / "smc_contextual_history_pairs.csv"
    _write_json(input_path, _build_evidence_summary(now_ts))

    monkeypatch.setattr(
        analysis_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input=str(input_path),
                output=str(json_output_path),
                markdown_output=str(markdown_output_path),
                pair_summary_csv=str(csv_output_path),
            )
        ),
    )

    rc = analysis_script.main()

    assert rc == 0
    assert json_output_path.exists()
    markdown_text = markdown_output_path.read_text(encoding="utf-8")
    assert "# Contextual Calibration History Analysis" in markdown_text
    assert "| session | 4 | 1 | 1 | 1 |" in markdown_text
    assert "| MSFT/1H | htf_bias | htf_bias | no | 50.0% |" in markdown_text
    assert "insufficient_history_runs" in markdown_text
    assert "insufficient_recommendation_history" in markdown_text
    assert "recommended_dimension_not_stable_across_history" in markdown_text

    with csv_output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    aapl_row = next(row for row in rows if row["pair"] == "AAPL/15m")
    msft_row = next(row for row in rows if row["pair"] == "MSFT/1H")
    assert aapl_row["recommendation_count_session"] == "3"
    assert aapl_row["promotion_ready_count_session"] == "1"
    assert msft_row["recommendation_count_htf_bias"] == "1"
    assert msft_row["recommendation_count_vol_regime"] == "0"
    assert msft_row["latest_promotion_ready"] == "False"


def test_contextual_history_analysis_requires_measurement_history(monkeypatch, tmp_path: Path) -> None:
    input_path = tmp_path / "invalid.json"
    _write_json(input_path, {"report_kind": "gate_evidence_summary"})

    monkeypatch.setattr(
        analysis_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                input=str(input_path),
                output="-",
            )
        ),
    )

    rc = analysis_script.main()

    assert rc == 1