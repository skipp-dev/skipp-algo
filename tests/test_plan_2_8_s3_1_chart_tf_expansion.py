"""Structural pin-test for Plan 2.8 S3.1 Chart-TF-Expansion.

Guards the expansion to the canonical 7-TF set
{5m, 10m, 15m, 30m, 1H, 4H, 1D} for:

  * the shared release_policy.RELEASE_REFERENCE_TIMEFRAMES tuple,
  * the rolling benchmark workflow default,
  * the benchmark CLI default.

Prevents silent regressions (e.g. someone trimming back to the old
15m/1H slice) that would undo the Phase-E2 proof-point story.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.run_smc_measurement_benchmark import build_parser
from smc_integration.release_policy import RELEASE_REFERENCE_TIMEFRAMES

REPO = Path(__file__).resolve().parents[1]
ROLLING_WF = REPO / ".github" / "workflows" / "smc-measurement-benchmark-rolling.yml"


def test_release_reference_tuple_contains_the_canonical_seven_tfs() -> None:
    assert RELEASE_REFERENCE_TIMEFRAMES == ("5m", "10m", "15m", "30m", "1H", "4H", "1D")


def test_benchmark_cli_default_covers_all_seven_tfs() -> None:
    parser = build_parser()
    ns = parser.parse_args([])
    tfs = [tf.strip() for tf in ns.timeframes.split(",")]
    assert tfs == ["5m", "10m", "15m", "30m", "1H", "4H", "1D"]


def test_rolling_workflow_default_timeframes_covers_all_seven() -> None:
    wf = yaml.safe_load(ROLLING_WF.read_text(encoding="utf-8"))
    inputs = wf.get("on", wf.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["timeframes"]["default"] == "5m,10m,15m,30m,1H,4H,1D"


def test_rolling_workflow_run_step_fallback_covers_all_seven() -> None:
    text = ROLLING_WF.read_text(encoding="utf-8")
    # The shell fallback when inputs.timeframes is empty must point at
    # the canonical 7-TF default, not older reduced defaults.
    assert "|| '5m,10m,15m,30m,1H,4H,1D'" in text
    assert "|| '5m,15m,1H,4H'" not in text
    assert "|| '15m,1H'" not in text
    # No stray leftover default anywhere in the file.
    assert not re.search(r'default:\s*"15m,1H"', text)
