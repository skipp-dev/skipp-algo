"""Tests for ``scripts/append_adr.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "append_adr.py"


def _load():
    spec = importlib.util.spec_from_file_location("append_adr", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["append_adr"] = mod
    spec.loader.exec_module(mod)
    return mod


adr = _load()


# ---- render_entry --------------------------------------------------------- #

def test_render_entry_has_all_required_subsections() -> None:
    out = adr.render_entry(
        date="2026-07-14", slug="sample",
        context="ctx.", decision="do X.",
        alternatives="- A: because.", consequences="none.",
        evidence="evidence.md", status="accepted",
    )
    for label in (
        "**Context.**", "**Decision.**", "**Alternatives considered.**",
        "**Consequences.**", "**Evidence.**", "**Status.**",
    ):
        assert label in out


def test_render_entry_header_has_date_and_slug() -> None:
    out = adr.render_entry(
        date="2026-07-14", slug="reject 2H layer",
        context="", decision="D", alternatives="", consequences="",
        evidence="", status="accepted",
    )
    assert out.splitlines()[0] == "### 2026-07-14 - reject 2H layer"


def test_render_entry_rejects_bad_date() -> None:
    with pytest.raises(ValueError, match="date must be YYYY-MM-DD"):
        adr.render_entry(
            date="14.07.2026", slug="x", context="", decision="d",
            alternatives="", consequences="", evidence="", status="accepted",
        )


def test_render_entry_rejects_empty_slug_and_decision() -> None:
    with pytest.raises(ValueError, match="slug"):
        adr.render_entry(
            date="2026-07-14", slug="", context="", decision="d",
            alternatives="", consequences="", evidence="", status="accepted",
        )
    with pytest.raises(ValueError, match="decision"):
        adr.render_entry(
            date="2026-07-14", slug="x", context="", decision="",
            alternatives="", consequences="", evidence="", status="accepted",
        )


def test_render_entry_status_whitelist() -> None:
    with pytest.raises(ValueError, match="status must be"):
        adr.render_entry(
            date="2026-07-14", slug="x", context="", decision="d",
            alternatives="", consequences="", evidence="", status="pending",
        )
    # Accepted shapes:
    for s in ("accepted", "deferred", "superseded by other-slug"):
        adr.render_entry(
            date="2026-07-14", slug="x", context="", decision="d",
            alternatives="", consequences="", evidence="", status=s,
        )


def test_render_entry_alternatives_placeholder_when_empty() -> None:
    out = adr.render_entry(
        date="2026-07-14", slug="x", context="", decision="d",
        alternatives="", consequences="", evidence="", status="accepted",
    )
    assert "- _none recorded_" in out


# ---- append_entry --------------------------------------------------------- #

def _scaffold(tmp_path: Path) -> Path:
    p = tmp_path / "DECISIONS.md"
    p.write_text("# Architectural Decisions\n\n## Entries\n\n", encoding="utf-8")
    return p


def test_append_entry_adds_after_existing_content(tmp_path: Path) -> None:
    path = _scaffold(tmp_path)
    entry = adr.render_entry(
        date="2026-07-14", slug="first", context="", decision="d",
        alternatives="", consequences="", evidence="", status="accepted",
    )
    adr.append_entry(path, entry)
    text = path.read_text(encoding="utf-8")
    assert "### 2026-07-14 - first" in text
    # Second append should not overwrite.
    entry2 = adr.render_entry(
        date="2026-07-15", slug="second", context="", decision="d",
        alternatives="", consequences="", evidence="", status="accepted",
    )
    adr.append_entry(path, entry2)
    text = path.read_text(encoding="utf-8")
    assert "### 2026-07-14 - first" in text
    assert "### 2026-07-15 - second" in text
    # Ordering preserved.
    assert text.index("first") < text.index("second")


def test_append_entry_requires_entries_header(tmp_path: Path) -> None:
    path = tmp_path / "DECISIONS.md"
    path.write_text("# Architectural Decisions\n", encoding="utf-8")
    with pytest.raises(ValueError, match="'## Entries' section"):
        adr.append_entry(path, "### 2026-07-14 - x\n")


# ---- CLI ------------------------------------------------------------------ #

def test_cli_dry_run_prints_entry_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = _scaffold(tmp_path)
    before = path.read_text(encoding="utf-8")
    rc = adr.main([
        "--decisions", str(path),
        "--slug", "try-me",
        "--date", "2026-07-14",
        "--decision", "do it",
        "--dry-run",
    ])
    assert rc == 0
    assert path.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "### 2026-07-14 - try-me" in out


def test_cli_writes_to_file(tmp_path: Path) -> None:
    path = _scaffold(tmp_path)
    rc = adr.main([
        "--decisions", str(path),
        "--slug", "written",
        "--date", "2026-07-14",
        "--decision", "do it",
    ])
    assert rc == 0
    assert "### 2026-07-14 - written" in path.read_text(encoding="utf-8")


def test_cli_error_exits_non_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = _scaffold(tmp_path)
    rc = adr.main([
        "--decisions", str(path),
        "--slug", "x",
        "--date", "bogus",
        "--decision", "d",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "date must be YYYY-MM-DD" in err
