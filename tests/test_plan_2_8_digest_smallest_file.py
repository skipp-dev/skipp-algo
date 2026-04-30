"""Tests for ``scripts/plan_2_8_digest_smallest_file.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_smallest_file.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_smallest_file", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_smallest_file"] = mod
    spec.loader.exec_module(mod)
    return mod


sf = _load()


def test_empty(tmp_path: Path) -> None:
    rep = sf.build(tmp_path)
    assert rep["smallest_name"] is None


def test_only_empty_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("", encoding="utf-8")
    (tmp_path / "b.md").write_text("", encoding="utf-8")
    rep = sf.build(tmp_path)
    assert rep["smallest_name"] is None
    assert rep["file_count"] == 2


def test_picks_smallest_nonempty(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("xxxx", encoding="utf-8")
    (tmp_path / "b.md").write_text("x", encoding="utf-8")
    (tmp_path / "c.md").write_text("xx", encoding="utf-8")
    rep = sf.build(tmp_path)
    assert rep["smallest_name"] == "b.md"
    assert rep["smallest_bytes"] == 1


def test_tie_breaks_by_name(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("xx", encoding="utf-8")
    (tmp_path / "a.md").write_text("xx", encoding="utf-8")
    rep = sf.build(tmp_path)
    assert rep["smallest_name"] == "a.md"


def test_subdirs_ignored(tmp_path: Path) -> None:
    sub = tmp_path / "s"
    sub.mkdir()
    (sub / "tiny.md").write_text("x", encoding="utf-8")
    (tmp_path / "a.md").write_text("xxxx", encoding="utf-8")
    rep = sf.build(tmp_path)
    assert rep["smallest_name"] == "a.md"


def test_markdown_na(tmp_path: Path) -> None:
    md = sf.render_markdown(sf.build(tmp_path))
    assert "smallest_name: n/a" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abc", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = sf.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["smallest_bytes"] == 3


def test_cli_fail_below_bytes(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    rc = sf.main([
        "--artifact-dir", str(tmp_path), "--fail-below-bytes", "10",
    ])
    assert rc == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sf.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_smallest_file_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest smallest file" in names
    assert "Upload Plan 2.8 digest smallest file" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest smallest file")
    assert "plan_2_8_digest_smallest_file.py" in step["run"]
