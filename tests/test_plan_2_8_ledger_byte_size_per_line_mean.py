"""Tests for ``plan_2_8_ledger_byte_size_per_line_mean.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_byte_size_per_line_mean.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_byte_size_per_line_mean", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_byte_size_per_line_mean"] = mod
    spec.loader.exec_module(mod)
    return mod


bm = _load()


def test_empty(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_bytes(b"")
    rep = bm.compute(p)
    assert rep["nonblank_line_count"] == 0
    assert rep["byte_size_per_line_mean"] == 0.0


def test_mean(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    # 3 nonblank lines with lengths 2, 4, 6 -> mean 4.0
    p.write_bytes(b"aa\nbbbb\ncccccc\n\n")
    rep = bm.compute(p)
    assert rep["nonblank_line_count"] == 3
    assert rep["byte_size_per_line_mean"] == 4.0


def test_markdown_shape(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_bytes(b"x")
    assert "byte_size_per_line_mean" in bm.render_markdown(bm.compute(p))


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_bytes(b"abc\n")
    out = tmp_path / "o.json"
    code = bm.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["byte_size_per_line_mean"] == 3.0


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = bm.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_bm_steps() -> None:
    pytest.importorskip("yaml")
    data = _wf(WEEKLY)
    steps = data["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger byte size per line mean" in names
    assert "Upload Plan 2.8 ledger byte size per line mean" in names
    step = next(
        s for s in steps
        if s.get("name") == "Plan 2.8 ledger byte size per line mean"
    )
    assert "plan_2_8_ledger_byte_size_per_line_mean.py" in step["run"]
