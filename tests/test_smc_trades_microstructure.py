"""Unit tests for :mod:`scripts.smc_trades_microstructure` (WP-I).

All tests operate on synthetic in-memory tables -- no Databento network I/O.
"""

from __future__ import annotations

from collections import namedtuple

import pandas as pd
import pytest

from scripts.smc_trades_microstructure import (
    MICROSTRUCTURE_KEYS,
    aggregate_trades_microstructure,
)

_Trade = namedtuple("_Trade", ["size", "side"])


def _df(rows: list[tuple[int, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["size", "side"])


def test_keys_present_and_typed() -> None:
    result = aggregate_trades_microstructure(_df([(10, "A"), (5, "B")]))
    assert set(result) == set(MICROSTRUCTURE_KEYS)
    assert isinstance(result["buy_volume_pct"], float)
    assert isinstance(result["avg_trade_size"], float)
    assert isinstance(result["total_size"], int)
    assert isinstance(result["n_trades"], int)


def test_buy_heavy_tape() -> None:
    result = aggregate_trades_microstructure(_df([(80, "A"), (20, "B")]))
    assert result["buy_volume_pct"] == 80.0
    assert result["buy_size"] == 80
    assert result["sell_size"] == 20
    assert result["total_size"] == 100
    assert result["n_trades"] == 2
    assert result["avg_trade_size"] == 50.0


def test_sell_heavy_tape() -> None:
    result = aggregate_trades_microstructure(_df([(10, "A"), (90, "B")]))
    assert result["buy_volume_pct"] == 10.0
    assert result["buy_size"] == 10
    assert result["sell_size"] == 90


def test_balanced_tape_is_fifty() -> None:
    result = aggregate_trades_microstructure(_df([(25, "A"), (25, "B")]))
    assert result["buy_volume_pct"] == 50.0


def test_neutral_side_excluded_from_pct_but_counted_in_size() -> None:
    # A 'N' (no aggressor) trade must not skew the buy/sell split, but its
    # volume still belongs to the tape so avg_trade_size reflects it.
    result = aggregate_trades_microstructure(
        _df([(40, "A"), (10, "B"), (50, "N")])
    )
    # Directional split: 40 buy / 10 sell -> 80%.
    assert result["buy_volume_pct"] == 80.0
    assert result["buy_size"] == 40
    assert result["sell_size"] == 10
    # avg_trade_size over all 3 trades: (40+10+50)/3.
    assert result["n_trades"] == 3
    assert result["total_size"] == 100
    assert result["avg_trade_size"] == pytest.approx(100 / 3, rel=1e-6)


def test_no_directional_volume_defaults_to_neutral() -> None:
    # Only neutral trades -> no buy/sell -> neutral 50.0 (never fabricate bias).
    result = aggregate_trades_microstructure(_df([(30, "N"), (70, "N")]))
    assert result["buy_volume_pct"] == 50.0
    assert result["buy_size"] == 0
    assert result["sell_size"] == 0
    assert result["total_size"] == 100
    assert result["avg_trade_size"] == 50.0


def test_empty_dataframe() -> None:
    result = aggregate_trades_microstructure(pd.DataFrame(columns=["size", "side"]))
    assert result == {
        "buy_volume_pct": 50.0,
        "avg_trade_size": 0.0,
        "total_size": 0,
        "n_trades": 0,
        "buy_size": 0,
        "sell_size": 0,
    }


def test_none_input() -> None:
    assert aggregate_trades_microstructure(None)["buy_volume_pct"] == 50.0
    assert aggregate_trades_microstructure(None)["n_trades"] == 0


def test_dataframe_without_side_column() -> None:
    # Size-only frame: no directional info -> neutral pct, full size accounting.
    df = pd.DataFrame({"size": [10, 20, 30]})
    result = aggregate_trades_microstructure(df)
    assert result["buy_volume_pct"] == 50.0
    assert result["n_trades"] == 3
    assert result["total_size"] == 60
    assert result["avg_trade_size"] == 20.0


def test_dataframe_with_nan_sizes() -> None:
    df = pd.DataFrame({"size": [10, None, 30], "side": ["A", "A", "B"]})
    result = aggregate_trades_microstructure(df)
    # NaN size coerced to 0; buy = 10 (+0), sell = 30.
    assert result["buy_size"] == 10
    assert result["sell_size"] == 30
    assert result["total_size"] == 40
    assert result["n_trades"] == 3


def test_iterable_of_records_path() -> None:
    records = [_Trade(60, "A"), _Trade(40, "B"), _Trade(100, "N")]
    result = aggregate_trades_microstructure(records)
    assert result["buy_volume_pct"] == 60.0
    assert result["buy_size"] == 60
    assert result["sell_size"] == 40
    assert result["total_size"] == 200
    assert result["n_trades"] == 3


def test_iterable_empty() -> None:
    result = aggregate_trades_microstructure([])
    assert result["buy_volume_pct"] == 50.0
    assert result["n_trades"] == 0


def test_iterable_skips_records_without_size() -> None:
    Bad = namedtuple("Bad", ["side"])
    records = [_Trade(50, "A"), Bad("B")]
    result = aggregate_trades_microstructure(records)
    # The size-less record is skipped entirely.
    assert result["n_trades"] == 1
    assert result["buy_size"] == 50
    assert result["total_size"] == 50


def test_determinism_repeated_calls() -> None:
    df = _df([(11, "A"), (7, "B"), (3, "N")])
    first = aggregate_trades_microstructure(df)
    second = aggregate_trades_microstructure(df)
    assert first == second
