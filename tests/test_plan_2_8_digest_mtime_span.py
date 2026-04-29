"""Tests for ``scripts/plan_2_8_digest_mtime_span.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_mtime_span.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_mtime_span", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_mtime_span"] = mod
    spec.loader.exec_module(mod)
    return mod


ms = _load()


def test_empty(tmp_path: Path) -> None:
    assert ms.build(tmp_path)["found"] is False


def test_single(tmp_path: Path) -> None:
    p = tmp_path / "a"
    p.write_bytes(b"x")
    os.utime(p, (1_700_000_000, 1_700_000_000))
    rep = ms.build(tmp_path)
    assert rep["file_count"] == 1
    assert rep["span_hours"] == 0.0


def test_multi_span(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    os.utime(a, (1_700_000_000, 1_700_000_000))
    # 2 hours later
    os.utime(b, (1_700_000_000 + 7200, 1_700_000_000 + 7200))
    rep = ms.build(tmp_path)
    assert rep["span_hours"] == 2.0


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a").write_bytes(b"x")
    assert ms.build(tmp_path)["found"] is False


def test_markdown_empty(tmp_path: Path) -> None:
    assert "_none_" in ms.render_markdown(ms.build(tmp_path))


def test_markdown_found(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = ms.render_markdown(ms.build(tmp_path))
    assert "span_hours" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = ms.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["found"] is True


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ms.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_mtime_span_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest mtime span" in names
    assert "Upload Plan 2.8 digest mtime span" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest mtime span")
    assert "plan_2_8_digest_mtime_span.py" in step["run"]
