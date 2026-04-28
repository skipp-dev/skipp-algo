"""Tests for ``scripts/plan_2_8_digest_catalog_diff.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_catalog_diff.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_digest_catalog_diff", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_catalog_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


cd = _load()


def _cat(known: list[str] | None = None,
         unknown: list[str] | None = None) -> dict[str, Any]:
    return {
        "known":   [{"name": n} for n in (known or [])],
        "unknown": [{"name": n} for n in (unknown or [])],
    }


def test_identical_no_changes() -> None:
    rep = cd.diff(_cat(["a"]), _cat(["a"]))
    assert rep["added_known"] == []
    assert rep["dropped"] == []


def test_added_known() -> None:
    rep = cd.diff(_cat(["a"]), _cat(["a", "b"]))
    assert rep["added_known"] == ["b"]


def test_added_unknown() -> None:
    rep = cd.diff(_cat(["a"]), _cat(["a"], ["z"]))
    assert rep["added_unknown"] == ["z"]


def test_dropped() -> None:
    rep = cd.diff(_cat(["a", "b"]), _cat(["a"]))
    assert rep["dropped"] == ["b"]


def test_known_to_unknown() -> None:
    rep = cd.diff(_cat(["a"]), _cat([], ["a"]))
    assert rep["known_to_unknown"] == ["a"]


def test_unknown_to_known() -> None:
    rep = cd.diff(_cat([], ["a"]), _cat(["a"]))
    assert rep["unknown_to_known"] == ["a"]


def test_malformed_prior_treated_empty(tmp_path: Path) -> None:
    p = tmp_path / "p.json"
    p.write_text("not json", encoding="utf-8")
    c = tmp_path / "c.json"
    c.write_text(json.dumps(_cat(["a"])), encoding="utf-8")
    rc = cd.main(["--prior", str(p), "--current", str(c)])
    assert rc == 0


def test_markdown_shape() -> None:
    md = cd.render_markdown(
        cd.diff(_cat(["a"]), _cat(["a", "b"])),
    )
    assert "artifact catalog diff" in md
    assert "`b`" in md


def test_markdown_empty_sections() -> None:
    md = cd.render_markdown(cd.diff(_cat(["a"]), _cat(["a"])))
    assert "_(none)_" in md


def test_fail_on_unknown_growth(tmp_path: Path) -> None:
    p = tmp_path / "p.json"
    p.write_text(json.dumps(_cat(["a"])), encoding="utf-8")
    c = tmp_path / "c.json"
    c.write_text(json.dumps(_cat(["a"], ["z"])), encoding="utf-8")
    rc = cd.main([
        "--prior", str(p), "--current", str(c),
        "--fail-on-unknown-growth",
    ])
    assert rc == 1


def test_cli_missing_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "p.json"
    p.write_text("{}", encoding="utf-8")
    rc = cd.main([
        "--prior", str(p),
        "--current", str(tmp_path / "nope.json"),
    ])
    assert rc == 1
    assert "current not found" in capsys.readouterr().err


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "p.json"
    p.write_text(json.dumps(_cat(["a"])), encoding="utf-8")
    c = tmp_path / "c.json"
    c.write_text(json.dumps(_cat(["a", "b"])), encoding="utf-8")
    out = tmp_path / "o.json"
    rc = cd.main([
        "--prior", str(p), "--current", str(c),
        "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["added_known"] == ["b"]


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_catalog_diff_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest catalog diff" in names
    assert "Upload Plan 2.8 digest catalog diff" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest catalog diff")
    assert "plan_2_8_digest_catalog_diff.py" in step["run"]
