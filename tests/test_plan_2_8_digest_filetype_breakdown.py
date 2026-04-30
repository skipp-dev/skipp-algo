"""Tests for ``scripts/plan_2_8_digest_filetype_breakdown.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_filetype_breakdown.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_filetype_breakdown", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_filetype_breakdown"] = mod
    spec.loader.exec_module(mod)
    return mod


fb = _load()


def test_empty_dir(tmp_path: Path) -> None:
    rep = fb.build(tmp_path)
    assert rep["file_count"] == 0
    assert rep["entries"] == []


def test_single_md(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"xx")
    rep = fb.build(tmp_path)
    assert rep["entries"] == [{"ext": ".md", "count": 1, "bytes": 2}]
    assert rep["total_bytes"] == 2


def test_grouping_multiple_ext(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    (tmp_path / "b.md").write_bytes(b"yy")
    (tmp_path / "c.json").write_bytes(b"zzz")
    rep = fb.build(tmp_path)
    by_ext = {e["ext"]: e for e in rep["entries"]}
    assert by_ext[".md"]["count"] == 2
    assert by_ext[".md"]["bytes"] == 3
    assert by_ext[".json"]["count"] == 1
    assert rep["file_count"] == 3


def test_no_extension_bucket(tmp_path: Path) -> None:
    (tmp_path / "README").write_bytes(b"r")
    rep = fb.build(tmp_path)
    by_ext = {e["ext"]: e for e in rep["entries"]}
    assert "" in by_ext
    assert by_ext[""]["count"] == 1


def test_case_folded_ext(tmp_path: Path) -> None:
    (tmp_path / "a.MD").write_bytes(b"x")
    rep = fb.build(tmp_path)
    assert rep["entries"][0]["ext"] == ".md"


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_bytes(b"yy")
    rep = fb.build(tmp_path)
    assert rep["file_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    md = fb.render_markdown(fb.build(tmp_path))
    assert "filetype breakdown" in md
    assert ".md" in md


def test_markdown_empty_placeholder(tmp_path: Path) -> None:
    md = fb.render_markdown(fb.build(tmp_path))
    assert "_none_" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = fb.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fb.main(["--artifact-dir", str(tmp_path / "nope")])
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


def test_weekly_has_filetype_breakdown_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest filetype breakdown" in names
    assert "Upload Plan 2.8 digest filetype breakdown" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest filetype breakdown")
    assert "plan_2_8_digest_filetype_breakdown.py" in step["run"]
