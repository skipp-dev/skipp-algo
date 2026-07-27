"""The §15 shadow gets a consumer — pins the aggregation the decision reads."""
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
            "measured_regime": regime,
            "score_delta": delta,
            "would_change_score": bool(delta),
        },
    }


def test_summarize_aggregates_across_files(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps(_payload([
        _row("AA", "TRENDING", 0.4), _row("BB", "NEUTRAL", 0.0),
    ])), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(_payload([
        _row("CC", "RANGING", -0.6),
    ])), encoding="utf-8")

    out = summarize(sorted(tmp_path.glob("*.json")))
    assert out["rows"] == 3
    assert out["measured_regime_counts"] == {"NEUTRAL": 1, "RANGING": 1, "TRENDING": 1}
    assert out["non_neutral_share"] == round(2 / 3, 4)
    assert out["would_change_share"] == round(2 / 3, 4)
    assert out["max_abs_score_delta"] == 0.6
    assert out["top_movers"][0]["symbol"] == "CC"


def test_rows_without_shadow_and_broken_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps(_payload(
        [{"symbol": "XX"}, _row("AA", "NEUTRAL", 0.0)],
    )), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    out = summarize(sorted(tmp_path.glob("*.json")))
    assert out["rows"] == 1
    assert out["files_scanned"] == 2
    assert out["files_with_shadow_rows"] == 1
    assert out["non_neutral_share"] == 0.0
    assert out["top_movers"] == []


def test_empty_input_is_honest_not_zeroed(tmp_path: Path) -> None:
    out = summarize([])
    assert out["rows"] == 0
    assert out["non_neutral_share"] is None
    assert out["mean_abs_score_delta"] is None
