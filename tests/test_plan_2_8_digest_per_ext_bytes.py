"""Tests for ``scripts/plan_2_8_digest_per_ext_bytes.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_per_ext_bytes.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_per_ext_bytes", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_per_ext_bytes"] = mod
    spec.loader.exec_module(mod)
    return mod


pe = _load()


def test_empty(tmp_path: Path) -> None:
    rep = pe.build(tmp_path)
    assert rep["entries"] == []


def test_groups_and_sorts(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x" * 10)
    (tmp_path / "b.md").write_bytes(b"x" * 20)
    (tmp_path / "c.txt").write_bytes(b"x" * 5)
    rep = pe.build(tmp_path)
    # .md totals 30, .txt totals 5, sorted by bytes desc
    assert [e["extension"] for e in rep["entries"]] == [".md", ".txt"]
    assert [e["bytes"] for e in rep["entries"]] == [30, 5]


def test_no_suffix_bucket(tmp_path: Path) -> None:
    (tmp_path / "README").write_bytes(b"xx")
    rep = pe.build(tmp_path)
    assert rep["entries"][0]["extension"] == "(none)"


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.md").write_bytes(b"x")
    assert pe.build(tmp_path)["file_count"] == 0


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    md = pe.render_markdown(pe.build(tmp_path))
    assert ".md: 1B" in md


def test_markdown_empty(tmp_path: Path) -> None:
    assert "_none_" in pe.render_markdown(pe.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = pe.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["group_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = pe.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_per_ext_bytes_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest per-extension bytes" in names
    assert "Upload Plan 2.8 digest per-extension bytes" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest per-extension bytes")
    assert "plan_2_8_digest_per_ext_bytes.py" in step["run"]
