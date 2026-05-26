"""Tests for ``scripts/plan_2_8_weekly_summary_sha256.py``."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_sha256.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_sha256", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_sha256"] = mod
    spec.loader.exec_module(mod)
    return mod


sh = _load()


def test_missing(tmp_path: Path) -> None:
    rep = sh.compute(tmp_path / "nope.md")
    assert rep["sha256"] is None
    assert rep["size_bytes"] == 0


def test_known_digest(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    data = b"hello\n"
    p.write_bytes(data)
    rep = sh.compute(p)
    assert rep["sha256"] == hashlib.sha256(data).hexdigest()
    assert rep["size_bytes"] == len(data)
    assert rep["line_count"] == 1


def test_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("alpha\nbeta\n", encoding="utf-8")
    a = sh.compute(p)
    b = sh.compute(p)
    assert a == b


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("x\n", encoding="utf-8")
    md = sh.render_markdown(sh.compute(p))
    assert "sha256" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    # ``write_bytes`` so Windows does not translate ``\n`` to ``\r\n`` and shift the sha256.
    p.write_bytes(b"hi\n")
    out = tmp_path / "o.json"
    rc = sh.main([
        "--summary", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sha256"] == hashlib.sha256(b"hi\n").hexdigest()


def test_cli_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sh.main(["--summary", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "summary not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_sha256_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary sha256" in names
    assert "Upload Plan 2.8 weekly summary sha256" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary sha256")
    assert "plan_2_8_weekly_summary_sha256.py" in step["run"]
