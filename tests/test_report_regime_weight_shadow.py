"""The exact §15 shadow gets a full-universe report consumer."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.report_regime_weight_shadow import summarize


def _payload(rows: list[dict]) -> dict:
    return {"schema_version": 1, "ranked_v2": rows}


def _row(symbol: str, regime: str, delta: float) -> dict:
    return {
        "symbol": symbol,
        "regime_weight_shadow": {
            "exact_second_scorer_pass": True,
            "rank_delta": 0,
            "measured_regime": regime,
            "score_delta": delta,
            "would_change_score": bool(delta),
        },
    }


def test_summarize_aggregates_exact_rows_across_files(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps(_payload([
        _row("AA", "TRENDING", 0.4), _row("BB", "NEUTRAL", 0.0),
    ])), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(_payload([
        _row("CC", "RANGING", -0.6),
    ])), encoding="utf-8")

    out = summarize(sorted(tmp_path.glob("*.json")))
    assert out["rows"] == 3
    assert out["exact_rows"] == 3
    assert out["unresolved_rows"] == 0
    assert out["measured_regime_counts"] == {"NEUTRAL": 1, "RANGING": 1, "TRENDING": 1}
    assert out["non_neutral_share"] == round(2 / 3, 4)
    assert out["would_change_share"] == round(2 / 3, 4)
    assert out["max_abs_score_delta"] == 0.6
    assert out["top_movers"][0]["symbol"] == "CC"


def test_full_universe_summary_takes_precedence_over_served_rows(tmp_path: Path) -> None:
    served = _row("TOP", "NEUTRAL", 0.0)
    outside_top = _row("OUTSIDE", "TRENDING", 0.5)["regime_weight_shadow"]
    outside_top["symbol"] = "OUTSIDE"
    payload = _payload([served])
    payload["regime_weight_shadow_summary"] = {"comparisons": [outside_top]}
    path = tmp_path / "full.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    out = summarize([path])
    assert out["rows"] == 1
    assert out["measured_regime_counts"] == {"TRENDING": 1}
    assert out["top_movers"][0]["symbol"] == "OUTSIDE"


def test_unresolved_rows_do_not_enter_decision_denominators(tmp_path: Path) -> None:
    unresolved = _row("XX", "NEUTRAL", 0.0)
    unresolved["regime_weight_shadow"]["exact_second_scorer_pass"] = False
    path = tmp_path / "a.json"
    path.write_text(json.dumps(_payload([unresolved, _row("AA", "NEUTRAL", 0.0)])), encoding="utf-8")

    out = summarize([path])
    assert out["rows"] == 2
    assert out["exact_rows"] == 1
    assert out["unresolved_rows"] == 1
    assert out["non_neutral_share"] == 0.0


def test_empty_input_is_honest_not_zeroed() -> None:
    out = summarize([])
    assert out["rows"] == 0
    assert out["exact_rows"] == 0
    assert out["non_neutral_share"] is None
    assert out["mean_abs_score_delta"] is None
