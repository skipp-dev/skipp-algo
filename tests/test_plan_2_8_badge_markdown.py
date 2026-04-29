"""Tests for ``scripts/plan_2_8_badge_markdown.py``."""

from __future__ import annotations

import importlib.util
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_badge_markdown.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_badge_markdown", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_badge_markdown"] = mod
    spec.loader.exec_module(mod)
    return mod


bm = _load()


def test_render_basic() -> None:
    url = "https://example.com/badge.json"
    md = bm.render(url)
    # single markdown image line
    assert md.startswith("![plan 2.8](https://img.shields.io/endpoint?url=")
    assert md.endswith(")\n")
    # endpoint URL is fully URL-encoded (colons, slashes, dots escaped)
    assert urllib.parse.quote(url, safe="") in md


def test_render_custom_label() -> None:
    md = bm.render("https://x/y.json", label="plan 2.8 weekly")
    assert md.startswith("![plan 2.8 weekly](")


def test_render_with_link() -> None:
    md = bm.render(
        "https://x/y.json",
        label="plan 2.8",
        link_url="https://github.com/owner/repo",
    )
    assert md.startswith("[![plan 2.8](")
    assert md.rstrip().endswith(")](https://github.com/owner/repo)")


def test_render_strips_closing_bracket_from_label() -> None:
    md = bm.render("https://x/y.json", label="bad]label")
    assert "![badlabel]" in md


def test_render_rejects_empty_endpoint() -> None:
    with pytest.raises(ValueError):
        bm.render("")


def test_render_rejects_non_string_endpoint() -> None:
    with pytest.raises(ValueError):
        bm.render(None)  # type: ignore[arg-type]


def test_cli_prints_line(capsys: pytest.CaptureFixture[str]) -> None:
    rc = bm.main([
        "--endpoint-url", "https://example.com/badge.json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "img.shields.io/endpoint?url=" in out
    assert out.count("\n") == 1  # single trailing newline


def test_cli_writes_output(tmp_path: Path) -> None:
    out = tmp_path / "badge.md"
    rc = bm.main([
        "--endpoint-url", "https://example.com/badge.json",
        "--output", str(out),
    ])
    assert rc == 0
    assert "img.shields.io/endpoint?url=" in out.read_text(encoding="utf-8")


def test_cli_link_url(capsys: pytest.CaptureFixture[str]) -> None:
    rc = bm.main([
        "--endpoint-url", "https://example.com/badge.json",
        "--link-url",     "https://github.com/owner/repo",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("[![plan 2.8](")
    assert "github.com/owner/repo" in out


def test_cli_rejects_empty_endpoint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = bm.main(["--endpoint-url", ""])
    assert rc == 1
    assert "endpoint_url" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_badge_markdown_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 README badge markdown" in names
    assert "Upload Plan 2.8 README badge markdown" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 README badge markdown")
    assert "plan_2_8_badge_markdown.py" in step["run"]
    assert "GITHUB_REPOSITORY" in step["run"]
