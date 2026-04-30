"""Tests for ``scripts/plan_2_8_weekly_summary_image_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_image_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_image_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_image_count"] = mod
    spec.loader.exec_module(mod)
    return mod


ic = _load()


def test_missing(tmp_path: Path) -> None:
    rep = ic.compute(tmp_path / "nope.md")
    assert rep["image_count"] == 0


def test_counts_images(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "![a](x.png) and ![b](y.png) plus ![a](x.png)\n",
        encoding="utf-8",
    )
    rep = ic.compute(p)
    assert rep["image_count"] == 3
    assert rep["distinct_srcs"] == 2


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n![fake](f.png)\n```\n![real](r.png)\n",
        encoding="utf-8",
    )
    rep = ic.compute(p)
    assert rep["image_count"] == 1


def test_link_not_image(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("[link](x.md)\n", encoding="utf-8")
    rep = ic.compute(p)
    assert rep["image_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("![x](y.png)\n", encoding="utf-8")
    md = ic.render_markdown(ic.compute(p))
    assert "image count" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("![x](y.png)\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = ic.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["image_count"] == 1


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ic.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_image_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary image count" in names
    assert "Upload Plan 2.8 weekly summary image count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary image count")
    assert "plan_2_8_weekly_summary_image_count.py" in step["run"]
