"""Tests for ``scripts/plan_2_8_digest_min_file_size.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_min_file_size.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_min_file_size", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_min_file_size"] = mod
    spec.loader.exec_module(mod)
    return mod


mn = _load()


def test_empty(tmp_path: Path) -> None:
    assert mn.build(tmp_path)["min_file_size_bytes"] == 0


def test_min(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x" * 10)
    (tmp_path / "b.md").write_bytes(b"x" * 3)
    (tmp_path / "sub").mkdir()
    rep = mn.build(tmp_path)
    assert rep["entry_count"] == 3
    assert rep["min_file_size_bytes"] == 3


def test_markdown_shape(tmp_path: Path) -> None:
    assert "min_file_size_bytes" in mn.render_markdown(mn.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"xyz")
    out = tmp_path / "o.json"
    code = mn.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["min_file_size_bytes"] == 3


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = mn.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_min_file_size_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest min file size" in names
    assert "Upload Plan 2.8 digest min file size" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest min file size")
    assert "plan_2_8_digest_min_file_size.py" in step["run"]
