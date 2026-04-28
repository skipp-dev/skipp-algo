"""Tests for ``scripts/plan_2_8_runcard_badge.py`` + #74 wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_runcard_badge.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_runcard_badge", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_runcard_badge"] = mod
    spec.loader.exec_module(mod)
    return mod


rb = _load()


def test_green_status_maps_to_brightgreen() -> None:
    badge = rb.build({"status": "green"})
    assert badge == {
        "schemaVersion": 1,
        "label":   "plan 2.8",
        "message": "green",
        "color":   "brightgreen",
    }


def test_amber_maps_to_yellow() -> None:
    badge = rb.build({"status": "amber"})
    assert badge["color"] == "yellow"
    assert badge["message"] == "amber"


def test_red_maps_to_red() -> None:
    badge = rb.build({"status": "red"})
    assert badge["color"] == "red"


def test_unknown_status_falls_back_to_lightgrey() -> None:
    badge = rb.build({"status": "weird"})
    assert badge["color"] == "lightgrey"
    assert badge["message"] == "weird"


def test_uppercase_status_normalised() -> None:
    badge = rb.build({"status": "GREEN"})
    assert badge["message"] == "green"
    assert badge["color"] == "brightgreen"


def test_missing_status_uses_rollup_fallback() -> None:
    badge = rb.build({"rollup": "amber"})
    assert badge["message"] == "amber"
    assert badge["color"] == "yellow"


def test_no_status_no_rollup_becomes_unknown() -> None:
    badge = rb.build({})
    assert badge["message"] == "unknown"
    assert badge["color"] == "lightgrey"


def test_non_dict_payload_becomes_unknown() -> None:
    badge = rb.build(["not-a-dict"])
    assert badge["message"] == "unknown"
    assert badge["color"] == "lightgrey"


def test_custom_label() -> None:
    badge = rb.build({"status": "green"}, label="plan 2.8 weekly")
    assert badge["label"] == "plan 2.8 weekly"


def _seed(tmp: Path, payload: Any) -> Path:
    p = tmp / "in.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_cli_prints_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = _seed(tmp_path, {"status": "green"})
    rc = rb.main(["--input", str(p)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schemaVersion"] == 1
    assert payload["color"] == "brightgreen"


def test_cli_writes_output(tmp_path: Path) -> None:
    p = _seed(tmp_path, {"status": "red"})
    out = tmp_path / "badge.json"
    rc = rb.main(["--input", str(p), "--output", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["color"] == "red"


def test_cli_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = rb.main(["--input", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "input not found" in capsys.readouterr().err


def test_cli_bad_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not-json", encoding="utf-8")
    rc = rb.main(["--input", str(p)])
    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_status_badge_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 shields.io status badge" in names
    assert "Upload Plan 2.8 status badge" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 shields.io status badge")
    assert "plan_2_8_runcard_badge.py" in step["run"]
