"""Tests for scripts/eval_sweep_trap_shadow.py (WS4a shadow evaluator)."""
from __future__ import annotations

import json

import pytest

from governance.family_calibration import MIN_OOS_SAMPLES
from scripts.eval_sweep_trap_shadow import (
    MIN_SHADOW_SAMPLES,
    collect_samples,
    evaluate,
    events_content_hash,
    load_ledger,
    main,
    merge_row,
)


def _sweep(q: float, outcome: int) -> dict:
    # Leakage-free: the label lives in features as the disjoint late outcome; the
    # top-level ``outcome`` (full-window) is intentionally NOT what the eval reads.
    return {
        "family": "SWEEP",
        "outcome": bool(outcome),
        "features": {"sweep_trap_quality_score": q, "sweep_trap_outcome_late": bool(outcome)},
    }


def _skillful(n_each: int) -> list[dict]:
    # High quality → reverses; low quality → doesn't. A perfectly discriminating score.
    return [_sweep(0.9, 1) for _ in range(n_each)] + [_sweep(0.2, 0) for _ in range(n_each)]


class TestCollectSamples:
    def test_filters_family_and_missing_score(self) -> None:
        events = [
            _sweep(0.8, 1),
            {"family": "FVG", "outcome": True,
             "features": {"sweep_trap_quality_score": 0.9, "sweep_trap_outcome_late": True}},  # wrong family
            {"family": "SWEEP", "outcome": True, "features": {}},  # no score
            {"family": "SWEEP", "outcome": False,
             "features": {"sweep_trap_quality_score": 1.5, "sweep_trap_outcome_late": False}},  # out of range
            # Pre-leakage-fix record: has the score but no disjoint late outcome -> excluded.
            {"family": "SWEEP", "outcome": True, "features": {"sweep_trap_quality_score": 0.7}},
        ]
        assert collect_samples(events) == [(0.8, 1)]

    def test_late_outcome_is_the_label_not_full_window_outcome(self) -> None:
        # Top-level full-window outcome disagrees with the disjoint late outcome;
        # the evaluator must use the late outcome (leakage-free contract).
        ev = {
            "family": "SWEEP",
            "outcome": True,  # full-window reversal hit (would be leaky)
            "features": {"sweep_trap_quality_score": 0.6, "sweep_trap_outcome_late": False},
        }
        assert collect_samples([ev]) == [(0.6, 0)]


class TestEvaluate:
    def test_skillful_score_is_promotable(self) -> None:
        m = evaluate([(q, o) for e in _skillful(25) for q, o in [(e["features"]["sweep_trap_quality_score"], int(e["outcome"]))]])
        assert m["n_samples"] == 50
        assert m["brier_delta"] > 0.0        # signal beats the base-rate
        assert m["lift"] == pytest.approx(1.0)  # top tercile all hit, bottom none
        assert m["verdict"] == "PROMOTABLE"

    def test_no_skill_is_shadow(self) -> None:
        # Quality uncorrelated with outcome (all q=0.5, half reverse) → no skill.
        samples = [(0.5, i % 2) for i in range(MIN_OOS_SAMPLES + 10)]
        m = evaluate(samples)
        assert m["brier_delta"] == pytest.approx(0.0, abs=1e-9)
        assert m["verdict"] == "SHADOW"

    def test_thin_is_inconclusive(self) -> None:
        m = evaluate([(0.9, 1), (0.2, 0)] * 5)  # 10 < MIN_SHADOW_SAMPLES
        assert m["n_samples"] == 10
        assert m["verdict"] == "INCONCLUSIVE"

    def test_shadow_sample_floor_is_local_not_borrowed_oos(self) -> None:
        # The gate is a pooled-shadow SAMPLE-COUNT floor (its own constant), not a
        # walk-forward OOS guarantee. It equals MIN_OOS_SAMPLES numerically but is
        # decoupled so a future real-OOS gate can raise it independently.
        assert MIN_SHADOW_SAMPLES == 40 == MIN_OOS_SAMPLES
        just_below = evaluate([(0.9, 1), (0.2, 0)] * (MIN_SHADOW_SAMPLES // 2 - 1))
        assert just_below["n_samples"] == MIN_SHADOW_SAMPLES - 2
        assert just_below["verdict"] == "INCONCLUSIVE"

    def test_empty(self) -> None:
        m = evaluate([])
        assert m["n_samples"] == 0 and m["verdict"] == "INCONCLUSIVE" and m["brier_delta"] is None


class TestLedger:
    def test_merge_is_idempotent_on_date_hash(self) -> None:
        r1 = {"date": "2026-07-11", "events_hash": "aaa", "verdict": "SHADOW"}
        r1b = {"date": "2026-07-11", "events_hash": "aaa", "verdict": "PROMOTABLE"}
        merged = merge_row([r1], r1b)
        assert merged == [r1b]  # latest wins, no dup

    def test_load_ledger_fails_closed_on_corruption(self, tmp_path) -> None:
        p = tmp_path / "led.jsonl"
        p.write_text('{"date":"2026-07-11"}\nnot-json\n', encoding="utf-8")
        with pytest.raises(ValueError, match="corrupt"):
            load_ledger(p)

    def test_load_missing_is_cold_start(self, tmp_path) -> None:
        assert load_ledger(tmp_path / "nope.jsonl") == []


class TestMainEndToEnd:
    def _run(self, tmp_path, events, date="2026-07-11"):
        ejson = tmp_path / "events.json"
        ejson.write_text(json.dumps(events), encoding="utf-8")
        ledger = tmp_path / "shadow.jsonl"
        snap = tmp_path / "snap.json"
        rc = main(["--events-json", str(ejson), "--ledger", str(ledger), "--snapshot", str(snap), "--date", date])
        return rc, ledger, snap

    def test_promotable_writes_ledger_and_snapshot(self, tmp_path) -> None:
        rc, ledger, snap = self._run(tmp_path, _skillful(25))
        assert rc == 0
        rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
        assert len(rows) == 1 and rows[0]["verdict"] == "PROMOTABLE"
        s = json.loads(snap.read_text())
        assert s["verdict_code"] == 2 and s["n_samples"] == 50 and s["brier_delta"] > 0
        assert s["min_samples"] == MIN_SHADOW_SAMPLES  # snapshot carries the local floor

    def test_benchmark_dir_fails_closed_on_corrupt_line(self, tmp_path) -> None:
        # A truncated/off-schema event line in the production benchmark-dir corpus
        # must fail closed (exit 1), never silently grade a partial corpus into a
        # verdict. strict=True in _read_events_from_dir activates main()'s handler.
        pair = tmp_path / "AAPL" / "5m"
        pair.mkdir(parents=True)
        (pair / "events_AAPL_5m.jsonl").write_text("{ this is not valid json\n", encoding="utf-8")
        snap = tmp_path / "snap.json"
        ledger = tmp_path / "shadow.jsonl"
        rc = main(["--benchmark-dir", str(tmp_path), "--ledger", str(ledger),
                   "--snapshot", str(snap), "--date", "2026-07-11"])
        assert rc == 1
        assert not snap.exists()  # no verdict snapshot written

    def test_no_data_exit_3(self, tmp_path) -> None:
        rc, ledger, _ = self._run(tmp_path, [{"family": "FVG", "outcome": True, "features": {}}])
        assert rc == 3
        assert not ledger.exists()  # nothing appended

    def test_stale_feed_appends_nothing(self, tmp_path) -> None:
        events = _skillful(25)
        # First run on an EARLIER date populates the ledger.
        self._run(tmp_path, events, date="2026-07-10")
        # Same events, later date → stale feed (hash already graded earlier) → rc 5, no new row.
        ejson = tmp_path / "events.json"
        ejson.write_text(json.dumps(events), encoding="utf-8")
        ledger = tmp_path / "shadow.jsonl"
        rc = main(["--events-json", str(ejson), "--ledger", str(ledger),
                   "--snapshot", str(tmp_path / "s.json"), "--date", "2026-07-11"])
        assert rc == 5
        rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
        assert len(rows) == 1 and rows[0]["date"] == "2026-07-10"

    def test_events_hash_stable(self) -> None:
        a = [(0.9, 1), (0.2, 0)]
        assert events_content_hash(a) == events_content_hash(list(reversed(a)))
