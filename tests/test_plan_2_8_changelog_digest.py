"""Tests for ``scripts/plan_2_8_changelog_digest.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_changelog_digest.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_changelog_digest", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_changelog_digest"] = mod
    spec.loader.exec_module(mod)
    return mod


cl = _load()


FIXTURE = """\
# CHANGELOG

## [Unreleased]

### Added (2026-04-21) - third item

body three line one
body three line two

### Added (2026-04-14) - second item

body two

### Fixed (2026-04-01) - first item

body one

## [0.1.0] - 2026-03-01

### Added (2026-03-01) - old item

ancient body
"""


def test_parse_all_four_entries() -> None:
    entries = cl.parse_changelog(FIXTURE)
    assert [e["title"] for e in entries] == [
        "third item", "second item", "first item", "old item",
    ]
    assert [e["kind"] for e in entries] == [
        "Added", "Added", "Fixed", "Added",
    ]


def test_parse_captures_body() -> None:
    entries = cl.parse_changelog(FIXTURE)
    assert "body three line one" in entries[0]["body"]
    assert "body three line two" in entries[0]["body"]


def test_parse_supports_em_dash_separator() -> None:
    alt = "### Added (2026-04-21) \u2014 em-dash title\n\nbody\n"
    entries = cl.parse_changelog(alt)
    assert entries and entries[0]["title"] == "em-dash title"


def test_filter_lookback_days() -> None:
    entries = cl.parse_changelog(FIXTURE)
    kept = cl.filter_entries(
        entries,
        lookback_days=14,
        now=_dt.date(2026, 4, 22),
    )
    titles = [e["title"] for e in kept]
    assert "third item" in titles
    assert "second item" in titles
    assert "first item" not in titles
    assert "old item" not in titles


def test_filter_limit_and_sort_desc() -> None:
    entries = cl.parse_changelog(FIXTURE)
    kept = cl.filter_entries(entries, limit=2)
    assert [e["title"] for e in kept] == ["third item", "second item"]


def test_render_markdown_empty() -> None:
    md = cl.render_markdown([])
    assert "No matching CHANGELOG entries" in md


def test_render_markdown_populated_has_headings() -> None:
    entries = cl.parse_changelog(FIXTURE)
    md = cl.render_markdown(entries[:2], window_label="last 14 days")
    assert "(last 14 days)" in md
    assert "## 2026-04-21 - third item" in md
    assert "_Added_" in md


def test_cli_json_with_lookback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ch = tmp_path / "CHANGELOG.md"
    ch.write_text(FIXTURE, encoding="utf-8")
    rc = cl.main([
        "--changelog", str(ch),
        "--lookback-days", "365",
        "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["filter"]["lookback_days"] == 365
    assert len(payload["entries"]) >= 1


def test_cli_md_output_file(tmp_path: Path) -> None:
    ch = tmp_path / "CHANGELOG.md"
    ch.write_text(FIXTURE, encoding="utf-8")
    out = tmp_path / "recent.md"
    rc = cl.main([
        "--changelog", str(ch), "--limit", "1", "--output", str(out),
    ])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "third item" in text
    assert "second item" not in text


def test_cli_missing_changelog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cl.main(["--changelog", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "changelog not found" in capsys.readouterr().err
