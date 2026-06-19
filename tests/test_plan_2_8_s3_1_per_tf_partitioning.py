"""Pin-test for Plan 2.8 S3.1 per-TF artifact partitioning.

Phase 1 of the addendum rollout asks for verification that per-TF
scoring artifacts are persisted distinctly for each chart-TF in the
expanded set {5m, 15m, 1H, 4H}. This test pins:

  * the output-dir layout is <root>/<symbol>/<tf_token>,
  * `_path_token` is stable under the exact TF strings used by
    `RELEASE_REFERENCE_TIMEFRAMES`,
    * all seven TFs partition to distinct directories (no collisions).

Regressions here would silently merge cross-TF events into a single
bucket and break per-chart_tf calibration exactly at the layer the
addendum is designed to strengthen.
"""

from __future__ import annotations

from pathlib import Path

from scripts.run_smc_measurement_benchmark import _pair_output_dir, _path_token
from smc_integration.release_policy import RELEASE_REFERENCE_TIMEFRAMES


def test_path_token_stable_for_all_release_tfs() -> None:
    # All canonical TFs must pass through _path_token unchanged (no slashes
    # or spaces in the canonical strings).
    for tf in RELEASE_REFERENCE_TIMEFRAMES:
        assert _path_token(tf) == tf


def test_pair_output_dir_partitions_per_tf() -> None:
    root = Path("/tmp/bench")
    dirs = {
        tf: _pair_output_dir(root, symbol="AAPL", timeframe=tf)
        for tf in RELEASE_REFERENCE_TIMEFRAMES
    }
    # Expect seven distinct directories.
    assert len({str(p) for p in dirs.values()}) == 7
    assert dirs["5m"] == root / "AAPL" / "5m"
    assert dirs["10m"] == root / "AAPL" / "10m"
    assert dirs["15m"] == root / "AAPL" / "15m"
    assert dirs["30m"] == root / "AAPL" / "30m"
    assert dirs["1H"] == root / "AAPL" / "1H"
    assert dirs["4H"] == root / "AAPL" / "4H"
    assert dirs["1D"] == root / "AAPL" / "1D"


def test_pair_output_dir_partitions_per_symbol() -> None:
    root = Path("/tmp/bench")
    a = _pair_output_dir(root, symbol="AAPL", timeframe="5m")
    m = _pair_output_dir(root, symbol="MSFT", timeframe="5m")
    assert a != m
    assert a.parent.name == "AAPL"
    assert m.parent.name == "MSFT"


def test_path_token_normalises_slashes_and_spaces() -> None:
    assert _path_token("FOO/BAR") == "FOO_BAR"
    assert _path_token("a b") == "a_b"
    assert _path_token("  1H  ") == "1H"
