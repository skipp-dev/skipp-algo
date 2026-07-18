import pandas as pd

from scripts.compare_databento_daily_parity import compare


def _sample() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": f"S{symbol}",
                "trade_date": f"2026-07-{day:02d}",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 1000,
            }
            for symbol in range(10)
            for day in range(1, 11)
        ]
    )


def test_complete_10_by_10_sample_is_ready() -> None:
    sample = _sample()
    report = compare(sample, sample.copy())
    assert report["minimum_10x10_met"] is True
    assert report["matched_rows"] == 100
    assert report["deltas"]["close"]["max_absolute"] == 0.0


def test_missing_candidate_row_is_visible() -> None:
    sample = _sample()
    report = compare(sample, sample.iloc[:-1].copy())
    assert report["reference_only_rows"] == 1
    assert report["status"] == "insufficient_evidence"


def test_dimensions_alone_do_not_fake_a_complete_sample() -> None:
    sample = _sample()
    report = compare(sample, sample.iloc[[0]].copy())
    assert report["minimum_10x10_met"] is True
    assert report["matched_10x10_met"] is False
    assert report["status"] == "insufficient_evidence"
