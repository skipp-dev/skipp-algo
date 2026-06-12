"""Schema + CLI scaffolding tests for the SMC strategy snapshot harness (#2353).

These tests always run (they do not depend on the Python mirror), and pin:

- The fixture file layout under ``tests/fixtures/smc_strategy/``.
- The exit-code contract of ``scripts/regen_smc_strategy_fixtures.py``
  while the mirror under ``python/strategies/smc_mirror/`` does not exist.

Once the mirror lands the second test will need to be reworked (or
gated behind ``importlib.util.find_spec``); leaving it as-is gives a
loud signal that the scaffolding has caught up with reality.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from scripts.regen_smc_strategy_fixtures import (
    EXIT_MIRROR_MISSING,
    FIXTURE_ROOT,
    KNOWN_STRATEGIES,
    SIGNAL_FLOAT_COLS,
    SIGNAL_STRING_COLS,
)
from scripts.regen_smc_strategy_fixtures import (
    main as regen_main,
)

_EXPECTED_INPUT_COLS = ("bar_index", "timestamp", "open", "high", "low", "close", "volume")
_EXPECTED_SIGNAL_COLS = ("bar_index", *SIGNAL_STRING_COLS, *SIGNAL_FLOAT_COLS)
_VALID_SIGNALS = {"LONG_ENTRY", "LONG_EXIT", "SHORT_ENTRY", "SHORT_EXIT", "NONE"}


@pytest.mark.parametrize("strategy", KNOWN_STRATEGIES)
def test_fixture_pair_exists_and_aligns(strategy: str) -> None:
    in_path = FIXTURE_ROOT / f"{strategy}_input.csv"
    exp_path = FIXTURE_ROOT / f"{strategy}_expected_signals.csv"
    assert in_path.exists(), f"missing input fixture: {in_path}"
    assert exp_path.exists(), f"missing expected fixture: {exp_path}"

    with in_path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = tuple(next(reader))
        rows = list(reader)
    assert header == _EXPECTED_INPUT_COLS, f"{in_path}: header drift, got {header}"
    assert [int(r[0]) for r in rows] == list(range(len(rows))), (
        f"{in_path}: bar_index must be 0..N-1 contiguous"
    )

    with exp_path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        exp_header = tuple(next(reader))
        exp_rows = list(reader)
    assert exp_header == _EXPECTED_SIGNAL_COLS, f"{exp_path}: header drift, got {exp_header}"
    assert len(exp_rows) == len(rows), (
        f"row count mismatch: input={len(rows)} expected_signals={len(exp_rows)}"
    )
    bad = {r[1] for r in exp_rows} - _VALID_SIGNALS
    assert not bad, f"{exp_path}: unknown signal_type values: {sorted(bad)}"


def _mirror_present() -> bool:
    try:
        return importlib.util.find_spec("python.strategies.smc_mirror") is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(
    _mirror_present(),
    reason="mirror exists — this contract is for the scaffolding-only state",
)
def test_regen_cli_exits_two_while_mirror_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = regen_main(["--strategy", KNOWN_STRATEGIES[0]])
    assert rc == EXIT_MIRROR_MISSING
    err = capsys.readouterr().err
    assert "#2353" in err
    assert "smc_mirror" in err


def test_regen_cli_rejects_unknown_strategy() -> None:
    with pytest.raises(SystemExit):
        regen_main(["--strategy", "definitely-not-a-strategy"])


def test_scripts_directory_module_path_on_sys_path() -> None:
    """Sanity check so the CLI import in this file does not break in CI."""
    assert any(
        Path(entry).resolve() == Path(__file__).resolve().parents[1]
        for entry in sys.path
    ), "tests/ root should be reachable on sys.path for the regen CLI import"
