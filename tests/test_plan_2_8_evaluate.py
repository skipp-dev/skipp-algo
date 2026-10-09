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
