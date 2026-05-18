"""Tests for ``scripts/plan_2_8_digest_summary_index.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_summary_index.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_summary_index", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_summary_index"] = mod
    spec.loader.exec_module(mod)
    return mod


si = _load()


def test_empty_dir(tmp_path: Path) -> None:
    rep = si.build(tmp_path)
    assert rep["count"] == 0
    assert rep["entries"] == []


def test_md_heading_extracted(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Title\nbody\n", encoding="utf-8")
    rep = si.build(tmp_path)
    assert rep["entries"][0]["heading"] == "Title"


def test_md_without_heading_falls_back_to_name(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("no heading here\n", encoding="utf-8")
    rep = si.build(tmp_path)
    assert rep["entries"][0]["heading"] == "a.md"


def test_non_md_filtered(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# t", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    rep = si.build(tmp_path)
    assert rep["count"] == 1


def test_subdirectories_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# t", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("# u", encoding="utf-8")
    rep = si.build(tmp_path)
    assert rep["count"] == 1


def test_sorted_by_name(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("# b", encoding="utf-8")
    (tmp_path / "a.md").write_text("# a", encoding="utf-8")
    rep = si.build(tmp_path)
    names = [e["name"] for e in rep["entries"]]
    assert names == ["a.md", "b.md"]


def test_size_reported(tmp_path: Path) -> None:
    # ``newline=""`` so Windows keeps the single ``\n`` instead of expanding to ``\r\n``.
    (tmp_path / "a.md").write_text("# hi\n", encoding="utf-8", newline="")
    rep = si.build(tmp_path)
    assert rep["entries"][0]["size"] == 5


def test_markdown_empty(tmp_path: Path) -> None:
    md = si.render_markdown(si.build(tmp_path))
    assert "_none_" in md


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Title\n", encoding="utf-8")
    md = si.render_markdown(si.build(tmp_path))
    assert "summary index" in md
    assert "Title" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# t\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = si.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = si.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_summary_index_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest summary index" in names
    assert "Upload Plan 2.8 digest summary index" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest summary index")
    assert "plan_2_8_digest_summary_index.py" in step["run"]
