"""Tests for ``scripts/plan_2_8_weekly_summary_toc_only.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_toc_only.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_toc_only", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_toc_only"] = mod
    spec.loader.exec_module(mod)
    return mod


toc = _load()


SAMPLE = (
    "# Plan 2.8 weekly summary\n"
    "\n"
    "## Contents\n"
    "\n"
    "1. [A](#a)\n"
    "2. [B](#b)\n"
    "\n"
    "## A\n"
    "\n"
    "body-a\n"
    "\n"
    "## B\n"
    "\n"
    "body-b\n"
)


def test_extracts_contents_block() -> None:
    out = toc.extract(SAMPLE)
    assert out.startswith("## Contents")
    assert "[A](#a)" in out
    assert "body-a" not in out


def test_returns_empty_when_no_toc() -> None:
    out = toc.extract("# title\n\nno toc here\n")
    assert out == ""


def test_stops_at_next_h2() -> None:
    out = toc.extract(SAMPLE)
    assert "## A" not in out


def test_cli_writes_output(tmp_path: Path) -> None:
    src = tmp_path / "s.md"
    src.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "toc.md"
    rc = toc.main([
        "--input", str(src), "--output", str(out),
    ])
    assert rc == 0
    assert "## Contents" in out.read_text(encoding="utf-8")


def test_cli_fail_on_empty(tmp_path: Path) -> None:
    src = tmp_path / "s.md"
    src.write_text("# title\n", encoding="utf-8")
    rc = toc.main([
        "--input", str(src), "--fail-on-empty",
    ])
    assert rc == 1


def test_cli_fail_on_empty_clean(tmp_path: Path) -> None:
    src = tmp_path / "s.md"
    src.write_text(SAMPLE, encoding="utf-8")
    rc = toc.main([
        "--input", str(src), "--fail-on-empty",
    ])
    assert rc == 0


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = toc.main(["--input", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "input not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_toc_only_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly-summary TOC only" in names
    assert "Upload Plan 2.8 weekly-summary TOC" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly-summary TOC only")
    assert "plan_2_8_weekly_summary_toc_only.py" in step["run"]
    assert "GITHUB_STEP_SUMMARY" in step["run"]
