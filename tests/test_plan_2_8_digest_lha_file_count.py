"""Tests for ``plan_2_8_digest_lha_file_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_lha_file_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_lha_file_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_lha_file_count"] = mod
    spec.loader.exec_module(mod)
    return mod


lh = _load()


def test_empty(tmp_path: Path) -> None:
    assert lh.build(tmp_path)["lha_file_count"] == 0


def test_counts(tmp_path: Path) -> None:
    (tmp_path / "a.lha").write_bytes(b"x")
    (tmp_path / "B.LHA").write_bytes(b"x")
    (tmp_path / "c.arj").write_bytes(b"x")
    rep = lh.build(tmp_path)
    assert rep["file_count"] == 3
    assert rep["lha_file_count"] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    body = lh.render_markdown(lh.build(tmp_path))
    assert "lha_file_count" in body


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "x.lha").write_bytes(b"x")
    out = tmp_path / "o.json"
    code = lh.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["lha_file_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = lh.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_lh_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest lha file count" in names
    assert "Upload Plan 2.8 digest lha file count" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 digest lha file count"
    )
    assert "plan_2_8_digest_lha_file_count.py" in step["run"]
