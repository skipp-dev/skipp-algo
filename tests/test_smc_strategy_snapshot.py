"""Snapshot tests for the SMC strategy Python mirror (#2353).

The mirror under ``python/strategies/smc_mirror/`` does not exist yet
(2026-05-25). These tests are skipped at collection time until the
mirror is published; once it is, the skip guard at the top of the
module is removed and the rest of the file is exercised verbatim.

The contract pinned here is documented in
`tests/fixtures/smc_strategy/README.md`:

- ``bar_index`` and ``signal_type`` are compared exactly.
- ``sl``, ``tp``, ``confidence`` are compared with
  ``np.allclose(rtol=1e-9, atol=1e-9, equal_nan=True)``.

Reference: Re-audit F4 / issue #2353.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "smc_strategy"
SIGNAL_STRING_COLS = ("signal_type",)
SIGNAL_FLOAT_COLS = ("sl", "tp", "confidence")
VALID_SIGNALS = frozenset({"LONG_ENTRY", "LONG_EXIT", "SHORT_ENTRY", "SHORT_EXIT", "NONE"})

# Strategies that ship a fixture pair. Add a new entry when a strategy's
# Python mirror lands and its expected_signals.csv is generated.
STRATEGIES = ("long_strategy",)


def _mirror_available() -> bool:
    try:
        return importlib.util.find_spec("python.strategies.smc_mirror") is not None
    except ModuleNotFoundError:
        return False


_MIRROR_AVAILABLE = _mirror_available()

pytestmark = pytest.mark.skipif(
    not _MIRROR_AVAILABLE,
    reason="python/strategies/smc_mirror not implemented yet (#2353)",
)


def _load_input(strategy: str) -> pd.DataFrame:
    path = FIXTURE_ROOT / f"{strategy}_input.csv"
    frame = pd.read_csv(path)
    assert list(frame["bar_index"]) == list(range(len(frame))), (
        f"{path}: bar_index must be 0..N-1 contiguous"
    )
    return frame


def _load_expected(strategy: str) -> pd.DataFrame:
    path = FIXTURE_ROOT / f"{strategy}_expected_signals.csv"
    frame = pd.read_csv(path)
    bad = set(frame["signal_type"].unique()) - VALID_SIGNALS
    assert not bad, f"{path}: unknown signal_type values: {sorted(bad)}"
    return frame


def _run_mirror(strategy: str, input_frame: pd.DataFrame) -> pd.DataFrame:
    """Dispatch to the strategy's Python mirror entrypoint."""
    from python.strategies import smc_mirror  # type: ignore[import-not-found]

    runner = getattr(smc_mirror, f"run_{strategy}")
    return runner(input_frame)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_smc_strategy_snapshot_matches_fixture(strategy: str) -> None:
    input_frame = _load_input(strategy)
    expected = _load_expected(strategy)
    actual = _run_mirror(strategy, input_frame)

    assert list(actual.columns) >= [*SIGNAL_STRING_COLS, *SIGNAL_FLOAT_COLS, "bar_index"], (
        f"mirror output missing columns; got {list(actual.columns)}"
    )
    assert len(actual) == len(expected), (
        f"row count mismatch: actual={len(actual)} expected={len(expected)}"
    )
    assert list(actual["bar_index"]) == list(expected["bar_index"]), "bar_index drift"
    for col in SIGNAL_STRING_COLS:
        mismatch = actual[col].astype(str).values != expected[col].astype(str).values
        assert not mismatch.any(), (
            f"{col} mismatch at bar_index="
            f"{actual.loc[mismatch, 'bar_index'].tolist()[:10]}"
        )
    for col in SIGNAL_FLOAT_COLS:
        if not np.allclose(
            actual[col].to_numpy(dtype=float),
            expected[col].to_numpy(dtype=float),
            rtol=1e-9,
            atol=1e-9,
            equal_nan=True,
        ):
            diffs = np.abs(
                actual[col].to_numpy(dtype=float) - expected[col].to_numpy(dtype=float)
            )
            worst = int(np.nanargmax(diffs))
            pytest.fail(
                f"{col} diverged beyond rtol=atol=1e-9; "
                f"worst bar_index={int(actual.loc[worst, 'bar_index'])}, "
                f"actual={actual.loc[worst, col]}, expected={expected.loc[worst, col]}"
            )
