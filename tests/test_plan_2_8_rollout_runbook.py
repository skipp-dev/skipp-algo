"""Pin-test for docs/plan_2_8_rollout_runbook.md.

Guards the W13 operator checklist against silent drift: the three
addendum gates (G1/G2/G3), the helper references, and the phase-0/1
done markers must stay in sync with the actually-shipped toolset.
"""

from __future__ import annotations

from pathlib import Path

RUNBOOK = (
    Path(__file__).resolve().parents[1]
    / "docs" / "plan_2_8_rollout_runbook.md"
)


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_runbook_exists_with_title() -> None:
    assert RUNBOOK.exists()
    assert _text().startswith("# Plan 2.8 rollout runbook")


def test_three_gates_documented_with_thresholds() -> None:
    text = _text()
    assert "G1 uplift" in text
    assert "G2 Brier" in text
    assert "G3 events" in text
    # Addendum-canonical thresholds.
    assert "3pp" in text or "0.03" in text
    assert "0.02" in text
    assert "30 events" in text


def test_runbook_cross_references_shipped_tooling() -> None:
    text = _text()
    assert "plan_2_8_q4_gate_evaluator.py" in text
    assert "plan_2_8_tf_family_rollup" in text
    assert "smc-measurement-benchmark-rolling.yml" in text
    assert "DECISIONS.md" in text
    assert "append_adr.py" in text


def test_phase_table_lists_all_four_phases() -> None:
    text = _text()
    for phase in ("Phase 0", "Phase 1", "Phase 2", "Phase 3"):
        assert phase in text, f"phase table missing {phase}"


def test_runbook_pins_phases_0_and_1_as_done() -> None:
    text = _text()
    # Phase-0 and Phase-1 rows must show the `done` marker.
    lines = [ln for ln in text.splitlines() if ln.startswith("| Phase 0")]
    assert lines and "done" in lines[0]
    lines = [ln for ln in text.splitlines() if ln.startswith("| Phase 1")]
    assert lines and "done" in lines[0]


def test_addendum_default_thresholds_cited() -> None:
    text = _text()
    for default in (
        "DEFAULT_UPLIFT_MIN_PP = 0.03",
        "DEFAULT_UPLIFT_MIN_BUCKETS = 2",
        "DEFAULT_BRIER_MAX_REGRESSION = 0.02",
        "DEFAULT_MIN_EVENTS_PER_BUCKET = 30",
    ):
        assert default in text, f"runbook missing default constant: {default}"
