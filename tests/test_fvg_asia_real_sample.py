from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from scripts import fvg_asia_real_sample as sample


def test_process_symbol_classifies_fvg_from_timezone_aware_anchor(monkeypatch) -> None:
    anchor = datetime(2026, 7, 17, 0, 0, tzinfo=UTC)
    bars = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "timestamp": [anchor, anchor + timedelta(minutes=5), anchor + timedelta(minutes=10)],
            "high": [102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
        }
    )
    monkeypatch.setattr(
        sample,
        "build_fvg_from_bars",
        lambda *_args, **_kwargs: [
            {
                "anchor_ts": anchor.timestamp(),
                "low": 100.0,
                "high": 101.0,
                "dir": "BULL",
            }
        ],
    )
    monkeypatch.setattr(sample, "_label_fvg", lambda **_kwargs: (True, False))

    events = sample._process_symbol_tf(bars_5m=bars, symbol="AAPL", timeframe="5m")

    assert len(events) == 1
    assert events[0]["session"] == "ASIA"
