"""Tests for ``scripts/plan_2_8_ledger_rarest_status.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_rarest_status.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_rarest_status", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_rarest_status"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s, "captured_at": "t"}


def test_empty_alphabetical_tie() -> None:
    rep = rs.compute([])
    assert rep["rarest_status"] == "amber"
    assert rep["count"] == 0


def test_rarest_is_red() -> None:
    recs = (
        [_r("green")] * 5
        + [_r("amber")] * 3
        + [_r("red")]
        + [_r("unknown")] * 2
    )
    rep = rs.compute(recs)
    assert rep["rarest_status"] == "red"
    assert rep["count"] == 1


def test_ignores_invalid() -> None:
    recs = [_r("bogus")] * 5 + [_r("green")]
    rep = rs.compute(recs)
    assert rep["count"] == 0


def test_markdown_shape() -> None:
    assert "rarest_status" in rs.render_markdown(rs.compute([_r("green")]))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_r("red")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    code = rs.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert "rarest_status" in json.loads(out.read_text(encoding="utf-8"))


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = rs.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_rarest_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger rarest status" in names
    assert "Upload Plan 2.8 ledger rarest status" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger rarest status")
    assert "plan_2_8_ledger_rarest_status.py" in step["run"]
