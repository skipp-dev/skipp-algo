"""Tests for ``scripts/plan_2_8_runbook_sections.py`` + #76 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_runbook_sections.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_runbook_sections", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_runbook_sections"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load()


SIMPLE = """\
# Plan 2.8

## Alpha

some text

## Beta

more text
"""

WITH_FENCE = """\
## Real

```
## Fake heading in fence
```

## Other
"""


def test_collect_sections_top_level_only() -> None:
    sections = rs.collect_sections(SIMPLE)
    assert sections == ["Alpha", "Beta"]


def test_collect_ignores_fenced() -> None:
    sections = rs.collect_sections(WITH_FENCE)
    assert "Fake heading in fence" not in sections
    assert sections == ["Real", "Other"]


def test_check_all_present() -> None:
    rep = rs.check(SIMPLE, required=["Alpha", "Beta"])
    assert rep["counts"]["missing"] == 0
    assert rep["missing"] == []


def test_check_some_missing() -> None:
    rep = rs.check(SIMPLE, required=["Alpha", "Gamma"])
    assert rep["counts"]["missing"] == 1
    assert rep["missing"] == ["Gamma"]


def test_check_empty_required_list() -> None:
    rep = rs.check(SIMPLE, required=[])
    assert rep["counts"]["required"] == 0
    assert rep["counts"]["missing"] == 0


def test_check_trims_whitespace_in_required() -> None:
    rep = rs.check(SIMPLE, required=["  Alpha  ", "Beta"])
    assert rep["counts"]["missing"] == 0


def test_heading_match_trims_trailing_whitespace() -> None:
    assert rs.collect_sections("## Alpha  \n") == ["Alpha"]


def test_non_level2_headings_ignored() -> None:
    text = "### Sub\n## Top\n# H1\n"
    assert rs.collect_sections(text) == ["Top"]


def test_render_markdown_present() -> None:
    md = rs.render_markdown(rs.check(SIMPLE, required=["Alpha"]))
    assert "_All required sections present._" in md


def test_render_markdown_missing() -> None:
    md = rs.render_markdown(rs.check(SIMPLE, required=["Alpha", "Gamma"]))
    assert "## Missing" in md
    assert "`Gamma`" in md


def _seed(tmp: Path, text: str) -> Path:
    p = tmp / "d.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = _seed(tmp_path, SIMPLE)
    rc = rs.main([
        "--doc", str(doc), "--required", "Alpha,Beta",
        "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["missing"] == 0


def test_cli_md_output(tmp_path: Path) -> None:
    doc = _seed(tmp_path, SIMPLE)
    out = tmp_path / "r.md"
    rc = rs.main([
        "--doc", str(doc), "--required", "Alpha",
        "--output", str(out),
    ])
    assert rc == 0
    assert "runbook section check" in out.read_text(encoding="utf-8")


def test_cli_fail_on_missing_returns_1(tmp_path: Path) -> None:
    doc = _seed(tmp_path, SIMPLE)
    rc = rs.main([
        "--doc", str(doc), "--required", "Alpha,Gamma",
        "--fail-on-missing",
    ])
    assert rc == 1


def test_cli_fail_on_missing_passes_when_clean(tmp_path: Path) -> None:
    doc = _seed(tmp_path, SIMPLE)
    rc = rs.main([
        "--doc", str(doc), "--required", "Alpha,Beta",
        "--fail-on-missing",
    ])
    assert rc == 0


def test_cli_missing_doc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rs.main(["--doc", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "doc not found" in capsys.readouterr().err


def test_real_runbook_satisfies_defaults() -> None:
    doc = REPO / "docs" / "plan_2_8_rollout_runbook.md"
    if not doc.exists():
        pytest.skip("runbook not present")
    rep = rs.check(doc.read_text(encoding="utf-8"))
    assert rep["counts"]["missing"] == 0, rep["missing"]


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_section_check_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 runbook section check" in names
    assert "Upload Plan 2.8 runbook section report" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 runbook section check")
    assert "plan_2_8_runbook_sections.py" in step["run"]
