from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import plan_2_8_evaluate as mod


def test_plan_2_8_evaluate_main_writes_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "plan_2_8_tf_family_rollup.json"
    monkeypatch.setattr("sys.argv", ["plan_2_8_evaluate.py", "--output", str(out)])
    rc = mod.main()
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"
    assert "aggregate" in payload
    assert "phase_e2_verdict" in payload


def test_snapshot_declares_itself_synthetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every field in this snapshot is drawn from ``random`` and the Phase E2
    verdicts are labelled ``"measured"`` regardless. Until real evaluation
    logic lands, the flag is the only thing standing between a consumer and
    reading dice as evidence (audit finding F-6, 2026-08-08)."""
    out = tmp_path / "rollup.json"
    monkeypatch.setattr("sys.argv", ["plan_2_8_evaluate.py", "--output", str(out)])
    assert mod.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["synthetic"] is True
