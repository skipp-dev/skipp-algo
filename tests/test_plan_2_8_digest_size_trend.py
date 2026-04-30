"""Tests for ``scripts/plan_2_8_digest_size_trend.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_size_trend.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_size_trend", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_size_trend"] = mod
    spec.loader.exec_module(mod)
    return mod


st = _load()


def _mk(dirpath: Path, name: str, size: int) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / name).write_bytes(b"x" * size)


def test_equal_sizes_zero_delta(tmp_path: Path) -> None:
    _mk(tmp_path / "p", "a", 100)
    _mk(tmp_path / "c", "a", 100)
    rep = st.compute(tmp_path / "p", tmp_path / "c")
    assert rep["delta_bytes"] == 0
    assert rep["delta_pct"] == 0.0


def test_growth_positive_pct(tmp_path: Path) -> None:
    _mk(tmp_path / "p", "a", 100)
    _mk(tmp_path / "c", "a", 150)
    rep = st.compute(tmp_path / "p", tmp_path / "c")
    assert rep["delta_bytes"] == 50
    assert rep["delta_pct"] == 50.0


def test_drop_negative_pct(tmp_path: Path) -> None:
    _mk(tmp_path / "p", "a", 100)
    _mk(tmp_path / "c", "a", 50)
    rep = st.compute(tmp_path / "p", tmp_path / "c")
    assert rep["delta_pct"] == -50.0


def test_empty_prior_pct_none(tmp_path: Path) -> None:
    (tmp_path / "p").mkdir()
    _mk(tmp_path / "c", "a", 100)
    rep = st.compute(tmp_path / "p", tmp_path / "c")
    assert rep["delta_pct"] is None


def test_missing_prior_dir(tmp_path: Path) -> None:
    _mk(tmp_path / "c", "a", 100)
    rep = st.compute(tmp_path / "nope", tmp_path / "c")
    assert rep["prior_bytes"] == 0


def test_subdirectories_not_counted(tmp_path: Path) -> None:
    _mk(tmp_path / "c", "a", 100)
    (tmp_path / "c" / "sub").mkdir()
    (tmp_path / "c" / "sub" / "b").write_bytes(b"x" * 999)
    rep = st.compute(tmp_path / "c", tmp_path / "c")
    assert rep["current_bytes"] == 100


def test_markdown_shape(tmp_path: Path) -> None:
    _mk(tmp_path / "c", "a", 100)
    md = st.render_markdown(st.compute(tmp_path / "c", tmp_path / "c"))
    assert "artifact size trend" in md


def test_fail_on_drop_pct(tmp_path: Path) -> None:
    _mk(tmp_path / "p", "a", 100)
    _mk(tmp_path / "c", "a", 50)
    rc = st.main([
        "--prior",   str(tmp_path / "p"),
        "--current", str(tmp_path / "c"),
        "--fail-on-drop-pct", "10",
    ])
    assert rc == 1


def test_fail_on_drop_pct_clean(tmp_path: Path) -> None:
    _mk(tmp_path / "p", "a", 100)
    _mk(tmp_path / "c", "a", 100)
    rc = st.main([
        "--prior",   str(tmp_path / "p"),
        "--current", str(tmp_path / "c"),
        "--fail-on-drop-pct", "10",
    ])
    assert rc == 0


def test_cli_json(tmp_path: Path) -> None:
    _mk(tmp_path / "p", "a", 100)
    _mk(tmp_path / "c", "a", 120)
    out = tmp_path / "o.json"
    rc = st.main([
        "--prior",   str(tmp_path / "p"),
        "--current", str(tmp_path / "c"),
        "--format",  "json",
        "--output",  str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["delta_bytes"] == 20


def test_cli_missing_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = st.main([
        "--prior", str(tmp_path),
        "--current", str(tmp_path / "nope"),
    ])
    assert rc == 1
    assert "current dir not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_size_trend_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest size trend" in names
    assert "Upload Plan 2.8 digest size trend" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest size trend")
    assert "plan_2_8_digest_size_trend.py" in step["run"]
