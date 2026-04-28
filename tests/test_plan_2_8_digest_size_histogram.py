"""Tests for ``scripts/plan_2_8_digest_size_histogram.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_size_histogram.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_size_histogram", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_size_histogram"] = mod
    spec.loader.exec_module(mod)
    return mod


sh = _load()


def _bucket(report: dict[str, Any], label: str) -> dict[str, int]:
    for e in report["entries"]:
        if e["label"] == label:
            return e
    raise AssertionError(f"bucket {label} missing")


def test_empty_all_zero(tmp_path: Path) -> None:
    rep = sh.build(tmp_path)
    assert rep["file_count"] == 0
    assert all(e["count"] == 0 for e in rep["entries"])


def test_small_bucket(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 500)
    rep = sh.build(tmp_path)
    assert _bucket(rep, "<1KB")["count"] == 1


def test_mid_bucket(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 5000)
    rep = sh.build(tmp_path)
    assert _bucket(rep, "1-10KB")["count"] == 1


def test_large_bucket(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 50_000)
    rep = sh.build(tmp_path)
    assert _bucket(rep, "10-100KB")["count"] == 1


def test_100kb_1mb_bucket(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 200_000)
    rep = sh.build(tmp_path)
    assert _bucket(rep, "100KB-1MB")["count"] == 1


def test_over_1mb_bucket(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 1_100_000)
    rep = sh.build(tmp_path)
    assert _bucket(rep, ">=1MB")["count"] == 1


def test_boundary_1kb(tmp_path: Path) -> None:
    # size==1024 goes into 1-10KB (not <1KB)
    (tmp_path / "a").write_bytes(b"x" * 1024)
    rep = sh.build(tmp_path)
    assert _bucket(rep, "<1KB")["count"] == 0
    assert _bucket(rep, "1-10KB")["count"] == 1


def test_subdirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"xx")
    rep = sh.build(tmp_path)
    assert rep["file_count"] == 1


def test_markdown_shape(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    md = sh.render_markdown(sh.build(tmp_path))
    assert "size histogram" in md
    assert "<1KB" in md


def test_cli_json(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x")
    out = tmp_path / "o.json"
    rc = sh.main([
        "--artifact-dir", str(tmp_path),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["file_count"] == 1


def test_cli_missing_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = sh.main(["--artifact-dir", str(tmp_path / "nope")])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_size_histogram_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest size histogram" in names
    assert "Upload Plan 2.8 digest size histogram" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest size histogram")
    assert "plan_2_8_digest_size_histogram.py" in step["run"]
