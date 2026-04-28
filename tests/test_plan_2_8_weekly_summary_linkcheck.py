"""Tests for ``scripts/plan_2_8_weekly_summary_linkcheck.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_linkcheck.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_linkcheck", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_linkcheck"] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load()


def test_all_links_resolve() -> None:
    md = (
        "# Title\n\n"
        "- [Alpha](#alpha)\n\n"
        "## Alpha\n\n"
        "body\n"
    )
    rep = lc.scan(md)
    assert rep["total"] == 1
    assert rep["broken_count"] == 0


def test_broken_link_detected() -> None:
    md = (
        "# Title\n\n"
        "- [Nope](#nope)\n\n"
        "## Alpha\n\n"
    )
    rep = lc.scan(md)
    assert rep["broken_count"] == 1
    assert rep["broken"][0]["slug"] == "nope"


def test_multiple_links_mixed() -> None:
    md = (
        "# T\n\n"
        "- [A](#alpha)\n"
        "- [B](#bravo)\n\n"
        "## Alpha\n\n"
    )
    rep = lc.scan(md)
    assert rep["total"] == 2
    assert rep["broken_count"] == 1


def test_http_links_ignored() -> None:
    md = "[ext](https://example.test)\n## heading\n"
    rep = lc.scan(md)
    assert rep["total"] == 0


def test_slugify_handles_spaces_and_case() -> None:
    md = (
        "# Top\n\n"
        "- [x](#status-flip-alert)\n\n"
        "## Status Flip Alert\n"
    )
    rep = lc.scan(md)
    assert rep["broken_count"] == 0


def test_markdown_shape_has_broken_section() -> None:
    md = "# T\n\n[x](#missing)\n"
    out = lc.render_markdown(lc.scan(md))
    assert "Broken links" in out
    assert "#missing" in out


def test_markdown_shape_clean() -> None:
    md = "# T\n\n[x](#t)\n"
    out = lc.render_markdown(lc.scan(md))
    assert "All links resolve" in out


def test_cli_json(tmp_path: Path) -> None:
    src = tmp_path / "s.md"
    src.write_text("# T\n\n[x](#nope)\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = lc.main([
        "--input", str(src), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["broken_count"] == 1


def test_cli_fail_on_broken(tmp_path: Path) -> None:
    src = tmp_path / "s.md"
    src.write_text("# T\n\n[x](#nope)\n", encoding="utf-8")
    rc = lc.main([
        "--input", str(src), "--fail-on-broken",
    ])
    assert rc == 1


def test_cli_fail_on_broken_clean(tmp_path: Path) -> None:
    src = tmp_path / "s.md"
    src.write_text("# T\n\n[x](#t)\n", encoding="utf-8")
    rc = lc.main([
        "--input", str(src), "--fail-on-broken",
    ])
    assert rc == 0


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lc.main(["--input", str(tmp_path / "nope.md")])
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


def test_weekly_has_linkcheck_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly-summary link check" in names
    assert "Upload Plan 2.8 weekly-summary link check" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly-summary link check")
    assert "plan_2_8_weekly_summary_linkcheck.py" in step["run"]
