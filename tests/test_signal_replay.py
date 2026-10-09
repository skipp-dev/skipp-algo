"""Tests for B7 Signal Replay — outcome data loading and hit-rate computation."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from open_prep.outcomes import (
    _load_outcomes_range,
    compute_hit_rates,
    store_daily_outcomes,
)


@pytest.fixture()
def outcomes_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect OUTCOMES_DIR to a temp directory."""
    import open_prep.outcomes as mod

    d = tmp_path / "outcomes"
    d.mkdir()
    monkeypatch.setattr(mod, "OUTCOMES_DIR", d)
    return d


def _make_records(
    n: int = 3,
    profitable: bool | None = True,
    pnl: float = 1.5,
    gap_pct: float = 2.0,
    rvol: float = 1.5,
    regime: str = "RISK_ON",
) -> list[dict]:
    return [
        {
            "date": "2026-04-20",
            "symbol": f"SYM{i}",
            "gap_pct": gap_pct + i * 0.5,
            "rvol": rvol,
            "score": 0.5 + i * 0.1,
            "confidence_tier": "STANDARD",
            "gap_bucket_label": "medium",
            "rvol_bucket_label": "normal",
            "regime": regime,
            "profitable_30m": profitable,
            "pnl_30m_pct": pnl if profitable is not None else None,
        }
        for i in range(n)
    ]


class TestLoadOutcomesRange:
    def test_returns_empty_when_no_dir(self, outcomes_dir: Path) -> None:
        import shutil
        shutil.rmtree(outcomes_dir)
        assert _load_outcomes_range(5) == []

    def test_loads_records_from_single_file(self, outcomes_dir: Path) -> None:
        (outcomes_dir / "outcomes_2026-04-20.json").write_text(
            json.dumps(_make_records(2)), encoding="utf-8"
        )
        result = _load_outcomes_range(5)
        assert len(result) == 2
        assert result[0]["symbol"] == "SYM0"

    def test_respects_lookback_limit(self, outcomes_dir: Path) -> None:
        for i in range(5):
            (outcomes_dir / f"outcomes_2026-04-{20 - i:02d}.json").write_text(
                json.dumps(_make_records(1)), encoding="utf-8"
            )
        assert len(_load_outcomes_range(2)) == 2
        assert len(_load_outcomes_range(5)) == 5

    def test_skips_corrupt_files(self, outcomes_dir: Path) -> None:
        (outcomes_dir / "outcomes_2026-04-20.json").write_text("NOT JSON", encoding="utf-8")
        (outcomes_dir / "outcomes_2026-04-19.json").write_text(
            json.dumps(_make_records(1)), encoding="utf-8"
        )
        result = _load_outcomes_range(5)
        assert len(result) == 1


class TestComputeHitRates:
    def test_empty_returns_empty(self, outcomes_dir: Path) -> None:
        assert compute_hit_rates(5) == {}

    def test_computes_rate_for_single_bucket(self, outcomes_dir: Path) -> None:
        records = _make_records(4, profitable=True, pnl=2.0, gap_pct=3.0, rvol=1.5)
        records.append({**records[0], "profitable_30m": False, "pnl_30m_pct": -1.0, "symbol": "LOSER"})
        (outcomes_dir / "outcomes_2026-04-20.json").write_text(
            json.dumps(records), encoding="utf-8"
        )
        rates = compute_hit_rates(5)
        assert len(rates) > 0
        for _key, data in rates.items():
            assert "hit_rate" in data
            assert "total" in data
            assert "avg_pnl_pct" in data

    def test_multiple_buckets_are_separated(self, outcomes_dir: Path) -> None:
        r1 = {"date": "2026-04-20", "symbol": "A", "gap_pct": 0.5, "rvol": 0.5,
               "score": 1, "profitable_30m": True, "pnl_30m_pct": 1.0}
        r2 = {"date": "2026-04-20", "symbol": "B", "gap_pct": 8.0, "rvol": 3.0,
               "score": 1, "profitable_30m": False, "pnl_30m_pct": -2.0}
        (outcomes_dir / "outcomes_2026-04-20.json").write_text(
            json.dumps([r1, r2]), encoding="utf-8"
        )
        rates = compute_hit_rates(5)
        assert len(rates) == 2


class TestStoreOutcomes:
    def test_stores_and_loads_round_trip(self, outcomes_dir: Path) -> None:
        records = _make_records(3)
        path = store_daily_outcomes(date(2026, 4, 20), records)
        assert path.exists()
        loaded = _load_outcomes_range(5)
        assert len(loaded) == 3
        assert loaded[0]["symbol"] == "SYM0"

    def test_rotation_removes_old_files(self, outcomes_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPEN_PREP_OUTCOME_RETENTION_DAYS", "7")
        for i in range(10):
            store_daily_outcomes(date(2026, 4, 11 + i), _make_records(1))
        files = sorted(outcomes_dir.glob("outcomes_*.json"))
        assert len(files) <= 7


class TestSignalReplayTabData:
    """Integration-level tests that validate the data transformations
    the Signal Replay tab performs on loaded outcome records."""

    def test_aggregate_metrics(self, outcomes_dir: Path) -> None:
        winners = _make_records(3, profitable=True, pnl=2.0)
        losers = _make_records(2, profitable=False, pnl=-1.0)
        pending = _make_records(1, profitable=None)
        all_records = winners + losers + pending
        (outcomes_dir / "outcomes_2026-04-20.json").write_text(
            json.dumps(all_records), encoding="utf-8"
        )
        records = _load_outcomes_range(5)
        with_outcome = [r for r in records if r.get("profitable_30m") is not None]
        win_count = sum(1 for r in with_outcome if r.get("profitable_30m") is True)
        hit_rate = win_count / len(with_outcome) if with_outcome else 0.0
        pnl_vals = [float(r.get("pnl_30m_pct") or 0) for r in with_outcome]
        avg_pnl = sum(pnl_vals) / len(pnl_vals) if pnl_vals else 0.0

        assert len(records) == 6
        assert len(with_outcome) == 5
        assert hit_rate == pytest.approx(0.6)
        assert avg_pnl == pytest.approx(0.8)

    def test_daily_grouping(self, outcomes_dir: Path) -> None:
        r1 = _make_records(2, profitable=True, pnl=1.0)
        for r in r1:
            r["date"] = "2026-04-19"
        r2 = _make_records(3, profitable=False, pnl=-0.5)
        for r in r2:
            r["date"] = "2026-04-20"
        (outcomes_dir / "outcomes_2026-04-20.json").write_text(
            json.dumps(r2), encoding="utf-8"
        )
        (outcomes_dir / "outcomes_2026-04-19.json").write_text(
            json.dumps(r1), encoding="utf-8"
        )
        records = _load_outcomes_range(5)
        by_date: dict[str, list] = {}
        for r in records:
            by_date.setdefault(str(r.get("date", "")), []).append(r)
        assert len(by_date) == 2
        assert len(by_date["2026-04-19"]) == 2
        assert len(by_date["2026-04-20"]) == 3
