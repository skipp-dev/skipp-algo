"""Tests for ``scripts/plan_2_8_runbook_toc.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_runbook_toc.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_runbook_toc", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_runbook_toc"] = mod
    spec.loader.exec_module(mod)
    return mod


toc = _load()


DOC = """\
# Title

## Section A

Intro A.

### Sub A1

body

### Sub A2

body

## Section B

```
### Code inside fence should be ignored
```

### Sub B1 With Symbols!
"""


def test_slug_basic() -> None:
    assert toc._slug("Hello World") == "hello-world"
    assert toc._slug("  Mixed  Spaces  ") == "mixed-spaces"
    assert toc._slug("Sym!bols@") == "symbols"
    assert toc._slug("A -- B") == "a-b"


def test_parse_toc_levels() -> None:
    entries = toc.parse_toc(DOC)
    levels = [(e["level"], e["title"]) for e in entries]
    assert (2, "Section A") in levels
    assert (3, "Sub A1") in levels
    assert (3, "Sub B1 With Symbols!") in levels


def test_code_fence_ignored() -> None:
    entries = toc.parse_toc(DOC)
    titles = [e["title"] for e in entries]
    assert "Code inside fence should be ignored" not in titles


def test_duplicate_slug_gets_suffix() -> None:
    body = "## A\n\n## A\n\n## A\n"
    entries = toc.parse_toc(body)
    assert [e["anchor"] for e in entries] == ["a", "a-1", "a-2"]


def test_render_markdown_indent() -> None:
    entries = toc.parse_toc(DOC)
    md = toc.render_markdown(entries, min_level=2, max_level=3)
    assert "- [Section A](#section-a)" in md
    assert "  - [Sub A1](#sub-a1)" in md


def test_render_markdown_range_filter() -> None:
    entries = toc.parse_toc(DOC)
    md = toc.render_markdown(entries, min_level=2, max_level=2)
    assert "Sub A1" not in md
    assert "Section A" in md


def test_render_markdown_empty() -> None:
    md = toc.render_markdown([])
    assert "No headings" in md


def test_cli_md_output(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(DOC, encoding="utf-8")
    out = tmp_path / "toc.md"
    rc = toc.main([
        "--doc", str(doc), "--output", str(out),
    ])
    assert rc == 0
    assert "Section A" in out.read_text(encoding="utf-8")


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(DOC, encoding="utf-8")
    rc = toc.main([
        "--doc", str(doc), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(e["title"] == "Section A" for e in payload["entries"])


def test_cli_missing_doc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = toc.main(["--doc", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "doc not found" in capsys.readouterr().err
