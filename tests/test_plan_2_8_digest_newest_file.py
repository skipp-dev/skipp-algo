"""Tests for ``scripts/plan_2_8_digest_newest_file.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_newest_file.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_newest_file", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_newest_file"] = mod
    spec.loader.exec_module(mod)
    return mod


nf = _load()


def test_empty(tmp_path: Path) -> None:
    assert nf.build(tmp_path)["found"] is False


def test_picks_newest(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"x")
    b.write_bytes(b"xxx")
    os.utime(a, (1_700_000_000, 1_700_000_000))
    os.utime(b, (1_800_000_000, 1_800_000_000))
    rep = nf.build(tmp_path)
    assert rep["name"] == "b"
    assert rep["size_bytes"] == 3


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a").write_bytes(b"x")
    assert nf.build(tmp_path)["found"] is False


def test_markdown_found(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = nf.render_markdown(nf.build(tmp_path))
    assert "name: a" in md


def test_markdown_empty(tmp_path: Path) -> None:
    assert "_none_" in nf.render_markdown(nf.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = nf.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["name"] == "a"


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = nf.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_newest_file_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest newest file" in names
    assert "Upload Plan 2.8 digest newest file" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest newest file")
    assert "plan_2_8_digest_newest_file.py" in step["run"]
