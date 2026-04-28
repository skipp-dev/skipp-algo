"""Tests for ``scripts/plan_2_8_weekly_summary_heading_order.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_heading_order.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_heading_order", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_heading_order"] = mod
    spec.loader.exec_module(mod)
    return mod


ho = _load()


ORDER = ("A", "B", "C")


def test_in_order() -> None:
    rep = ho.compute("## A\n## B\n## C\n", order=ORDER)
    assert rep["misordered"] is False
    assert rep["missing"] == []
    assert rep["extra"] == []


def test_missing_detected() -> None:
    rep = ho.compute("## A\n## C\n", order=ORDER)
    assert rep["missing"] == ["B"]
    assert rep["misordered"] is False


def test_extra_detected() -> None:
    rep = ho.compute("## A\n## X\n## B\n## C\n", order=ORDER)
    assert rep["extra"] == ["X"]
    assert rep["misordered"] is False


def test_misorder_detected() -> None:
    rep = ho.compute("## B\n## A\n## C\n", order=ORDER)
    assert rep["misordered"] is True


def test_empty_input() -> None:
    rep = ho.compute("", order=ORDER)
    assert rep["missing"] == list(ORDER)
    assert rep["found"] == []


def test_h1_not_counted() -> None:
    rep = ho.compute("# Title\n## A\n## B\n## C\n", order=ORDER)
    assert rep["misordered"] is False


def test_markdown_shape() -> None:
    md = ho.render_markdown(ho.compute("## A\n## B\n## C\n", order=ORDER))
    assert "heading order" in md
    assert "misordered: false" in md


def test_default_order_populated() -> None:
    assert "Status ledger summary" in ho.DEFAULT_ORDER
    assert ho.DEFAULT_ORDER[0] == "Status ledger summary"


def test_cli_fail_on_misorder(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text(
        "## Status flip alert\n## Status ledger summary\n", encoding="utf-8",
    )
    rc = ho.main([
        "--input", str(p), "--fail-on-misorder",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text("## Status ledger summary\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ho.main([
        "--input", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["misordered"] is False


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ho.main(["--input", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "input not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_heading_order_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary heading order" in names
    assert "Upload Plan 2.8 weekly summary heading order" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary heading order")
    assert "plan_2_8_weekly_summary_heading_order.py" in step["run"]
