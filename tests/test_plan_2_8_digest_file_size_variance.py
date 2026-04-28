"""Tests for ``scripts/plan_2_8_digest_file_size_variance.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_file_size_variance.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_file_size_variance", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_file_size_variance"] = mod
    spec.loader.exec_module(mod)
    return mod


fv = _load()


def test_empty(tmp_path: Path) -> None:
    assert fv.build(tmp_path)["file_size_variance"] == 0.0


def test_variance(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x" * 2)
    (tmp_path / "b.md").write_bytes(b"x" * 4)
    # mean=3, var = ((2-3)^2 + (4-3)^2)/2 = 1.0
    assert fv.build(tmp_path)["file_size_variance"] == 1.0


def test_markdown_shape(tmp_path: Path) -> None:
    assert "file_size_variance" in fv.render_markdown(fv.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_bytes(b"x")
    out = tmp_path / "o.json"
    code = fv.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["file_size_variance"] == 0.0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = fv.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_variance_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest file size variance" in names
    assert "Upload Plan 2.8 digest file size variance" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest file size variance")
    assert "plan_2_8_digest_file_size_variance.py" in step["run"]
