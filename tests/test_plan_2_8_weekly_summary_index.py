"""Tests for ``scripts/plan_2_8_weekly_summary_index.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_index.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_index", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_index"] = mod
    spec.loader.exec_module(mod)
    return mod


wsi = _load()


def test_all_missing_placeholders(tmp_path: Path) -> None:
    body = wsi.build(tmp_path)
    assert body.startswith("# Plan 2.8 weekly summary")
    assert "(missing)" in body
    assert "Report not present" in body


def test_present_section_inlined(tmp_path: Path) -> None:
    (tmp_path / "downtime.md").write_text(
        "# Downtime\n\n- amber: 10\n",
        encoding="utf-8",
    )
    body = wsi.build(tmp_path)
    assert "## Ledger downtime" in body
    assert "- amber: 10" in body
    # The embedded H1 must be stripped
    assert "# Downtime\n" not in body


def test_toc_order_is_preserved(tmp_path: Path) -> None:
    for name in (
        "status_ledger_summary.md",
        "status_flip_alert.md",
        "downtime.md",
    ):
        (tmp_path / name).write_text(f"# {name}\nx\n", encoding="utf-8")
    body = wsi.build(tmp_path)
    i_summary = body.find("Status ledger summary")
    i_flip = body.find("Status flip alert")
    i_down = body.find("Ledger downtime")
    assert 0 < i_summary < i_flip < i_down


def test_empty_file_treated_as_missing(tmp_path: Path) -> None:
    (tmp_path / "downtime.md").write_text("", encoding="utf-8")
    body = wsi.build(tmp_path)
    assert "(missing)" in body


def test_custom_sections() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "a.md").write_text("# A\nbody\n", encoding="utf-8")
        body = wsi.build(d, sections=(("a.md", "Section A"),))
        assert "## Section A" in body
        assert "body" in body
        assert "Section B" not in body


def test_cli_writes_output(tmp_path: Path) -> None:
    out = tmp_path / "sum.md"
    rc = wsi.main([
        "--artifact-dir", str(tmp_path),
        "--output", str(out),
        "--quiet",
    ])
    assert rc == 0
    assert out.is_file()
    assert out.read_text(encoding="utf-8").startswith(
        "# Plan 2.8 weekly summary",
    )


def test_cli_missing_artifact_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wsi.main([
        "--artifact-dir", str(tmp_path / "nope"),
        "--output", str(tmp_path / "out.md"),
    ])
    assert rc == 1
    assert "artifact dir not found" in capsys.readouterr().err


def test_cli_stdout_unless_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = wsi.main([
        "--artifact-dir", str(tmp_path),
        "--output", str(tmp_path / "out.md"),
    ])
    assert rc == 0
    assert "weekly summary" in capsys.readouterr().out


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_summary_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary index" in names
    assert "Upload Plan 2.8 weekly summary" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary index")
    assert "plan_2_8_weekly_summary_index.py" in step["run"]
    assert "weekly_summary.md" in step["run"]
