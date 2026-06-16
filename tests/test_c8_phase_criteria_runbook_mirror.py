"""Pin the runbook ↔ code mirror for C8 phase-pass criteria.

C-sprint deep-review MAJOR finding: ``docs/c8_live_incubation_runbook.md``
prescribes numeric thresholds for promoting between paper / live_small /
live_full, but those numbers existed only as prose. Drift between the
runbook and the production runner was therefore invisible until a human
read both.

This test parses the runbook for each Phase's "Pass criteria" block and
asserts the documented numeric thresholds match the
``PHASE_*_CRITERIA`` dataclasses exported from
``scripts.run_smc_live_incubation``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.run_smc_live_incubation import (
    PHASE_A_CRITERIA,
    PHASE_B_CRITERIA,
    PHASE_C_CRITERIA,
    PHASE_PASS_CRITERIA,
    PhasePassCriteria,
)

RUNBOOK_PATH = Path(__file__).resolve().parent.parent / "docs" / "c8_live_incubation_runbook.md"


def _runbook_text() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def _phase_section(text: str, header: str) -> str:
    """Extract a single Phase-X section between ``## Phase-X`` and the
    next top-level ``## `` heading or end-of-file.
    """
    pattern = re.compile(
        rf"^## {re.escape(header)}.*?(?=^## |\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    assert m is not None, f"could not find section starting with '## {header}' in runbook"
    return m.group(0)


# ---------------------------------------------------------------------------
# Static surface: dataclass + registry shape.
# ---------------------------------------------------------------------------


def test_phase_pass_criteria_dataclass_is_frozen() -> None:
    c = PhasePassCriteria(
        phase="paper",
        min_phase_days=1,
        min_trades_closed=1,
        max_drift_score_deviation=None,
        min_drift_score=None,
        require_drift_verdict_in=(),
    )
    with pytest.raises((AttributeError, TypeError)):
        c.phase = "live_small"  # type: ignore[misc]


def test_phase_registry_maps_all_phases() -> None:
    assert set(PHASE_PASS_CRITERIA) == {"paper", "live_small", "live_full"}
    assert PHASE_PASS_CRITERIA["paper"] is PHASE_A_CRITERIA
    assert PHASE_PASS_CRITERIA["live_small"] is PHASE_B_CRITERIA
    assert PHASE_PASS_CRITERIA["live_full"] is PHASE_C_CRITERIA


# ---------------------------------------------------------------------------
# Runbook ↔ code mirror.
# ---------------------------------------------------------------------------


def test_runbook_file_exists_and_is_utf8() -> None:
    assert RUNBOOK_PATH.exists(), f"runbook missing at {RUNBOOK_PATH}"
    text = _runbook_text()
    assert "Phase-A" in text and "Phase-B" in text


def test_phase_a_runbook_mirrors_dataclass() -> None:
    section = _phase_section(_runbook_text(), "Phase-A — Paper")
    # 4 weeks minimum
    assert "4 weeks" in section
    assert PHASE_A_CRITERIA.min_phase_days == 28
    # ≥ 45 paper trades closed (W9-8: raised from 20 for 80% power)
    assert re.search(r"≥\s*45\s+paper trades", section), section
    assert PHASE_A_CRITERIA.min_trades_closed == 45
    # |paper-Sharpe / OOS-Sharpe − 1| < 0.30
    assert re.search(r"<\s*0\.30", section), section
    assert PHASE_A_CRITERIA.max_drift_score_deviation == 0.30
    # drift_score ≥ 0.70
    assert re.search(r"drift_score\s*≥\s*0\.70", section), section
    assert PHASE_A_CRITERIA.min_drift_score == 0.70
    # verdict pass or acceptable
    assert "pass" in section and "acceptable" in section
    assert PHASE_A_CRITERIA.require_drift_verdict_in == ("pass", "acceptable")


def test_phase_b_runbook_mirrors_dataclass() -> None:
    section = _phase_section(_runbook_text(), "Phase-B — Live Small")
    # ≥ 30 live trades closed
    assert re.search(r"≥\s*30\s+live trades", section), section
    assert PHASE_B_CRITERIA.min_trades_closed == 30
    # drift_score ≥ 0.50
    assert re.search(r"drift_score\s*≥\s*0\.50", section), section
    assert PHASE_B_CRITERIA.min_drift_score == 0.50
    # 3-6 months => min_phase_days at least 90 (3 months ≈ 90 days)
    assert "3–6 months" in section or "3-6 months" in section
    assert PHASE_B_CRITERIA.min_phase_days == 90
    # Kill-switch never fired + Max-DD live < 2× backtest-Max-DD
    assert "Kill-switch never fired" in section
    assert "kill_switch_never_fired" in PHASE_B_CRITERIA.extra
    assert re.search(r"Max-DD live\s*<\s*2[×x]\s*backtest", section), section
    assert "max_dd_live_lt_2x_backtest" in PHASE_B_CRITERIA.extra
    # Slippage K-S reference type must be ``backtest_samples`` for Phase-B.
    # The C-sprint deep-review found this only in the runbook prose, not
    # mirrored on the dataclass — making it invisible to the machine-
    # checkable promotion gate. Now pinned in both directions.
    assert "backtest_samples" in section
    assert "slippage_ks_reference_backtest_samples" in PHASE_B_CRITERIA.extra
    # Watchdog window-coverage requirement (no missing date files).
    assert "window_complete" in section
    assert "drift_window_complete" in PHASE_B_CRITERIA.extra
    # verdict pass or acceptable
    assert PHASE_B_CRITERIA.require_drift_verdict_in == ("pass", "acceptable")


def test_phase_c_is_intentionally_open_ended() -> None:
    section = _phase_section(_runbook_text(), "Phase-C — Live Full")
    assert (
        "Scale-Phase" in section
        or "Kelly" in section
    ), section
    # No numeric thresholds documented — code mirrors that.
    assert PHASE_C_CRITERIA.min_drift_score is None
    assert PHASE_C_CRITERIA.max_drift_score_deviation is None
    assert PHASE_C_CRITERIA.require_drift_verdict_in == ()


def test_manual_signoff_contract_documented() -> None:
    """The runbook's "manual sign-off only" contract is the gate. The
    dataclass intentionally does not expose a boolean "auto_promote"
    flag — promotion always requires a human."""
    text = _runbook_text()
    assert "manual sign-off only" in text
    # The dataclass field set must NOT contain anything that smells
    # like an auto-promotion knob (regression-pin against future
    # accidental drift).
    forbidden = {"auto_promote", "auto_advance", "auto_signoff"}
    fields = {f for f in PhasePassCriteria.__dataclass_fields__}
    assert not (fields & forbidden), f"forbidden auto-promotion field present: {fields & forbidden}"


def test_phase_pass_criteria_registry_is_immutable() -> None:
    """The registry must be a read-only mapping so a downstream test
    cannot accidentally mutate the canonical Phase-A/B/C contract."""
    from scripts import run_smc_live_incubation as runner

    with pytest.raises(TypeError):
        runner.PHASE_PASS_CRITERIA["paper"] = runner.PHASE_C_CRITERIA  # type: ignore[index]


def test_phase_section_extracts_last_section_in_file() -> None:
    """``_phase_section`` must terminate on EOF as well as the next ``##``."""
    text = "## Phase-A — Paper\nx = 1\n\n## Phase-Z — Last\ny = 42\n"
    section = _phase_section(text, "Phase-Z")
    assert "y = 42" in section
