"""Tests for ``scripts/plan_2_8_weekly_runcard.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_runcard.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_weekly_runcard", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_runcard"] = mod
    spec.loader.exec_module(mod)
    return mod


rc_mod = _load()


def _seed(artifact: Path, files: dict[str, str]) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (artifact / name).write_text(body, encoding="utf-8")


def test_empty_artifact_dir_produces_placeholder(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    md = rc_mod.render_runcard(tmp_path)
    assert "# Plan 2.8 weekly runcard" in md
    assert "Runcard is empty" in md


def test_sections_appear_in_order(tmp_path: Path) -> None:
    _seed(tmp_path, {
        "weekly_digest.md":     "# Weekly digest body",
        "coverage.md":           "# Coverage body",
        "stability.md":          "# Stability body",
        "alert_history_summary.md": "# History summary body",
    })
    md = rc_mod.render_runcard(tmp_path)
    assert md.index("## Weekly digest") < md.index("## Slice coverage")
    assert md.index("## Slice coverage") < md.index("## Slice stability")
    assert md.index("## Slice stability") < md.index("## Alert-history summary")


def test_missing_sections_are_skipped(tmp_path: Path) -> None:
    _seed(tmp_path, {"coverage.md": "# Just coverage"})
    md = rc_mod.render_runcard(tmp_path)
    assert "## Slice coverage" in md
    assert "## Slice stability" not in md


def test_empty_file_is_skipped(tmp_path: Path) -> None:
    _seed(tmp_path, {"coverage.md": "", "stability.md": "# Not empty"})
    md = rc_mod.render_runcard(tmp_path)
    assert "## Slice coverage" not in md
    assert "## Slice stability" in md


def test_included_sections_index_emitted(tmp_path: Path) -> None:
    _seed(tmp_path, {"coverage.md": "x", "stability.md": "y"})
    md = rc_mod.render_runcard(tmp_path)
    assert "## Included sections" in md
    idx_start = md.index("## Included sections")
    idx_end = md.index("---")
    assert "Slice coverage" in md[idx_start:idx_end]
    assert "Slice stability" in md[idx_start:idx_end]


def test_run_url_rendered(tmp_path: Path) -> None:
    _seed(tmp_path, {"coverage.md": "x"})
    md = rc_mod.render_runcard(
        tmp_path, run_url="https://example/run/42",
    )
    assert "https://example/run/42" in md


def test_generated_timestamp_in_utc_iso(tmp_path: Path) -> None:
    _seed(tmp_path, {"coverage.md": "x"})
    md = rc_mod.render_runcard(
        tmp_path,
        now=_dt.datetime(2026, 4, 21, 12, 0, 0, tzinfo=_dt.UTC),
    )
    assert "2026-04-21T12:00:00Z" in md


def test_cli_writes_output(tmp_path: Path) -> None:
    art = tmp_path / "art"
    _seed(art, {"coverage.md": "# Coverage"})
    out = tmp_path / "runcard.md"
    rc = rc_mod.main([
        "--artifact-dir", str(art), "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    assert "Plan 2.8 weekly runcard" in out.read_text(encoding="utf-8")


def test_cli_missing_artifact_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rc_mod.main([
        "--artifact-dir", str(tmp_path / "nope"),
        "--output", str(tmp_path / "r.md"),
    ])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def test_cli_run_url_in_output(tmp_path: Path) -> None:
    art = tmp_path / "art"
    _seed(art, {"coverage.md": "body"})
    out = tmp_path / "r.md"
    rc = rc_mod.main([
        "--artifact-dir", str(art), "--output", str(out),
        "--run-url", "https://example/run/9",
    ])
    assert rc == 0
    assert "https://example/run/9" in out.read_text(encoding="utf-8")
