"""Tests for ``scripts/plan_2_8_weekly_summary_link_check.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_link_check.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_link_check", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_link_check"] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("", encoding="utf-8")
    rep = lc.compute(p)
    assert rep["total"] == 0


def test_url_counted(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("see [docs](https://example.com)\n", encoding="utf-8")
    rep = lc.compute(p)
    assert rep["total"] == 1
    assert rep["url_count"] == 1
    assert rep["fragment_count"] == 0


def test_fragment_with_matching_anchor(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "## My Section\n\nsee [here](#my-section)\n",
        encoding="utf-8",
    )
    rep = lc.compute(p)
    assert rep["fragment_count"] == 1
    assert rep["missing_fragments"] == []


def test_fragment_without_anchor(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("see [bad](#missing)\n", encoding="utf-8")
    rep = lc.compute(p)
    assert rep["missing_fragments"] == ["#missing"]


def test_slug_normalisation(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "## Hello, World!\n\n[link](#hello-world)\n",
        encoding="utf-8",
    )
    rep = lc.compute(p)
    assert rep["missing_fragments"] == []


def test_missing_fragment_dedup(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "[a](#missing)\n[b](#missing)\n",
        encoding="utf-8",
    )
    rep = lc.compute(p)
    assert rep["missing_fragments"] == ["#missing"]


def test_missing_file_handled() -> None:
    rep = lc.compute(Path("nope.md"))
    assert rep["total"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[x](https://a)\n", encoding="utf-8")
    md = lc.render_markdown(lc.compute(p))
    assert "link check" in md
    assert "url_count: 1" in md


def test_markdown_lists_missing(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[x](#bad)\n", encoding="utf-8")
    md = lc.render_markdown(lc.compute(p))
    assert "Missing anchors" in md
    assert "#bad" in md


def test_cli_fail_on_missing_fragments(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[x](#bad)\n", encoding="utf-8")
    rc = lc.main([
        "--summary", str(p), "--fail-on-missing-fragments",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[x](https://a)\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = lc.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total"] == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lc.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_link_check_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary link check" in names
    assert "Upload Plan 2.8 weekly summary link check" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary link check")
    assert "plan_2_8_weekly_summary_link_check.py" in step["run"]
