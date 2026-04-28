"""Tests for ``scripts/plan_2_8_weekly_summary_required_sections.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_required_sections.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_required_sections", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_required_sections"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load()


REQ = ("A", "B", "C")


def test_all_present() -> None:
    rep = rs.compute("## A\n## B\n## C\n", required=REQ)
    assert rep["missing"] == []
    assert rep["present"] == ["A", "B", "C"]


def test_missing_detected() -> None:
    rep = rs.compute("## A\n## C\n", required=REQ)
    assert rep["missing"] == ["B"]


def test_empty_all_missing() -> None:
    rep = rs.compute("", required=REQ)
    assert rep["missing"] == list(REQ)


def test_extra_not_flagged() -> None:
    rep = rs.compute("## A\n## B\n## C\n## X\n", required=REQ)
    assert rep["missing"] == []


def test_h1_not_counted() -> None:
    rep = rs.compute("# A\n## B\n## C\n", required=REQ)
    assert "A" in rep["missing"]


def test_default_required_tuple() -> None:
    assert isinstance(rs.DEFAULT_REQUIRED, tuple)
    assert "Status ledger summary" in rs.DEFAULT_REQUIRED


def test_markdown_none_placeholder() -> None:
    md = rs.render_markdown(rs.compute("## A\n## B\n## C\n", required=REQ))
    assert "_(none)_" in md


def test_markdown_shape() -> None:
    md = rs.render_markdown(rs.compute("## A\n", required=REQ))
    assert "required sections" in md
    assert "`B`" in md


def test_cli_fail_on_missing(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text("## Status flip alert\n", encoding="utf-8")
    rc = rs.main([
        "--input", str(p), "--fail-on-missing",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text(
        "## Status ledger summary\n## Status flip alert\n## Downtime\n"
        "## Size budget\n## Archive index\n## Index diff\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = rs.main([
        "--input", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["missing"] == []


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rs.main(["--input", str(tmp_path / "nope.md")])
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


def test_weekly_has_required_sections_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary required sections" in names
    assert "Upload Plan 2.8 weekly summary required sections" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary required sections")
    assert "plan_2_8_weekly_summary_required_sections.py" in step["run"]
