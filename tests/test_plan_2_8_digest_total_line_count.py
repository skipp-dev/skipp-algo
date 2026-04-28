"""Tests for ``scripts/plan_2_8_digest_total_line_count.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_total_line_count.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_total_line_count", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_total_line_count"] = mod
    spec.loader.exec_module(mod)
    return mod


tl = _load()


def test_empty(tmp_path: Path) -> None:
    assert tl.build(tmp_path)["total_line_count"] == 0


def test_sum(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a\nb\n")
    (tmp_path / "b.md").write_text("x\ny\nz\n")
    rep = tl.build(tmp_path)
    assert rep["file_count"] == 2
    assert rep["total_line_count"] == 5


def test_skip_binary(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("only\nline\n")
    (tmp_path / "b.bin").write_bytes(b"\xff\xfe\x00")
    rep = tl.build(tmp_path)
    assert rep["file_count"] == 2
    assert rep["total_line_count"] == 2


def test_markdown_shape(tmp_path: Path) -> None:
    assert "total_line_count" in tl.render_markdown(tl.build(tmp_path))


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a\n")
    out = tmp_path / "o.json"
    code = tl.main([
        "--artifact-dir", str(tmp_path), "--format", "json",
        "--output", str(out),
    ])
    assert code == 0
    assert json.loads(
        out.read_text(encoding="utf-8"))["total_line_count"] == 1


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = tl.main(["--artifact-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_total_lines_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest total line count" in names
    assert "Upload Plan 2.8 digest total line count" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest total line count")
    assert "plan_2_8_digest_total_line_count.py" in step["run"]
