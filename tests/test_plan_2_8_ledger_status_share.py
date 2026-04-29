"""Tests for ``scripts/plan_2_8_ledger_status_share.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_share.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_share", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_share"] = mod
    spec.loader.exec_module(mod)
    return mod


sh = _load()


def _rec(status: str) -> dict[str, Any]:
    return {"captured_at": "2026-04-21T00:00:00+00:00", "status": status}


def test_empty_zero_total() -> None:
    rep = sh.compute([])
    assert rep["total"] == 0
    assert rep["shares_pct"]["green"] == 0.0


def test_all_green_100_pct() -> None:
    rep = sh.compute([_rec("green"), _rec("green")])
    assert rep["shares_pct"]["green"] == 100.0


def test_mixed_rounded() -> None:
    rep = sh.compute([
        _rec("green"), _rec("green"), _rec("amber"),
    ])
    assert rep["shares_pct"]["green"] == pytest.approx(66.67, abs=0.01)
    assert rep["shares_pct"]["amber"] == pytest.approx(33.33, abs=0.01)


def test_invalid_status_tallied() -> None:
    rep = sh.compute([_rec("green"), _rec("bogus")])
    assert rep["skipped"] == 1
    assert rep["total"] == 1


def test_missing_status_skipped() -> None:
    rep = sh.compute([{"captured_at": "t"}, _rec("green")])
    assert rep["skipped"] == 1


def test_markdown_shape() -> None:
    md = sh.render_markdown(sh.compute([_rec("green")]))
    assert "status share" in md
    assert "100.00" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps(_rec("green")) + "\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = sh.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["total"] == 1


def test_cli_fail_below_green(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("amber")) + "\n" + json.dumps(_rec("amber")) + "\n",
        encoding="utf-8",
    )
    rc = sh.main([
        "--ledger", str(p), "--fail-below-green", "90",
    ])
    assert rc == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sh.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_status_share_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status share" in names
    assert "Upload Plan 2.8 ledger status share" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status share")
    assert "plan_2_8_ledger_status_share.py" in step["run"]
