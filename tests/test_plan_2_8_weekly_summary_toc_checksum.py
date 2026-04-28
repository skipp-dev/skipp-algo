"""Tests for ``scripts/plan_2_8_weekly_summary_toc_checksum.py``."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_weekly_summary_toc_checksum.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_weekly_summary_toc_checksum", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_weekly_summary_toc_checksum"] = mod
    spec.loader.exec_module(mod)
    return mod


tc = _load()


def test_missing_toc_returns_empty() -> None:
    rep = tc.compute("# Title\n\nbody\n")
    assert rep["present"] is False
    assert rep["sha256"] == ""


def test_extracts_between_h2s() -> None:
    text = (
        "# Title\n\n## Contents\n- [A](#a)\n- [B](#b)\n\n## A\nx\n"
    )
    assert tc.extract(text) == "- [A](#a)\n- [B](#b)"


def test_same_block_same_checksum() -> None:
    t1 = "## Contents\n- a\n\n## Next\n"
    t2 = "## Contents\n- a\n\n## Other\n"
    assert tc.compute(t1)["sha256"] == tc.compute(t2)["sha256"]


def test_different_block_different_checksum() -> None:
    t1 = "## Contents\n- a\n"
    t2 = "## Contents\n- b\n"
    assert tc.compute(t1)["sha256"] != tc.compute(t2)["sha256"]


def test_trailing_whitespace_normalised() -> None:
    t1 = "## Contents\n- a   \n"
    t2 = "## Contents\n- a\n"
    assert tc.compute(t1)["sha256"] == tc.compute(t2)["sha256"]


def test_leading_and_trailing_blank_lines_stripped() -> None:
    t1 = "## Contents\n\n\n- a\n\n\n"
    t2 = "## Contents\n- a\n"
    assert tc.compute(t1)["sha256"] == tc.compute(t2)["sha256"]


def test_lines_count() -> None:
    rep = tc.compute("## Contents\n- a\n- b\n\n## Next\n")
    assert rep["lines"] == 2


def test_sha256_is_stable_hash() -> None:
    rep = tc.compute("## Contents\n- a\n")
    expected = hashlib.sha256(b"- a").hexdigest()
    assert rep["sha256"] == expected


def test_markdown_shape() -> None:
    md = tc.render_markdown(tc.compute("## Contents\n- a\n"))
    assert "TOC checksum" in md


def test_cli_fail_on_missing(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text("# Title\nbody\n", encoding="utf-8")
    rc = tc.main([
        "--input", str(p), "--fail-on-missing",
    ])
    assert rc == 1


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "w.md"
    p.write_text("## Contents\n- a\n", encoding="utf-8")
    out = tmp_path / "o.json"
    rc = tc.main([
        "--input", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["present"] is True


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = tc.main(["--input", str(tmp_path / "nope.md")])
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


def test_weekly_has_toc_checksum_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 weekly summary TOC checksum" in names
    assert "Upload Plan 2.8 weekly summary TOC checksum" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 weekly summary TOC checksum")
    assert "plan_2_8_weekly_summary_toc_checksum.py" in step["run"]
