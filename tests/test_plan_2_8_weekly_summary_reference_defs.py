"""Tests for ``scripts/plan_2_8_weekly_summary_reference_defs.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_reference_defs.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_reference_defs", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_reference_defs"] = mod
    spec.loader.exec_module(mod)
    return mod


rd = _load()


def test_missing(tmp_path: Path) -> None:
    assert rd.compute(tmp_path / "nope.md")["count"] == 0


def test_none(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("plain\n", encoding="utf-8")
    assert rd.compute(p)["count"] == 0


def test_counts_and_sorts(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "[beta]: https://b\n[alpha]: https://a\n",
        encoding="utf-8",
    )
    rep = rd.compute(p)
    assert rep["count"] == 2
    assert rep["labels"] == ["alpha", "beta"]


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n[ignored]: https://x\n```\n[a]: https://a\n",
        encoding="utf-8",
    )
    rep = rd.compute(p)
    assert rep["labels"] == ["a"]


def test_requires_nonempty_url(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[a]: \n[b]: https://b\n", encoding="utf-8")
    rep = rd.compute(p)
    assert rep["labels"] == ["b"]


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[a]: https://a\n", encoding="utf-8")
    md = rd.render_markdown(rd.compute(p))
    assert "count: 1" in md
    assert "  - a" in md


def test_markdown_empty(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("plain\n", encoding="utf-8")
    assert "_none_" in rd.render_markdown(rd.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[a]: https://a\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = rd.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rd.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_reference_defs_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary reference defs" in names
    assert "Upload Plan 2.8 weekly summary reference defs" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary reference defs")
    assert "plan_2_8_weekly_summary_reference_defs.py" in step["run"]
