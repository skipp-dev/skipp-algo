"""Tests for ``scripts/plan_2_8_adr_queue.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_adr_queue.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_adr_queue", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_adr_queue"] = mod
    spec.loader.exec_module(mod)
    return mod


adr = _load()


FIXTURE = """
## Entries

### 2026-04-21 - decision one

**Context.** Context line.

**Decision.** Keep the 3-layer stack.

**Alternatives considered.**

- Something.

**Consequences.** TBD.

**Evidence.** test.py

**Status.** accepted

### 2026-05-01 - decision two

**Decision.** Defer the 4th layer.

**Status.** deferred

### 2026-06-01 - decision three

**Decision.** Replace X with Y.

**Status.** superseded by decision-four
"""


def test_parse_three_entries() -> None:
    entries = adr.parse_decisions(FIXTURE)
    assert [e["slug"] for e in entries] == [
        "decision one", "decision two", "decision three",
    ]


def test_status_extracted() -> None:
    entries = adr.parse_decisions(FIXTURE)
    statuses = [e["status"] for e in entries]
    assert statuses == [
        "accepted", "deferred", "superseded by decision-four",
    ]


def test_decision_summary_extracted() -> None:
    entries = adr.parse_decisions(FIXTURE)
    assert entries[0]["summary"] == "Keep the 3-layer stack."
    assert entries[1]["summary"] == "Defer the 4th layer."


def test_filter_accepted() -> None:
    entries = adr.parse_decisions(FIXTURE)
    accepted = adr.filter_entries(entries, status="accepted")
    assert [e["slug"] for e in accepted] == ["decision one"]


def test_filter_deferred() -> None:
    entries = adr.parse_decisions(FIXTURE)
    deferred = adr.filter_entries(entries, status="deferred")
    assert [e["slug"] for e in deferred] == ["decision two"]


def test_filter_superseded_matches_prefix() -> None:
    entries = adr.parse_decisions(FIXTURE)
    sup = adr.filter_entries(entries, status="superseded")
    assert [e["slug"] for e in sup] == ["decision three"]


def test_filter_none_returns_all() -> None:
    entries = adr.parse_decisions(FIXTURE)
    all_ = adr.filter_entries(entries)
    assert len(all_) == 3


def test_render_markdown_empty_and_populated() -> None:
    empty = adr.render_markdown([])
    assert "No matching ADR entries." in empty
    populated = adr.render_markdown(adr.parse_decisions(FIXTURE))
    assert "| date | slug | status |" in populated
    assert "decision one" in populated


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dec = tmp_path / "DECISIONS.md"
    dec.write_text(FIXTURE, encoding="utf-8")
    rc = adr.main([
        "--decisions", str(dec), "--status", "deferred", "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["filter"] == "deferred"
    assert [e["slug"] for e in payload["entries"]] == ["decision two"]


def test_cli_text_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    dec = tmp_path / "DECISIONS.md"
    dec.write_text(FIXTURE, encoding="utf-8")
    rc = adr.main([
        "--decisions", str(dec), "--format", "text",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "decision one" in out
    assert "### " not in out  # text, not markdown
    assert "| date | slug | status |" not in out


def test_cli_missing_decisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = adr.main(["--decisions", str(tmp_path / "no.md")])
    assert rc == 1
    assert "decisions log not found" in capsys.readouterr().err


def test_cli_output_file(tmp_path: Path) -> None:
    dec = tmp_path / "DECISIONS.md"
    dec.write_text(FIXTURE, encoding="utf-8")
    out = tmp_path / "q.md"
    rc = adr.main([
        "--decisions", str(dec), "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    assert "decision one" in out.read_text(encoding="utf-8")
