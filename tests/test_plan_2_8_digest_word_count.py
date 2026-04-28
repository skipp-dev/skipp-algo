"""Tests for ``scripts/plan_2_8_digest_word_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_word_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_word_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_word_count"] = mod
    spec.loader.exec_module(mod)
    return mod


wc = _load()


def test_empty(tmp_path: Path) -> None:
    rep = wc.build(tmp_path)
    assert rep["total_words"] == 0
    assert rep["entries"] == []


def test_counts(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("one two three\n", encoding="utf-8")
    rep = wc.build(tmp_path)
    assert rep["total_words"] == 5
    assert [e["name"] for e in rep["entries"]] == ["a.md", "b.md"]


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text("skipped\n", encoding="utf-8")
    assert wc.build(tmp_path)["total_words"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("one\n", encoding="utf-8")
    md = wc.render_markdown(wc.build(tmp_path))
    assert "total_words: 1" in md


def test_markdown_empty(tmp_path: Path) -> None:
    assert "_none_" in wc.render_markdown(wc.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x y\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = wc.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total_words"] == 2


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wc.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_word_count_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest word count" in names
    assert "Upload Plan 2.8 digest word count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest word count")
    assert "plan_2_8_digest_word_count.py" in step["run"]
