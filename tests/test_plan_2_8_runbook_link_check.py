"""Tests for ``scripts/plan_2_8_runbook_link_check.py`` + #71 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_runbook_link_check.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_runbook_link_check", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_runbook_link_check"] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load()


GOOD = """\
## Section A

See [Section B](#section-b).

## Section B

Back to [Section A](#section-a).
"""

BROKEN = """\
## Section A

Link to [Missing](#missing-section).
Link to [External](https://example.com) should be ignored.
Cross-file link [file](other.md#something) should be ignored.

### Sub B1
"""

FENCED = """\
## Real heading

```
## Fake heading in fence
[link](#real-heading)
```

Outside: [real](#real-heading)
"""

DUP = """\
## Same

[first](#same)

## Same

[second](#same-1)
"""


def test_good_doc_no_broken() -> None:
    rep = lc.check(GOOD)
    assert rep["counts"]["broken"] == 0
    assert rep["counts"]["links"] == 2
    assert rep["counts"]["anchors"] == 2


def test_broken_anchor_detected() -> None:
    rep = lc.check(BROKEN)
    assert rep["counts"]["broken"] == 1
    assert rep["broken"][0]["anchor"] == "missing-section"


def test_external_links_ignored() -> None:
    rep = lc.check(BROKEN)
    # External http(s) link and cross-file link must not be counted.
    assert rep["counts"]["links"] == 1


def test_fenced_headings_and_links_skipped() -> None:
    rep = lc.check(FENCED)
    assert "real-heading" in lc.collect_anchors(FENCED)
    assert "fake-heading-in-fence" not in lc.collect_anchors(FENCED)
    # Only the outside link counts.
    assert rep["counts"]["links"] == 1
    assert rep["counts"]["broken"] == 0


def test_duplicate_slugs_disambiguated() -> None:
    rep = lc.check(DUP)
    assert rep["counts"]["anchors"] == 2
    assert rep["counts"]["broken"] == 0


def test_render_markdown_empty_broken() -> None:
    md = lc.render_markdown(lc.check(GOOD))
    assert "All intra-doc links resolve." in md


def test_render_markdown_broken_table() -> None:
    md = lc.render_markdown(lc.check(BROKEN))
    assert "## Broken links" in md
    assert "missing-section" in md


def test_cli_md_output(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    doc.write_text(GOOD, encoding="utf-8")
    out = tmp_path / "check.md"
    rc = lc.main([
        "--doc", str(doc), "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 runbook link check" in out.read_text(encoding="utf-8")


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = tmp_path / "d.md"
    doc.write_text(BROKEN, encoding="utf-8")
    rc = lc.main([
        "--doc", str(doc), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["broken"] == 1


def test_cli_fail_on_broken_returns_1(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    doc.write_text(BROKEN, encoding="utf-8")
    rc = lc.main([
        "--doc", str(doc), "--fail-on-broken",
    ])
    assert rc == 1


def test_cli_fail_on_broken_returns_0_when_clean(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    doc.write_text(GOOD, encoding="utf-8")
    rc = lc.main([
        "--doc", str(doc), "--fail-on-broken",
    ])
    assert rc == 0


def test_cli_missing_doc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lc.main(["--doc", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "doc not found" in capsys.readouterr().err


def test_real_runbook_has_no_broken_links() -> None:
    doc = REPO / "docs" / "plan_2_8_rollout_runbook.md"
    if not doc.exists():
        pytest.skip("runbook not present")
    rep = lc.check(doc.read_text(encoding="utf-8"))
    assert rep["counts"]["broken"] == 0, rep["broken"]


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_compact_status_runcard_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 compact status runcard" in names
    assert "Upload Plan 2.8 status runcard" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 compact status runcard")
    assert "plan_2_8_runcard_from_status.py" in step["run"]
    assert "status_runcard.md" in step["run"]
