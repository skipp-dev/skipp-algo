"""Tests for ``scripts/plan_2_8_weekly_summary_autolink_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_autolink_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_autolink_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_autolink_count"] = mod
    spec.loader.exec_module(mod)
    return mod


al = _load()


def test_missing(tmp_path: Path) -> None:
    assert al.compute(tmp_path / "nope.md")["count"] == 0


def test_none(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("plain text\n", encoding="utf-8")
    assert al.compute(p)["count"] == 0


def test_counts(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "<https://a.example> and <http://b.example>\n"
        "<mailto:me@x>\n",
        encoding="utf-8",
    )
    assert al.compute(p)["count"] == 3


def test_non_scheme_ignored(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("<div>\n<foo:bar>\n", encoding="utf-8")
    assert al.compute(p)["count"] == 0


def test_fenced_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "```\n<https://ignored>\n```\n<https://counted>\n",
        encoding="utf-8",
    )
    assert al.compute(p)["count"] == 1


def test_inline_code_excluded(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text(
        "`<https://not>` and <https://yes>\n",
        encoding="utf-8",
    )
    assert al.compute(p)["count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("<https://a>\n", encoding="utf-8")
    md = al.render_markdown(al.compute(p))
    assert "count" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("<https://a>\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = al.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = al.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_autolink_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary autolink count" in names
    assert "Upload Plan 2.8 weekly summary autolink count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary autolink count")
    assert "plan_2_8_weekly_summary_autolink_count.py" in step["run"]
