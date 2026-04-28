"""Tests for ``scripts/plan_2_8_digest_to_coverage.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_to_coverage.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_to_coverage", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_to_coverage"] = mod
    spec.loader.exec_module(mod)
    return mod


dc = _load()


def _alert(tf: str, fam: str) -> dict[str, Any]:
    return {"tf": tf, "family": fam}


def _digest(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "alerts": [_alert(tf, fam) for tf, fam in pairs],
    }


def test_gap_reported_when_alert_has_no_coverage() -> None:
    rep = dc.project(
        _digest([("5m", "HR")]),
        {"entries": [{"tf": "15m", "family": "FVG"}]},
    )
    assert rep["counts"]["alerts_without_coverage"] == 1
    assert rep["alerts_without_coverage"] == [{"tf": "5m", "family": "HR"}]


def test_coverage_without_alerts_is_informational() -> None:
    rep = dc.project(
        _digest([]),
        {"entries": [{"tf": "15m", "family": "FVG"}]},
    )
    assert rep["counts"]["coverage_without_alerts"] == 1
    assert rep["counts"]["alerts_without_coverage"] == 0


def test_intersection() -> None:
    rep = dc.project(
        _digest([("5m", "HR"), ("15m", "FVG")]),
        {"entries": [
            {"tf": "5m", "family": "HR"},
            {"tf": "5m", "family": "BOS"},
        ]},
    )
    assert rep["counts"]["intersection"] == 1
    assert rep["intersection"] == [{"tf": "5m", "family": "HR"}]


def test_coverage_accepts_bare_list() -> None:
    rep = dc.project(
        _digest([("5m", "HR")]),
        [{"tf": "5m", "family": "HR"}],
    )
    assert rep["counts"]["intersection"] == 1


def test_ignores_non_string_alert_keys() -> None:
    rep = dc.project(
        {"alerts": [
            {"tf": 5, "family": "HR"},
            {"tf": "5m", "family": "HR"},
        ]},
        {"entries": [{"tf": "5m", "family": "HR"}]},
    )
    assert rep["counts"]["intersection"] == 1
    assert rep["counts"]["alerts_without_coverage"] == 0


def test_handles_missing_alerts_key() -> None:
    rep = dc.project({}, {"entries": []})
    assert rep["counts"]["alerts"] == 0
    assert rep["counts"]["coverage"] == 0


def test_handles_non_dict_inputs() -> None:
    rep = dc.project("not a dict", 42)
    assert rep["counts"]["alerts"] == 0
    assert rep["counts"]["coverage"] == 0


def test_render_markdown_sections() -> None:
    rep = dc.project(
        _digest([("5m", "HR")]),
        {"entries": [{"tf": "15m", "family": "FVG"}]},
    )
    md = dc.render_markdown(rep)
    assert "## Alerts without coverage (1)" in md
    assert "## Coverage without alerts (1)" in md
    assert "5m" in md and "15m" in md


def test_render_markdown_empty_sections() -> None:
    md = dc.render_markdown(dc.project({}, {"entries": []}))
    assert "_none_" in md


def _seed(tmp: Path, name: str, payload: Any) -> Path:
    p = tmp / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = _seed(tmp_path, "d.json", _digest([("5m", "HR")]))
    c = _seed(tmp_path, "c.json", {"entries": [{"tf": "5m", "family": "HR"}]})
    rc = dc.main([
        "--digest", str(d), "--coverage", str(c), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["intersection"] == 1


def test_cli_md_output(tmp_path: Path) -> None:
    d = _seed(tmp_path, "d.json", _digest([("5m", "HR")]))
    c = _seed(tmp_path, "c.json", {"entries": []})
    out = tmp_path / "r.md"
    rc = dc.main([
        "--digest", str(d), "--coverage", str(c), "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 digest vs coverage" in out.read_text(encoding="utf-8")


def test_cli_fail_on_gap_returns_1(tmp_path: Path) -> None:
    d = _seed(tmp_path, "d.json", _digest([("5m", "HR")]))
    c = _seed(tmp_path, "c.json", {"entries": []})
    rc = dc.main([
        "--digest", str(d), "--coverage", str(c), "--fail-on-gap",
    ])
    assert rc == 1


def test_cli_fail_on_gap_passes_when_clean(tmp_path: Path) -> None:
    d = _seed(tmp_path, "d.json", _digest([("5m", "HR")]))
    c = _seed(tmp_path, "c.json", {"entries": [{"tf": "5m", "family": "HR"}]})
    rc = dc.main([
        "--digest", str(d), "--coverage", str(c), "--fail-on-gap",
    ])
    assert rc == 0


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    d = _seed(tmp_path, "d.json", _digest([]))
    rc = dc.main([
        "--digest", str(d), "--coverage", str(tmp_path / "nope.json"),
    ])
    assert rc == 1
    assert "input not found" in capsys.readouterr().err


def test_cli_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    c = _seed(tmp_path, "c.json", {"entries": []})
    rc = dc.main([
        "--digest", str(bad), "--coverage", str(c),
    ])
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_digest_vs_coverage_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest vs coverage projection" in names
    assert "Upload Plan 2.8 digest vs coverage" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest vs coverage projection")
    assert "plan_2_8_digest_to_coverage.py" in step["run"]
