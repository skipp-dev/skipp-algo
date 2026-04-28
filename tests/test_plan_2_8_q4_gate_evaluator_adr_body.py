"""Tests for ``render_adr_body`` in plan_2_8_q4_gate_evaluator.py.

Pins the ADR-skeleton shape so the W13 operator workflow
(evaluator --format adr | append_adr.py ...) keeps working.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


evaluator = _load(
    "plan_2_8_q4_gate_evaluator",
    REPO / "scripts" / "plan_2_8_q4_gate_evaluator.py",
)


def _bundle_pass() -> dict:
    return {
        "buckets": [
            {"key": "5m/FVG", "hr_baseline": 0.45, "hr_candidate": 0.49, "n_events": 110},
            {"key": "1H/FVG", "hr_baseline": 0.45, "hr_candidate": 0.49, "n_events": 100},
            {"key": "4H/BOS", "hr_baseline": 0.40, "hr_candidate": 0.44, "n_events":  35},
        ],
        "brier_baseline":  0.235,
        "brier_candidate": 0.236,
    }


def _bundle_fail_g3() -> dict:
    return {
        "buckets": [
            {"key": "5m/FVG", "hr_baseline": 0.45, "hr_candidate": 0.49, "n_events": 25},
            {"key": "1H/FVG", "hr_baseline": 0.45, "hr_candidate": 0.49, "n_events": 100},
        ],
        "brier_baseline": 0.20, "brier_candidate": 0.20,
    }


def test_adr_body_has_all_four_required_sections() -> None:
    body = evaluator.render_adr_body(evaluator.evaluate_gate(_bundle_pass()))
    for header in (
        "## Decision", "## Alternatives considered",
        "## Consequences", "## Evidence",
    ):
        assert header in body, f"missing ADR section: {header}"


def test_adr_body_pass_promotes_2h_layer() -> None:
    body = evaluator.render_adr_body(evaluator.evaluate_gate(_bundle_pass()))
    assert "Promote 2H 4th HTF trend layer" in body
    assert "Reject 2H promotion" in body  # listed as rejected alternative


def test_adr_body_fail_rejects_promotion_with_failed_gate_listed() -> None:
    body = evaluator.render_adr_body(evaluator.evaluate_gate(_bundle_fail_g3()))
    assert "Reject 2H 4th HTF trend layer" in body
    assert "G3_min_events" in body  # the failed gate is named in the alternatives


def test_adr_body_evidence_includes_all_three_gates() -> None:
    body = evaluator.render_adr_body(evaluator.evaluate_gate(_bundle_pass()))
    assert "G1 uplift" in body
    assert "G2 Brier" in body
    assert "G3 min-events" in body


def test_adr_body_evidence_brier_numbers_present() -> None:
    body = evaluator.render_adr_body(evaluator.evaluate_gate(_bundle_pass()))
    assert "baseline=0.2350" in body
    assert "candidate=0.2360" in body
    # Sign-prefixed regression formatting.
    assert "regression=+" in body or "regression=-" in body


def test_cli_format_adr_emits_decision_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(_bundle_pass()), encoding="utf-8")
    rc = evaluator.main([
        "--bundle", str(bundle_path),
        "--format", "adr",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Decision" in out
    assert "Promote 2H 4th HTF trend layer" in out
