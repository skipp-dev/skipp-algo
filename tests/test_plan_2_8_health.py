"""Tests for ``scripts/plan_2_8_health.py`` and batch #65 workflow wires."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_health.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"
MONTHLY = REPO / ".github" / "workflows" / "plan-2-8-monthly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_health", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_health"] = mod
    spec.loader.exec_module(mod)
    return mod


health = _load()


# ---------- core aggregator ------------------------------------------------

def test_all_green_when_inputs_clean() -> None:
    rep = health.assess(
        digest   ={"alerts": []},
        coverage ={"counts": {"under": 0}},
        stability={"counts": {"unstable": 0}},
    )
    assert rep["status"] == "green"
    assert rep["score"] == 1.0
    assert rep["findings"] == []


def test_alerts_alone_drop_to_amber() -> None:
    rep = health.assess(
        digest   ={"alerts": [{"tf": "5m", "family": "HR"}]},
        coverage ={"counts": {"under": 0}},
        stability={"counts": {"unstable": 0}},
    )
    assert rep["status"] == "amber"
    assert rep["score"] == 0.5
    assert "1 drift alert" in rep["findings"][0]


def test_coverage_gap_alone_amber() -> None:
    rep = health.assess(
        digest   ={"alerts": []},
        coverage ={"counts": {"under": 2}},
        stability={"counts": {"unstable": 0}},
    )
    assert rep["status"] == "amber"
    assert rep["score"] == 0.75


def test_all_three_failures_go_red() -> None:
    rep = health.assess(
        digest   ={"alerts": [{}]},
        coverage ={"counts": {"under": 3}},
        stability={"counts": {"unstable": 1}},
    )
    assert rep["status"] == "red"
    assert rep["score"] == 0.0
    assert len(rep["findings"]) == 3


def test_missing_inputs_are_unknown() -> None:
    rep = health.assess(None, None, None)
    assert rep["status"] == "green"
    assert rep["inputs_seen"] == {
        "digest": False, "coverage": False, "stability": False,
    }


def test_signals_reflect_counts() -> None:
    rep = health.assess(
        digest   ={"alerts": [{}, {}, {}]},
        coverage ={"counts": {"under": 5}},
        stability={"counts": {"unstable": 2}},
    )
    assert rep["signals"] == {"alerts": 3, "under": 5, "unstable": 2}


def test_render_markdown_green() -> None:
    rep = health.assess({"alerts": []}, {"counts": {"under": 0}},
                        {"counts": {"unstable": 0}})
    md = health.render_markdown(rep)
    assert "status:_ **green**" in md
    assert "No findings" in md


def test_render_markdown_red_lists_findings() -> None:
    rep = health.assess({"alerts": [{}]}, {"counts": {"under": 1}},
                        {"counts": {"unstable": 1}})
    md = health.render_markdown(rep)
    assert "status:_ **red**" in md
    assert "## Findings" in md
    assert "drift alert" in md


# ---------- CLI -----------------------------------------------------------

def _seed(dir_: Path, data: dict[str, Any], name: str) -> Path:
    p = dir_ / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_cli_json_output_with_all_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    dj = _seed(tmp_path, {"alerts": []}, "digest.json")
    cj = _seed(tmp_path, {"counts": {"under": 0}}, "coverage.json")
    sj = _seed(tmp_path, {"counts": {"unstable": 0}}, "stability.json")
    rc = health.main([
        "--digest", str(dj), "--coverage", str(cj), "--stability", str(sj),
        "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "green"


def test_cli_output_file_and_md_format(tmp_path: Path) -> None:
    dj = _seed(tmp_path, {"alerts": [{}]}, "digest.json")
    out = tmp_path / "health.md"
    rc = health.main([
        "--digest", str(dj), "--format", "md", "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    assert "rollout health" in out.read_text(encoding="utf-8")


def test_cli_fail_on_red(tmp_path: Path) -> None:
    dj = _seed(tmp_path, {"alerts": [{}]}, "digest.json")
    cj = _seed(tmp_path, {"counts": {"under": 1}}, "coverage.json")
    sj = _seed(tmp_path, {"counts": {"unstable": 1}}, "stability.json")
    rc = health.main([
        "--digest", str(dj), "--coverage", str(cj), "--stability", str(sj),
        "--fail-on-red",
    ])
    assert rc == 1


def test_cli_missing_input_tolerated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = health.main(["--format", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "green"
    assert payload["inputs_seen"]["digest"] is False


# ---------- workflow wiring (pin tests) ------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    # yaml1.1 bare-on shim is not needed here; we only read 'jobs'.
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_runcard_step_at_the_end() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Assemble weekly runcard" in names
    assert "Upload weekly runcard" in names
    i_assemble = names.index("Assemble weekly runcard")
    i_upload = names.index("Upload weekly runcard")
    # Upload must come after assemble.
    assert i_assemble < i_upload


def test_weekly_runcard_reads_from_digest_artifacts() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    step = next(s for s in steps if s.get("name") == "Assemble weekly runcard")
    run = step["run"]
    assert "artifacts/plan_2_8_digest" in run
    assert "plan_2_8_weekly_runcard.py" in run
    assert "--run-url" in run


def test_monthly_has_adr_queue_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(MONTHLY)
    steps = wf["jobs"]["monthly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 deferred ADR queue" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 deferred ADR queue")
    run = step["run"]
    assert "plan_2_8_adr_queue.py" in run
    assert "--status    deferred" in run
