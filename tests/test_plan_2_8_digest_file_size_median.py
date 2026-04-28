"""Tests for ``scripts/plan_2_8_digest_file_size_median.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_file_size_median.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_file_size_median", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_file_size_median"] = mod
    spec.loader.exec_module(mod)
    return mod


md = _load()


def test_empty(tmp_path: Path) -> None:
    assert md.build(tmp_path)["file_size_median_bytes"] == 0.0


def test_odd(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    (tmp_path / "b.md").write_bytes(b"x" * 3)
    (tmp_path / "c.md").write_bytes(b"x" * 10)
    assert md.build(tmp_path)["file_size_median_bytes"] == 3


def test_even(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x" * 2)
    (tmp_path / "b.md").write_bytes(b"x" * 4)
    assert md.build(tmp_path)["file_size_median_bytes"] == 3


def test_markdown_shape(tmp_path: Path) -> None:
    assert "file_size_median_bytes" in md.render_markdown(md.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    out = tmp_path / "o.json"
    code = md.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["file_size_median_bytes"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = md.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_median_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest file size median" in names
    assert "Upload Plan 2.8 digest file size median" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest file size median")
    assert "plan_2_8_digest_file_size_median.py" in step["run"]
