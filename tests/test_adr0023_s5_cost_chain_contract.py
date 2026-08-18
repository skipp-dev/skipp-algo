"""Contract pins for the ADR-0023 §5 empirical cost chain (D2, 2026-08-18).

Both links of the chain (``incubation_to_execution_sessions`` ->
``calibrate_execution_costs``) existed for weeks with NO scheduler — 6/6
``epnl_after_cost_*`` gate artifacts carried ``cost_source: flat_default``
while the ADR-0023 handover described the empirical bar in the present
tense, and the bridge script's own docstring named the gap ("no job invokes
that script"). These pins keep the chain wired in promotion-gate-daily:

  fetch      data/phase-a-audit -> cache/live/incubation_*.jsonl (read-only)
  convert    incubation_to_execution_sessions -> per-day session JSONs
  calibrate  calibrate_execution_costs -> cost_calibration.json
  consume    run_epnl_after_cost_gate ${COST_FLAG} — only on calibrator rc=0
             (rc=2 = produced but UNMEASURABLE keeps the disclosed
             flat_default path; the gate hard-errors on unmeasurable+flag
             by design)
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "promotion-gate-daily.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_both_chain_links_have_a_scheduler() -> None:
    text = _text()
    assert "scripts.incubation_to_execution_sessions" in text, (
        "the ledger->sessions bridge lost its only scheduler"
    )
    assert "scripts.calibrate_execution_costs" in text, (
        "the cost calibrator lost its only scheduler"
    )


def test_the_gate_consumes_the_calibration_conditionally() -> None:
    text = _text()
    # The flag reaches the epnl invocation ...
    assert "${COST_FLAG" in text
    epnl_at = text.index("run_epnl_after_cost_gate")
    assert text.index("${COST_FLAG") < text.index(
        "--out", epnl_at
    ), "COST_FLAG must be part of the epnl invocation"
    # ... but only a MEASURABLE calibration exports it: the rc=2
    # (produced-but-unmeasurable) branch must keep flat_default disclosed
    # instead of hard-erroring the daily gate.
    assert '-eq 2' in text and "not yet measurable" in text
    assert 'COST_FLAG=--cost-calibration' in text


def test_the_chain_runs_before_the_gate_on_fetched_ledgers() -> None:
    text = _text()
    fetch_at = text.index("data/phase-a-audit")
    convert_at = text.index("scripts.incubation_to_execution_sessions")
    calibrate_at = text.index("scripts.calibrate_execution_costs")
    gate_at = text.index("run_epnl_after_cost_gate")
    assert fetch_at < convert_at < calibrate_at < gate_at
