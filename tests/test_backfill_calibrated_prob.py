"""Tests for scripts/backfill_calibrated_prob.py (Stage #5, PR 3).

Covers the pure join logic (spec -> {event_id: prob}, ledger back-fill) plus the
producer hook in ``to_build_spec`` that surfaces ``calibrated_prob_by_event``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from governance.family_returns import to_build_spec
from governance.family_walkforward import family_outcome_horizon
from scripts.backfill_calibrated_prob import (
    backfill_ledger_tree,
    calibrated_prob_map,
    main,
)
from smc_core.event_ledger import read_event_ledger, write_event_ledger


def _write_pair(root: Path, symbol: str, tf: str, source_events: list[dict]) -> None:
    pair = root / symbol / tf
    pair.mkdir(parents=True, exist_ok=True)
    write_event_ledger(
        source_events, output_path=pair / f"events_{symbol}_{tf}.jsonl", symbol=symbol, timeframe=tf
    )


def _src(event_id: str, prob: float = 0.6) -> dict:
    return {"event_id": event_id, "family": "BOS", "predicted_prob": prob,
            "outcome": True, "timestamp": 1.0}


# ── calibrated_prob_map ───────────────────────────────────────────────────────
class TestCalibratedProbMap:
    def test_merges_families(self) -> None:
        spec = {"families": {
            "BOS": {"calibrated_prob_by_event": {"a": 0.7, "b": 0.3}},
            "OB": {"calibrated_prob_by_event": {"c": 0.55}},
        }}
        assert calibrated_prob_map(spec) == {"a": 0.7, "b": 0.3, "c": 0.55}

    def test_skips_families_without_the_field(self) -> None:
        spec = {"families": {"BOS": {"brier": 0.2}, "OB": {"calibrated_prob_by_event": {"c": 0.5}}}}
        assert calibrated_prob_map(spec) == {"c": 0.5}

    def test_malformed_spec_is_empty(self) -> None:
        assert calibrated_prob_map({}) == {}
        assert calibrated_prob_map({"families": []}) == {}


# ── backfill_ledger_tree ──────────────────────────────────────────────────────
class TestBackfill:
    def test_fills_mapped_leaves_unmapped_null(self, tmp_path: Path) -> None:
        _write_pair(tmp_path, "AAPL", "1D", [_src("e1"), _src("e2")])
        stats = backfill_ledger_tree(tmp_path, {"e1": 0.83})
        assert stats == {"files": 1, "records": 2, "filled": 1}
        rows = {r["event_id"]: r for r in read_event_ledger(next(tmp_path.rglob("events_*.jsonl")))}
        assert rows["e1"]["calibrated_prob"] == 0.83   # joined
        assert rows["e2"]["calibrated_prob"] is None    # never covered -> stays null
        # the heuristic prior is untouched by the back-fill
        assert rows["e1"]["heuristic_direction_score"] == 0.6

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        _write_pair(tmp_path, "AAPL", "1D", [_src("e1")])
        path = next(tmp_path.rglob("events_*.jsonl"))
        before = path.read_text(encoding="utf-8")
        stats = backfill_ledger_tree(tmp_path, {"e1": 0.83}, dry_run=True)
        assert stats["filled"] == 1
        assert path.read_text(encoding="utf-8") == before  # unchanged

    def test_idempotent(self, tmp_path: Path) -> None:
        _write_pair(tmp_path, "AAPL", "1D", [_src("e1"), _src("e2")])
        backfill_ledger_tree(tmp_path, {"e1": 0.83})
        first = next(tmp_path.rglob("events_*.jsonl")).read_text(encoding="utf-8")
        backfill_ledger_tree(tmp_path, {"e1": 0.83})
        assert next(tmp_path.rglob("events_*.jsonl")).read_text(encoding="utf-8") == first

    def test_result_is_strict_valid(self, tmp_path: Path) -> None:
        _write_pair(tmp_path, "AAPL", "1D", [_src("e1")])
        backfill_ledger_tree(tmp_path, {"e1": 0.5})
        # strict read re-validates every row (calibrated_prob domain included)
        assert len(list(read_event_ledger(next(tmp_path.rglob("events_*.jsonl")), strict=True))) == 1


# ── CLI ───────────────────────────────────────────────────────────────────────
class TestMain:
    def test_cli_backfills(self, tmp_path: Path) -> None:
        _write_pair(tmp_path, "AAPL", "1D", [_src("e1"), _src("e2")])
        spec = tmp_path / "spec.json"
        spec.write_text(json.dumps({"families": {"BOS": {"calibrated_prob_by_event": {"e1": 0.9}}}}), encoding="utf-8")
        rc = main(["--benchmark-dir", str(tmp_path), "--spec", str(spec)])
        assert rc == 0
        rows = {r["event_id"]: r for r in read_event_ledger(next(tmp_path.rglob("events_*.jsonl")))}
        assert rows["e1"]["calibrated_prob"] == 0.9 and rows["e2"]["calibrated_prob"] is None

    def test_cli_empty_map_exit_3(self, tmp_path: Path) -> None:
        _write_pair(tmp_path, "AAPL", "1D", [_src("e1")])
        spec = tmp_path / "spec.json"
        spec.write_text(json.dumps({"families": {"BOS": {"brier": 0.2}}}), encoding="utf-8")
        assert main(["--benchmark-dir", str(tmp_path), "--spec", str(spec)]) == 3


# ── producer hook: to_build_spec surfaces calibrated_prob_by_event ────────────
_BAR = 900.0
_BASE_TS = 1_700_000_000.0


def _triggering_bos_event(event_id: str, *, index: int, win: bool) -> dict[str, Any]:
    """A BOS event that triggers (return exists) and carries a discriminating score.

    Events are spaced far apart (``index * 50`` bars) so each event's label+embargo
    guard window resolves well before the next event — otherwise the walk-forward
    purge would drop every training event and no calibration block would form.
    """
    horizon = family_outcome_horizon("BOS")
    n = horizon + 3
    anchor_ts = _BASE_TS + index * 50 * _BAR
    step = 0.6 if win else -0.6
    return {
        "family": "BOS",
        "event_id": event_id,
        "direction": "BULL",
        "zone_low": 100.0,
        "zone_high": 101.0,
        "anchor_ts": anchor_ts,
        "forward_lows": [100.5] + [102.0 + i for i in range(n - 1)],
        "forward_highs": [101.0] + [103.0 + i for i in range(n - 1)],
        "forward_closes": [100.8 + step * i for i in range(n)],
        "forward_timestamps": [anchor_ts + (j + 1) * _BAR for j in range(n)],
        "score": 2.0 if win else 0.5,  # score discriminates the outcome
    }


def test_to_build_spec_surfaces_calibrated_prob_by_event() -> None:
    # 80 alternating win/loss BOS events -> the walk-forward calibrator fits and
    # emits event_id-aligned OOS probs, which to_build_spec surfaces per family.
    events = [
        _triggering_bos_event(f"bos-{i}", index=i, win=(i % 2 == 0))
        for i in range(80)
    ]
    spec = to_build_spec(events, periods_per_year=252)
    by_event = spec["families"]["BOS"].get("calibrated_prob_by_event")
    assert isinstance(by_event, dict) and by_event
    # ids are a subset of the inputs; values are probabilities
    assert set(by_event) <= {f"bos-{i}" for i in range(80)}
    assert all(0.0 <= p <= 1.0 for p in by_event.values())
